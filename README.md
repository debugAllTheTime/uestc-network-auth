# UESTC Network Auth

轻量的电子科技大学校园网自动认证服务。使用 Docker Compose 部署，自动检测网络并在掉线后重新认证。

## 特性

- 支持校园网、电信和移动三种网络配置。
- 连续 ping 失败后自动认证，登录后等待 60 秒再检测。
- 适配 `CONFIG.ip` 和 `user_ip` 两种认证页面。
- 请求直连认证服务器，不使用环境代理。
- 北京时间日志，支持日志轮转和可选完整通信归档。
- Docker Compose 一键构建和部署。

## 快速开始

需要 Linux、Docker Engine 和 Docker Compose v2，并已接入对应校园网络。

下载项目并进入目录：

```bash
git clone https://github.com/debugAllTheTime/uestc-network-auth.git
cd uestc-network-auth

# 交互式配置学号和密码
sudo python3 -I scripts/configure.py

# 构建并启动
docker compose up -d --build

# 查看日志
docker compose logs --tail 100 -f auth
```

如需选择电信或移动网络，在启动前修改 `compose.yaml` 中的 `NETWORK`。

## 让 AI 帮你配置

如果你使用的 AI 助手能够操作目标 Linux 主机的终端，可以把下面整段提示词发给它，让它完成部署。提示词已包含项目地址；如果已经下载项目，直接告诉 AI 本地目录即可。只有聊天能力、没有终端权限的 AI 可以逐步指导你操作。

```text
请帮我在当前 Linux 主机上部署 UESTC Network Auth，直接完成可执行的步骤，而不是只给命令清单。

项目地址：https://github.com/debugAllTheTime/uestc-network-auth
项目目录：如果已下载，使用我提供的目录；否则在合适的位置克隆到独立目录。
网络类型：校园网 uestc（如果我使用的是电信或移动，请分别改为 dx 或 cmcc）。

请按以下步骤操作：
1. 检查 Linux、Docker Engine、Docker Compose v2 和服务权限，阅读项目 README、compose.yaml 及 scripts/configure.py。缺少依赖时先说明需要安装什么；只有确实需要的信息再问我。
2. 检查是否有同类自动认证容器正在运行，避免并行认证。若发现已有服务，先让我确认是否替换，不要直接停止或覆盖。
3. 配置 NETWORK，其他参数先保持项目默认值：ping www.scu.edu.cn、连续失败 3 次后认证、认证后冷却 60 秒、北京时间日志、完整通信归档关闭。
4. 运行 sudo python3 -I scripts/configure.py，让我在交互式终端输入学号和密码；密码隐藏输入，学号不带域后缀。若你的工具不支持交互，请暂停这一项并告诉我如何在项目目录执行，等我完成后继续。sudo 密码也由我在终端输入，不需要我发送到聊天。确认凭据文件属于 root，权限为 0600，不显示文件内容。如果文件已经存在，保留并询问是否使用，不直接覆盖。
5. 执行 docker compose up -d --build。构建下载需要代理时再问我代理地址，仅用于构建；容器运行时必须直连，保持现有代理清空配置以及 Session.trust_env=False。
6. 查看 docker compose ps 和最近的服务日志，在容器内 ping www.scu.edu.cn 验证连通性。不主动断网或注销，也不为了验证密码而额外触发登录。分别说明“服务运行正常”“目标可达”和“服务端认证成功”，不要将它们混为一谈。
7. 最后给出项目目录、运行状态、采用的网络类型，以及查看日志、重启、停止和更新的方法。构建或启动失败时明确报告失败步骤，解决后再继续，不把未完成的步骤说成成功。

请只操作这个项目，不修改无关容器或宿主机网络。需要我交互输入或确认时再暂停，其余步骤连续完成。
```

## 网络选择

| NETWORK | 网络 | 认证地址 | ac_id | 自动追加的账号后缀 |
|---|---|---|---|---|
| `uestc` | 校园网 | `10.253.0.237` | `1` | `@dx-uestc` |
| `dx` | 电信 | `10.253.0.235` | `3` | `@dx` |
| `cmcc` | 移动 | `10.253.0.235` | `3` | `@cmcc` |

