# v1.0.3 变更说明

> v1.0.4 已移除「每半个月」「每季度」，改为 5 种周期 + 条件子选项。本文保留 v1.0.3
> 当时的行为记录；当前规范请以 [MODULE_DEVELOPMENT.md](MODULE_DEVELOPMENT.md) 为准。

v1.0.3 在不重写已有模块加载、执行日志、SSE、参数加密和 Docker 部署链路的前提下，
新增/调整了以下能力：

1. 用户设置：修改用户名、修改密码；
2. 登录安全：关闭自动填充与用户名预填，统一错误、防枚举与敏感操作限流；
3. 随机时间调度：时间窗 + 六种周期，周期起始日 00:00 生成，整点重试，时间窗中点兜底；
4. 多账号：账号数组、增删折叠、拖拽排序、串行执行、2–5 分钟随机间隔、脱敏日志；
5. 全局推送：Bark / Server酱 / PushPlus / 钉钉 / 飞书，加密保存，模块推送开关，模板变量；
6. 示例模块、进阶模板、开发文档、验证脚本和测试同步更新。

---

## 1. 关键行为约定

### 1.1 随机调度

- 每个模块保存 `start_time` / `end_time`（`HH:mm`）和 `repeat_cycle`；
- 开始时间必须严格早于结束时间，不支持跨天；
- **只在周期起始日执行**：
  - 每日 = 每天；
  - 每周 = 周一；
  - 每半个月 = 1 日 / 16 日；
  - 每月 = 1 日；
  - 每季度 = 1 / 4 / 7 / 10 月 1 日；
  - 每年 = 1 月 1 日；
- 周期起始日 00:00（`TIMEZONE`）在时间窗内均匀随机生成执行时间；
- 每个模块每个周期只保留一条 `module_schedules` 记录；
- 整点检查缺失并重试；
- 到时间窗中点仍无计划时使用中点兜底，并发送 `schedule_failure` 推送；
- 用户可手动重新生成；
- APScheduler 使用动态的一次性 `DateTrigger`：`plan` / `exec` / `fallback`，
  不再为每个模块注册固定 Cron。

### 1.2 多账号

- `config.json` 的 `multi_account: true` 时，`params` 会按账号重复渲染；
- 账号结构：`{id, label, params}`，整体以加密 JSON 数组保存；
- 参数在数组中的顺序就是执行顺序；
- 平台逐账号调用一次 `run(params)`；
- 账号间随机等待 `ACCOUNT_INTERVAL_MIN_SECONDS`–`ACCOUNT_INTERVAL_MAX_SECONDS`
  （默认 120–300 秒），最后一个账号后不等待；
- `MODULE_TIMEOUT` 按账号分别计时；
- 账号标识优先显示备注；否则用 `account_label: true` 字段的脱敏值；
- 全部成功才标记整体成功；部分失败标记整体失败，并推送 `partial_failure`；
- `multi_account: false` 时保持原有单账号表单与执行方式。

### 1.3 推送

- 全局渠道在「用户设置 → 全局推送通知」配置；
- 模块级「启用推送」开关默认关闭；
- 推送由平台统一发送，模块代码不需要也不应该实现推送；
- 事件：单账号成功/失败、多账号全成功/全失败/部分失败、随机时间生成失败、测试消息；
- 模板变量：
  `{event}`、`{module_name}`、`{module_key}`、`{account}`、`{status}`、
  `{result}`、`{duration}`、`{error}`、`{time}`、`{summary}`、`{details}`；
- 钉钉/飞书 Webhook 仅允许官方 HTTPS 域名；推送失败不改变签到结果。

### 1.4 兼容性

- 旧模块的 `default_cron` 仍会被读取，并尽量推导为 1 小时时间窗；
- 旧数据库启动时自动执行 SQLite 前向迁移；
- 旧字段 `cron` / `default_cron` 保留，但新模块应使用 `default_*` 时间字段；
- 旧单账号 `params` 在模块切换为多账号后可作为一个 legacy 账号读取；
- 用户已保存的调度字段不会被扫描覆盖。

---

## 2. 文件变更清单

### 2.1 新增文件

**后端**

