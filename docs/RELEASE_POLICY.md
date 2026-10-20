# 发布与封版后变更管制

适用版本：`v1.0.0-rc.1` 及后续正式版。

## 1. 当前状态

- Tag：`v1.0.0-rc.1`
- 状态：Release Candidate
- 代码封版：已完成
- 生产流量切换：**阻塞**，等待 Docker 实机门禁
- 正式 Tag：`v1.0.0`，仅在门禁通过后创建

## 2. 主分支变更管制

自 `v1.0.0-rc.1` 起，`main` 仅接受：

1. P0 级安全漏洞修复；
2. P0 级数据完整性修复；
3. 与之配套的专项回归测试；
4. Release Notes 中标注 **“Post-RC Fix”** 的说明。

以下变更必须新开分支：

- 新功能；
- 重构；
- 文档更新；
- P1/P2/P3 技术债修复；
- 依赖升级；
- 配置默认值调整。

变更分支必须通过：

```bash
pytest backend/tests -q
pnpm run build
node scripts/check_frontend_privacy.mjs
python scripts/verify_api.py
bash verify_docker.sh   # 有 Docker 的环境
```

## 3. 热修复流程

1. 从当前 `main` 或发布 Tag 创建 `hotfix/p0-<summary>`；
2. 编写最小修复 + 专项测试；
3. 全量回归；
4. 合并后在 Release Notes 标注 `Post-RC Fix`；
5. 重新构建并重新执行 Docker 门禁；
6. 生成新的 RC 或正式版本 Tag，不移动旧 Tag。

## 4. Docker 门禁

```bash
cp .env.example .env
# 修改 ADMIN_PASS / SECRET_KEY / APP_BIND / PUID / PGID
bash verify_docker.sh
```

必须验证：

- 镜像构建成功；
- 容器以 PUID 非 root 运行；
- `/app/data`、`/app/logs` 权限 700；
- SQLite 600；
- 全部 API 验证通过；
- 未认证隐私检查通过。

门禁未通过前：

- 不创建 `v1.0.0`；
- 不切换生产流量；
- 不把 RC 附件标记为正式发布物。

## 5. 技术债

