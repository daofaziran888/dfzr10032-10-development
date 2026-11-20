"""数据质量校验接口。

覆盖标准化事件维护、规则口径更正、批次校验/复核、阻断异常与处置凭据查询。
路由层只做参数承接，口径冻结、当前结论唯一、处置凭据等业务判断都在 service。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.quality import (
    BLOCK_LEVELS,
    CHECK_TYPES,
    service,
)

router = APIRouter(prefix="/api/quality", tags=["数据质量校验"])


def _ok(message: str, entry: Any = None) -> ActionResult:
    return ActionResult(ok=True, message=message, entry=entry)


def _fail(message: str) -> ActionResult:
    return ActionResult(ok=False, message=message)


# ---------------------------------------------------------------- 标准化事件
@router.get("/events", response_model=PageResult[dict])
def list_events(batch_id: int | None = None, page: int = 1, size: int = 50) -> PageResult[dict]:
    items = service.list_events(batch_id=batch_id)
    total = len(items)
    start = max(page - 1, 0) * size
    return PageResult(items=items[start:start + size], total=total, page=page, size=size)


@router.post("/events", response_model=ActionResult)
def create_event(payload: EntryPayload) -> ActionResult:
    entry, message = service.create_event(payload.values)
    return _ok("标准化事件已登记", entry) if entry else _fail(message)


@router.get("/events/{event_id}", response_model=dict)
def get_event(event_id: int) -> dict:
    event = service.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"事件 {event_id} 不存在")
    return event


# ---------------------------------------------------------------- 规则与版本
@router.get("/rules", response_model=PageResult[dict])
def list_rules(page: int = 1, size: int = 50) -> PageResult[dict]:
    items = service.list_rules()
    total = len(items)
    start = max(page - 1, 0) * size
    return PageResult(items=items[start:start + size], total=total, page=page, size=size)


@router.post("/rules", response_model=ActionResult)
def create_rule(payload: EntryPayload) -> ActionResult:
    values = payload.values
    if str(values.get("校验类型") or "") not in CHECK_TYPES:
        return _fail(f"校验类型仅支持：{'、'.join(CHECK_TYPES)}")
    if str(values.get("阻断级别") or "阻断") not in BLOCK_LEVELS:
        return _fail(f"阻断级别仅支持：{'、'.join(BLOCK_LEVELS)}")
    rule, message = service.create_rule(values)
    return _ok("校验规则已登记并生成 V1 口径", rule) if rule else _fail(message)


@router.get("/rules/{rule_id}/revisions", response_model=PageResult[dict])
def list_revisions(rule_id: int) -> PageResult[dict]:
    if service.get_rule(rule_id) is None:
        raise HTTPException(status_code=404, detail=f"校验规则 {rule_id} 不存在")
    items = service.list_revisions(rule_id)
    return PageResult(items=items, total=len(items), page=1, size=len(items) or 1)


@router.post("/rules/{rule_id}/revisions", response_model=ActionResult)
def correct_tolerance(rule_id: int, payload: EntryPayload) -> ActionResult:
    """容差更正：追加新版本，历史版本与已落库结论/处置都不动。"""
    revision, message = service.correct_tolerance(rule_id, payload.values)
    if revision is None:
        return _fail(message)
    return _ok(f"已生成 V{revision['版本号']} 口径，后续批次按新版本冻结", revision)


# ---------------------------------------------------------------- 批次校验
@router.post("/checks", response_model=ActionResult)
def run_check(payload: EntryPayload) -> ActionResult:
    values = payload.values
    raw_ids = values.get("event_ids") or []
    try:
        event_ids = [int(value) for value in raw_ids] if isinstance(raw_ids, list) else []
    except (TypeError, ValueError):
        return _fail("event_ids 必须是事件 id 数组")
    batch, message = service.run_check(
        batch_no=str(values.get("批次编号") or "") or None,
        event_ids=event_ids or None,
        trigger_note=str(values.get("触发说明") or "例行数据质量校验"),
    )
    if batch is None:
        return _fail(message)
    return _ok(
        f"批次 {batch['批次编号']} 完成：{batch['结论数']} 条字段结论，{batch['阻断异常数']} 条阻断异常",
        batch,
    )


@router.get("/batches", response_model=PageResult[dict])
def list_batches() -> PageResult[dict]:
    items = service.list_batches()
    return PageResult(items=items, total=len(items), page=1, size=len(items) or 1)


@router.post("/batches/{batch_id}/recheck", response_model=ActionResult)
def recheck(batch_id: int, payload: EntryPayload) -> ActionResult:
    values = payload.values
    raw_ids = values.get("event_ids") or []
    try:
        event_ids = [int(value) for value in raw_ids] if isinstance(raw_ids, list) else None
    except (TypeError, ValueError):
        return _fail("event_ids 必须是事件 id 数组")
    review_batch, message = service.recheck(
        batch_id=batch_id,
        event_ids=event_ids,
        note=str(values.get("触发说明") or "容差更正后复核重算"),
    )
    if review_batch is None:
        return _fail(message)
    return _ok(
        f"复核批次 {review_batch['批次编号']} 完成：阻断异常 {review_batch['阻断异常数']} 条",
        review_batch,
    )


# ---------------------------------------------------------------- 结论查询
@router.get("/results", response_model=PageResult[dict])
def list_results(
    batch_id: int | None = None,
    event_id: int | None = None,
    current_only: bool = False,
) -> PageResult[dict]:
    items = service.list_results(batch_id=batch_id, event_id=event_id, current_only=current_only)
    return PageResult(items=items, total=len(items), page=1, size=len(items) or 1)


# ---------------------------------------------------------------- 异常与处置
@router.get("/anomalies", response_model=PageResult[dict])
def list_anomalies(status: str | None = Query(default=None, description="待处置/重算中/重算通过已解除等")) -> PageResult[dict]:
    items = service.list_anomalies(status=status)
    return PageResult(items=items, total=len(items), page=1, size=len(items) or 1)


@router.post("/anomalies/{anomaly_id}/dispositions", response_model=ActionResult)
def issue_disposition(anomaly_id: int, payload: EntryPayload) -> ActionResult:
    disposition, message = service.issue_disposition(anomaly_id, payload.values)
    if disposition is None:
        return _fail(message)
    return _ok(f"处置单 {disposition['处置单号']} 已派出，依据已固化", disposition)


@router.get("/dispositions", response_model=PageResult[dict])
def list_dispositions(anomaly_id: int | None = None) -> PageResult[dict]:
    items = service.list_dispositions(anomaly_id=anomaly_id)
    return PageResult(items=items, total=len(items), page=1, size=len(items) or 1)


@router.post("/dispositions/{disposition_id}/conflict", response_model=ActionResult)
def resolve_conflict(disposition_id: int, payload: EntryPayload) -> ActionResult:
    """结论冲突时核对凭据：复核沿用 或 已撤销。"""
    disposition, message = service.resolve_conflict(disposition_id, payload.values)
    if disposition is None:
        return _fail(message)
    return _ok(f"处置单已标记为「{disposition['处置状态']}」，凭据链已追加", disposition)


# ---------------------------------------------------------------- 回查台账
@router.get("/trace", response_model=dict)
def trace(event_id: int, rule_id: int) -> dict[str, Any]:
    detail = service.trace(event_id, rule_id)
    if not detail:
        raise HTTPException(status_code=404, detail="事件或规则不存在，无法回查")
    return detail
