"""
db_admin.py — CLI for inspecting and manipulating Klara memory stores.

Examples:
    python -m agent.memory.db_admin status
    python -m agent.memory.db_admin export --output /tmp/klara-memory.json
    python -m agent.memory.db_admin clear events preferences
    python -m agent.memory.db_admin delete events 1 2 3
    python -m agent.memory.db_admin reset
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from agent.memory.sqlite_store import SCHEMA

console = Console()
TABLES = ("events", "user_facts", "preferences", "assistant_actions")
VECTOR_COLLECTION = "klara_memories"
BASE_DIR = Path(__file__).resolve().parents[2]


def load_config(profile: str) -> dict[str, Any]:
    base_path = BASE_DIR / "config" / "base.json"
    profile_path = BASE_DIR / "config" / f"profile.{profile}.json"

    with open(base_path, encoding="utf-8") as file_handle:
        config = json.load(file_handle)
    if profile_path.exists():
        with open(profile_path, encoding="utf-8") as file_handle:
            overrides = json.load(file_handle)
        _deep_merge(config, overrides)
    return config


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> None:
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _sqlite_path(config: dict[str, Any]) -> Path:
    return (BASE_DIR / config["memory"]["sqlite_path"]).resolve()


def _vector_path(config: dict[str, Any]) -> Path:
    return (BASE_DIR / config["memory"]["vector_db_path"]).resolve()


def _connect_sqlite(config: dict[str, Any]) -> sqlite3.Connection:
    db_path = _sqlite_path(config)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    connection.commit()
    return connection


def _table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in TABLES:
        counts[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return counts


def _vector_count(config: dict[str, Any]) -> int:
    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(_vector_path(config)))
        collection = client.get_or_create_collection(name=VECTOR_COLLECTION)
        return int(collection.count())
    except Exception:
        return 0


def status_command(config: dict[str, Any]) -> int:
    sqlite_path = _sqlite_path(config)
    vector_path = _vector_path(config)
    with _connect_sqlite(config) as connection:
        counts = _table_counts(connection)

    table = Table(title="Klara Memory Status", header_style="bold cyan")
    table.add_column("Store")
    table.add_column("Entries", justify="right")
    table.add_column("Path")
    for table_name in TABLES:
        table.add_row(table_name, str(counts[table_name]), str(sqlite_path))
    table.add_row("vector_store", str(_vector_count(config)), str(vector_path))
    console.print(table)
    return 0


def export_command(config: dict[str, Any], output: str | None) -> int:
    export_data: dict[str, Any] = {
        "sqlite_path": str(_sqlite_path(config)),
        "vector_path": str(_vector_path(config)),
        "tables": {},
    }
    with _connect_sqlite(config) as connection:
        for table in TABLES:
            rows = connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            export_data["tables"][table] = [dict(row) for row in rows]

    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(_vector_path(config)))
        collection = client.get_or_create_collection(name=VECTOR_COLLECTION)
        export_data["vector_store"] = collection.get()
    except Exception as exc:
        export_data["vector_store_error"] = str(exc)

    payload = json.dumps(export_data, ensure_ascii=False, indent=2)
    if output:
        Path(output).write_text(payload, encoding="utf-8")
        console.print(f"[green]Export geschrieben:[/green] {output}")
    else:
        console.print(payload)
    return 0


def clear_command(config: dict[str, Any], targets: list[str]) -> int:
    normalized = [target.lower() for target in targets]
    clear_sqlite = {"all", *TABLES}.intersection(normalized)
    clear_vector = "all" in normalized or "vector" in normalized or "vector_store" in normalized

    with _connect_sqlite(config) as connection:
        for table in TABLES:
            if "all" in clear_sqlite or table in clear_sqlite:
                connection.execute(f"DELETE FROM {table}")
        connection.commit()
        connection.execute("VACUUM")

    if clear_vector:
        try:
            import chromadb

            client = chromadb.PersistentClient(path=str(_vector_path(config)))
            try:
                client.delete_collection(VECTOR_COLLECTION)
            except Exception:
                pass
            client.get_or_create_collection(name=VECTOR_COLLECTION)
        except Exception as exc:
            console.print(f"[yellow]Vector-Store konnte nicht geleert werden:[/yellow] {exc}")

    console.print("[green]Speicher bereinigt.[/green]")
    return 0


def delete_command(config: dict[str, Any], table: str, ids: list[int]) -> int:
    if table not in TABLES:
        raise SystemExit(f"Unbekannte Tabelle: {table}")
    with _connect_sqlite(config) as connection:
        placeholders = ", ".join("?" for _ in ids)
        connection.execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", ids)
        connection.commit()
        connection.execute("VACUUM")
    console.print(f"[green]Einträge gelöscht:[/green] {table} -> {ids}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Klara DB admin")
    parser.add_argument(
        "--profile",
        default="dev",
        choices=["dev", "prod"],
        help="Konfigurationsprofil",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Zeigt Anzahl der Einträge je Store")

    export_parser = subparsers.add_parser("export", help="Exportiert SQLite- und Vector-Inhalte")
    export_parser.add_argument("--output", help="Zieldatei für den Export")

    clear_parser = subparsers.add_parser("clear", help="Leert Tabellen oder den Vector-Store")
    clear_parser.add_argument(
        "targets",
        nargs="+",
        help="events, user_facts, preferences, assistant_actions, vector, all",
    )

    delete_parser = subparsers.add_parser("delete", help="Löscht IDs aus einer SQLite-Tabelle")
    delete_parser.add_argument("table", choices=TABLES)
    delete_parser.add_argument("ids", nargs="+", type=int)

    subparsers.add_parser("reset", help="Leert SQLite und Vector-Store komplett")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(args.profile)

    if args.command == "status":
        return status_command(config)
    if args.command == "export":
        return export_command(config, args.output)
    if args.command == "clear":
        return clear_command(config, args.targets)
    if args.command == "delete":
        return delete_command(config, args.table, args.ids)
    if args.command == "reset":
        return clear_command(config, ["all"])
    raise SystemExit(f"Unbekannter Befehl: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
