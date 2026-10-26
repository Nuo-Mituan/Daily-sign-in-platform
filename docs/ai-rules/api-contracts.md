# API 契约与前端路由

> 本文以 `backend/app/routers/`、`main.py` 与 `schemas.py` 的实际实现为准。
> 除特别标注外，`/api` 下的接口都需要 Cookie 会话；非 `GET/HEAD/OPTIONS` 还需 `X-CSRF-Token`。
> `POST /api/auth/login` 是唯一免 CSRF 的写接口。

## 认证体系
| 机制 | 实现 |
|---|---|
| 会话载体 | HttpOnly Cookie（checkin_session），SameSite=Strict |
| 会话存储 | 服务端 auth_sessions 白名单 + SHA256 哈希 |
| CSRF | 写方法需 X-CSRF-Token 头（登录接口除外） |
| 续期 | 每 session_renew_interval_seconds（默认300s）自动续期 |
| 强制改密 | password_must_change=true 时仅允许 /auth/session、/auth/me、/auth/logout、/auth/logout-all、/auth/change-password |

## 公开端点

| 方法 | 路径 | 认证 | 参数 | 响应模型 | 用途 |
|---|---|---|---|---|---|
| GET | /api/health | 否 | - | HealthOut | 健康检查 |
| GET | /api/modules/icon | 否 | Query: key, path | 二进制 Response | 模块本地图标 |
| GET | /metrics | 否 | - | text/plain | Prometheus 指标（根路径，不在 /api 下） |

> `GET /docs` 公开；`GET /api`（`include_in_schema=False`）返回名称、版本、文档与健康检查路径。

## 认证

| 方法 | 路径 | 认证 | 参数 | 响应模型 | 用途 |
|---|---|---|---|---|---|
| POST | /api/auth/login | 否 | Body: LoginRequest | LoginResponse | 登录并设置 Cookie |
| GET | /api/auth/session | 是 | - | SessionResponse | 校验并续期；未登录返回 401 |
| GET | /api/auth/me | 是 | - | UserOut | 当前登录用户 |
| POST | /api/auth/logout | 是 | - | MessageResponse | 登出当前会话 |
| POST | /api/auth/logout-all | 是 | - | MessageResponse | 注销全部会话 |
| PUT | /api/auth/username | 是 | Body: UsernameUpdateRequest | UserOut | 修改用户名 |
| POST | /api/auth/change-password | 是 | Body: ChangePasswordRequest | MessageResponse | 修改密码 |

## 模块

| 方法 | 路径 | 认证 | 参数 | 响应模型 | 用途 |
|---|---|---|---|---|---|
| GET | /api/modules | 是 | - | list[ModuleOut] | 模块列表 |
| POST | /api/modules/scan | 是 | - | ScanResponse | 扫描磁盘并热加载 |
| POST | /api/modules/upload | 是 | Multipart: file；Form: name；Query: overwrite | UploadResponse | 上传 ZIP |
| POST | /api/modules/schedule/preview | 是 | Body: SchedulePreviewRequest | SchedulePreviewResponse | 预览周期与下次日期 |
| POST | /api/modules/schedule-preview | 是 | Body: SchedulePreviewRequest | SchedulePreviewResponse | 隐藏别名（include_in_schema=False） |
| GET | /api/modules/{module_id} | 是 | Path: module_id (int) | ModuleDetail | 模块详情 |
| PUT | /api/modules/{module_id} | 是 | Body: ModuleUpdateRequest | ModuleDetail | 更新配置 |
| PATCH | /api/modules/{module_id}/enabled | 是 | Body: ToggleRequest | ModuleOut | 启用/禁用 |
| POST | /api/modules/{module_id}/reveal-sensitive | 是 | Body: RevealSensitiveRequest | RevealSensitiveResponse | 二次验证查看敏感参数 |
| POST | /api/modules/{module_id}/run | 是 | - | RunResponse | 手动执行 |
| POST | /api/modules/{module_id}/test | 是（开发者模式） | - | RunResponse | 测试执行；非开发者返回 403 |
| POST | /api/modules/{module_id}/schedule/regenerate | 是 | - | RegenerateScheduleResponse | 重新生成本期时间 |
| DELETE | /api/modules/{module_id} | 是 | Path: module_id (int 或 key)；Query: delete_files | MessageResponse | 删除模块 |

## 推送

