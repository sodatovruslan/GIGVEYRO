import asyncio
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
from sqlalchemy.engine import make_url


async def test_fee_migration_upgrade_downgrade_one_revision_upgrade():
    project_root = Path(__file__).resolve().parent.parent
    base_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"gigveyro_fee_migration_{uuid.uuid4().hex[:12]}"
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
            ("upgrade", "0021"),
            ("upgrade", "head"),
            ("downgrade", "0021"),
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
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == "0024"
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM fee_policies WHERE status = 'active'"
                )
                == 1
            )
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM fee_policy_components WHERE enabled"
                )
                == 0
            )
            assert await connection.fetchval("SELECT count(*) FROM fee_policy_components") == 4
        finally:
            await connection.close()
    finally:
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await admin.execute(f'DROP DATABASE "{database_name}"')
        await admin.close()
