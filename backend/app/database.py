"""SQLAlchemy engine / session management. Schema is PostgreSQL-compatible and
also runs on SQLite (for zero-setup local demos) via the DATABASE_URL setting."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


_engine_kwargs: dict = {"pool_pre_ping": True}
if settings.is_sqlite:
    _engine_kwargs = {"connect_args": {"check_same_thread": False}}

engine = create_engine(settings.DATABASE_URL, **_engine_kwargs)

if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):  # pragma: no cover
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _sync_schema() -> None:
    """Bring pre-existing tables up to date with the ORM model (idempotent).

    `create_all()` only creates tables that do not exist yet — it never alters an
    existing table. If a model column is added after a database was first created
    (there is no migration tool in this prototype), every query touching that
    table fails with an UndefinedColumn error at startup. This pass adds any
    missing columns / constraints so an old database is upgraded in place instead
    of crashing the API.
    """
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text

    with engine.begin() as conn:
        inspector = sa_inspect(conn)
        existing_tables = set(inspector.get_table_names())
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue
                # Add the column as NULLable even for model NOT NULL columns:
                # SQLAlchemy always supplies python-side defaults on insert, and
                # a strict NOT NULL ADD COLUMN would fail on a non-empty table.
                ddl = col.type.compile(dialect=engine.dialect)
                conn.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}')
                )
                print(f"[schema] added missing column {table.name}.{col.name}")
            if table.name == "rule_results":
                # Ensure the four-state CHECK constraint exists (fresh create_all
                # already includes it; older databases need it backfilled).
                existing_checks = {c["name"] for c in inspector.get_check_constraints(table.name)}
                if "ck_rule_results_result_four_states" not in existing_checks:
                    try:
                        conn.execute(
                            text(
                                "ALTER TABLE rule_results ADD CONSTRAINT "
                                "ck_rule_results_result_four_states CHECK "
                                "(result IN ('COMPLIANT', 'NON_COMPLIANT', "
                                "'MANUAL_REVIEW', 'POTENTIAL_NON_COMPLIANCE'))"
                            )
                        )
                        print("[schema] added rule_results four-state CHECK constraint")
                    except Exception as exc:  # pragma: no cover - legacy data may violate it
                        print(f"[schema] skipped four-state CHECK constraint: {exc}")


def init_db() -> None:
    """Create tables, upgrade any pre-existing tables, then seed demo data."""
    from . import models  # noqa: F401  (register models on Base)
    from .seed import seed_all

    Base.metadata.create_all(bind=engine)
    _sync_schema()
    with SessionLocal() as db:
        seed_all(db)
