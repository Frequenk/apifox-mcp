# Apifox MCP Server

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![uv](https://img.shields.io/badge/uv-Compatible-purple?logo=python&logoColor=white)](https://docs.astral.sh/uv/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0id2hpdGUiIGQ9Ik0xMiAyQzYuNDggMiAyIDYuNDggMiAxMnM0LjQ4IDEwIDEwIDEwIDEwLTQuNDggMTAtMTBTMTcuNTIgMiAxMiAyek0xMiAyMGMtNC40MSAwLTgtMy41OS04LThzMy41OS04IDgtOCA4IDMuNTkgOCA4LTMuNTkgOC04IDh6Ii8+PC9zdmc+)](https://modelcontextprotocol.io/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Apifox](https://img.shields.io/badge/Apifox-Integration-orange?logo=swagger&logoColor=white)](https://apifox.com/)

---

这是一个基于 [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) 的服务器，用于通过 LLM (如 Claude) 直接管理 [Apifox](https://apifox.com/) 项目。

它允许你通过自然语言指令来查看、创建、安全更新和批量处理 Apifox 中的 API 接口、数据模型 (Schema)、文件夹等，并能检查 API 定义的完整性。核心目标是让 AI 在改接口文档时尽量使用轻量上下文、局部修改和写后复核，减少误覆盖和上下文浪费。删除操作不由 MCP 执行，工具只会提示需要在 Apifox 客户端手动删除哪些资源。

## ✨ 功能特性

*   **API 接口管理**:
    *   列出接口 (`list_api_endpoints`)
    *   批量获取接口轻量摘要 (`batch_get_api_endpoint_summaries`) - 只返回名称、描述、标签、参数数量、响应码
    *   获取接口详情 (`get_api_endpoint_detail`)
    *   获取完整接口快照 (`get_api_endpoint_snapshot`) - 修改旧接口前建议先读取
    *   创建接口 (`create_api_endpoint`) - 只写入显式传入的响应
    *   安全更新接口元信息 (`patch_api_endpoint_metadata`) - 只改名称、描述、标签并保留原内容
    *   安全局部更新接口 (`patch_api_endpoint_operation`) - 可一次更新参数、请求/响应 Schema 片段和示例，并做写后复核
    *   批量安全修改接口名称 (`batch_patch_api_endpoint_titles`) - 只改名称并做写后复核
    *   全量替换接口 (`update_api_endpoint`) - 需要 `confirm_replace=True`
    *   接口完整性检查 (`check_api_responses`, `audit_all_api_responses`)
*   **批量操作与操作日志**:
    *   统一批量执行 (`batch_execute`) - 支持 endpoint/schema/folder 的 create/update/patch；delete 请求只返回手动删除指引，不执行删除
    *   操作日志列表 (`list_operation_logs`) - 查看最近写操作、状态和目标
    *   撤销写操作 (`undo_operation`) - 根据日志尝试恢复 update/patch；create 只能提示手动删除创建的资源
*   **数据模型 (Schema) 管理**:
    *   列出模型 (`list_schemas`)
    *   获取模型详情 (`get_schema_detail`)
    *   创建模型 (`create_schema`)
    *   更新模型 (`update_schema`)
*   **其他管理**:
    *   目录管理 (`list_folders`, `create_folder`)
    *   标签管理 (`list_tags`)
    *   按标签获取接口 (`get_apis_by_tag`, `add_tag_to_api`)
    *   配置检查 (`check_apifox_config`)

## 🛠️ 安装

确保你的系统中已安装 Python 3.10 或更高版本。

1.  **克隆项目**
    ```bash
    git clone <repository_url>
    cd <repository_name>
    ```

2.  **创建并激活虚拟环境 (可选但推荐)**

    **使用 uv**
    ```bash
    uv venv
    # 激活虚拟环境
    # Windows
    .venv\Scripts\activate
    # macOS/Linux
    source .venv/bin/activate
    ```

    **使用 venv**
    ```bash
    python -m venv .venv
    # Windows
    .venv\Scripts\activate
    # macOS/Linux
    source .venv/bin/activate
    ```

3.  **安装依赖**

    本项目支持使用 [uv](https://docs.astral.sh/uv/) (推荐用于本地开发) 或 pip 来安装依赖。

    **使用 uv (推荐，更快的本地开发)**
    ```bash
    # 安装 uv (如果尚未安装)
    curl -LsSf https://astral.sh/uv/install.sh | sh
    
    # 安装依赖
    uv sync
    
    # 运行 MCP server
    uv run python -m apifox_mcp.main
    ```

    **使用 pip (传统方式)**
    ```bash
    pip install mcp[cli] requests
    
    # 运行 MCP server
    python -m apifox_mcp.main
    ```

## ⚙️ 配置

在使用前，你需要设置以下环境变量来连接你的 Apifox 项目。

| 环境变量 | 描述 | 获取方式 |
| :--- | :--- | :--- |
| `APIFOX_TOKEN` | Apifox 开放 API 令牌 | Apifox 客户端 -> 账号设置 -> API 访问令牌 |
| `APIFOX_PROJECTS` | 可用项目列表，JSON 数组 | 项目概览页 -> 项目设置 -> 基本设置 -> ID |
| `APIFOX_MCP_LOG_DIR` | 操作日志目录，默认 `.apifox-mcp-logs` | 可选；建议 Docker 场景挂载持久化目录 |

> 修改 `APIFOX_TOKEN` 或 `APIFOX_PROJECTS` 后，已经启动的 MCP server 不会自动读取新值。请重启终端和 AI/Codex 会话；如果是通过 `codex mcp add --env ...` 注册的，还需要先 `codex mcp remove apifox`，再用新的环境变量重新执行 `codex mcp add apifox ...`。

## 重点⚠️
### APIFOX_TOKEN获取方式
<img width="1594" height="1029" alt="截屏2025-12-17 01 58 51" src="https://github.com/user-attachments/assets/aad5da36-a99d-484b-959c-116918897487" />


### APIFOX_PROJECTS 获取方式

<img width="2032" height="1167" alt="截屏2025-12-17 01 57 06" src="https://github.com/user-attachments/assets/a381baf8-7da0-4d88-950c-ac8b78c7af8d" />

`APIFOX_PROJECTS` 需要配置为 JSON 数组，支持多个项目：

```bash
export APIFOX_PROJECTS='[
  {"name":"主项目","id":"7575229"},
  {"name":"测试项目","id":"1234567"}
]'
```


### 设置项目文档为公开
ps:我实际使用发现只有设置为文档发布才能正常操作项目

 <img width="1594" height="1029" alt="截屏2025-12-17 01 55 12" src="https://github.com/user-attachments/assets/59cb26ea-26af-47a4-8329-aabe4ec63bce" />

## 🐳 使用方法 (Docker)

### Codex 团队推荐：使用 GHCR 镜像

本项目的 GitHub Actions 会在 `main` 分支和 `v*` 标签推送时自动构建 Docker 镜像并发布到 GHCR。

团队成员无需克隆源码，先在当前终端设置环境变量：

```bash
export APIFOX_TOKEN="your_token_here"
export APIFOX_PROJECTS='[{"name":"主项目","id":"7575229"},{"name":"测试项目","id":"1234567"}]'
```

然后直接注册到 Codex 即可：

```bash
codex mcp add apifox \
  --env APIFOX_TOKEN="$APIFOX_TOKEN" \
  --env APIFOX_PROJECTS="$APIFOX_PROJECTS" \
  --env MCP_CLIENT_NAME="codex" \
  -- sh -lc '
client="${MCP_CLIENT_NAME:-codex}"
workspace="$(basename "$PWD" | tr -cs "A-Za-z0-9_.-" "-" | tr "[:upper:]" "[:lower:]" | sed "s/^-//;s/-$//")"
suffix="$(openssl rand -hex 2 2>/dev/null || LC_ALL=C tr -dc "a-z0-9" </dev/urandom | head -c 4)"
docker run -i --rm \
    --name "apifox-mcp_${client}_${workspace:-workspace}_${suffix}" \
    --label app=apifox-mcp \
    --label mcp.client="$client" \
    --label mcp.workspace="${workspace:-workspace}" \
    -e APIFOX_TOKEN \
    -e APIFOX_PROJECTS \
    ghcr.io/frequenk/apifox-mcp:latest
'
```

推荐生产或团队固定版本时使用 tag 镜像：

```bash
codex mcp add apifox \
  --env APIFOX_TOKEN="$APIFOX_TOKEN" \
  --env APIFOX_PROJECTS="$APIFOX_PROJECTS" \
  --env MCP_CLIENT_NAME="codex" \
  -- sh -lc '
client="${MCP_CLIENT_NAME:-codex}"
workspace="$(basename "$PWD" | tr -cs "A-Za-z0-9_.-" "-" | tr "[:upper:]" "[:lower:]" | sed "s/^-//;s/-$//")"
suffix="$(openssl rand -hex 2 2>/dev/null || LC_ALL=C tr -dc "a-z0-9" </dev/urandom | head -c 4)"
docker run -i --rm \
    --name "apifox-mcp_${client}_${workspace:-workspace}_${suffix}" \
    --label app=apifox-mcp \
    --label mcp.client="$client" \
    --label mcp.workspace="${workspace:-workspace}" \
    -e APIFOX_TOKEN \
    -e APIFOX_PROJECTS \
    ghcr.io/frequenk/apifox-mcp:v0.1.0
'
```

> `codex mcp add --env` 需要使用 `KEY=VALUE` 形式。如果希望长期生效，可将上面的 `export` 写入 `~/.zshrc` 或 `~/.bashrc`。修改 `.zshrc`、`.bashrc` 或当前 shell 中的环境变量后，需要重启终端；已经运行中的 MCP server/容器不会自动刷新环境变量。若已注册过 MCP，请 `codex mcp remove apifox` 后重新执行 `codex mcp add apifox ...`。容器名格式为 `apifox-mcp_{工具名}_{启动目录名}_{四位随机码}`，并带有 `app=apifox-mcp` label。

注册后可检查：

```bash
codex mcp list
codex mcp get apifox
```

如需更新到最新镜像：

```bash
docker pull ghcr.io/frequenk/apifox-mcp:latest
codex mcp remove apifox
```

然后重新执行上面的 `codex mcp add apifox ...` 注册命令。已经运行中的 Codex/AI Agent 会继续使用旧容器，关闭对应会话后再重新启动即可使用新镜像。

同理，更新 `APIFOX_PROJECTS`、`APIFOX_TOKEN` 等环境变量后，也需要关闭当前 Codex/AI 会话，重新打开终端并重新注册 MCP，才能让新项目列表生效。可用 `check_apifox_config` 确认 MCP 实际读取到的项目数量。

如需卸载或重新配置该 MCP：

```bash
codex mcp remove apifox
```

如需同时清理本地 Docker 镜像缓存：

```bash
docker rmi ghcr.io/frequenk/apifox-mcp:latest
```

> 首次发布 GHCR 镜像后，请在 GitHub Packages 中确认镜像可见性。如果仓库公开，建议将 package 设置为 public，团队成员即可免登录拉取。

### 方法一：从源码构建

```bash
git clone https://github.com/iwen-conf/apifox-mcp.git
cd apifox-mcp
docker build -t apifox-mcp .
```

### 方法二：使用预构建镜像

从 [Releases](https://github.com/iwen-conf/apifox-mcp/releases) 下载 `apifox-mcp.tar`，然后加载：

```bash
docker load -i apifox-mcp.tar
```

### 配置 Claude Desktop

编辑 Claude Desktop 的配置文件：
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

#### 方式一：使用 Docker (推荐用于生产环境)

```json
{
  "mcpServers": {
    "apifox": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e", "APIFOX_TOKEN",
        "-e", "APIFOX_PROJECTS",
        "apifox-mcp"
      ],
      "env": {
        "APIFOX_TOKEN": "your_token_here",
        "APIFOX_PROJECTS": "[{\"name\":\"主项目\",\"id\":\"7575229\"}]"
      }
    }
  }
}
```

#### 方式二：使用 uv (推荐用于本地开发)

```json
{
  "mcpServers": {
    "apifox": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/apifox-mcp",
        "python",
        "-m",
        "apifox_mcp.main"
      ],
      "env": {
        "APIFOX_TOKEN": "your_token_here",
        "APIFOX_PROJECTS": "[{\"name\":\"主项目\",\"id\":\"7575229\"}]"
      }
    }
  }
}
```

> **注意**: 
> - 请将 `your_token_here` 和 `APIFOX_PROJECTS` 中的项目名称、项目 ID 替换为你的实际凭证
> - 使用 uv 方式时，请将 `/path/to/apifox-mcp` 替换为实际的项目路径
> - 更新环境变量后要重启终端和 MCP 进程；Codex 注册方式还需要重新 `codex mcp remove` / `codex mcp add`

### 3. 命令行运行 (可选)

你也可以直接在命令行中测试：

```bash
# 使用环境变量
docker run -i --rm \
  -e APIFOX_TOKEN=your_token \
  -e APIFOX_PROJECTS='[{"name":"主项目","id":"7575229"}]' \
  apifox-mcp

# 或者使用 .env 文件
docker run -i --rm --env-file .env apifox-mcp
```

## 📝 编写规范

本工具在创建和更新接口时强制执行以下规范，以确保文档质量：

1.  **中文描述**: 必须提供中文的 `title` 和 `description`。
2.  **完整 Schema**: `response_schema` 和 `request_body_schema` 中的每个字段必须包含 `description`。
3.  **真实示例**: 示例数据 (`example`) 必须是真实值，不能是简单的类型占位符 (如 "string")。
4.  **显式响应**: 系统不会自动补齐 400/401/500 等错误响应；只有明确传入 `responses` 时才会写入对应响应。

## 推荐工作流

### 轻量读取

当只需要批量检查或修改标题、说明、标签时，优先使用轻量工具：

- `batch_get_api_endpoint_summaries`: 批量读取名称、描述、标签、参数数量、响应码，不返回完整 schema/components。
- `get_api_endpoint_snapshot`: 只有准备做复杂修改或全量替换时再读取完整 operation 快照。

### 局部修改优先

修改旧接口的名称、说明、标签时，优先使用：

```text
patch_api_endpoint_metadata(project_id, path, method, title?, description?, tags?)
```

该工具会先导出完整接口定义，只替换指定字段，再导入覆盖。写入后会重新导出接口做复核，并返回紧凑 diff，例如名称、描述、标签、响应码变化，以及参数/请求体/响应是否出现非预期丢失。

当需要同时修改参数、请求体、响应字段或示例时，优先使用：

```text
patch_api_endpoint_operation(
  path,
  method,
  project_id?,
  title?,
  description?,
  tags?,
  query_params?,
  header_params?,
  path_params?,
  request_body_schema_patch?,
  request_body_example_patch?,
  response_schema_patch?,
  response_example_patch?,
  response_code="200",
  content_type="application/json",
  dry_run=False
)
```

该工具适合“已有接口加参数、补响应字段、更新 example”这类高频文档维护任务。它会保留未触达的参数、请求体、响应码、示例和 components，只对传入片段做递归合并；`required` 字段采用追加并集语义。写入后会自动复核参数名、响应示例字段和关键差异。

示例：

```text
patch_api_endpoint_operation(
  path="/jp/wechat/user/get-oss-config",
  method="GET",
  query_params=[
    {"name":"scene","type":"string","description":"OSS 使用场景","enum":["TEMP_PHOTO","REFUND_CREDENTIAL"],"required":false},
    {"name":"order_no","type":"string","description":"退款凭证场景下的订单号","required":false}
  ],
  response_schema_patch={
    "properties":{"scene":{"type":"string","description":"OSS 使用场景"}},
    "required":["scene"]
  },
  response_example_patch={"data":{"scene":"REFUND_CREDENTIAL"}}
)
```

如果 `APIFOX_PROJECTS` 只配置了一个项目，`project_id` 可以不传；如果配置多个项目，可以传项目 ID 或项目名称。

### 全量替换需要确认

`update_api_endpoint` 是全量替换工具，默认拒绝执行。只有确认要重建完整接口定义时，才设置：

```text
confirm_replace=True
```

全量替换写入后也会返回写后复核和操作日志 ID，方便 AI 判断本次修改范围是否符合预期。

### 批量操作

通用批量写操作使用：

```text
batch_execute(project_id, items=[...])
```

支持的组合：

- endpoint: `create` / `update` / `patch`
- schema: `create` / `update`
- folder: `create`

如果传入 `delete` 操作，MCP 不会调用 Apifox 删除 API，只会返回“请在 Apifox 客户端手动删除”的目标提示，并在批量汇总中计为失败，避免误判为已删除。

执行策略：

- 按 `items` 顺序执行。
- 单个操作失败不会阻塞后续操作。
- 返回每个子操作的关键输出，包括写后复核、操作日志 ID 或失败原因。
- 支持 `dry_run=True` 做全局紧凑预览：只做参数校验和操作摘要，不调用真实写入工具，不返回完整 OpenAPI。

### 操作日志与恢复

所有写操作都会生成本地操作日志，可使用：

- `list_operation_logs(project_id, limit)`
- `undo_operation(operation_id)`

`undo_operation` 会根据日志尝试恢复：

- create: 不自动删除资源，只提示应在 Apifox 客户端手动删除的目标
- update/patch: 使用 before 快照重新导入

接口撤销会优先使用日志中保存的 operation 和 components 上下文恢复，避免只恢复 operation 而丢失 schema 引用。

## ⚠️ 能力边界

- 批量只读名称、描述、标签、参数数量、响应码时，优先使用 `batch_get_api_endpoint_summaries`，避免把完整 schema/components 塞进上下文。
- 批量修改接口名称时，可以使用 `batch_patch_api_endpoint_titles`；更通用的批量 create/update/patch 使用 `batch_execute`。
- 修改旧接口的名称、描述或标签时，优先使用 `patch_api_endpoint_metadata`，该工具会保留原参数、请求体、响应、示例和组件引用。
- 修改旧接口的参数、请求体字段、响应字段或示例时，优先使用 `patch_api_endpoint_operation`，避免读取完整快照后手动重组 OpenAPI。
- `update_api_endpoint` 是全量替换工具，默认会拒绝执行；只有确认要重建完整接口时才设置 `confirm_replace=True`。
- 修改旧接口前建议先调用 `get_api_endpoint_snapshot` 查看完整结构化快照。
- MCP 不执行删除。需要删除接口、数据模型或目录时，请先用轻量查询工具列出目标，再在 Apifox 客户端中手动删除。
- 恢复能力依赖操作日志和 Apifox 导入能力。接口恢复会携带日志中的 components 上下文；如果引用的外部资源未在日志中出现，可能需要人工补齐。
- 默认操作日志目录为 `.apifox-mcp-logs`。容器或团队环境建议通过 `APIFOX_MCP_LOG_DIR` 指向持久化目录。
- 写操作可优先使用 `dry_run=True` 预览。预览默认返回紧凑摘要，不返回完整 OpenAPI，避免占用过多上下文。
- 创建接口和 CRUD 生成器不会自动补齐错误响应；如需错误响应，请显式传入或在 Apifox 客户端维护。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！
