import os
import redis
import jsonpickle
import hashlib
import requests
from minio import Minio
from io import BytesIO
import subprocess
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Redis setup
redis_host = os.getenv("REDIS_HOST", "localhost")
redis_port = int(os.getenv("REDIS_PORT", 6379))
redis_client = redis.StrictRedis(host=redis_host, port=redis_port, db=0)

# MinIO setup
minio_host = os.getenv("MINIO_HOST", "localhost:9000")
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

# Ensure output bucket exists
if not minio_client.bucket_exists(output_bucket):
    minio_client.make_bucket(output_bucket)

def process_song(songhash, callback):
    input_path = f"/tmp/{songhash}.mp3"
    output_path = f"/tmp/output/{songhash}"

    # Download the song from MinIO
    minio_client.fget_object(input_bucket, f"{songhash}.mp3", input_path)
    logging.info(f"Downloaded {songhash}.mp3 from MinIO")

    # Run DEMUCS for separation using the specified model
    os.makedirs(output_path, exist_ok=True)
    demucs_command = f"demucs -o {output_path} -n mdx_extra_q --mp3 {input_path}"
    subprocess.run(demucs_command, shell=True)
    logging.info(f"DEMUCS separation completed for {songhash}")

    # Upload separated tracks to MinIO
    separated_folder = os.path.join(output_path, "mdx_extra_q", songhash)
    for track in ['bass', 'drums', 'vocals', 'other']:
        track_file = f"{separated_folder}/{track}.mp3"
        if os.path.exists(track_file):
            minio_client.fput_object(output_bucket, f"{songhash}-{track}.mp3", track_file)
            logging.info(f"Uploaded {track}.mp3 for {songhash} to MinIO")
        else:
            logging.warning(f"{track}.mp3 for {songhash} not found")

    # Send callback if specified
    if callback:
        try:
            requests.post(callback['url'], json=callback['data'])
            logging.info(f"Callback sent for {songhash}")
        except Exception as e:
            logging.error(f"Callback failed for {songhash}: {e}")

print("Worker started and waiting for tasks...")

while True:
    task_data = redis_client.blpop("toWorker")
    if task_data:
        logging.info(f"Task received: {task_data}")
        task = jsonpickle.decode(task_data[1])
        songhash = task['songhash']
        callback = task.get("callback", None)

        # Process the song
        process_song(songhash, callback)
