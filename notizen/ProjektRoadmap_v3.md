# MASTER-ROADMAP V3: KLARA (ohne Self-Improvement)

Ziel: Ein sehr schnelles, stabiles und qualitativ hochwertiges Agenten-System mit starkem Langzeitgedaechtnis.

Wichtig:
- Kein Self-Improvement-Agent in der Basis.
- Alle anderen Kernbereiche bleiben enthalten: Orchestrierung, Smart Home, Vision, Internet, Filesystem, Voice, Memory.
- Umsetzung in Major-Versionen mit klaren KPIs, damit Geschwindigkeit und Qualitaet messbar steigen.

---

## 1) Leitprinzipien fuer ein effizientes Grundgeruest

1. Event-Driven statt Polling-Overkill
- Reagiere auf Events (HA-Statuswechsel, Motion-Trigger, User-Input), nicht auf dauerndes Voll-Sampling.
- Polling nur als Fallback mit niedriger Frequenz.

2. Budgetiertes Tooling pro Zyklus
- Max Tool-Calls je Zyklus, harte Timeouts, Abbruchregeln.
- Kein unkontrolliertes Kaskadieren von Sub-Agenten.

3. Zwei-Stufen-Inferenz fuer Textqualitaet und Speed
- Stufe A: Fast Planner (kleines Modell, kurze Antwort, JSON only).
- Stufe B: Rich Responder (groesseres Modell) nur wenn wirklich gesprochen/ausgegeben werden muss.

4. Memory as Product Feature
- Langzeitgedaechtnis ist Kernfunktion, nicht Add-on.
- Persistenz + Retrieval + Konsolidierung von Anfang an einbauen.

5. Deterministische Datenfluesse
- Klare Schemas, klare Tool-Vertraege, klare Fehlerpfade.
- Keine Logik auf Freitext-Hacks.

---

## 2) Zielarchitektur (v3 Basis)

klara-development/
- config/
  - base.json
  - profile.dev.json
  - profile.prod.json
- docker-compose.yml
- deploy.py
- agent/
  - main.py
  - orchestrator.py
  - event_bus.py
  - task_queue.py
  - schemas/
    - assessment.py
    - world_state.py
    - tool_contracts.py
  - memory/
    - sqlite_store.py
    - vector_store.py
    - retrieval.py
    - consolidation.py
  - tools/
    - smarthome.py
    - vision.py
    - internet.py
    - filesystem.py
    - voice.py
  - safety/
    - tool_budget.py
    - rate_limiter.py
    - validators.py
  - observability/
    - metrics.py
    - tracing.py
    - quality_checks.py
- shared-data/
  - sqlite/
  - vector_db/
  - voice_samples/
  - xtts_models/
  - cache/

---

## 3) Major-Versionen

## Major v1.0 (Foundation Fast Core)

Ziel:
- Stabiler Kern mit messbar schneller Reaktion.

Enthaelt:
- Deploy-Check fuer Modelle und Dienste.
- Orchestrator + Event-Bus + Task-Queue.
- Sub-Agenten: smarthome, voice, filesystem.
- Hybrid Memory (SQLite + Vektorstore) mit Retrieval.
- Grundlegende TTS-Pipeline mit Caching.
- Metriken und strukturierte Logs.

KPI-Ziele:
- Planner-Latenz p95 <= 1.5s.
- End-to-End (Input bis TTS-Start) p95 <= 3.5s.
- JSON-Validierungsquote >= 99%.
- Memory-Retrieval-Hit-Rate >= 70% bei Standardfragen.

Abnahme:
- 72h Dauertest ohne Absturz.
- Keine Memory-Korruption.

## Major v2.0 (Multimodal + Internet)

Ziel:
- Mehr Kontextfaehigkeit bei stabiler Geschwindigkeit.

Enthaelt:
- Vision-Agent (triggerbasiert, nicht permanent).
- Internet-Agent mit Whitelist, Content-Limit, Prompt-Injection-Schutz.
- Besseres Prioritaetsmodell in task_queue.
- Persona/Response-Style-Layer getrennt von Planungslogik.

KPI-Ziele:
- End-to-End p95 <= 4.5s bei aktivem Vision/Internet-Zugriff.
- Tool-Timeout-Handling 100% sauber.
- Halluzinations-Quote in factual Antworten deutlich reduziert durch Retrieval.

## Major v3.0 (Prod-Hardening auf Proxmox + Intel Arc)

Ziel:
- Produktionsbetrieb auf schwacherer Hardware.

Enthaelt:
- Modelle auf effiziente Groesse/Quantisierung begrenzt.
- Adaptive Sampling-Strategie (bei Last weniger Side-Tools).
- Strikte Cache- und Queue-Optimierung.
- Betriebsprofile fuer Nacht/Tag/Lastspitzen.

KPI-Ziele:
- Stabile 24/7 Laufzeit.
- End-to-End p95 <= 5.0s auf Prod-Hardware.
- Keine Queue-Staus > 30s.

## Major v4.0 (Memory Intelligence)

Ziel:
- Spuerbar personalisierte Assistenz ueber Wochen.

