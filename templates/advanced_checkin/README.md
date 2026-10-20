# Acme 签到 · 进阶多账号模板

这是一个**生产场景导向**的单账号入口模板。平台会把多账号列表拆成多次串行调用，
并在账号之间自动等待 2–5 分钟；模块只需要专注一次签到的业务逻辑。

模板演示了：

- 多账号模式下，`config.json` 的 `params` 会为每个账号独立渲染与加密保存
- Cookie / Token 过期检测
- 使用账号密码自动重新登录一次
- 网络错误、HTTP 429、5xx 的带抖动指数退避重试
- 统一超时与异常分类
- 日志中不打印密码 / Cookie / Token
- 默认模拟模式，无网络也能完整跑通流程

> 本模板位于 `templates/`，不会被平台自动扫描。请阅读「安装」后再启用。

## 平台已经替你做了什么

| 能力 | 由谁负责 |
| --- | --- |
| 账号列表、增删、拖拽排序 | 平台网页端 |
| 账号串行执行、2–5 分钟随机间隔 | 平台执行器 |
| 每日 / 每周 / 每月15日 / 每月 / 每年 + 子选项 | 平台随机调度器 |
| 执行日 00:00 生成随机执行时间 | 平台调度器 |
| 失败整点重试、时间窗中点兜底 | 平台调度器 |
| Bark / Server酱 / PushPlus / 钉钉 / 飞书 | 平台全局推送 |
| 成功 / 失败 / 部分失败 / 随机生成失败通知 | 平台推送服务 |
| 账号标识脱敏、参数加密、执行日志 | 平台 |

因此模块代码**不要遍历账号列表，也不要实现推送**。平台会为每个账号分别调用
一次 `run(params)`，再汇总所有账号的结果。

## 文件说明

```
advanced_checkin/
├── config.json   # 7 个账号级参数，multi_account=true 与随机时间默认值
├── main.py       # 单账号 HTTP 会话、过期检测、自动登录、重试
└── README.md     # 当前文档
```

## 安装与安全试运行

1. 将目录复制到项目的 `modules/` 下（或压缩成 ZIP 上传）：

   ```bash
   cp -R templates/advanced_checkin modules/advanced_checkin
   ```

2. 在网页端「签到模块」点击「扫描目录」。
3. 打开「Acme 签到（进阶多账号模板）」，在账号列表中添加 1–2 个账号。
   可以随意填写账号、密码或 Cookie——模拟模式不会访问网络。
4. 设置开始/结束时间窗与重复周期，打开模块推送开关（可选），保存并启用。
5. 点击「立即执行」。多账号会依次执行，日志中以
   `[账号 1/2]`、`[账号 2/2]` 分隔；完整账号标识会自动脱敏。
6. 返回数据中可以看到 `auth_refreshed: true`、`request_count: 3`、
   `points: 12` 等字段。

模拟模式使用 `httpx.MockTransport`，**不会访问网络**。

## 接入真实平台

本模板的接口路径、登录 payload 和响应字段是示例值。接入时请逐项修改：

| 位置 | 需要修改的内容 |
| --- | --- |
| `main.py` 顶部 | `DEFAULT_API_BASE`、`CHECKIN_PATH`、`LOGIN_PATH` |
| `AcmeClient.login()` | 登录请求字段（例如 `username/password` 改成 `account/passwd`） |
| `AcmeClient.login()` | Token 字段名、Cookie 名称、`Set-Cookie` 处理 |
| `AcmeClient.checkin()` | 签到请求 body/header、成功码映射、积分字段 |
| `AUTH_ERROR_CODES` | 目标平台表示登录失效的业务码 |
| `SUCCESS_CODES` | 目标平台表示成功的业务码 |
| `config.json` | 参数 label、默认 API 地址、参数说明 |
| `default_*` 字段 | 模块首次导入时的默认时间窗与周期 |

例如，如果目标接口返回：

```json
{"ret": 0, "msg": "签到成功", "data": {"point": 10}}
```

则把 `SUCCESS_CODES` 改成 `{0, "0"}`，把积分读取改为 `payload.get("point")`。

### 真实的请求链路（单个账号）

```
读取当前账号的 params
  ↓
创建 httpx.AsyncClient（Cookie / Authorization）
  ↓
POST 签到接口
  ├─ 200 + 成功码 → 成功
  ├─ 401/403 或业务失效码 → 自动登录 → 重试签到（仅一次）
  ├─ 429 / 5xx / 网络错误 → 指数退避重试（最多 max_retries 次）
  └─ 其它 4xx / 业务失败 → 返回清晰的失败 message
  ↓
返回 { "success", "message", "points", "auth_refreshed", ... }
  ↓
平台汇总多个账号并按模块推送开关统一通知
```

## config.json 说明

