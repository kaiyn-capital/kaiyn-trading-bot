import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_backup_restore_scripts_are_valid_sh():
    for script in [
        "scripts/backup_database.sh",
        "scripts/backup_loop.sh",
        "scripts/disaster_restore_from_r2.sh",
        "scripts/restore_latest_backup.sh",
    ]:
        subprocess.run(["sh", "-n", str(ROOT / script)], check=True)  # noqa: S603, S607


def test_db_backup_service_uses_shared_backup_script():
    compose = read_repo_file("compose.yml")
    coolify_compose = read_repo_file("compose.coolify.yml")

    assert "db-backup:" in compose
    assert "image: *bot-image" in compose
    assert "R2_BACKUP_ENABLED" in compose
    assert "BACKUP_ENCRYPTION_KEY" in compose
    assert "./scripts:/scripts:ro" in compose
    assert "BACKUP_LOCAL_KEEP_COUNT" in compose
    assert "/scripts/backup_loop.sh" in compose
    assert "image: ${BOT_IMAGE:?Set BOT_IMAGE in Coolify}" in coolify_compose
    assert "/app/scripts/backup_loop.sh" in coolify_compose


def test_production_compose_requires_database_credentials_and_binds_postgres_to_loopback():
    compose = read_repo_file("compose.yml")
    production_compose = read_repo_file("compose.prod.yml")
    makefile = read_repo_file("Makefile")
    ci = read_repo_file(".github/workflows/ci.yml")

    assert '"${POSTGRES_PORT:-127.0.0.1:5432}:5432"' in compose
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD for production}" in production_compose
    assert 'ports: !override\n      - "127.0.0.1:5432:5432"' in production_compose
    assert production_compose.count("DATABASE_URL: ${DATABASE_URL:?Set DATABASE_URL for production}") == 2
    assert "up-db-image:" in makefile
    assert '$(MAKE) up-db-image BOT_IMAGE="$(BOT_IMAGE)"' in makefile
    assert "compose-prod-check:" in makefile
    assert "run: make compose-prod-check" in ci


def test_backup_script_writes_manifest_and_ownerless_dump():
    script = read_repo_file("scripts/backup_database.sh")

    assert "umask 077" in script
    assert 'POSTGRES_PASSWORD="${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD}"' in script
    assert "--no-owner" in script
    assert "--no-privileges" in script
    assert "backup_manifest.json" in script
    assert "backup_status.json" in script
    assert ".sha256" in script
    assert "BACKUP_LOCAL_KEEP_COUNT" in script
    assert "R2_BACKUP_ENABLED" in script
    assert "r2_backup.py" in script
    assert " upload" in script


def test_restore_script_has_checksum_and_non_empty_database_guard():
    script = read_repo_file("scripts/restore_latest_backup.sh")

    assert "calc_sha256()" in script
    assert "CONFIRM_RESTORE=YES" in script
    assert "Target database is not empty" in script
    assert "drop schema if exists public cascade" in script
    assert "alembic upgrade head" in script
    assert "python -m app.main --check-db" in script


def test_makefile_exposes_manual_backup_and_restore_targets():
    makefile = read_repo_file("Makefile")

    assert "BOT_IMAGE_FILE ?= .bot_image" in makefile
    assert "RESOLVED_BOT_IMAGE" in makefile
    assert "BACKUP_COMPOSE" in makefile
    assert 'printf \'%s\\n\' "$(BOT_IMAGE)" > "$(BOT_IMAGE_FILE)"' in makefile
    assert "backup-now:" in makefile
    assert "r2-download-latest:" in makefile
    assert "restore-latest:" in makefile
    assert "disaster-restore:" in makefile
    assert "generate-backup-key:" in makefile
    assert "sh /scripts/backup_database.sh" in makefile
    assert "r2_backup.py download-latest" in makefile
    assert "sh scripts/restore_latest_backup.sh" in makefile


def test_backup_image_installs_postgres_client():
    dockerfile = read_repo_file("Dockerfile")

    assert "postgresql-client" in dockerfile


def test_deployed_bot_image_marker_is_ignored():
    gitignore = read_repo_file(".gitignore")

    assert ".bot_image" in gitignore
