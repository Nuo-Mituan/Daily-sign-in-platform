# 技术债登记（v1.0.5 封版审查）

> 本文件记录已确认但不在封版前修复的 P2/P3 问题。
> 责任人按角色登记；下一迭代启动时必须重新评估优先级。
>
> 排期与批次：[docs/TECH_DEBT_CLEARANCE_PLAN.md](TECH_DEBT_CLEARANCE_PLAN.md)
>
> **Batch 1 状态（2026-10-20）**：TD-01 / TD-02 / TD-03 / TD-05 / TD-10 已完成；
> TD-04 调整至 Batch 4（Router→Service 迁移）。核心服务/驱动的 `Any` 计数已降为 0。
>
> **Batch 2 状态（2026-10-20）**：TD-07 / TD-08 / TD-09 / TD-11 / TD-15 已完成。
> 推送批次具备稳定幂等键、事务性审计 outbox、全 skip `noop` 终态、驱动删除保护和可配置 HTTP 参数。
>
> **Batch 3 状态（2026-10-20）**：TD-06 / TD-13 / TD-14 / TD-16 / TD-20 已完成。
> 环形日志改为单写线程 + 有界队列；SSE 指标/重连滞后可查询；心跳可配置；新增只读系统日志页。

| ID | 优先级 | 位置 | 问题 | 影响 | 建议 | 责任人 |
| --- | --- | --- | --- | --- | --- | --- |
| TD-01 | P2 | `services/push_pool.py:90/175/321` | `ensure_batch` / `record_unified_result` / `_flush_locked` 超过 80 行、圈复杂度高 | 维护成本高，修改易引入批次状态回归 | 拆为 `_load_expected`、`_sync_skips`、`_record_probe`、`_apply_result`、`_send_summary`、`_persist_flush` | 平台维护者 |
| TD-02 | P2 | `routers/logs.py:123/140` | `stream_log` / `event_stream` 圈复杂度约 50 | SSE 分支难测试，异常路径易遗漏 | 抽出 `_replay_ring`、`_drain_live`、`_close_stale_log`、`_sse_payload` | 平台维护者 |
| TD-03 | P2 | `services/execution.py:330` | `_perform` 211 行、圈复杂度约 34 | 执行器职责过多，异常分支复杂 | 拆为 `load_inputs`、`run_accounts`、`aggregate_outcome`、`emit_header` | 执行器维护者 |
| TD-04 | P2 | `routers/modules.py:594` | `update_module` 133 行、圈复杂度约 31 | Router 内含业务编排，分层不纯 | 迁移到 `services/module_config.py`，Router 仅调用 service | 模块维护者 |
| TD-05 | P2 | `services/push.py`、`push_pool.py`、`ring_log.py` | 核心服务仍使用 52 处 `Any` | 契约弱化，重构时缺少静态保护 | 引入 `TypedDict`/dataclass：`PushConfigData`、`PushSendResult`、`RingRow` | 平台维护者 |
| TD-06 | P2 | `services/ring_log.py` | 同步 SQLite 写入在事件循环线程执行 | 高并发日志可能导致请求延迟 | 改为专用单写线程 + 有界队列；或 `asyncio.to_thread` 批量写入 | 平台维护者 |
| TD-07 | P2 | `services/push_pool.py:321` | 外部 HTTP 发送与 DB 最终化无法原子化，最坏情况重复汇总 | 网络抖动/崩溃后可能重复通知 | 提供服务商幂等键；或 `sending` 状态 + 人工确认队列 | 推送维护者 |
| TD-08 | P2 | `services/push_pool.py` + `ring_log.append_push` | 推送审计环形日志与 `push_records` 不同事务 | 极端崩溃可能缺少审计行 | 引入本地 outbox 表，同一 DB 事务写入，再由后台投递 | 平台维护者 |
| TD-09 | P2 | `services/push_pool.py` | 全部 skip 且无手动执行的批次永久 `pending` | 记录页显示等待中，池行只能等保留期清理 | 引入 `noop`/`skipped` 终态，手动补执行时可重新打开 | 推送维护者 |
| TD-10 | P2 | `push_pool._locks`、`execution._module_locks`、`schedules._schedule_locks`、`auth_guard._sensitive_locks` | 按 key 增长的锁字典不回收 | 长时间运行内存缓慢增长 | 引用计数或 LRU 锁池 | 平台维护者 |
| TD-11 | P2 | `push_drivers/registry.py` | 删除驱动前未检查全局推送配置是否仍引用 | 删除后测试/推送失败 | 删除前扫描 `push_config.channel`，或强制切换渠道 | 驱动维护者 |
| TD-12 | P2 | `push_drivers/registry.py` | 版本排序使用字符串排序 | `1.0.10` 可能排在 `1.0.9` 前 | 使用 `packaging.version.Version` 或数字元组 | 驱动维护者 |
| TD-13 | P2 | `services/capture.py` / `hub.py` | SSE 队列满时丢弃最旧事件 | 浏览器短暂断流，依赖 `last_seq` 重连补齐 | 记录 drop 指标；提高队列或转环形轮询 | 日志维护者 |
| TD-14 | P3 | `services/ring_log.py` | `15s` busy timeout、`6` retries、`10000` loop 等魔法值 | 调优需改代码 | 提取模块常量/配置 | 平台维护者 |
| TD-15 | P3 | `services/push.py` | HTTP 超时 `10/5`、响应截断 `4000`、重试 `0.8` 等硬编码 | 不同渠道无法独立调优 | 提取 `PUSH_HTTP_TIMEOUT` / `PUSH_RESPONSE_MAX_CHARS` | 推送维护者 |
| TD-16 | P3 | `routers/logs.py` | SSE keep-alive 固定 15 秒 | 不适合特殊代理 | 配置化 | 日志维护者 |
| TD-17 | P3 | `services/module_upload.py` | 临时文件 close 异常被静默忽略 | 极端文件句柄问题无日志 | 记录 debug 日志 | 模块维护者 |
| TD-18 | P3 | 全项目 | 未接入 import-linter / mypy / ruff CI | 回归依赖人工 | CI 增加 import-linter、mypy（渐进）、ruff | 平台维护者 |
| TD-19 | P3 | `services/execution.py` | 旧 `execution_logs.output` 字段保留 | 数据模型有历史包袱 | 下个大版本迁移后移除 | 平台维护者 |
| TD-20 | P3 | `docs` | 系统/应用环形日志无独立 Web 查询页 | 运维排查需查 DB | 增加系统日志只读页 | 运维维护者 |

