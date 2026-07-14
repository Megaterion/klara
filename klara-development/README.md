# Klara Operations Guide

Arbeitsverzeichnis:

```bash
cd /home/runner/work/klara/klara/klara-development
```

Standardstart:

```bash
./start.sh
```

`./start.sh` führt in dieser Reihenfolge aus:

1. legt bei Bedarf `.venv/` an
2. installiert/aktualisiert `requirements.txt`
3. führt `deploy.py` aus
4. startet eine `tmux`-Session mit 2 Fenstern
   - links: Setup + Chat
   - rechts: Live-Logs

## Voraussetzungen

- Python 3.11 oder neuer
- Docker + `docker compose`
- `tmux`
- `ffmpeg` nur dann, wenn `shared-data/voice_samples/killjoy.wav` noch nicht existiert

## Startvarianten

```bash
./start.sh check
./start.sh logs
./start.sh stop
```

## DB-Befehle

```bash
./start.sh db status
./start.sh db export --output /tmp/klara-memory.json
./start.sh db clear events preferences
./start.sh db delete events 1 2 3
./start.sh db reset
```

## Deploy-Check

`deploy.py` prüft und automatisiert:

- Docker Runtime
- Docker-Container (`klara_ollama`, `klara_xtts`)
- Ollama-Modelle (`llm_model`, `vision_model`, `embedding_model`)
- XTTS-Health
- Voice-Sample

Wenn `shared-data/voice_samples/killjoy.wav` fehlt und `killjoyGermanLines6min.mp3` im Repo-Root liegt, erzeugt `deploy.py` die WAV-Datei automatisch.

`./start.sh` startet den Agenten nur dann, wenn der Check erfolgreich ist.

Erzwungener Start trotz fehlgeschlagener Checks:

```bash
python .venv/bin/python deploy.py --profile dev --start --force-start
```

## Logs

- Live-Logs laufen im rechten Fenster über `agent.observability.log_viewer`
- `shared-data/logs/klara.log` ist ein rotierendes Log
- Standardgrenzen aus `config/base.json`:
  - `log_max_bytes = 10485760`
  - `log_backup_count = 3`

## DB-Management

SQLite-Datei:

- `shared-data/sqlite/klara.db`

Tabellen:

- `events`
- `user_facts`
- `preferences`
- `assistant_actions`

Der Vektorstore liegt separat in `shared-data/vector_db`.

DB-Eingriffe erfolgen über:

```bash
./start.sh db ...
```

## Direkter Python-Start

```bash
pip install -r /home/runner/work/klara/klara/klara-development/requirements.txt
cd /home/runner/work/klara/klara/klara-development
KLARA_PROFILE=dev python -m agent.main
```
