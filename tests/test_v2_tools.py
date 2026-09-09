import asyncio

from conftest import FakeRepository

from apifox_mcp.tools import v2_tools


def setup_tools(monkeypatch, tmp_path, document, strip_nested_ref=False):
    fake = FakeRepository(document, strip_nested_ref=strip_nested_ref)
    monkeypatch.setattr(v2_tools, "repository", fake)
    monkeypatch.setattr(v2_tools, "_project_id", lambda project_id: "1")
    monkeypatch.setattr(v2_tools.operation_logger, "log_dir", tmp_path)
    return fake


def test_read_documents_returns_only_reachable_components(monkeypatch, tmp_path, fixture_document):
    setup_tools(monkeypatch, tmp_path, fixture_document)

    result = v2_tools.read_api_documents(
        project_id="1",
        endpoints=[{"path": "/orders", "method": "GET"}],
    )

    schemas = result["documents"][0]["components"]["schemas"]
    assert set(schemas) == {"OrderResponse", "OrderItem"}
    assert result["output_chars"] < 10000


def test_read_documents_supports_pagination(monkeypatch, tmp_path, fixture_document):
    fixture_document["paths"]["/orders"]["get"]["description"] = "长描述" * 10000
    setup_tools(monkeypatch, tmp_path, fixture_document)

    result = v2_tools.read_api_documents(
        project_id="1",
        endpoints=[{"path": "/orders", "method": "GET"}],
        max_output_chars=10000,
    )

    assert result["paginated"] is True
    assert result["next_cursor"] == 10000
    assert len(result["chunk"]) == 10000

    chunks = [result["chunk"]]
    cursor = result["next_cursor"]
    while cursor is not None:
        page = v2_tools.read_api_documents(
            project_id="1",
            endpoints=[{"path": "/orders", "method": "GET"}],
            max_output_chars=10000,
            cursor=cursor,
        )
        chunks.append(page["chunk"])
        cursor = page["next_cursor"]

    import json

    parsed = json.loads("".join(chunks))
    assert parsed["documents"][0]["operation"]["summary"] == "订单列表"


def test_grouped_apply_uses_one_import_and_verifies(monkeypatch, tmp_path, fixture_document):
    fake = setup_tools(monkeypatch, tmp_path, fixture_document)
    result = v2_tools.apply_api_document_changes(
        project_id="1",
        schema_changes=[
            {
                "name": "OrderItem",
                "action": "patch",
                "patch": {"properties": {"cover_url": {"type": "string", "description": "封面地址"}}},
            }
        ],
        endpoint_changes=[
            {
                "path": "/orders",
                "method": "GET",
                "action": "patch",
                "patch": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "example": {
                                        "code": 0,
                                        "data": [
                                            {"id": 1, "name": "测试订单", "cover_url": "https://example.com/a.jpg"}
                                        ],
                                    }
                                }
                            }
                        }
                    }
                },
            }
        ],
    )

    assert result["ok"] is True
    assert result["verified"] is True
    assert fake.import_count == 1
    assert fake.export_count == 2
    assert result["component_count"] == 2


def test_write_review_detects_silent_ref_loss_and_rolls_back(monkeypatch, tmp_path, fixture_document):
    fake = setup_tools(monkeypatch, tmp_path, fixture_document, strip_nested_ref=True)
    result = v2_tools.apply_api_document_changes(
        project_id="1",
        schema_changes=[
            {
                "name": "OrderResponse",
                "action": "patch",
                "patch": {"properties": {"data": {"description": "订单结果列表"}}},
            }
        ],
    )

    assert result["ok"] is False
    assert any("$ref" in mismatch for mismatch in result["mismatches"])
    assert result["rolled_back"] is True
    assert fake.import_count == 2


def test_apply_rejects_missing_descriptions(monkeypatch, tmp_path, fixture_document):
    setup_tools(monkeypatch, tmp_path, fixture_document)

    result = v2_tools.apply_api_document_changes(
        project_id="1",
        schema_changes=[
            {
                "name": "OrderItem",
                "action": "patch",
                "patch": {"properties": {"cover_url": {"type": "string"}}},
            }
        ],
    )

    assert result["ok"] is False
    assert result["stage"] == "validation"
    assert "OrderItem.cover_url 缺少 description" in result["issues"]


