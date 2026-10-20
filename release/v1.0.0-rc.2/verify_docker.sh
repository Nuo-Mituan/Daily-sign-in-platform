#!/usr/bin/env bash
#
# 一键验证签到云台的 Docker 构建、启动与核心 API。
#
# 该脚本会创建一个完全隔离的临时环境：
#   - 临时数据库 / 日志 / 模块目录（不会碰你的 data、logs、modules）
#   - 独立 Compose 项目名、容器名、镜像名和一个随机本地端口
#   - 随机管理员密码和临时 SECRET_KEY
# 验证完成后自动销毁，除非传入 --keep。
#
# 用法：
#   ./verify_docker.sh
#   ./verify_docker.sh --keep
#   ./verify_docker.sh --help
#
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
KEEP_ENV=0
CONTAINER_STARTED=0
TMP_ROOT=""
PROJECT_NAME=""
IMAGE_NAME_VERIFY=""
CONTAINER_NAME_VERIFY=""

if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'
  C_BOLD=$'\033[1m'
  C_DIM=$'\033[2m'
  C_RED=$'\033[31m'
  C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'
  C_BLUE=$'\033[34m'
else
  C_RESET=""
  C_BOLD=""
  C_DIM=""
  C_RED=""
  C_GREEN=""
  C_YELLOW=""
  C_BLUE=""
fi

usage() {
  cat <<'EOF'
签到云台 Docker 部署验证

用法：
  ./verify_docker.sh            构建、启动、验证，然后自动清理
  ./verify_docker.sh --keep     验证后保留临时容器和环境（用于排查）
  ./verify_docker.sh --help     显示帮助

说明：
  - 需要 Docker Engine 与 Docker Compose v2。
  - 构建可能要几分钟，首次运行需要下载镜像和依赖。
  - 本脚本使用临时数据，不会修改项目中的 data/、logs/、modules/。
EOF
}

log_step() {
  printf '\n%s%s==> %s%s\n' "$C_BOLD" "$C_BLUE" "$*" "$C_RESET"
}

log_info() {
  printf '%s  · %s%s\n' "$C_DIM" "$*" "$C_RESET"
}

log_pass() {
  printf '%s  [PASS] %s%s\n' "$C_GREEN" "$*" "$C_RESET"
}

log_warn() {
  printf '%s  [WARN] %s%s\n' "$C_YELLOW" "$*" "$C_RESET"
}

log_fail() {
  printf '%s  [FAIL] %s%s\n' "$C_RED" "$*" "$C_RESET" >&2
}

die() {
  log_fail "$*"
  exit 1
}

compose() {
  docker compose --project-name "$PROJECT_NAME" --file "$ROOT_DIR/docker-compose.yml" "$@"
}

generate_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  elif [[ -r /dev/urandom ]] && command -v od >/dev/null 2>&1; then
    od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
  else
    printf 'verify-%s-%s-%s-%s' "$(date +%s)" "$RANDOM" "$RANDOM" "$RANDOM"
  fi
}

find_free_port() {
  if command -v python3 >/dev/null 2>&1; then
    python3 - <<'PY'
import socket
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
  else
    awk 'BEGIN { srand(); print 20000 + int(rand() * 20000) }'
  fi
}

