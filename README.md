# Apifox MCP Server v2

面向 AI 的 Apifox 接口文档读写服务。v2 将读取、批量写入、校验和恢复收敛为少量高层工具，避免把整个项目 OpenAPI 塞入模型上下文。

## 核心能力

- `get_apifox_status`：检查连接与项目。
- `search_api_documents`：统一搜索接口和 Schema。
- `read_api_documents`：批量读取目标及其传递依赖，支持字段筛选和分页。
- `apply_api_document_changes`：一次导入多个接口、Schema 和目录变更，并自动回读校验。
- `audit_api_documents`：检查响应、描述、示例和引用。
- `list_change_logs`：查看分组操作日志。
- `undo_change`：恢复可恢复的分组写入。

推荐流程：搜索目标、批量读取、一次提交全部变更。写入工具已经包含强制回读，无需成功后再次读取。

## 写入语义

- `patch`：对象递归合并，数组整体替换。
- `remove_paths`：使用 JSON Pointer 显式删除字段。
- `replace`：必须传 `confirm_replace=true`。
- 全部变更先校验，再通过一份最小 OpenAPI 文档导入。
- 写后字段或 `$ref` 不符合预期时判定失败，并恢复已有资源。
- 不支持删除整个接口、Schema 或目录。

示例：一次更新接口描述、响应示例和关联 Schema。

```json
{
  "project_id": "remote-service",
  "endpoint_changes": [
    {
      "path": "/jcp/wechat/work/get-work-details",
      "method": "GET",
      "action": "patch",
      "patch": {
        "description": "获取作品完整详情",
        "responses": {
          "200": {
            "content": {
              "application/json": {
                "example": {"errorcode": 0, "errormessage": "success", "data": {}}
              }
            }
          }
        }
      }
    }
  ],
  "schema_changes": [
    {
      "name": "JcpWorkDetails",
      "action": "patch",
      "patch": {
        "properties": {
          "generated_image_results": {
            "type": "array",
            "description": "增强后归档图片",
            "items": {"$ref": "#/components/schemas/JcpGeneratedImage"}
          }
        }
      }
    }
  ]
}
```

## 配置

```bash
export APIFOX_TOKEN="your-token"
export APIFOX_PROJECTS='[{"name":"remote-service","id":"7575229"}]'
```

可选配置：

- `APIFOX_MCP_LOG_DIR`：操作日志目录，默认 `.apifox-mcp-logs`。
- `APIFOX_MCP_CACHE_TTL_SECONDS`：OpenAPI 缓存秒数，默认 `300`。

## Docker

```bash
docker run --pull=always -i --rm \
  -e APIFOX_TOKEN \
  -e APIFOX_PROJECTS \
  ghcr.io/frequenk/apifox-mcp:latest
```

各客户端配置见 [docs/clients](./docs/clients/README.md)。v2 删除了旧工具名，升级后需要重启 MCP 客户端以重新加载工具列表。

## 开发与测试

```bash
uv sync --frozen
uv run pytest -q
```

真实写测使用 Apifox `myself` 项目的永久夹具，默认不会运行：

```bash
APIFOX_MCP_LIVE_TEST=1 \
APIFOX_MCP_LIVE_TEST_PROJECT=myself \
uv run pytest tests/test_live_myself.py -q
```

真实测试会使用 `GET /mcp-tests/document-sync`、`McpIntegrationItem` 和 `McpIntegrationResponse`，完成后恢复原始内容。测试基准见 [测试结果](./docs/test-results/apifox-mcp-v2.md)。
