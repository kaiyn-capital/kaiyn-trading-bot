#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken

DEFAULT_PREFIX = "kaiyn-trading-bot"
DEFAULT_REGION = "auto"
SERVICE = "s3"
LATEST_MANIFEST_NAME = "latest.json"


class R2BackupError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class R2Config:
    endpoint: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    encryption_key: str
    prefix: str = DEFAULT_PREFIX
    region: str = DEFAULT_REGION

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> R2Config:
        source = os.environ if env is None else env
        endpoint = (source.get("R2_ENDPOINT") or "").strip().rstrip("/")
        account_id = (source.get("R2_ACCOUNT_ID") or "").strip()
        if not endpoint and account_id:
            endpoint = f"https://{account_id}.r2.cloudflarestorage.com"

        config = cls(
            endpoint=endpoint,
            bucket=(source.get("R2_BUCKET") or "").strip(),
            access_key_id=(source.get("R2_ACCESS_KEY_ID") or "").strip(),
            secret_access_key=(source.get("R2_SECRET_ACCESS_KEY") or "").strip(),
            encryption_key=(source.get("BACKUP_ENCRYPTION_KEY") or "").strip(),
            prefix=(source.get("R2_BACKUP_PREFIX") or DEFAULT_PREFIX).strip("/"),
            region=(source.get("R2_REGION") or DEFAULT_REGION).strip(),
        )
        config.validate()
        return config

    def validate(self) -> None:
        missing = []
        if not self.endpoint:
            missing.append("R2_ENDPOINT or R2_ACCOUNT_ID")
        if not self.bucket:
            missing.append("R2_BUCKET")
        if not self.access_key_id:
            missing.append("R2_ACCESS_KEY_ID")
        if not self.secret_access_key:
            missing.append("R2_SECRET_ACCESS_KEY")
        if not self.encryption_key:
            missing.append("BACKUP_ENCRYPTION_KEY")
        if missing:
            raise R2BackupError(f"Missing required R2 backup settings: {', '.join(missing)}")
        try:
            Fernet(self.encryption_key.encode())
        except (TypeError, ValueError) as exc:
            raise R2BackupError("BACKUP_ENCRYPTION_KEY must be a Fernet key") from exc


class R2Client:
    def __init__(self, config: R2Config, timeout: float = 60.0):
        self.config = config
        self.timeout = timeout
        parsed = urlparse(config.endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise R2BackupError("R2_ENDPOINT must be an https URL")
        self.host = parsed.netloc

    def put_bytes(self, key: str, body: bytes, content_type: str) -> None:
        self._request("PUT", key, body=body, content_type=content_type)

    def get_bytes(self, key: str) -> bytes:
        return self._request("GET", key, body=b"", content_type=None)

    def _request(
        self,
        method: str,
        key: str,
        *,
        body: bytes,
        content_type: str | None,
    ) -> bytes:
        canonical_uri = self._canonical_uri(key)
        url = f"{self.config.endpoint}{canonical_uri}"
        payload_hash = hashlib.sha256(body).hexdigest()
        amz_date = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        headers = self._signed_headers(
            method=method,
            canonical_uri=canonical_uri,
            payload_hash=payload_hash,
            amz_date=amz_date,
        )
        if content_type:
            headers["content-type"] = content_type

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            raise R2BackupError(f"R2 {method} failed before response: {exc}") from exc

        if response.status_code >= 400:
            message = response.text.replace("\n", " ")[:500]
            raise R2BackupError(f"R2 {method} {key} failed: HTTP {response.status_code} {message}")
        return response.content

    def _canonical_uri(self, key: str) -> str:
        path = f"/{self.config.bucket}/{key.lstrip('/')}"
        return quote(path, safe="/-_.~")

    def _signed_headers(
        self,
        *,
        method: str,
        canonical_uri: str,
        payload_hash: str,
        amz_date: str,
    ) -> dict[str, str]:
        date_stamp = amz_date[:8]
        credential_scope = f"{date_stamp}/{self.config.region}/{SERVICE}/aws4_request"
        canonical_headers = f"host:{self.host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amz_date}\n"
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_request = "\n".join(
            [
                method,
                canonical_uri,
                "",
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )
        signature = hmac.new(
            _signing_key(self.config.secret_access_key, date_stamp, self.config.region, SERVICE),
            string_to_sign.encode(),
            hashlib.sha256,
        ).hexdigest()
        authorization = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.config.access_key_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )
        return {
            "authorization": authorization,
            "host": self.host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }


def _signing_key(secret_access_key: str, date_stamp: str, region: str, service: str) -> bytes:
    date_key = hmac.new(f"AWS4{secret_access_key}".encode(), date_stamp.encode(), hashlib.sha256).digest()
    date_region_key = hmac.new(date_key, region.encode(), hashlib.sha256).digest()
    date_region_service_key = hmac.new(date_region_key, service.encode(), hashlib.sha256).digest()
    return hmac.new(date_region_service_key, b"aws4_request", hashlib.sha256).digest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return data if isinstance(data, dict) else {}


def write_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def read_checksum(path: Path) -> str | None:
    checksum_path = Path(f"{path}.sha256")
    if not checksum_path.exists():
        return None
    return checksum_path.read_text(encoding="utf-8").split()[0]


def object_key(prefix: str, *parts: str) -> str:
    clean_parts = [part.strip("/") for part in parts if part.strip("/")]
    if prefix:
        return "/".join([prefix.strip("/"), *clean_parts])
    return "/".join(clean_parts)


def encrypt_backup(path: Path, key: str) -> bytes:
    return Fernet(key.encode()).encrypt(path.read_bytes())


def decrypt_backup(data: bytes, key: str) -> bytes:
    try:
        return Fernet(key.encode()).decrypt(data)
    except InvalidToken as exc:
        raise R2BackupError("Failed to decrypt R2 backup with BACKUP_ENCRYPTION_KEY") from exc


def build_remote_manifest(
    *,
    config: R2Config,
    file_path: Path,
    local_manifest: dict[str, Any],
    encrypted_bytes: bytes,
) -> dict[str, Any]:
    plaintext_sha256 = sha256_file(file_path)
    checksum_sha256 = read_checksum(file_path)
    if checksum_sha256 and checksum_sha256 != plaintext_sha256:
        raise R2BackupError(f"Local checksum mismatch before upload: {file_path}")

    encrypted_name = f"{file_path.name}.enc"
    backup_key = object_key(config.prefix, "backups", encrypted_name)
    manifest_key = object_key(config.prefix, "manifests", f"{file_path.name}.json")
    latest_key = object_key(config.prefix, LATEST_MANIFEST_NAME)
    uploaded_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "status": "success",
        "timestamp": local_manifest.get("timestamp") or uploaded_at,
        "uploaded_at": uploaded_at,
        "filename": file_path.name,
        "sha256": plaintext_sha256,
        "size_bytes": file_path.stat().st_size,
        "database": local_manifest.get("database"),
        "encryption": "fernet",
        "encrypted_filename": encrypted_name,
        "encrypted_sha256": sha256_bytes(encrypted_bytes),
        "encrypted_size_bytes": len(encrypted_bytes),
        "bucket": config.bucket,
        "object_key": backup_key,
        "manifest_key": manifest_key,
        "latest_key": latest_key,
    }