Enthaelt:
- Nachtkonsolidierung mit Widerspruchsloesung.
- Preference-Scoring mit Verfallslogik (Recency/Frequency).
- Goal- und Kontext-gebundenes Retrieval.
- Antwortverhalten sichtbar durch Memory beeinflusst.

KPI-Ziele:
- Relevante Personalisierung in >= 80% der Alltagssituationen.
- Falsche/alte Praeferenzen sinken messbar durch Konsolidierung.

---

## 4) Geschwindigkeit und Textqualitaet: konkrete Strategie

1. Router-Pattern fuer Modellwahl
- Planner-Modell klein und schnell.
- Response-Modell nur bei Nutzeransprache.
- Vision nur bei Trigger und nur kurze Bildzusammenfassung.

2. Prompt-Komprimierung
- Feste Systemteile kurz halten.
- Kontextfenster nur mit relevanten Abschnitten fuellen.
- Memory-Retrieval top_k begrenzen und reranken.

3. Output-Qualitaet
- Strenge Schema-Validierung (Pydantic).
- Retry nur bei ungueltigem JSON (max 1-2 Retries).
- Stil-Layer nachgelagert: Inhalt zuerst, Ton danach.

4. Caching
- Web-Suche TTL-Cache.
- TTS-Waveform-Cache fuer haeufige Phrasen.
- Embedding-Cache fuer identische Inhalte.

---

## 5) Sprachsynthese-Qualitaet: konkrete Strategie

1. XTTS sauber betreiben
- Einheitliche Sample-Rate in gesamter Pipeline.
- Lautstaerke-Normalisierung und leichte Kompression.
- Voice-Sample-Qualitaet priorisieren (sauber, wenig Rauschen).

2. Vorverarbeitung fuer bessere Aussprache
- Zahlen, Uhrzeiten, Abkuerzungen in sprechbare Form normalisieren.
- Lange Saetze in prosodische Segmente teilen.

3. Laufzeitoptimierung
- TTS asynchron starten, sobald finaler Antworttext steht.
- Audio-Stream sofort abspielen (kein Warten auf gesamte Datei).

4. Qualitaetskontrollen
- MOS-Checkliste intern (Verstaendlichkeit, Natuerlichkeit, Stabilitaet).
- Automatischer Fallback auf kuerzere Antwort bei TTS-Fehler.

---

## 6) Langzeitgedaechtnis, das Verhalten wirklich beeinflusst

## Speicherdesign
- SQLite als Source of Truth:
  - events
  - user_facts
  - preferences
  - assistant_actions
- Vektorstore fuer semantische Suche:
  - chunked memories
  - embeddings mit metadata (timestamp, confidence, source)

## Schreibpfad
- Nach jedem relevanten Zyklus:
  - Event und Antwort in SQLite.
  - Semantisch relevante Elemente in Vektorstore.
- Nur hochwertige Eintraege vektorisieren (Signal > Noise).

## Lesepfad (vor jeder Entscheidung)
- Query aus aktuellem Ziel + Kontext + letzter User-Absicht.
- Retrieval top_k (z. B. 8-12), danach Rerank.
- Nur die besten Treffer in den Prompt.

## Konsolidierung (nachtaktiv)
- Dubletten entfernen.
- Widersprueche markieren und mit Zeitgewicht loesen.
- Praeferenzen mit Recency/Frequency neu bewerten.
- Permanente Eigenschaften aktualisieren.

## Verhaltenseinfluss
- Planner bekommt kompaktes Preference-Set als versteckten Kontext.
- Entscheidungen muessen erklaerbar auf Memory-Eintraege referenzieren (internes Log).

---

## 7) Dev- und Prod-Profil (dein Hardware-Setup)

## Dev (RTX 5090)
- Groesseres Response-Modell moeglich.
- Hoehere Parallelitaet fuer Tooling.
- Aggressive Caches fuer schnelle Iteration.

## Prod (Proxmox + Intel Arc A310)
- Kleinere quantisierte Modelle.
- Niedrigere Vision-Frequenz.
- Striktere Tool-Budgets und kuerzere Kontexte.
- Fokus auf stabile Sprachausgabe und verlaessliche Kernaufgaben.

Faustregel:
- Funktionsumfang bleibt gleich.
- Rechenintensitaet wird per Profil skaliert.

---

## 8) Reihenfolge fuer die direkte Umsetzung

1. v1.0 Kern aufsetzen (ohne Vision/Internet zuerst).
2. Metriken aktivieren und baseline messen.
3. Memory-Schreib-/Lesepfad verifizieren.
4. TTS-Qualitaet mit realen Alltagssaetzen tunen.
5. Erst danach Vision/Internet aus v2.0 zuschalten.
6. Anschliessend Prod-Hardening fuer v3.0.

---

## 9) Definition of Done fuer dein Grundgeruest

Das Grundgeruest ist nur dann fertig, wenn:
- JSON-Output robust validiert wird.
- End-to-End-Latenz im Zielbereich liegt.
- TTS subjektiv und technisch stabil ist.
- Memory bei Entscheidungen sichtbar Einfluss hat.
- 72h Stabilitaetstest ohne kritische Fehler durchlaeuft.
- Kein Self-Improvement-Code enthalten ist.
