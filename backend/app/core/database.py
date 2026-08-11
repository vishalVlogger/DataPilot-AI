from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import Base


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    try:
        engine = create_engine(url, pool_pre_ping=True, **kwargs)
        if url.startswith("sqlite"):
            @event.listens_for(engine, "connect")
            def enable_foreign_keys(connection, _record):
                cursor = connection.cursor(); cursor.execute("PRAGMA foreign_keys=ON"); cursor.close()
        return engine
    except Exception as exc:
        raise AppError("Metadata database is unavailable.", "DATABASE_UNAVAILABLE", 503) from exc


def init_database() -> None:
    try:
        Base.metadata.create_all(get_engine())
    except Exception as exc:
        raise AppError("Metadata database is unavailable.", "DATABASE_UNAVAILABLE", 503) from exc


def session_scope() -> Session:
    init_database()
    return sessionmaker(bind=get_engine(), expire_on_commit=False)()


def reset_database_engine() -> None:
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
