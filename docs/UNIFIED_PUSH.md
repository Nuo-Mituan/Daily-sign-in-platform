# 统一推送：主触发与超时兜底

> v1.1 行为变更。`PUSH_MAX_WAIT_MINUTES` 已废弃，统一推送不再按“最大等待时间”自动汇总。

## 1. 主触发（唯一正常路径）

每天 **01:00**：

1. 读取所有 `enabled=true` 且 `push_unified=true` 的模块；
2. 读取每个模块当天的实际随机签到时间 `ModuleSchedule.scheduled_at`；
3. 取最晚时间，**+1 分钟**，写入 `push_batches.trigger_at`；
4. 每分钟 sweep 检查 `now >= trigger_at`，立即汇总并发送。

若主触发发送成功：

- `push_batches.status = sent`；
- `push_pool` 明细立即清理；
- 当天后续任何超时任务都直接跳过。

主触发到达时仍未完成的模块标记为普通失败（不是 `timeout`）。

## 2. 超时兜底（仅异常补偿）

`push_config.unified_timeout_enabled` / `unified_timeout_time`：

- 默认关闭；
- 开启后，仅当主触发**未成功**（`pending` 或 `failed`）且到达配置时间才执行；
- 兜底触发时，未完成模块标记为 `push_pool.status = timeout`；
- `push_batches.status = timeout`，`timeout_count` 记录数量；
- 消息标题/摘要包含「⚠️ 部分模块推送超时（兜底触发）」；
- 主触发已 `sent` 时，兜底任务不会发送任何消息。

超时时间必须晚于当天计算出的主触发时间，否则不生成兜底计划。

## 3. API

```http
GET /api/push/unified-settings
PUT /api/push/unified-settings

{"timeout_enabled": true, "timeout_time": "23:30"}
```

统一配置仍通过：

```http
GET /api/push/config
PUT /api/push/config
```

## 4. 状态机

```text
pending
  ├─ 主触发成功 ──> sent          （终态，禁止兜底）
  ├─ 主触发失败 ──> failed
  │                   └─ 到达超时 ──> timeout（兜底成功，终态）
  │                                    failed（兜底发送失败，不再重试）
  └─ 全部 skip ──> noop
```

`timeout` 只在兜底执行时产生；主触发成功永不进入 `timeout`。

## 5. 调度注册

| 任务 | 时间 | 作用 |
| --- | --- | --- |
| `system:unified-batch-plan` | 每日 01:00 | 计算并持久化主触发时间 |
| `system:unified-batch-sweep` | 每分钟 | 主触发到达检查 + 超时兜底 |
| `system:unified-batch-init` | 每日 00:05 | 创建当天预期批次 |

应用启动时也会调用一次 `plan_unified_batch()`，兼容错过 01:00 的进程重启。

## 6. 回滚

见 [MIGRATION_ROLLBACK_v1.0.2.md](MIGRATION_ROLLBACK_v1.0.2.md)。
