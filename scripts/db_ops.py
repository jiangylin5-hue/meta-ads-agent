from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db.connection import health_check
from scripts.check_database_schema import check_schema


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Database operations for the PostgreSQL-backed ads agent.")
    parser.add_argument(
        "command",
        choices=[
            "check-schema",
            "health",
            "migrate",
            "current",
            "history",
            "offline-sql",
            "downgrade",
            "offline-downgrade-sql",
        ],
    )
    parser.add_argument(
        "--allow-destructive-local-reset",
        action="store_true",
        help="Allow Alembic downgrade commands that intentionally drop the local Stage 03 schema.",
    )
    args = parser.parse_args(argv)

    if args.command == "check-schema":
        errors = check_schema()
        if errors:
            print("\n".join(errors))
            return 1
        print("Database schema check passed.")
        return 0

    if args.command == "health":
        try:
            print(health_check())
        except SQLAlchemyError as exc:
            print(f"Database health check failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.command == "migrate":
        return subprocess.call([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT)

    if args.command == "current":
        return subprocess.call([sys.executable, "-m", "alembic", "current", "-v"], cwd=ROOT)

    if args.command == "history":
        return subprocess.call([sys.executable, "-m", "alembic", "history", "--verbose"], cwd=ROOT)

    if args.command == "offline-sql":
        return subprocess.call([sys.executable, "-m", "alembic", "upgrade", "head", "--sql"], cwd=ROOT)

    if args.command in {"downgrade", "offline-downgrade-sql"}:
        if not args.allow_destructive_local_reset:
            print(
                "Refusing destructive downgrade. Re-run with --allow-destructive-local-reset "
                "only for an intentional local database reset.",
                file=sys.stderr,
            )
            return 2
        env = os.environ.copy()
        env["ADS_AGENT_ALLOW_DESTRUCTIVE_MIGRATION"] = "yes"
        command = [sys.executable, "-m", "alembic", "downgrade", "base"]
        if args.command == "offline-downgrade-sql":
            command.append("--sql")
        return subprocess.call(command, cwd=ROOT, env=env)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
