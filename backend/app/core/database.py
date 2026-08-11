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
        _ensure_legacy_tenant()
    except Exception as exc:
        raise AppError("Metadata database is unavailable.", "DATABASE_UNAVAILABLE", 503) from exc


def _ensure_legacy_tenant() -> None:
    from app.models import User, Workspace, WorkspaceMember
    settings = get_settings(); factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        if session.get(User, settings.legacy_user_id) is None:
            session.add(User(id=settings.legacy_user_id, email="legacy-local@datapilot.invalid", normalized_email="legacy-local@datapilot.invalid", password_hash="!", display_name="Legacy Local User", is_active=False))
        if session.get(Workspace, settings.legacy_workspace_id) is None:
            session.add(Workspace(id=settings.legacy_workspace_id, name="Legacy Local Workspace", slug=f"legacy-local-{settings.legacy_workspace_id[-8:]}", owner_user_id=settings.legacy_user_id, plan_code=settings.default_plan))
        session.flush()
        if session.get(WorkspaceMember, (settings.legacy_workspace_id, settings.legacy_user_id)) is None:
            session.add(WorkspaceMember(workspace_id=settings.legacy_workspace_id, user_id=settings.legacy_user_id, role="owner"))
        session.commit()


def session_scope() -> Session:
    init_database()
    return sessionmaker(bind=get_engine(), expire_on_commit=False)()


def reset_database_engine() -> None:
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
