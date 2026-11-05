"""Versioned Markdown management with atomic publication to the legacy index."""
import asyncio
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import db
from ..auth import get_current_user, require_role

router = APIRouter(prefix="/api/knowledge", tags=["知识库管理"])
MAX_FILE_BYTES = 2 * 1024 * 1024


def document_dict(document: db.Document, include_content: bool = False) -> dict:
    result = {key: getattr(document, key) for key in ("id", "document_code", "title", "document_type", "version")}
    result["created_at"] = db.iso_timestamp(document.created_at)
    if include_content:
        result["content"] = document.content
    return result


@router.get("/documents")
async def list_documents(_user=Depends(get_current_user), session: AsyncSession = Depends(db.get_db)):
    documents = (await session.scalars(select(db.Document).order_by(db.Document.id))).all()
    return [document_dict(document) for document in documents]


@router.get("/documents/{document_id}")
async def get_document(document_id: int, _user=Depends(get_current_user), session: AsyncSession = Depends(db.get_db)):
    document = await session.get(db.Document, document_id)
    if not document:
        raise HTTPException(404, "文档不存在；历史运行仍保留当时的引用原文")
    return document_dict(document, include_content=True)


@router.post("/upload", status_code=201)
async def upload_document(
    file: Annotated[UploadFile, File()],
    document_code: Annotated[str, Form(min_length=1, max_length=120)],
    title: Annotated[str, Form(min_length=1, max_length=240)],
    document_type: Annotated[Literal["contract", "price_list", "rule", "interview"], Form()],
    version: Annotated[str, Form(min_length=1, max_length=40)] = "1",
    _user=Depends(require_role("admin")),
    session: AsyncSession = Depends(db.get_db),
):
    if not (file.filename or "").lower().endswith(".md"):
        raise HTTPException(400, "仅支持 UTF-8 Markdown（.md）文档")
    if not re.fullmatch(r"[\w.-]+", document_code) or not re.fullmatch(r"[\w.-]+", version):
        raise HTTPException(400, "文档编号和版本仅可包含文字、数字、点、下划线或短横线")
    try:
        content_bytes = await file.read(MAX_FILE_BYTES + 1)
    finally:
        await file.close()
    if len(content_bytes) > MAX_FILE_BYTES:
        raise HTTPException(413, "文档不能超过 2 MiB")
    try:
        content = content_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "文档必须使用 UTF-8 编码") from None
    if not content.strip() or not title.strip() or "\x00" in content:
        raise HTTPException(400, "标题或正文为空，或正文含无效字符")
    async with db.knowledge_lock:
        try:
            document = await db.add_document(session, document_code=document_code, title=title.strip(),
                                             document_type=document_type, version=version, content=content)
            # Publish an atomic index file; on commit failure restore from committed DB.
            await db.rebuild_index(session)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            await db.rebuild_index(session)
            if isinstance(exc, IntegrityError):
                raise HTTPException(409, "该文档编号与版本已存在，请使用新版本号") from None
            raise
    return document_dict(document, include_content=True)


@router.delete("/documents/{document_id}")
async def delete_document(document_id: int, _user=Depends(require_role("admin")), session: AsyncSession = Depends(db.get_db)):
    async with db.knowledge_lock:
        document = await session.get(db.Document, document_id)
        if not document:
            raise HTTPException(404, "文档不存在")
        try:
            await session.execute(delete(db.KnowledgeChunk).where(db.KnowledgeChunk.document_id == document_id))
            await session.delete(document)
            await session.flush()
            await db.rebuild_index(session)
            await session.commit()
        except Exception:
            await session.rollback()
            await db.rebuild_index(session)
            raise
    return {"message": "文档与当前检索索引已删除；历史运行中的引用快照保留"}
