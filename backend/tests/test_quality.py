"""数据质量校验链路的端到端验证（只依赖标准库 + 应用代码）。

运行：cd backend && python3 -I tests/test_quality.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.services.quality import (  # noqa: E402
    service,
    BLOCK, CHECK_RANGE, CHECK_REQUIRED,
    PASS, FAIL, CURRENT, SUPERSEDED,
    ANOMALY_OPEN, ANOMALY_RESOLVED,
    DISP_ISSUED, DISP_RETAINED, DISP_REVOKED,
)
from app.store import store  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" -- {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def fresh_event(code: str, payload: str) -> dict:
    event, msg = service.create_event({"事件编号": code, "事件载荷": payload})
    assert event, msg
    return event


# ---------------------------------------------------------------- 1. 种子数据
rules = service.list_rules()
check("种子：存在已启用规则", len(rules) >= 2)
wt_rule = next(r for r in rules if r["规则编号"] == "R-WT-DEV")
revs = service.list_revisions(wt_rule["id"])
check("种子：水温规则有 V1(容差2)/V2(容差3) 两个版本",
      [r["版本号"] for r in revs] == [1, 2]
      and revs[0]["容差"] == 2 and revs[1]["容差"] == 3)
check("种子：规则当前指向 V2", wt_rule["当前版本号"] == 2)
seed_results = service.list_results(current_only=True)
check("种子：首轮结论仍按 V1 容差2 判定",
      any(r["规则编号"] == "R-WT-DEV" and r["事件编号"] == "EVT-WT-01"
          and r["结论"] == FAIL and r["采用版本号"] == 1 for r in seed_results))

# ---------------------------------------------------------------- 2. 新建事件并跑首轮校验
e1 = fresh_event("EVT-T-01", "水温偏差=2.4,车间=二车间")
e2 = fresh_event("EVT-T-02", "水温偏差=0.5,车间=四车间")
batch, msg = service.run_check(event_ids=[e1["id"], e2["id"]], trigger_note="测试首轮")
assert batch, msg
b1_id = batch["id"]
check("首轮：批次冻结了规则版本快照", set(batch["规则版本快照"].keys()) == {r["id"] for r in rules})
snap_tol = batch["规则版本快照"][wt_rule["id"]]["容差"]
check("首轮：按当前 V2 容差3 冻结（2.4 应通过）", snap_tol == 3)

r1 = [r for r in service.list_results(batch_id=b1_id, event_id=e1["id"])
      if r["规则id"] == wt_rule["id"]][0]
check("首轮：2.4 对容差3 判定通过", r1["结论"] == PASS and r1["失败字段"] is None)
enum_rule = next(r for r in rules if r["规则编号"] == "R-SHOP-ENUM")
r2 = [r for r in service.list_results(batch_id=b1_id, event_id=e2["id"])
      if r["规则id"] == enum_rule["id"]][0]
check("首轮：枚举失败字段被记录且为提醒级不阻断",
      r2["结论"] == FAIL and r2["失败字段"] == "车间" and r2["是否阻断"] is False)
check("首轮：提醒级失败不产生阻断异常",
      not any(a["事件id"] == e2["id"] and a["规则id"] == enum_rule["id"]
              for a in service.list_anomalies()))

# ---------------------------------------------------------------- 3. 口径冻结：批次执行期间容差更正不影响当轮
rule_new, msg = service.create_rule({
    "规则编号": "R-FREEZE", "校验字段": "水温偏差", "校验类型": CHECK_RANGE,
    "期望值": 0, "容差": 2, "阻断级别": BLOCK,
})
assert rule_new, msg
e3 = fresh_event("EVT-T-03", "水温偏差=2.4")
b2, msg = service.run_check(event_ids=[e3["id"]], trigger_note="冻结测试")
assert b2, msg
frozen_snapshot = b2["规则版本快照"][rule_new["id"]]
# 批次跑完后更正容差
rev, msg = service.correct_tolerance(rule_new["id"], {"容差": 3, "更正原因": "批次后放宽"})
assert rev and rev["版本号"] == 2, msg
b2_again = store.find("quality_batch", b2["id"])
check("口径冻结：历史批次快照仍是旧容差2，未被更正污染",
      b2_again["规则版本快照"][rule_new["id"]]["容差"] == 2
      and b2_again["规则版本快照"][rule_new["id"]]["版本号"] == 1)
old_res = [r for r in service.list_results(batch_id=b2["id"], event_id=e3["id"])
           if r["规则id"] == rule_new["id"]][0]
check("口径冻结：旧结论保持失败且依据 V1",
      old_res["结论"] == FAIL and old_res["采用版本号"] == 1)

# ---------------------------------------------------------------- 4. 阻断异常 + 采集日志 + 派出处置
anomaly = next(a for a in service.list_anomalies()
               if a["事件id"] == e3["id"] and a["规则id"] == rule_new["id"])
check("阻断：2.4 对容差2 生成阻断异常", anomaly["是否阻断"] is True and anomaly["异常状态"] == ANOMALY_OPEN)
qc_logs = [lg for lg in store.rows("log_viewer") if lg.get("异常id") == anomaly["id"]]
check("采集日志：阻断异常写入日志并带异常/结论/批次凭据", len(qc_logs) == 1 and "结论id=" in qc_logs[0]["错误堆栈"])

dsp, msg = service.issue_disposition(anomaly["id"], {"处理人": "王工", "处置动作": "现场检修"})
assert dsp, msg
check("处置：派出时固化 V1 容差2 口径快照",
      dsp["依据版本号"] == 1 and dsp["依据口径快照"]["容差"] == 2)

# ---------------------------------------------------------------- 5. 复核重算：当前结论唯一 + 旧异常关联新处置记录
b3, msg = service.recheck(batch_id=b2["id"], note="容差更正为3后复核")
assert b3, msg
new_res = [r for r in service.list_results(batch_id=b3["id"], event_id=e3["id"])
           if r["规则id"] == rule_new["id"]][0]
check("复核：按 V2 容差3 重算，2.4 通过", new_res["结论"] == PASS and new_res["采用版本号"] == 2)
pair_results = [r for r in service.list_results(event_id=e3["id"]) if r["规则id"] == rule_new["id"]]
current = [r for r in pair_results if r["is_current"]]
check("当前结论唯一：同事件同规则只有一条 is_current", len(current) == 1 and current[0]["id"] == new_res["id"])
check("旧结论：被标记为已取代但保留可回查",
      any(not r["is_current"] and r["结论状态"] == SUPERSEDED for r in pair_results))
anomaly2 = next(a for a in service.list_anomalies()
                if a["事件id"] == e3["id"] and a["规则id"] == rule_new["id"])
check("异常复用：仍是同一张异常单（旧异常关联重算记录）",
      anomaly2["id"] == anomaly["id"] and anomaly2["异常状态"] == ANOMALY_RESOLVED
      and anomaly2["首报版本号"] == 1 and anomaly2["重算次数"] == 1)
dsp_reloaded = store.find("quality_disposition", dsp["id"])
check("处置不可改写：重算通过后原处置仍为已派出、依据仍是 V1",
      dsp_reloaded["处置状态"] == DISP_ISSUED and dsp_reloaded["依据版本号"] == 1)

# ---------------------------------------------------------------- 6. 结论冲突凭据：撤销
dsp2, msg = service.resolve_conflict(dsp["id"], {"decision": DISP_REVOKED, "处理人": "李工"})
assert dsp2, msg
check("冲突凭据：撤销后状态翻转且历史派出凭据保留",
      dsp2["处置状态"] == DISP_REVOKED and len(dsp2["凭据链"]) == 2
      and dsp2["凭据链"][0]["动作"] == "派出处置" and dsp2["凭据链"][1]["动作"] == DISP_REVOKED
      and dsp2["核对结论id"] == new_res["id"])

# ---------------------------------------------------------------- 7. 冲突沿用（重算后仍失败的场景）
rule_b, _ = service.create_rule({
    "规则编号": "R-KEEP", "校验字段": "水温偏差", "校验类型": CHECK_RANGE,
    "期望值": 0, "容差": 1, "阻断级别": BLOCK,
})
e4 = fresh_event("EVT-T-04", "水温偏差=5")
b4, _ = service.run_check(event_ids=[e4["id"]], trigger_note="沿用测试")
an4 = next(a for a in service.list_anomalies()
           if a["事件id"] == e4["id"] and a["规则id"] == rule_b["id"])
d4, _ = service.issue_disposition(an4["id"], {"处理人": "赵工", "处置动作": "停机检查"})
service.correct_tolerance(rule_b["id"], {"容差": 2, "更正原因": "小幅放宽仍不够"})
b5, _ = service.recheck(batch_id=b4["id"])
d4b, msg = service.resolve_conflict(d4["id"], {"decision": DISP_RETAINED})
assert d4b, msg
check("冲突凭据：重算仍失败时可沿用，链上同时留原依据与当前结论",
      d4b["处置状态"] == DISP_RETAINED
      and d4b["凭据链"][-1]["当前结论"] == FAIL
      and d4b["凭据链"][-1]["原依据版本号"] == 1)

# ---------------------------------------------------------------- 8. 水温场景回查台账（题设示例）
trace = service.trace(1, wt_rule["id"])
check("回查：能取到警报有效性/当轮容差/处置去向三要素",
      "警报是否仍有效" in trace and "当轮实际使用容差" in trace and "处置去向" in trace)
check("回查：种子场景当前结论仍是 V1 失败、警报有效、当轮容差2",
      trace["警报是否仍有效"] is True and trace["当轮实际使用容差"] == 2
      and trace["当轮采用版本号"] == 1)
check("回查：已派出处置可查到去向与首报依据",
      len(trace["处置去向"]) == 1 and trace["处置去向"][0]["处置状态"] == DISP_ISSUED
      and trace["处置去向"][0]["依据口径快照"]["容差"] == 2)

# 对种子场景执行复核（V2 容差3），警报应解除
seed_batch = next(b for b in service.list_batches() if b["批次编号"] == "BATCH-20261120-01")
rb, msg = service.recheck(batch_id=seed_batch["id"], note="题设：复核期间容差已更正为3")
assert rb, msg
trace2 = service.trace(1, wt_rule["id"])
check("题设复核：2.4 对容差3 通过，警报失效", trace2["警报是否仍有效"] is False
      and trace2["当轮实际使用容差"] == 3 and trace2["当轮采用版本号"] == 2)
check("题设复核：先前派出的处置仍可回查，等待撤销/沿用凭据",
      len(trace2["处置去向"]) == 1 and trace2["处置去向"][0]["处置状态"] == DISP_ISSUED)
seed_dsp_id = trace2["处置去向"][0]["id"]
d_final, _ = service.resolve_conflict(seed_dsp_id, {"decision": DISP_REVOKED, "处理人": "值班长"})
check("题设复核：撤销凭据落链，处置去向可核对",
      d_final["处置状态"] == DISP_REVOKED and len(d_final["凭据链"]) == 2)

# ---------------------------------------------------------------- 9. 同一原批次重复复核：当前结论仍唯一
service.correct_tolerance(rule_new["id"], {"容差": 4, "更正原因": "再次放宽"})
b3b, msg = service.recheck(batch_id=b2["id"], note="对同一原批次第二次复核")
assert b3b, msg
pair_results_b = [r for r in service.list_results(event_id=e3["id"]) if r["规则id"] == rule_new["id"]]
current_b = [r for r in pair_results_b if r["is_current"]]
check("重复复核：同事件同规则仍只有一条当前结论（最新复核批次）",
      len(current_b) == 1 and current_b[0]["批次id"] == b3b["id"]
      and current_b[0]["采用版本号"] == 3)
check("重复复核：历史结论全部保留可回查", len(pair_results_b) == 3)

# ---------------------------------------------------------------- 10. 普通校验重复执行：当前结论全局唯一
e6 = fresh_event("EVT-T-06", "水温偏差=2.4")
b7, _ = service.run_check(event_ids=[e6["id"]], trigger_note="重复校验第一次")
b8, _ = service.run_check(event_ids=[e6["id"]], trigger_note="重复校验第二次")
pair_c = [r for r in service.list_results(event_id=e6["id"]) if r["规则id"] == rule_new["id"]]
current_c = [r for r in pair_c if r["is_current"]]
check("重复普通校验：同事件同规则仍只有一条当前结论",
      len(current_c) == 1 and current_c[0]["批次id"] == b8["id"])
check("重复普通校验：首轮结论已让位但仍可回查",
      any(r["批次id"] == b7["id"] and r["结论状态"] == SUPERSEDED for r in pair_c))

# ---------------------------------------------------------------- 11. 必填规则与载荷校验
rule_c, _ = service.create_rule({
    "规则编号": "R-REQ", "校验字段": "设备编号", "校验类型": CHECK_REQUIRED,
    "阻断级别": BLOCK,
})
e5 = fresh_event("EVT-T-05", "水温偏差=0.1")
b6, _ = service.run_check(event_ids=[e5["id"]], trigger_note="必填测试")
rr = [r for r in service.list_results(batch_id=b6["id"], event_id=e5["id"])
      if r["规则id"] == rule_c["id"]][0]
check("必填规则：缺字段判失败并阻断", rr["结论"] == FAIL and rr["是否阻断"] is True)
bad, msg = service.create_event({"事件编号": "BAD-1", "事件载荷": "没有等号"})
check("载荷校验：非法载荷被拒并提示", bad is None and "字段=值" in msg)

print()
if failures:
    print(f"共 {len(failures)} 项失败：{failures}")
    sys.exit(1)
print("全部约束验证通过")
