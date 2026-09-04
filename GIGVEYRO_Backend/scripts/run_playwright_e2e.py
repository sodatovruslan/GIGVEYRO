"""Run Playwright against disposable PostgreSQL and an isolated Redis namespace."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

import asyncpg
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "GIGVEYRO_Backend"
FRONTEND = ROOT / "gigveyro-frontend"
BACKEND_PORT = 8100
FRONTEND_PORT = 3100
PASSWORD = "E2e-Only-Password-42"
TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
TOTP_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


def executable(name: str) -> str:
    value = f"{name}.cmd" if os.name == "nt" else name
    found = shutil.which(value)
    if not found:
        raise RuntimeError(f"Required executable is unavailable: {value}")
    return found


def assert_port_free(port: int) -> None:
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"Refusing to reuse occupied E2E port {port}")


async def database(action: str, admin_url: str, name: str) -> None:
    connection = await asyncpg.connect(admin_url)
    try:
        if action == "create":
            exists = await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
            if exists:
                raise RuntimeError(f"Refusing to replace existing database {name}")
            await connection.execute(f'CREATE DATABASE "{name}"')
        else:
            await connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await connection.close()


async def cleanup_redis(url: str, prefix: str) -> None:
    try:
        import redis.asyncio as redis

        client = redis.from_url(url, socket_connect_timeout=2)
        async for key in client.scan_iter(match=f"{prefix}:*"):
            await client.delete(key)
        await client.aclose()
    except Exception:
        pass


def wait_for(url: str, timeout: float, processes: list[subprocess.Popen]) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for process in processes:
            if process.poll() is not None:
                raise RuntimeError(f"E2E service exited early with code {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for {url}")


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)


def start(command: list[str], cwd: Path, env: dict[str, str], log) -> subprocess.Popen:
    return subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=os.name != "nt",
    )


def main() -> int:
    assert_port_free(BACKEND_PORT)
    assert_port_free(FRONTEND_PORT)
    values = dotenv_values(BACKEND / ".env")
    base_database_url = os.environ.get("DATABASE_URL") or values.get("DATABASE_URL")
    if not base_database_url:
        raise RuntimeError("DATABASE_URL is required to derive the disposable E2E database")
    base_url = make_url(str(base_database_url))
    base_name = base_url.database or "gigveyro"
    database_name = f"{base_name[:38]}_e2e_{os.getpid()}_{uuid.uuid4().hex[:6]}"
    if not re.fullmatch(r"[A-Za-z0-9_]+", database_name):
        raise RuntimeError("Derived E2E database name contains unsafe characters")
    test_url = base_url.set(database=database_name)
    admin_url = base_url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    database_url = test_url.render_as_string(hide_password=False)
    redis_url = os.environ.get("REDIS_URL") or values.get("REDIS_URL") or "redis://127.0.0.1:6379/0"
    redis_prefix = f"gigapay:e2e:{uuid.uuid4().hex}"

    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "test",
            "PYTHONUTF8": "1",
            "DEBUG": "false",
            "DATABASE_URL": database_url,
            "REDIS_URL": str(redis_url),
            "REDIS_KEY_PREFIX": redis_prefix,
            "REALTIME_BROKER": "redis",
            "JWT_SECRET_KEY": "e2e-only-jwt-secret-key-at-least-32-characters",
            "TOTP_ENCRYPTION_KEY": TOTP_KEY,
            "E2E_PERSONA_PASSWORD": PASSWORD,
            "E2E_OWNER_TOTP_SECRET": TOTP_SECRET,
            "TELEGRAM_BOT_ENABLED": "false",
            "TELEGRAM_DELIVERY_ENABLED": "false",
            "PAYOUT_ENABLED": "false",
            "PAYOUT_PROVIDER_MODE": "disabled",
            "PAYOUT_SIMULATION_ENABLED": "false",
            "BYBIT_WRITE_ENABLED": "false",
            "DEPOSIT_PROVIDER_TYPE": "mock",
            "EXCHANGE_RATE_PROVIDER_TYPE": "fallback",
            "DOCS_ENABLED": "true",
            "LOGIN_RATE_LIMIT_REQUESTS": "100",
            "TWO_FACTOR_VERIFY_RATE_LIMIT_REQUESTS": "100",
            "DEFAULT_RATE_LIMIT_REQUESTS": "10000",
            "BACKEND_API_URL": f"http://127.0.0.1:{BACKEND_PORT}",
            "E2E_BASE_URL": f"http://localhost:{FRONTEND_PORT}",
            "NEXT_PUBLIC_REALTIME_URL": f"ws://127.0.0.1:{BACKEND_PORT}/api/v1/ws",
            "CORS_ALLOWED_ORIGINS": (
                f'["http://localhost:{FRONTEND_PORT}",'
                f'"http://127.0.0.1:{FRONTEND_PORT}"]'
            ),
        }
    )
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if os.name == "nt" and chrome.exists():
        environment["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"] = str(chrome)

    processes: list[subprocess.Popen] = []
    created = False
    with tempfile.TemporaryDirectory(prefix="gigapay-e2e-") as temp_dir:
        log_path = Path(temp_dir) / "services.log"
        try:
            asyncio.run(database("create", admin_url, database_name))
            created = True
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=BACKEND,
                env=environment,
                check=True,
            )
            subprocess.run(
                [sys.executable, "-m", "scripts.e2e_seed"],
                cwd=BACKEND,
                env=environment,
                check=True,
            )
            with log_path.open("w", encoding="utf-8") as service_log:
                processes.append(
                    start(
                        [
                            sys.executable,
                            "-m",
                            "uvicorn",
                            "app.main:app",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(BACKEND_PORT),
                        ],
                        BACKEND,
                        environment,
                        service_log,
                    )
                )
                wait_for(f"http://127.0.0.1:{BACKEND_PORT}/health/live", 60, processes)
                processes.append(
                    start(
                        [sys.executable, "worker_entrypoint.py"], BACKEND, environment, service_log
                    )
                )
                npm = executable("npm")
                processes.append(
                    start(
                        [
                            npm,
                            "run",
                            "dev",
                            "--",
                            "--webpack",
                            "--hostname",
                            "127.0.0.1",
                            "--port",
                            str(FRONTEND_PORT),
                        ],
                        FRONTEND,
                        environment,
                        service_log,
                    )
                )
                wait_for(f"http://127.0.0.1:{FRONTEND_PORT}/login", 120, processes)
                result = subprocess.run(
                    [executable("npx"), "playwright", "test", *sys.argv[1:]],
                    cwd=FRONTEND,
                    env=environment,
                    check=False,
                )
                if result.returncode:
                    print(
                        log_path.read_text(encoding="utf-8", errors="replace")[-8000:],
                        file=sys.stderr,
                    )
                return result.returncode
        except Exception as exc:
            if log_path.exists():
                print(
                    log_path.read_text(encoding="utf-8", errors="replace")[-8000:], file=sys.stderr
                )
            print(f"E2E harness failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        finally:
            for process in reversed(processes):
                stop_process(process)
            asyncio.run(cleanup_redis(str(redis_url), redis_prefix))
            if created:
                asyncio.run(database("drop", admin_url, database_name))


if __name__ == "__main__":
    raise SystemExit(main())
