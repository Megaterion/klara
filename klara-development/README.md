# Klara Operations Guide

Klara wird operativ bewusst über **einen Einstiegspunkt** bedient:

```bash
cd /home/runner/work/klara/klara/klara-development
./start.sh
```

Dieser Befehl macht genau Folgendes:

1. legt bei Bedarf `.venv/` an
2. installiert/aktualisiert `requirements.txt`
3. führt `deploy.py` aus
4. startet Klara im **2-Fenster-Modus**
   - links: Setup + Chat
   - rechts: Live-Logs

## Voraussetzungen

- Python 3.11+
- Docker + `docker compose`
- `tmux`
- `ffmpeg` (nur nötig, wenn `shared-data/voice_samples/killjoy.wav` noch nicht existiert)

## Weitere Befehle

```bash
./start.sh check
./start.sh logs
./start.sh db status
./start.sh db export --output /tmp/klara-memory.json
./start.sh db clear events preferences
./start.sh db delete events 1 2 3
./start.sh db reset
./start.sh stop
```

## Deploy-Verhalten

`deploy.py` prüft und automatisiert:

- Docker Runtime
- Docker-Container (`klara_ollama`, `klara_xtts`)
- Ollama-Modelle (`llm_model`, `vision_model`, `embedding_model`)
- XTTS-Health
- Voice-Sample

Falls `killjoy.wav` fehlt und `killjoyGermanLines6min.mp3` im Repo-Root liegt, wird das WAV automatisch erzeugt.

## Logs

- Live-Logs laufen im rechten Fenster über `agent.observability.log_viewer`
- die Datei `shared-data/logs/klara.log` ist nur ein **rotierender Ringpuffer**
- Standardlimit:
  - `log_max_bytes = 2097152`
  - `log_backup_count = 2`

Damit bleibt die Log-Ablage begrenzt und wächst nicht unkontrolliert.

## DB-Management

SQLite bleibt die Source of Truth:

- `events`
- `user_facts`
- `preferences`
- `assistant_actions`

Der Vektorstore liegt separat in `shared-data/vector_db`.

DB-Eingriffe laufen über:

```bash
./start.sh db ...
```

Nicht über ad-hoc-Skripte, nicht über manuelle SQL-Dateien im Repo.

## Roadmap-Abgleich

Abgleich gegen `notizen/ProjektRoadmap_v3.md`:

- **erfüllt:** Event-getriebener Kern, Tool-Budget, Hybrid-Memory, strukturierte Logs, Deploy-Check, Voice/Filesystem/Internet/Vision-Module vorhanden
- **operativ ergänzt:** ein klarer Launcher (`start.sh`) und ein DB-Admin-CLI
- **bewusst nicht enthalten:** Self-Improvement-Agent in der Basis; das entspricht v3

## Vereinfachungsprinzip

Für den Betriebsweg gilt:

- ein Startskript
- ein Checkskript
- ein DB-CLI
- ein Log-Viewer

Keine zusätzlichen Launcher, keine unnötigen Start-Fallbacks, keine temporären Hilfsskripte im Repo.