def test_apply_rejects_missing_inline_response_description(monkeypatch, tmp_path, fixture_document):
    setup_tools(monkeypatch, tmp_path, fixture_document)

    result = v2_tools.apply_api_document_changes(
        project_id="1",
        endpoint_changes=[
            {
                "path": "/orders",
                "method": "GET",
                "action": "patch",
                "patch": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/xml": {
                                    "schema": {"type": "object", "properties": {"id": {"type": "integer"}}}
                                }
                            }
                        }
                    }
                },
            }
        ],
    )

    assert result["ok"] is False
    assert any("responses/200/application/xml.id 缺少 description" in issue for issue in result["issues"])


def test_apply_skips_import_when_there_is_no_change(monkeypatch, tmp_path, fixture_document):
    fake = setup_tools(monkeypatch, tmp_path, fixture_document)
    result = v2_tools.apply_api_document_changes(
        project_id="1",
        schema_changes=[
            {
                "name": "OrderItem",
                "action": "patch",
                "patch": {"description": "订单"},
            }
        ],
    )

    assert result["status"] == "no_change"
    assert fake.import_count == 0


def test_apply_rejects_stale_revision(monkeypatch, tmp_path, fixture_document):
    setup_tools(monkeypatch, tmp_path, fixture_document)

    result = v2_tools.apply_api_document_changes(
        project_id="1",
        schema_changes=[
            {
                "name": "OrderItem",
                "action": "patch",
                "expected_revision": "stale",
                "patch": {"description": "新描述"},
            }
        ],
    )

    assert result["ok"] is False
    assert "并发变化" in result["error"]["message"]


def test_apply_rejects_example_that_does_not_match_schema(monkeypatch, tmp_path, fixture_document):
    setup_tools(monkeypatch, tmp_path, fixture_document)

    result = v2_tools.apply_api_document_changes(
        project_id="1",
        endpoint_changes=[
            {
                "path": "/orders",
                "method": "GET",
                "action": "patch",
                "patch": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "example": {"code": 0, "data": [{"id": "wrong", "name": "测试订单"}]}
                                }
                            }
                        }
                    }
                },
            }
        ],
    )

    assert result["ok"] is False
    assert result["stage"] == "validation"
    assert any("not of type 'integer'" in issue for issue in result["issues"])


def test_undo_restores_grouped_change(monkeypatch, tmp_path, fixture_document):
    fake = setup_tools(monkeypatch, tmp_path, fixture_document)
    changed = v2_tools.apply_api_document_changes(
        project_id="1",
        schema_changes=[
            {
                "name": "OrderItem",
                "action": "patch",
                "patch": {"description": "修改后的订单"},
            }
        ],
    )

    undone = v2_tools.undo_change(changed["operation_id"])

    assert undone["ok"] is True
    assert fake.document["components"]["schemas"]["OrderItem"]["description"] == "订单"


def test_audit_finds_nested_missing_description(monkeypatch, tmp_path, fixture_document):
    fixture_document["components"]["schemas"]["OrderItem"]["properties"]["name"].pop("description")
    setup_tools(monkeypatch, tmp_path, fixture_document)

    result = v2_tools.audit_api_documents(
        project_id="1",
        endpoints=[{"path": "/orders", "method": "GET"}],
    )

    assert result["ok"] is False
    assert any("OrderItem.name" in issue for issue in result["findings"][0]["issues"])


def test_search_combines_endpoint_and_schema(monkeypatch, tmp_path, fixture_document):
    setup_tools(monkeypatch, tmp_path, fixture_document)

    result = v2_tools.search_api_documents(project_id="1", query="订单")

    assert {item["resource_type"] for item in result["results"]} == {"endpoint", "schema"}


def test_runtime_only_registers_seven_v2_tools():
    from apifox_mcp.config import mcp

    tools = asyncio.run(mcp.list_tools())

    assert {tool.name for tool in tools} == {
        "get_apifox_status",
        "search_api_documents",
        "read_api_documents",
        "apply_api_document_changes",
        "audit_api_documents",
        "list_change_logs",
        "undo_change",
    }


def test_tool_errors_are_structured():
    from apifox_mcp.config import mcp

    @mcp.tool()
    def fail_for_test():
        raise RuntimeError("boom")

    result = fail_for_test()

    assert result == {
        "ok": False,
        "error": {"code": "tool_error", "tool": "fail_for_test", "message": "boom"},
    }