---

## 下一迭代规划输入（Iteration 7）

本表为每项债务建立内部 Task 编号。正式 Issue Tracker 接入后，将 `RC6-TD-xx` 映射到对应 Issue；在此之前以本表作为排期依据。

| Task | 优先级 | 预估工时 | 验收标准 |
| --- | --- | --- | --- |
| `RC6-TD-01` | P2 | 1.5 人日 | `ensure_batch` / `record_unified_result` / `_flush_locked` 均 ≤80 行、圈复杂度 ≤15，且批次/skip/并发测试全过 |
| `RC6-TD-02` | P2 | 1 人日 | SSE 拆为回放/实时/收尾三个函数；断点续读、断线、超时测试全过 |
| `RC6-TD-03` | P2 | 1.5 人日 | `_perform` 拆为输入加载/账号执行/结果聚合；单账号/多账号/异常测试全过 |
| `RC6-TD-04` | P2 | 1 人日 | `update_module` 业务迁移到 service；Router 行数显著下降；API 契约不变 |
| `RC6-TD-05` | P2 | 2 人日 | 核心推送/环形/会话服务新增 TypedDict 或 dataclass，核心路径不再新增 `Any` |
| `RC6-TD-06` | P2 | 2 人日 | 环形日志改为单写线程/批量写；压测下请求 P95 不因日志写放大 |
| `RC6-TD-07` | P2 | 1 人日 | 明确 at-least-once 策略；补充幂等键或发送状态恢复方案与故障演练 |
| `RC6-TD-08` | P2 | 1.5 人日 | 推送审计 outbox 与业务记录同事务；故障注入下审计不丢失 |
| `RC6-TD-09` | P2 | 0.5 人日 | 全 skip 批次进入 `noop/skipped` 终态；手动补执行可重新打开；无推送 |
| `RC6-TD-10` | P2 | 0.5 人日 | 锁字典有回收策略；长跑内存曲线稳定 |
| `RC6-TD-11` | P2 | 0.5 人日 | 删除驱动前检查全局配置引用，返回明确错误或要求切换 |
| `RC6-TD-12` | P2 | 0.2 人日 | 版本按语义版本排序；回滚测试覆盖 `1.0.9` / `1.0.10` |
| `RC6-TD-13` | P2 | 1 人日 | SSE 队列丢弃有指标/日志；重连补齐测试覆盖 |
| `RC6-TD-14` | P3 | 0.2 人日 | 环形日志魔法值提取到模块常量/配置 |
| `RC6-TD-15` | P3 | 0.5 人日 | 推送超时/截断/退避可配置，渠道独立 |
| `RC6-TD-16` | P3 | 0.2 人日 | SSE keep-alive 可配置 |
| `RC6-TD-17` | P3 | 0.2 人日 | 临时文件关闭异常记录 debug 日志 |
| `RC6-TD-18` | P3 | 1.5 人日 | CI 接入 import-linter、ruff；mypy 渐进启用 |
| `RC6-TD-19` | P3 | 1 人日 | 下个大版本迁移后移除旧 `output` 字段 |
| `RC6-TD-20` | P3 | 1 人日 | 系统日志只读查询页可用，不影响模块日志隐私 |