- `backend/app/scheduling.py`：周期、时间窗、随机时间、下次计划日期的纯函数；
- `backend/app/migrations.py`：SQLite 前向迁移与旧 Cron → 时间窗；
- `backend/app/services/schedules.py`：计划状态机、生成、兜底、原子认领、取消；
- `backend/app/services/push.py`：全局推送配置、模板、五个渠道适配器；
- `backend/app/services/auth_guard.py`：敏感操作用户锁与失败限流；
- `backend/app/routers/push.py`：推送配置与测试 API；
- `backend/tests/test_scheduler.py`：动态 plan/exec/fallback 与真实调度执行测试；
- `backend/tests/test_push.py`：渠道配置、模板、签名测试；
- `backend/tests/test_push_delivery.py`：使用 Fake HTTP Client 验证五个渠道请求构造。

**前端**

- `frontend/src/views/SettingsView.vue`：用户名、密码、全局推送配置；
- `frontend/src/components/AccountEditor.vue`：账号添加、删除、折叠、复制、上下移动、拖拽排序；
- `frontend/src/components/RandomScheduleField.vue`：时间窗与周期编辑；
- `frontend/src/utils/schedule.js`：周期文案、时间校验、状态展示；
- `frontend/src/utils/accounts.js`：账号默认参数、脱敏提示、账号级校验。

**文档与截图**

- `docs/ITERATION3_CHANGES.md`（本文件）；
- `docs/screenshots/settings.png`；
- `docs/screenshots/module-config.png`。

### 2.2 修改文件

**后端**

- `backend/app/config.py`：账号间隔、随机时间最小提前秒数；
- `backend/app/models.py`：调度字段、`ModuleSchedule`、`PushConfig`、账号密文；
- `backend/app/database.py`：启动时执行前向迁移；
- `backend/app/schemas.py`：新请求/响应模型、账号、计划、推送、用户设置；
- `backend/app/module_loader.py`：新默认字段、旧 Cron 推导、账号规范化与脱敏；
- `backend/app/main.py`：注册推送路由、启动时清理遗留计划、异步 reconcile；
- `backend/app/routers/auth.py`：用户名修改、并发锁、失败限流、统一登录错误；
- `backend/app/routers/modules.py`：账号 CRUD、随机调度、重新生成、推送开关；
- `backend/app/routers/system.py`：`/api/meta` 返回周期/账号间隔等新信息；
- `backend/app/services/execution.py`：多账号串行、随机间隔、脱敏、汇总、通知；
- `backend/app/services/scheduler.py`：动态 plan/exec/fallback、整点补偿；
- `backend/app/services/bootstrap.py`：启动提示改为「用户设置」；
- `backend/tests/conftest.py`：测试环境账号间隔设为 1 秒；
- `backend/tests/test_core.py`：周期/时间窗/账号/旧 Cron 兼容测试；
- `backend/tests/test_api.py`：完整新 API 流程；
- `backend/tests/test_advanced_template.py`：多账号模板与无模块级推送测试。

**前端**

- `frontend/src/api/index.js`：用户名、重新生成计划、推送配置 API；
- `frontend/src/stores/auth.js`：用户名更新；
- `frontend/src/router/index.js`：`/settings` 路由；
- `frontend/src/layouts/AppLayout.vue`：用户设置入口、侧栏；
- `frontend/src/views/LoginView.vue`：空用户名、`autocomplete="off"`、新文案；
- `frontend/src/views/DashboardView.vue`：本次随机时间、周期/时间窗、待执行列表；
- `frontend/src/views/ModulesView.vue`：时间窗、本次执行、账号/推送模式；
- `frontend/src/views/ModuleDetailView.vue`：账号编辑器、随机时间、推送开关、重新生成；
- `frontend/src/views/GuideView.vue`：新 config 字段、多账号与平台推送说明；
- `README.md`、`docs/MODULE_DEVELOPMENT.md`、`docs/PRODUCTION_SECURITY.md`、
  `docs/BACKUP_AND_MIGRATION.md`：功能、配置、迁移与安全说明；
- `docs/screenshots/dashboard.png`、`modules.png`、`login.png`：新界面截图。

**示例与部署**

- `modules/demo_checkin/{config.json,main.py}`：单账号示例，新默认时间字段；
- `modules/moyu_energy/{config.json,main.py}`：多账号示例、部分失败模拟；
- `templates/advanced_checkin/{config.json,main.py,README.md}`：多账号平台标准入口，
  移除模块级推送；
