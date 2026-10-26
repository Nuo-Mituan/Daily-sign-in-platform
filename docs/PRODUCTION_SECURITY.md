# 内网部署安全指南（v1.0.5）

本文面向**单机 Docker Compose、局域网内部使用**的签到云台部署。v1.0.5 默认不要求 HTTPS、反向代理或公网暴露；但必须理解没有 HTTPS 时的风险边界。

---

## 1. 推荐部署拓扑

```text
局域网浏览器
    │  HTTP（内网）
    ▼
127.0.0.1 / 局域网 IP : APP_PORT
    ▼
Docker Compose（单容器）
    ├── FastAPI + SPA
    ├── SQLite（data/）
    ├── 环形日志（同库 ring_logs）
    └── 以 PUID:PGID 降权运行
```

- `APP_BIND=127.0.0.1`：仅本机访问，最安全；
- `APP_BIND=<局域网 IP>`：仅内网访问；
- **不要**把端口映射到公网，不要做路由器端口转发；
- 如未来需要公网/HTTPS，再增加反向代理和 `COOKIE_SECURE=true`。

## 2. HTTPS 非必需，但风险必须显式接受

> **警告：默认 `COOKIE_SECURE=false` 会让登录 Cookie 通过局域网 HTTP 明文传输。**
> 同网段嗅探、ARP 欺骗、恶意 Wi-Fi、交换机端口镜像、旁路代理都可能截获
> `checkin_session`。拿到 Cookie 即等同于拿到当前管理员会话，直到注销或过期。
> 这不是“配置无关紧要”的默认值，而是内网可信场景下的明确取舍。

具体风险点：

| 风险 | 后果 | 缓解措施 |
| --- | --- | --- |
| 同网段抓包 | Cookie 明文泄露，会话被重放 | 交换机端口隔离、VLAN、可信 Wi-Fi |
| ARP 欺骗 / 中间人 | 攻击者代理 HTTP 流量 | 静态 ARP、动态 ARP 检测、隔离管理网 |
| 恶意 Wi-Fi / 访客网络 | 未授权设备接入 | 独立 SSID、WPA3、禁用访客互访 |
| 路由器端口转发 | 应用暴露公网 | 不做端口映射、防火墙拒绝 WAN |
| 反向代理误配 | TLS 终止但 Cookie 仍无 Secure | 启用 HTTPS 后设 `COOKIE_SECURE=true` |

适用边界：

- 只在自己信任的家庭/办公室内网使用；
- 不接入公共 Wi-Fi；
- 不允许不受信任的人访问同一广播域；
- **必须**用防火墙白名单限制可访问 `APP_PORT` 的源 IP；
- **推荐**把应用放进独立 VLAN/管理网，访客 VLAN 不可路由到该端口；
- 定期检查 `auth_sessions` 与访问来源。

如条件允许，仍建议使用 HTTPS 或至少限制来源 IP。

## 3. 必做项

- [ ] 修改默认管理员密码；首次登录后立即在「用户设置」修改；
- [ ] `SECRET_KEY` 显式设置或确认 `data/.secret_key` 已生成且纳入备份；
- [ ] `.env` 权限 `600`，不提交 Git；
- [ ] `APP_BIND` 限定为 `127.0.0.1` 或可信局域网 IP；
- [ ] 容器以 `PUID/PGID` 非 root 运行，`data/`、`logs/` 权限 `700`；
- [ ] SQLite 文件权限 `600`（应用自动设置）；
- [ ] 只安装信任的模块和推送驱动；
- [ ] 运行 `python scripts/verify_api.py` 与 `bash verify_docker.sh`；
- [ ] 配置备份并实际恢复一次。

## 4. 加密与密钥

- 模块参数、账号参数、推送凭据使用 **AES-256-GCM v2**；
- HKDF-SHA256 从 `SECRET_KEY` 派生 256 位密钥；
- 每条密文独立 12 字节 nonce；
- AAD 绑定 `user_id | module_key | account_index`，跨模块/跨账号搬移密文会失败；
- 旧 Fernet v1 密文透明兼容并在读取/执行时自动升级为 v2；
- 更换 `SECRET_KEY` 会导致旧密文不可解密；必须同时迁移或重新填写；
- 密码使用 PBKDF2 不可逆哈希。

## 5. 登录与会话

- Cookie 名称 `checkin_session`；
- `HttpOnly`、`SameSite=Strict`、`Path=/`、10 年 `Max-Age`；
- 服务端 `auth_sessions` 保存 session_id 的 SHA-256，支持注销与全端注销；
- 5 分钟滑动续期；
- `COOKIE_SECURE` 在 HTTPS 环境必须为 `true`；
- 不再使用 JWT/Bearer；旧 JWT 全部失效。

## 6. CSRF

- `CSRF_ENABLED=true` 默认开启；
- 写方法必须带 `X-CSRF-Token`；
- Token 只保存在 Pinia 内存，不写 localStorage；
- 登录接口豁免，登出/修改密码/删除等全部校验；
- 关闭开关只用于兼容调试，不建议生产关闭。

## 7. 敏感字段与日志

- `config.json` 中 `sensitive: true` 或 password/cookie/token/secret/key 自动掩码；
- API 默认返回掩码，二次密码验证后才可临时显示；
- 日志统一进入环形存储 `ring_logs`；
- 应用日志、模块 stdout、SSE、数据库、异常 traceback 均经过脱敏；
- 环形日志受保留天数和系统/模块/推送独立配额约束；
- 旧文件日志写入器已移除，只保留过期清理。

## 8. 推送与驱动安全

- 推送凭据加密保存，API 掩码；
- 统一推送汇总成功后立即物理删除 `push_pool` 明细，仅保留 `push_batches` 摘要；
- 自定义驱动运行在服务进程内，**AST 校验不是沙箱**；
- 只允许可信管理员上传驱动；
- 内置驱动不可删除；
- ZIP 上传拒绝路径穿越、符号链接和额外文件。

## 9. Docker 非 root

- 入口脚本以 root 修正 bind mount 所有权，然后 `setgid/setuid` 到 `PUID:PGID`；
- 默认 `PUID=PGID=10001`；
- 宿主机 bind mount 可能被 chown，请提前确认；
- 建议 `no-new-privileges: true`；
- 容器内 `/app/data`、`/app/logs` 应为 `700`，SQLite 为 `600`。

## 10. 数据备份与日志清理

备份：

```bash
sqlite3 data/checkin.db ".backup 'backup.db'"
cp data/.secret_key backup.secret_key
```

必须同时备份数据库和 `SECRET_KEY`，否则密文无法恢复。

日志：

- 默认保留 31 天；
- Web「用户设置 → 日志设置」可改 1–365 天，保存后立即裁剪；
- 每日 03:10 自动裁剪；
- 推送批次明细 flush 后立即清理，不等待保留期。

## 11. 安全检查清单

- [ ] 默认密码已修改；
- [ ] 端口未暴露公网；
- [ ] `COOKIE_SECURE` 与部署协议一致；
- [ ] CSRF 未关闭；
- [ ] 容器 UID 非 0；
- [ ] data/logs 权限 700，DB 600；
- [ ] 备份可用；
- [ ] 只安装可信模块/驱动；
- [ ] 日志保留策略符合磁盘容量；
- [ ] `verify_api.py` 与 `verify_docker.sh` 通过。
