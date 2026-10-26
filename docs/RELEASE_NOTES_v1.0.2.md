# Release Notes — v1.0.2

> 统一推送主触发与超时兜底重构。

## 新增/变更

- 每日 01:00 计算所有已启用统一推送模块的最晚签到时间，+1 分钟作为主触发时间；
- 主触发通过 APScheduler DateTrigger 精确注册，同时保留每分钟 sweep 作为重启补偿；
- `PUSH_MAX_WAIT_MINUTES` 废弃，不再按固定最大等待时间自动汇总；
- `push_config` 新增 `unified_timeout_enabled`、`unified_timeout_time`；
- `push_batches` 新增 `trigger_at`、`timeout_at`、`timeout_attempted_at`、`timeout_count`；
- 兜底成功时批次状态 `timeout`，未完成模块标记 `push_pool.status=timeout`；
- 汇总标题/摘要增加「⚠️ 部分模块推送超时（兜底触发）」；
- 前端统一批次页新增超时开关与时间选择器；
- 主触发成功后兜底任务直接跳过，不重复推送。

## 配置/API

```http
GET /api/push/unified-settings
PUT /api/push/unified-settings
```

```json
{"timeout_enabled": true, "timeout_time": "23:30"}
```

## 测试

```text
pytest backend/tests -q     67 passed
node --test frontend/tests/*.test.mjs  2 passed
```

## 升级/回滚

- 迁移：`backend/app/migrations.py` 自动添加字段；
- 回滚：见 [MIGRATION_ROLLBACK_v1.0.2.md](MIGRATION_ROLLBACK_v1.0.2.md)；
- APScheduler 使用内存 JobStore，但计划持久化在 `push_batches.trigger_at`，重启自动补算；
- 推荐代码回滚，不删除新列。
