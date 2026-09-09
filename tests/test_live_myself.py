import copy
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("APIFOX_MCP_LIVE_TEST") != "1",
    reason="仅在显式开启真实 Apifox 写测时运行",
)


ITEM_SCHEMA = {
    "type": "object",
    "description": "MCP 集成测试条目",
    "properties": {
        "id": {"type": "integer", "description": "测试条目 ID"},
        "probe": {"type": "string", "description": "引用保持探针"},
    },
    "required": ["id", "probe"],
}

RESPONSE_SCHEMA = {
    "type": "object",
    "description": "MCP 集成测试响应",
    "properties": {
        "code": {"type": "integer", "description": "错误码"},
        "items": {
            "type": "array",
            "description": "测试条目列表",
            "items": {"$ref": "#/components/schemas/McpIntegrationItem"},
        },
    },
    "required": ["code", "items"],
}

ENDPOINT = {
    "summary": "MCP 文档同步测试",
    "description": "仅用于 Apifox MCP 真实读写回归",
    "tags": ["MCP集成测试"],
    "responses": {
        "200": {
            "description": "成功",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/McpIntegrationResponse"},
                    "example": {"code": 0, "items": [{"id": 1, "probe": "baseline"}]},
                }
            },
        }
    },
}


def test_myself_real_read_write_roundtrip(tmp_path, monkeypatch):
    from apifox_mcp.tools import v2_tools

    project = os.getenv("APIFOX_MCP_LIVE_TEST_PROJECT", "myself")
    monkeypatch.setattr(v2_tools.operation_logger, "log_dir", tmp_path)
    document, _ = v2_tools.repository.export(v2_tools._project_id(project), force=True)
    schemas = document.get("components", {}).get("schemas", {})
    operation = document.get("paths", {}).get("/mcp-tests/document-sync", {}).get("get")

    schema_changes = []
    if "McpIntegrationItem" not in schemas:
        schema_changes.append({"name": "McpIntegrationItem", "action": "create", "document": ITEM_SCHEMA})
    if "McpIntegrationResponse" not in schemas:
        schema_changes.append({"name": "McpIntegrationResponse", "action": "create", "document": RESPONSE_SCHEMA})
    endpoint_changes = []
    if operation is None:
        endpoint_changes.append(
            {
                "path": "/mcp-tests/document-sync",
                "method": "GET",
                "action": "create",
                "document": ENDPOINT,
            }
        )
    if schema_changes or endpoint_changes:
        bootstrap = v2_tools.apply_api_document_changes(
            project_id=project,
            schema_changes=schema_changes,
            endpoint_changes=endpoint_changes,
            folder_changes=[{"name": "MCP集成测试", "action": "create"}],
        )
        assert bootstrap["ok"], bootstrap

    status = v2_tools.get_apifox_status(project_id=project)
    assert status["ok"] is True
    assert status["probe_performed"] is False
    assert status["metrics"]["request_count"] == 0

    before = v2_tools.read_api_documents(
        project_id=project,
        endpoints=[{"path": "/mcp-tests/document-sync", "method": "GET"}],
        schemas=["McpIntegrationItem", "McpIntegrationResponse"],
        force_refresh=True,
    )
    assert set(before["components"]["schemas"]) == {"McpIntegrationItem", "McpIntegrationResponse"}
    assert all("components" not in item and "schemas" not in item for item in before["documents"])
    assert before["output_chars"] <= 2120
    before_operation = copy.deepcopy(before["documents"][0]["operation"])
    before_item = copy.deepcopy(before["components"]["schemas"]["McpIntegrationItem"])

    try:
        changed = v2_tools.apply_api_document_changes(
            project_id=project,
            schema_changes=[
                {
                    "name": "McpIntegrationItem",
                    "action": "patch",
                    "patch": {"properties": {"probe": {"description": "引用保持探针（changed）"}}},
                }
            ],
            endpoint_changes=[
                {
                    "path": "/mcp-tests/document-sync",
                    "method": "GET",
                    "action": "patch",
                    "patch": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "example": {"code": 0, "items": [{"id": 1, "probe": "changed"}]}
                                    }
                                }
                            }
                        }
                    },
                }
            ],
        )
        assert changed["ok"], changed
        assert changed["metrics"]["request_count"] <= 3

        read_back = v2_tools.read_api_documents(
            project_id=project,
            endpoints=[{"path": "/mcp-tests/document-sync", "method": "GET"}],
            force_refresh=True,
        )
        schemas = read_back["components"]["schemas"]
        assert schemas["McpIntegrationResponse"]["properties"]["items"]["items"]["$ref"].endswith("McpIntegrationItem")
        assert schemas["McpIntegrationItem"]["properties"]["probe"]["description"].endswith("（changed）")
    finally:
        restored = v2_tools.apply_api_document_changes(
            project_id=project,
            schema_changes=[
                {
                    "name": "McpIntegrationItem",
                    "action": "replace",
                    "confirm_replace": True,
                    "document": before_item,
                }
            ],
            endpoint_changes=[
                {
                    "path": "/mcp-tests/document-sync",
                    "method": "GET",
                    "action": "replace",
                    "confirm_replace": True,
                    "document": before_operation,
                }
            ],
        )
        assert restored["ok"], restored
