# opencode 对接

[opencode](https://opencode.ai) 的全局配置文件为 `~/.config/opencode/opencode.json`（或 `opencode.jsonc`）。

## 1. 配置

在配置文件中加入 `mcp` 段：

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "apifox": {
      "type": "local",
      "command": [
        "docker", "run", "--pull=always", "-i", "--rm",
        "-e", "APIFOX_TOKEN",
        "-e", "APIFOX_PROJECTS",
        "ghcr.io/frequenk/apifox-mcp:latest"
      ],
      "enabled": true,
      "env": {
        "APIFOX_TOKEN": "your_token_here",
        "APIFOX_PROJECTS": "[{\"name\":\"主项目\",\"id\":\"7575229\"}]"
      }
    }
  }
}
```

> opencode 的字段是 `mcp`（不是 `mcpServers`），且 `command` 是**字符串数组**（不是单个字符串）。

## 2. 生效与校验

- opencode 启动时加载一次配置，不热重载；改完需**重启 opencode**。
- 重启后在会话中调用 `get_apifox_status` 复核实际读到的项目数量与连接状态。

## 3. 更新镜像

使用 `--pull=always` 后，每次启动都会检查最新镜像；也可以手动更新：

```bash
docker pull ghcr.io/frequenk/apifox-mcp:latest
```

拉取后重启 opencode 即生效。

## 4. 卸载

删除配置文件里的 `mcp.apifox` 段，重启 opencode。
