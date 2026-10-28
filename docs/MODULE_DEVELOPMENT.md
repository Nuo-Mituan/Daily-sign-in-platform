# 模块开发指南

本指南适用于签到云台 **1.0.5+**。模块仍然是可热插拔目录，但调度方式已从固定 Cron
升级为「按周期随机生成执行时间」，并支持多账号串行、统一推送、模块物理目录映射与
多源模块图标。当前模块契约以本文档和「模块开发指南」页面为准。

> 重要：模块代码**不需要**处理账号列表、随机时间、账号间隔或推送。平台会为多账号模块
> 的每个账号分别调用一次 `run(params)`，然后负责汇总、日志和通知。

---

## 1. 平台与模块的职责边界

| 能力 | 负责方 | 模块需要做什么 |
| --- | --- | --- |
| 账号列表、增删、拖拽排序 | 平台网页端 | 在 `config.json` 声明 `multi_account: true` 和账号级参数 |
| 账号串行执行、2–5 分钟随机间隔 | 平台执行器 | 只实现「一个账号的一次签到」 |
| 每日 / 每周 / 每月等周期 | 平台调度器 | 提供默认时间窗与周期 |
| 执行日 00:00 生成随机时间 | 平台调度器 | 无 |
| 整点补偿、时间窗中点兜底 | 平台调度器 | 无 |
| Bark / Server酱 / PushPlus / 钉钉 / 飞书 | 平台推送服务 | 无；不要自己实现推送 |
| 成功 / 失败 / 部分失败 / 随机失败通知 | 平台推送服务 | 返回准确的 `success` 与 `message` |
| 账号标识脱敏、参数加密、执行日志 | 平台 | 不要在日志打印敏感明文 |

模块开发者只需要保证：

1. `config.json` 合法；
2. `main.py` 暴露 `async def run(params) -> dict`；
3. 返回 `{"success": bool, "message": str, ...}`；
4. 不依赖模块被调用的次数或顺序；
5. 不把完整 Cookie / Token / 密码写入日志。

---

## 2. 目录结构与加载生命周期

```text
modules/
└── my_checkin/
    ├── config.json          # 必需：模块元信息与参数定义
    ├── main.py              # 必需：入口 run(params)
    ├── helpers.py           # 可选：模块内辅助文件
    └── data/                # 可选：模块自己的只读资源（不要写运行时状态）
```

加载流程：

1. 启动时或点击「扫描目录」后，平台读取每个目录的 `config.json`；
2. 校验元信息、默认时间窗、参数定义，并同步到数据库；
3. 新模块默认**禁用**，用户填写账号后手动启用；
4. 启用时会根据时间窗与周期生成本期随机执行时间；
5. 执行时按需重新导入 `main.py`，因此修改代码后下一次执行立即生效；
6. 删除模块时默认同时删除目录，也可以只删数据库记录（保留文件）。

### 2.1 API key、物理目录与 legacy_key

模块有两个不同的身份：

| 名称 | 所在位置 | 用途 |
| --- | --- | --- |
| `key` | 数据库 / API / 执行日志 | 稳定 API 标识，对外 URL、账号配置与日志目录都按它索引。 |
| `directory_name` | `config.json` / `modules/` | 真实物理目录名；未声明时回退为 `key`，便于目录名与 API key 独立演进。 |
| `legacy_key` | `config.json` | 目录改名时显式声明要保留的旧 API key。 |

规则：

- `key` 与 `directory_name` 都必须匹配 `[A-Za-z0-9][A-Za-z0-9_-]{0,79}`，
  最长 80 字符；
- `directory_name` 为空或省略时，平台读取 `modules/<key>/`；
- 声明 `directory_name` 时，它**必须与磁盘上的实际目录名一致**；平台按它解析图标、
  执行和删除路径，不会自动重命名目录；
- 修改物理目录名后，在网页端重新「扫描目录」即可同步数据库；
- 希望保留原 API key 时，`config.json` 必须同时声明 `legacy_key`；
- `legacy_key` 只会在旧 key 对应目录已不存在、且旧记录未绑定其它目录时生效，
  防止两个同名模块串用账号配置；
- `legacy_key` 同样必须匹配 `[A-Za-z0-9][A-Za-z0-9_-]{0,79}`；
- 若两个模块声明同一个物理目录，扫描/上传会被拒绝（数据库唯一索引与冲突检查）；
- 不要仅凭显示名称 `name` 判断模块身份。

