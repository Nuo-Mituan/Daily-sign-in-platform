# v1.0.0 Pre-Release 代码健康度审查报告

- 审查对象：`backend/app` 全部非测试业务代码，重点覆盖 Batch 1~4 重构核心链路
- 审查日期：2026-10-20
- 工具：`ruff`（F/E9）、`mypy`（核心契约/锁/outbox）、自研 import 架构守卫、AST 复杂度扫描、人工走查
- 测试：`pytest` **61 passed**
- 当前版本：`v1.0.0-rc.2`（未创建 v1.0.0）

---

## 一、审查范围

重点文件：

- `ring_log.py`
- `push_pool.py`
- `push.py`
- `push_outbox.py`
- `module_update.py`
- `execution.py`
- `routers/logs.py`、`routers/push.py`、`routers/modules.py`
- `push_drivers/`、`contracts.py`、`lock_registry.py`

架构检查：

- Router → Service → Model 单向依赖；
- services 不导入 routers；
- models 不导入 services/routers；
- `push_drivers.registry` 不反向依赖 `services.push`；
- 全局单例/锁/线程生命周期；
- 多表事务边界。

---

## 二、问题清单

### Critical（已修复）

#### C-01 环形日志写线程关闭时 sentinel 可能被吞，线程无法退出

- 文件：`backend/app/services/ring_log.py`
- 问题：批量取队列时若在 `get_nowait()` 中读到 `None` sentinel，只 `task_done` 后继续处理 batch；处理完不返回，写线程继续阻塞在空队列。`close()` 的 join 超时，旧线程泄漏。
- 复现：先 append 少量数据，再 `ring_log.close()`；断言 `_writer is None` 失败或 join 等 10 秒。
- 修复：`stop_after` 标记；处理完当前 batch 后立即 return；关闭时重置队列和 `_writer_failed`。
- 回归：`test_td06_graceful_close_flushes_queue` 断言 close 后 `_writer is None`。

#### C-02 Outbox drain 将环形日志失败误判为成功

- 文件：`backend/app/services/push_outbox.py`
- 问题：`ring_log.append_push()` 失败时返回 0；drain 未检查返回值，仍把 outbox 标记 `processed`，审计丢失。
- 复现：monkeypatch `append_push` 返回 0，调用 drain，outbox 变 processed。
- 修复：`seq == 0` 视为失败，保留 pending、attempts+1、记录错误。
- 回归：`test_td08_outbox_stays_pending_when_ring_write_fails`。

#### C-03 独立推送/补发记录幂等键可能碰撞

- 文件：`backend/app/services/push.py`、`push_pool.py`
- 问题：独立审计键只含 module/date/title；同一模块同标题多次执行会触发 `PushRecord.idempotency_key` 唯一约束，记录写入失败。
- 修复：独立审计键加入 `time_ns()`；补发键加入 `time_ns()`；批次幂等键保持稳定。
- 回归：并发 flush/补发测试；61 项全量。

### Major（已修复）

#### M-01 `ring_write_retries` 默认值被错误 clamp

- 文件：`backend/app/config.py`
- 问题：`ring_write_retries=6` 被通用 `max(10, ...)` 提升为 10，默认值不生效。
- 修复：单独 clamp 到 1–20；其他队列/裁剪参数保留下限。
- 回归：`test_td14_ring_constants_are_bounded`。

#### M-02 环形 100k 压测受单条提交限制

- 文件：`backend/app/services/ring_log.py`
- 问题：writer 每行一个事务，100k 压测无法在合理时间完成。
- 修复：writer 批量取最多 256 条，同一事务插入、更新 seq、裁剪；保持顺序与背压。
- 结果：100k 总耗时 4912ms，约 20,358 rows/s。

#### M-03 `module_update` 服务反向依赖 API Schema

- 文件：`backend/app/services/module_update.py`
- 问题：Service 导入 `ModuleUpdateRequest`，形成 Service→API 契约耦合。
- 修复：定义 `ModuleUpdatePayload` Protocol，Service 只依赖结构协议。
- 回归：API 更新、账号合并、周期冲突测试全部通过。

#### M-04 死代码/未使用常量

- 文件：`routers/logs.py`、`push_pool.py`
- 问题：`_SSE_KEEPALIVE_SECONDS`、`TERMINAL` 在配置化/重构后未使用。
- 修复：删除。
- 回归：`ruff F/E9` 通过。

### Minor（已确认/接受）

- Routers 内仍有 63 处 `Any`（模块配置辅助函数、Pydantic payload）；核心 Service/驱动为 0。
- `system_logs` 默认只读筛选；大表查询使用 LIMIT/OFFSET。
- `ring_log` 队列满采用阻塞背压，极端突发下会阻塞生产者。
- `execution_logs.output` 已标记 Deprecated，rc.2 不删列。
- `notify_module` 为旧兼容入口，保留至 v2.0 清理评估。
- `push_outbox.drain` 与环形写入仍非同一 DB 事务（审计 outbox 为补充机制）。

---

## 三、架构与事务结论

- Router → Service → Model 单向依赖成立；
- services 不导入 routers；models 不导入 services/routers；
- registry 不反向导入 `services.push`（`builtin_specs.py` 拆分）；
- `PushRecord` + `PushBatch` + `PushPool` 清理 + outbox 写入在同一本地事务提交；
- 外部 HTTP 与 DB 无法原子化，语义为 at-least-once；
- 环形写线程单写、批量事务、队列有界；
- SSE Hub 退订在 `finally`；锁均有释放路径；
- 配置项均有默认值与 prepare 边界校验；
- 无 `os.getenv()` 无兜底调用。

---

## 四、验证结果

```text
pytest backend/tests -q        61 passed
ruff check F,E9                All checks passed
mypy contracts/lock/outbox     Success
import architecture guard      OK
```

性能（`docs/perf/rc2-after.json`）：

- 50 并发生产者 / 5000 行：p95 0.0076ms，0 错误；
- 100,000 行：4912.05ms，20,358 rows/s；
- 50 模块 flush：679.92ms，池清理 0；
- 20 SSE：首包 5.49ms，丢弃 0。

网络/SSE 脚本：

```text
scripts/benchmark_rc2_network.py
本地烟测：API p95 374.57ms；loop max 33.686ms；
SSE first 53.3ms；catchup 53.83ms；drops 0
```

> 实机门禁数据需在目标 Linux 宿主机按 `docs/DOCKER_GATE_SOP.md` 重采。

---

## 五、最终结论

未发现未修复的 Critical/Major 问题；残留 Minor 均为已登记/已接受的兼容或性能权衡。

**代码健康度终审通过。**

> 该结论不等于生产发布完成：Docker 实机门禁与网络压测仍需在目标宿主执行；`v1.0.0` Tag 尚未创建。
