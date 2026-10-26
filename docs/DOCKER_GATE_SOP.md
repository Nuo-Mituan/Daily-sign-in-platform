# Docker 实机门禁执行 SOP（v1.0.5）

> 目标：在目标 Linux 宿主机上完成镜像构建、非 root 运行、容器内全量测试、API 验证与网络/SSE 压测，全部通过后方可创建或晋级 `v1.0.5`。

## 1. 环境要求

- Docker Engine **24+**
- Docker Compose **v2.20+**（`docker compose` 插件）
- Linux x86_64 或 arm64
- 建议 2 vCPU / 4 GB RAM / 5 GB 可用磁盘
- 已安装 `curl`、`bash`、`sha256sum`
- 目标端口仅绑定 `127.0.0.1` 或可信局域网 IP
- 首次升级前必须备份 `data/` 目录与 `data/.secret_key`

```bash
docker --version
docker compose version
```

## 2. 获取发布候选

```bash
git fetch --tags
git checkout v1.0.5
cp .env.example .env
```

编辑 `.env`：

```text
ADMIN_USER=...
ADMIN_PASS=...
SECRET_KEY=...          # 或保留自动生成并备份 data/.secret_key
APP_BIND=127.0.0.1      # 或可信局域网 IP
APP_PORT=5000
PUID=10001
PGID=10001
COOKIE_SECURE=false     # 仅 HTTP 内网
CSRF_ENABLED=true
```

```bash
chmod 600 .env
mkdir -p data logs
cp -a data data.backup.$(date +%Y%m%d%H%M%S)
```

> **警告：**本版本涉及非 root 入口脚本与卷权限调整。首次升级前必须备份 `data/`。

## 3. 构建镜像

```bash
docker compose build --no-cache
```

确认镜像包含：

- `backend/tests`；
- `requirements-dev.txt` / pytest；
- `templates`、`modules`；
- `/app/data`、`/app/logs`。

## 4. 容器内全量技术债回归

```bash
docker compose up -d
docker compose exec -T \
  -e DATA_DIR=/tmp/rc2-tests/data \
  -e LOGS_DIR=/tmp/rc2-tests/logs \
  -e SECRET_KEY=rc2-container-test \
  -e ADMIN_USER=admin \
  -e ADMIN_PASS=admin123 \
  checkin-platform env PYTHONPATH=/app pytest backend/tests -q
```

判定：

- Exit Code **0**；
- 默认回归输出 **221 passed**（当前矩阵）；PBT 与 benchmark 单独执行并通过。

## 5. 非 root 与权限检查

```bash
docker compose exec -T checkin-platform \
  awk '/^Uid:/{print $2}' /proc/1/status
docker compose exec -T checkin-platform stat -c '%a %n' /app/data /app/logs /app/data/checkin.db
```

判定：

- 主进程 UID = `.env` 中 `PUID`，且 **非 0**；
- `/app/data`、`/app/logs` = `700`；
- `checkin.db` = `600`。

## 6. 执行完整或临时门禁

```bash
bash verify_docker.sh
```

该脚本会：

- 构建临时镜像；
- 启动独立临时项目；
- 健康检查；
- 非 root / 权限检查；
- 容器内 pytest；
- 执行 `verify_api.py`；
- 清理临时环境。

判定：**Exit Code 0**。

## 7. 网络与 SSE 重连压测

在宿主机 Python 3.11+ 环境执行（推荐独立 venv）：

```bash
python3 -m venv .venv-gate
source .venv-gate/bin/activate
pip install -r backend/requirements-dev.txt

set -a
source .env
set +a
python scripts/benchmark_rc2_network.py \
  --base-url "http://127.0.0.1:5000/api" \
  --user "$ADMIN_USER" \
  --password "$ADMIN_PASS" \
  --output docs/perf/rc2-after.json
```

或容器内执行：

```bash
docker compose cp scripts/benchmark_rc2_network.py \
  checkin-platform:/tmp/benchmark_rc2_network.py
docker compose exec -T checkin-platform python /tmp/benchmark_rc2_network.py \
  --base-url http://127.0.0.1:5000/api \
  --user "$ADMIN_USER" --password "$ADMIN_PASS" \
  --output /tmp/rc2-after.json
docker compose cp checkin-platform:/tmp/rc2-after.json ./rc2-after.json
```

脚本会自动：

- 登录并选择一个执行日志（必要时触发一次执行）；
- 发起 50 并发 `/modules` 请求；
- 用后台任务测量事件循环阻塞；
- 建立 20 个 SSE 连接，断开后以 `Last-Event-ID` 重连；
- 读取 `/system/metrics` 的 `dropped_chunks`；
- 将 `network` 对象合并进 `docs/perf/rc2-after.json`。

判定阈值：

| 指标 | 门槛 |
| --- | --- |
| API p95 | ≤ 500 ms |
| API errors | 0 |
| event loop max block | ≤ 250 ms |
| SSE first packet p95 | ≤ 1000 ms |
| SSE catchup p95 | ≤ 1000 ms |
| dropped_chunks | 0 |
| replayed chunks | > 0（证明完成补齐） |

> 若日志只有 1 条 chunk，脚本会以较晚 cursor 起步；仍无法形成缺失窗口时会失败，需先执行一次有输出的模块。

## 8. 数据与指标归档

```bash
sha256sum docs/perf/rc2-after.json
python - <<'PY'
import json
data=json.load(open('docs/perf/rc2-after.json'))
print(data['network'])
PY
```

确认：

- `network.api`、`network.sse_reconnect` 存在；
- `docs/perf/rc2-after.json` 已包含 100k 环形日志、50 模块 flush、50 并发生产者数据；
- `SHA256SUMS` 中发布附件已更新。

## 9. 通过判定与晋升

全部满足：

- [ ] `verify_docker.sh` Exit 0；
- [ ] 容器内默认 pytest ≥221 passed；PBT/benchmark 单独执行并通过；
- [ ] 非 root UID / 700 / 600；
- [ ] API 验证全部 PASS；
- [ ] 网络压测全部达标；
- [ ] `docs/perf/rc2-after.json` 已合并 `network`；
- [ ] `data/` 备份已保留。

通过后回复：

```text
实机门禁通过
```

随后执行：

1. 合并最终压测数据；
2. 创建/移动 `v1.0.5` Tag；
3. 将 Release Notes 更新为 **v1.0.5 (Production Ready)**；
4. 输出发布宣告。

## 10. 失败处理

- 镜像构建失败：检查 Docker/Compose 版本、PUID/PGID、网络代理；
- pytest 失败：保留容器内 `pytest` 输出与 `/tmp/rc2-tests`；
- 非 root 失败：检查 entrypoint 的 `setuid/setgid` 与 bind mount 权限；
- 压测失败：保留 `docs/perf/rc2-after.json` 原始数据与容器日志，不得晋升 v1.0.5。