### P2 首周排期要求

Iteration 7 第一周必须完成以下评估并给出排期：

- `RC6-TD-01` 上帝函数拆分；
- `RC6-TD-02` SSE 拆分；
- `RC6-TD-03` 执行器拆分；
- `RC6-TD-05` `Any` 类型清理；
- `RC6-TD-06` 环形日志同步写阻塞。

责任人：平台维护者（TD-01/02/05/06）、执行器维护者（TD-03）、推送维护者（TD-07/08/09/11/12）、日志维护者（TD-13）。

### 纳入下一迭代

`docs/TECH_DEBT.md` 作为 Iteration 7 规划输入项；每个 Task 在迭代计划中必须保留优先级、工时、验收标准与责任人。

---

## RC.2 清零状态

- [x] RC6-TD-01 Resolved in v1.0.0-rc.2
- [x] RC6-TD-02 Resolved in v1.0.0-rc.2
- [x] RC6-TD-03 Resolved in v1.0.0-rc.2
- [x] RC6-TD-04 Resolved in v1.0.0-rc.2
- [x] RC6-TD-05 Resolved in v1.0.0-rc.2
- [x] RC6-TD-06 Resolved in v1.0.0-rc.2
- [x] RC6-TD-07 Resolved in v1.0.0-rc.2
- [x] RC6-TD-08 Resolved in v1.0.0-rc.2
- [x] RC6-TD-09 Resolved in v1.0.0-rc.2
- [x] RC6-TD-10 Resolved in v1.0.0-rc.2
- [x] RC6-TD-11 Resolved in v1.0.0-rc.2
- [x] RC6-TD-12 Resolved in v1.0.0-rc.2
- [x] RC6-TD-13 Resolved in v1.0.0-rc.2
- [x] RC6-TD-14 Resolved in v1.0.0-rc.2
- [x] RC6-TD-15 Resolved in v1.0.0-rc.2
- [x] RC6-TD-16 Resolved in v1.0.0-rc.2
- [x] RC6-TD-17 Resolved in v1.0.0-rc.2
- [x] RC6-TD-18 Resolved in v1.0.0-rc.2
- [x] RC6-TD-19 Resolved in v1.0.0-rc.2
- [x] RC6-TD-20 Resolved in v1.0.0-rc.2
