# 备份、恢复与迁移指南

本文适用于使用仓库默认 `docker-compose.yml`（bind mount）的部署方式。
如果你修改过 `DATA_DIR_HOST`、`MODULES_DIR_HOST`、`LOGS_DIR_HOST`，请用实际宿主机路径替换下文中的
`data/`、`modules/`、`logs/`。

> 相关文档：[生产安全检查清单](PRODUCTION_SECURITY.md)、[部署说明](../README.md)

---

## 1. 需要备份什么

| 路径 / 文件 | 是否必需 | 内容 |
| --- | --- | --- |
| `data/checkin.db` | **必需** | 用户、管理员密码哈希、模块、账号参数、随机执行计划、推送配置、执行记录与启用状态。 |
| `data/.secret_key` | **必需**（自动密钥模式） | AES-256-GCM 参数加密与会话 Cookie 签名密钥。丢失后已保存的参数无法解密。 |
| `.env` | **强烈建议** | 管理员初始化配置、显式 `SECRET_KEY`、端口、时区、日志策略等。 |
| `modules/` | **必需** | 所有已安装模块的源码、`config.json`、辅助文件。 |
| `logs/` | 可选 | 执行日志的文件镜像；主要日志也保存在数据库中。 |
| `frontend/dist/` | 否 | 可重新构建，不需要备份。 |
| Docker 镜像 | 否 | 可通过源码重新构建；建议记录版本 / commit。 |

> `data/checkin.db-wal`、`checkin.db-shm` 如果存在，也应一起备份。停止服务后再复制可确保一致性。

**尤其注意**：`data/` 与 `.env` 中可能包含敏感信息（密钥、加密后的凭据）。备份文件必须
存放在受限制的位置，建议加密后异地保存。

---

## 2. 完整备份

推荐**先停止服务**，再做文件级备份，避免 SQLite 处于写入中间状态。

```bash
cd /path/to/daily-checkin-platform

# 确保备份目录存在，并限制权限
mkdir -p backups
umask 077

# 暂停容器（不会删除容器或数据）
docker compose stop

ARCHIVE="backups/checkin-$(date +%Y%m%d-%H%M%S).tar.gz"
FILES=(data modules logs)
[[ -f .env ]] && FILES+=(.env)
[[ -f data/.secret_key ]] && echo "包含自动生成的 .secret_key"

tar -czf "$ARCHIVE" "${FILES[@]}"

# 重新启动
docker compose start
```

> 如果 `logs/` 很大，可先从 `FILES` 数组中去掉它；执行记录仍保存在数据库中。
> 备份期间服务短暂停机，适合个人 / 内网部署。若不能停机，请使用 SQLite 在线备份 API，
> 不要在写入过程中直接复制 `.db` 文件。

### 2.1 校验备份

```bash
# 查看文件列表
tar -tzf "$ARCHIVE" | head -40

# 检查关键文件是否存在
tar -tzf "$ARCHIVE" | grep -E '(^|/)data/(checkin.db|\.secret_key)(|$)' \
  || echo "警告：备份中缺少数据库或 .secret_key"

# 计算校验和并保存
if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$ARCHIVE" | tee "$ARCHIVE.sha256"
else
  sha256sum "$ARCHIVE" | tee "$ARCHIVE.sha256"
fi
```

如果希望恢复后检查数据库完整性：

```bash
tar -xzf "$ARCHIVE" -C /tmp/checkin-restore-check data/checkin.db
python3 - <<'PY'
import sqlite3
connection = sqlite3.connect("/tmp/checkin-restore-check/data/checkin.db")
print(connection.execute("PRAGMA integrity_check").fetchone()[0])
connection.close()
PY
rm -rf /tmp/checkin-restore-check
```

### 2.2 加密并异地保存

```bash
# 使用 GPG 对称加密
gpg --symmetric --cipher-algo AES256 "$ARCHIVE"

# 或使用 age
age -p -o "$ARCHIVE.age" "$ARCHIVE"

# 复制到另一台机器 / 对象存储 / NAS
scp "$ARCHIVE.gpg" backup-host:/secure/checkin/
```

请把加密口令保存在密码管理器中，**不要和备份放在同一台机器上**。

### 2.3 备份频率建议

