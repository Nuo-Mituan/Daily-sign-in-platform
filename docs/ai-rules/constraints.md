# 技术栈、加密体系、环境红线与技术债

## 技术栈清单

### 后端
| 组件 | 版本 | 用途 |
|---|---|---|
| Python | 3.11 | 运行时 |
| FastAPI | 0.115.6 | Web 框架（异步） |
| SQLAlchemy | 2.0.36 | ORM（asyncio） |
| aiosqlite | 0.20.0 | SQLite 异步驱动 |
| APScheduler | 3.10.4 | 定时调度 |
| cryptography | 50.0.0 | AES-256-GCM (v2) |
| pydantic-settings | 2.7.1 | 环境变量配置 |
| python-multipart | 0.0.31 | 文件上传 |
| httpx | 0.28.1 | 异步 HTTP（推送） |
| itsdangerous | 2.2.0 | 会话签名 |
| Pillow | ≥10.4.0 | 图标处理 |
| redis | ≥4.5.0 | 可选预留 |

### 前端
Vue 3.5.44（^3.5.13） │ Element Plus 2.14.7（^2.9.1） │ Pinia 2.3.1（^2.3.0）
Vue Router 4.6.4（^4.5.0） │ Axios 1.20.0（^1.7.9） │ dayjs 1.11.23（^1.11.13） │ Vite 6.4.4（^6.0.7）

> 锁定版本取自 `frontend/pnpm-lock.yaml` / `package-lock.json`；括号内为 `package.json` 声明范围。

### 基础设施
Docker 多阶段构建（Node 22 → Python 3.11-slim）
GitHub Actions CI/CD │ Nginx/Caddy 反代

## 加密体系 v2

| 项目 | 规格 |
|---|---|
| 算法 | AES-256-GCM |
| 密钥派生 | HKDF-SHA256（salt=`daily-checkin-field-encryption`，info=`aes-256-gcm-v2`） |
| Nonce | 12 字节随机 |
| AAD | `v2 \| user_id \| module_key \| account_index` |
| 密文格式 | `v2:<urlsafe-base64(nonce \| ciphertext \| tag)>` |
| 账号加密 | 外层 `account_index=-1`；每个账号的 `params` 使用真实索引独立加密 |
| 向后兼容 | 旧 Fernet (v1) 透明升级，读取时自动迁移 |
| 持久化密钥 | `SECRET_KEY` 为空时生成 `data/.secret_key`（chmod 600）；环境变量优先 |
| 敏感标记 | `param_schema`（来自 `config.json` 的 `params`）`sensitive:true` + 自动推断 |
| API 掩码 | 短值 `****`；长值保留首尾 4 位；`reveal-sensitive` / `push/reveal` 二次密码后返回明文 |

## 绝对禁止红线

| 红线 | 原因 |
|---|---|
| localStorage 存认证信息 | 已移除，Cookie 是唯一认证载体 |
| 日志/SSE/traceback 输出明文敏感参数 | 泄露密钥=泄露所有模块凭据 |
| 绕过 CSRF 执行写操作 | 非 GET/HEAD/OPTIONS 自动校验（登录接口除外） |
| Service 层新增 FastAPI Request/Response 依赖 | 破坏分层；现存例外：`services/auth_sessions.py`（Response）、`services/module_upload.py`（UploadFile），重构时移除 |
| 正常路径直接修改 execution_logs.output | 已废弃，正常路径写入 ring_logs；仅 ring_log 写失败时允许紧急 fallback，旧值只读 |
| 删除 data/.secret_key | 所有加密参数永久不可解密 |

## 设计约束

| 约束 | 说明 |
|---|---|
| 单管理员 | 不支持多租户，扩展需重构 User |
| SQLite 单写者 | 高并发写入瓶颈，不适合 SaaS |
| 驱动同权限 | 自定义驱动非沙箱，仅可信管理员可上传 |
| 单机部署 | Docker 容器内，不支持分布式 |
| 前端 dist 内嵌 | 开发默认 `frontend/dist`；容器 `FRONTEND_DIR=/app/static`；dist 不入库 |

## 技术债清单

| 编号 | 描述 | 优先级 | 状态 |
|---|---|---|---|
| TD-1 | module_loader.py 55KB 巨型文件 | 高 | 待拆分 |
| TD-2 | execution_logs.output 废弃 | 中 | 已由 ring_log 接管，物理删列待 v2.0 |
| TD-3 | SQLite 单写者限制 | 低 | 设计定位即单机 |
| TD-4 | 自定义驱动非沙箱 | 中 | 已在 PUSH_DRIVERS.md / dev-sop.md 警告；仍非沙箱 |
| TD-5 | 前端 dist 构建产物管理 | 低 | 已解决：dist 已 gitignore，CI/Docker 构建 |

## 迭代历史

| 版本 | 关键变更 |
|---|---|
| v1.0.0-rc.1 | 初始架构 |
| v1.0.0-rc.2 | 环形日志迁移 |
| v1.0.1 | 稳定性修复 |
| v1.0.2 | 统一推送主触发与超时兜底重构 |
| v1.0.3 | 多账号串行、随机时间 |
| v1.0.4 | 隐私修复、周期精简为5种 |
| v1.0.5 | 安全基础 + 环形日志 + 推送驱动 + 双推送 + 模块图标 |
| v1.0.5 收尾 | PBT、状态机 Playbook v2.1、CI 性能门禁、连接池可观测性（已落地） |

## 版本演进方向
- PBT 驱动开发（Hypothesis + CI 双轨）
- 性能门禁（>20% 热路径回退阻断）
- 连接池可观测性（utilization/error rate/invalidation）
- 状态机契约化（Playbook v2.1）
- DB 日志限流优化（自适应衰减 + FIFO 淘汰）
