# Release Notes — v1.0.1

> 增量版本：模块开发者模式与手动测试执行。
>
> 本版本基于 `v1.0.0-rc.2` 代码线开发；正式发布仍需完成 Docker 实机门禁。

## 新增

- `users.developer_mode_enabled`，默认 `False`；
- `GET/PUT /api/settings/developer`；
- `POST /api/modules/{module_id}/test`；
- 测试执行日志 `trigger_type=test`，标题 `[TEST]`；
- 测试推送 `[测试推送]` 标识，跳过统一批次；
- 用户设置“模块开发者选项”开关；
- 模块卡片“测试执行”按钮，严格受服务端开关控制。

## 安全

- 测试 API 在 Service 层重新查询开发者状态，关闭时返回 403；
- 不依赖前端隐藏按钮；
- 测试推送仍是真实推送，仅增加标识；
- CSRF/会话策略不变。

## 验证

```text
pytest backend/tests -q     63 passed
ruff / mypy / import guard  passed
frontend build              passed
```

新增测试：

- 开发者模式关闭时测试 API 403；
- 开发者模式开启时执行并生成 `[TEST]` 日志。
