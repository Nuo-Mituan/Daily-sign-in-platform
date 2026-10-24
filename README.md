# 签到云台 · Daily Check-in Platform

> ## v1.0.5 Release
>
> 本次 Minor 版本新增模块图标系统：支持 Emoji、本地 ICO、Base64 Data URI 与 HTTPS URL；
> 本地 ICO 经 RGBA PNG 转换保留 Alpha 透明通道，并提供路径沙箱、Magic Bytes、大小/尺寸限制与统一降级。
>
> - 发布与变更管制：[docs/RELEASE_POLICY.md](docs/RELEASE_POLICY.md)
> - Docker 验证 SOP：[docs/DOCKER_GATE_SOP.md](docs/DOCKER_GATE_SOP.md)
> - 统一推送：[docs/UNIFIED_PUSH.md](docs/UNIFIED_PUSH.md)
> - 生产安全：[docs/PRODUCTION_SECURITY.md](docs/PRODUCTION_SECURITY.md)
>
> 生产部署前请执行 `bash verify_docker.sh`，并确认目标架构上的构建、启动与核心 API 验证通过。

一个可自托管、可在 Docker 中一键部署的**每日自动签到平台**。它把每个签到项目当作独立模块（插件）管理：
在网页端安装模块、填写账号参数、设置随机时间窗与重复周期、独立启停、立即执行，
并实时查看执行日志。多账号模块会按顺序串行执行，账号之间自动随机等待。

> 定位类似青龙面板的签到任务管理，但更专注于「模块化 + 账号管理 + 随机调度 + 统一推送」。
> 技术栈：**FastAPI + APScheduler + SQLite + Vue 3 + Element Plus**。
>
> 第三次迭代（用户设置、随机时间、多账号、统一推送）的详细变更与文件清单见
> [docs/ITERATION3_CHANGES.md](docs/ITERATION3_CHANGES.md)。
> 第四次迭代（周期子选项、未认证页面隐私）见
> [docs/ITERATION4_CHANGES.md](docs/ITERATION4_CHANGES.md)。
> 第六轮（安全基础、环形日志、推送重构）见
> [docs/ITERATION6_CHANGES.md](docs/ITERATION6_CHANGES.md)。

<p align="center">
  <img src="docs/screenshots/dashboard.png" width="49%" alt="运行概览" />
  <img src="docs/screenshots/modules.png" width="49%" alt="签到模块" />
</p>

> 截图使用示例数据，实际部署时模块默认关闭且参数为空。

---

## 目录

