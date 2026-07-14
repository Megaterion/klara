FROM python:3.11-slim

WORKDIR /app

# System deps for audio, OpenCV, and chromadb
RUN apt-get update && apt-get install -y --no-install-recommends \
    libportaudio2 \
    libsndfile1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent/ ./agent/
COPY config/ ./config/

# Shared runtime data is mounted via volume
ENV KLARA_PROFILE=prod
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "agent.main"]
