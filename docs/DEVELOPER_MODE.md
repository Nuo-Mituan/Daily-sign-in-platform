# 模块开发者模式与手动测试执行

> v1.0.1 增量功能。开发者模式是**服务端强制**权限，不是前端隐藏按钮。

## 1. 用户偏好

字段：`users.developer_mode_enabled`，默认 `False`。

### 读取

```http
GET /api/settings/developer
```

```json
{"enabled": false}
```

### 修改

```http
PUT /api/settings/developer
Content-Type: application/json
X-CSRF-Token: <token>

{"enabled": true}
```

- 需要登录与 CSRF；
- 登录响应、`GET /api/auth/me`、`GET /api/auth/session` 的 `user.developer_mode_enabled` 同步返回；
- 关闭后，已渲染页面的测试按钮应在下一次刷新/状态同步后消失。

## 2. 测试执行

```http
POST /api/modules/{module_id}/test
X-CSRF-Token: <token>
```

成功：

```json
{"log_id": 123, "status": "running", "message": "测试执行已触发，请查看执行日志"}
```

拒绝：

- `403`：当前用户未开启开发者模式；
- `409`：模块正在执行；
- `400`：模块不可执行/加载异常。

服务端执行顺序：

1. Router 认证 + CSRF；
2. Service 查询 `users.developer_mode_enabled`；
3. 为 `False` 立即抛出 `DeveloperModeDisabledError`；
4. 复用现有执行器，`trigger_type="test"`。

前端按钮隐藏不能替代此检查。

## 3. 日志隔离

- `execution_logs.trigger_type = "test"`；
- `execution_logs.module_name` 带 `[TEST]` 前缀；
- 执行正文标题为“手动测试”；
- 前端日志页可筛选“测试执行”；
- 测试日志与定时/手动日志共用同一执行历史表，不做删除。

## 4. 推送隔离

测试执行会：

- **跳过统一推送池**，避免测试结果进入周期批次；
- 强制调用独立推送通道，验证真实推送配置；
- 在推送 `result` / `summary` / `details` 前追加 `[测试推送]`；
- 模块名在测试日志中带 `[TEST]`；
- 无全局推送渠道时，模块仍执行，只不发送外部通知。

## 5. 示例

```bash
curl -c cookies.txt -X POST http://127.0.0.1:5000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"..."}'

curl -b cookies.txt -X PUT http://127.0.0.1:5000/api/settings/developer \
  -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: $CSRF" \
  -d '{"enabled":true}'

curl -b cookies.txt -X POST http://127.0.0.1:5000/api/modules/1/test \
  -H "X-CSRF-Token: $CSRF"
```
