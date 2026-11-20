# 多源数据采集与RPA自动化平台

面向网页抓取、API接入、增量采集、RPA流程编排、数据校验与采集监控的数据工程平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 数据源配置 | `datasource` | 数据源 | 源端编号、连接类型、接入地址 |
| 网页采集规则 | `crawler` | 采集规则 | 规则编号、目标网址、页面选择器 |
| API接入管理 | `apiclient` | API客户端 | 客户端编号、接口名称、请求方法 |
| 增量采集 | `incremental` | 增量游标 | 游标编号、来源标识、增量字段 |
| RPA任务编排 | `robot_task` | RPA任务 | 任务编号、任务名称、页面定位器 |
| 数据接入通道 | `ingestion` | 接入通道 | 通道编号、通道名称、输入格式 |
| 格式解析器 | `parser` | 解析配置 | 解析编号、输入格式、输出格式 |
| 采集结果校验 | `validator` | 校验规则 | 规则编号、校验字段、校验类型 |
| 数据质量校验 | `quality` | 标准化事件/规则版本/校验结论/阻断异常/处置凭据 | 规则版本快照、失败字段、是否阻断、凭据链 |
| 采集去重 | `dedup` | 去重策略 | 策略编号、输入来源、去重键 |
| 采集调度 | `schedule` | 调度计划 | 计划编号、关联任务、调度周期 |
| 采集监控 | `monitor` | 监控面板 | 面板编号、采集源总数、今日采集量 |
| 采集日志 | `log_viewer` | 日志条目 | 日志编号、关联任务、日志级别 |
| 凭证管理 | `auth` | 认证凭证 | 凭证编号、凭证类型、关联数据源 |
| 采集转换管道 | `transform` | 转换节点 | 节点编号、输入来源、输出目标 |
| 数据流转编排 | `flow` | 流转管道 | 管道编号、管道名称、起始节点 |
| 数据血缘追踪 | `lineage` | 血缘关系 | 关系编号、上游节点、下游节点 |
| 采集报告 | `report` | 采集报告 | 报告编号、采集源、统计周期 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 数据质量校验（quality 模块）

对标准化事件做字段级校验，结论保留采用的规则口径、失败字段与是否阻断，核心约束：

- **口径冻结**：每轮校验开跑时把启用规则的当前版本（期望值/容差/阻断级别）整体快照到
  批次（`规则版本快照`），整轮只读快照；复核期间容差被更正也不影响当轮，
  下一轮校验/复核才按新版本重新冻结——同一次校验绝不混用变更前后的容差。
- **当前结论唯一**：同一事件+规则在全库最多一条 `is_current` 结论；重算时旧结论置为
  `已被重算取代` 但保留完整依据，可随时回查。
- **处置不可改写**：处置单落库即固化首报结论 id 与口径快照；容差更正、结论翻转都不会
  改动已派出处置，只能通过「复核沿用 / 已撤销」追加凭据链。
- **阻断异常与采集日志联动**：阻断级失败才生成异常单并写入采集日志（提醒级只留字段结论）；
  重算通过后同一张异常单解除、关联日志同步关闭。
- **回查台账**：`GET /api/quality/trace?event_id=&rule_id=` 一次给出警报是否仍有效、
  当轮实际使用容差/版本、结论沿革与全部处置去向。

内置水温偏差演示场景（事件 EVT-WT-01，实测 2.4 度，V1 容差 2 度已阻断并派出处置，
复核期间已提交 V2 容差 3 度），启动后可直接在「数据质量校验」页面复核。

验证脚本（仅依赖标准库）：

```bash
cd backend
python3 -I tests/test_quality.py          # 服务层 33 项约束
python3 -m uvicorn app.main:app &         # 先起服务
python3 -I tests/http_smoke_quality.py    # HTTP 链路冒烟
```
