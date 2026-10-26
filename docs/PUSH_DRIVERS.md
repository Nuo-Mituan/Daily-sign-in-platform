# 推送驱动开发指南

签到云台内置 Bark、Server 酱、PushPlus、钉钉、飞书驱动，并允许可信管理员上传自定义驱动实现热加载、回滚和删除。

> **安全边界：自定义驱动不是沙箱。**
> 上传时的 AST 检查只能拦截明显危险调用，无法阻止所有恶意逻辑。驱动与主程序在同一 Python 进程内运行，拥有相同权限。**只安装你完全信任的代码**；不要把“上传校验”误认为安全隔离。

---

## 1. 目录与版本

```text
backend/app/push_drivers/
├── base.py
├── registry.py
├── validation.py
└── custom/
    └── my_driver/
        ├── active.json          # {"version": "1.0.0"}
        ├── 1.0.0/
        │   ├── manifest.json
        │   └── driver.py
        └── 1.0.1/
            ├── manifest.json
            └── driver.py
```

- 每个驱动最多保留最近 5 个版本（`PUSH_DRIVER_MAX_VERSIONS`）。
- 上传成功后立即卸载旧模块、导入新模块并更新注册表。
- 新版本导入失败时自动回滚到上一 active 版本；旧版本文件保留。
- 回滚会重新导入目标版本；失败时保持当前 active 版本不变。
- 内置驱动不可删除。

## 2. manifest.json

```json
{
  "key": "my_driver",
  "name": "我的推送",
  "version": "1.0.0",
  "description": "示例自定义驱动",
  "entry": "driver.py",
  "fields": [
    {
      "key": "webhook",
      "label": "Webhook",
      "required": true,
      "secret": true,
      "placeholder": "https://example.com/hook",
      "help": "推送地址"
    }
  ]
}
```

约束：

- `key`：小写字母开头，字母/数字/下划线，2–40 位；
- `version`：字母/数字/点/下划线/短横线，1–40 位；
- `entry` 必须是 `driver.py`；
- `fields` 最多 30 项；`secret: true` 的字段在 API 中掩码显示；
- manifest 与 driver.py 必须在 ZIP 根目录；
- ZIP 不允许路径穿越、绝对路径、符号链接或额外文件。

## 3. driver.py 接口

```python
async def send(config: dict, title: str, body: str) -> dict:
    # config 来自全局推送配置，已按 fields 校验
    return {
        "sent": True,
        "channel": "my_driver",
        "response": "ok",
    }
```

- 必须定义**模块级**可调用 `send(config, title, body)`，不需要继承类；
- 支持 `async def`，也兼容同步函数；
- 返回必须是 dict；
- 失败返回 `{"sent": False, "error": "..."}` 或抛出异常；
- 驱动内不得记录凭据明文；
- 推荐使用 `httpx` 发起 HTTPS 请求，设置明确超时。

允许导入的模块（与 `validation.py` 的 `ALLOWED_IMPORTS` 完全一致）：

```text
asyncio base64 datetime hashlib hmac httpx json math re time typing urllib
```

禁止导入的模块（`FORBIDDEN_MODULES`）：

```text
builtins ctypes importlib marshal os pathlib pickle shutil signal socket
subprocess sys tempfile threading
```

禁止引用/调用的名称（`FORBIDDEN_NAMES`）：

```text
__builtins__ __import__ breakpoint compile eval exec getattr globals hasattr
input locals open setattr vars delattr
```

禁止调用的属性（`FORBIDDEN_ATTRS`）：

```text
chmod chown execv execve fork kill link mkdir makedirs popen remove removedirs
rename renames replace rmdir rmtree spawn system unlink walk write writelines
```

另外禁止访问任何双下划线属性（如 `__class__`、`__globals__`、`__code__`）。

## 4. 上传方式

### 4.1 .zip（推荐）

ZIP 根目录包含 `manifest.json` 与 `driver.py`。

```text
my_driver.zip
├── manifest.json
└── driver.py
```

### 4.2 单个 .py

上传接口同时提交：

```text
file=my_driver.py
key=my_driver
name=我的推送
version=1.0.0
```

单文件模式通过表单生成 manifest，`fields` 为空，适合没有额外凭据字段的驱动。

## 5. 管理 API

```text
GET    /api/push/drivers
POST   /api/push/drivers/upload
POST   /api/push/drivers/{key}/rollback
DELETE /api/push/drivers/{key}
```

所有写操作必须带 `X-CSRF-Token`，且仅登录管理员可调用。

内置驱动不可删除；若目标驱动仍是当前全局推送渠道，删除会返回 `409`，需先切换渠道。

## 6. 热加载生命周期

1. 接收并限制文件大小；
2. 校验 ZIP 路径、入口、manifest；
3. AST 静态检查；
4. 写入临时版本目录；
5. 导入新模块并检查 `send`；
6. 成功：更新 `active.json`、注册表、清理超过 5 个的旧版本；
7. 失败：删除新版本，重新导入上一 active 版本，返回明确错误。

## 7. 与环形日志/推送记录的关系

- 驱动发送成功/失败会写入统一环形日志的 `push` 域；
- 独立推送、统一汇总、重试、补发均写入 `push_records`；
- 驱动本身**不要**写日志文件或数据库；
- 凭据由平台加密存储，驱动只接收解密后的 config。
