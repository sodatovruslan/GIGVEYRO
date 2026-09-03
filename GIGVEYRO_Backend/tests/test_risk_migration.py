import asyncio
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
from sqlalchemy.engine import make_url


async def test_risk_migration_roundtrip_on_disposable_database():
    root = Path(__file__).resolve().parent.parent
    base = make_url(os.environ["DATABASE_URL"])
    name = f"gigveyro_risk_migration_{uuid.uuid4().hex[:12]}"
    assert re.fullmatch(r"[A-Za-z0-9_]+", name)
    admin = await asyncpg.connect(
        base.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    )
    await admin.execute(f'CREATE DATABASE "{name}"')
    try:
        url = base.set(database=name)
        env = {
            **os.environ,
            "APP_ENV": "test",
            "DEBUG": "false",
            "DATABASE_URL": url.render_as_string(hide_password=False),
        }
        for args in (
            ("upgrade", "0022"),
            ("upgrade", "head"),
            ("downgrade", "0022"),
            ("upgrade", "head"),
        ):
            await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "alembic", *args],
                cwd=root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
        connection = await asyncpg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False)
        )
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == "0027"
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM risk_policies WHERE status='active'"
                )
                == 1
            )
            assert (
                await connection.fetchval("SELECT reserve_coverage_enabled FROM risk_policies")
                is False
            )
        finally:
            await connection.close()
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()
