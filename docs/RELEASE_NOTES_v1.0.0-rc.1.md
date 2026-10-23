# Release Notes — v1.0.0-rc.1

> **状态：Release Candidate（封版候选）**
>
> `v1.0.0-rc.1` 为第六轮迭代候选版本，**不是最终生产正式版**。
>
> ### Docker 实机验证门禁
>
> **`v1.0.0-rc.1` 为候选版本，生产部署前必须在目标架构机器上执行 `bash verify_docker.sh`
> 并通过全部检查项，方可将 Tag 晋升为 `v1.0.0` 正式版。**
>
> Docker 实机验证列为运维侧待办，不阻塞代码封版，但**阻塞生产流量切换**。

---

## 代码质量合格声明（摘要）

> 本次封版审查未发现 P0 缺陷。已发现并修复 3 项 P1：
>
> 1. 驱动注册表循环导入；
> 2. 推送配置密文失败静默覆盖；
> 3. 环形日志失败导致执行正文丢失。
>
> 剩余 P2/P3 问题已登记到 `docs/TECH_DEBT.md`，均不构成封版阻塞项。
>
> 后端 38 项测试、前端构建、API 验证、隐私检查均通过。
> Docker 实际构建因审查环境无 daemon 未执行，须在有 Docker 的机器完成
> `bash verify_docker.sh` 后再切换生产流量。
>
> 审查报告：`docs/CODE_QUALITY_AUDIT.md`。

---

## 发布信息

- Tag：`v1.0.0-rc.1`
- 基线：Iteration 6（安全基础 + 环形日志 + 推送重构）
- 日期：2026-10-19
- 回归：`pytest backend/tests -q` → **38 passed**
- 前端：`pnpm run build` 通过
- API：`scripts/verify_api.py` 全部 PASS
- 隐私：`scripts/check_frontend_privacy.mjs` 全部 PASS

### 附件

| 文件 | 用途 |
| --- | --- |
| `.env.example` | 环境变量模板与默认值 |
| `verify_docker.sh` | Docker 实机门禁脚本 |
| `check_frontend_privacy.mjs` | 未认证页面隐私检查 |
| `v1.0.0-rc.1-attachments.zip` | 上述三个附件的打包文件 |

附件与 `SHA256SUMS.txt` 同时存放于 `release/v1.0.0-rc.1/`。

```text
20194e52975434c07887856d2f3cbc81af0375ce5d818717b63edccb4fd80d36  .env.example
9435bc20a273b2ba9350b1c4fa1d5e0f5991d3edd50ee558a3ba971bbc26fa2e  verify_docker.sh
c1af5f64359d81fea89e1cb2b4bfc2328f9c6820b4e124aedffe505b7fd27794  check_frontend_privacy.mjs
5fd6a05d6cbe046a7a82783b02c2c0f059d48e070dec4c699bef455c78679d3d  v1.0.0-rc.1-attachments.zip
```

---

## 封版后变更管制

1. 主分支仅接受 **P0 级安全 / 数据完整性热修复**。
2. 功能性变更、重构、文档更新必须新开分支，经完整回归测试后合入。
3. 热修复必须附带专项测试，并在 Release Notes 标注 **“Post-RC Fix”**。
4. 在 Docker 实机门禁通过前，禁止切换生产流量或将 Tag 晋升为 `v1.0.0`。

---

## 完整变更正文

以下是 `docs/ITERATION6_CHANGES.md` 全文。

# Iteration 6 变更说明

本文件合并 Iteration 6 第一批（安全基础）与第二批（环形日志 + 推送重构）的实际落地内容。

---

## 1. 安全基础

- AES-256-GCM v2，HKDF-SHA256 派生密钥，nonce 12 字节；
- AAD：`user_id | module_key | account_index`；
- 旧 Fernet v1 透明兼容，读取/执行/推送配置读取时自动升级 v2；
- 敏感字段 `sensitive: true` 与自动推断；
- API 掩码；二次密码验证后显示明文；
- 保存掩码/空值保留原密文；
- 日志、SSE、traceback、数据库、旧文件统一脱敏；
- Cookie 会话替代 JWT：HttpOnly、SameSite=Strict、可选 Secure、服务端白名单；
- CSRF Header 校验，默认开启；
- 前端只保留 Pinia 内存态，不再写 localStorage；
- PUID/PGID 非 root Docker 入口；
- data/logs=700，SQLite=600，`.secret_key`=600。

## 2. 统一环形日志

- SQLite `ring_logs` + `ring_state.next_seq`；
- 写入与淘汰同事务，进程锁串行；
- 单调 `seq`，重启不丢序；
- 双约束：保留天数 + 条数/字节；
- 系统 / 每模块 / 推送独立配额；
- 每批 1000 条裁剪；
- 启动、每日 03:10、Web 设置修改后立即裁剪；
- 执行正文从 `execution_logs.output` 迁移到环形表；旧值保留只读回退；
- SSE 支持 `last_seq` / `Last-Event-ID` 断点续读；
- 旧文件日志写入器删除，仅清理旧文件；
- 日志设置 API：`GET/PUT /api/settings/logs`，1–365 天校验。

## 3. 推送驱动

