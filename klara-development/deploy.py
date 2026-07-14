#!/usr/bin/env python3
"""
deploy.py - Klara pre-flight deployment checker.

Checks Docker containers, model availability, and service health
before launching the main agent. Run with:
    python deploy.py [--profile dev|prod] [--start]
"""

import asyncio
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

BASE_DIR = Path(__file__).parent
CONFIG_BASE = BASE_DIR / "config" / "base.json"
ROOT_DIR = BASE_DIR.parent
VOICE_SAMPLE_TARGET = BASE_DIR / "shared-data" / "voice_samples" / "killjoy.wav"
VOICE_SAMPLE_SOURCE = ROOT_DIR / "killjoyGermanLines6min.mp3"


def load_config(profile: str) -> dict:
    with open(CONFIG_BASE) as f:
        config = json.load(f)
    profile_path = BASE_DIR / "config" / f"profile.{profile}.json"
    if profile_path.exists():
        with open(profile_path) as f:
            overrides = json.load(f)
        _deep_merge(config, overrides)
    return config


def _deep_merge(base: dict, overrides: dict) -> None:
    for k, v in overrides.items():
        if isinstance(v, dict) and k in base and isinstance(base[k], dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def run_cmd(cmd: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode, result.stdout + result.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 1, str(e)


async def check_docker_containers() -> list[dict]:
    """Check if required Docker containers are running."""
    containers = ["klara_ollama", "klara_xtts"]
    results = []
    for name in containers:
        code, out = run_cmd(["docker", "inspect", "--format", "{{.State.Status}}", name])
        if code == 0:
            status = out.strip()
            running = status == "running"
        else:
            status = "not found"
            running = False
        results.append({"name": name, "status": status, "ok": running})
    return results


async def check_docker_runtime() -> list[dict]:
    """Check whether docker and docker compose are available."""
    checks = []
    code, out = run_cmd(["docker", "--version"])
    checks.append(
        {
            "name": "docker",
            "ok": code == 0,
            "detail": out.strip() if out.strip() else "not available",
        }
    )
    code, out = run_cmd(["docker", "compose", "version"])
    checks.append(
        {
            "name": "docker compose",
            "ok": code == 0,
            "detail": out.strip() if out.strip() else "not available",
        }
    )
    return checks


async def check_ollama_models(config: dict, client: httpx.AsyncClient) -> list[dict]:
    """Check if required Ollama models are pulled."""
    required = [
        config["llm_model"],
        config["vision_model"],
        config["embedding_model"],
    ]
    results = []
    try:
        resp = await client.get(f"{config['ollama_url']}/api/tags", timeout=10)
        resp.raise_for_status()
        pulled = {m["name"] for m in resp.json().get("models", [])}
    except Exception as e:
        for m in required:
            results.append({"model": m, "ok": False, "detail": str(e)})
        return results

    for model in required:
        # Ollama uses "name:tag" format; check prefix match
        found = any(p == model or p.startswith(model.split(":")[0]) for p in pulled)
        results.append({"model": model, "ok": found, "detail": "present" if found else "missing"})
    return results


async def pull_missing_models(config: dict, model_results: list[dict], client: httpx.AsyncClient) -> None:
    """Pull any missing Ollama models."""
    missing = [m["model"] for m in model_results if not m["ok"]]
    if not missing:
        return
    for model in missing:
        console.print(f"  📥 Pulling model [bold]{model}[/bold] ...")
        try:
            async with client.stream(
                "POST",
                f"{config['ollama_url']}/api/pull",
                json={"name": model},
                timeout=600,
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.strip():
                        try:
                            data = json.loads(line)
                            if "status" in data:
                                console.print(f"     {data['status']}", end="\r")
                        except json.JSONDecodeError:
                            pass
            console.print(f"  ✅ Pulled {model}                    ")
        except Exception as e:
            console.print(f"  ❌ Failed to pull {model}: {e}")


async def check_xtts_health(config: dict, client: httpx.AsyncClient) -> dict:
    """Check XTTS server health."""
    try:
        resp = await client.get(f"{config['xtts_url']}/health", timeout=10)
        return {"ok": resp.status_code == 200, "detail": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "detail": str(e)}


async def check_voice_sample(config: dict) -> dict:
    """Check if voice sample file exists."""
    # Try both container path and local path
    sample_path = config["voice_sample"]
    local_candidates = [
        BASE_DIR / "shared-data" / "voice_samples" / Path(sample_path).name,
        Path(sample_path),
    ]
    for path in local_candidates:
        if path.exists():
            return {"ok": True, "path": str(path)}
    return {
        "ok": False,
        "detail": f"Not found at {sample_path} or in shared-data/voice_samples/",
    }


async def ensure_voice_sample(config: dict) -> dict:
    """Ensure the XTTS voice sample exists, converting the bundled MP3 if possible."""
    existing = await check_voice_sample(config)
    if existing["ok"]:
        existing["detail"] = existing.get("path", "present")
        return existing

    if not VOICE_SAMPLE_SOURCE.exists():
        return {
            "ok": False,
            "detail": (
                f"Voice sample fehlt und Quelle wurde nicht gefunden: {VOICE_SAMPLE_SOURCE}"
            ),
        }

    code, out = run_cmd(["ffmpeg", "-version"])
    if code != 0:
        return {
            "ok": False,
            "detail": "ffmpeg fehlt; automatische WAV-Konvertierung nicht möglich",
        }

    VOICE_SAMPLE_TARGET.parent.mkdir(parents=True, exist_ok=True)
    console.print("  🎙️  Voice sample fehlt. Konvertiere MP3 nach WAV ...")
    code, out = run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(VOICE_SAMPLE_SOURCE),
            "-ar",
            "22050",
            "-ac",
            "1",
            str(VOICE_SAMPLE_TARGET),
        ]
    )
    if code != 0:
        return {"ok": False, "detail": f"ffmpeg-Konvertierung fehlgeschlagen: {out.strip()}"}

    return {
        "ok": True,
        "path": str(VOICE_SAMPLE_TARGET),
        "detail": f"erstellt aus {VOICE_SAMPLE_SOURCE.name}",
    }


def print_results_table(checks: dict) -> bool:
    """Print a summary table; return True if all critical checks pass."""
    table = Table(title="🤖 Klara Pre-Flight Check", show_header=True, header_style="bold cyan")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Detail")

    all_ok = True

    for section, items in checks.items():
        if isinstance(items, list):
            for item in items:
                ok = item.get("ok", False)
                label = item.get("name") or item.get("model") or section
                detail = item.get("detail", item.get("status", ""))
                table.add_row(
                    label,
                    "✅ OK" if ok else "❌ FAIL",
                    str(detail),
                )
                if not ok:
                    all_ok = False
        else:
            ok = items.get("ok", False)
            detail = items.get("detail", "")
            table.add_row(
                section,
                "✅ OK" if ok else "⚠️  WARN",
                str(detail),
            )
            if section not in {"XTTS server"} and not ok:
                all_ok = False

    console.print(table)
    return all_ok


async def start_docker_services() -> None:
    """Start Docker Compose services if not running."""
    console.print("🐳 Starting Docker Compose services...")
    code, out = run_cmd(["docker", "compose", "-f", str(BASE_DIR / "docker-compose.yml"), "up", "-d"])
    if code == 0:
        console.print("  ✅ Docker services started")
    else:
        console.print(f"  ❌ docker compose up failed:\n{out}")


async def wait_for_service(name: str, url: str, expected_status: int = 200, timeout: int = 90) -> dict:
    """Wait until an HTTP service responds successfully."""
    deadline = asyncio.get_running_loop().time() + timeout
    async with httpx.AsyncClient() as client:
        last_error = "no response"
        while asyncio.get_running_loop().time() < deadline:
            try:
                resp = await client.get(url, timeout=10)
                if resp.status_code == expected_status:
                    return {"name": name, "ok": True, "detail": f"HTTP {resp.status_code}"}
                last_error = f"HTTP {resp.status_code}"
            except Exception as exc:
                last_error = str(exc)
            await asyncio.sleep(2)
    return {"name": name, "ok": False, "detail": last_error}


async def main(profile: str, auto_start: bool, force_start: bool, skip_docker: bool) -> int:
    console.print(f"\n[bold cyan]🤖 Klara Deploy Check[/bold cyan] — profile: [bold]{profile}[/bold]\n")

    config = load_config(profile)

    async with httpx.AsyncClient() as client:
        with console.status("Checking Docker runtime..."):
            docker_runtime = await check_docker_runtime()

        # 1. Docker containers
        if not skip_docker and all(item["ok"] for item in docker_runtime):
            with console.status("Checking Docker containers..."):
                container_results = await check_docker_containers()

            if not all(c["ok"] for c in container_results):
                console.print("  Some containers are not running. Starting them...")
                await start_docker_services()
                console.print("  ⏳ Waiting for Ollama to become reachable...")
                await wait_for_service("ollama", f"{config['ollama_url']}/api/tags")
                console.print("  ⏳ Waiting for XTTS to become reachable...")
                await wait_for_service("xtts", f"{config['xtts_url']}/health")
                container_results = await check_docker_containers()
        else:
            container_results = [{"name": "skipped", "status": "skipped", "ok": True}]

        # 2. Ollama models
        with console.status("Checking Ollama models..."):
            model_results = await check_ollama_models(config, client)

        missing_models = [m for m in model_results if not m["ok"]]
        if missing_models:
            console.print(f"  📦 {len(missing_models)} model(s) missing. Auto-pulling...")
            await pull_missing_models(config, model_results, client)
            model_results = await check_ollama_models(config, client)

        # 3. XTTS health
        with console.status("Checking XTTS server..."):
            xtts_result = await check_xtts_health(config, client)

        # 4. Voice sample
        voice_result = await ensure_voice_sample(config)

    checks = {
        "Docker runtime": docker_runtime,
        "Docker containers": container_results,
        "Ollama models": model_results,
        "XTTS server": xtts_result,
        "Voice sample": voice_result,
    }

    all_ok = print_results_table(checks)

    if all_ok:
        console.print("\n[bold green]✅ All checks passed. Klara is ready to start.[/bold green]")
    else:
        console.print("\n[bold yellow]⚠️  Some checks failed. Review issues above.[/bold yellow]")

    if auto_start and (all_ok or force_start):
        if force_start and not all_ok:
            console.print("[yellow]Starte trotz fehlgeschlagener Checks (--force-start).[/yellow]")
        console.print("\n🚀 Launching Klara agent...\n")
        os.execvp(
            sys.executable,
            [sys.executable, "-m", "agent.main"],
        )
    if auto_start and not all_ok:
        console.print("\n[bold red]⛔ Start abgebrochen, da Checks fehlgeschlagen sind.[/bold red]")

    return 0 if all_ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Klara deployment checker")
    parser.add_argument(
        "--profile", default=os.environ.get("KLARA_PROFILE", "dev"),
        choices=["dev", "prod"], help="Config profile to use"
    )
    parser.add_argument(
        "--start", action="store_true",
        help="Start the agent after checks pass"
    )
    parser.add_argument(
        "--force-start", action="store_true",
        help="Start the agent even if checks fail"
    )
    parser.add_argument(
        "--skip-docker", action="store_true",
        help="Skip Docker container checks (for local dev without Docker)"
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.profile, args.start, args.force_start, args.skip_docker)))
