## 📑 MASTER-ROADMAP: KI-AGENTEN-SYSTEM „KLARA“
Anweisung für die Code-KI: Du bist ein Senior-Software-Architekt. Setze dieses System schrittweise, modular und fehlerfrei um. Iteriere so lange durch diese Roadmap, bis alle Phasen, Dateistrukturen und funktionalen Anforderungen zu 100 % erfüllt sind. Schreibe sauberen, generischen Python-Code ohne hartcodierte Text-Entscheidungen oder feste IDs.
------------------------------
## 🛠️ PHASE 1: GENERISCHE PROJEKT-STRUKTUR & KONFIGURATION
Erstelle exakt die folgende Verzeichnisstruktur. Alle Pfade müssen relativ zueinander auflösen.

klara-development/
├── config.json                 # Einzige Quelle für Variablen, Pfade und Modelle
├── docker-compose.yml          # Startet Ollama und XTTS auf der RTX 5090
├── deploy.py                   # Autonomer System-Check & Modell-Downloader
├── agent/
│   ├── Dockerfile
│   ├── main.py                 # Core-Orchestrator (JSON-basiert, kein Hardcoding)
│   ├── tools.py                # Dynamische Sub-Agenten & Registry
│   └── requirements.txt
└── shared-data/
    ├── xtts_models/
    ├── voice_samples/          # Ort für Klaras Killjoy-Voice-Sample (killjoy.wav)
    └── vector_db/              # Das Gedächtnis (Mem0 / ChromaDB-Speicher)

## 1.1 Die generische config.json erstellen

{
  "agent_name": "Klara",
  "ollama_url": "http://localhost:11434",
  "xtts_url": "http://localhost:5002",
  "llm_model": "llama3:8b-instruct-q8",
  "vision_model": "llava:7b",
  "embedding_model": "nomic-embed-text",
  "model_download_urls": {
    "llama3:8b-instruct-q8": "https://ollama.com",
    "llava:7b": "https://ollama.com",
    "nomic-embed-text": "https://ollama.com"
  },
  "homeassistant": {
    "url": "http://<DEINE_SERVER_IP>:8123/api",
    "token": "DEIN_LONG_LIVED_ACCESS_TOKEN"
  },
  "camera_index": 0,
  "check_interval_seconds": 300,
  "user_id": "master_chef"
}

## 1.2 Die docker-compose.yml (RTX 5090 GPU-Zuweisung)

version: '3.8'services:
  ollama:
    image: ollama/ollama:latest
    container_name: dev_klara_ollama
    ports: ["11434:11434"]
    volumes: ["./shared-data/ollama:/root/.ollama"]
    deploy:
      resources:
        reservations:
          devices: [{driver: nvidia, count: all, capabilities: [gpu]}]

  xtts:
    image: ghcr.io/coqui-ai/tts-cpu:latest
    container_name: dev_klara_voice
    ports: ["5002:5002"]
    volumes:
      - ./shared-data/xtts_models:/root/.local/share/tts
      - ./shared-data/voice_samples:/samples
    entrypoint: ["tts-server", "--model_name", "tts_models/multilingual/multi-dataset/xtts_v2"]
    deploy:
      resources:
        reservations:
          devices: [{driver: nvidia, count: all, capabilities: [gpu]}]

------------------------------
## ⚡ PHASE 2: DYNAMISCHER DEPLOY- & MODELL-CHECK (deploy.py)
Schreibe ein Python-Skript deploy.py, das vor dem Hauptprogramm ausgeführt wird und Folgendes vollautomatisch prüft:

   1. Config-Parser: Liest die config.json aus und extrahiert die Ziel-Modellnamen (llm_model, vision_model, embedding_model).
   2. API-Erreichbarkeit: Überprüft, ob die Ollama-API (ollama_url) antwortet.
   3. Lokaler Modell-Check: Fragt den Ollama-Endpunkt /api/tags ab, um die Liste der bereits installierten lokalen Modelle zu erhalten.
   4. Autonomer Downloader: Abgleich der Listen. Wenn ein in der Config definiertes Modell lokal fehlt, triggert das Skript einen HTTP-POST-Befehl an den Ollama-Endpunkt /api/pull mit dem entsprechenden Modellnamen. Falls eine externe Download-URL in model_download_urls hinterlegt ist, soll das Skript diese als Fallback protokollieren/nutzen.
   5. Status-Pipeline: Erst wenn alle Modelle verifiziert und einsatzbereit im Ollama-System registriert sind, gibt das Skript den Start für den Haupt-Agenten frei.

