import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_dev_simulate_route_not_mounted_when_app_env_is_production():
    """app/main.py only registers the DEV mock-transaction-ingestion router
    when settings.APP_ENV != "production". Since `settings`/`app` are
    singletons already imported by this test process under the dev .env,
    flipping APP_ENV here wouldn't re-evaluate that conditional - so this
    spawns a fresh interpreter with APP_ENV=production set before anything
    is imported, the same way a real production deployment would set it.
    """
    script = (
        "import os; os.environ['APP_ENV'] = 'production'; os.environ['DEBUG'] = 'false'; "
        "os.environ['ALLOW_MOCK_PROVIDERS_IN_PRODUCTION'] = 'true'; "
        "os.environ['DOCS_ENABLED'] = 'false'; os.environ['METRICS_ENABLED'] = 'false'; "
        "from app.main import app; "
        "schema = app.openapi(); "
        "paths = list(schema['paths'].keys()); "
        "print('DEV_ROUTE_PRESENT' if any('/dev/' in p for p in paths) else 'DEV_ROUTE_ABSENT')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=_PROJECT_ROOT,
    )

    assert "DEV_ROUTE_ABSENT" in result.stdout, result.stdout + result.stderr
    assert "DEV_ROUTE_PRESENT" not in result.stdout


def test_dev_simulate_route_is_mounted_in_development():
    """Sanity check for the test above: confirms the route genuinely does
    exist under the normal dev configuration, so "absent in production"
    is a real distinction and not just always-absent."""
    script = (
        "from app.main import app; "
        "schema = app.openapi(); "
        "paths = list(schema['paths'].keys()); "
        "print('DEV_ROUTE_PRESENT' if any('/dev/' in p for p in paths) else 'DEV_ROUTE_ABSENT')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=_PROJECT_ROOT,
    )

    assert "DEV_ROUTE_PRESENT" in result.stdout, result.stdout + result.stderr