- `scripts/verify_api.py`：重写为随机调度/多账号/推送/用户设置验证；
- `verify_docker.sh`：验证环境账号间隔与文案；
- `docker-compose.yml`、`.env.example`：新环境变量与说明。

### 2.3 删除文件

- `backend/app/cron_utils.py`：固定 Cron 调度已由随机调度取代；
- `frontend/src/components/CronField.vue`：Cron 输入组件不再使用；
- `frontend/src/utils/cron.js`：Cron 文案/预设不再使用；
- `templates/advanced_checkin/push.py`：推送统一由平台负责，模块不再实现。

---

## 3. API 变更

### 新增/调整

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `PUT` | `/api/auth/username` | 修改用户名，验证当前密码；幂等、并发锁、唯一性兜底 |
| `POST` | `/api/modules/{id}/schedule/regenerate` | 手动重新生成本期随机时间 |
| `GET` | `/api/push/config` | 读取全局推送配置 |
| `PUT` | `/api/push/config` | 保存全局推送配置 |
| `POST` | `/api/push/test` | 发送测试消息 |

### 字段变化

- `ModuleOut` 新增：
  `start_time`、`end_time`、`repeat_cycle`、`default_start_time`、
  `default_end_time`、`default_repeat_cycle`、`multi_account`、`push_enabled`、
  `current_schedule_at`、`schedule_period_start`、`schedule_status`、
  `schedule_source`、`schedule_fallback_used`、`schedule_note`、`account_count`。
- `ModuleDetail` 新增：
  `accounts: [{id,label,params}]`；单账号时 `params` 仍为扁平对象；
- `ModuleUpdateRequest` 新增：
  `start_time`、`end_time`、`repeat_cycle`、`multi_account` 相关账号、`push_enabled`；
  `cron` 字段不再用于调度。
- 移除：`POST /api/modules/cron/preview`。
- `module_schedules` 新增表；`push_config` 新增单例表。

---

## 4. 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ACCOUNT_INTERVAL_MIN_SECONDS` | `120` | 多账号串行最小间隔 |
| `ACCOUNT_INTERVAL_MAX_SECONDS` | `300` | 多账号串行最大间隔 |
| `SCHEDULE_MIN_LEAD_SECONDS` | `5` | 随机时间至少提前秒数 |
| `MODULE_TIMEOUT` | `300` | 单个账号超时 |

`TZ` / `TIMEZONE` 仍决定业务时区；数据库内时间统一存 UTC，页面按业务时区展示。

---

## 5. 升级与部署

### 从旧版本升级

1. 备份 `data/`、`.env`、自定义 `modules/`；
2. 拉取新代码并重新构建：
   ```bash
   docker compose build
   docker compose up -d
   ```
3. 启动时自动补充数据库字段、迁移旧 Cron 默认时间窗；
4. 登录后进入「用户设置」检查账号凭据；
5. 打开每个模块确认时间窗与账号；
6. 在「用户设置 → 全局推送通知」配置渠道，再按需打开模块推送开关。

无需手工修改旧 `config.json`；新字段是推荐写法，旧 `default_cron` 仍兼容。

---

## 6. 验证结果

本次在本地环境完成：

- 后端单元/集成测试：`19 passed`；
- 前端生产构建：`pnpm run build` 通过；
- 真实后端启动 + `scripts/verify_api.py` 全流程通过：
  - 未认证 401、统一登录错误；
  - 六种周期、随机时间生成、手动重新生成；
  - 单账号执行；
  - 多账号顺序、1 秒测试间隔、脱敏日志、部分失败汇总；
  - 推送配置、非法渠道与非法 Webhook；
  - 用户名幂等/修改/改回、密码修改；
  - 扫描、仪表盘、执行历史。
- 无头 Chrome 渲染登录、仪表盘、模块列表、单/多账号配置、用户设置与推送页，
  浏览器控制台无错误。

### Docker 说明

当前开发环境没有可用的 Docker daemon，因此没有实际执行 `docker compose build` 和
`verify_docker.sh`。本次已完成等价的本地构建、启动、API 验证、前端构建和浏览器渲染验证；
`verify_docker.sh` 已同步新的验证内容，可在有 Docker 的机器上直接运行。