模块列表/详情接口额外返回：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `directory_name` | string / null | 数据库保存的物理目录名。 |
| `legacy_key` | string / null | 目录改名时显式保留的旧 API key。 |
| `physical_directory` | string | 实际读取的目录：`directory_name or key`。 |
| `migration_status` | string | `ok`：映射存在、目录存在且与 key 一致；`needs_legacy_key`：旧记录尚未写入 `directory_name`；`directory_mismatch`：映射与 key 不同或目录不存在。 |

> 图标、执行加载、ZIP 覆盖与删除都使用 `physical_directory`；API 调用仍使用 `key`。

目录改名并保留旧 API key 的示例：

```json
{
  "name": "Acme 签到",
  "directory_name": "acme_checkin_v2",
  "legacy_key": "acme_checkin"
}
```

只有当旧记录仍使用 `legacy_key`、且旧目录已不存在时，平台才会复用旧记录；否则会作为
新模块处理并参与目录唯一性冲突检查。

---

## 3. `config.json`

### 3.1 完整示例（多账号）

```json
{
  "name": "Acme 签到",
  "description": "自动完成 Acme 每日签到",
  "author": "your-name",
  "directory_name": "acme_checkin",
  "version": "2.0.0",
  "icon": "🛰️",
  "default_start_time": "09:00",
  "default_end_time": "11:00",
  "default_repeat_cycle": "daily",
  "default_repeat_sub_value": "",
  "multi_account": true,
  "params": [
    {
      "key": "account",
      "label": "账号",
      "type": "text",
      "required": true,
      "account_label": true,
      "placeholder": "账号 / 邮箱 / 手机号"
    },
    {
      "key": "password",
      "label": "密码",
      "type": "password",
      "required": true
    },
    {
      "key": "cookie",
      "label": "Cookie",
      "type": "textarea",
      "required": false,
      "rows": 4
    },
    {
      "key": "verbose",
      "label": "详细日志",
      "type": "switch",
      "default": true
    }
  ]
}
```

### 3.2 顶层字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `name` | string | 是 | — | 模块显示名称，最长 120 字符。 |
| `description` | string | 否 | `""` | 模块描述，最长 2000 字符。 |
| `author` | string | 否 | `""` | 作者 / 维护者。 |
| `version` | string | 否 | `"1.0.0"` | 模块版本。 |
| `icon` | string | 否 | `"🧩"` | Emoji、本地 PNG/JPG/WebP/ICO、Base64 Data URI 或 HTTPS URL。 |
| `directory_name` | string | 否 | 回退 `key` | 物理模块目录名；`[A-Za-z0-9][A-Za-z0-9_-]{0,79}`。 |
| `legacy_key` | string | 否 | — | 目录改名时显式保留的旧 API key。 |
| `icon_source` | string | 否 | `"url"` | **旧兼容字段**：`url` / `base64` / `local`。 |
| `icon_data` | string | 否 | — | **旧兼容字段**：旧版 base64 图标数据。 |
| `default_start_time` | string | 否 | 旧 Cron 推导或 `08:00` | 默认开始时间，24 小时制 `HH:mm`。 |
| `default_end_time` | string | 否 | 旧 Cron 推导或 `10:00` | 默认结束时间，必须晚于开始时间。 |
| `default_repeat_cycle` | string | 否 | `"daily"` | `daily` / `weekly` / `monthly_15` / `monthly` / `yearly`。 |
| `default_repeat_sub_value` | string | 否 | 见下 | 子选项默认值：每周 `1`-`7`；每月 `1`-`28`；每年 `M-D`。 |
| `multi_account` | boolean | 否 | `false` | 是否启用多账号模式。 |
| `params` | array | 否 | `[]` | 参数定义；多账号模式下每个账号各填一组。 |
| `default_cron` | string | 否 | — | **旧版兼容字段**；新模块不应再使用。 |

### 3.3 旧版 Cron 兼容

升级旧模块时：

- 如果只写了 `default_cron`，平台会尝试从简单的 `分 时 * * *` 推导一个 1 小时时间窗；
- 例如 `30 9 * * *` → 默认 `09:30–10:30`，首次导入时周期为 `daily`；
- 如果无法推导（如 `*/10 * * * *`），使用 `08:00–10:00`；
- 数据库迁移会把旧模块的 `cron` 值转换为 `start_time` / `end_time`；
- **已有用户的调度配置不会被扫描覆盖**。`default_*` 只影响新建模块的初始值。

