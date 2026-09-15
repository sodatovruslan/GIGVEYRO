import asyncio
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
from sqlalchemy.engine import make_url


async def test_managed_fiat_migration_upgrade_downgrade_upgrade_on_disposable_database():
    project_root = Path(__file__).resolve().parent.parent
    base_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"gigveyro_fiat_migration_{uuid.uuid4().hex[:12]}"
    assert re.fullmatch(r"[A-Za-z0-9_]+", database_name)
    admin_url = base_url.set(drivername="postgresql", database="postgres")
    disposable_url = base_url.set(database=database_name)
    admin = await asyncpg.connect(admin_url.render_as_string(hide_password=False))
    await admin.execute(f'CREATE DATABASE "{database_name}"')
    try:
        environment = {
            **os.environ,
            "APP_ENV": "test",
            "DEBUG": "false",
            "DATABASE_URL": disposable_url.render_as_string(hide_password=False),
        }
        for arguments in (
            ("upgrade", "0020"),
            ("upgrade", "head"),
            ("downgrade", "0020"),
            ("upgrade", "head"),
        ):
            await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "alembic", *arguments],
                cwd=project_root,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
        connection = await asyncpg.connect(
            disposable_url.set(drivername="postgresql").render_as_string(hide_password=False)
        )
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == "0037"
            assert (
                await connection.fetchval("SELECT to_regclass('public.fiat_wallet_balances')::text")
                == "fiat_wallet_balances"
            )
        finally:
            await connection.close()
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
        await admin.close()
