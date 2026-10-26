# 第六轮封版前代码质量与架构健康度审查报告

- 审查时间：2026-10-19
- 范围：v1.0.5 安全基础、环形日志、推送重构，以及历史遗留的调度/模块配置代码
- 方法：AST 复杂度扫描、异常与资源扫描、导入关系检查、Schema/ORM 对照、全量测试与 API/浏览器验证
- 结论：**未发现 P0 缺陷；3 项 P1 已在封版前修复；剩余 P2/P3 已登记 `docs/TECH_DEBT.md`**

---

## 一、问题清单

### P0（阻塞）— 0 项

未发现会导致数据不可恢复、认证绕过、任意文件写入或启动即故障的 P0 缺陷。

### P1（高）— 3 项，均已修复

#### P1-01 驱动注册表与推送服务循环依赖

- 文件：`backend/app/push_drivers/registry.py`
- 原位置：`builtin_records()` 内部 `from ..services.push import CHANNEL_SPECS`
- 问题：`services.push` 导入 `push_drivers.registry`，registry 在运行时反向导入 `services.push`，形成隐式循环。导入顺序变化时可能触发 `ImportError` 或半初始化模块。
- 复现：在未先导入 `app.services.push` 的进程中直接导入 `app.push_drivers.registry`，并调用 `list_drivers()`。
- 修复：将内置渠道元数据迁移到 `backend/app/push_drivers/builtin_specs.py`；`push.py` 与 registry 均只依赖该模块。
- 当前：`registry.py:107-108` 使用 `from .builtin_specs import CHANNEL_SPECS`，无反向服务导入。
- 回归：独立进程导入 registry，确认 `app.services.push` 不在 `sys.modules`。

#### P1-02 推送配置解密失败时静默覆盖旧凭据

- 文件：`backend/app/services/push.py:249`
- 问题：`save_push_config()` 捕获 `ParameterDecryptionError` 后把 `previous` 置空，用户保存新配置会覆盖无法解密的旧凭据，造成不可逆数据丢失。
- 复现：将 `push_config.config_encrypted` 人为破坏，然后调用 `PUT /api/push/config`。
- 修复：解密失败抛出 `PushConfigError`，拒绝保存并提示恢复 `SECRET_KEY` 或重置配置。
- 回归：`test_corrupt_push_config_is_not_silently_overwritten`。

#### P1-03 环形日志写入失败导致执行正文彻底丢失

- 文件：`backend/app/services/capture.py:40/82/94`、`backend/app/services/execution.py:651-660`
- 问题：`ring_log.append()` 在 SQLite 锁竞争耗尽重试后返回 0；原实现只把正文保留在内存中，最终 `_finalize` 写 `NULL`，日志永久丢失。
- 复现：并发持有 SQLite 写锁，使环形写入失败，执行结束后无 `ring_logs` 行，`execution_logs.output` 为 `NULL`。
- 修复：
  - `OutputCapture.ring_failed` 标记降级状态；
  - `_execute()` 在环形失败时把内存正文作为**紧急 legacy fallback**写入 `execution_logs.output`；
  - 正常路径仍坚持环形日志为唯一正文入口。
- 回归：`test_ring_write_failure_marks_emergency_fallback`。

### P2（中）— 主要发现

