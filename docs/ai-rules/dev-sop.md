# 闭环开发 SOP 与扩展点指南

## 新功能开发 SOP

```
Step 1: 需求理解
  ├─ 确认影响范围（前端/后端/数据库/Docker）
  ├─ 检查 architecture.md（数据模型）和 api-contracts.md（API 契约）
  └─ 新环境变量 → 同步 .env.example + config.py

Step 2: 数据层变更（如需要）
  ├─ models.py 新增/修改 ORM 模型
  ├─ migrations.py 编写既有库 ALTER TABLE
  ├─ schemas.py 新增/修改 Pydantic 模型
  └─ main.py#patch_schema() 仅保留 users.password_must_change 等历史幂等补丁，不新增变更

Step 3: 服务层实现
  ├─ services/ 新建或修改
  ├─ Service 不得新增 FastAPI Request/Response 依赖（现有 auth_sessions/module_upload 例外见 constraints.md）
  ├─ 敏感数据用 crypto.py v2 API
  ├─ 日志通过 ring_log 写入
  └─ 推送遵循 push_drivers/ 注册表模式

Step 4: 路由层暴露
  ├─ routers/ 新增端点
  ├─ 需登录的写方法自动受 CSRF 保护（登录接口除外）
  ├─ 认证用 deps.py#get_current_user
  └─ 统一 JSON 响应，错误用 HTTPException

Step 5: 前端适配
  ├─ api/index.js 添加调用
  ├─ stores/ 更新 Pinia store
  ├─ views/components 实现 UI
  ├─ 父路由 / 统一 requiresAuth，子路由继承；/login 仅 guestOnly
  └─ 不在 localStorage 存储任何东西

Step 6: 测试验证
  ├─ backend/tests/ pytest
  ├─ PBT 放 backend/tests/property/，标记 @pytest.mark.property（CI 用 pytest -m property）
  ├─ pnpm run build
  └─ scripts/verify_api.py 端到端

Step 7: 部署验证
  ├─ .env.example 补充说明
  ├─ CHANGELOG.md 记录
  └─ docs/ 更新文档
```

## Bug 修复 SOP

```
Step 1: 定位
  ├─ 确认层级（Router/Service/Data/前端）
  ├─ 查 ring_logs（系统+模块+推送日志）
  ├─ 查 execution_logs（执行历史）
  └─ 查 push_batches/push_pool（推送问题）

Step 2: 修复
  ├─ 只改对应层级
  ├─ 加密数据确认 v1/v2 兼容
  ├─ 调度检查 scheduling.py 5种周期+子选项
  └─ 推送检查 push_state.py + push_lock.py

Step 3: 回归
  ├─ pytest + PBT 通过
  ├─ API 契约不被破坏
  └─ pnpm run build 通过

Step 4: 记录 → CHANGELOG.md Fixed 条目
```

## 重构 SOP

```
Step 1: 评估 → 检查层级边界，注意 module_loader.py (TD-1)
Step 2: 契约保护 → 先写 PBT 固化行为，CI 阻止 >20% 性能回退
Step 3: 增量重构 → 每次只改一个 Service/Router，保持 API 兼容
Step 4: 验证 → PBT + pytest + build + verify_api.py 全通过
```

## 扩展点指南

### 新增签到模块
ZIP 包结构：
```
my_module/          # 可选：根目录或一级子目录
├── config.json   # name/version/default_*/multi_account/params（无 key 字段）
├── main.py       # async def run(params) -> dict
└── README.md     # 可选
```

> `key` 由模块目录名或上传时的 `name` 决定；`config.json` 可另声明 `directory_name` / `legacy_key`。

### 新增推送驱动

驱动包（推荐 ZIP，根目录仅两个文件）：

```text
my_driver.zip
├── manifest.json   # key/name/version/entry/fields
└── driver.py       # 模块级 send(config, title, body) -> dict
```

`driver.py` 必须定义模块级函数，不需要继承类：

```python
async def send(config: dict, title: str, body: str) -> dict:
    return {"sent": True, "channel": "my_driver", "response": "ok"}
```

- 通过 `POST /api/push/drivers/upload` 上传（登录 + CSRF），也支持单 `.py` + 表单 `key/name/version`；
- 平台校验 ZIP Slip、符号链接、额外文件、manifest 与 AST 危险调用；
- 成功后热加载并保留最近 5 个版本；新版本导入失败自动回滚上一版本；
- 回滚：`POST /api/push/drivers/{key}/rollback`；删除：`DELETE /api/push/drivers/{key}`；
- 自定义驱动不是沙箱，与主进程同权限运行，仅允许安装可信代码；
- 完整规范见 [PUSH_DRIVERS.md](../PUSH_DRIVERS.md)。

### 新增 API 端点
```python
# routers/my_feature.py
router = APIRouter(prefix="/my-feature", tags=["我的功能"])
@router.get("")
async def list_items(user=Depends(get_current_user)): ...

# main.py 注册
api = settings.api_prefix.rstrip("/")
app.include_router(my_feature.router, prefix=api)
```

## 关键文件索引

### 必读（任何修改前）
| 文件 | 大小 | 说明 |
|---|---|---|
| config.py | 8.5KB | 所有配置项 |
| models.py | 18KB | 全部 ORM 模型 |
| main.py | 17.5KB | 启动流程、中间件 |
| schemas.py | 10KB | Pydantic 模型 |
| .env.example | 2.5KB | 环境变量默认值 |

### 高频修改
| 文件 | 大小 | 说明 |
|---|---|---|
| routers/modules.py | 42KB | 模块 CRUD+执行+调度 |
| module_loader.py | 55KB | 巨型，修改需特别谨慎 |
| services/execution.py | 26.5KB | 任务执行引擎 |
| services/push*.py | ~75KB | 推送子系统全集 |
| services/ring_log.py | 26.5KB | 环形日志 |
| scheduling.py | 13KB | 调度算法 |

### 文档索引
| 文件 | 说明 |
|---|---|
| RELEASE_NOTES_v1.0.5.md | v1.0.5 完整变更 |
| MODULE_DEVELOPMENT.md | 模块开发规范（32KB） |
| PRODUCTION_SECURITY.md | 生产安全检查清单 |
| PUSH_DRIVERS.md | 推送驱动开发规范 |
| TECH_DEBT.md | 技术债清单 |
| playbooks/state-machine-refactoring.md | 状态机重构 Playbook v2.1 |
| backend/app/DESIGN_DECISIONS.md | 核心状态机 ADR 与 PBT 契约 ID |
