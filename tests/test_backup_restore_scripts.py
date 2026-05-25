import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_backup_restore_scripts_are_valid_sh():
    for script in [
        "scripts/backup_database.sh",
        "scripts/backup_loop.sh",
        "scripts/restore_latest_backup.sh",
    ]:
        subprocess.run(["sh", "-n", str(ROOT / script)], check=True)  # noqa: S603, S607


def test_db_backup_service_uses_shared_backup_script():
    compose = read_repo_file("compose.yml")

    assert "./scripts:/scripts:ro" in compose
    assert "BACKUP_LOCAL_KEEP_COUNT" in compose
    assert "/scripts/backup_loop.sh" in compose


def test_backup_script_writes_manifest_and_ownerless_dump():
    script = read_repo_file("scripts/backup_database.sh")

    assert "--no-owner" in script
    assert "--no-privileges" in script
    assert "backup_manifest.json" in script
    assert "backup_status.json" in script
    assert ".sha256" in script
    assert "BACKUP_LOCAL_KEEP_COUNT" in script


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

    assert "backup-now:" in makefile
    assert "restore-latest:" in makefile
    assert "sh /scripts/backup_database.sh" in makefile
    assert "sh scripts/restore_latest_backup.sh" in makefile
