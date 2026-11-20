"""数据质量校验业务规则。

围绕"标准化事件 -> 字段级校验结论 -> 阻断异常 -> 处置凭据"这条链路实现，
关键的口径与凭据约束都收敛在本模块里：

1. 口径冻结：一次校验在开跑时把当轮启用规则的版本（期望值/容差/阻断级别）
   整体快照到批次上，整轮只读取快照，批次执行过程中即使有人更正容差，
   也不会影响当轮结论 —— 同一次校验绝不混用变更前后的容差。
2. 当前结论唯一：同一批次里同一(事件, 规则)最多只有一条 is_current 结论；
   复核重算时旧结论显式置为 superseded，处置仍可凭旧结论 id 回查原依据。
3. 处置不可改写：处置记录落库时固化规则口径快照与结论 id，后续容差更正、
   结论翻转都不会改动已派出处置，只能在重算后做"沿用/撤销"并留下凭据。
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from app.store import store

# 模块表名
EVENT_TABLE = "quality_event"
RULE_TABLE = "quality_rule"
REVISION_TABLE = "quality_rule_revision"
BATCH_TABLE = "quality_batch"
RESULT_TABLE = "quality_result"
ANOMALY_TABLE = "quality_anomaly"
LOG_TABLE = "log_viewer"

# 校验类型
CHECK_RANGE = "数值偏差"
CHECK_REQUIRED = "必填非空"
CHECK_ENUM = "枚举取值"
CHECK_TYPES = [CHECK_RANGE, CHECK_ENUM, CHECK_REQUIRED]

# 阻断级别
BLOCK = "阻断"
WARN = "提醒"
BLOCK_LEVELS = [BLOCK, WARN]

# 结论 / 异常 / 处置 / 批次状态
PASS = "通过"
FAIL = "失败"
CURRENT = "当前有效"
SUPERSEDED = "已被重算取代"

ANOMALY_OPEN = "待处置"
ANOMALY_RETRY = "重算中"
ANOMALY_RESOLVED = "重算通过已解除"
ANOMALY_CONFIRMED = "复核确认保留"
# 尚未关闭、复核重算时需要继续关联的异常状态（含已派出处置在途的"处置中"）
ANOMALY_OPEN_STATUSES = (ANOMALY_OPEN, ANOMALY_RETRY, "处置中", ANOMALY_CONFIRMED)

DISP_ISSUED = "已派出"
DISP_RETAINED = "复核沿用"
DISP_REVOKED = "已撤销"

BATCH_RUNNING = "执行中"
BATCH_DONE = "已完成"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def seed_quality_demo() -> None:
    """灌入水温偏差演示场景。

    事件 EVT-WT-01：水温实测偏差 2.4 度；规则 R-WT-DEV V1 允许偏差 2 度（阻断），
    首轮校验失败并已派出处置；复核期间有人提交了 V2（容差 3 度）但尚未重算，
    处置人员可直接发起复核，观察警报解除与处置凭据的沿用/撤销。
    """
    if store.has_table(EVENT_TABLE):  # 已初始化过，不重复灌数据
        return

    event = store.add(EVENT_TABLE, {
        "事件编号": "EVT-WT-01",
        "事件类型": "传感器读数",
        "来源批次": "INGE-20261120-01",
        "事件载荷": "水温偏差=2.4,设备编号=SENS-A17,车间=二车间",
        "标准化字段": {"水温偏差": 2.4, "设备编号": "SENS-A17", "车间": "二车间"},
        "status": "已标准化",
        "pending": False,
        "abnormal": False,
    })
    event2 = store.add(EVENT_TABLE, {
        "事件编号": "EVT-WT-02",
        "事件类型": "传感器读数",
        "来源批次": "INGE-20261120-01",
        "事件载荷": "水温偏差=1.2,设备编号=SENS-A18,车间=二车间",
        "标准化字段": {"水温偏差": 1.2, "设备编号": "SENS-A18", "车间": "二车间"},
        "status": "已标准化",
        "pending": False,
        "abnormal": False,
    })

    rule = store.add(RULE_TABLE, {
        "规则编号": "R-WT-DEV",
        "校验字段": "水温偏差",
        "校验类型": CHECK_RANGE,
        "启用状态": "已启用",
        "当前版本号": 2,
        "当前版本id": None,
        "status": "已启用",
        "pending": False,
        "abnormal": False,
    })
    rev1 = store.add(REVISION_TABLE, {
        "规则id": rule["id"], "版本号": 1, "期望值": 0, "容差": 2,
        "允许枚举": "", "阻断级别": BLOCK,
        "口径说明": "启用口径：允许偏差 2 度（含边界）",
        "变更原因": "初始登记", "生效时间": "2026-11-18 09:00:00",
        "status": "生效中", "pending": False, "abnormal": False,
    })
    rev2 = store.add(REVISION_TABLE, {
        "规则id": rule["id"], "版本号": 2, "期望值": 0, "容差": 3,
        "允许枚举": "", "阻断级别": BLOCK,
        "口径说明": "复核期间更正：允许偏差放宽到 3 度",
        "变更原因": "复核期间提交容差更正，待下一轮校验冻结",
        "生效时间": "2026-11-20 10:30:00",
        "status": "生效中", "pending": False, "abnormal": False,
    })
    rule["当前版本id"] = rev2["id"]

    rule2 = store.add(RULE_TABLE, {
        "规则编号": "R-SHOP-ENUM",
        "校验字段": "车间",
        "校验类型": CHECK_ENUM,
        "启用状态": "已启用",
        "当前版本号": 1,
        "当前版本id": None,
        "status": "已启用",
        "pending": False,
        "abnormal": False,
    })
    rev3 = store.add(REVISION_TABLE, {
        "规则id": rule2["id"], "版本号": 1, "期望值": "", "容差": "",
        "允许枚举": "一车间|二车间|三车间", "阻断级别": WARN,
        "口径说明": "车间名称必须在登记范围内，失败仅提醒不阻断",
        "变更原因": "初始登记", "生效时间": "2026-11-18 09:05:00",
        "status": "生效中", "pending": False, "abnormal": False,
    })
    rule2["当前版本id"] = rev3["id"]

    # 首轮批次：冻结 V1（容差 2），即使现在规则已到 V2，旧批次快照仍保持 2
    snap1 = {
        rule["id"]: {
            "规则id": rule["id"], "规则编号": rule["规则编号"], "校验字段": "水温偏差",
            "校验类型": CHECK_RANGE, "版本id": rev1["id"], "版本号": 1,
            "期望值": 0, "容差": 2, "允许枚举": "", "阻断级别": BLOCK,
            "口径说明": rev1["口径说明"],
        },
        rule2["id"]: {
            "规则id": rule2["id"], "规则编号": rule2["规则编号"], "校验字段": "车间",
            "校验类型": CHECK_ENUM, "版本id": rev3["id"], "版本号": 1,
            "期望值": "", "容差": "", "允许枚举": "一车间|二车间|三车间",
            "阻断级别": WARN, "口径说明": rev3["口径说明"],
        },
    }
    batch = store.add(BATCH_TABLE, {
        "批次编号": "BATCH-20261120-01",
        "触发说明": "首轮数据质量校验（容差更正前）",
        "event_ids": [event["id"], event2["id"]],
        "规则版本快照": snap1,
        "冻结时间": "2026-11-20 09:15:00",
        "状态": BATCH_DONE,
        "结论数": 4,
        "阻断异常数": 1,
        "status": BATCH_DONE,
        "pending": False,
        "abnormal": True,
    })

    fail_result = store.add(RESULT_TABLE, {
        "批次id": batch["id"], "事件id": event["id"], "事件编号": event["事件编号"],
        "规则id": rule["id"], "规则编号": rule["规则编号"], "校验字段": "水温偏差",
        "校验类型": CHECK_RANGE, "结论": FAIL, "失败字段": "水温偏差",
        "是否阻断": True, "阻断级别": BLOCK, "实测值": 2.4, "偏差量": 2.4,
        "采用版本id": rev1["id"], "采用版本号": 1,
        "采用口径": {"期望值": 0, "容差": 2, "允许枚举": "", "阻断级别": BLOCK,
                  "口径说明": rev1["口径说明"]},
        "判定说明": "实测 2.4，期望 0，偏差 2.4，当轮容差 2（口径：偏差 ≤ 容差 即通过）",
        "is_current": True, "结论状态": CURRENT, "异常id": None,
        "校验时间": "2026-11-20 09:15:00",
        "status": FAIL, "pending": True, "abnormal": True,
    })
    store.add(RESULT_TABLE, {
        "批次id": batch["id"], "事件id": event["id"], "事件编号": event["事件编号"],
        "规则id": rule2["id"], "规则编号": rule2["规则编号"], "校验字段": "车间",
        "校验类型": CHECK_ENUM, "结论": PASS, "失败字段": None,
        "是否阻断": False, "阻断级别": WARN, "实测值": "二车间", "偏差量": None,
        "采用版本id": rev3["id"], "采用版本号": 1,
        "采用口径": {"期望值": "", "容差": "", "允许枚举": "一车间|二车间|三车间",
                  "阻断级别": WARN, "口径说明": rev3["口径说明"]},
        "判定说明": "取值「二车间」，允许集合：一车间、二车间、三车间",
        "is_current": True, "结论状态": CURRENT, "异常id": None,
        "校验时间": "2026-11-20 09:15:00",
        "status": PASS, "pending": False, "abnormal": False,
    })
    store.add(RESULT_TABLE, {
        "批次id": batch["id"], "事件id": event2["id"], "事件编号": event2["事件编号"],
        "规则id": rule["id"], "规则编号": rule["规则编号"], "校验字段": "水温偏差",
        "校验类型": CHECK_RANGE, "结论": PASS, "失败字段": None,
        "是否阻断": False, "阻断级别": BLOCK, "实测值": 1.2, "偏差量": 1.2,
        "采用版本id": rev1["id"], "采用版本号": 1,
        "采用口径": {"期望值": 0, "容差": 2, "允许枚举": "", "阻断级别": BLOCK,
                  "口径说明": rev1["口径说明"]},
        "判定说明": "实测 1.2，期望 0，偏差 1.2，当轮容差 2（口径：偏差 ≤ 容差 即通过）",
        "is_current": True, "结论状态": CURRENT, "异常id": None,
        "校验时间": "2026-11-20 09:15:00",
        "status": PASS, "pending": False, "abnormal": False,
    })
    store.add(RESULT_TABLE, {
        "批次id": batch["id"], "事件id": event2["id"], "事件编号": event2["事件编号"],
        "规则id": rule2["id"], "规则编号": rule2["规则编号"], "校验字段": "车间",
        "校验类型": CHECK_ENUM, "结论": PASS, "失败字段": None,
        "是否阻断": False, "阻断级别": WARN, "实测值": "二车间", "偏差量": None,
        "采用版本id": rev3["id"], "采用版本号": 1,
        "采用口径": {"期望值": "", "容差": "", "允许枚举": "一车间|二车间|三车间",
                  "阻断级别": WARN, "口径说明": rev3["口径说明"]},
        "判定说明": "取值「二车间」，允许集合：一车间、二车间、三车间",
        "is_current": True, "结论状态": CURRENT, "异常id": None,
        "校验时间": "2026-11-20 09:15:00",
        "status": PASS, "pending": False, "abnormal": False,
    })

    anomaly = store.add(ANOMALY_TABLE, {
        "异常编号": f"ANM-{event['事件编号']}-{rule['规则编号']}",
        "批次id": batch["id"], "最近批次id": batch["id"],
        "事件id": event["id"], "事件编号": event["事件编号"],
        "规则id": rule["id"], "规则编号": rule["规则编号"],
        "校验字段": "水温偏差", "阻断级别": BLOCK, "是否阻断": True,
        "首报结论id": fail_result["id"], "最近结论id": fail_result["id"],
        "首报口径快照": dict(fail_result["采用口径"]), "首报版本号": 1,
        "异常状态": "处置中", "重算次数": 0,
        "status": "处置中", "pending": True, "abnormal": True,
    })
    fail_result["异常id"] = anomaly["id"]

    store.add(LOG_TABLE, {
        "日志编号": f"LOG-QC-{batch['id']}-{event['id']}-{rule['id']}",
        "关联任务": f"{batch['批次编号']} / {event['事件编号']} / {rule['规则编号']}",
        "日志级别": "阻断异常", "记录时间": "2026-11-20 09:16:00",
        "日志内容": (
            "数据质量校验阻断：字段「水温偏差」实测 2.4，期望 0，偏差 2.4，"
            "当轮容差 2；采用规则版本 V1，阻断级别 阻断；异常单号 "
            f"{anomaly['异常编号']}"
        ),
        "错误堆栈": f"结论id={fail_result['id']}；异常id={anomaly['id']}；批次id={batch['id']}",
        "处理状态": "处置中", "处理人": "现场处置-王工",
        "异常id": anomaly["id"], "批次id": batch["id"],
        "status": "处置中", "pending": True, "abnormal": True,
    })

    store.add("quality_disposition", {
        "处置单号": "DSP-WT01-001",
        "异常id": anomaly["id"], "事件id": event["id"], "事件编号": event["事件编号"],
        "规则id": rule["id"], "规则编号": rule["规则编号"],
        "处理人": "现场处置-王工", "处置动作": "派发现场检修工单",
        "处置说明": "按 V1 容差 2 度判定阻断，派员到二车间核查传感器 SENS-A17",
        "处置状态": DISP_ISSUED,
        "依据结论id": fail_result["id"], "依据批次id": batch["id"],
        "依据版本号": 1,
        "依据口径快照": dict(fail_result["采用口径"]),
        "凭据链": [{
            "动作": "派出处置", "处理人": "现场处置-王工",
            "时间": "2026-11-20 09:20:00",
            "依据结论id": fail_result["id"], "依据版本号": 1,
            "说明": f"按 {anomaly['异常编号']} 首报口径派出",
        }],
        "status": DISP_ISSUED, "pending": True, "abnormal": True,
    })


class QualityService:
    # ------------------------------------------------------------------ 事件
    def list_events(self, batch_id: int | None = None) -> list[dict[str, Any]]:
        rows = [dict(row) for row in store.rows(EVENT_TABLE)]
        if batch_id is not None:
            batch = store.find(BATCH_TABLE, batch_id)
            ids = set(batch.get("event_ids", [])) if batch else set()
            rows = [row for row in rows if int(row["id"]) in ids]
        return rows

    def get_event(self, event_id: int) -> dict[str, Any] | None:
        return store.find(EVENT_TABLE, event_id)

    def create_event(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        event_code = str(values.get("事件编号") or "").strip()
        if not event_code:
            return None, "事件编号不能为空"
        payload = str(values.get("事件载荷") or "").strip()
        if not payload:
            return None, "标准化事件载荷不能为空"
        fields, message = self._parse_payload(payload)
        if fields is None:
            return None, message
        entry = {
            "事件编号": event_code,
            "事件类型": str(values.get("事件类型") or "传感器读数").strip(),
            "来源批次": str(values.get("来源批次") or "").strip(),
            "事件载荷": payload,
            "标准化字段": fields,
            "status": "已标准化",
            "pending": False,
            "abnormal": False,
        }
        return store.add(EVENT_TABLE, entry), ""

    @staticmethod
    def _parse_payload(payload: str) -> tuple[dict[str, Any] | None, str]:
        """标准化事件载荷约定为 key=value，多个字段用逗号或换行分隔。"""
        fields: dict[str, Any] = {}
        for chunk in payload.replace("\n", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "=" not in chunk:
                return None, f"载荷片段「{chunk}」不是 字段=值 形式"
            key, raw = chunk.split("=", 1)
            key = key.strip()
            raw = raw.strip()
            if not key:
                return None, "存在空字段名"
            number = _to_float(raw)
            fields[key] = number if number is not None else raw
        if not fields:
            return None, "事件载荷里没有可校验的字段"
        return fields, ""

    # ------------------------------------------------------------------ 规则
    def list_rules(self) -> list[dict[str, Any]]:
        return [dict(row) for row in store.rows(RULE_TABLE)]

    def get_rule(self, rule_id: int) -> dict[str, Any] | None:
        return store.find(RULE_TABLE, rule_id)

    def list_revisions(self, rule_id: int) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in store.rows(REVISION_TABLE)
            if int(row.get("规则id", 0)) == rule_id
        ]

    def create_rule(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        code = str(values.get("规则编号") or "").strip()
        field = str(values.get("校验字段") or "").strip()
        check_type = str(values.get("校验类型") or "").strip()
        if not code or not field or not check_type:
            return None, "规则编号、校验字段、校验类型为必填"
        if check_type not in CHECK_TYPES:
            return None, f"校验类型仅支持：{'、'.join(CHECK_TYPES)}"
        block_level = str(values.get("阻断级别") or BLOCK).strip()
        if block_level not in BLOCK_LEVELS:
            return None, f"阻断级别仅支持：{'、'.join(BLOCK_LEVELS)}"
        if check_type == CHECK_RANGE:
            if _to_float(values.get("期望值")) is None:
                return None, "数值偏差规则的期望值必须是数字"
            if _to_float(values.get("容差")) is None:
                return None, "数值偏差规则的容差必须是数字"
        rule = store.add(RULE_TABLE, {
            "规则编号": code,
            "校验字段": field,
            "校验类型": check_type,
            "启用状态": "已启用",
            "当前版本号": 1,
            "status": "已启用",
            "pending": False,
            "abnormal": False,
        })
        revision = store.add(REVISION_TABLE, self._build_revision(rule["id"], 1, values, block_level, "初始登记"))
        rule["当前版本id"] = revision["id"]
        return rule, ""

    def correct_tolerance(
        self, rule_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        """容差/期望/阻断级别更正：只追加新版本，绝不覆盖历史版本。"""
        rule = store.find(RULE_TABLE, rule_id)
        if rule is None:
            return None, f"校验规则 {rule_id} 不存在"
        revisions = self.list_revisions(rule_id)
        latest = max(revisions, key=lambda row: int(row["版本号"]))
        next_version = int(latest["版本号"]) + 1

        def pick(key: str) -> Any:
            return values[key] if key in values and str(values[key]).strip() != "" else latest[key]

        check_type = str(rule["校验类型"])
        expected = pick("期望值")
        tolerance = pick("容差")
        if check_type == CHECK_RANGE:
            if _to_float(expected) is None:
                return None, "期望值必须是数字"
            if _to_float(tolerance) is None:
                return None, "容差必须是数字"
        block_level = str(pick("阻断级别")).strip()
        if block_level not in BLOCK_LEVELS:
            return None, f"阻断级别仅支持：{'、'.join(BLOCK_LEVELS)}"
        revision = store.add(REVISION_TABLE, self._build_revision(
            rule_id,
            next_version,
            {"期望值": expected, "容差": tolerance, "允许枚举": pick("允许枚举"), "口径说明": pick("口径说明")},
            block_level,
            str(values.get("更正原因") or "容差/口径更正"),
        ))
        rule["当前版本号"] = next_version
        rule["当前版本id"] = revision["id"]
        return revision, ""

    @staticmethod
    def _build_revision(
        rule_id: int, version: int, values: dict[str, Any], block_level: str, change_note: str
    ) -> dict[str, Any]:
        return {
            "规则id": rule_id,
            "版本号": version,
            "期望值": _to_float(values.get("期望值")) if _to_float(values.get("期望值")) is not None else str(values.get("期望值") or ""),
            "容差": _to_float(values.get("容差")) if _to_float(values.get("容差")) is not None else str(values.get("容差") or ""),
            "允许枚举": str(values.get("允许枚举") or "").strip(),
            "阻断级别": block_level,
            "口径说明": str(values.get("口径说明") or "").strip(),
            "变更原因": change_note,
            "生效时间": _now(),
            "status": "生效中",
            "pending": False,
            "abnormal": False,
        }

    # ------------------------------------------------------------------ 校验
    def run_check(
        self,
        *,
        batch_no: str | None = None,
        event_ids: list[int] | None = None,
        trigger_note: str = "例行数据质量校验",
    ) -> tuple[dict[str, Any] | None, str]:
        events = self._select_events(event_ids)
        if not events:
            return None, "没有可校验的标准化事件"
        active_rules = [row for row in store.rows(RULE_TABLE) if row.get("启用状态") == "已启用"]
        if not active_rules:
            return None, "没有已启用的校验规则，无法判定字段"

        # 口径冻结点：把当轮启用规则的当前版本整体复制进批次快照，
        # 之后整轮只使用 snapshot，规则表再怎么更正都与当轮无关。
        snapshot: dict[int, dict[str, Any]] = {}
        for rule in active_rules:
            revision = store.find(REVISION_TABLE, int(rule["当前版本id"]))
            snapshot[int(rule["id"])] = {
                "规则id": int(rule["id"]),
                "规则编号": rule["规则编号"],
                "校验字段": rule["校验字段"],
                "校验类型": rule["校验类型"],
                "版本id": revision["id"],
                "版本号": revision["版本号"],
                "期望值": revision["期望值"],
                "容差": revision["容差"],
                "允许枚举": revision["允许枚举"],
                "阻断级别": revision["阻断级别"],
                "口径说明": revision["口径说明"],
            }

        batch = store.add(BATCH_TABLE, {
            "批次编号": batch_no or f"BATCH-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "触发说明": trigger_note,
            "event_ids": [int(event["id"]) for event in events],
            "规则版本快照": snapshot,
            "冻结时间": _now(),
            "状态": BATCH_RUNNING,
            "结论数": 0,
            "阻断异常数": 0,
            "status": BATCH_RUNNING,
            "pending": True,
            "abnormal": False,
        })

        result_count = 0
        blocking_count = 0
        # 当前结论唯一：新一轮校验覆盖的(事件, 规则)，其历史当前结论一律让位，
        # 保证同一事件+规则在全库里最多一条 is_current，而不只是同批次内唯一。
        check_event_ids = {int(event["id"]) for event in events}
        for old in store.rows(RESULT_TABLE):
            if (
                old.get("is_current")
                and int(old["事件id"]) in check_event_ids
                and int(old["规则id"]) in snapshot
            ):
                old["is_current"] = False
                old["结论状态"] = SUPERSEDED
                old["pending"] = False
        for event in events:
            for rule_id, snap in snapshot.items():
                result, is_blocking = self._evaluate(batch, event, snap)
                # store.add 写入的是副本，后续关联必须用返回的入库对象
                stored = store.add(RESULT_TABLE, result)
                result_count += 1
                if is_blocking:
                    # 只有阻断级失败才生成需处置的阻断异常与采集日志；
                    # 提醒级失败只留字段结论，不产生阻断异常。
                    anomaly = self._register_anomaly(batch, event, snap, stored, is_blocking)
                    stored["异常id"] = anomaly["id"]
                    blocking_count += 1
                    self._write_log(batch, event, snap, stored, anomaly)

        batch["结论数"] = result_count
        batch["阻断异常数"] = blocking_count
        batch["状态"] = BATCH_DONE
        batch["status"] = BATCH_DONE
        batch["pending"] = blocking_count == 0
        batch["abnormal"] = blocking_count > 0
        return batch, ""

    def _select_events(self, event_ids: list[int] | None) -> list[dict[str, Any]]:
        rows = store.rows(EVENT_TABLE)
        if not event_ids:
            return rows
        wanted = {int(value) for value in event_ids}
        return [row for row in rows if int(row["id"]) in wanted]

    def _evaluate(
        self, batch: dict[str, Any], event: dict[str, Any], snap: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        field = str(snap["校验字段"])
        actual = event.get("标准化字段", {}).get(field)
        check_type = str(snap["校验类型"])
        passed = False
        deviation: Any = None
        detail = ""

        if check_type == CHECK_RANGE:
            expected = _to_float(snap["期望值"])
            tolerance = _to_float(snap["容差"])
            actual_num = _to_float(actual)
            if actual_num is None:
                detail = "字段缺失或不是数值，无法按数值偏差口径判定"
            else:
                deviation = round(abs(actual_num - float(expected)), 6)
                passed = deviation <= float(tolerance)
                detail = (
                    f"实测 {actual_num}，期望 {expected}，偏差 {deviation}，"
                    f"当轮容差 {tolerance}（口径：偏差 ≤ 容差 即通过）"
                )
        elif check_type == CHECK_REQUIRED:
            passed = actual is not None and str(actual).strip() != ""
            detail = "字段必填非空" if passed else "字段缺失或为空"
        else:  # CHECK_ENUM
            allowed = {item.strip() for item in str(snap["允许枚举"]).split("|") if item.strip()}
            text = "" if actual is None else str(actual)
            passed = text in allowed if allowed else False
            detail = f"取值「{text}」，允许集合：{'、'.join(sorted(allowed)) or '未配置'}"

        is_blocking = str(snap["阻断级别"]) == BLOCK and not passed
        result = {
            "批次id": batch["id"],
            "事件id": event["id"],
            "事件编号": event["事件编号"],
            "规则id": snap["规则id"],
            "规则编号": snap["规则编号"],
            "校验字段": field,
            "校验类型": check_type,
            "结论": PASS if passed else FAIL,
            "失败字段": None if passed else field,
            "是否阻断": is_blocking,
            "阻断级别": snap["阻断级别"],
            "实测值": actual,
            "偏差量": deviation,
            "采用版本id": snap["版本id"],
            "采用版本号": snap["版本号"],
            "采用口径": {
                "期望值": snap["期望值"],
                "容差": snap["容差"],
                "允许枚举": snap["允许枚举"],
                "阻断级别": snap["阻断级别"],
                "口径说明": snap["口径说明"],
            },
            "判定说明": detail,
            "is_current": True,
            "结论状态": CURRENT,
            "异常id": None,
            "校验时间": _now(),
            "status": PASS if passed else FAIL,
            "pending": not passed,
            "abnormal": is_blocking,
        }
        return result, is_blocking

    def _register_anomaly(
        self,
        batch: dict[str, Any],
        event: dict[str, Any],
        snap: dict[str, Any],
        result: dict[str, Any],
        is_blocking: bool,
    ) -> dict[str, Any]:
        # 同一(事件, 规则)只保留一条阻断异常：重试时复用旧异常，保留首次依据。
        existing = next((
            row for row in store.rows(ANOMALY_TABLE)
            if int(row["事件id"]) == int(event["id"])
            and int(row["规则id"]) == int(snap["规则id"])
            and row["异常状态"] in ANOMALY_OPEN_STATUSES
        ), None)
        if existing is not None:
            existing["异常状态"] = ANOMALY_RETRY
            existing["status"] = ANOMALY_RETRY
            existing["最近批次id"] = batch["id"]
            existing["最近结论id"] = result["id"] if result.get("id") else existing["最近结论id"]
            existing["重算次数"] = int(existing.get("重算次数", 0)) + 1
            return existing

        return store.add(ANOMALY_TABLE, {
            "异常编号": f"ANM-{event['事件编号']}-{snap['规则编号']}",
            "批次id": batch["id"],
            "最近批次id": batch["id"],
            "事件id": event["id"],
            "事件编号": event["事件编号"],
            "规则id": snap["规则id"],
            "规则编号": snap["规则编号"],
            "校验字段": snap["校验字段"],
            "阻断级别": snap["阻断级别"],
            "是否阻断": is_blocking,
            "首报结论id": result.get("id"),
            "最近结论id": result.get("id"),
            "首报口径快照": deepcopy(result["采用口径"]),
            "首报版本号": result["采用版本号"],
            "异常状态": ANOMALY_OPEN,
            "重算次数": 0,
            "status": ANOMALY_OPEN,
            "pending": True,
            "abnormal": is_blocking,
        })

    def _write_log(
        self,
        batch: dict[str, Any],
        event: dict[str, Any],
        snap: dict[str, Any],
        result: dict[str, Any],
        anomaly: dict[str, Any],
    ) -> None:
        """采集日志：阻断异常才落日志，提醒级失败不产生阻断日志。"""
        store.add(LOG_TABLE, {
            "日志编号": f"LOG-QC-{batch['id']}-{event['id']}-{snap['规则id']}",
            "关联任务": f"{batch['批次编号']} / {event['事件编号']} / {snap['规则编号']}",
            "日志级别": "阻断异常",
            "记录时间": _now(),
            "日志内容": (
                f"数据质量校验阻断：字段「{snap['校验字段']}」{result['判定说明']}；"
                f"采用规则版本 V{snap['版本号']}，阻断级别 {snap['阻断级别']}；"
                f"异常单号 {anomaly['异常编号']}"
            ),
            "错误堆栈": f"结论id={result.get('id')}；异常id={anomaly['id']}；批次id={batch['id']}",
            "处理状态": ANOMALY_OPEN,
            "处理人": "",
            "异常id": anomaly["id"],
            "批次id": batch["id"],
            "status": ANOMALY_OPEN,
            "pending": True,
            "abnormal": True,
        })

    # ------------------------------------------------------------------ 复核
    def recheck(
        self, *, batch_id: int, event_ids: list[int] | None = None, note: str = "容差更正后复核重算"
    ) -> tuple[dict[str, Any] | None, str]:
        original = store.find(BATCH_TABLE, batch_id)
        if original is None:
            return None, f"批次 {batch_id} 不存在"
        events = self._select_events(event_ids or original.get("event_ids", []))
        if not events:
            return None, "复核范围内没有事件"

        review_batch = store.add(BATCH_TABLE, {
            "批次编号": f"{original['批次编号']}-R{int(original['id'])}",
            "触发说明": note,
            "复核自批次id": batch_id,
            "event_ids": [int(event["id"]) for event in events],
            "规则版本快照": {},
            "冻结时间": _now(),
            "状态": BATCH_RUNNING,
            "结论数": 0,
            "阻断异常数": 0,
            "status": BATCH_RUNNING,
            "pending": True,
            "abnormal": False,
        })

        # 复核轮重新冻结当前启用版本，因此能体现"复核期间容差被更正"这一变化；
        # 旧批次快照保持不动，两轮口径各自可查、互不串用。
        snapshot: dict[int, dict[str, Any]] = {}
        for rule in store.rows(RULE_TABLE):
            if rule.get("启用状态") != "已启用":
                continue
            revision = store.find(REVISION_TABLE, int(rule["当前版本id"]))
            snapshot[int(rule["id"])] = {
                "规则id": int(rule["id"]),
                "规则编号": rule["规则编号"],
                "校验字段": rule["校验字段"],
                "校验类型": rule["校验类型"],
                "版本id": revision["id"],
                "版本号": revision["版本号"],
                "期望值": revision["期望值"],
                "容差": revision["容差"],
                "允许枚举": revision["允许枚举"],
                "阻断级别": revision["阻断级别"],
                "口径说明": revision["口径说明"],
            }
        review_batch["规则版本快照"] = snapshot

        # 当前结论唯一：同(事件, 规则)的旧当前结论先让位。
        # 注意按事件+规则维度而非按批次过滤——同一原批次可能被多次复核，
        # 上一轮复核批次产生的当前结论也必须让位，否则会出现两条 is_current。
        # 复核快照里没有的规则（如已停用）不产生新结论，其旧结论保持当前。
        review_event_ids = {int(event["id"]) for event in events}
        review_rule_ids = set(snapshot)
        old_current = [
            row for row in store.rows(RESULT_TABLE)
            if row.get("is_current")
            and int(row["事件id"]) in review_event_ids
            and int(row["规则id"]) in review_rule_ids
        ]
        for old in old_current:
            old["is_current"] = False
            old["结论状态"] = SUPERSEDED
            old["pending"] = False

        blocking_count = 0
        for event in events:
            for rule_id, snap in snapshot.items():
                result, is_blocking = self._evaluate(review_batch, event, snap)
                stored = store.add(RESULT_TABLE, result)
                self._apply_review_outcome(review_batch, event, snap, stored, is_blocking)
                if is_blocking:
                    blocking_count += 1

        review_batch["结论数"] = len(events) * len(snapshot)
        review_batch["阻断异常数"] = blocking_count
        review_batch["状态"] = BATCH_DONE
        review_batch["status"] = BATCH_DONE
        review_batch["pending"] = blocking_count == 0
        review_batch["abnormal"] = blocking_count > 0
        return review_batch, ""

    def _apply_review_outcome(
        self,
        review_batch: dict[str, Any],
        event: dict[str, Any],
        snap: dict[str, Any],
        result: dict[str, Any],
        is_blocking: bool,
    ) -> None:
        anomaly = next((
            row for row in store.rows(ANOMALY_TABLE)
            if int(row["事件id"]) == int(event["id"])
            and int(row["规则id"]) == int(snap["规则id"])
            and row["异常状态"] in ANOMALY_OPEN_STATUSES
        ), None)

        if result["结论"] == FAIL:
            if not is_blocking:
                # 提醒级失败只更新字段结论，不挂阻断异常、不写阻断日志
                return
            if anomaly is None:
                anomaly = self._register_anomaly(review_batch, event, snap, result, is_blocking)
            else:
                anomaly["异常状态"] = ANOMALY_RETRY
                anomaly["status"] = ANOMALY_RETRY
                anomaly["最近批次id"] = review_batch["id"]
                anomaly["最近结论id"] = result["id"]
                anomaly["重算次数"] = int(anomaly.get("重算次数", 0)) + 1
            result["异常id"] = anomaly["id"]
            if is_blocking:
                self._write_log(review_batch, event, snap, result, anomaly)
            return

        # 重算通过：异常解除；已派出处置不会被自动改写，等待人工沿用/撤销凭据。
        if anomaly is not None:
            anomaly["异常状态"] = ANOMALY_RESOLVED
            anomaly["status"] = ANOMALY_RESOLVED
            anomaly["pending"] = False
            anomaly["abnormal"] = False
            anomaly["最近批次id"] = review_batch["id"]
            anomaly["最近结论id"] = result["id"]
            anomaly["重算次数"] = int(anomaly.get("重算次数", 0)) + 1
            result["异常id"] = anomaly["id"]
            for log in store.rows(LOG_TABLE):
                if log.get("异常id") == anomaly["id"] and log.get("处理状态") == ANOMALY_OPEN:
                    log["处理状态"] = ANOMALY_RESOLVED
                    log["status"] = ANOMALY_RESOLVED
                    log["pending"] = False
                    log["abnormal"] = False

    # ------------------------------------------------------------------ 处置
    def issue_disposition(
        self, anomaly_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        anomaly = store.find(ANOMALY_TABLE, anomaly_id)
        if anomaly is None:
            return None, f"异常单 {anomaly_id} 不存在"
        if not anomaly.get("是否阻断"):
            return None, "提醒级异常不需要派出阻断处置"
        handler = str(values.get("处理人") or "").strip()
        action = str(values.get("处置动作") or "").strip()
        if not handler or not action:
            return None, "处理人与处置动作必填"

        basis = self._basis_snapshot(anomaly)
        if basis is None:
            return None, "找不到该异常对应的校验结论，无法固化处置依据"
        disposition = store.add("quality_disposition", {
            "处置单号": f"DSP-{anomaly['异常编号']}-{store.next_id('quality_disposition')}",
            "异常id": anomaly["id"],
            "事件id": anomaly["事件id"],
            "事件编号": anomaly["事件编号"],
            "规则id": anomaly["规则id"],
            "规则编号": anomaly["规则编号"],
            "处理人": handler,
            "处置动作": action,
            "处置说明": str(values.get("处置说明") or "").strip(),
            "处置状态": DISP_ISSUED,
            "依据结论id": basis["id"],
            "依据批次id": basis["批次id"],
            "依据版本号": basis["采用版本号"],
            "依据口径快照": deepcopy(basis["采用口径"]),
            "凭据链": [{
                "动作": "派出处置",
                "处理人": handler,
                "时间": _now(),
                "依据结论id": basis["id"],
                "依据版本号": basis["采用版本号"],
                "说明": f"按 {anomaly['异常编号']} 首报口径派出",
            }],
            "status": DISP_ISSUED,
            "pending": True,
            "abnormal": True,
        })
        anomaly["异常状态"] = "处置中"
        anomaly["status"] = "处置中"
        for log in store.rows(LOG_TABLE):
            if log.get("异常id") == anomaly["id"] and log.get("处理状态") == ANOMALY_OPEN:
                log["处理状态"] = "处置中"
                log["status"] = "处置中"
                log["处理人"] = handler
        return disposition, ""

    def resolve_conflict(
        self, disposition_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        """结论冲突时对已落库处置做沿用或撤销，全程追加凭据，不改写历史。"""
        disposition = store.find("quality_disposition", disposition_id)
        if disposition is None:
            return None, f"处置单 {disposition_id} 不存在"
        decision = str(values.get("decision") or "").strip()
        if decision not in (DISP_RETAINED, DISP_REVOKED):
            return None, "decision 仅支持「复核沿用」或「已撤销」"
        handler = str(values.get("处理人") or disposition.get("处理人") or "").strip()

        anomaly = store.find(ANOMALY_TABLE, int(disposition["异常id"]))
        latest_result = self._latest_current_result(
            int(disposition["事件id"]), int(disposition["规则id"])
        )
        if latest_result is None:
            return None, "找不到当前有效结论，无法核对冲突"

        chain = list(disposition.get("凭据链", []))
        chain.append({
            "动作": decision,
            "处理人": handler,
            "时间": _now(),
            "当前结论id": latest_result["id"],
            "当前版本号": latest_result["采用版本号"],
            "当前结论": latest_result["结论"],
            "原依据结论id": disposition["依据结论id"],
            "原依据版本号": disposition["依据版本号"],
            "说明": str(values.get("说明") or (
                "重算后仍失败，原处置继续有效" if decision == DISP_RETAINED
                else "容差更正后重算通过，撤销原处置"
            )),
        })
        disposition["凭据链"] = chain
        disposition["处置状态"] = decision
        disposition["status"] = decision
        disposition["pending"] = decision == DISP_RETAINED
        disposition["abnormal"] = decision == DISP_RETAINED
        disposition["核对结论id"] = latest_result["id"]

        if anomaly is not None and decision == DISP_REVOKED:
            if anomaly["异常状态"] == ANOMALY_RESOLVED:
                anomaly["异常状态"] = "已撤销处置"
                anomaly["status"] = "已撤销处置"
                anomaly["pending"] = False
                anomaly["abnormal"] = False
        return disposition, ""

    def _basis_snapshot(self, anomaly: dict[str, Any]) -> dict[str, Any] | None:
        """处置回查原依据：优先首报结论，找不到再退回最近结论。"""
        result_id = anomaly.get("首报结论id")
        result = store.find(RESULT_TABLE, int(result_id)) if result_id else None
        if result is None:
            result = store.find(RESULT_TABLE, int(anomaly["最近结论id"]))
        return result

    def _latest_current_result(self, event_id: int, rule_id: int) -> dict[str, Any] | None:
        candidates = [
            row for row in store.rows(RESULT_TABLE)
            if row.get("is_current")
            and int(row["事件id"]) == event_id
            and int(row["规则id"]) == rule_id
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda row: int(row["id"]))

    # ------------------------------------------------------------------ 查询
    def list_batches(self) -> list[dict[str, Any]]:
        return [dict(row) for row in store.rows(BATCH_TABLE)]

    def list_results(
        self,
        *,
        batch_id: int | None = None,
        event_id: int | None = None,
        current_only: bool = False,
    ) -> list[dict[str, Any]]:
        rows = store.rows(RESULT_TABLE)
        if batch_id is not None:
            rows = [row for row in rows if int(row["批次id"]) == batch_id]
        if event_id is not None:
            rows = [row for row in rows if int(row["事件id"]) == event_id]
        if current_only:
            rows = [row for row in rows if row.get("is_current")]
        return [dict(row) for row in rows]

    def list_anomalies(self, status: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(ANOMALY_TABLE)
        if status:
            rows = [row for row in rows if row.get("异常状态") == status]
        return [dict(row) for row in rows]

    def list_dispositions(self, anomaly_id: int | None = None) -> list[dict[str, Any]]:
        rows = store.rows("quality_disposition")
        if anomaly_id is not None:
            rows = [row for row in rows if int(row["异常id"]) == anomaly_id]
        return [dict(row) for row in rows]

    def trace(self, event_id: int, rule_id: int) -> dict[str, Any]:
        """处置人员回查：警报是否仍有效、当轮实际容差、已派出处置去向。"""
        event = store.find(EVENT_TABLE, event_id)
        rule = store.find(RULE_TABLE, rule_id)
        if event is None or rule is None:
            return {}
        current = self._latest_current_result(event_id, rule_id)
        anomaly = next((
            row for row in store.rows(ANOMALY_TABLE)
            if int(row["事件id"]) == event_id and int(row["规则id"]) == rule_id
        ), None)
        history = [
            dict(row) for row in store.rows(RESULT_TABLE)
            if int(row["事件id"]) == event_id and int(row["规则id"]) == rule_id
        ]
        history.sort(key=lambda row: int(row["id"]))
        dispositions = [
            dict(row) for row in store.rows("quality_disposition")
            if int(row["事件id"]) == event_id and int(row["规则id"]) == rule_id
        ]
        return {
            "事件": dict(event),
            "规则": dict(rule),
            "当前有效结论": dict(current) if current else None,
            "警报是否仍有效": bool(
                anomaly is not None
                and anomaly.get("异常状态") in ANOMALY_OPEN_STATUSES
                and current is not None and current["结论"] == FAIL
            ),
            "当轮实际使用容差": current["采用口径"].get("容差") if current else None,
            "当轮采用版本号": current["采用版本号"] if current else None,
            "异常单": dict(anomaly) if anomaly else None,
            "结论沿革": history,
            "处置去向": dispositions,
        }


service = QualityService()

# 导入即建表并灌入演示场景；store 是进程内单例，重启后自动回到初始演示态。
seed_quality_demo()
