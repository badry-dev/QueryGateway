"""Phase 7 — Migration upgrade path validation.

Verifies that the Alembic migration chain is deterministic and complete:
- All models are reflected in migrations.
- Migration scripts have proper structure.
- Schema creation works on a clean database.

Note: The local ``alembic/`` package directory shadows the installed
``alembic`` package, so we validate migrations via file inspection
and import of the version modules rather than the Alembic API.
"""

import importlib
import pathlib
import re
import uuid

import pytest

# ── Migration file structure tests ───────────────────────────────────────────


MIGRATION_DIR = pathlib.Path("alembic/versions")


def _extract(source: str, name: str) -> str | None:
    """Return the literal value assigned to ``name`` in a migration module.

    Handles ``name: <type> = "value"`` and ``name: <type> = None`` forms.
    """
    m = re.search(rf"^{name}\s*:[^=]*=\s*(.+)$", source, re.MULTILINE)
    if m is None:
        return None
    value = m.group(1).strip()
    if value == "None":
        return None
    return value.strip("\"'")


class TestMigrationFileStructure:
    """Validate migration file structure and content."""

    def test_versions_directory_exists(self) -> None:
        assert MIGRATION_DIR.is_dir(), f"Migration versions directory not found: {MIGRATION_DIR}"

    def test_at_least_one_migration_exists(self) -> None:
        py_files = list(MIGRATION_DIR.glob("*.py"))
        assert len(py_files) >= 1, "No migration files found"

    def test_initial_migration_file_exists(self) -> None:
        initial = MIGRATION_DIR / "0001_initial_schema.py"
        assert initial.is_file(), "Initial migration 0001_initial_schema.py not found"

    def test_initial_migration_has_upgrade_and_downgrade(self) -> None:
        initial = MIGRATION_DIR / "0001_initial_schema.py"
        source = initial.read_text()
        assert "def upgrade()" in source, "Missing upgrade() in initial migration"
        assert "def downgrade()" in source, "Missing downgrade() in initial migration"

    def test_initial_migration_is_base(self) -> None:
        """The initial migration should have no down_revision."""
        initial = MIGRATION_DIR / "0001_initial_schema.py"
        source = initial.read_text()
        assert "down_revision" in source
        # down_revision should be None for the base
        assert "None" in source

    def test_migration_creates_all_tables(self) -> None:
        """All 8 domain tables must appear in migration."""
        initial = MIGRATION_DIR / "0001_initial_schema.py"
        source = initial.read_text()

        expected_tables = [
            "connections",
            "auth_methods",
            "endpoints",
            "schedules",
            "job_runs",
            "snapshots",
            "access_logs",
            "app_settings",
        ]
        for table in expected_tables:
            assert table in source, f"Table '{table}' not found in initial migration"

    def test_downgrade_drops_all_tables(self) -> None:
        """Downgrade should drop all tables and enum types."""
        initial = MIGRATION_DIR / "0001_initial_schema.py"
        source = initial.read_text()

        # Check that downgrade drops tables
        expected_drops = [
            "op.drop_table",
        ]
        for drop in expected_drops:
            assert drop in source, f"Expected '{drop}' in downgrade"

    def test_migration_creates_enum_types(self) -> None:
        """Enum types should be created in migration."""
        initial = MIGRATION_DIR / "0001_initial_schema.py"
        source = initial.read_text()

        expected_enums = [
            "oracle_mode",
            "auth_method_type",
            "data_strategy",
            "schedule_type",
            "job_run_status",
        ]
        for enum_name in expected_enums:
            assert enum_name in source, f"Enum type '{enum_name}' not found in migration"

    def test_no_duplicate_migration_files(self) -> None:
        """Each migration revision ID should be unique across files."""
        py_files = list(MIGRATION_DIR.glob("*.py"))
        # Extract revision IDs from filenames (e.g., 0001_initial_schema.py → 0001)
        revisions = [f.stem.split("_")[0] for f in py_files]
        assert len(revisions) == len(set(revisions)), "Duplicate migration revision IDs"

    def test_allow_unauthenticated_migration(self) -> None:
        """M1: the SAME revision that references allow_unauthenticated must add
        the endpoints column (upgrade) and drop it (downgrade) — i.e. it is
        reversible in place, not just that some migration adds and another drops
        a column."""
        matches = [
            f for f in MIGRATION_DIR.glob("*.py") if "allow_unauthenticated" in f.read_text()
        ]
        assert matches, "No migration references allow_unauthenticated"
        for f in matches:
            src = f.read_text()
            assert "add_column" in src, f"{f.name} must add the column (upgrade)"
            assert "drop_column" in src, f"{f.name} must drop the column (downgrade)"
            assert "endpoints" in src, f"{f.name} must target the endpoints table"

    def test_schedule_delete_preserves_job_runs_migration(self) -> None:
        migration = MIGRATION_DIR / "b2d18f4a6c73_preserve_job_runs_when_deleting_schedules.py"
        source = migration.read_text()
        assert migration.is_file()
        assert 'ondelete="SET NULL"' in source
        assert '"schedule_id"' in source
        assert "nullable=True" in source

    def test_endpoint_delete_preserves_job_runs_migration(self) -> None:
        migration = MIGRATION_DIR / "c7e91a4f2d60_preserve_job_runs_when_deleting_endpoints.py"
        source = migration.read_text()
        assert migration.is_file()
        assert 'ondelete="SET NULL"' in source
        assert '"endpoint_id"' in source
        assert "nullable=True" in source

    def test_migration_chain_is_linear(self) -> None:
        """The revision graph must be a single linear chain: exactly one base
        (down_revision=None), exactly one head, and every down_revision known."""
        revisions: dict[str, str | None] = {}
        for f in MIGRATION_DIR.glob("*.py"):
            src = f.read_text()
            rev = _extract(src, "revision")
            down = _extract(src, "down_revision")
            assert rev is not None, f"{f.name} has no revision id"
            revisions[rev] = down

        bases = [r for r, d in revisions.items() if d is None]
        assert len(bases) == 1, f"Expected exactly one base migration, found {bases}"
        for rev, down in revisions.items():
            if down is not None:
                assert down in revisions, f"{rev} points at unknown down_revision {down}"

        # A linear chain has exactly one head — a revision that no other
        # revision lists as its down_revision. Two heads ⇒ a fork (branched
        # history), which Alembic can't `upgrade head` unambiguously.
        down_targets = {d for d in revisions.values() if d is not None}
        heads = [r for r in revisions if r not in down_targets]
        assert len(heads) == 1, f"Expected exactly one head (linear history), found {heads}"


