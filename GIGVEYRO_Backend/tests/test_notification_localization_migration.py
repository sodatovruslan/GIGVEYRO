import asyncio
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
from sqlalchemy.engine import make_url


async def test_notification_localization_migration_roundtrip_on_disposable_database():
    root = Path(__file__).resolve().parent.parent
    base = make_url(os.environ["DATABASE_URL"])
    name = f"gigveyro_notification_migration_{uuid.uuid4().hex[:10]}"
    assert re.fullmatch(r"[A-Za-z0-9_]+", name)
    admin = await asyncpg.connect(
        base.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    )
    await admin.execute(f'CREATE DATABASE "{name}"')
    try:
        url = base.set(database=name)
        database_url = url.render_as_string(hide_password=False)
        env = {
            **os.environ,
            "APP_ENV": "test",
            "DEBUG": "false",
            "DATABASE_URL": database_url,
        }

        async def migrate(*arguments: str) -> None:
            await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "alembic", *arguments],
                cwd=root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

        await migrate("upgrade", "0027")
        connection = await asyncpg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False)
        )
        account_id = uuid.uuid4()
        notification_id = uuid.uuid4()
        try:
            await connection.execute(
                "INSERT INTO accounts (id, username, password_hash, role, full_name) "
                "VALUES ($1, $2, $3, 'user', $4)",
                account_id,
                f"migration_{uuid.uuid4().hex[:8]}",
                "not-a-real-password-hash",
                "Migration Test",
            )
            await connection.execute(
                "INSERT INTO notifications "
                "(id, account_id, type, title, message, is_read, in_app_visible) "
                "VALUES ($1, $2, 'SECURITY_EVENT', $3, $4, false, true)",
                notification_id,
                account_id,
                "Legacy title",
                "Legacy body",
            )
        finally:
            await connection.close()

        for arguments in (
            ("upgrade", "0028"),
            ("downgrade", "0027"),
            ("upgrade", "0028"),
        ):
            await migrate(*arguments)

        connection = await asyncpg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False)
        )
        try:
            row = await connection.fetchrow(
                "SELECT title, message, message_key, message_params FROM notifications WHERE id=$1",
                notification_id,
            )
            assert dict(row) == {
                "title": "Legacy title",
                "message": "Legacy body",
                "message_key": None,
                "message_params": None,
            }
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == "0028"
            assert await connection.fetchval("SELECT to_regclass('ix_notifications_message_key')")
        finally:
            await connection.close()
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()