```json
{
  "default_start_time": "09:00",
  "default_end_time": "11:00",
  "default_repeat_cycle": "daily",
  "default_repeat_sub_value": "",
  "multi_account": true,
  "params": [
    { "key": "account", "type": "text", "account_label": true },
    { "key": "cookie", "type": "textarea" }
  ]
}
```

- `multi_account: true`：网页端显示账号卡片列表，每个账号各填一组 `params`。
- `account_label: true`：指定哪个字段用于日志与推送中的自动脱敏标识。
  - 若账号填写了备注名称，则优先显示备注；
  - 否则显示该字段脱敏后的值；
  - 两个都为空时显示账号序号。
- `default_start_time` / `default_end_time`：24 小时制 `HH:mm`，开始必须早于结束，
  且不能跨天。
- `default_repeat_cycle`：`daily` / `weekly` / `monthly_15` / `monthly` / `yearly`。
- `default_repeat_sub_value`：子选项默认值：
  - 每周：`"1"`-`"7"`（周一=1）；
  - 每月：`"1"`-`"28"`；
  - 每年：`"M-D"`，例如 `"1-1"`、`"2-29"`。
- 用户保存后，网页端值优先；平台不会在每次扫描时覆盖用户时间窗。

## 参数说明

| 参数 | 用途 |
| --- | --- |
| `api_base` | 真实模式的目标 API 根地址，必须以 `http://` 或 `https://` 开头。 |
| `account` | 账号标识；用于自动登录，也会作为脱敏后的日志标识。 |
| `password` | Cookie 失效时用于自动重新登录。 |
| `cookie` | 可选的已有登录态；存在时优先复用。 |
| `max_retries` | 单个请求的最大尝试次数（1–5）。 |
| `request_timeout` | 单次 HTTP 请求超时（5–60 秒）。 |
| `simulate` | 默认开启。使用 MockTransport，不访问网络。 |

多账号模式下这些参数会**按账号分别加密保存**；修改账号数量或顺序不会影响其他账号。

## 推送说明

平台级推送在「用户设置 → 全局推送通知」中配置，支持 Bark、Server酱、PushPlus、
钉钉和飞书。模块页的「启用推送」开关只控制当前模块是否发送，不需要在模块代码中
填写任何 Key。

可用的模板变量包括：

`{event}`、`{module_name}`、`{module_key}`、`{account}`、`{status}`、
`{result}`、`{duration}`、`{error}`、`{time}`、`{summary}`、`{details}`

平台会自动推送：

- 单账号成功 / 失败；
- 多账号全部成功 / 全部失败 / 部分失败汇总；
- 随机时间生成失败（时间窗中点兜底时）。

## 关于 Cookie 自动刷新

当前实现**只在本次执行内刷新会话**：如果首次签到失败，会自动登录，然后用新 Cookie /
Token 再签到一次。刷新后的 Cookie 不会回写到网页端参数，也不会跨执行持久化。

这是有意为之：

- 避免把刷新后的凭据写入未加密的状态文件；
- 每次执行使用网页端保存的加密参数作为初始凭据；
- 大多数平台允许一次新的登录，或可以使用长期有效的 Cookie。

如果你的目标平台**每次登录都会使旧会话失效**，可以在模块目录外增加一个受保护的本地
状态缓存（例如 `$DATA_DIR/module_state/advanced_checkin.json`，权限 `0600`）来保存最新
Cookie。实现时必须注意：

- 状态文件与数据库中的参数要保持一致；
- Web 端更新参数后要能覆盖旧缓存；
- 状态文件不能进入 Git / 日志 / 备份的公开位置；
- 不要把状态文件内容打印到日志。

## 测试

在项目根目录使用平台相同的加载方式（包 + 相对导入）：

```bash
python - <<'PY'
import asyncio
import importlib.util
import sys

path = "templates/advanced_checkin/main.py"
pkg = "_advanced_demo"
spec = importlib.util.spec_from_file_location(
    pkg, path, submodule_search_locations=["templates/advanced_checkin"]
)
mod = importlib.util.module_from_spec(spec)
sys.modules[pkg] = mod
spec.loader.exec_module(mod)

print(asyncio.run(mod.run({
    "simulate": True,
    "account": "demo@example.com",
    "password": "not-a-real-password",
    "cookie": "session=expired",
    "max_retries": 2,
    "request_timeout": 10,
})))
PY
```

更好的方式是通过网页端「立即执行」，可以同时验证平台的账号串行、参数加密、
日志捕获、结果汇总和推送。

## 安全注意事项

- 模块代码会以服务进程权限执行，请只安装可信模块。
- 不要在日志中输出密码、Cookie、Token 或完整推送 Key。
- 生产环境务必使用 HTTPS。
- 如果使用真实账号，请确认目标平台允许自动化签到，并遵守其服务条款。