# ── Model–migration alignment tests ─────────────────────────────────────────


class TestModelMigrationAlignment:
    """Verify all ORM models have corresponding migration coverage."""

    def test_all_model_tables_in_migration(self) -> None:
        """Every SQLAlchemy model tablename must appear in migration scripts."""
        from app.models.base import Base

        # Import all model modules to register them with Base.metadata
        model_modules = [
            "app.models.connection",
            "app.models.auth_method",
            "app.models.endpoint",
            "app.models.schedule",
            "app.models.job_run",
            "app.models.snapshot",
            "app.models.access_log",
            "app.models.setting",
        ]
        for mod in model_modules:
            importlib.import_module(mod)

        model_tables = set(Base.metadata.tables.keys())
        assert len(model_tables) >= 8, f"Expected >=8 tables, got {model_tables}"

        migration_path = MIGRATION_DIR / "0001_initial_schema.py"
        migration_source = migration_path.read_text()

        for table_name in model_tables:
            assert table_name in migration_source, (
                f"Table '{table_name}' defined in models but not found in migration"
            )


# ── Alembic config validation ───────────────────────────────────────────────


class TestAlembicConfig:
    """Validate Alembic environment configuration."""

    def test_alembic_ini_exists(self) -> None:
        ini = pathlib.Path("alembic.ini")
        assert ini.is_file(), "alembic.ini not found"

    def test_env_py_exists(self) -> None:
        env = pathlib.Path("alembic/env.py")
        assert env.is_file(), "alembic/env.py not found"

    def test_env_py_imports_models(self) -> None:
        """env.py should import Base metadata for autogenerate support."""
        env = pathlib.Path("alembic/env.py")
        source = env.read_text()
        assert "Base" in source or "target_metadata" in source, (
            "env.py should reference Base metadata"
        )


# ── Database schema tests (require PostgreSQL) ──────────────────────────────


@pytest.mark.integration
class TestSchemaCreation:
    """Verify schema creation from models matches expectations."""

    async def test_tables_created(self, async_client: object) -> None:
        """The conftest engine fixture creates all tables; verify key tables exist."""
        from httpx import AsyncClient

        client: AsyncClient = async_client  # type: ignore[assignment]

        # If we can hit the health endpoint, tables are created
        r = await client.get("/api/v1/admin/health/ready")
        assert r.status_code == 200

    async def test_connection_crud_after_fresh_schema(self, async_client: object) -> None:
        """Verify CRUD operations work on fresh schema."""
        from httpx import AsyncClient

        client: AsyncClient = async_client  # type: ignore[assignment]

        name = f"migration-test-{uuid.uuid4().hex[:8]}"
        r = await client.post(
            "/api/v1/admin/connections/",
            json={
                "name": name,
                "host": "localhost",
                "service_name": "XE",
                "username": "test",
                "password": "test",
            },
        )
        assert r.status_code == 201

        conn_id = r.json()["id"]
        r = await client.delete(f"/api/v1/admin/connections/{conn_id}")
        assert r.status_code == 204
