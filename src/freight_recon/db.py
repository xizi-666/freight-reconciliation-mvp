"""Five-table async SQLite storage, exact decimals, and idempotent bootstrap."""
import asyncio
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .knowledge.ingest import split_md
from .sample_data import ensure_samples

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("FREIGHT_DATA_DIR", str(ROOT / "data"))).resolve()
INDEX_PATH = DATA_DIR / "index" / "chunks.jsonl"
DATA_DIR.mkdir(parents=True, exist_ok=True)
engine = create_async_engine(f"sqlite+aiosqlite:///{(DATA_DIR / 'freight.db').as_posix()}", connect_args={"timeout": 15})
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
knowledge_lock = asyncio.Lock()


@event.listens_for(engine.sync_engine, "connect")
def configure_sqlite(connection, _record):
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=15000")
    cursor.close()


def utcnow():
    return datetime.now(timezone.utc)


def iso_timestamp(value: datetime) -> str:
    # SQLite drops timezone information from DateTime columns; timestamps are UTC.
    return value.replace(tzinfo=timezone.utc).isoformat(timespec="seconds") if value.tzinfo is None else value.isoformat(timespec="seconds")


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


class ExactDecimal(TypeDecorator):
    """SQLite TEXT avoids SQLite/DBAPI converting monetary values through float."""
    impl = String(64)
    cache_ok = True

    def process_bind_param(self, value, _dialect):
        if value is None:
            return None
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("金额或重量必须为有限十进制数")
        return format(number, "f")

    def process_result_value(self, value, _dialect):
        return None if value is None else Decimal(value)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin','reconciler')"), {"sqlite_autoincrement": True})
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("document_code", "version"),
        CheckConstraint("document_type IN ('contract','price_list','rule','interview')"),
        {"sqlite_autoincrement": True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_code: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(240))
    document_type: Mapped[str] = mapped_column(String(20))
    version: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"), {"sqlite_autoincrement": True})
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_no: Mapped[str] = mapped_column(String(80), unique=True)
    carrier: Mapped[str] = mapped_column(String(80))
    lane: Mapped[str] = mapped_column(String(80))
    weight_actual: Mapped[Decimal] = mapped_column(ExactDecimal())
    weight_volume: Mapped[Decimal] = mapped_column(ExactDecimal())
    weight_min: Mapped[Decimal] = mapped_column(ExactDecimal())
    amount: Mapped[Decimal] = mapped_column(ExactDecimal())
    billing_time: Mapped[str] = mapped_column(String(64))
    system_status: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"
    __table_args__ = (CheckConstraint("status IN ('matched','needs_review','pending_manual')"), {"sqlite_autoincrement": True})
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id"), index=True)
    snapshot_data: Mapped[str] = mapped_column(Text)
    rule_version: Mapped[str] = mapped_column(String(160))
    calculated_amount: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    original_amount: Mapped[Decimal] = mapped_column(ExactDecimal())
    difference: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    explanation: Mapped[str] = mapped_column(Text)
    references_json: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


async def get_db():
    async with SessionLocal() as session:
        yield session


def chunk_reference(document: Document, chunk: KnowledgeChunk) -> dict:
    original = ROOT / "data" / "knowledge" / f"{document.document_code}.md"
    legacy = document.version == "1" and original.is_file()
    return {
        "id": f"{document.document_code}:{chunk.chunk_index + 1}" if legacy else f"doc-{document.id}:{chunk.chunk_index + 1}",
        "source": original.name if legacy else f"{document.document_code}@{document.version}.md",
        "heading": chunk.heading, "text": chunk.text,
        "document_id": document.id, "chunk_id": chunk.id,
        "document_code": document.document_code, "version": document.version,
        "document_type": document.document_type,
        "content_hash": hashlib.sha256(document.content.encode("utf-8")).hexdigest(),
        "text_hash": hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
    }


def write_index(rows: list[dict]) -> None:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=INDEX_PATH.parent, suffix=".tmp", delete=False) as handle:
            temporary_path = Path(handle.name)
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(temporary_path, INDEX_PATH)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


async def rebuild_index(session: AsyncSession) -> None:
    records = (await session.execute(select(Document, KnowledgeChunk).join(KnowledgeChunk).order_by(Document.id, KnowledgeChunk.chunk_index))).all()
    rows = [chunk_reference(document, chunk) for document, chunk in records]
    await asyncio.to_thread(write_index, rows)


async def add_document(session: AsyncSession, **values) -> Document:
    document = Document(**values)
    session.add(document)
    await session.flush()
    for index, (heading, text) in enumerate(split_md(document.content)):
        session.add(KnowledgeChunk(document_id=document.id, chunk_index=index, heading=heading, text=text))
    await session.flush()
    return document


async def init_db() -> None:
    await asyncio.to_thread(ensure_samples, DATA_DIR)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with knowledge_lock, SessionLocal() as session:
        # Seed only a brand-new database; deleted documents must not reappear.
        first_boot = (await session.scalar(select(User.id).limit(1))) is None
        if first_boot:
            session.add_all([
                User(username="admin", password_hash=hash_password("admin123"), role="admin"),
                User(username="recon", password_hash=hash_password("recon123"), role="reconciler"),
            ])
            for path in sorted((ROOT / "data" / "knowledge").glob("*.md")):
                await add_document(session, document_code=path.stem, title=path.stem,
                                   document_type="interview" if path.stem == "discovery-report" else "rule",
                                   version="1", content=path.read_text(encoding="utf-8"))
            for path in sorted((DATA_DIR / "samples" / "contracts").glob("*.md")):
                carrier = path.stem.rsplit("-", 1)[-1]
                await add_document(session, document_code=path.stem, title=path.stem,
                                   document_type="price_list" if "-price-" in path.stem else "contract",
                                   version="v2" if carrier == "a" else "v1", content=path.read_text(encoding="utf-8"))
            rows = await asyncio.to_thread(lambda: json.loads((DATA_DIR / "samples" / "shipments.json").read_text(encoding="utf-8")))
            fields = ("shipment_no", "carrier", "lane", "weight_actual", "weight_volume", "weight_min", "amount", "billing_time", "system_status")
            session.add_all([Shipment(**{key: row[key] for key in fields}) for row in rows])
            await session.commit()
        await rebuild_index(session)
