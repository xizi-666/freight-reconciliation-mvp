"""Authenticated shipment, reconciliation, and immutable run history endpoints."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import db
from ..auth import get_current_user, require_role
from ..core.reconciliation import read_snapshots, reconcile_shipment, run_dict, shipment_dict

router = APIRouter(prefix="/api", tags=["运费对账"])


class ReconcileRequest(BaseModel):
    shipment_id: int = Field(gt=0)


@router.get("/shipments")
async def shipments(_user=Depends(get_current_user), session: AsyncSession = Depends(db.get_db)):
    records = (await session.scalars(select(db.Shipment).order_by(db.Shipment.id))).all()
    return [shipment_dict(record) for record in records]


@router.get("/shipments/{shipment_id}")
async def shipment_detail(shipment_id: int, _user=Depends(get_current_user), session: AsyncSession = Depends(db.get_db)):
    record = await session.get(db.Shipment, shipment_id)
    if not record:
        raise HTTPException(404, "运单不存在")
    return {"shipment": shipment_dict(record), "snapshots": await asyncio.to_thread(read_snapshots, record.shipment_no)}


@router.post("/reconcile", status_code=201)
async def reconcile(body: ReconcileRequest, user=Depends(require_role("reconciler")), session: AsyncSession = Depends(db.get_db)):
    shipment = await session.get(db.Shipment, body.shipment_id)
    if not shipment:
        raise HTTPException(404, "运单不存在")
    shipment_no = shipment.shipment_no
    run = await reconcile_shipment(session, shipment, user["id"])
    return run_dict(run, shipment_no)


@router.get("/reconcile/runs")
async def list_runs(user=Depends(get_current_user), session: AsyncSession = Depends(db.get_db),
                    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
    statement = select(db.ReconciliationRun, db.Shipment.shipment_no).join(db.Shipment)
    if user["role"] != "admin":
        statement = statement.where(db.ReconciliationRun.created_by == user["id"])
    rows = (await session.execute(statement.order_by(db.ReconciliationRun.id.desc()).offset(offset).limit(limit))).all()
    return [run_dict(run, shipment_no, detail=False) for run, shipment_no in rows]


@router.get("/reconcile/runs/{run_id}")
async def run_detail(run_id: int, user=Depends(get_current_user), session: AsyncSession = Depends(db.get_db)):
    row = (await session.execute(select(db.ReconciliationRun, db.Shipment.shipment_no).join(db.Shipment).where(db.ReconciliationRun.id == run_id))).first()
    if not row:
        raise HTTPException(404, "对账记录不存在")
    run, shipment_no = row
    if user["role"] != "admin" and run.created_by != user["id"]:
        raise HTTPException(403, "只能查看本人发起的对账记录")
    return run_dict(run, shipment_no)
