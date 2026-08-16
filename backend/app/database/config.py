"""Database configuration and session management.

The default database is SQLite (``sqlite+aiosqlite:///./audio_analyzer.db``).
PostgreSQL is still supported through the ``DATABASE_URL`` environment
variable (e.g. ``postgresql+asyncpg://user:pass@host:5432/audio_analyzer``).

The database stores metadata only — audio files live on the filesystem.
"""
import os

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./audio_analyzer.db")

# Convert sync postgres URL to async driver if needed
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("DEBUG", "false").lower() == "true",
    poolclass=NullPool,
    future=True,
    connect_args=connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db():
    """Dependency for getting async database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_schema_updates()


# Columns added to pre-existing tables after the initial schema was created.
# ``create_all`` only creates missing tables, so new columns on existing tables
# must be added explicitly for both SQLite and PostgreSQL databases.
#
# Type names must be valid for BOTH dialects: SQLite accepts any name, but
# PostgreSQL is strict (e.g. ``DATETIME`` is not a Postgres type — use
# ``TIMESTAMP``).
_SCHEMA_ADDITIONS = {
    "songs": [
        ("duration_seconds", "INTEGER"),
        ("artist_id", "INTEGER"),
    ],
    "albums": [
        ("artist_id", "INTEGER"),
    ],
    "crawl_jobs": [
        ("total_resources", "INTEGER"),
        ("failed_urls_count", "INTEGER"),
        ("skipped_urls_count", "INTEGER"),
        ("current_year", "INTEGER"),
        ("current_album", "VARCHAR(300)"),
        ("current_song", "VARCHAR(300)"),
        ("progress_percentage", "FLOAT"),
        ("started_at", "TIMESTAMP"),
        ("error_message", "TEXT"),
    ],
    "archives": [
        ("crawl_job_id", "INTEGER"),
        ("status", "VARCHAR(20)"),
        ("error_message", "TEXT"),
        ("completed_at", "TIMESTAMP"),
    ],
}


async def ensure_schema_updates():
    """Idempotently add columns that were introduced after the base schema.

    Works on SQLite and PostgreSQL. Missing tables/columns are skipped; the
    operation never drops or alters existing data.

    Each ``ALTER`` runs in its own transaction: PostgreSQL aborts the whole
    transaction when one statement fails, which previously caused every later
    migration (e.g. the ``archives`` columns) to be silently skipped.
    """
    from sqlalchemy import text
    import structlog

    logger = structlog.get_logger()
    dialect = engine.dialect.name  # 'postgresql' | 'sqlite' | ...

    async with engine.connect() as conn:
        existing_by_table = {}
        for table in _SCHEMA_ADDITIONS:
            if dialect == "postgresql":
                # Schema-qualified so same-named tables in other schemas can
                # never produce false "column exists" matches.
                result = await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = :t AND table_schema = current_schema()"
                    ).bindparams(t=table)
                )
                existing_by_table[table] = {row[0] for row in result.fetchall()}
            else:
                try:
                    result = await conn.execute(text(f'PRAGMA table_info("{table}")'))
                    existing_by_table[table] = {row[1] for row in result.fetchall()}
                except Exception as e:
                    logger.warning(
                        "Schema migration: table not visible, skipping",
                        table=table, error=str(e),
                    )
                    existing_by_table[table] = set()

    for table, columns in _SCHEMA_ADDITIONS.items():
        existing = existing_by_table.get(table, set())
        if not existing:
            # Table does not exist (or is not visible) — nothing to migrate.
            continue

        for col, coltype in columns:
            if col in existing:
                continue
            try:
                async with engine.begin() as conn:
                    await conn.execute(
                        text(f'ALTER TABLE "{table}" ADD COLUMN "{col}" {coltype}')
                    )
            except Exception as e:
                # Column may have been added concurrently / dialect quirks.
                # Log instead of swallowing so silent migration gaps are visible.
                logger.warning(
                    "Schema migration column skipped",
                    table=table, column=col, error=str(e),
                )
