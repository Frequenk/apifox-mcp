# Claude Code 对接

[Claude Code](https://claude.com/claude-code) 是 Anthropic 官方 CLI。通过 `claude mcp add-json` 注册，凭证写死，使用 GHCR 云镜像。

## 1. 注册

```bash
claude mcp add-json apifox --scope user '{
  "command": "docker",
  "args": ["run", "-i", "--rm", "-e", "APIFOX_TOKEN", "-e", "APIFOX_PROJECTS", "ghcr.io/frequenk/apifox-mcp:latest"],
  "env": {
    "APIFOX_TOKEN": "your_token_here",
    "APIFOX_PROJECTS": "[{\"name\":\"主项目\",\"id\":\"7575229\"}]"
  }
}'
```

> `--scope user` 写入全局 `~/.claude.json`，所有项目可用。

## 2. 检查

```bash
claude mcp list
claude mcp get apifox
```

或在 Claude Code 会话内输入 `/mcp` 查看连接状态与工具数。

## 3. 更新镜像

`latest` 标签不会自动更新：

```bash
docker pull ghcr.io/frequenk/apifox-mcp:latest
```

拉取后重启 Claude Code 会话即生效。

## 4. 卸载

```bash
claude mcp remove apifox
```