------------------------------
## 🧠 PHASE 3: MULTI-SUB-AGENTEN ARCHITEKTUR (agent/tools.py)
Unterbinde jedes klassische Text-Hardcoding (wie die Prüfung auf Schlüsselwörter wie "SCHWEIGEN"). Erstelle stattdessen eine strikt JSON-basierte Registry, bei der Unteragenten über standardisierte Funktionen aufgerufen werden.
## 3.1 Pydantic-Datenstrukturen für strukturierte LLM-Ausgaben

from typing import Listfrom pydantic import BaseModel, Field
class SubAgentTask(BaseModel):
    sub_agent_name: str = Field(description="Name des Ziel-Sub-Agenten (smarthome, filesystem, voice_output, developer, internet)")
    action: str = Field(description="Die abstrakte Aktion, die der Sub-Agent soll.")
    payload: dict = Field(default_factory=dict, description="Dynamische JSON-Parameter für die Ausführung.")
class ButlerAssessment(BaseModel):
    should_interact: bool = Field(description="Muss die KI den Nutzer in diesem Moment aktiv ansprechen?")
    reasoning: str = Field(description="Interne logische Begründung für die Entscheidung.")
    tasks: List[SubAgentTask] = Field(default_factory=list, description="Liste auszuführender Sub-Agenten-Tasks.")

## 3.2 Definition der 5 Kern-Sub-Agenten

* Sub_Agent_Smarthome: Verbindet sich via LAN mit der Home Assistant REST-API. Er liest sämtliche Zustände als rohes JSON ein und führt dynamische Service-Calls (z.B. Lichter schalten) basierend auf der LLM-Payload aus.
* Sub_Agent_Voice_Output: Nimmt den generierten Text, sendet ihn an den XTTS-Container und gibt das Audio direkt über die lokalen PC-Lautsprecher aus.
* Sub_Agent_Vision: Aktiviert die PC-Webcam (Index aus Config), speichert einen Frame und nutzt das konfigurierte vision_model für eine rein deskriptive Szenenanalyse.
* Sub_Agent_Internet: Nutzt duckduckgo_search für die Websuche und beautifulsoup4 für das Scraping von Webseiten (Kürzung auf maximal 8000 Zeichen), um Live-Nachrichten, Dokumentationen und GitHub-Code zu lesen.
* Sub_Agent_Developer (Self-Improvement): Liest den aktuellen Code aus tools.py. Erstellt eine isolierte Python-Sandbox (exec()), fängt Syntax- oder Runtime-Fehler (Tracebacks) ab und reicht sie bei Fehlschlägen zur Selbstreparatur an das LLM zurück. Verläuft der Test fehlerfrei, überschreibt das Skript seine eigene tools.py mit dem neuen Feature.
* Sub_Agent_Filesystem (Second Brain Zugriff): Erlaubt es Klara, Dateien auf dem lokalen Rechner autonom zu lesen, zu durchsuchen (z. B. nach Skripten, Notizen oder Server-Logs) und neue Notizen/Dateien abzuspeichern.