http_probe() {
  local url="$1"
  if command -v curl >/dev/null 2>&1; then
    curl --noproxy "*" -fsS --max-time 3 "$url" >/dev/null 2>&1
    return $?
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$url" >/dev/null 2>&1 <<'PY'
import sys
import urllib.request

try:
    with urllib.request.urlopen(sys.argv[1], timeout=3) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
    return $?
  fi
  return 2
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  set +e

  if (( CONTAINER_STARTED == 1 && KEEP_ENV == 0 )); then
    compose down --remove-orphans --timeout 15 >/dev/null 2>&1
  fi

  if (( exit_code != 0 && CONTAINER_STARTED == 1 )); then
    printf '\n%s最近 150 行容器日志：%s\n' "$C_YELLOW" "$C_RESET" >&2
    compose logs --no-color --tail=150 2>/dev/null
  fi

  if (( KEEP_ENV == 1 )); then
    printf '\n%s验证环境已保留（--keep）：%s\n' "$C_YELLOW" "$C_RESET"
    printf '  访问地址 : http://127.0.0.1:%s\n' "$APP_PORT"
    printf '  管理员   : %s\n' "$ADMIN_USER"
    printf '  密码     : %s\n' "$ADMIN_PASS"
    printf '  容器名   : %s\n' "$CONTAINER_NAME_VERIFY"
    printf '  镜像名   : %s\n' "$IMAGE_NAME_VERIFY"
    printf '  临时目录 : %s\n' "$TMP_ROOT"
    printf '  清理命令 : docker rm -f %s; docker image rm -f %s; docker network rm %s_default 2>/dev/null; rm -rf %s\n' \
      "$CONTAINER_NAME_VERIFY" "$IMAGE_NAME_VERIFY" "$PROJECT_NAME" "$TMP_ROOT"
  else
    if [[ -n "$TMP_ROOT" && -d "$TMP_ROOT" ]]; then
      rm -rf "$TMP_ROOT"
    fi
    if [[ -n "$IMAGE_NAME_VERIFY" ]]; then
      docker image rm -f "$IMAGE_NAME_VERIFY" >/dev/null 2>&1 || true
    fi
    if (( CONTAINER_STARTED == 1 )); then
      printf '%s  临时容器、镜像与数据目录已清理。%s\n' "$C_DIM" "$C_RESET"
    fi
  fi

  exit "$exit_code"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for arg in "$@"; do
  case "$arg" in
    --keep)
      KEEP_ENV=1
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "未知参数：$arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

cd "$ROOT_DIR"

log_step "0/7 检查环境"
[[ -f "$ROOT_DIR/Dockerfile" ]] || die "未找到 Dockerfile"
[[ -f "$ROOT_DIR/docker-compose.yml" ]] || die "未找到 docker-compose.yml"
[[ -f "$ROOT_DIR/scripts/verify_api.py" ]] || die "未找到 scripts/verify_api.py"
command -v docker >/dev/null 2>&1 || die "未安装 Docker"
docker compose version >/dev/null 2>&1 || die "未安装 Docker Compose v2（需要 docker compose 命令）"
docker info >/dev/null 2>&1 || die "无法连接 Docker 守护进程，请确认 Docker Desktop / dockerd 已启动"
if ! command -v curl >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
  die "健康检查需要 curl 或 python3（至少安装一个）"
fi
log_pass "Docker、Compose v2 与健康检查工具均可用"

PROJECT_NAME="daily-checkin-verify-$(date +%s)-$$"
CONTAINER_NAME_VERIFY="daily-checkin-verify-$$"
IMAGE_NAME_VERIFY="daily-checkin-platform-verify:$$-$(date +%s)"
TMP_ROOT="$(mktemp -d "$ROOT_DIR/.verify.XXXXXX")"
TMP_ROOT="$(cd "$TMP_ROOT" && pwd -P)"
mkdir -p "$TMP_ROOT/data" "$TMP_ROOT/logs" "$TMP_ROOT/modules"
cp -R "$ROOT_DIR/modules/." "$TMP_ROOT/modules/"

APP_PORT="$(find_free_port)"
APP_BIND="127.0.0.1"
ADMIN_USER="verifyadmin"
ADMIN_PASS="Verify-$(generate_secret | cut -c1-24)"
SECRET_KEY="$(generate_secret)"
export APP_PORT APP_BIND ADMIN_USER ADMIN_PASS SECRET_KEY
export TZ="Asia/Shanghai"
export TIMEZONE="Asia/Shanghai"
export MODULE_TIMEOUT="120"
export ACCOUNT_INTERVAL_MIN_SECONDS="1"
export ACCOUNT_INTERVAL_MAX_SECONDS="1"
export SCHEDULE_MIN_LEAD_SECONDS="2"
export LOG_RETENTION_DAYS="31"
export PUID="$(id -u)"
export PGID="$(id -g)"
export COOKIE_SECURE="false"
export CSRF_ENABLED="true"
export LOG_MAX_CHARS="512000"
export UPLOAD_MAX_MB="10"
export CONTAINER_NAME="$CONTAINER_NAME_VERIFY"
export IMAGE_NAME="$IMAGE_NAME_VERIFY"
export DATA_DIR_HOST="$TMP_ROOT/data"
export MODULES_DIR_HOST="$TMP_ROOT/modules"
export LOGS_DIR_HOST="$TMP_ROOT/logs"
export COMPOSE_PROJECT_NAME="$PROJECT_NAME"