新模块请直接使用 `default_start_time` / `default_end_time` /
`default_repeat_cycle` / `default_repeat_sub_value`，不要新增 `default_cron`。

### 3.4 周期子选项

`repeat_cycle` 只有 5 个合法值。父周期选择后，网页端会按需显示子下拉框：

| `repeat_cycle` | 显示 | `repeat_sub_value` 格式 | 缺失时默认值 |
| --- | --- | --- | --- |
| `daily` | 每日 | 空字符串 | `""` |
| `weekly` | 每周 + 星期几 | `"1"`-`"7"`（周一=1，周日=7） | `"1"` |
| `monthly_15` | 每月15日 | 空字符串 | `""` |
| `monthly` | 每月 + 日期 | `"1"`-`"28"`（固定上限 28） | `"1"` |
| `yearly` | 每年 + 月-日 | `"M-D"`，例如 `"1-1"`、`"12-31"`、`"2-29"` | `"1-1"` |

说明：

- 每月日期固定上限为 28，避免大小月问题；
- 每年会按所选月份自动限制天数（2 月支持 29 日）；
- 选择 `"2-29"` 时，非闰年没有该日期，平台会自动跳到下一个闰年执行；
- 子选项在数据库中保存为 `repeat_sub_value`，与 `repeat_cycle` 一起校验；
- 旧周期 `half_month` / `quarterly` 会在启动迁移时自动降级为
  `monthly` + `"1"`（每月 1 日），并写入迁移日志。

### 3.5 模块图标

`icon` 支持四种形式；旧字段 `icon_source` / `icon_data` 继续兼容：

| 类型 | 示例 | 说明 |
| --- | --- | --- |
| Emoji / 文本 | `"icon": "🎯"` | 原样渲染，保留 Emoji 底色。 |
| 本地图片 | `"icon": "./favicon.png"` / `.jpg` / `.jpeg` / `.webp` / `.ico` | 读取 `modules/<physical_directory>/` 内的文件；校验魔数后统一转为 RGBA PNG。 |
| Base64 Data URI | `"icon": "data:image/png;base64,..."` | 仅允许 `x-icon` / `png` / `svg+xml`，≤64KB。 |
| HTTPS URL | `"icon": "https://example.com/icon.png"` | 加载失败降级为 `⚠️`。 |

安全约束：

- 本地路径只允许模块物理目录内的相对路径，拒绝 `..`、绝对路径、反斜杠和空字节；
- 使用 `resolve()` 后的真实路径前缀校验，阻断软链接逃逸；
- 本地 PNG / JPEG / WebP / ICO 文件 ≤64KB、解码尺寸 ≤1024×1024；
- 不依赖扩展名或 `Content-Type`：PNG `89 50 4E 47`、JPEG `FF D8 FF`、WebP `RIFF....WEBP`、
  ICO `00 00 01 00`，并通过 Pillow 解码校验；
- 后端使用 Pillow 以 RGBA 打开并转 PNG，保留 Alpha 透明通道；
- 格式非法返回 415，文件超限返回 413；前端提示“图标格式不支持，请上传 PNG / JPG / WebP 格式”。
- 图片加载/解码失败统一降级为 `⚠️`，不抛出未捕获异常。

图标接口：`GET /api/modules/icon?key=<key>`（公开，供 `<img>` 加载）。

---

## 4. 参数定义

`params` 中每一项会渲染成网页表单控件，并且全部使用平台密钥加密保存。

| 字段 | 说明 |
| --- | --- |
| `key` | 参数键名，`params` 字典的 key；只能包含字母、数字、下划线。 |
| `label` | 表单标签。 |
| `type` | `text` / `textarea` / `password` / `select` / `switch` / `number`。 |
| `required` | 是否必填；启用模块与保存时都会校验。 |
| `default` | 默认值。select 的默认值应存在于 options 中。 |
| `placeholder` | 输入框占位提示。 |
| `help` | 控件下方的帮助文字。 |
| `options` | select 专用；支持字符串数组或 `{label, value}` 数组。 |
| `min` / `max` / `step` | number 专用。 |
| `rows` | textarea 专用，2–20。 |
| `account_label` | 多账号模式可选；标记用于日志/推送脱敏展示的账号标识字段。 |
| `sensitive` | 可选；声明为敏感参数。`password` / `cookie` / `token` / `secret` / `key` 等字段也会自动推断。 |

### 4.1 `account_label`