学号不带后缀。凭据文件使用 `id` 和 `passwd` 两个 JSON 字段，结构见 [examples/credentials.example.json](examples/credentials.example.json)。配置向导会自动创建权限为 `0600` 的 root 所有文件，并通过只读挂载供容器读取。

## 配置

在 `compose.yaml` 的 `environment` 中调整：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `NETWORK` | `uestc` | `uestc` / `dx` / `cmcc` |
| `PING_TARGET` | `www.scu.edu.cn` | 连通性检测目标 |
| `CHECK_INTERVAL` | `16` | 初始检测间隔，单位秒 |
| `MAX_FAILED` | `3` | 连续失败次数 |
| `LOGIN_COOLDOWN` | `60` | 每次认证后的等待时间，至少 60 秒 |
| `TZ` | `Asia/Shanghai` | 日志时区 |
| `CREDENTIALS_FILE` | `/run/secrets/uestc_credentials` | 容器内凭据文件位置 |
| `ARCHIVE_ENABLED` | `false` | 是否保存完整认证通信 |
| `RESPONSE_DIR` | `/var/lib/uestc-auth/responses` | 通信归档位置 |

HTTP 连接超时为 5 秒，读取超时为 10 秒。当前账号密码编码支持 ASCII 字符。

### 检测流程

```text
ping 成功 → 等待下一次检测
ping 连续失败 3 次 → 获取页面 IP → 获取 challenge → 提交认证
认证结束 → 等待 60 秒 → 重新检测
```

沿用连续失败后检测间隔减半的策略：初始 16 秒，首次失败后等 8 秒，第二次失败后等 4 秒；认证后重置。正常 ping 不逐次输出日志，仅记录失败、恢复及认证结果。

`success` 表示服务端认证成功；`already_online` 表示当前 IP 已在线。ping 和 DNS 失败均计入检测失败，因此认证成功后目标仍不可达时，会按相同规则再次检测和重试。

### 完整通信归档

需要排查认证问题时，设置 `ARCHIVE_ENABLED: "true"` 并重建服务：

```bash
docker compose up -d
```

记录保存在 `responses` Docker volume 的 `auth-exchanges.jsonl` 中，包含认证 HTTP 请求 URL、参数、响应头和完整正文，不记录 ping。文件权限 `0600`，约 10 MiB 一份，保留 3 份；单条记录不截断。记录包含账号和认证材料，请勿作为公开附件提交。

## 常用操作

```bash
docker compose ps                      # 服务状态
docker compose logs --tail 100 auth    # 最近日志
docker compose restart auth           # 重启
docker compose stop auth              # 停止
docker compose up -d --build           # 更新代码后构建并运行
```

更换凭据时编辑本机 `secrets/credentials.json`，保留 root 所有及 `0600` 权限，然后运行 `docker compose up -d --force-recreate auth`。

服务采用 host 网络，不需要端口映射。Docker 构建下载可使用代理；应用运行时保持直连。服务停止不会注销现有网络会话。

## 工程结构

```text
src/uestc_auth/
├── config.py       # 网络与凭据配置
├── auth.py         # 认证协议
├── monitor.py      # 网络监测
├── responses.py    # 可选通信归档
├── encryption/     # 协议编码
└── __main__.py     # 服务入口
scripts/configure.py
examples/credentials.example.json
Dockerfile
compose.yaml
```

## 致谢

感谢以下开源项目提供的代码与思路：

- [AutoLoginUESTC](https://github.com/b71db892/AutoLoginUESTC)：参考其电子科技大学校园网认证脚本、网络配置和自动重连流程。
- [BIT-srun-login-script](https://github.com/coffeehat/BIT-srun-login-script)：参考其深澜（Srun）认证协议实现，并复用了相关加密编码代码。

本项目在此基础上整理了 Docker Compose 部署、认证页面适配、日志与可选通信归档等功能。相关许可信息见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## License

MIT，详见 [LICENSE](LICENSE) 和 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
