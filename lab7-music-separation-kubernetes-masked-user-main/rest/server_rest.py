from flask import Flask, request, jsonify, send_file
import os
import redis
import jsonpickle
import base64
import hashlib
from minio import Minio
from io import BytesIO

app = Flask(__name__)

# Redis setup
redis_host = os.getenv("REDIS_HOST", "redis")
redis_port = int(os.getenv("REDIS_PORT", 6379))
redis_client = redis.StrictRedis(host=redis_host, port=redis_port, db=0)

# MinIO setup
minio_host = os.getenv("MINIO_HOST", "minio-proj.minio-ns.svc.cluster.local:9000")
minio_access_key = os.getenv("MINIO_ACCESS_KEY", "rootuser")
minio_secret_key = os.getenv("MINIO_SECRET_KEY", "rootpass123")
minio_client = Minio(
    minio_host,
    access_key=minio_access_key,
    secret_key=minio_secret_key,
    secure=False
)

# Define buckets
input_bucket = "demucs-bucket"
output_bucket = "output"

# Ensure MinIO buckets exist
if not minio_client.bucket_exists(input_bucket):
    minio_client.make_bucket(input_bucket)
if not minio_client.bucket_exists(output_bucket):
    minio_client.make_bucket(output_bucket)

# Endpoint to enqueue a song for processing
@app.route('/apiv1/separate', methods=['POST'])
def separate():
    data = request.json
    mp3_data = base64.b64decode(data['mp3'])
    song_hash = hashlib.sha256(mp3_data).hexdigest()

    # Upload MP3 to MinIO input bucket
    minio_client.put_object(input_bucket, f"{song_hash}.mp3", BytesIO(mp3_data), length=len(mp3_data))

    # Queue the job in Redis
    job_data = jsonpickle.encode({
        "songhash": song_hash,
        "callback": data.get("callback", None)
    })
    redis_client.lpush("toWorker", job_data)

    return jsonify({"hash": song_hash, "reason": "Song enqueued for separation"})

# Endpoint to view the job queue
@app.route('/apiv1/queue', methods=['GET'])
def view_queue():
    queue = redis_client.lrange("toWorker", 0, -1)
    # Decode bytes to strings before deserializing with jsonpickle
    queue_list = [jsonpickle.decode(item.decode('utf-8')) for item in queue]
    return jsonify({"queue": queue_list})

# Endpoint to retrieve a separated track
@app.route('/apiv1/track/<songhash>/<track>', methods=['GET'])
def get_track(songhash, track):
    try:
        track_object = minio_client.get_object(output_bucket, f"{songhash}-{track}.mp3")
        return send_file(BytesIO(track_object.read()), mimetype="audio/mpeg", as_attachment=True, download_name=f"{track}.mp3")
    except Exception as e:
        return jsonify({"error": str(e)}), 404

# Endpoint to delete a separated track
@app.route('/apiv1/remove/<songhash>/<track>', methods=['DELETE'])
def delete_track(songhash, track):
    try:
        minio_client.remove_object(output_bucket, f"{songhash}-{track}.mp3")
        return jsonify({"status": "deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 404

# Health check route
@app.route('/', methods=['GET'])
def home():
    return '<h1>Music Separation Server</h1><p>Use a valid endpoint.</p>'

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000)
