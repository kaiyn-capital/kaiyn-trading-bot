import importlib.util
from pathlib import Path


def load_revision_module():
    revision_path = (
        Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20260523_0008_user_position_cap_null.py"
    )
    spec = importlib.util.spec_from_file_location("user_position_cap_null", revision_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_user_position_cap_migration_clears_existing_user_caps(monkeypatch):
    revision = load_revision_module()
    statements = []

    monkeypatch.setattr(revision.op, "execute", statements.append)

    revision.upgrade()

    assert statements == ["UPDATE users SET max_position_size = NULL"]


def test_user_position_cap_migration_downgrade_restores_legacy_default(monkeypatch):
    revision = load_revision_module()
    statements = []

    monkeypatch.setattr(revision.op, "execute", statements.append)

    revision.downgrade()

    assert statements == ["UPDATE users SET max_position_size = 1000 WHERE max_position_size IS NULL"]