多账号模式下，平台需要知道用哪个参数作为账号标识：

```json
{
  "key": "cookie",
  "label": "Cookie",
  "type": "textarea",
  "account_label": true
}
```

显示优先级：

1. 用户在账号卡片填写的备注名称（如「主账号」）；
2. `account_label: true` 字段脱敏后的值；
3. 常见字段名（`account` / `username` / `email` / `cookie` / `token`）脱敏后的值；
4. 「未提供账号标识」。

脱敏示例：

- `demo@example.com` → `de***@example.com`
- `SESSDATA=abcdefgh123456` → `SESSDATA=abcd***56`
- `abc123` → `ab***`

模块自己打印日志时也应使用脱敏值，或只打印账号序号。

### 4.2 参数加密

- `password` 类型只是输入时隐藏；**所有类型**都会在服务端加密后保存；
- 当前使用 AES-256-GCM v2，密钥由 `SECRET_KEY` 经 HKDF-SHA256 派生，AAD 绑定用户、
  模块与账号序号；旧 Fernet 密文会在读取时透明升级；
- 敏感参数在 API 中默认返回 `abcd****wxyz` 掩码；保存掩码或空值会保留原密文，
  只有显式点击「显示敏感值」并通过当前密码校验才返回明文；
- 多账号模式下，每个账号的 `params` 整体作为一个加密 JSON 数组保存；
- 网页端详情接口会返回解密后（或掩码后）的参数，因此 `/api/modules/*` 必须保持登录鉴权。

---

## 5. 入口函数 `run(params)`

### 5.1 单账号模式

```python
from typing import Any


async def run(params: dict[str, Any]) -> dict[str, Any]:
    account = str(params.get("account") or "").strip()
    if not account:
        return {"success": False, "message": "账号为空"}

    print(f"开始为 {account[:2]}*** 签到")
    # 真实的网络请求逻辑……
    return {
        "success": True,
        "message": "签到成功",
        "points": 10,
    }
```

平台会：

- 为每个启用的模块创建一个执行记录；
- 捕获 `print()`、`logging`、stdout/stderr；
- 使用 `MODULE_TIMEOUT` 做超时控制；
- 将返回值中的 `success`、`message` 和额外字段写入日志与数据库；
- 根据模块推送开关发送通知。

### 5.2 多账号模式

`config.json` 中设置：

```json
{
  "multi_account": true,
  "params": [
    { "key": "cookie", "label": "Cookie", "type": "textarea", "required": true },
    { "key": "target_level", "label": "目标等级", "type": "number", "default": 3 }
  ]
}
```

用户保存的账号列表形如：

```json
[
  {
    "id": "acct-1",
    "label": "主账号",
    "params": { "cookie": "SESSDATA=...", "target_level": 3 }
  },
  {
    "id": "acct-2",
    "label": "",
    "params": { "cookie": "SESSDATA=...", "target_level": 5 }
  }
]
```

平台会按列表顺序：

1. 为账号 1 调用 `run(params_1)`；
2. 等待随机 `ACCOUNT_INTERVAL_MIN_SECONDS`–`ACCOUNT_INTERVAL_MAX_SECONDS`（默认 120–300 秒）；
3. 为账号 2 调用 `run(params_2)`；
4. 汇总状态与消息。

模块侧只接收**一个账号的 params**，不要在模块内循环账号列表。每次调用都会重新导入模块，
不要在模块全局变量里保存「上一个账号」的状态。

### 5.3 返回值约定

必须返回 `dict`，并且包含：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `success` | bool | 该账号是否成功。支持 `true/false` 或 `"true"/"false"`。 |
| `message` | string | 展示在日志和推送中的结果说明。 |
| 其他字段 | any | 可序列化为 JSON 的额外信息，会写入执行日志的「返回数据」。 |

示例：

```python
return {
    "success": True,
    "message": "签到成功，获得 10 积分",
    "points": 10,
    "request_count": 3,
}
```

多账号汇总规则：

- 全部成功 → `success`，消息为「全部 N 个账号签到成功」；
- 全部失败 → `failed`，消息为「全部 N 个账号签到失败」；
- 部分成功 → `failed`，消息为「N 个账号中 X 个成功、Y 个失败」；
- 平台只会发送一条汇总推送，不会为每个账号单独推送。

### 5.4 账号级超时与间隔

