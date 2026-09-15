import asyncio
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
from sqlalchemy.engine import make_url


async def test_telegram_migration_roundtrip_on_disposable_database():
    root = Path(__file__).resolve().parent.parent
    base = make_url(os.environ["DATABASE_URL"])
    name = f"gigveyro_telegram_migration_{uuid.uuid4().hex[:12]}"
    assert re.fullmatch(r"[A-Za-z0-9_]+", name)
    admin = await asyncpg.connect(
        base.set(drivername="postgresql", database="postgres").render_as_string(
            hide_password=False
        )
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
        for arguments in (
            ("upgrade", "0025"),
            ("upgrade", "head"),
            ("downgrade", "0025"),
            ("upgrade", "head"),
        ):
            await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "alembic", *arguments],
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
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == "0037"
            assert await connection.fetchval("SELECT to_regclass('telegram_link_tokens')")
            columns = {
                row["column_name"]
                for row in await connection.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='telegram_account_links'"
                )
            }
            assert {"language", "delivery_enabled", "linked_at"} <= columns
            assert "verification_code_hash" not in columns
            indexes = {
                row["indexname"]
                for row in await connection.fetch(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename='telegram_account_links'"
                )
            }
            assert {
                "uq_telegram_link_active_user",
                "uq_telegram_link_active_chat",
            } <= indexes
        finally:
            await connection.close()
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()
