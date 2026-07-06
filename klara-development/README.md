# Klara – KI-Agenten-System v1.0 (Foundation Fast Core)

Klara ist ein event-getriebenes, proaktives KI-Agenten-System mit Killjoy-Persönlichkeit.

## Architektur

```
klara-development/
├── config/
│   ├── base.json            # Hauptkonfiguration (keine Secrets)
│   ├── profile.dev.json     # RTX 5090 Dev-Profil
│   └── profile.prod.json    # Proxmox + Intel Arc A310 Prod-Profil
├── docker-compose.yml       # Ollama + XTTS Services
├── deploy.py                # Automatischer Modell-Check & Download
├── agent/
│   ├── main.py              # Einstiegspunkt & Async Event Loop
│   ├── orchestrator.py      # Core-Orchestrator (World-State → LLM → Tasks)
│   ├── event_bus.py         # Async Pub/Sub Event-Verteiler
│   ├── task_queue.py        # Prioritäts-Queue (0=Kritisch … 3=Hintergrund)
│   ├── schemas/             # Pydantic-Schemas (ButlerAssessment, WorldState, Tools)
│   ├── memory/              # SQLite (Source of Truth) + ChromaDB (Vektoren)
│   ├── tools/               # Sub-Agenten: smarthome, voice, filesystem, vision, internet
│   ├── safety/              # Tool-Budget, Rate-Limiter, Validators
│   └── observability/       # Metriken, Tracing, KPI-Checks
└── shared-data/             # Persistent data (DB, models, cache)
```

## Schnellstart

### 1. Environment einrichten

```bash
cp .env.example .env
# .env bearbeiten: HOMEASSISTANT_URL + HOMEASSISTANT_TOKEN setzen
```

### 2. Voice Sample platzieren

```bash
cp /pfad/zu/killjoy.wav shared-data/voice_samples/killjoy.wav
```

### 3. Services starten

```bash
# Dev (RTX 5090)
KLARA_PROFILE=dev docker compose up -d ollama xtts

# Modelle prüfen & herunterladen
python deploy.py

# Agenten starten
cd agent
pip install -r requirements.txt
KLARA_PROFILE=dev python -m agent.main
```

## KPI-Ziele (v1.0)

| Metrik | Ziel |
|---|---|
| Planner-Latenz p95 | ≤ 1.5s |
| End-to-End p95 | ≤ 3.5s |
| JSON-Validierungsquote | ≥ 99% |
| Memory-Retrieval-Hit-Rate | ≥ 70% |
| Stabilitätstest | 72h ohne Absturz |

## Konfiguration

Alle Einstellungen liegen in `config/base.json`. Profil-spezifische Overrides in
`config/profile.dev.json` bzw. `config/profile.prod.json`.

Secrets (`HOMEASSISTANT_TOKEN` etc.) werden ausschließlich über Umgebungsvariablen übergeben –
**niemals in Konfigurationsdateien eintragen**.

## Versionsplan

| Version | Fokus |
|---|---|
| **v1.0** ✅ | Foundation Fast Core (Orchestrator, Memory, Voice, Filesystem) |
| v2.0 | Multimodal + Internet (Vision, Web-Suche) |
| v3.0 | Prod-Hardening auf Proxmox + Intel Arc |
| v4.0 | Memory Intelligence (Konsolidierung, Preference-Scoring) |