- 个人使用：每周一次 + 重大改动前；
- 参数 / 模块频繁变化：每天一次；
- 保留最近 7-30 份，并定期验证可恢复性；
- 升级、迁移、修改 `SECRET_KEY` 前必须备份。

---

## 3. 在新服务器上恢复 / 迁移

### 3.1 准备新服务器

```bash
# 安装 Docker Engine + Compose v2
git clone <你的仓库地址> /opt/daily-checkin-platform
# 或者拷贝与备份时相同版本的项目源码

cd /opt/daily-checkin-platform
mkdir -p data modules logs
```

如果旧服务器使用自动生成的 `data/.secret_key`，恢复时**必须保持它不变**。
如果旧服务器在 `.env` 中显式设置了 `SECRET_KEY`，新服务器也必须使用同一个值。

### 3.2 停止旧服务并做最终备份

```bash
# 旧服务器
docker compose stop
```

在旧服务停止后再执行第 2 节的备份，确保没有新的签到结果或配置写入。

### 3.3 恢复文件

```bash
# 新服务器，项目根目录
docker compose down || true

# 解压备份（备份包内包含 data/、modules/、可选 .env）
tar -xzf /path/to/checkin-YYYYMMDD-HHMMSS.tar.gz

# 如果备份里没有 .env，则从 .env.example 创建并填入相同的关键配置
# cp .env.example .env
# 编辑 .env：SECRET_KEY / TIMEZONE / 端口等务必与旧环境一致

# 权限收紧（宿主机用户可读写，其他用户不可读）
chmod 600 .env data/.secret_key 2>/dev/null || true
```

确认：

```bash
ls -l data/checkin.db data/.secret_key modules/
# 如果 data/.secret_key 不存在且旧环境使用显式 SECRET_KEY，
# 请确保 .env 中的 SECRET_KEY 与旧服务器一致。
```

### 3.4 启动并验证

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100 checkin-platform
```

打开网页端：

1. 使用**旧数据库中的管理员账号密码**登录
   （注意：如果在新的 `.env` 中修改了 `ADMIN_USER` / `ADMIN_PASS`，
   已经存在的数据库不会自动应用新密码）；
2. 检查「签到模块」列表是否完整；
3. 打开任一模块，确认单账号参数或多账号列表已恢复、时间窗与周期正确、
   「本次执行时间」正常；再进入「用户设置」确认全局推送配置仍然存在；
4. 手动执行一个低风险模块，确认日志与执行结果；
5. 配置反向代理 / DNS / 防火墙。

也可以运行隔离验证脚本检查 Docker 和 API：

```bash
./verify_docker.sh
```

> 该脚本使用临时数据，不会验证恢复后的旧数据库内容；它验证的是构建和 API 链路。

### 3.5 迁移禁用事项

- 不要同时在旧、新两台服务器运行同一个数据库的调度任务（除非只读测试）；
  否则会造成重复签到或重复日志。
- 不要在迁移时删除旧服务器，至少保留一个完整备份周期。
- 切换 DNS / 反向代理前，确认新服务器可以通过 HTTP 健康检查。
- 如果使用对象存储 / 外部数据库（自定义 `DATABASE_URL`），还要迁移对应数据库实体。

---

## 4. 升级版本

### 4.1 升级前

1. 阅读新版本的发布说明 / README；
2. 备份 `data/`、`modules/`、`.env`；
3. 记录当前版本号 / Git commit 和可用镜像 tag；
4. 在维护窗口内升级，避免签到高峰。

### 4.2 标准升级流程

```bash
cd /path/to/daily-checkin-platform

# 1. 备份
docker compose stop
mkdir -p backups
UPGRADE_ARCHIVE="backups/pre-upgrade-$(date +%Y%m%d-%H%M%S).tar.gz"
BACKUP_ITEMS=(data modules logs)
[[ -f .env ]] && BACKUP_ITEMS+=(.env)
tar -czf "$UPGRADE_ARCHIVE" "${BACKUP_ITEMS[@]}"
echo "已备份到 $UPGRADE_ARCHIVE"

# 2. 更新源码（保留 data、modules、.env）
git pull --ff-only
# 如果未使用 Git，用新版本源码覆盖 backend/、frontend/src/、Dockerfile 等代码文件，
# 但不要覆盖 data/、modules/、.env

