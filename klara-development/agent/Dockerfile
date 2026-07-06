FROM python:3.12-slim

WORKDIR /app

# System dependencies for audio playback
RUN apt-get update && apt-get install -y --no-install-recommends \
    alsa-utils \
    pulseaudio-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV KLARA_PROFILE=dev
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "agent.main"]