def upload_backup(args: argparse.Namespace) -> int:
    config = R2Config.from_env()
    client = R2Client(config)
    file_path = Path(args.file)
    if not file_path.is_file():
        raise R2BackupError(f"Backup file does not exist: {file_path}")

    local_manifest = read_json_file(Path(args.manifest)) if args.manifest else {}
    encrypted_bytes = encrypt_backup(file_path, config.encryption_key)
    remote_manifest = build_remote_manifest(
        config=config,
        file_path=file_path,
        local_manifest=local_manifest,
        encrypted_bytes=encrypted_bytes,
    )
    manifest_bytes = json.dumps(remote_manifest, ensure_ascii=False, separators=(",", ":")).encode()

    client.put_bytes(remote_manifest["object_key"], encrypted_bytes, "application/octet-stream")
    client.put_bytes(remote_manifest["manifest_key"], manifest_bytes, "application/json")
    client.put_bytes(remote_manifest["latest_key"], manifest_bytes, "application/json")

    if args.status_output:
        write_json_file(Path(args.status_output), remote_manifest)
    sys.stdout.write(f"Uploaded encrypted backup to R2: {remote_manifest['object_key']}\n")
    return 0


def download_latest_backup(args: argparse.Namespace) -> int:
    config = R2Config.from_env()
    client = R2Client(config)
    latest_key = object_key(config.prefix, LATEST_MANIFEST_NAME)
    manifest = json.loads(client.get_bytes(latest_key).decode("utf-8"))
    if not isinstance(manifest, dict):
        raise R2BackupError("R2 latest manifest is invalid")

    backup_object_key = str(manifest.get("object_key") or "").strip()
    if not backup_object_key:
        raise R2BackupError("R2 latest manifest has no backup object key")
    encrypted_bytes = client.get_bytes(backup_object_key)
    expected_encrypted_sha = str(manifest.get("encrypted_sha256") or "")
    if expected_encrypted_sha and expected_encrypted_sha != sha256_bytes(encrypted_bytes):
        raise R2BackupError("Encrypted R2 backup checksum mismatch")

    plaintext = decrypt_backup(encrypted_bytes, config.encryption_key)
    expected_plaintext_sha = str(manifest.get("sha256") or "")
    if expected_plaintext_sha and expected_plaintext_sha != sha256_bytes(plaintext):
        raise R2BackupError("Decrypted R2 backup checksum mismatch")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = str(manifest.get("filename") or "").strip()
    if not filename or filename != Path(filename).name:
        raise R2BackupError("R2 latest manifest has invalid filename")
    output_path = output_dir / filename
    output_path.write_bytes(plaintext)
    checksum = sha256_bytes(plaintext)
    Path(f"{output_path}.sha256").write_text(f"{checksum}  {filename}\n", encoding="utf-8")

    local_manifest = dict(manifest)
    local_manifest["downloaded_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_json_file(output_dir / "backup_manifest.json", local_manifest)
    if args.status_output:
        write_json_file(Path(args.status_output), local_manifest)
    if args.filename_output:
        Path(args.filename_output).write_text(filename + "\n", encoding="utf-8")
    sys.stdout.write(f"Downloaded and decrypted R2 backup: {output_path}\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Upload and download encrypted PostgreSQL backups from Cloudflare R2")
    subparsers = parser.add_subparsers(dest="command", required=True)

    upload_parser = subparsers.add_parser("upload")
    upload_parser.add_argument("--file", required=True)
    upload_parser.add_argument("--manifest")
    upload_parser.add_argument("--status-output")
    upload_parser.set_defaults(func=upload_backup)

    download_parser = subparsers.add_parser("download-latest")
    download_parser.add_argument("--output-dir", required=True)
    download_parser.add_argument("--status-output")
    download_parser.add_argument("--filename-output")
    download_parser.set_defaults(func=download_latest_backup)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except (OSError, ValueError, json.JSONDecodeError, R2BackupError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