- `MODULE_TIMEOUT` 是**每个账号**的超时，不是整个模块的总超时；
- 超时后平台记录该账号失败，继续执行下一个账号（若还有）；
- 多账号总耗时 = 各账号执行时间 + 账号间等待；默认两个账号可能超过 5 分钟；
- 测试环境可设置 `ACCOUNT_INTERVAL_MIN_SECONDS=1` / `ACCOUNT_INTERVAL_MAX_SECONDS=1`；
- 账号间隔只在多账号且不是最后一个账号时等待。

### 5.5 手动执行

「立即执行」不受模块启用状态限制，但仍要求：

- 模块加载正常；
- 单账号参数 / 多账号列表完整；
- 同一模块当前没有其他执行实例。

手动执行与定时执行使用同一套账号串行、日志和推送流程。

---

## 6. 随机时间调度

### 6.1 时间窗

每个模块保存：

- `start_time`：开始时间，`HH:mm`；
- `end_time`：结束时间，`HH:mm`；
- `repeat_cycle`：重复周期，5 个值之一；
- `repeat_sub_value`：周期子选项（周几 / 日期 / 月-日）。

约束：

- 24 小时制，必须补零，例如 `09:00`、`18:30`；
- 开始时间必须严格早于结束时间；
- 时间窗不能跨天；
- 所有时间按服务器 `TIMEZONE`（默认 `Asia/Shanghai`）解释；
- 数据库存储 UTC，界面按业务时区展示。

### 6.2 执行日与子选项

执行只发生在选定的**执行日**，不会在其他日期补跑：

| `repeat_cycle` | 子选项 | 执行日 |
| --- | --- | --- |
| `daily` | 无 | 每天 |
| `weekly` | 星期几（1-7） | 每周选定的星期几 |
| `monthly_15` | 无 | 每月 15 日 |
| `monthly` | 日期（1-28） | 每月选定的日期 |
| `yearly` | 月-日（M-D） | 每年选定的月-日；2-29 仅闰年 |

例如：每周五模块在周五 00:00 生成本周执行时间，在周五的时间窗内执行；周六不会补跑。
如果周五服务停机且错过执行时间，本期会被标记为「已错过」，等待下周五。

每年 `2-29` 在非闰年没有执行日，平台会直接安排到下一个闰年；例如 2025 年启用时，
下一次计划为 2028-02-29。

### 6.3 生成规则

1. 执行日 00:00（业务时区），平台在 `[start_time, end_time]` 内均匀随机选择时间；
2. 生成结果保存到 `module_schedules` 表，每个模块每个周期只有一条；
3. 页面展示「本次执行时间」；
4. 用户可点击「重新生成」手动换一个随机时间；
5. 修改时间窗或周期后，旧计划取消，并立即生成本期新计划；
6. 如果启用模块时已经过了开始时间，只在剩余时间窗内生成；如果已经过了结束时间，
   本期不生成，等待下一个周期。

### 6.4 可靠性机制

- **整点补偿**：每小时整点检查启用模块是否缺少本期随机时间，缺失则重试生成；
- **时间窗中点兜底**：如果到时间窗中点仍未生成成功，自动使用中点时间执行，
  并发送「随机时间生成失败」推送（前提是模块推送开关开启）；
- **服务重启恢复**：启动时把遗留的 `running` 执行记录/计划标记为失败或错过，
  然后为当前周期重新安排；
- **APScheduler 动态任务**：每个模块最多三个一次性任务：
  - `module:<id>:plan`：下个执行日 00:00；
  - `module:<id>:exec`：本期随机执行时间；
  - `module:<id>:fallback`：时间窗中点兜底检查。
  没有每个模块固定 Cron 的任务。

### 6.5 手动重新生成

`POST /api/modules/{id}/schedule/regenerate`

- 仅启用模块可调用；
- 正在执行时返回 409；
- 生成来源标记为 `manual`；
- 返回 `schedule` 与最新 `module`；
- 页面上的「重新生成」按钮会刷新「本次执行时间」。

### 6.6 旧 Cron 迁移

- 旧数据库字段 `cron` / `default_cron` 仍保留用于兼容；
- 启动时自动执行 SQLite 前向迁移，为模块补充新字段；
- 旧 Cron 简单表达式会转换为默认时间窗；
- 旧 `half_month` / `quarterly` 会降级为 `monthly` + `repeat_sub_value="1"`，
  并记录迁移日志；
- 迁移不会删除旧数据，也不会覆盖用户已经合法的 `start_time` / `end_time` /
  `repeat_cycle`；