| ID | 文件/行 | 问题 | 处理 |
| --- | --- | --- | --- |
| P2-01 | `services/push_pool.py:90/175/321` | `ensure_batch` 83 行/cc~18，`record_unified_result` 76 行/cc~26，`_flush_locked` 86 行/cc~18 | 登记 TD-01，下一迭代拆分 |
| P2-02 | `routers/logs.py:123/140` | `stream_log` 165 行/cc~53，`event_stream` 138 行/cc~49 | 登记 TD-02 |
| P2-03 | `services/execution.py:330` | `_perform` 211 行/cc~34 | 登记 TD-03 |
| P2-04 | `routers/modules.py:594` | `update_module` 133 行/cc~31，Router 含业务编排 | 登记 TD-04 |
| P2-05 | 核心服务 | 52 处 `Any`，`crypto.decrypt_any` 返回 `Any` | 登记 TD-05 |
| P2-06 | `services/ring_log.py` | 同步 SQLite 写入在事件循环线程执行，锁竞争时阻塞请求 | 登记 TD-06 |
| P2-07 | `services/push_pool.py:321` | 外部 HTTP 发送与 DB 最终化无法原子化，崩溃/网络抖动可能重复日报 | 登记 TD-07；当前为 at-least-once 语义 |
| P2-08 | `push_pool` + ring push audit | 审计环形日志与 `push_records` 不同事务 | 登记 TD-08，审计缺失不阻断业务 |
| P2-09 | `push_pool` | 全部 skip 且无手动执行的批次长期 `pending` | 登记 TD-09；无推送符合业务规则 |
| P2-10 | 多个 Lock 字典 | 按 key 增长不回收 | 登记 TD-10 |
| P2-11 | `push_drivers/registry.py` | 删除驱动前未检查全局配置引用；版本字符串排序 | 登记 TD-11/TD-12 |
| P2-12 | `capture.py`/`hub.py` | SSE 队列满时丢弃最旧事件 | 登记 TD-13；依赖 `last_seq` 重连补齐 |

**事务边界结论：**

- `push_batches` 状态、`push_records` 插入、`push_pool` 删除在 `_flush_locked()` 的同一 SQLAlchemy 事务中提交；
- 外部 HTTP 与 DB 无法组成分布式事务，当前明确采用 **at-least-once**；
- 环形推送审计是独立连接，属于审计补充，业务摘要以 `push_records` 为准；
- 未发现“池已清理但记录未写”的单库事务缺口；崩溃窗口是“外部已发送但 DB 未提交”，已登记 TD-07。

### P3（低）— 主要发现

- 魔法值：`ring_log` 的 15s/6 次/10000 循环，`push` 的 10s/5s/0.8s/4000 字符，SSE 15s keep-alive；登记 TD-14~TD-16。
- `module_upload` 关闭临时文件的异常被静默忽略；登记 TD-17。
- 未接入 import-linter/mypy/ruff CI；登记 TD-18。
- 旧 `execution_logs.output` 字段保留；登记 TD-19。
- 系统日志暂无独立 Web 查询页；登记 TD-20。

---

## 二、异常、资源与锁审查

### 异常

- 全项目无裸 `except:`。
- `except Exception` 均位于边界层，并满足以下之一：
  - 重新抛出（`database.get_db` rollback + raise）；
  - 记录 `logger.exception`（execution、scheduler、push、main）；
  - 明确降级并写审计（`push_pool` 汇总失败）；
  - 日志系统自身“不得失败”的兜底（`redaction`/`module_upload` close）。
- 已修复两处静默吞异常：
  - 推送配置解密失败；
  - 账号密文升级失败改为 warning + 保留原密文。

### 资源

- SQLAlchemy：41 处 `SessionLocal` 全部 `async with`。
- 文件 I/O：ZIP、驱动文件、模块上传均使用 `with`。
- HTTP：`httpx.AsyncClient` 使用 `async with`。
- 环形日志：`contextlib.closing` 保证 SQLite 连接关闭。
- SSE：`finally` 中 `hub.unsubscribe`。
- 锁：`asyncio.Lock`/`threading.RLock`/`Lock` 均在 `with`/`async with`/`finally` 中释放；异常分支未发现未释放锁。

---

## 三、类型与契约

- `ModuleOut.push_independent/push_unified` 与 ORM 可空字段通过 `_module_out()` 统一 `bool()`。
- `PushBatchOut` 与 `PushBatch` 字段一致，包含 `deadline_at/details_cleared/retry_count`。
- `LogDetail.last_seq` 由环形日志读取后填充。
- `PushRecordOut`/`PushBatchOut` 使用 `from_attributes=True`。
- 前端已实际浏览器验证模块双开关、推送中心、日志设置、SSE 断点续读。
- 核心服务仍有 `Any`（TD-05），不影响当前契约，但列为 P2。

---

## 四、架构与依赖

- Router → Service → Model 分层总体成立。
- `services/` 不导入 `routers/`；`models.py` 不导入业务服务。
- 已消除 registry ↔ push 的运行时反向导入。
- 遗留分层问题：`routers/logs.py` SSE 编排、`routers/modules.py update_module` 业务编排，登记 P2。
- 未引入 import-linter，建议下一迭代 CI 增加。

