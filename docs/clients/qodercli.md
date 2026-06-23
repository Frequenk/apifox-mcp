# Qoder CLI 对接

[Qoder CLI](https://qoder.ai) 通过 `mcp` 子命令管理 MCP server。

## 1. 注册

```bash
qodercli mcp add-json apifox -s user '{
  "command": "docker",
  "args": ["run", "-i", "--rm", "-e", "APIFOX_TOKEN", "-e", "APIFOX_PROJECTS", "ghcr.io/frequenk/apifox-mcp:latest"],
  "env": {
    "APIFOX_TOKEN": "your_token_here",
    "APIFOX_PROJECTS": "[{\"name\":\"主项目\",\"id\":\"7575229\"}]"
  }
}'
```

> 用 `add-json` 而非 `add`：`mcp add` 的 `-e/--env` 与 docker 的 `-e` 会命令行解析冲突，`add-json` 直接传 JSON 干净无歧义。
> `-s user` 写入全局 `~/.qoder/settings.json`，所有项目可用。

## 2. 检查

```bash
qodercli mcp list
qodercli mcp get apifox
```

`mcp get` 的 `Status: ✓ Connected` 表示已实际启动容器并握手成功，是最直接的连通性验证。

## 3. 更新镜像

`latest` 标签不会自动更新：

```bash
docker pull ghcr.io/frequenk/apifox-mcp:latest
```

拉取后重启 qodercli 会话即生效。

## 4. 卸载

```bash
qodercli mcp remove apifox -s user
```