- 升级前建议先备份 `data/`。

---

## 7. 平台级推送（模块不需要实现）

全局推送在「用户设置 → 全局推送通知」中配置，支持：

| 渠道 | 必填 |
| --- | --- |
| Bark | Device Key |
| Server 酱 | SendKey |
| PushPlus | Token |
| 钉钉机器人 | Webhook；可选加签 Secret |
| 飞书机器人 | Webhook；可选签名 Secret |

推送触发事件：

- 单账号签到成功 / 失败；
- 多账号全部成功 / 全部失败 / 部分失败汇总；
- 随机时间生成失败（时间窗中点兜底时）；
- 用户手动发送的测试消息。

模块页的「启用推送」开关只控制当前模块是否发送；关闭后该模块的所有通知都不会发送。
推送发送失败只记录 warning，不会影响签到结果或执行状态。

可用模板变量：

`{event}`、`{module_name}`、`{module_key}`、`{account}`、`{status}`、
`{result}`、`{duration}`、`{error}`、`{time}`、`{summary}`、`{details}`

模块开发者不应在模块内读取推送 Key、发送 HTTP 推送或依赖第三方 SDK。若业务需要发送
平台不支持的通知，请把需求反馈给平台层，而不是在模块里另建一套凭据。

---

## 8. 日志、异常与状态

平台会捕获：

- `print()` / `sys.stdout` / `sys.stderr`；
- 标准库 `logging`；
- 模块返回值中的额外字段。

建议：

- 只输出必要信息；
- 使用 `logging` 的级别区分正常流程与异常；
- 不要打印完整密码、Cookie、Token、推送 Key；
- 单次执行输出有最大字符限制（`LOG_MAX_CHARS`）；
- 异常时返回 `success: False` 和用户可读的 `message`，不要只抛异常；
- 模块入口内部应兜底捕获可预期异常，避免整个进程被拖垮。

平台状态：

- 单账号：由返回的 `success` 决定 `success` / `failed`；
- 多账号：所有账号成功才 `success`，任一失败即 `failed`；
- 执行中的状态由平台维护；
- 禁用、加载异常、正在执行时会拒绝或跳过执行。

---

## 9. 进阶模板

[`templates/advanced_checkin`](../templates/advanced_checkin/README.md) 是推荐起点：

- `multi_account: true`，账号级参数通过平台渲染；
- Cookie 过期检测、自动重新登录一次；
- 网络错误 / 429 / 5xx 的带抖动退避重试；
- 统一超时、异常分类；
- 模拟模式（`httpx.MockTransport`）不访问网络；
- **不包含模块级推送代码**；推送全部由平台负责。

安装：

```bash
cp -R templates/advanced_checkin modules/advanced_checkin
```

然后在网页端扫描目录、添加账号、设置时间窗与周期并启用。

---

## 10. 打包、上传与更新

### 10.1 ZIP 结构

ZIP 根目录应包含 `config.json` 和 `main.py`，不要多包一层同名目录：

```text
my_checkin.zip
├── config.json
└── main.py
```

上传后可选择覆盖同名模块。覆盖时：

- 代码文件更新；
- 用户已保存的账号、参数、时间窗与启用状态保留；
- 新模块的 `default_*` 只作为初始值，不会覆盖用户已有调度。

### 10.2 第三方依赖

模块不应在运行时 `pip install`。将依赖加入项目根目录的
`backend/requirements.txt`，重新构建镜像：

```bash
docker compose build --no-cache
docker compose up -d
```

### 10.3 删除模块

删除默认同时删除目录。若只想移除数据库记录、保留文件，可在请求中设置
`delete_files=false`。

---

## 11. 常见问题

**Q：保存时间窗后没有「本次执行时间」？**

- 只有启用模块才会生成；
- 如果今天不是该周期的执行日，会在下一个执行日生成；
- 如果今天已过结束时间，本期不会生成；
- 检查 `start_time` 是否早于 `end_time`，且格式为 `HH:mm`。

**Q：为什么周二没有补跑每周任务？**

设计如此：每周任务只在周一执行。错过后本期标记为「已错过」，下周一重新生成。

**Q：多账号为什么没有按预期等待？**

检查 `ACCOUNT_INTERVAL_MIN_SECONDS` / `ACCOUNT_INTERVAL_MAX_SECONDS`。测试环境可设为
`1`；生产默认 120–300 秒。等待只在两个账号之间发生，最后一个账号后不等待。

