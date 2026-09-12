from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_compose_has_fail_closed_production_topology():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert {"postgres", "redis", "migrate", "backend", "worker", "frontend", "nginx"} <= set(
        services
    )
    for name in ("postgres", "redis", "backend", "frontend"):
        assert "ports" not in services[name]
    assert services["nginx"]["ports"] == ["${HTTP_PORT:-80}:80"]
    assert services["frontend"]["environment"]["BACKEND_API_URL"] == "http://backend:8000"
    for name in ("migrate", "backend", "worker"):
        environment = services[name]["environment"]
        assert environment["APP_ENV"] == "production"
        assert environment["DEBUG"] == "false"
        assert environment["PAYOUT_ENABLED"] == "false"
        assert environment["PAYOUT_PROVIDER_MODE"] == "disabled"
        assert environment["BYBIT_WRITE_ENABLED"] == "false"
    assert services["backend"]["depends_on"]["migrate"]["condition"] == (
        "service_completed_successfully"
    )
    assert services["redis"]["command"].endswith("--maxmemory-policy noeviction\n")


def test_nginx_preserves_bff_and_websocket_security_boundaries():
    config = (ROOT / "nginx" / "nginx.conf").read_text(encoding="utf-8")
    assert "proxy_pass http://frontend;" in config
    assert "location /api/v1/ws" in config
    assert 'proxy_set_header Upgrade    $http_upgrade;' in config
    assert 'proxy_set_header Connection "upgrade";' in config
    assert "Content-Security-Policy" in config
    assert "deny all;" in config
    assert 'add_header Strict-Transport-Security "' not in config


def test_images_and_env_templates_do_not_bake_runtime_secrets():
    backend_dockerfile = (ROOT / "GIGVEYRO_Backend" / "Dockerfile").read_text(encoding="utf-8")
    frontend_dockerfile = (ROOT / "gigveyro-frontend" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "USER appuser" in backend_dockerfile
    assert "USER nextjs" in frontend_dockerfile
    assert "COPY .env" not in backend_dockerfile + frontend_dockerfile
    production = (ROOT / "GIGVEYRO_Backend" / ".env.production.example").read_text(
        encoding="utf-8"
    )
    assert "APP_ENV=production" in production
    assert "DEBUG=false" in production
    assert "PAYOUT_ENABLED=false" in production
    assert "PAYOUT_PROVIDER_MODE=disabled" in production
    assert "BYBIT_WRITE_ENABLED=false" in production


def test_dockerignore_excludes_local_password_helper():
    dockerignore = (ROOT / "GIGVEYRO_Backend" / ".dockerignore").read_text(encoding="utf-8")
    assert "reset_owner_password.py" in dockerignore


def test_restore_requires_exact_target_confirmation():
    restore = (ROOT / "scripts" / "restore_db.sh").read_text(encoding="utf-8")
    assert 'RESTORE_CONFIRM_TARGET="${RESTORE_CONFIRM_TARGET:-}"' in restore
    assert '"${RESTORE_CONFIRM_TARGET}" != "${TARGET_DB}"' in restore
    assert "sleep 5" not in restore