- 内置 Bark / Server 酱 / PushPlus / 钉钉 / 飞书；
- 自定义驱动目录 `backend/app/push_drivers/custom/`；
- 上传 `.py` / `.zip`，manifest + driver.py；
- ZIP Slip、符号链接、额外文件、大小校验；
- AST 拦截 os/subprocess/eval/exec/open/importlib 等危险调用；
- 上传校验不是安全沙箱，仅可信管理员；
- 热加载、失败回滚、最多 5 个版本；
- 驱动管理 API 与「推送中心 → 驱动管理」UI；
- 推送审计写入环形日志 `scope_type=push`。

## 4. 独立/统一推送

- 模块双开关：`push_independent`、`push_unified`；
- 两者同时开启时统一推送优先；
- 独立推送即时发送并写 `push_records`；
- 统一推送：
  - 期望集合 = 当日所有启用且开启统一推送的模块；
  - 批次初始化时预生成 skip：`当日不在执行周期`；年度 2-29 非闰年：`本年无执行日`；
  - 全部终态或超过 `PUSH_MAX_WAIT_MINUTES` 后汇总；
  - 全部 skip 且无手动执行：完全不推送；
  - `PUSH_SKIP_NOTICE=false`：不展示 skip 明细，但计数保留；
  - 手动补执行更新 skipped 行为真实结果，标注「手动补执行」；
  - flush 后手动执行按 `PUSH_AFTER_FLUSH_MODE=single` 补发单条；
  - 汇总成功后立即删除 `push_pool` 明细，仅保留 `push_batches` 摘要；
  - 失败重试耗尽后标记 failed、保留摘要、清理正文；
  - 批次锁 + 幂等状态，避免重复汇总/脏写；
- 推送记录 API：`/api/push/records`、`/api/push/batches`；
- 「推送中心」页面支持记录筛选、批次摘要、驱动管理。

## 5. 配置

```text
LOG_RETENTION_DAYS=31
PUSH_SKIP_NOTICE=true
PUSH_AFTER_FLUSH_MODE=single
PUSH_MAX_WAIT_MINUTES=60
PUSH_RETRY_ATTEMPTS=3
PUSH_RETRY_BASE_SECONDS=1.0
PUSH_DRIVER_MAX_VERSIONS=5
PUID=10001
PGID=10001
COOKIE_SECURE=false
CSRF_ENABLED=true
```

完整的环形容量变量见 `.env.example`。

## 6. 验收

- `pytest backend/tests -q`：全部通过；
- 前端 `pnpm run build`：通过；
- `scripts/check_frontend_privacy.mjs`：未认证路由全部 PASS；
- `scripts/verify_api.py`：Cookie/CSRF、模块、调度、多账号、推送、环形日志、驱动、批次摘要；
- `verify_docker.sh`：非 root UID、data/logs 700、DB 600、API 验证；
- Docker 实际构建需在具备 daemon 的机器执行。

## 7. 已知边界

- 自定义驱动与主进程同权限，不是沙箱；
- HTTP 内网部署存在抓包风险，HTTPS 可选但推荐；
- SQLite 单写者，适合单机小规模；
- 旧 `execution_logs.output` 仅用于升级前记录回退，新执行不再写入。

---

## 8. 新增/变更环境变量与默认值

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LOG_RETENTION_DAYS` | `31` | 统一环形日志保留天数，1–365；Web 可覆盖 |
| `RING_LOG_MAX_ROWS` | `200000` | 全局环形日志最大条数 |
| `RING_LOG_MAX_BYTES` | `134217728` | 全局环形日志最大字节数（128 MiB） |
| `RING_SYSTEM_MAX_ROWS` | `50000` | 系统日志最大条数 |
| `RING_SYSTEM_MAX_BYTES` | `33554432` | 系统日志最大字节数（32 MiB） |
| `RING_MODULE_MAX_ROWS` | `20000` | 每模块日志独立最大条数 |
| `RING_MODULE_MAX_BYTES` | `16777216` | 每模块日志独立最大字节数（16 MiB） |
| `RING_PUSH_MAX_ROWS` | `50000` | 推送审计日志最大条数 |
| `RING_PUSH_MAX_BYTES` | `33554432` | 推送审计日志最大字节数（32 MiB） |
| `RING_TRIM_BATCH_SIZE` | `1000` | 裁剪批大小 |
| `PUSH_SKIP_NOTICE` | `true` | 统一摘要是否展示 skip 明细（计数始终保留） |
| `PUSH_AFTER_FLUSH_MODE` | `single` | flush 后手动执行的补发模式：`single` / `none` |
| `PUSH_MAX_WAIT_MINUTES` | `60` | 批次超时兜底等待时间 |
| `PUSH_RETRY_ATTEMPTS` | `3` | 统一汇总最大尝试次数 |
| `PUSH_RETRY_BASE_SECONDS` | `1.0` | 指数退避基数 |
| `PUSH_DRIVER_MAX_VERSIONS` | `5` | 自定义驱动保留版本数 |
| `COOKIE_SECURE` | `false` | HTTPS 环境必须改为 `true` |
| `CSRF_ENABLED` | `true` | 写方法 CSRF Header 校验开关 |
| `PUID` / `PGID` | `10001` | 容器降权后的运行 UID/GID |

---

## 9. 升级部署警告

> **本版本涉及非 root 入口脚本与卷权限调整。首次升级部署前务必备份 `data/` 目录，并在有 Docker 的环境中执行 `bash verify_docker.sh` 验证通过后再切换生产流量。**