**Q：多账号部分成功为什么整体是失败？**

为了在仪表盘和推送中提醒至少有一个账号异常，整体状态为 `failed`，消息中会写明
「N 个账号中 X 个成功、Y 个失败」。推送事件为 `partial_failure`。

**Q：如何让模块发送推送？**

不需要。配置全局渠道，打开模块的「启用推送」开关即可。模块只需要返回准确的
`success` / `message`。

**Q：旧模块还能用吗？**

可以。旧 `default_cron` 会被推导为时间窗；数据库会自动迁移。建议逐步改为新的
`default_start_time` / `default_end_time` / `default_repeat_cycle` /
`default_repeat_sub_value` 字段。

**Q：账号参数解密失败？**

`SECRET_KEY` 变化了。恢复原密钥，或在网页端重新填写账号参数并保存。

**Q：执行超时了但线程还在跑？**

同步模块在超时后底层线程可能仍会运行到结束。优先使用 `async def run()` 和异步
HTTP 客户端；同步阻塞代码应自行设置网络超时。

**Q：修改账号顺序会影响历史执行吗？**

不会。历史日志保存的是当时的展示结果；新顺序只影响后续执行。账号 ID 在保存后保持稳定。

---

## 12. API 速查

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/auth/login` | 登录 |
| `GET` | `/api/auth/me` | 当前用户 |
| `PUT` | `/api/auth/username` | 修改用户名（需当前密码） |
| `POST` | `/api/auth/change-password` | 修改密码 |
| `GET` | `/api/modules` | 模块列表；含 `directory_name` / `legacy_key` / `physical_directory` / `migration_status` |
| `GET` | `/api/modules/{id}` | 模块详情、参数与账号（敏感值默认掩码） |
| `GET` | `/api/modules/icon` | 模块图标（公开，按 `directory_name` 读取） |
| `PUT` | `/api/modules/{id}` | 保存账号 / 参数 / 时间窗 / 周期 / 推送开关 |
| `PATCH` | `/api/modules/{id}/enabled` | 启用 / 禁用 |
| `POST` | `/api/modules/{id}/schedule/regenerate` | 手动重新生成本期随机时间 |
| `POST` | `/api/modules/{id}/run` | 立即执行 |
| `POST` | `/api/modules/scan` | 扫描目录 |
| `POST` | `/api/modules/upload` | 上传 ZIP |
| `DELETE` | `/api/modules/{id}` | 删除模块 |
| `GET` | `/api/push/config` | 读取全局推送配置 |
| `PUT` | `/api/push/config` | 保存全局推送配置 |
| `POST` | `/api/push/test` | 发送测试消息 |
| `GET` | `/api/logs` | 执行记录分页 |
| `GET` | `/api/logs/{id}` | 执行详情 |
| `GET` | `/api/logs/{id}/stream` | SSE 实时日志 |
| `GET` | `/api/system/metrics` | 诊断指标：环形日志、SSE、限流器、连接池与锁竞争（需登录） |
| `GET` | `/metrics` | Prometheus 文本指标（公开，DB 日志限流器压力） |
| `GET` | `/api/health` | 健康检查（公开） |
| `GET` | `/api/meta` | 系统元信息（需登录） |

除 `/api/health`、`/api/auth/login`、`/api/modules/icon`、`/metrics` 外，其他 API 均要求
Cookie 会话登录；写请求还需携带 `X-CSRF-Token`。不再使用 JWT/Bearer。

---

## 13. 测试与验证

### 13.1 单元测试

```bash
cd daily-check-in-platform
python -m pytest backend/tests -q                 # 默认快速测试：221 passed
python -m pytest backend/tests -m property -q      # PBT 契约测试：5 passed
python -m pytest backend/tests/benchmark -m benchmark --benchmark-only  # 3 passed
```

测试覆盖：

- 密码哈希、参数加密（含账号数组）；
- 周期执行日、时间窗、随机时间、五种周期与子选项；
- 旧 Cron 兼容推导；
- 旧 `half_month` / `quarterly` 周期迁移；
- 账号规范化、脱敏与数量上限；
- 随机时间 APScheduler 一次性任务与兜底任务；
- 推送渠道校验、模板渲染、签名；
- 完整 API 流程（登录、幂等用户名、随机调度、多账号串行、部分失败、推送配置）；
- 进阶模板的模拟登录与配置校验；
- 模块物理目录映射、`legacy_key` 冲突与扫描/上传边界；
- 图标路径沙箱、ICO/PNG/SVG 校验与降级；
- 限流器/连接池/关闭状态机的 Property-Based Testing 与性能基准。

### 13.2 API 验证

```bash
# 本地（使用可丢弃的数据库）
VERIFY_BASE_URL=http://127.0.0.1:5000/api \
ADMIN_USER=admin ADMIN_PASS=admin123 \
ACCOUNT_INTERVAL_MIN_SECONDS=1 ACCOUNT_INTERVAL_MAX_SECONDS=1 \
python3 scripts/verify_api.py
```

或使用 `./verify_docker.sh` 完成隔离的 Docker 构建 + 启动 + API 验证。

验证脚本会修改运行数据，**不要对生产数据库执行**。

---

## 14. 安全实践

- 只安装可信来源的模块；模块代码会以服务进程权限运行；
- 不要在日志、URL、异常信息中暴露密码 / Cookie / Token / 推送 Key；
- 不要绕过平台的参数存储自行落盘明文凭据；
- 不要实现模块级推送，避免绕过全局凭据与安全审计；
- 真实签到请遵守目标平台的服务条款；
- 生产环境使用 HTTPS、反向代理、强随机 `SECRET_KEY` 和强管理员密码；
- 定期备份 `data/`；更换 `SECRET_KEY` 会导致已保存参数无法解密。

---

## 15. 参考

- 平台安全清单：[PRODUCTION_SECURITY.md](PRODUCTION_SECURITY.md)
- 备份与迁移：[BACKUP_AND_MIGRATION.md](BACKUP_AND_MIGRATION.md)
- 进阶模板：[templates/advanced_checkin](../templates/advanced_checkin/README.md)
- 示例模块：[modules/demo_checkin](../modules/demo_checkin)（单账号）、
  [modules/moyu_energy](../modules/moyu_energy)（多账号）

---

## Appendix A：v1.0.5 补充 — 敏感参数与统一环形日志

> 以下内容是 1.0.x 已有能力的补充说明；`sensitive` 字段已并入第 4 节参数定义。

### A.1 `sensitive` 参数标记

`config.json` 的参数项可以显式声明：

```json
{
  "key": "password",
  "label": "密码",
  "type": "password",
  "required": true,
  "sensitive": true
}
```

平台还会对以下字段自动推断为敏感：

- `type: "password"`；
- `password` / `passwd` / `pwd` / `cookie` / `token` / `secret` / `key`；
- 以 `_token` / `_secret` / `_key` 结尾的字段。

敏感参数：

- 使用 AES-256-GCM v2 加密，AAD 绑定用户、模块与账号序号；
- 默认 API 返回 `abcd****wxyz` 形式掩码；
- 保存掩码或空值会保留原密文；
- 只有显式点击「显示敏感值」并通过当前密码校验时才返回明文；
- 不得在 `print`、`logging`、异常消息或返回值中输出完整明文。

### A.2 模块返回值与推送数据

```python
async def run(params: dict) -> dict:
    return {
        "success": True,
        "message": "签到成功：+10 积分",
        # 可选，平台会作为日志和推送的附加上下文
        "details": "累计签到 30 天",
    }
```

- `success`：必需，布尔值；
- `message`：必需，简明结果；
- `details`：可选，会进入执行输出和日报摘要；
- 平台负责独立推送、统一批次、重试、脱敏和审计，模块**不得**自行发送推送；
- 多账号模式下平台逐个账号调用 `run`，模块只处理单个账号。

### A.3 统一环形日志写入规范

模块**禁止**自行创建日志文件、写 SQLite 日志表或使用 `logging.FileHandler`。所有输出必须通过：

```python
print("普通输出")
logging.getLogger("modules.my_module").info("结构化输出")
```

平台 `OutputCapture` / stdout 路由会把内容写入统一 `ring_logs`：

- `scope_type=module`；
- `scope_key=<module_key>`；
- `category=execution`；
- `ref_type=execution`、`ref_id=<执行记录 ID>`；
- 每条携带单调 `seq`，实时 SSE 与断点续读都按 `seq`。

规则：

1. 每个模块独立配额，不得假设自己的日志会无限保留；
2. 读取按 `seq`，不要依赖文件行序；
3. 敏感值必须脱敏；平台会做正则和上下文值替换，但模块仍应避免输出明文；
4. 历史执行正文从环形日志读取，`execution_logs.output` 对新执行不再写入。
