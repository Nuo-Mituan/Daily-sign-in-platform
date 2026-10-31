# 架构分层与数据模型

## 架构分层图

```
┌─────────────────────────────────────────────────────────┐
│                    浏览器 (Vue 3 SPA)                     │
│  Dashboard │ Modules │ Logs │ PushCenter │ SystemLogs    │
│  Settings │ Guide │ Pinia Stores + Axios (http.js+csrf)  │
└──────────────────────┬──────────────────────────────────┘
                       │ Cookie + CSRF Token
                       ▼
┌─────────────────────────────────────────────────────────┐
│              FastAPI 应用层 (backend/app/main.py)         │
│  CORS（可选）→ 路由级 get_current_user / get_auth_context │
│  → CSRF Check（非 GET/HEAD/OPTIONS）                     │
│                                                          │
│  Router: auth│modules│logs│dashboard│push│system│metrics│
│       ↓                                                    │
│  Service Layer: execution│scheduler│push*│ring_log│      │
│               bootstrap│hub(SSE)│capture│maintenance     │
│       ↓                                                    │
│  Data Layer: SQLAlchemy 2.0 ORM → aiosqlite → SQLite    │
│            Ring Buffer (ring_logs + ring_state)           │
│                                                          │
│  Cross-cutting: config│crypto│deps│security│timeutils│  │
│               contracts│module_loader                    │
└─────────────────────────────────────────────────────────┘
```

## 层级职责与边界

| 层级 | 目录/文件 | 职责 | 禁止越界 |
|---|---|---|---|
| Router | routers/*.py | HTTP 解析、参数校验、简单 DB 查询、调用 Service | 复杂业务编排应下沉 Service；当前 Router 仍直接使用 AsyncSession |
| Service | services/*.py | 业务编排、事务管理、跨模块协调 | 不新增 FastAPI Request/Response 依赖；现存例外：auth_sessions.py（Response）、module_upload.py（UploadFile） |
| Data | models.py, database.py | ORM 定义、连接/初始化 | 不包含业务逻辑 |
| Cross-cutting | config/crypto/deps/security | 配置、加密、依赖注入 | deps 当前依赖 services.auth_sessions |
| Module Loader | module_loader.py | 磁盘扫描、config.json 解析、DB 同步 | 55KB 巨型文件，修改需谨慎 |

> 当前实现不是完全理想分层：Router 仍有大量直接 `AsyncSession` 操作，`services/auth_sessions.py` 与 `services/module_upload.py` 仍引用 FastAPI 类型，`deps.py` 依赖 `services.auth_sessions`。规则用于约束**新增**代码，存量例外在后续重构中清理。

### v1.0.6 补充核心文件
| 文件 | 职责 |
|---|---|
| services/legacy_wash.py | 清洗旧版管理员凭据与废弃字段 |
| services/lock_registry.py | 进程内并发锁注册表（防竞态） |
| contracts.py | 跨模块契约定义（PBT 依赖） |

## 推送子系统独立架构

```
push_drivers/
├── base.py            # 驱动协议 PushDriver 与 DriverRecord
├── builtin_specs.py   # 内置驱动规格
├── registry.py        # 驱动注册表（热加载、版本管理、回滚）
├── validation.py      # 上传校验（ZIP Slip、AST 危险调用拦截）
└── custom/            # 用户自定义驱动目录

services/push*.py
├── push.py / push_delivery.py / push_pool.py / push_state.py
├── push_outbox.py / push_plan.py / push_lock.py
└── push_summary.py / push_time.py
```

## 数据库模型关系

```
users (单管理员) ──(N) auth_sessions

modules（全局表，无 user_id）──(N) execution_logs
  ├──(N) module_schedules
  └──(N) push_pool ──(cycle_id 逻辑关联，无 FK)── push_batches
                                                      └──(N) push_records（batch_id FK）

push_config（单例） │ ring_logs │ ring_state（单例） │ app_settings（KV） │ push_outbox
```

> `modules` 没有 `user_id`；单管理员模式下 `owner_user_id()` 取第一个用户作为字段加密 AAD 的 owner。

### 核心表要点
| 表 | 关键字段 | 设计意图 |
|---|---|---|
| users | password_must_change, developer_mode_enabled | 强制改密、开发者模式 |
| auth_sessions | session_hash, expires_at, revoked_at | 服务端白名单会话 |
| modules | key, params_encrypted, accounts_encrypted, push_independent/unified | 加密参数、双推送开关 |
| module_schedules | period_start, scheduled_at, status | 每周期一条随机执行时间 |
| ring_logs | seq(单调递增), scope_type, scope_key, ref_type, ref_id | 统一环形日志，断点续读 |
| push_pool | cycle_id, module_id, status | 统一推送等待池；按 cycle_id 逻辑关联批次 |
| push_batches | cycle_id, idempotency_key, status | 批次幂等控制 |
| push_records | batch_id, idempotency_key, status | 推送发送记录；batch_id → push_batches |
| push_outbox | idempotency_key, status, attempts | 事务性审计 outbox |

## 完整启动流程

```
Docker 容器启动
├─ docker-entrypoint.py: chown/chmod/umask/setgroups/setgid/setuid → exec uvicorn
├─ FastAPI lifespan (main.py):
│   install_redaction（模块导入时已调用，lifespan 再幂等调用）
│   → hub.bind_loop
│   → init_db（create_all + migrate_schema + ring_log.initialize）
│   → patch_schema（仅 users.password_must_change 历史补丁）
│   → ring_log.initialize → install_stdout_router
│   → wash_legacy_admin_credentials → seed_admin
│   → mark_stale_running_logs → mark_stale_running_schedules
│   → scheduler_service.start
│   → initialize_modules → ensure_batch → scheduler_service.plan_unified_batch
│   → drain_push_outbox → purge_old_logs → load_all_modules
│   → scheduler_service.reconcile → yield
└─ 请求就绪: /api/health → 200
```

## 调度系统核心逻辑

### 五种合法周期
| 内部值 | 显示 | 子选项 |
|---|---|---|
| daily | 每日 | 无 |
| weekly | 每周 | 星期几（1-7） |
| monthly_15 | 每月15日 | 无 |
| monthly | 每月 | 日期（1-28） |
| yearly | 每年 | 月-日（M-D） |

### 状态机
```
执行记录：running → success / failed（无 pending）
调度记录：pending / fallback → running → executed；另有 missed / cancelled
推送池明细：pending → success / failed / skipped / timeout
统一推送批次：pending → sent / failed / timeout / noop / expired
              failed 可转 timeout / expired / noop；noop 可重开为 pending
```

## 统一推送批次流程

```
每日 00:05 → ensure_batch() 创建 cycle_id
→ 每日 01:00 → plan_unified_batch() 取当天最晚 scheduled_at + 1 分钟
→ 写 push_batches.trigger_at，并注册 system:unified-main:<cycle> 的 DateTrigger
→ 每分钟 sweep：flush_due_batches() 检查主触发 / 超时兜底（DateTrigger 丢失时补偿）
→ 主触发失败且开启 timeout → 超时兜底；主触发 sent 后禁止兜底
→ flush 后手动执行 → PUSH_AFTER_FLUSH_MODE=single 补发
→ 应用启动时也会调用一次 plan_unified_batch()
```
