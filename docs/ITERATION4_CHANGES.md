# 第四次迭代变更说明

本次为最小化增量修改，优先处理未认证页面隐私泄露，再完成周期精简与子选项联动。
没有重构模块加载、执行器、日志、SSE、参数加密、推送与 Docker 部署主链路。

---

## 1. 隐私修复（最高优先级）

- 彻底删除登录页 `.schedule-preview` 预览卡片：
  - 模块名称（演示签到 / 摸鱼能量签到）
  - 时间窗（`09:00–11:00` / `08:00–10:00`）
  - `02 modules` 数量
  - `已排程` / `待启用` 状态
- 删除对应模板块、全部 `.preview-*` CSS、`CircleCheckFilled` 图标导入。
- 登录页不 import 任何模块/仪表盘/日志/推送 API，不存在相关数据请求。
- 受保护路由在未认证时由 router guard 重定向到登录页，不挂载业务组件。
- 登录页增加一个**不含任何真实数据**的通用隐私说明卡片，避免删除预览后左侧布局空洞。
- 新增 `scripts/check_frontend_privacy.mjs`：使用无头 Chrome 打开 `/`、`/login`、
  `/dashboard`、`/modules`、`/modules/1`、`/logs`、`/settings`、`/guide`，
  断言 DOM 不包含 `schedule-preview`、模块名称、时间窗、账号数量等敏感内容。
- 新增受保护的周期预览接口：
  - `POST /api/modules/schedule/preview`
  - `POST /api/modules/schedule-preview`（兼容别名，不在 OpenAPI 展示）
  - 未认证均返回 401。

---

## 2. 周期精简与子选项

### 2.1 合法周期（严格 5 项）

| 内部值 | 显示 |
| --- | --- |
| `daily` | 每日 |
| `weekly` | 每周 |
| `monthly_15` | 每月15日 |
| `monthly` | 每月 |
| `yearly` | 每年 |

移除 `half_month`、`quarterly` 以及前端/文档中的“每半个月”“每季度”选项。

### 2.2 条件子选项

| 父周期 | 子控件 | `repeat_sub_value` |
| --- | --- | --- |
| `daily` | 不显示 | `""` |
| `weekly` | 星期几（周一至周日） | `"1"`-`"7"`（周一=1） |
| `monthly_15` | 不显示 | `""` |
| `monthly` | 日期（1-28） | `"1"`-`"28"` |
| `yearly` | 月 + 日两个联动下拉框 | `"M-D"`，如 `"1-1"`、`"12-31"`、`"2-29"` |

实现细节：

- 每月日期固定上限 28，规避大小月；
- 每年按所选月份动态计算天数，2 月允许 29 日，非闰年自动跳到下一个闰年；
- 切换父周期时自动修正子选项（如周五 → 每月保留 5 日；28 日 → 每周会降级为周一）；
- `config.json` 新增 `default_repeat_sub_value`；
- 数据库新增 `repeat_sub_value` / `default_repeat_sub_value`；
- 旧 `half_month` / `quarterly` 自动迁移为 `monthly` + `"1"`，并记录日志；
- 后端同时兼容旧模块配置中的旧周期值（导入时自动降级），但 API/前端只展示 5 项。

### 2.3 调度语义

- 执行只发生在选定的执行日；
- 每周按选定星期几，每月按选定 1-28 日，每年按选定月-日；
- `2-29` 仅闰年执行；
- 执行日 00:00 在时间窗内随机生成时间；
- APScheduler `plan` 任务指向下一个执行日 00:00；
- 其他可靠性机制（整点补偿、中点兜底、手动重新生成）保持不变。

---

## 3. 精确文件清单

以下为本轮实际修改/新增的文件，不含生成的 `frontend/dist`、`node_modules`、
`__pycache__`、临时验证数据。

### 3.1 新增

| 文件 | 说明 |
| --- | --- |
| `scripts/check_frontend_privacy.mjs` | 无头 Chrome 未认证 DOM 隐私检查 |
| `docs/ITERATION4_CHANGES.md` | 本变更说明 |
| `docs/ITERATION4_CODE_SNIPPETS.md` | 关键变更代码摘录（带行号） |

### 3.2 后端修改