log_info "临时环境：$TMP_ROOT"
log_info "镜像：$IMAGE_NAME_VERIFY"
log_info "容器：$CONTAINER_NAME_VERIFY"
log_info "本地地址：http://127.0.0.1:$APP_PORT"

log_step "1/7 构建 Docker 镜像（docker compose build）"
if ! compose build; then
  die "docker compose build 失败"
fi
log_pass "Docker 镜像构建成功"

log_step "2/7 启动容器"
CONTAINER_STARTED=1
if ! compose up -d --no-build; then
  die "docker compose up 失败"
fi
log_pass "容器已启动"

log_step "3/7 等待 HTTP 健康检查"
HEALTH_URL="http://127.0.0.1:${APP_PORT}/api/health"
READY=0
for _attempt in $(seq 1 60); do
  if http_probe "$HEALTH_URL"; then
    READY=1
    break
  fi
  sleep 2
done
if (( READY == 0 )); then
  die "容器在 120 秒内未通过健康检查：$HEALTH_URL"
fi
log_pass "健康检查通过：$HEALTH_URL"

log_step "4/7 验证非 root 运行与私有数据权限"
APP_UID="$(compose exec -T checkin-platform awk '/^Uid:/{print $2}' /proc/1/status | tr -d '\r')"
if [[ "$APP_UID" != "$PUID" ]]; then
  die "主进程 UID 为 $APP_UID，期望 PUID=$PUID（入口降权失败）"
fi
DATA_MODE="$(compose exec -T checkin-platform stat -c '%a' /app/data | tr -d '\r')"
DB_MODE="$(compose exec -T checkin-platform stat -c '%a' /app/data/checkin.db | tr -d '\r')"
LOG_MODE="$(compose exec -T checkin-platform stat -c '%a' /app/logs | tr -d '\r')"
[[ "$DATA_MODE" == "700" ]] || die "/app/data 权限为 $DATA_MODE，期望 700"
[[ "$DB_MODE" == "600" ]] || die "SQLite 权限为 $DB_MODE，期望 600"
[[ "$LOG_MODE" == "700" ]] || die "/app/logs 权限为 $LOG_MODE，期望 700"
log_pass "非 root 进程 UID=$APP_UID；data/logs=700，SQLite=600"

log_step "5/7 容器内测试（生产包按需）"
if compose exec -T checkin-platform test -d /app/backend/tests; then
  if ! compose exec -T -e DATA_DIR=/tmp/rc2-tests/data -e LOGS_DIR=/tmp/rc2-tests/logs -e SECRET_KEY=rc2-container-test -e ADMIN_USER=admin -e ADMIN_PASS=admin123 checkin-platform env PYTHONPATH=/app pytest backend/tests -q; then
    die "容器内技术债回归失败"
  fi
  log_pass "容器内全量测试通过"
else
  log_warn "生产包不包含 tests/，跳过容器内 pytest；完整测试需在源码 Release Tag 执行"
fi

log_step "6/7 验证登录、随机调度、多账号、推送、用户设置、环形日志与执行 API"
if ! compose exec -T checkin-platform python - < "$ROOT_DIR/scripts/verify_api.py"; then
  die "核心 API 验证失败"
fi
log_pass "核心 API 验证全部通过"

log_step "7/7 清理"
if (( KEEP_ENV == 1 )); then
  log_warn "指定了 --keep，将保留验证环境，请稍后手动清理"
else
  log_info "验证完成后自动清理临时环境"
fi

printf '\n%s%s✓ 部署验证通过%s\n' "$C_BOLD" "$C_GREEN" "$C_RESET"
printf '  镜像构建、容器启动、健康检查、登录、未认证隔离、用户名/密码、\n'
printf '  五种周期与条件子选项、旧周期迁移、随机时间、多账号串行、脱敏日志、\n'
printf '  部分失败、推送配置、启用/禁用调度、手动执行、环形日志保留策略、\n'
printf '  历史日志、目录扫描与仪表盘均已验证。\n\n'

exit 0
