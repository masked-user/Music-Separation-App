FROM xserrat/facebook-demucs:latest

# Install additional dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Install necessary Python libraries
RUN pip install --no-cache-dir redis minio requests jsonpickle torchaudio diffq

# Set up the working directory and create log directory
WORKDIR /app
RUN mkdir -p /app/logs /tmp && chmod 777 /app/logs /tmp

# Copy the worker server script
COPY worker-server.py /app/worker-server.py

# Override ENTRYPOINT to start worker-server.py directly
ENTRYPOINT ["python3", "/app/worker-server.py"]
