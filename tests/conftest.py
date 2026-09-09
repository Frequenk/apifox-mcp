import copy

import pytest

from apifox_mcp.core import RequestMetrics


def make_openapi_fixture():
    return {
        "openapi": "3.1.0",
        "info": {"title": "测试项目", "version": "1.0.0"},
        "tags": [{"name": "订单"}],
        "paths": {
            "/orders": {
                "get": {
                    "summary": "订单列表",
                    "description": "获取订单列表",
                    "tags": ["订单"],
                    "parameters": [],
                    "responses": {
                        "200": {
                            "description": "成功",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/OrderResponse"},
                                    "example": {
                                        "code": 0,
                                        "data": [{"id": 1, "name": "测试订单"}],
                                    },
                                }
                            },
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "OrderItem": {
                    "type": "object",
                    "description": "订单",
                    "properties": {
                        "id": {"type": "integer", "description": "订单 ID"},
                        "name": {"type": "string", "description": "订单名称"},
                    },
                },
                "OrderResponse": {
                    "type": "object",
                    "description": "订单列表响应",
                    "properties": {
                        "code": {"type": "integer", "description": "错误码"},
                        "data": {
                            "type": "array",
                            "description": "订单列表",
                            "items": {"$ref": "#/components/schemas/OrderItem"},
                        },
                    },
                },
                "Unrelated": {
                    "type": "object",
                    "properties": {"secret": {"type": "string", "description": "无关字段"}},
                },
            }
        },
    }


class FakeRepository:
    def __init__(self, document=None, strip_nested_ref=False):
        self.document = copy.deepcopy(document or make_openapi_fixture())
        self.strip_nested_ref = strip_nested_ref
        self.export_count = 0
        self.import_count = 0
        self.client = type("FakeClient", (), {})()
        self.client.metrics = RequestMetrics()
        self.client.reset_metrics = lambda: setattr(self.client, "metrics", RequestMetrics())

    def export(self, project_id, force=False):
        self.export_count += 1
        self.client.metrics.request_count += 1
        return copy.deepcopy(self.document), False

    def import_spec(self, project_id, spec):
        self.import_count += 1
        self.client.metrics.request_count += 1
        for path, item in spec.get("paths", {}).items():
            self.document.setdefault("paths", {}).setdefault(path, {}).update(copy.deepcopy(item))
        self.document.setdefault("components", {}).setdefault("schemas", {}).update(
            copy.deepcopy(spec.get("components", {}).get("schemas", {}))
        )
        if "tags" in spec:
            self.document["tags"] = copy.deepcopy(spec["tags"])
        if self.strip_nested_ref and self.import_count == 1:
            self.document["components"]["schemas"]["OrderResponse"]["properties"]["data"]["items"] = {
                "type": "object",
                "properties": {},
            }
        return {"data": {"counters": {"endpointUpdated": 1, "schemaUpdated": 1}}}

    def cache_state(self):
        return {}


@pytest.fixture
def fixture_document():
    return make_openapi_fixture()
