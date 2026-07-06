"""
deploy.py – Klara Autonomous Deploy & Model-Check Script

Runs before the main agent to:
1. Load and merge config (base + profile).
2. Verify Ollama API is reachable.
3. Check which models are already pulled locally.
4. Pull any missing models automatically.
5. Release the agent start signal only when all models are ready.
"""

import json
import os
import sys
import time
import logging
from pathlib import Path

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
log = logging.getLogger("klara.deploy")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(profile: str | None = None) -> dict:
    base_dir = Path(__file__).parent
    base_path = base_dir / "config" / "base.json"
    if not base_path.exists():
        log.error("base.json not found at %s", base_path)
        sys.exit(1)

    with base_path.open(encoding="utf-8") as f:
        cfg: dict = json.load(f)

    if profile:
        profile_path = base_dir / "config" / f"profile.{profile}.json"
        if profile_path.exists():
            with profile_path.open(encoding="utf-8") as f:
                profile_cfg: dict = json.load(f)
            cfg = _deep_merge(cfg, profile_cfg)
            log.info("Profile '%s' merged.", profile)
        else:
            log.warning("Profile file %s not found – using base config only.", profile_path)

    # Allow environment-variable overrides for secrets
    if os.getenv("HOMEASSISTANT_URL"):
        cfg.setdefault("homeassistant", {})["url"] = os.environ["HOMEASSISTANT_URL"]
    if os.getenv("HOMEASSISTANT_TOKEN"):
        cfg.setdefault("homeassistant", {})["token"] = os.environ["HOMEASSISTANT_TOKEN"]

    return cfg


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------------------------

def wait_for_ollama(base_url: str, retries: int = 10, delay: float = 3.0) -> None:
    url = f"{base_url.rstrip('/')}/api/tags"
    for attempt in range(1, retries + 1):
        try:
            r = httpx.get(url, timeout=5.0)
            r.raise_for_status()
            log.info("Ollama is reachable at %s", base_url)
            return
        except Exception as exc:
            log.warning("Ollama not ready (attempt %d/%d): %s", attempt, retries, exc)
            if attempt < retries:
                time.sleep(delay)
    log.error("Ollama did not become ready after %d attempts. Aborting.", retries)
    sys.exit(1)


def get_local_models(base_url: str) -> set[str]:
    url = f"{base_url.rstrip('/')}/api/tags"
    r = httpx.get(url, timeout=10.0)
    r.raise_for_status()
    data = r.json()
    return {m["name"] for m in data.get("models", [])}


def pull_model(base_url: str, model_name: str, timeout: float = 600.0) -> None:
    url = f"{base_url.rstrip('/')}/api/pull"
    log.info("Pulling model '%s' – this may take a while…", model_name)
    with httpx.stream("POST", url, json={"name": model_name, "stream": True}, timeout=timeout) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line.strip():
                try:
                    chunk = json.loads(line)
                    if chunk.get("status"):
                        log.debug("[pull] %s", chunk["status"])
                except json.JSONDecodeError:
                    pass
    log.info("Model '%s' pulled successfully.", model_name)


# ---------------------------------------------------------------------------
# Main check flow
# ---------------------------------------------------------------------------

def ensure_models(cfg: dict) -> None:
    ollama_url: str = cfg["ollama_url"]
    required_models: list[str] = [
        cfg["llm_planner_model"],
        cfg["llm_responder_model"],
        cfg["embedding_model"],
    ]
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_models: list[str] = []
    for m in required_models:
        if m not in seen:
            seen.add(m)
            unique_models.append(m)

    log.info("Required models: %s", unique_models)

    local_models = get_local_models(ollama_url)
    log.info("Locally available models: %s", local_models)

    missing = [m for m in unique_models if m not in local_models]
    if not missing:
        log.info("All required models are already available. ✓")
        return

    if not cfg.get("model_pull_on_missing", True):
        log.error("Missing models %s and model_pull_on_missing=false. Aborting.", missing)
        sys.exit(1)

    for model in missing:
        pull_model(ollama_url, model)

    # Final verification
    local_models = get_local_models(ollama_url)
    still_missing = [m for m in unique_models if m not in local_models]
    if still_missing:
        log.error("Models still missing after pull: %s", still_missing)
        sys.exit(1)

    log.info("All required models are ready. ✓")


def check_xtts(cfg: dict) -> None:
    url = cfg.get("xtts_url", "")
    if not url:
        return
    try:
        r = httpx.get(f"{url.rstrip('/')}/health", timeout=5.0)
        if r.is_success:
            log.info("XTTS service is reachable. ✓")
            return
    except Exception:
        pass
    log.warning("XTTS service not reachable at %s – TTS will be unavailable.", url)


def main() -> None:
    profile = os.getenv("KLARA_PROFILE", "dev")
    log.info("=== Klara Deploy Check (profile: %s) ===", profile)

    cfg = load_config(profile)

    log.info("Waiting for Ollama…")
    wait_for_ollama(cfg["ollama_url"])

    log.info("Checking XTTS…")
    check_xtts(cfg)

    log.info("Ensuring models…")
    ensure_models(cfg)

    log.info("=== Deploy check passed. Klara agent may start. ===")


if __name__ == "__main__":
    main()