# 3. 核对 .env / compose 是否有新增环境变量
# 如新版本增加变量，按新 .env.example 补充

# 4. 重新构建并启动
docker compose build
docker compose up -d
docker compose logs --tail=100 checkin-platform
```

### 4.3 哪些文件不能覆盖

| 路径 | 升级时处理方式 |
| --- | --- |
| `data/` | **绝不覆盖、绝不删除**。包含数据库和 `.secret_key`。 |
| `modules/` | **不要用新版目录整体覆盖**。保留自定义模块；示例模块如需更新，逐个手动合并。 |
| `.env` | **保留原文件**，仅按新版 `.env.example` 补充新增配置。 |
| `data/.secret_key` | **绝不替换**，否则参数无法解密。 |
| `logs/` | 可保留。新版本不会依赖旧文件日志。 |

可以安全替换 / 更新的内容：

- `backend/app/`
- `frontend/src/`、`frontend/dist/`（构建产物可重建）
- `Dockerfile`、`docker-compose.yml`（注意新变量与挂载路径）
- `docs/`、`README.md`、`scripts/`、`templates/`

更新后建议运行一次隔离验证：

```bash
./verify_docker.sh
```

### 4.4 数据库版本说明

当前版本使用 SQLAlchemy `create_all` 自动建表，并内置 **SQLite 前向迁移**
（`backend/app/migrations.py`）：

- 新增表通常会自动创建；
- 启动时会为旧 `modules` 表补充随机调度、周期子选项、多账号、推送开关等字段；
- 旧 `cron` / `default_cron` 会转换为默认时间窗，用户已有的新调度字段不会被覆盖；
- 旧 `half_month` / `quarterly` 会迁移为 `monthly` + 每月 1 日，并记录迁移日志；
- 新增 `module_schedules` 与 `push_config` 表由 `create_all` 创建；
- 迁移是幂等的，但删除字段、修改列类型等破坏性变更仍需手工处理；
- 跨大版本升级前必须备份，并阅读具体版本的迁移说明；
- 如果升级后出现数据库结构错误，最安全的做法是回滚到升级前的源码与备份。
- 非 SQLite 的 `DATABASE_URL` 不会执行该 SQLite 迁移，需要自行迁移表结构。

### 4.5 回滚

```bash
cd /path/to/daily-checkin-platform

docker compose down

# 恢复升级前备份（会覆盖 data/modules/.env）
tar -xzf backups/pre-upgrade-YYYYMMDD-HHMMSS.tar.gz

# 切回旧版本代码（Git 或旧源码目录）
git checkout <old-commit-or-tag>

docker compose build
docker compose up -d
```

如果新版本已经写入不兼容的数据结构，不能只回滚代码；
必须恢复升级前的数据库备份，否则旧代码可能无法读取新数据。

---

## 5. 只迁移模块到另一套实例

如果只想迁移模块而不迁移数据库：

```bash
# 旧服务器
tar -czf modules-backup.tar.gz modules/my_checkin modules/another_module

# 新服务器
tar -xzf modules-backup.tar.gz
```

然后在新系统的「签到模块」页点击「扫描目录」。
注意：**参数与账号不会随模块文件迁移**。单账号参数保存在
`modules.params_encrypted`，多账号数组保存在 `modules.accounts_encrypted`，
执行计划在 `module_schedules`，全局推送在 `push_config`。如需全部保留，请迁移整个
`data/`；只迁移模块文件时需要在网页端重新填写账号和调度配置。

---

## 6. 恢复后检查清单

- [ ] `data/checkin.db` 存在且 `PRAGMA integrity_check` 返回 `ok`
- [ ] `data/.secret_key` 存在；若使用显式 `SECRET_KEY`，值正确
- [ ] 能用原管理员账号登录
- [ ] 模块列表、单账号参数 / 多账号列表、时间窗与启用状态完整
- [ ] 至少手动执行一个模块成功
- [ ] 「本次执行时间」与重复周期已恢复
- [ ] 反向代理与 HTTPS 正常
- [ ] 执行记录可查询、实时日志正常
- [ ] 备份文件已加密并异地保存
- [ ] 旧服务器没有继续写入同一个数据库
- [ ] 了解停机期间错过的定时任务不会自动补跑