- [核心特性](#核心特性)
- [快速开始](#快速开始)
- [部署验证](#部署验证)
- [目录结构](#目录结构)
- [使用说明](#使用说明)
- [模块系统](#模块系统)
- [模块图标配置](#模块图标配置)
- [配置项](#配置项)
- [本地开发](#本地开发)
- [开发与调试工具](#开发与调试工具)
- [生产安全加固](#生产安全加固)
- [数据备份与升级](#数据备份与升级)
- [安全说明](#安全说明)
- [已知限制](#已知限制)
- [常见问题](#常见问题)
- [API 一览](#api-一览)
- [更新日志](#更新日志)

---

## 核心特性

- **多源模块图标**：支持 Emoji、本地 ICO、Base64 Data URI、HTTPS URL；本地 ICO 自动转 RGBA PNG 保留透明通道，非法或加载失败统一降级为 ⚠️。
- **模块热插拔**：上传 ZIP 或把模块目录放进 `modules/` 后点击扫描，无需重启服务。
- **自动渲染参数表单**：模块通过 `config.json` 声明 `text / textarea / password / select / switch / number` 参数。
- **参数加密存储**：AES-256-GCM v2（HKDF-SHA256 派生密钥、AAD 绑定模块/账号），旧 Fernet 密文透明升级。
- **随机时间调度**：为每个模块设置 `HH:mm` 时间窗与每日 / 每周 / 每月15日 / 每月 / 每年周期；
  每周可选星期几、每月可选 1–28 日、每年可选月-日。平台在执行日 00:00 均匀随机生成执行时间；
  整点补偿，时间窗中点兜底并推送告警。
- **多账号串行**：账号数组支持添加、删除、折叠、备注与拖拽排序；平台逐账号执行，
  默认随机等待 2–5 分钟；日志中的账号标识自动脱敏，部分失败会汇总为整体失败。
- **统一推送**：Bark / Server酱 / PushPlus / 钉钉 / 飞书，全局渠道加密保存；
  每个模块有独立推送开关，支持自定义标题与正文模板变量。
- **独立开关**：每个模块独立启用 / 禁用，开关与随机调度即时同步。
- **手动执行 / 手动重生成**：任意模块可立即执行一次；启用模块可重新生成本期随机时间。
- **实时日志**：执行输出通过 SSE 实时推送到网页，支持查看历史、复制、下载。
- **仪表盘**：模块总数、启用数、今日执行、成功 / 失败、运行中模块、下一次随机计划与最近记录。
- **完整执行历史**：按模块、状态、触发方式筛选，分页查询。
- **单管理员 + Cookie 会话**：首次部署自动创建管理员；HttpOnly/SameSite=Strict Cookie、服务端会话白名单与 CSRF 防护
  与修改密码，登录失败统一提示，具备基础防枚举与敏感操作限流。
- **Docker 一键部署**：多阶段构建，前端与后端打包进同一个轻量镜像，数据通过 volume 持久化。
- **内置示例模块**：两个不访问真实接口的演示模块，覆盖所有参数类型与相对导入。
- **进阶模块模板**：多账号标准入口，演示 Cookie 过期检测、自动刷新、退避重试与平台推送接入。
- **部署验证脚本**：一条命令在隔离环境中验证 Docker 构建、启动、随机调度、多账号、推送配置与核心 API。

---

## 快速开始

### 前置要求

- Docker Engine 20.10+
- Docker Compose v2（`docker compose` 命令）
- 建议 1 GB 以上可用内存

### 1. 准备目录

```bash
cd daily-checkin-platform

mkdir -p data logs modules
cp .env.example .env        # 可选：修改端口；ADMIN_PASS 留空则自动生成随机密码
```

### 2. 构建并启动

```bash
docker compose up -d --build
```

首次构建需要下载 Node 与 Python 依赖，耗时取决于网络。启动后查看日志：

```bash
docker compose logs -f checkin-platform
```

看到类似下面的日志表示启动成功：

```text
调度器已启动，时区=Asia/Shanghai
模块同步完成：新增 2，更新 0，异常 0
签到云台 v1.0.5 启动完成 | 模块 2 | 已排程 0 | 时区 Asia/Shanghai
```

### 3. 访问

打开 **<http://localhost:5000>**。

首次启动时若未设置 `ADMIN_PASS`，系统会自动生成随机密码并输出到容器日志。
请使用以下命令获取（仅首次创建管理员时输出）：

```bash
docker logs <container> 2>&1 | grep 'Generated admin password'
```

完整密码仅在首次创建管理员时输出一次到容器 stdout，不会写入 `.initial_pwd` 或日志文件；
请在首次启动后立即从部署日志中保存，并妥善保管。获取后使用该密码登录；首次登录会被强制要求修改密码。

**显式设置 `ADMIN_PASS` 时策略不同**：系统使用你指定的密码，首次登录**不会**强制改密。
请确保该密码符合安全策略，并自行在「用户设置」中完成首次改密。
`ADMIN_USER` / `ADMIN_PASS` 不会修改已存在账户的凭据。

### 4. 配置示例模块

1. 进入「签到模块」，两个示例模块默认处于禁用状态。
2. 点击「演示签到」卡片进入配置页。
3. 填写任意账号 / 密码，选择服务器，设置时间窗与周期，点击「保存配置」。
4. 打开右上角开关启用模块，页面会生成本期随机执行时间。
5. 点击「立即执行」查看实时日志；多账号示例可在配置页添加多个账号。

也可以上传自己的模块，详见 [模块系统](#模块系统) 与
[docs/MODULE_DEVELOPMENT.md](docs/MODULE_DEVELOPMENT.md)。

---

## 部署验证

仓库内置了一个隔离验证脚本，适合在首次部署或升级后运行：

```bash
chmod +x verify_docker.sh
./verify_docker.sh
```

脚本会：

1. 使用独立的 Compose 项目名、容器名、镜像名和随机端口；
2. 在临时目录中复制示例模块，不修改你的 `data/`、`logs/`、`modules/`；
3. 执行 `docker compose build` 并启动容器；
4. 调用 `/api/health`；
5. 使用随机管理员密码登录，验证未认证隔离、用户名/密码、随机时间与五种周期、
   多账号串行与脱敏日志、部分失败汇总、推送配置、启用/禁用、手动执行、历史日志、
   目录扫描与仪表盘；
6. 自动清理临时环境；失败时输出最近容器日志并以非零状态退出。

前端隐私检查（需要已安装 Chrome / Chromium，并确保前端已构建或通过 Vite 运行）：

```bash
BASE_URL=http://127.0.0.1:5000 node scripts/check_frontend_privacy.mjs
```

脚本会以未登录状态打开 `/login`、`/dashboard`、`/modules`、`/settings` 等路由，
断言 DOM 中不存在 `schedule-preview`、模块名称、时间窗、账号数量等敏感内容。

需要排查时可以保留环境：

```bash
./verify_docker.sh --keep
```

前提：Docker Engine、Docker Compose v2，以及 `curl` 或 `python3`（用于宿主机健康检查）。

> 验证脚本会修改临时环境中的模块配置和执行记录，**不要**让它连接生产数据库。

核心 API 验证逻辑单独放在 [`scripts/verify_api.py`](scripts/verify_api.py)，
也可以在本地对已有实例运行（会修改数据，仅限一次性 / 验证环境）：

```bash
VERIFY_BASE_URL=http://127.0.0.1:5000/api \
ADMIN_USER=admin ADMIN_PASS=<首次生成的随机密码> \
python3 scripts/verify_api.py --password <首次生成的随机密码>
```

---

## 目录结构

```text
daily-checkin-platform/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI 入口、lifespan、静态文件托管
│   │   ├── config.py               # 环境变量 / 路径 / 密钥初始化
│   │   ├── database.py             # async SQLAlchemy + SQLite
│   │   ├── models.py               # User / Module / ModuleSchedule / PushConfig / ExecutionLog
│   │   ├── schemas.py              # Pydantic 请求与响应
│   │   ├── security.py             # PBKDF2 密码哈希
│   │   ├── crypto.py               # 参数与推送配置加密（支持账号数组）
│   │   ├── module_loader.py        # 模块扫描、校验、账号规范化、热导入
│   │   ├── scheduling.py           # 周期、时间窗、随机时间计算
│   │   ├── migrations.py           # SQLite 前向迁移（旧 Cron → 时间窗）
│   │   ├── routers/
│   │   │   ├── auth.py             # 登录 / 当前用户 / 用户名 / 密码
│   │   │   ├── modules.py          # 模块 CRUD、账号、随机调度、执行
│   │   │   ├── push.py             # 全局推送配置与测试
│   │   │   ├── logs.py             # 历史记录 + SSE 实时日志
│   │   │   ├── dashboard.py        # 仪表盘统计
│   │   │   └── system.py           # /api/health、/api/meta
│   │   └── services/
│   │       ├── scheduler.py        # 动态 plan / exec / fallback 一次性任务
│   │       ├── schedules.py        # 本期计划生成、兜底、状态机
│   │       ├── execution.py        # 多账号串行、间隔、汇总、推送
│   │       ├── push.py             # Bark / Server酱 / PushPlus / 钉钉 / 飞书
│   │       ├── auth_guard.py       # 敏感操作锁与失败限流
│   │       ├── hub.py              # 内存日志发布 / 订阅
│   │       ├── capture.py          # stdout / stderr / logging 捕获
│   │       ├── module_upload.py    # ZIP 安全解压、安装、删除
│   │       ├── maintenance.py      # 遗留任务修复、日志清理
│   │       ├── file_logs.py        # 文件日志镜像
│   │       └── bootstrap.py        # 首次管理员与模块同步
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/
│   ├── src/
│   │   ├── views/                  # Login / Dashboard / Modules / Detail / Logs / Settings / Guide
│   │   ├── components/             # 参数表单、账号编辑器、随机时间、日志抽屉
│   │   ├── layouts/AppLayout.vue   # 侧栏 + 顶栏 + 用户菜单
│   │   ├── router/                 # 路由与登录守卫
│   │   ├── stores/                 # Pinia：auth / app
│   │   ├── api/                    # Axios + SSE 客户端
│   │   └── styles/global.css
│   ├── package.json
│   ├── package-lock.json
│   ├── pnpm-lock.yaml
│   ├── vite.config.js
│   └── pnpm-workspace.yaml
├── modules/
│   ├── demo_checkin/               # 示例 1：覆盖全部参数类型
│   │   ├── config.json
│   │   └── main.py
│   └── moyu_energy/                # 示例 2：多账号 + 相对导入 + 辅助文件
│       ├── config.json
│       ├── main.py
│       └── utils.py
├── templates/
│   └── advanced_checkin/           # 进阶模板：多账号入口、Cookie 刷新、重试
│       ├── config.json
│       ├── main.py
│       └── README.md
├── scripts/
│   └── verify_api.py               # 容器内执行的核心 API 验证
├── verify_docker.sh                # 一键 Docker 部署验证
├── docs/
│   ├── MODULE_DEVELOPMENT.md       # 模块开发规范
│   ├── PRODUCTION_SECURITY.md      # 内网部署安全指南
│   ├── BACKUP_AND_MIGRATION.md     # 备份、恢复与迁移
│   └── screenshots/
├── backend/tests/                  # 单元测试 + API 冒烟测试
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .dockerignore
└── README.md
```

运行时目录（已由 `.gitignore` 忽略）：

```text
data/checkin.db          # SQLite 数据库
data/.secret_key         # 自动生成的密钥（未配置 SECRET_KEY 时）
modules/<key>/           # 模块目录，挂载到宿主机
logs/executions/<key>/   # 执行日志文件镜像
```

---

## 使用说明

### 用户设置

- 登录页支持用户名 / 密码；使用 HttpOnly Cookie 会话，5 分钟滑动续期，写请求需要 `X-CSRF-Token`。
- 「用户设置」可修改用户名（需验证当前密码）和修改密码。
- 用户名修改是幂等的，并带有并发锁与数据库唯一性兜底；重复提交相同用户名不会报错。
- 连续输错当前密码会触发临时限流；登录失败统一提示「用户名或密码错误」。
- 修改密码后强制退出，需要使用新密码重新登录。
- 同一页面可配置全局推送渠道与消息模板。

### 签到模块列表

- 卡片展示模块名称、标识、作者、版本、描述。
- 展示时间窗、重复周期、本次随机执行时间、最近执行状态、账号数量与推送开关。
- 右上角开关独立启用 / 禁用；启用时生成本期随机执行时间。
- 底部操作：配置、立即执行、查看日志、更多（删除）。
- 支持按全部 / 已启用 / 未启用 / 异常筛选与关键词搜索。
- 「扫描目录」会热加载 `modules/` 下的模块。
- 「上传模块」支持 ZIP 安装，可选择覆盖同名模块；覆盖时保留账号与调度配置。

### 模块配置

- 表单由 `config.json` 的 `params` 自动生成，支持 `text`、`textarea`、`password`、
  `select`、`switch`、`number`。
- 单账号模块直接显示参数表单；`multi_account: true` 的模块显示账号卡片列表：
  添加、删除、复制、折叠、备注、上下移动与拖拽排序。
- 每个账号独立填写全部参数，并单独加密保存。账号顺序就是执行顺序。
- 随机执行时间：设置 `HH:mm` 时间窗与重复周期；开始必须早于结束，不支持跨天。
- 周期子选项：每周选择周一至周日；每月选择 1–28 日；每年选择月-日（2 月 29 日仅闰年执行）。
- 页面展示「本次执行时间」与状态；可手动「重新生成」。
- 模块页提供「启用推送」开关，推送内容由全局模板渲染。
- 保存后若时间窗 / 周期变化，会取消旧计划并立即生成本期新时间。
- 「使用模块默认时间窗」可恢复 `config.json` 的 `default_*` 值。

### 模块图标配置

模块图标由 `config.json` 的 `icon` 字段解析，支持四种格式；旧字段 `icon_source` / `icon_data` 继续兼容：

| 类型 | `icon` 示例 | 说明 |
| --- | --- | --- |
| Emoji / 文本 | `"icon": "🎯"` | 原样文本渲染，保留原有底色 |
| 本地 ICO | `"icon": "./favicon.ico"` | 读取 `modules/<module-key>/` 内的文件；后端转 RGBA PNG |
| Base64 Data URI | `"icon": "data:image/png;base64,..."` | 仅允许 `x-icon`、`png`、`svg+xml`，≤64KB |
| HTTPS URL | `"icon": "https://example.com/icon.png"` | 远程图片；加载失败降级为 ⚠️ |

```json
{
  "name": "示例签到",
  "icon": "./favicon.ico",
  "script": "main.py"
}
```

本地 ICO 放置位置：

```text
modules/
└── demo_checkin/
    ├── config.json
    ├── main.py
    └── favicon.ico
```

安全约束：

- 仅允许 `modules/<module-key>/` 自身目录内的相对路径，拒绝 `..`、绝对路径、反斜杠和空字节。
- 使用 `resolve()` 后的真实路径前缀校验，阻断软链接逃逸；路径不存在或越界直接拒绝。
- 文件大小 ≤64KB、解码尺寸 ≤1024×1024；文件头必须是 ICO magic `00 00 01 00`。
- 后端使用 Pillow 以 RGBA 打开并转存 PNG，透明 Alpha 通道不会在后端丢失。
- 前端对 Base64 做 MIME 白名单与正则二次校验，禁止 `javascript:` 等非图片 Data URI。
- 图片加载失败、文件缺失、非法 Base64 或路径非法时统一显示 `⚠️`，不抛未捕获异常。
- 图片态容器移除渐变背景、边框与阴影，避免透明区域被底色污染；Emoji 保留原样式。
- 非透明 ICO 保持原样，不会强制添加透明背景。

旧配置仍可用：

```json
{"icon_source": "local"}
{"icon_source": "base64", "icon_data": "data:image/png;base64,..."}
```

### 图标透明背景诊断

本地 ICO 会在后端通过 Pillow 转成 RGBA PNG 返回，透明像素不会被前端容器的渐变底色污染。
如仍有异常，使用诊断脚本检查 Base64/文件是否包含 Alpha：

```bash
python3 scripts/check_icon_alpha.py --base64 'data:image/x-icon;base64,AAABAAEAEBAAAAAAIABSAAAAFgAAAIlQTkcNChoKAAAADUlIRFIAAAAQAAAAEAgGAAAAH/P/YQAAABlJREFUeJxjYBgFo4AI8N/B4T8x6kbBkAYAvkECf0xuXgsAAAAASUVORK5CYII='
```

输出 `alpha_min=0` 表示存在透明像素。若 ICO 本身只有不透明颜色，`alpha_min=255` 属于正常，不应强制加透明。
前端图片容器在渲染图片时会移除渐变背景、边框和阴影；Emoji 仍保留原有底色。

### 立即执行与实时日志

- 点击「立即执行」后，后台创建执行记录并开始运行。
- 日志抽屉通过 SSE 流式展示 stdout / stderr / logging 输出。
- 支持查看耗时、触发方式、状态、结果说明。
- 支持复制与下载日志。
- 执行结束后自动刷新模块状态与执行记录。
- 同一模块同一时间只允许一个执行实例；重复触发会提示正在执行。
- 多账号执行会按顺序输出 `[账号 1/N]` … `[账号 N/N]`，账号之间显示随机等待，自动隐藏完整凭据。

### 执行记录

- 全局记录可按模块、状态、触发方式筛选。
- 可开启每 10 秒自动刷新。
- 点击任意记录打开日志抽屉；运行中的任务会实时显示输出。
- 执行输出同时保存在数据库与宿主机 `logs/` 目录。

### 仪表盘

- 模块总数 / 已启用模块 / 今日执行 / 正在运行。
- 今日成功、失败与成功率。
- 最近执行记录。
- 本次随机执行计划列表（按时间排序，展示周期/时间窗/状态）。
- 今日健康度环形图与调度器在线状态。

### 界面预览

| 登录 | 实时日志 |
| --- | --- |
| ![登录](docs/screenshots/login.png) | ![实时日志](docs/screenshots/live-logs.png) |

| 用户设置 / 全局推送 | 多账号与随机时间配置 |
| --- | --- |
| ![用户设置](docs/screenshots/settings.png) | ![模块配置](docs/screenshots/module-config.png) |

| 上传模块 |
| --- |
| ![上传模块](docs/screenshots/upload-module.png) |

---

## 模块系统

一个模块就是一个目录，包含 `config.json` 和 `main.py`：

```text
modules/
└── my_checkin/
    ├── config.json
    └── main.py
```

`config.json`：

```json
{
  "name": "某平台签到",
  "description": "自动完成某平台每日签到",
  "author": "your-name",
  "version": "1.0.0",
  "icon": "🎯",
  "default_start_time": "08:00",
  "default_end_time": "10:00",
  "default_repeat_cycle": "daily",
  "default_repeat_sub_value": "",
  "multi_account": true,
  "params": [
    {
      "key": "cookie",
      "label": "Cookie",
      "type": "textarea",
      "required": true,
      "rows": 4,
      "account_label": true,
      "placeholder": "请填入你的 Cookie"
    },
    {
      "key": "target_level",
      "label": "目标等级",
      "type": "number",
      "default": 3
    }
  ]
}
```

`main.py`（平台会为每个账号分别调用一次）：

```python
from typing import Any


async def run(params: dict[str, Any]) -> dict[str, Any]:
    cookie = str(params.get("cookie", "")).strip()
    if not cookie:
        return {"success": False, "message": "Cookie 为空"}

    print("开始签到 …")
    # 在这里实现单个账号的真实签到逻辑
    return {"success": True, "message": "签到成功"}
```

模块不需要遍历账号列表、不需要实现随机时间、也不需要发送推送。平台会负责这些平台级能力。

安装方式：

1. **ZIP 上传**：将模块目录压缩为 ZIP，在「签到模块」页上传。
2. **目录挂载**：放入 `./modules/` 后在网页端点击「扫描目录」。

更新代码后下一次执行会自动重新导入 `main.py`，无需重启。新增第三方依赖则需要重建镜像。

完整的字段说明、参数类型、超时、日志、多文件导入与安全建议，请阅读
**[模块开发说明](docs/MODULE_DEVELOPMENT.md)**。

### 示例模块

- `demo_checkin`：「演示签到」，单账号，覆盖全部参数类型，可模拟成功 / 失败。
- `moyu_energy`：「摸鱼能量签到（多账号）」，演示账号级参数、textarea、number、
  switch、相对导入与多账号部分失败汇总。

两个示例都完全在本地模拟，不会访问任何真实接口，可放心试用。

### 进阶模板

[`templates/advanced_checkin`](templates/advanced_checkin/README.md) 提供了一个真实场景模块骨架：

- HTTP 请求、超时与网络异常分类；
- 识别 401 / 403 或业务失效码，用账号密码自动重新登录一次；
- 指数退避重试（网络错误 / 429 / 5xx）；
- 不打印密码、Cookie、Token 明文；
- 多账号标准入口：平台逐账号调用 `run(params)`，模板内不重复账号循环；
- 不实现模块级推送：由「用户设置 → 全局推送」与模块推送开关统一处理；
- 内置 `httpx.MockTransport` 模拟模式，复制到 `modules/` 后可无网络试跑完整流程。

它不会被自动扫描；安装方法见模板内 README。接入真实平台时，请修改
`API_BASE`、接口路径、登录 payload 与成功码映射。

---

## 配置项

所有环境变量均为可选，未配置时使用默认值。

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_BIND` | `0.0.0.0` | Compose 映射端口绑定的宿主地址。内网建议 `127.0.0.1` 或可信局域网 IP。 |
| `APP_PORT` | `5000` | Compose 映射到宿主机的端口。 |
| `TZ` | `Asia/Shanghai` | 容器系统时区（影响容器日志时间）。 |
| `TIMEZONE` | `Asia/Shanghai` | 随机调度、时间窗与页面展示的业务时区。 |
| `ADMIN_USER` | `admin` | 首次创建的管理员用户名。 |
| `ADMIN_PASS` | 留空自动生成 | 首次创建的管理员密码。留空：生成随机密码并强制首次改密；显式设置：使用指定密码且首次登录不强制改密。 |
| `SECRET_KEY` | 自动生成 | Cookie 签名与 AES-256-GCM 参数加密密钥。留空时生成于 `data/.secret_key`。 |
| `COOKIE_SECURE` | `false` | HTTPS 部署必须设为 `true`；内网 HTTP 保持 `false`。 |
| `CSRF_ENABLED` | `true` | 写请求 CSRF Header 校验开关。 |
| `MODULE_TIMEOUT` | `300` | 单个账号执行超时（秒）；多账号分别计时。 |
| `ACCOUNT_INTERVAL_MIN_SECONDS` | `120` | 多账号串行时账号间随机等待下限（秒）。 |
| `ACCOUNT_INTERVAL_MAX_SECONDS` | `300` | 多账号串行时账号间随机等待上限（秒）。 |
| `SCHEDULE_MIN_LEAD_SECONDS` | `5` | 随机时间最少提前秒数，避免生成后立即触发。 |
| `LOG_RETENTION_DAYS` | `30` | 执行记录与文件日志保留天数，`0` 表示不清理。 |
| `LOG_MAX_CHARS` | `512000` | 单次执行捕获的最大输出字符数。 |
| `UPLOAD_MAX_MB` | `10` | ZIP 上传大小限制。 |
| `DATA_DIR` | `./data` | 数据库与密钥目录；容器内为 `/app/data`。 |
| `MODULES_DIR` | `./modules` | 模块目录；容器内为 `/app/modules`。 |
| `LOGS_DIR` | `./logs` | 文件日志目录；容器内为 `/app/logs`。 |
| `FRONTEND_DIR` | `./frontend/dist` | 前端构建产物目录；容器内为 `/app/static`。 |
| `DATABASE_URL` | SQLite | 可选的自定义数据库 URL（需安装对应异步驱动）。 |
| `CORS_ORIGINS` | 空 | 逗号分隔的额外允许来源，同源部署不需要配置。 |

修改 `.env` 后执行 `docker compose up -d` 重建容器。注意：**修改 `ADMIN_USER` / `ADMIN_PASS`
不会修改已存在账户的密码；`ADMIN_PASS` 仅在首次创建管理员时生效。
留空时首次登录强制改密；显式设置时首次登录不强制改密，请自行确认密码强度。**

### 关于 SECRET_KEY

- 推荐留空，让平台自动生成到 `data/.secret_key`。该文件随 data volume 持久化。
- 如果手动设置，请确保长期保持不变。修改后，数据库中已有的模块参数会无法解密，
  需要到每个模块配置页重新填写保存。
- 备份 `data/` 时必须包含 `.secret_key`。

---

## 本地开发

### 后端（Python 3.11+）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-dev.txt

uvicorn app.main:app --app-dir backend --reload --port 5000
```

默认使用项目根目录下的 `data/`、`modules/`、`logs/`，并托管 `frontend/dist/`。
未构建前端时访问 `/` 会返回提示 JSON，但 API 与 `/docs` 仍可用。

### 前端（Node.js 20+）

```bash
cd frontend
npm install          # 或 pnpm install
npm run dev
```

Vite 默认运行在 <http://localhost:5173>，并将 `/api` 代理到 `http://127.0.0.1:5000`。
可通过 `VITE_PROXY_TARGET` 修改代理目标。

生产构建：

```bash
cd frontend
npm run build
# 产物在 frontend/dist，后端默认会托管它
```

### 运行测试

```bash
source .venv/bin/activate
pytest backend/tests
```

### 无需 Docker 的一体化运行

```bash
cd frontend && npm run build && cd ..
source .venv/bin/activate
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 5000
```

打开 <http://localhost:5000>。

---

## 开发与调试工具

### 图标透明度诊断

本地 ICO 会在后端转成 RGBA PNG 返回。使用诊断脚本检查文件或 Base64 是否包含 Alpha：

```bash
python3 scripts/check_icon_alpha.py --file modules/demo_checkin/favicon.ico
python3 scripts/check_icon_alpha.py --base64 'data:image/x-icon;base64,...'
```

输出示例：

```text
format=ICO mode=RGBA alpha_min=0 alpha_max=255
```

`alpha_min=0` 表示存在透明像素；`alpha_min=255` 表示 ICO 本身完全不透明，属于正常情况。
测试集包含透明 ICO、超大文件、伪造 ICO、路径遍历与 Base64 XSS 场景。

### 质量检查

```bash
pytest backend/tests          # 84 passed
mypy backend/app              # 类型检查
cd frontend && npm run build  # 生产构建验证
```

## 生产安全加固

完整清单、Nginx / Caddy 配置与日志保留策略见
**[生产部署安全检查清单](docs/PRODUCTION_SECURITY.md)**。

上线前至少确认：

- [ ] 使用强随机管理员密码；留空 ADMIN_PASS 时首次登录必须改密
- [ ] 显式设置并长期保存 `SECRET_KEY`，或备份 `data/.secret_key`
- [ ] `.env` 权限为 `600`，且未提交到 Git
- [ ] 设置 `APP_BIND=127.0.0.1` 或可信局域网 IP，不暴露公网
- [ ] 如使用 HTTPS 反向代理，设置 `COOKIE_SECURE=true`
- [ ] 为 `/api/auth/login` 配置登录限流
- [ ] SSE 路径关闭代理缓冲（否则实时日志会被延迟）
- [ ] 合理设置 `LOG_RETENTION_DAYS` 并监控磁盘
- [ ] 只安装可信模块（模块代码以服务进程权限执行）
- [ ] 实际演练一次备份恢复

安全文档还包含：

- `SECRET_KEY` 生成、轮换与备份的注意事项
- 内网 HTTP 风险边界与防火墙/VLAN 建议
- Cookie/CSRF、上传大小、CORS 等生产推荐 `.env`
- 日志保留位置、清理任务与 Docker 日志轮转

---

## 数据备份与升级

完整步骤、升级回滚与「哪些文件不能覆盖」见
**[备份、恢复与迁移指南](docs/BACKUP_AND_MIGRATION.md)**。

### 快速备份

```bash
docker compose stop
mkdir -p backups
umask 077
FILES=(data modules logs)
[[ -f .env ]] && FILES+=(.env)
tar -czf "backups/checkin-$(date +%Y%m%d-%H%M%S).tar.gz" "${FILES[@]}"
docker compose start
```

`data/`（包含数据库与 `.secret_key`）、`modules/` 与 `.env` 是最关键的内容。
升级前请务必先备份，并保留一份升级前的代码 / commit。

### 升级

```bash
# 先备份！
git pull --ff-only
docker compose build
docker compose up -d
```

数据库使用 `create_all` 自动建表，并在启动时执行 SQLite 前向迁移，为旧库补充随机调度、
多账号与推送字段、把简单旧 Cron 转换为默认时间窗。迁移是幂等的，不会删除旧表或旧日志。
升级前仍强烈建议备份 `data/`、`.env` 与自定义 `modules/`；如果升级失败，请恢复备份。

---

## 安全说明

- 平台使用 HttpOnly Cookie 会话与 CSRF Header 校验；密码使用 PBKDF2-HMAC-SHA256 加盐存储。
- 模块参数使用 AES-256-GCM v2 加密，AAD 绑定用户、模块与账号；旧 Fernet 密文自动升级。
- 所有管理接口均需要登录；公开访问的只有 `/api/health`、`/docs` 和 OpenAPI 描述。
  未登录访问 `/api/modules/*`、`/api/dashboard/*`、`/api/push/*`、`/api/logs/*` 均返回 401。
- 未登录登录页不渲染任何模块名称、时间窗、账号数量或 `schedule-preview` 预览；
  受保护路由统一跳转登录页，模块/推送/日志接口在未认证时返回 401。
- 登录失败使用统一文案并执行一次占位密码校验，降低用户名枚举风险；修改用户名/密码需验证当前密码，
  并带进程内并发锁与失败限流。
- 全局推送凭据同样使用 `SECRET_KEY` 派生密钥加密；钉钉/飞书 Webhook 仅允许官方 HTTPS 域名，
  防止服务端被利用请求任意地址。
- 内网 HTTP 部署必须限制来源 IP；HTTPS 可选，但启用后必须设置 `COOKIE_SECURE=true`。
- 留空 `ADMIN_PASS` 时首次启动生成随机密码并强制改密；显式指定 `ADMIN_PASS` 时不强制，请立即自行修改为强密码。
- 模块图标本地读取受模块目录沙箱、真实路径/软链接校验、ICO Magic Bytes、64KB 与 1024×1024 限制保护；Base64 仅接受图片 MIME 白名单。
- 模块是会以服务进程权限执行的 Python 代码，**只安装可信模块**。平台不会在沙箱中隔离模块。
- 不要将平台直接暴露在公网；如需公网访问，建议增加访问限制、IP 白名单或 VPN。
- 容器当前以 root 运行以兼容宿主机绑定目录权限；`no-new-privileges` 已默认启用；如需更高隔离，可自行创建非 root 用户并调整 volume 权限。
- 完整内网安全边界与检查清单见 [内网部署安全指南](docs/PRODUCTION_SECURITY.md)。

---

## 已知限制

- **单实例设计**：APScheduler、实时日志 Hub 都在进程内。不要启动多个副本共享同一个 SQLite 数据库。
- **只支持单管理员**：适合个人 / 家庭使用；多用户与权限体系尚未实现。
- **模块在应用进程内运行**：第三方代码可以访问平台环境，无法做到强隔离。若需要隔离，可将模块改为子进程或容器执行。
- **同步模块无法被强制终止**：推荐使用 `async def run`。同步函数超时后线程可能继续运行。
- **数据库迁移有限**：内置 SQLite 前向迁移，可补充旧库的新字段并从旧 Cron 推导时间窗；
  但仍建议跨版本升级前备份。其他数据库方言需要自行迁移。
- **SQLite**：适合单机轻量场景。若需要并发更高的部署，替换为 PostgreSQL 需额外安装异步驱动并自行验证。
- **日志保留在内存中的缓冲区**：活跃执行流依赖当前进程；服务重启后，运行中的执行会被标记为中断。

---

## 常见问题

**Q：宿主机 5000 端口已被占用（macOS 的「隔空播放接收器」常用此端口）？**

在 `.env` 中设置 `APP_PORT=5001`，然后执行 `docker compose up -d`，改用
<http://localhost:5001> 访问。

**Q：启动后访问 5000 端口是 JSON 提示「尚未找到前端构建产物」？**

说明当前运行的是源码模式且 `frontend/dist` 不存在。请执行 `cd frontend && npm run build`，
或直接使用 `docker compose up -d --build`。

**Q：模块开关打不开？**

启用的前提是模块加载正常且必填参数已填写。页面会给出具体缺失项。先保存配置，再打开开关。

**Q：修改时间窗后何时生效？**

点击「保存配置」后立即取消旧计划并重新生成本期随机时间，无需重启。页面「本次执行时间」
会同步刷新。若只修改账号或推送开关，原有计划保持不变。

**Q：为什么没有在非执行日执行？**

设计如此：每周任务只在选定的星期几、每月任务只在选定的日期执行。错过本期会标记为
「已错过」，不会在其他日期补跑。每年 2 月 29 日会自动跳到下一个闰年。

**Q：多账号执行为什么会很久？**

默认账号间隔 120–300 秒，多个账号总耗时可能超过 5 分钟。这是为了避免触发平台风控。
测试时可把 `ACCOUNT_INTERVAL_MIN_SECONDS` / `ACCOUNT_INTERVAL_MAX_SECONDS` 设为 `1`。

**Q：如何配置推送？**

登录后进入「用户设置 → 全局推送通知」，选择渠道、填写凭据、保存并发测试。
然后到每个模块配置页打开「启用推送」开关。

**Q：日志里没有输出？**

模块可能没有 `print`，或输出为空。执行记录仍会保存状态与结果。若刚启动任务，
稍等片刻让日志流连接完成。

**Q：ZIP 上传失败？**

检查是否包含 `config.json` 与 `main.py`，是否只有一个模块，是否超过大小限制，
以及 `config.json` 是否合法。平台会给出具体错误。

**Q：参数解密失败？**

`SECRET_KEY` 与保存参数时不一致。恢复原密钥，或重新填写每个模块的参数并保存。
详见 [关于 SECRET_KEY](#关于-secret_key)。

**Q：示例模块会访问真实网站吗？**

不会。两个示例均为本地模拟，可安全运行。

**Q：如何修改管理员密码？**

登录后点击右上角头像 →「用户设置」。忘记密码时可备份后删除 `data/checkin.db`
重新初始化（会丢失所有模块配置与日志），或使用 SQLite 手动更新密码哈希。

**Q：如何添加模块依赖？**

将依赖写入 `backend/requirements.txt`，然后 `docker compose build --no-cache && docker compose up -d`。

---

## 更新日志

### v1.0.5

- 新增模块图标系统：Emoji、本地 ICO、Base64 Data URI、HTTPS URL。
- 本地 ICO 使用 Pillow 转 RGBA PNG，完整保留 Alpha 透明通道。
- 新增图标安全沙箱：路径遍历/绝对路径拦截、真实路径前缀校验、软链接逃逸阻断、ICO Magic Bytes、64KB/1024×1024 限制。
- Base64 图标增加 MIME 白名单与前后端双重正则校验，失败统一降级为 ⚠️。
- 新增 `ModuleIcon.vue`、图标 URL 安全构造函数、`scripts/check_icon_alpha.py` 诊断工具。
- 数据库新增 `icon_source` / `icon_data` 字段，SQLite/PostgreSQL 启动迁移。
- 测试集扩展至 84 个安全与功能用例，前端生产构建通过。

### v1.0.2

- 安全基础、环形日志与统一推送重构；详见历史发布说明。

## API 一览

FastAPI 自动生成的交互式文档：**`/docs`**

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/auth/login` | 登录并设置 Cookie 会话 |
| `GET` | `/api/auth/me` | 当前用户 |
| `PUT` | `/api/auth/username` | 修改用户名（验证当前密码） |
| `POST` | `/api/auth/change-password` | 修改密码 |
| `GET` | `/api/push/config` | 读取全局推送配置 |
| `PUT` | `/api/push/config` | 保存全局推送配置 |
| `POST` | `/api/push/test` | 发送推送测试消息 |
| `GET` | `/api/dashboard` | 仪表盘统计与最近执行 |
| `GET` | `/api/modules` | 模块列表 |
| `GET` | `/api/modules/{id}` | 模块详情与解密参数 |
| `PUT` | `/api/modules/{id}` | 保存账号 / 参数 / 时间窗 / 周期 / 子选项 / 推送开关 |
| `PATCH` | `/api/modules/{id}/enabled` | 独立开关 |
| `POST` | `/api/modules/schedule/preview` | 预览周期子选项与下一次执行日期（需登录） |
| `POST` | `/api/modules/{id}/schedule/regenerate` | 手动重新生成本期随机时间 |
| `POST` | `/api/modules/{id}/run` | 立即执行 |
| `DELETE` | `/api/modules/{id}` | 删除模块与目录 |
| `POST` | `/api/modules/scan` | 扫描模块目录 |
| `POST` | `/api/modules/upload` | 上传 ZIP 模块 |
| `GET` | `/api/logs` | 分页查询执行记录 |
| `GET` | `/api/logs/{id}` | 执行详情与输出 |
| `GET` | `/api/logs/{id}/stream` | SSE 实时日志流 |
| `DELETE` | `/api/logs` | 清空执行记录（可按模块） |
| `GET` | `/api/health` | 健康检查（无需登录） |
| `GET` | `/api/meta` | 系统元信息（周期选项、账号间隔等） |

---

## 技术栈

- **后端**：Python 3.11、FastAPI、SQLAlchemy 2（async）、SQLite、APScheduler 3、itsdangerous、cryptography、Pillow、pathlib
- **前端**：Vue 3、Vite 6、Element Plus、Pinia、Vue Router、Axios、Day.js
- **部署**：多阶段 Dockerfile、Docker Compose、持久化 volumes、容器健康检查

---

## 致谢

示例模块仅用于演示平台能力，不包含任何真实平台接口。
请在遵守目标平台服务条款的前提下开发自己的签到模块。
