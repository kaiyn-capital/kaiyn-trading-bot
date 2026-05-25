import importlib.util
import sys
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "r2_backup.py"

spec = importlib.util.spec_from_file_location("r2_backup_script", SCRIPT_PATH)
r2_backup = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["r2_backup_script"] = r2_backup
spec.loader.exec_module(r2_backup)


def test_r2_config_builds_default_endpoint_from_account_id():
    key = Fernet.generate_key().decode()

    config = r2_backup.R2Config.from_env(
        {
            "R2_ACCOUNT_ID": "abc123",
            "R2_BUCKET": "kaiyn-backups",
            "R2_ACCESS_KEY_ID": "access",
            "R2_SECRET_ACCESS_KEY": "secret",
            "BACKUP_ENCRYPTION_KEY": key,
        }
    )

    assert config.endpoint == "https://abc123.r2.cloudflarestorage.com"
    assert config.region == "auto"
    assert config.prefix == "kaiyn-trading-bot"


def test_r2_backup_encrypt_decrypt_roundtrip(tmp_path):
    key = Fernet.generate_key().decode()
    backup_file = tmp_path / "kaiyn_trading_bot_20260101_000000.sql.gz"
    backup_file.write_bytes(b"postgres dump bytes")

    encrypted = r2_backup.encrypt_backup(backup_file, key)
    decrypted = r2_backup.decrypt_backup(encrypted, key)

    assert encrypted != backup_file.read_bytes()
    assert decrypted == b"postgres dump bytes"


def test_r2_manifest_uses_encrypted_object_keys(tmp_path):
    key = Fernet.generate_key().decode()
    config = r2_backup.R2Config.from_env(
        {
            "R2_ENDPOINT": "https://example.r2.cloudflarestorage.com",
            "R2_BUCKET": "kaiyn-backups",
            "R2_ACCESS_KEY_ID": "access",
            "R2_SECRET_ACCESS_KEY": "secret",
            "R2_BACKUP_PREFIX": "prod",
            "BACKUP_ENCRYPTION_KEY": key,
        }
    )
    backup_file = tmp_path / "kaiyn_trading_bot_20260101_000000.sql.gz"
    backup_file.write_bytes(b"postgres dump bytes")
    checksum = r2_backup.sha256_file(backup_file)
    Path(f"{backup_file}.sha256").write_text(f"{checksum}  {backup_file.name}\n", encoding="utf-8")

    encrypted = r2_backup.encrypt_backup(backup_file, key)
    manifest = r2_backup.build_remote_manifest(
        config=config,
        file_path=backup_file,
        local_manifest={"timestamp": "2026-01-01T00:00:00Z", "database": "kaiyn_trading_bot"},
        encrypted_bytes=encrypted,
    )

    assert manifest["filename"] == backup_file.name
    assert manifest["object_key"] == f"prod/backups/{backup_file.name}.enc"
    assert manifest["manifest_key"] == f"prod/manifests/{backup_file.name}.json"
    assert manifest["latest_key"] == "prod/latest.json"
    assert manifest["sha256"] == checksum
    assert manifest["encrypted_sha256"] == r2_backup.sha256_bytes(encrypted)
