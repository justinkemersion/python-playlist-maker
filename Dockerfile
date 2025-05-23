# Stage 1: Build stage (if you had complex build steps, not strictly necessary here but good practice)
# For now, we'll keep it simple.

# Use a slim Python base image. Adjust Python version as needed.
# python:3.11-slim-bookworm is a good modern choice.
FROM python:3.11-slim-bookworm AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies
# - ffmpeg is for yt-dlp (and potentially other audio/video processing)
# - git might be needed if any of your pip requirements are git repositories
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
# --no-cache-dir reduces image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
# Copy the package
COPY playlist_maker/ ./playlist_maker/
# Copy the CLI entrypoint
COPY run_cli.py .

# Copy the default configuration file.
# Users can override this by mounting their own config.
COPY playlist_maker.conf .

# Create the data directory. This will be a mount point for user data.
RUN mkdir data

# Expose data directory as a volume (optional, but good practice to declare)
# This doesn't actually create a volume, just documents intent.
# Actual volume creation/mounting happens during `docker run`.
VOLUME /app/data

# Expose a mount point for the user's music library (documentation purposes)
# The actual path `/music` is arbitrary; users mount their host path here.
# Your app needs to be configured to read from this path.
VOLUME /music

# Set the entrypoint for the container
# This will execute `python run_cli.py` when the container starts.
# Any arguments passed to `docker run ... <image_name> ARGS` will be appended to this.
ENTRYPOINT ["python", "run_cli.py"]

# Default command (e.g., show help if no arguments are passed to `docker run`)
CMD ["--help"]