| 文件 | 改动 |
| --- | --- |
| `backend/app/scheduling.py` | 5 周期、子选项校验、执行日计算、闰年逻辑 |
| `backend/app/models.py` | `repeat_sub_value` / `default_repeat_sub_value` |
| `backend/app/migrations.py` | 新增列、旧周期降级、迁移日志 |
| `backend/app/module_loader.py` | config 子选项、旧周期规范化、同步时保留用户值 |
| `backend/app/schemas.py` | 新字段、周期预览请求/响应 |
| `backend/app/routers/modules.py` | 序列化、更新校验、预览接口与 401 别名 |
| `backend/app/services/schedules.py` | 生成/兜底/重新生成全部传递子选项 |
| `backend/app/services/scheduler.py` | 执行日与下一计划日使用子选项 |
| `backend/tests/test_core.py` | 5 周期/子选项/闰年/旧周期迁移测试 |
| `backend/tests/test_api.py` | API 5 组合、预览 401、字段断言 |

### 3.3 前端修改

| 文件 | 改动 |
| --- | --- |
| `frontend/src/utils/schedule.js` | 5 周期、子选项工具、星期/月/日选项、闰年天数 |
| `frontend/src/components/RandomScheduleField.vue` | 条件子下拉框、年月日联动、默认值修正 |
| `frontend/src/views/ModuleDetailView.vue` | 子选项状态、保存、重置、Hero/摘要显示 |
| `frontend/src/views/ModulesView.vue` | 卡片执行日显示（去重） |
| `frontend/src/views/DashboardView.vue` | 下次计划描述传入子选项 |
| `frontend/src/views/GuideView.vue` | 5 周期与子选项配置说明 |
| `frontend/src/views/LoginView.vue` | 删除 schedule-preview、CSS、图标；增加隐私说明卡片 |

### 3.4 脚本、测试与文档

| 文件 | 改动 |
| --- | --- |
| `scripts/verify_api.py` | 5 组合校验、预览 401、旧周期真实迁移验证 |
| `verify_docker.sh` | 验证说明更新 |
| `docs/MODULE_DEVELOPMENT.md` | 周期规范、子选项格式、迁移说明 |
| `docs/PRODUCTION_SECURITY.md` | 隐私检查项、401 范围 |
| `docs/BACKUP_AND_MIGRATION.md` | 子选项迁移与恢复检查 |
| `docs/ITERATION3_CHANGES.md` | 标注为历史版本 |
| `README.md` | 5 周期、隐私、验证命令 |
| `templates/advanced_checkin/config.json` | `default_repeat_sub_value` |
| `templates/advanced_checkin/README.md` | 周期与子选项说明 |
| `docs/screenshots/dashboard.png` | 最新界面 |
| `docs/screenshots/modules.png` | 最新界面 |
| `docs/screenshots/login.png` | 无 schedule-preview |
| `docs/screenshots/module-config.png` | 每周五子选项 |

---

## 4. 验证结果

### 4.1 后端测试

```text
20 passed
```

覆盖：

- 5 种周期与子选项规范化；
- 非法星期/日期/月-日拒绝；
- 每周、每月、每月15日、每年、2-29 执行日；
- 旧 `half_month` / `quarterly` 降级；
- API 字段、预览 401、旧数据库迁移。

### 4.2 前端

```text
pnpm run build  -> 通过
```

无头 Chrome：

```text
node scripts/check_frontend_privacy.mjs
[PASS] /, /login, /dashboard, /modules, /modules/1, /logs, /settings, /guide
```

条件子控件浏览器检查：

```text
[PASS] daily/-        无子控件
[PASS] weekly/5       星期几
[PASS] monthly_15/-   无子控件
[PASS] monthly/28     日期（上限 28）
[PASS] yearly/2-29    月-日
```

### 4.3 真实后端 API 验证

`scripts/verify_api.py` 全部 PASS，包括：

- 未认证访问 `/modules/schedule-preview` 与别名返回 401；
- 5 种周期组合保存/回读；
- 周期预览 `2-29` 下一次执行日期为 2028-02-29；
- 旧周期真实迁移插入、执行、回查、清理；
- 原有登录、多账号、推送、执行历史、仪表盘回归通过。

### 4.4 Docker

当前环境仍无可用 Docker daemon，未实际执行 `docker compose build` 与
`verify_docker.sh`；已使用本地真实后端、前端生产构建、无头 Chrome、旧库迁移脚本验证。
`verify_docker.sh` 已同步本轮验证内容。
