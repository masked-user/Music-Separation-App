import os
import redis
import jsonpickle
import requests
from minio import Minio
import logging
import time
import subprocess

# Configure logging to provide more detailed insight
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Redis and MinIO connection configurations
redis_host = os.getenv("REDIS_HOST", "redis")
redis_port = int(os.getenv("REDIS_PORT", 6379))
minio_host = os.getenv("MINIO_HOST", "minio-proj.minio-ns.svc.cluster.local:9000")
minio_access_key = os.getenv("MINIO_ACCESS_KEY", "rootuser")
minio_secret_key = os.getenv("MINIO_SECRET_KEY", "rootpass123")

# Initialize Redis and MinIO clients
try:
    redis_client = redis.StrictRedis(host=redis_host, port=redis_port, db=0, socket_connect_timeout=10)
    redis_client.ping()  # Test connection to Redis
    logging.info("Connected to Redis successfully.")
except redis.ConnectionError as e:
    logging.error(f"Failed to connect to Redis: {e}")
    exit(1)

try:
    minio_client = Minio(
        minio_host,
        access_key=minio_access_key,
        secret_key=minio_secret_key,
        secure=False
    )
    # Ensure MinIO output bucket exists
    output_bucket = "output"
    if not minio_client.bucket_exists(output_bucket):
        minio_client.make_bucket(output_bucket)
    logging.info("Connected to MinIO and ensured output bucket.")
except Exception as e:
    logging.error(f"Failed to connect to MinIO or create bucket: {e}")
    exit(1)

# Function to handle song processing
def process_song(songhash, callback):
    input_path = f"/tmp/{songhash}.mp3"
    output_path = f"/tmp/output/{songhash}"

    # Download song from MinIO
    try:
        minio_client.fget_object("demucs-bucket", f"{songhash}.mp3", input_path)
        logging.info(f"Downloaded {songhash}.mp3 from MinIO.")
    except Exception as e:
        logging.error(f"Failed to download song from MinIO: {e}")
        return

    # Run DEMUCS for separation
    try:
        os.makedirs(output_path, exist_ok=True)
        demucs_command = f"demucs -o {output_path} -n mdx_extra_q --mp3 {input_path}"
        subprocess.run(demucs_command, shell=True, check=True)
        logging.info(f"DEMUCS separation completed for {songhash}.")
    except subprocess.CalledProcessError as e:
        logging.error(f"DEMUCS processing failed: {e}")
        return

    # Upload separated tracks to MinIO
    separated_folder = os.path.join(output_path, "mdx_extra_q", songhash)
    for track in ['bass', 'drums', 'vocals', 'other']:
        track_file = f"{separated_folder}/{track}.mp3"
        if os.path.exists(track_file):
            try:
                minio_client.fput_object(output_bucket, f"{songhash}-{track}.mp3", track_file)
                logging.info(f"Uploaded {track}.mp3 for {songhash} to MinIO.")
            except Exception as e:
                logging.error(f"Failed to upload {track}.mp3 to MinIO: {e}")
        else:
            logging.warning(f"{track}.mp3 for {songhash} not found.")

    # Send callback if specified
    if callback:
        try:
            requests.post(callback['url'], json=callback['data'])
            logging.info(f"Callback sent for {songhash}.")
        except requests.RequestException as e:
            logging.error(f"Callback failed for {songhash}: {e}")

# Main worker loop to process tasks
print("Worker started and waiting for tasks...")

while True:
    try:
        # Check Redis queue for tasks, with a timeout to allow for periodic checks
        task_data = redis_client.blpop("toWorker", timeout=60)
        if task_data:
            logging.info(f"Task received: {task_data}")
            task = jsonpickle.decode(task_data[1])
            songhash = task['songhash']
            callback = task.get("callback", None)

            # Process the song
            process_song(songhash, callback)
        else:
            logging.info("No tasks found. Worker is waiting...")
    except redis.ConnectionError as e:
        logging.error(f"Redis connection lost: {e}. Reconnecting...")
        time.sleep(5)  # Wait before retrying
        continue
    except Exception as e:
        logging.error(f"Unexpected error in worker loop: {e}")
        time.sleep(5)

    # Periodic logging to indicate active status and prevent busy-waiting
    time.sleep(5)
