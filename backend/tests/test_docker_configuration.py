from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]


def test_compose_uses_narrow_contexts_and_required_services() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert {"frontend", "backend", "worker", "postgres", "redis", "minio", "minio-init"} <= services.keys()
    assert services["backend"]["build"] == "./backend"
    assert services["worker"]["build"] == "./backend"
    assert services["frontend"]["build"]["context"] == "./frontend"
    assert services["backend"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert services["backend"]["depends_on"]["redis"]["condition"] == "service_healthy"


def test_service_contexts_exclude_large_and_private_artifacts() -> None:
    backend_ignore = (ROOT / "backend" / ".dockerignore").read_text(encoding="utf-8")
    frontend_ignore = (ROOT / "frontend" / ".dockerignore").read_text(encoding="utf-8")
    for pattern in (".env", "**/.venv", "*.db", "*.parquet", ".data", "tests"):
        assert pattern in backend_ignore
    for pattern in (".env", "node_modules", ".next", "*.tsbuildinfo"):
        assert pattern in frontend_ignore