---

## 五、幂等与迁移

- `migrate_schema()`：
  - 仅添加缺失列；
  - `push_independent` 仅在 NULL 时按 `push_enabled` 填充；
  - 周期规范化重复执行结果稳定。
- v1→v2：
  - 以 `v2:` 前缀判断，已升级记录不会重复加密；
  - 模块详情、执行前、推送配置读取三条路径均幂等。
- 旧 `execution_logs.output`：
  - 仅当环形日志为空时作为只读回退；
  - 新执行正常路径不写该字段。
- 新增回归：
  - 旧 push 开关迁移；
  - v1 模块密文升级；
  - 旧 output 回退；
  - 重复迁移不产生脏数据（字段已迁移后保持原值）。

---

## 六、测试与验证

| 验证 | 结果 |
| --- | --- |
| `pytest backend/tests -q` | 38 passed |
| 前端 `pnpm run build` | 通过 |
| `scripts/verify_api.py` | 全部 PASS |
| `scripts/check_frontend_privacy.mjs` | 9 条未认证路由全部 PASS |
| `verify_docker.sh` | 语法/YAML 静态检查通过；无 Docker daemon，未实际构建 |
| 跨批次并发测试 | 保留裁剪 + flush + 补发无死锁/无脏写 |
| 旧数据升级测试 | push 开关/v1 密文/旧 output 均通过 |

### 负面/并发测试新增

- `test_concurrent_retention_flush_and_supplement_no_deadlock`
- `test_concurrent_results_only_one_summary`
- `test_flush_failure_clears_body_and_keeps_summary`
- `test_corrupt_push_config_is_not_silently_overwritten`
- `test_ring_write_failure_marks_emergency_fallback`
- 驱动危险代码/Zip Slip/回滚/删除
- 全部 skip 不推送、超时兜底、skip 降噪

### 测试盲区（已登记）

- 驱动回滚导入失败、删除时配置仍引用（P3）；
- SQLite 真正锁超时的集成测试（当前用失败注入）；
- SSE 客户端中途断开/自动重连的浏览器自动化；
- 实际 Docker 容器构建与非 root 运行。

---

## 七、重构方案摘要

### P1-01 已落地

```text
push_drivers/builtin_specs.py   # 纯元数据
        ▲                ▲
        │                │
 services/push.py   push_drivers/registry.py
        │                │
        └── no reverse import ──┘
```

### P1-02 已落地

```python
try:
    previous = parameter_cipher.decrypt(row.config_encrypted, context)
except ParameterDecryptionError as exc:
    raise PushConfigError(
        "原推送配置无法解密，请先恢复 SECRET_KEY 或清空并重新填写配置"
    ) from exc
```

### P1-03 已落地

```python
# OutputCapture
seq = ring_log.append_execution(...)
if not seq:
    self.ring_failed = True

# _execute
fallback = redact_text(capture.getvalue()) if capture.ring_failed else ""
await _finalize(..., output=fallback)
```

### P2 重构计划

- `push_pool`：拆为 `_load_expected` / `_sync_skips` / `_probe_flush_state` / `_apply_result` / `_send_summary` / `_persist_flush`。
- SSE：拆为 `_replay_ring` / `_drain_live_queue` / `_finish_stream`。
- 执行器：拆为 `load_execution_inputs` / `run_accounts` / `aggregate_outcome`。
- Router：模块更新业务迁移到 `services/module_config.py`。

---

## 八、代码质量合格声明

> **《代码质量合格声明》**
>
> 本次封版审查未发现 P0 缺陷。已发现并修复 3 项 P1：驱动注册表循环导入、推送配置密文失败静默覆盖、环形日志失败导致执行正文丢失。剩余 P2/P3 问题已逐项登记到 `docs/TECH_DEBT.md`，均不构成当前封版的阻塞项。
>
> 后端 38 项测试、前端构建、API 验证、隐私检查均通过。Docker 实际构建因当前环境无 daemon 未执行，须在有 Docker 的机器完成 `bash verify_docker.sh` 后再切换生产流量。

**审查结论：允许进入封版候选，Docker 实机验证为最终发布门禁。**
