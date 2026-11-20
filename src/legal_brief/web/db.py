"""Database models (SQLAlchemy 2). SQLite locally, Postgres on Render (DATABASE_URL)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text,
                        create_engine, event, select)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from legal_brief.config import PROJECT_ROOT


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Firm(Base):
    __tablename__ = "firms"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    include_summaries: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    users: Mapped[list["User"]] = relationship(back_populates="firm")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    firm_id: Mapped[int] = mapped_column(ForeignKey("firms.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="member")  # admin | member
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0)  # bump to sign the user out everywhere
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    firm: Mapped[Firm] = relationship(back_populates="users")


class Matter(Base):
    __tablename__ = "matters"
    id: Mapped[int] = mapped_column(primary_key=True)
    firm_id: Mapped[int] = mapped_column(ForeignKey("firms.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reference: Mapped[str] = mapped_column(String(80), default="")
    title: Mapped[str] = mapped_column(String(300))
    client_name: Mapped[str] = mapped_column(String(200))
    client_role: Mapped[str] = mapped_column(String(20), default="claimant")  # claimant | defendant
    opponent: Mapped[str] = mapped_column(String(300), default="")
    practice_area: Mapped[str] = mapped_column(String(40), default="")
    facts: Mapped[str] = mapped_column(Text, default="")
    objective: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    firm_id: Mapped[int] = mapped_column(ForeignKey("firms.id", ondelete="CASCADE"), index=True)
    matter_id: Mapped[int] = mapped_column(ForeignKey("matters.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | running | done | failed
    model: Mapped[str] = mapped_column(String(120), default="")
    rounds: Mapped[int] = mapped_column(Integer, default=2)
    events: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    seconds: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Authority(Base):
    """A judgment uploaded by a firm (statutes and case summaries live in data/)."""

    __tablename__ = "authorities"
    id: Mapped[int] = mapped_column(primary_key=True)
    firm_id: Mapped[int] = mapped_column(ForeignKey("firms.id", ondelete="CASCADE"), index=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="judgment")
    name: Mapped[str] = mapped_column(String(300), default="")
    citation: Mapped[str] = mapped_column(String(120), default="")
    court: Mapped[str] = mapped_column(String(120), default="")
    date: Mapped[str] = mapped_column(String(20), default="")
    area: Mapped[str] = mapped_column(String(40), default="other")
    url: Mapped[str] = mapped_column(String(500), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    doctrines: Mapped[dict] = mapped_column(JSON, default=dict)
    filename: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20), default="processing")  # processing | ready | failed
    error: Mapped[str] = mapped_column(Text, default="")
    n_passages: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    passages: Mapped[list["AuthorityPassage"]] = relationship(
        back_populates="authority", cascade="all, delete-orphan", order_by="AuthorityPassage.seq")


class AuthorityPassage(Base):
    __tablename__ = "authority_passages"
    id: Mapped[int] = mapped_column(primary_key=True)
    authority_id: Mapped[int] = mapped_column(ForeignKey("authorities.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    pid: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text)
    authority: Mapped[Authority] = relationship(back_populates="passages")


class EmbeddingRow(Base):
    __tablename__ = "embeddings"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    vector: Mapped[bytes] = mapped_column(LargeBinary)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    firm_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        path = Path(os.environ.get("LEGAL_BRIEF_VAR", PROJECT_ROOT / "var")) / "app.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path.as_posix()}"
    if url.startswith("postgres://"):  # Render and Heroku style URLs
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


_engine = None
SessionLocal: sessionmaker[Session] | None = None


def init_db(url: str | None = None):
    global _engine, SessionLocal
    url = url or database_url()
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    _engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _fk_on(dbapi_conn, _):  # SQLite ignores foreign keys unless asked
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(_engine)
    SessionLocal = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_session() -> Session:
    assert SessionLocal is not None, "init_db() first"
    return SessionLocal()


class DBEmbeddingCache:
    """Embedding cache stored in the database, so vectors survive restarts on Render."""

    def get_many(self, keys):
        import numpy as np

        if not keys:
            return {}
        out = {}
        with get_session() as db:
            for chunk in range(0, len(keys), 500):
                rows = db.execute(select(EmbeddingRow).where(EmbeddingRow.key.in_(keys[chunk:chunk + 500]))).scalars()
                out.update({r.key: np.frombuffer(r.vector, dtype=np.float16).astype(np.float32) for r in rows})
        return out

    def put_many(self, items):
        import numpy as np

        with get_session() as db:
            for k, v in items.items():
                db.merge(EmbeddingRow(key=k, vector=np.asarray(v, dtype=np.float16).tobytes()))
            db.commit()


def audit(db: Session, firm_id: int | None, user_id: int | None, action: str, detail: str = "") -> None:
    db.add(AuditEvent(firm_id=firm_id, user_id=user_id, action=action, detail=detail[:2000]))
