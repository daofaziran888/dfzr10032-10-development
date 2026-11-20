"""数据质量校验 HTTP 冒烟：需先启动后端（uvicorn app.main:app）。

运行：python3 -I tests/http_smoke_quality.py
"""
"""数据质量校验 HTTP 链路冒烟测试（仅标准库，对接本地 uvicorn）。"""
import json
import sys
import urllib.parse
import urllib.request

import os
BASE = os.environ.get("QC_BASE", "http://127.0.0.1:8000/api")
failures: list[str] = []


def call(method: str, path: str, payload: dict | None = None):
    if "?" in path:
        head, query = path.split("?", 1)
        query = urllib.parse.urlencode(urllib.parse.parse_qsl(query))
        path = f"{head}?{query}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# 1. 种子数据
rule = next(r for r in call("GET", "/quality/rules")["items"] if r["规则编号"] == "R-WT-DEV")
revs = call("GET", f"/quality/rules/{rule['id']}/revisions")["items"]
check("水温规则含 V1容差2、V2容差3", [r["容差"] for r in revs] == [2, 3])

trace = call("GET", f"/quality/trace?event_id=1&rule_id={rule['id']}")
check("回查：警报仍有效、当轮容差2、版本V1",
      trace["警报是否仍有效"] is True and trace["当轮实际使用容差"] == 2
      and trace["当轮采用版本号"] == 1)
check("回查：已派出处置可查且依据容差2",
      trace["处置去向"][0]["处置状态"] == "已派出"
      and trace["处置去向"][0]["依据口径快照"]["容差"] == 2)

# 2. 事件登记与载荷校验
ev = call("POST", "/quality/events", {"values": {
    "事件编号": "EVT-HTTP-01", "事件载荷": "水温偏差=2.4,设备编号=SENS-X9"}})
event_id = ev["entry"]["id"]
check("事件登记并标准化", ev["entry"]["标准化字段"]["水温偏差"] == 2.4)
bad = call("POST", "/quality/events", {"values": {"事件编号": "BAD", "事件载荷": "坏数据"}})
check("非法载荷被拒", bad["ok"] is False and "字段=值" in bad["message"])

# 3. 建规则（容差2）并首轮校验
nr = call("POST", "/quality/rules", {"values": {
    "规则编号": "R-HTTP-DEV", "校验字段": "水温偏差", "校验类型": "数值偏差",
    "期望值": 0, "容差": 2, "阻断级别": "阻断"}})
nr_id = nr["entry"]["id"]
check("规则登记生成 V1", nr["entry"]["当前版本号"] == 1)
b1 = call("POST", "/quality/checks", {"values": {"event_ids": [event_id], "触发说明": "HTTP首轮"}})
b1_id = b1["entry"]["id"]
check("首轮1条阻断异常", b1["entry"]["阻断异常数"] == 1)
check("批次冻结口径容差2", b1["entry"]["规则版本快照"][str(nr_id)]["容差"] == 2)

# 4. 阻断异常与采集日志
anm = next(a for a in call("GET", "/quality/anomalies?status=待处置")["items"]
           if a["事件id"] == event_id and a["规则id"] == nr_id)
anm_id = anm["id"]
logs = [lg for lg in call("GET", "/log_viewer")["items"] if lg.get("异常id") == anm_id]
check("采集日志写入阻断异常且带凭据", len(logs) == 1 and "结论id=" in logs[0]["错误堆栈"])

# 5. 派出处置
dsp = call("POST", f"/quality/anomalies/{anm_id}/dispositions",
           {"values": {"处理人": "王工", "处置动作": "现场检修"}})
dsp_id = dsp["entry"]["id"]
check("处置固化 V1 容差2 依据",
      dsp["entry"]["依据版本号"] == 1 and dsp["entry"]["依据口径快照"]["容差"] == 2)

# 6. 容差更正为3 后复核
cor = call("POST", f"/quality/rules/{nr_id}/revisions",
           {"values": {"容差": 3, "更正原因": "HTTP复核期更正"}})
check("更正生成 V2", cor["entry"]["版本号"] == 2)
b1_snapshot = next(b for b in call("GET", "/quality/batches")["items"] if b["id"] == b1_id)
check("历史批次快照仍是容差2（不混用）", b1_snapshot["规则版本快照"][str(nr_id)]["容差"] == 2)
rb = call("POST", f"/quality/batches/{b1_id}/recheck", {"values": {}})
check("复核批次阻断归零", rb["entry"]["阻断异常数"] == 0)
cur = next(r for r in call("GET", f"/quality/results?event_id={event_id}&current_only=true")["items"]
           if r["规则id"] == nr_id)
check("当前结论通过且采用 V2 容差3", cur["结论"] == "通过" and cur["采用版本号"] == 2)
pair = [r for r in call("GET", f"/quality/results?event_id={event_id}")["items"]
        if r["规则id"] == nr_id]
check("同事件同规则仅一条当前结论", sum(1 for r in pair if r["is_current"]) == 1)
check("旧结论保留且标记已取代", any(not r["is_current"] and r["结论状态"] == "已被重算取代" for r in pair))
anm2 = next(a for a in call("GET", "/quality/anomalies")["items"] if a["id"] == anm_id)
check("旧异常单复用、解除、重算次数+1",
      anm2["异常状态"] == "重算通过已解除" and anm2["首报版本号"] == 1 and anm2["重算次数"] == 1)

# 7. 冲突凭据：撤销
cf = call("POST", f"/quality/dispositions/{dsp_id}/conflict",
          {"values": {"decision": "已撤销", "处理人": "值班长"}})
check("处置撤销且凭据链两条", cf["entry"]["处置状态"] == "已撤销"
      and len(cf["entry"]["凭据链"]) == 2
      and cf["entry"]["凭据链"][0]["动作"] == "派出处置")

# 8. 题设种子场景复核
seed_batch = next(b for b in call("GET", "/quality/batches")["items"]
                  if b["批次编号"] == "BATCH-20261120-01")
call("POST", f"/quality/batches/{seed_batch['id']}/recheck", {"values": {}})
trace2 = call("GET", f"/quality/trace?event_id=1&rule_id={rule['id']}")
check("题设复核：警报失效、当轮容差3、版本V2",
      trace2["警报是否仍有效"] is False and trace2["当轮实际使用容差"] == 3
      and trace2["当轮采用版本号"] == 2)
check("题设复核：原处置仍在、未被自动改写",
      trace2["处置去向"][0]["处置状态"] == "已派出"
      and trace2["处置去向"][0]["依据口径快照"]["容差"] == 2)
cf2 = call("POST", f"/quality/dispositions/{trace2['处置去向'][0]['id']}/conflict",
           {"values": {"decision": "已撤销", "处理人": "值班长"}})
check("题设复核：撤销凭据关闭处置", cf2["entry"]["处置状态"] == "已撤销")

# 9. OpenAPI 文档完整挂载
with urllib.request.urlopen(os.environ.get("QC_OPENAPI", "http://127.0.0.1:8000/openapi.json"), timeout=10) as resp:
    schema = json.loads(resp.read().decode())
paths = {p for p in schema["paths"] if p.startswith("/api/quality")}
check("质量模块接口全部挂载", len(paths) >= 11)

print()
if failures:
    print(f"共 {len(failures)} 项失败：{failures}")
    sys.exit(1)
print("HTTP 冒烟全部通过")
