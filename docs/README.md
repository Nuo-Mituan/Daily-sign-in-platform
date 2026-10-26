# 文档索引

本目录汇总签到云台的模块开发、部署、运维与架构文档。模块契约以
[MODULE_DEVELOPMENT.md](MODULE_DEVELOPMENT.md) 和网页「模块开发指南」为准。

## 模块开发

- [模块开发指南](MODULE_DEVELOPMENT.md)：目录结构、`config.json`、`directory_name` /
  `legacy_key`、参数定义、图标、多账号、随机调度、日志与 API 速查。
- [统一推送](UNIFIED_PUSH.md)：推送渠道、模板与排障。
- [进阶模板](../templates/advanced_checkin/README.md)：真实场景模块骨架。
- 示例模块：[demo_checkin](../modules/demo_checkin)、[moyu_energy](../modules/moyu_energy)。

## 架构与质量

- [架构决策记录](../backend/app/DESIGN_DECISIONS.md)：限流器、连接池指标与关闭状态机不变量。
- [状态机重构 Playbook](playbooks/state-machine-refactoring.md)：PBT 契约守护流程。
- [Playbook 团队赋能材料](playbooks/state-machine-refactoring-slides.md)。
- [PBT Bootstrap 工具](../tools/pbt_bootstrap.py)。
- [金丝雀发布检查清单](runbooks/canary-validation-db-log-rate-limiter.md)。

## 部署与运维

- [生产安全清单](PRODUCTION_SECURITY.md)
- [备份、恢复与迁移](BACKUP_AND_MIGRATION.md)
- [Docker 部署验证 SOP](DOCKER_GATE_SOP.md)
- [发布策略](RELEASE_POLICY.md)
- [开发者模式](DEVELOPER_MODE.md)

## 变更记录

- [迭代 3](ITERATION3_CHANGES.md)
- [迭代 4](ITERATION4_CHANGES.md)
- [迭代 6](ITERATION6_CHANGES.md)
- [技术债清单](TECH_DEBT.md)