| 方法 | 路径 | 认证 | 参数 | 响应模型 | 用途 |
|---|---|---|---|---|---|
| GET | /api/push/config | 是 | - | PushConfigOut | 获取推送配置 |
| PUT | /api/push/config | 是 | Body: PushConfigUpdate | PushConfigOut | 保存推送配置 |
| GET | /api/push/unified-settings | 是 | - | PushUnifiedSettingsOut | 统一推送设置 |
| PUT | /api/push/unified-settings | 是 | Body: PushUnifiedSettingsUpdate | PushUnifiedSettingsOut | 更新统一推送设置 |
| POST | /api/push/reveal | 是 | Body: RevealSensitiveRequest | PushRevealResponse | 二次验证查看推送密钥 |
| POST | /api/push/test | 是 | - | PushTestResponse | 测试推送 |
| GET | /api/push/records | 是 | Query: kind, status, page, page_size | PushRecordPage | 推送记录（分页） |
| GET | /api/push/batches | 是 | Query: status, page, page_size | PushBatchPage | 推送批次（分页） |
| GET | /api/push/drivers | 是 | - | list[dict] | 驱动列表 |
| POST | /api/push/drivers/upload | 是 | Multipart: file；Form: key, name, version | dict | 上传自定义驱动 |
| POST | /api/push/drivers/{key}/rollback | 是 | Path: key；Body: DriverRollbackRequest | dict | 回滚驱动 |
| DELETE | /api/push/drivers/{key} | 是 | Path: key | dict | 删除驱动 |

## 日志与系统

| 方法 | 路径 | 认证 | 参数 | 响应模型 | 用途 |
|---|---|---|---|---|---|
| GET | /api/logs | 是 | Query: module_id, status, trigger, page, page_size | LogPage | 执行日志列表 |
| DELETE | /api/logs | 是 | Query: module_id | MessageResponse | 清除已完成记录（运行中保留） |
| GET | /api/logs/{log_id} | 是 | Path: log_id (int) | LogDetail | 执行详情与输出 |
| GET | /api/logs/{log_id}/stream | 是 | Query: last_seq；Header: Last-Event-ID | SSE | 实时日志流 |
| GET | /api/dashboard | 是 | Query: recent_limit | DashboardOut | 仪表盘统计 |
| GET | /api/meta | 是 | - | MetaOut | 系统元信息 |
| GET | /api/settings/logs | 是 | - | LogSettingsOut | 日志设置 |
| PUT | /api/settings/logs | 是 | Body: LogSettingsUpdate | LogSettingsUpdateOut | 更新日志设置 |
| GET | /api/settings/developer | 是 | - | DeveloperModeOut | 开发者模式状态 |
| PUT | /api/settings/developer | 是 | Body: DeveloperModeUpdate | DeveloperModeOut | 切换开发者模式 |
| GET | /api/system/logs | 是 | Query: scope_type, level, page, page_size | SystemLogPage | 系统环形日志 |
| GET | /api/system/metrics | 是 | - | RuntimeMetricsOut | 运行时诊断指标 |

## SSE 实时日志协议

```http
GET /api/logs/{log_id}/stream?last_seq={seq}
Headers: Accept: text/event-stream, Last-Event-ID: {seq}
```

事件格式：

```text
id: 123
event: chunk
data: {"text":"...","seq":123}
```

心跳是 SSE 注释帧（不是 `ping` 事件）：

```text
: keep-alive

```

结束事件：

```text
event: done
data: {"status":"success|failed","message":"...","duration_ms":123,"last_seq":123}
```

- `chunk` 与 `done` 是实际事件名；不存在 `log` / `ping` 事件；
- `chunk.data` 只有 `text`、`seq`，没有 `level` / `ts`；
- 旧记录无环形日志时，`chunk` 的 `seq` 为 0；
- 断点续读可用 `last_seq` 查询参数或 `Last-Event-ID` 请求头。

## 前端路由与权限守卫

| 路径 | 视图 | 鉴权要求 | 敏感操作 |
|---|---|---|---|
| / | AppLayout | requiresAuth | 重定向 /dashboard |
| /login | LoginView | guestOnly | - |
| /change-password | ChangePasswordView | requiresAuth | 强制改密 |
| /dashboard | DashboardView | requiresAuth | 统计卡片 |
| /modules | ModulesView | requiresAuth | 卡片网格 |
| /modules/:id | ModuleDetailView | requiresAuth | 参数/账号/调度/推送 |
| /logs | LogsView | requiresAuth | RunLogDrawer |
| /push-center | PushCenterView | requiresAuth | **查看密钥需二次验证(Reveal)** |
| /system-logs | SystemLogsView | requiresAuth | **仅管理员可见** |
| /settings | SettingsView | requiresAuth | 账号/日志/安全 |
| /guide | GuideView | requiresAuth | 模块开发文档 |

路由守卫：父路由 `/` 统一声明 `requiresAuth`，子路由继承；`/login` 仅 `guestOnly`；
未认证→`/login`，强制改密→`/change-password`，未匹配路径→`/dashboard`。
