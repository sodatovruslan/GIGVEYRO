import asyncio
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
from sqlalchemy.engine import make_url


async def test_deposit_reconciliation_migration_preserves_legacy_unmatched_row():
    root = Path(__file__).resolve().parent.parent
    base = make_url(os.environ["DATABASE_URL"])
    name = f"gigveyro_reconciliation_migration_{uuid.uuid4().hex[:10]}"
    assert re.fullmatch(r"[A-Za-z0-9_]+", name)
    admin = await asyncpg.connect(
        base.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    )
    await admin.execute(f'CREATE DATABASE "{name}"')
    try:
        url = base.set(database=name)
        database_url = url.render_as_string(hide_password=False)
        env = {**os.environ, "APP_ENV": "test", "DEBUG": "false", "DATABASE_URL": database_url}

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

        await migrate("upgrade", "0028")
        connection = await asyncpg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False)
        )
        transfer_id = uuid.uuid4()
        try:
            await connection.execute(
                "INSERT INTO unmatched_transfers "
                "(id, tx_hash, provider_event_id, from_address, to_address, amount, "
                "asset_contract, correlation_status, reason) "
                "VALUES ($1, 'legacy-tx', 'legacy-event', 'sender', 'recipient', 42, "
                "'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t', 'UNMATCHED', 'legacy row')",
                transfer_id,
            )
        finally:
            await connection.close()

        for arguments in (
            ("upgrade", "0029"),
            ("downgrade", "0028"),
            ("upgrade", "0029"),
        ):
            await migrate(*arguments)

        connection = await asyncpg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False)
        )
        try:
            row = await connection.fetchrow(
                "SELECT tx_hash, provider, network, confirmations, is_finalized, "
                "reconciliation_status FROM unmatched_transfers WHERE id=$1",
                transfer_id,
            )
            assert dict(row) == {
                "tx_hash": "legacy-tx",
                "provider": "unknown",
                "network": "TRC20",
                "confirmations": 0,
                "is_finalized": True,
                "reconciliation_status": "PENDING",
            }
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == "0029"
            assert await connection.fetchval("SELECT to_regclass('deposit_reconciliation_actions')")
        finally:
            await connection.close()
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()
