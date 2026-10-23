# v1.0.2 迁移回滚预案

## 新增字段

`push_config`：

- `unified_timeout_enabled BOOLEAN NOT NULL DEFAULT 0`
- `unified_timeout_time VARCHAR(5) NOT NULL DEFAULT '23:30'`

`push_batches`：

- `timeout_count INTEGER NOT NULL DEFAULT 0`
- `trigger_at DATETIME`
- `timeout_at DATETIME`
- `timeout_attempted_at DATETIME`

## 推荐回滚方式

**代码回滚优先，不删列。** v1.0.1 代码不读取这些新列，SQLite 允许保留额外列；因此：

```bash
git checkout v1.0.1
docker compose up -d --build
```

仅回滚代码即可，无需破坏性 schema 操作。

## 必须回滚 schema 时

先停止服务并备份数据库：

```bash
docker compose stop checkin-platform
cp data/checkin.db data/checkin.db.v1.0.2.bak
```

SQLite 3.35+ 支持 `DROP COLUMN`：

```sql
ALTER TABLE push_config DROP COLUMN unified_timeout_enabled;
ALTER TABLE push_config DROP COLUMN unified_timeout_time;

ALTER TABLE push_batches DROP COLUMN timeout_count;
ALTER TABLE push_batches DROP COLUMN trigger_at;
ALTER TABLE push_batches DROP COLUMN timeout_at;
ALTER TABLE push_batches DROP COLUMN timeout_attempted_at;
```

> 删除列会丢失 v1.0.2 的触发计划与超时统计。除必须恢复旧 schema 外，不建议执行。
> 更旧 SQLite 需使用“新建表 → 复制数据 → 重命名”方式，且必须先备份。

## APScheduler 说明

当前调度器使用进程内 JobStore，但**不依赖内存中的 DateTrigger 存活**：

- 每日计划时间持久化在 `push_batches.trigger_at`；
- 进程重启时 `main.py` 调用 `plan_unified_batch()` 重新计算；
- 每分钟 sweep 检查 `trigger_at` / `timeout_at`；
- 主触发成功写入 `sent`，重启后不会重复。

因此重启最多产生分钟级 sweep 延迟，不会丢失当日计划。若未来要求跨实例精确触发，需迁移到 SQLAlchemy/Redis JobStore，并把 JobStore 纳入备份与迁移流程。
