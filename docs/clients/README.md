# 客户端对接

本 MCP server 统一通过 **Docker 云镜像** `ghcr.io/frequenk/apifox-mcp:latest` 运行，无需本地克隆源码或安装 Python 依赖。各 MCP 客户端只需把容器启动命令注册进去，并传入两个必需环境变量即可。

## 客户端总览

| 客户端 | 配置位置 | 文档 |
| :--- | :--- | :--- |
| Codex | `~/.codex/config.toml` | [codex.md](./codex.md) |
| Claude Code | `~/.claude.json` | [claude-code.md](./claude-code.md) |
| opencode | `~/.config/opencode/opencode.json(.jsonc)` | [opencode.md](./opencode.md) |
| Qoder CLI | `~/.qoder/settings.json` | [qodercli.md](./qodercli.md) |

> 镜像统一使用 `ghcr.io/frequenk/apifox-mcp:latest`，启动参数统一增加 `--pull=always`。

---

## 通用经验：环境变量传递与凭证策略

对接任意客户端前，务必先理解下面几条跨客户端通用的机制与坑。

### 1. `docker run -e VAR`（无值）的取值机制

容器启动命令里写的是 `-e APIFOX_TOKEN`（**无等号、无值**），这是 Docker 的「从启动该容器的进程环境中取同名变量传入容器」语义。也就是说：

- 容器**读不到宿主机 shell 的 `.zshrc` / `.bashrc`**；
- 变量必须由 **MCP 客户端**把它**写死**在自己的 `env` 配置里，再注入到启动 `docker` 的子进程环境中，`docker -e` 才能取到。

因此每个客户端配置里都必须带 `env` 段，不能假设 Docker 会自动继承终端环境。

### 2. 凭证策略：统一写死

本仓库所有客户端文档统一采用**把凭证写死在配置的 `env` 段**，原因：

- **GUI 客户端**（如 Codex 桌面版）由系统启动，不读 `.zshrc` / `.bashrc`，引用系统环境变量会取不到；
- 写死后配置自包含、即拷即用，GUI 与 CLI 通用。

> 不推荐引用系统环境变量（如 `{env:VAR}`）：GUI 客户端取不到，且多端行为不一致。

### 3. JSON 转义

`APIFOX_PROJECTS` 本身是一个 JSON 数组字符串，写入客户端的 JSON 配置时，内层双引号必须转义为 `\"`：

```json
"APIFOX_PROJECTS": "[{\"name\":\"主项目\",\"id\":\"7575229\"}]"
```

TOML（Codex）用单引号字符串则无需转义：`'[{"name":"主项目","id":"7575229"}]'`。

### 4. 作用域

建议用 **user / 全局** scope，一次配置所有项目可用。项目级（如 `.mcp.json`）会让凭证进 git，慎用。

### 5. 生效与校验

- 所有客户端配置都是**启动时加载一次**，改完要**重启会话**；运行中的 MCP server / 容器不会刷新。
- 改完用 MCP 工具 `get_apifox_status` 复核实际读到的项目数量与连接状态。
- Qoder CLI 额外可用 `qodercli mcp get apifox`，其 `Status: ✓ Connected` 能直接确认握手成功。
