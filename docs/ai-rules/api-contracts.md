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
| POST | /api/modules/upload | 是 | Multipart: file；Form: name；Query: overwrite；无独立 icon 字段 | UploadResponse | 上传 ZIP |
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

### 模块图标契约

- `POST /api/modules/upload` 仅接收 ZIP，没有独立的 multipart `icon` 字段；图标是模块目录内的文件，
  由 `config.json` 的 `icon` 相对路径引用。
- `GET /api/modules/icon?key=<key>&path=icon.jpg` 公开读取模块物理目录内的图标；`key` 1–80 字符，`path` 默认 `icon.ico`、最长 255 字符。
- 允许扩展名：`.ico` / `.png` / `.jpg` / `.jpeg` / `.webp`；`.svg` 已停止支持。
- 路径型资源没有 Content-Type 输入；校验方式是“扩展名 + 文件魔数”一致性：
  PNG `89 50 4E 47`、JPEG `FF D8 FF`、WebP `RIFF....WEBP`、ICO `00 00 01 00`。
  扩展名与真实格式不一致、或魔数不识别的返回 415；`.svg` 返回 415 并提示改用 PNG。
- 后端再通过 Pillow 解码/尺寸校验；不宣称 MIME 白名单，因为该接口不接收 MIME 头。
- 单文件上限 64KB、解码像素上限 1024×1024；超限返回 413。
- PNG/JPEG/WebP/ICO 输出统一为 `image/png`；不存在 `image/svg+xml` 响应。
- 响应统一带 `X-Content-Type-Options: nosniff`、`ETag` 与
  `Cache-Control: public, max-age=86400, must-revalidate`，支持 `If-None-Match` 304。
- 该接口免鉴权（`<img>` 直接加载），仅暴露模块目录内图标；仍建议在网络层限制
  `/api/modules/icon` 的访问来源，避免图标资源被匿名批量枚举。

### 图标请求三态

| 条件 | 状态码 | body | code |
|---|---|---|---|
| key 语法非法（不满足首字符字母/数字等） | 403 | `{"detail":"模块标识不合法"}`，不含 directory_name/内部正则细节 | 无 |
| 合法 key 但模块或图标文件不存在 | 404 | `{"detail":"图标不存在"}` | 无 |
| 后缀不支持（含 `.svg`） | 415 | `.svg` 返回 `SVG 图标已停止支持，请改用 PNG 格式` | 无 |
| 默认格式/大小错误 | 415/413 | 原 detail | `icon_format_default` / `icon_size_default` |

### 图标错误 code 契约

图标错误响应保持原有 `detail` 与 HTTP 状态码，并新增**可选** `code` 字段：

```json
{"detail": "图标格式不合法", "code": "icon_format_default"}
```

| code | 状态码 | 出现条件 | 前端行为 |
|---|---|---|---|
| `icon_format_default` | 415 | 默认格式错误（后缀/魔数不匹配、解码失败） | 回退固定 PNG/JPG/ICO/WebP 文案。`.svg` 是后缀不支持的特例：返回 415 但**不携带 code**，走具体迁移 detail「SVG 图标已停止支持，请改用 PNG 格式」。 |
| `icon_size_default` | 413 | 文件超限、像素超限、DecompressionBomb | 回退固定“文件过大”文案 |
| 无 `code` | 415 | 例如 SVG 已停止支持的具体迁移提示 | 直接展示后端 `detail` |

- 该字段为向后兼容的新增字段；`code` 为 None 时不输出 `null`，旧响应形态不变。
- 路径型资源没有 Content-Type 输入；这里不涉及 MIME 校验。

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
