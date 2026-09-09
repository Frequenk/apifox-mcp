# Codex 对接

通过 `codex mcp add` 注册，凭证直接写死，使用 GHCR 云镜像。

## 1. 注册

```bash
codex mcp add apifox \
  --env APIFOX_TOKEN="your_token_here" \
  --env APIFOX_PROJECTS='[{"name":"主项目","id":"7575229"}]' \
  -- docker run --pull=always -i --rm -e APIFOX_TOKEN -e APIFOX_PROJECTS ghcr.io/frequenk/apifox-mcp:latest
```

## 2. 检查

```bash
codex mcp list
codex mcp get apifox
```

## 3. 更新镜像

使用 `--pull=always` 后，每次启动 MCP 容器都会检查并拉取最新镜像。也可以手动拉取：

```bash
docker pull ghcr.io/frequenk/apifox-mcp:latest
```

拉取后重启 Codex 会话即生效。

## 4. 卸载

```bash
codex mcp remove apifox
```
