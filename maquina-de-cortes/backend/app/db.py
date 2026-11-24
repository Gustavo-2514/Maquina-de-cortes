from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_settings = get_settings()
engine = create_engine(
    f"sqlite:///{_settings.db_path}",
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record) -> None:
    # WAL permite que a API leia enquanto o worker escreve.
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def _add_missing_columns() -> None:
    """Migração mínima: `create_all` não altera tabelas existentes, então colunas novas dos modelos
    são adicionadas com ALTER TABLE (com o default do modelo). Não remove nem altera colunas."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl_type = col.type.compile(dialect=engine.dialect)
                default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                if default is None and not col.nullable:
                    default = 0 if ddl_type in ("INTEGER", "FLOAT", "BOOLEAN") else ""
                lit = "NULL" if default is None else (repr(default) if isinstance(default, str) else str(int(default) if isinstance(default, bool) else default))
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl_type} DEFAULT {lit}'))


def init_db() -> None:
    from . import models  # noqa: F401  (registra as tabelas)

    SQLModel.metadata.create_all(engine)
    _add_missing_columns()
    from .services.caption_styles import seed_builtin_styles

    seed_builtin_styles()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