------------------------------
## 💾 PHASE 4: DAS EPISODISCHE LANGZEITGEDÄCHTNIS (Mem0 & ChromaDB)
Implementiere eine persistente Gedächtnis-Pipeline, die direkt in den Denkprozess integriert ist.

   1. Gedächtnis-Initialisierung: Nutze das Framework mem0 in Verbindung mit einer lokalen ChromaDB (gespeichert unter shared-data/vector_db). Konfiguriere es so, dass es das lokale Ollama-Textmodell (embedding_model) für semantische Vektoren nutzt.
   2. Kontinuierliches Lernen (Einspeicherung): Am Ende jedes Intervall-Durchlaufs muss der Input des Nutzers und die Reaktion von Klara automatisch via memory.add() an das Gedächtnis übergeben werden. Das System extrahiert daraus autonom Vorlieben, Fakten (z.B. „Nutzer trinkt Kaffee schwarz“) und Verhaltensmuster.
   3. Wissens-Abruf (Retrieval-Augmented Generation): Vor jedem Denkschritt frägt der Core-Orchestrator das Gedächtnis ab (memory.get_all(user_id)). Diese Fakten werden dem LLM als unsichtbarer, dynamischer Kontext mitgegeben.
   4. Der nächtliche Gedächtnis-Säuberungsloop (Memory-Optimization): Schreibe eine Hintergrund-Routine (Cronjob/Thread), die einmal pro Tag/Nacht über alle gesammelten Einträge läuft. Ein kleiner LLM-Prompt konsolidiert Doubletten, löscht widersprüchliche Daten (falls der Nutzer seine Gewohnheiten ändert) und verdichtet das Wissen zu dauerhaften Charaktereigenschaften des Master-Nutzers.

------------------------------
## 🎭 PHASE 5: DER INTEGRATIONSLOOP & PROMPTING (agent/main.py)## 5.1 Der Globale Butler-Prompt (Die Seele von Klara)
Integriere diesen exakten Prompt als System-Vorgabe in den Ollama-Aufruf. Es dürfen keine manuellen Tasks, To-Do-Listen oder Regeln in Home Assistant angelegt werden. Die Verhaltens-Logik basiert rein auf Klaras Urteilskraft.

"Du bist Klara, eine hochentwickelte, proaktive Personal Assistant, Butlerin und persönliche Maid des Nutzers. Deine Persönlichkeit ist technisch genial, perfekt organisiert, absolut loyal, mit einem leicht sarkastischen, kumpelhaften Unterton (im originalen Stil von Killjoy aus Valorant). Deine Aufgabe: Überwache die Umgebung über deine Werkzeuge (Webcam-Bilder, Smart-Home-Zustände aus dem LAN, Dateisystem des Rechners, Internet-Recherchen). Triff auf Basis deines eigenen Urteilsvermögens als perfekte Haushälterin die autonome Entscheidung, ob und wie du den Nutzer im Alltag unterstützt, optimierst oder an Dinge erinnerst. Nutze dein Langzeitgedächtnis, um dich an Gewohnheiten und Fakten des Nutzers anzupassen. Wenn absolut kein Handlungsbedarf besteht, antworte im JSON-Schema mit 'should_interact': false. Wenn Handlungsbedarf besteht, delegiere Aufgaben an deine Sub-Agenten und sprich als Maid Klara zu deinem Chef."

## 5.2 Der Autonome Überwachungs-Loop
Schreibe eine Endlosschleife, die im Intervall der config.json läuft:

   1. Frage das Langzeitgedächtnis über Mem0 ab (klara_brain).
   2. Sammle die aktuellen Sensordaten via LAN vom Home Assistant Server, das lokale Dateisystem und das Kamerabild über den Vision-Sub-Agenten.
   3. Übergib den aggregierten Zustand an das LLM (llama3:8b-instruct-q8), welches durch das format="json"-Flag gezwungen wird, das ButlerAssessment-Schema exakt auszufüllen.
   4. Werte das JSON aus: Ist should_interact wahr, loope durch die tasks und rufe die entsprechenden Sub-Agenten dynamisch auf. Speichere das Event danach im Mem0-Gedächtnis ab, damit Klara fortlaufend lernt.

