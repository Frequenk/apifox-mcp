import importlib
import os
import sys
import tempfile
import types
import unittest
from copy import deepcopy


def install_mcp_stub():
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")

    class FakeFastMCP:
        def __init__(self, *args, **kwargs):
            pass

        def tool(self):
            def decorator(func):
                return func

            return decorator

    fastmcp_module.FastMCP = FakeFastMCP
    sys.modules.setdefault("mcp", types.ModuleType("mcp"))
    sys.modules.setdefault("mcp.server", types.ModuleType("mcp.server"))
    sys.modules["mcp.server.fastmcp"] = fastmcp_module


def reload_project_modules():
    for name in list(sys.modules):
        if name.startswith("apifox_mcp"):
            del sys.modules[name]


class ProjectConfigTests(unittest.TestCase):
    def setUp(self):
        install_mcp_stub()
        reload_project_modules()
        self.old_env = os.environ.copy()
        self.log_tmp = tempfile.TemporaryDirectory()
        os.environ["APIFOX_MCP_LOG_DIR"] = self.log_tmp.name

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)
        self.log_tmp.cleanup()
        reload_project_modules()

    def test_config_requires_apifox_projects(self):
        os.environ.pop("APIFOX_PROJECTS", None)
        os.environ["APIFOX_TOKEN"] = "token"

        utils = importlib.import_module("apifox_mcp.utils")

        self.assertIn("APIFOX_PROJECTS", utils._validate_config())

    def test_resolve_project_id_from_configured_projects(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"},{"name":"测试项目","id":"1234567"}]'

        utils = importlib.import_module("apifox_mcp.utils")

        self.assertIsNone(utils._validate_config())
        self.assertEqual(utils._resolve_project_id("1234567"), "1234567")
        self.assertIn("主项目", utils._format_project_options())
        self.assertIn("7575229", utils._format_project_options())

    def test_rejects_unknown_project_id(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"}]'

        utils = importlib.import_module("apifox_mcp.utils")

        with self.assertRaises(ValueError) as ctx:
            utils._resolve_project_id("999")

        self.assertIn("未配置的 project_id", str(ctx.exception))
        self.assertIn("7575229", str(ctx.exception))

    def test_response_consistency_no_envelope_recommendation(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"}]'

        module = importlib.import_module("apifox_mcp.tools.validation_tools")
        module._make_request = lambda *args, **kwargs: {
            "success": True,
            "data": {
                "paths": {
                    "/orders": {
                        "get": {
                            "responses": {
                                "200": {
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {"id": {"type": "integer"}}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        self.assertNotIn("{code, message, data}", module.check_response_consistency.__doc__)
        self.assertNotIn("{code, message, details}", module.check_response_consistency.__doc__)
        output = module.check_response_consistency("7575229")
        self.assertNotIn("{code, message, data}", output)
        self.assertNotIn("{code, message, details}", output)

    def test_patch_metadata_preserves_existing_operation_details(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"}]'
        module = importlib.import_module("apifox_mcp.tools.api_tools")
        openapi_data = make_openapi_fixture()
        calls = []

        def fake_request(method, endpoint, data=None, params=None, use_public_api=True):
            calls.append({"method": method, "endpoint": endpoint, "data": data})
            if endpoint.endswith("/export-openapi?locale=zh-CN"):
                return {"success": True, "data": deepcopy(openapi_data)}
            if endpoint.endswith("/import-openapi?locale=zh-CN"):
                imported = json_loads(data["input"])
                operation = imported["paths"]["/orders"]["post"]
                self.assertEqual(operation["summary"], "新标题")
                self.assertEqual(operation["description"], "新描述")
                self.assertEqual(operation["parameters"][0]["name"], "source")
                self.assertEqual(
                    operation["requestBody"]["content"]["application/json"]["example"]["metadata"]["owner"],
                    "codex",
                )
                self.assertEqual(
                    operation["responses"]["200"]["content"]["application/json"]["example"]["status"],
                    "created",
                )
                self.assertIn("components", imported)
                return {"success": True, "data": {"data": {"counters": {"endpointUpdated": 1}}}}
            raise AssertionError(endpoint)

        module._make_request = fake_request

        result = module.patch_api_endpoint_metadata(
            project_id="7575229",
            path="/orders",
            method="POST",
            title="新标题",
            description="新描述",
        )

        self.assertIn("✅ 接口元信息更新成功", result)
        self.assertEqual(len([c for c in calls if "import-openapi" in c["endpoint"]]), 1)

    def test_patch_metadata_dry_run_does_not_import(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"}]'
        module = importlib.import_module("apifox_mcp.tools.api_tools")

        def fake_request(method, endpoint, data=None, params=None, use_public_api=True):
            if endpoint.endswith("/export-openapi?locale=zh-CN"):
                return {"success": True, "data": make_openapi_fixture()}
            if endpoint.endswith("/import-openapi?locale=zh-CN"):
                raise AssertionError("dry_run must not import")
            raise AssertionError(endpoint)

        module._make_request = fake_request

        result = module.patch_api_endpoint_metadata(
            project_id="7575229",
            path="/orders",
            method="POST",
            title="新标题",
            dry_run=True,
        )

        self.assertIn("DRY-RUN", result)
        self.assertIn("summary", result)
        self.assertNotIn("CreateOrderRequest", result)
        self.assertNotIn('"components"', result)

    def test_update_api_endpoint_requires_confirm_replace(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"}]'
        module = importlib.import_module("apifox_mcp.tools.api_tools")

        result = module.update_api_endpoint(
            project_id="7575229",
            path="/orders",
            method="POST",
            title="全量替换",
            description="全量替换",
            response_schema={"type": "object", "properties": {"id": {"type": "integer", "description": "ID"}}},
            response_example={"id": 1},
            request_body_schema={"type": "object", "properties": {"name": {"type": "string", "description": "名称"}}},
            request_body_example={"name": "订单"},
        )

        self.assertIn("全量覆盖", result)
        self.assertIn("confirm_replace=True", result)

    def test_operation_log_records_and_lists_entries(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"}]'
        module = importlib.import_module("apifox_mcp.operation_log")

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = module.OperationLog(log_dir=tmpdir)
            entry = logger.record(
                operation="update",
                resource_type="endpoint",
                project_id="7575229",
                target={"path": "/orders", "method": "POST"},
                before={"summary": "旧标题"},
                after={"summary": "新标题"},
            )

            self.assertEqual(entry["status"], "completed")
            self.assertIn("id", entry)
            logs = logger.list_logs(project_id="7575229")
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0]["target"]["path"], "/orders")

    def test_delete_api_endpoint_records_before_snapshot(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"}]'
        module = importlib.import_module("apifox_mcp.tools.api_tools")
        log_module = importlib.import_module("apifox_mcp.operation_log")
        openapi_data = make_openapi_fixture()
        imports = []

        with tempfile.TemporaryDirectory() as tmpdir:
            module.operation_logger = log_module.OperationLog(log_dir=tmpdir)

            def fake_request(method, endpoint, data=None, params=None, use_public_api=True):
                if endpoint.endswith("/export-openapi?locale=zh-CN"):
                    return {"success": True, "data": deepcopy(openapi_data)}
                if endpoint.endswith("/import-openapi?locale=zh-CN"):
                    imported = json_loads(data["input"])
                    imports.append(imported)
                    self.assertNotIn("post", imported["paths"].get("/orders", {}))
                    return {"success": True, "data": {"data": {"counters": {"endpointDeleted": 1}}}}
                raise AssertionError(endpoint)

            module._make_request = fake_request

            result = module.delete_api_endpoint("7575229", "/orders", "POST", confirm=True)

            self.assertIn("接口删除请求已提交", result)
            self.assertEqual(len(imports), 1)
            logs = module.operation_logger.list_logs(project_id="7575229")
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0]["operation"], "delete")
            self.assertEqual(logs[0]["before"]["summary"], "旧标题")
            self.assertIsNone(logs[0]["after"])

    def test_delete_api_endpoint_warns_when_post_verify_still_exists(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"}]'
        module = importlib.import_module("apifox_mcp.tools.api_tools")
        log_module = importlib.import_module("apifox_mcp.operation_log")
        openapi_data = make_openapi_fixture()

        with tempfile.TemporaryDirectory() as tmpdir:
            module.operation_logger = log_module.OperationLog(log_dir=tmpdir)

            def fake_request(method, endpoint, data=None, params=None, use_public_api=True):
                if endpoint.endswith("/export-openapi?locale=zh-CN"):
                    return {"success": True, "data": deepcopy(openapi_data)}
                if endpoint.endswith("/import-openapi?locale=zh-CN"):
                    return {"success": True, "data": {"data": {"counters": {"endpointDeleted": 0}}}}
                raise AssertionError(endpoint)

            module._make_request = fake_request

            result = module.delete_api_endpoint("7575229", "/orders", "POST", confirm=True)

            self.assertIn("未实际删除", result)
            logs = module.operation_logger.list_logs(project_id="7575229")
            self.assertEqual(logs[0]["status"], "failed")
            self.assertIn("目标仍存在", logs[0]["error"])

    def test_undo_endpoint_restores_components_from_log_context(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"}]'
        op_module = importlib.import_module("apifox_mcp.tools.operation_tools")
        log_module = importlib.import_module("apifox_mcp.operation_log")

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = log_module.OperationLog(log_dir=tmpdir)
            entry = logger.record(
                operation="delete",
                resource_type="endpoint",
                project_id="7575229",
                target={"path": "/orders", "method": "POST"},
                before=make_openapi_fixture()["paths"]["/orders"]["post"],
                after=None,
                context={
                    "before_components": {
                        "schemas": {
                            "OrderResponse": {
                                "type": "object",
                                "properties": {"id": {"type": "integer", "description": "ID"}},
                            }
                        }
                    }
                },
            )
            op_module.operation_logger = logger
            imported_specs = []

            def fake_request(method, endpoint, data=None, params=None, use_public_api=True):
                imported_specs.append(json_loads(data["input"]))
                return {"success": True, "data": {"data": {"counters": {"endpointUpdated": 1}}}}

            op_module._make_request = fake_request

            result = op_module.undo_operation(entry["id"])

            self.assertIn("已撤销接口操作", result)
            self.assertIn("撤销日志", result)
            self.assertIn("components", imported_specs[0])
            self.assertIn("OrderResponse", imported_specs[0]["components"]["schemas"])

    def test_delete_schema_and_folder_tools_exist_with_confirmation(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"}]'
        schema_module = importlib.import_module("apifox_mcp.tools.schema_tools")
        folder_module = importlib.import_module("apifox_mcp.tools.folder_tools")

        self.assertIn("安全提示", schema_module.delete_schema("7575229", "LegacyModel"))
        self.assertIn("安全提示", folder_module.delete_folder("7575229", "历史目录"))

    def test_batch_execute_continues_after_failed_item(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"}]'
        module = importlib.import_module("apifox_mcp.tools.batch_tools")
        calls = []

        def fake_create_schema(**kwargs):
            calls.append(kwargs["name"])
            if kwargs["name"] == "BrokenModel":
                return "❌ 创建失败: mock"
            return "✅ 数据模型创建成功!"

        module.schema_tools.create_schema = fake_create_schema

        result = module.batch_execute(
            project_id="7575229",
            items=[
                {"operation": "create", "resource_type": "schema", "name": "BrokenModel", "schema_type": "object"},
                {"operation": "create", "resource_type": "schema", "name": "UserModel", "schema_type": "object"},
            ],
        )

        self.assertEqual(calls, ["BrokenModel", "UserModel"])
        self.assertIn("汇总: 1 成功, 1 失败", result)

    def test_batch_execute_keeps_child_diff_and_log_id(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"}]'
        module = importlib.import_module("apifox_mcp.tools.batch_tools")

        def fake_patch_metadata(**kwargs):
            return "✅ 接口元信息更新成功\n\n写后复核:\n   • 名称: '旧标题' -> '新标题'\n操作日志: 20260422_101010_abcd"

        module.api_tools.patch_api_endpoint_metadata = fake_patch_metadata

        result = module.batch_execute(
            project_id="7575229",
            items=[
                {
                    "operation": "patch",
                    "resource_type": "endpoint",
                    "path": "/orders",
                    "method": "POST",
                    "title": "新标题",
                }
            ],
        )

        self.assertIn("写后复核", result)
        self.assertIn("旧标题", result)
        self.assertIn("20260422_101010_abcd", result)

    def test_batch_execute_dry_run_validates_without_calling_write_tools(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"}]'
        module = importlib.import_module("apifox_mcp.tools.batch_tools")

        def fake_delete(**kwargs):
            raise AssertionError("dry_run must not call write tools")

        module.api_tools.delete_api_endpoint = fake_delete

        result = module.batch_execute(
            project_id="7575229",
            dry_run=True,
            items=[
                {"operation": "delete", "resource_type": "endpoint", "path": "/orders", "method": "POST"},
                {"operation": "create", "resource_type": "schema", "schema_type": "object"},
            ],
        )

        self.assertIn("DRY-RUN", result)
        self.assertIn("参数校验通过", result)
        self.assertIn("缺少必填字段", result)
        self.assertIn("汇总: 1 可执行, 1 不可执行", result)

    def test_update_api_endpoint_returns_write_review_and_log_id(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"}]'
        module = importlib.import_module("apifox_mcp.tools.api_tools")
        exports = [make_openapi_fixture()]

        after_openapi = make_openapi_fixture()
        after_openapi["paths"]["/orders"]["post"]["summary"] = "全量新标题"
        exports.append(after_openapi)

        def fake_request(method, endpoint, data=None, params=None, use_public_api=True):
            if endpoint.endswith("/export-openapi?locale=zh-CN"):
                return {"success": True, "data": deepcopy(exports.pop(0))}
            if endpoint.endswith("/import-openapi?locale=zh-CN"):
                return {"success": True, "data": {"data": {"counters": {"endpointUpdated": 1}}}}
            raise AssertionError(endpoint)

        module._make_request = fake_request

        result = module.update_api_endpoint(
            project_id="7575229",
            path="/orders",
            method="POST",
            title="全量新标题",
            description="全量替换",
            response_schema={"type": "object", "properties": {"id": {"type": "integer", "description": "ID"}}},
            response_example={"id": 1},
            request_body_schema={"type": "object", "properties": {"name": {"type": "string", "description": "名称"}}},
            request_body_example={"name": "订单"},
            confirm_replace=True,
        )

        self.assertIn("写后复核", result)
        self.assertIn("名称", result)
        self.assertIn("操作日志", result)

    def test_create_api_endpoint_does_not_auto_fill_error_responses(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"}]'
        module = importlib.import_module("apifox_mcp.tools.api_tools")
        imports = []

        def fake_request(method, endpoint, data=None, params=None, use_public_api=True):
            if endpoint.endswith("/export-openapi?locale=zh-CN"):
                return {"success": True, "data": {"paths": {}}}
            if endpoint.endswith("/import-openapi?locale=zh-CN"):
                imports.append(json_loads(data["input"]))
                return {"success": True, "data": {"data": {"counters": {"endpointCreated": 1}}}}
            raise AssertionError(endpoint)

        module._make_request = fake_request

        result = module.create_api_endpoint(
            project_id="7575229",
            title="创建订单",
            path="/orders",
            method="POST",
            description="创建订单",
            response_schema={"type": "object", "properties": {"id": {"type": "integer", "description": "ID"}}},
            response_example={"id": 1},
            request_body_schema={"type": "object", "properties": {"name": {"type": "string", "description": "名称"}}},
            request_body_example={"name": "订单"},
            responses=[
                {
                    "code": 400,
                    "name": "请求错误",
                    "schema": {
                        "type": "object",
                        "properties": {"reason": {"type": "string", "description": "错误原因"}},
                    },
                    "example": {"reason": "名称不能为空"},
                }
            ],
        )

        responses = imports[0]["paths"]["/orders"]["post"]["responses"]
        self.assertIn("200", responses)
        self.assertIn("400", responses)
        self.assertNotIn("401", responses)
        self.assertNotIn("500", responses)
        self.assertNotIn("ErrorResponse", imports[0].get("components", {}).get("schemas", {}))
        self.assertNotIn("ErrorResponse", responses["400"]["content"]["application/json"]["schema"]["$ref"])
        self.assertIn("接口创建成功", result)

    def test_generate_crud_apis_does_not_auto_fill_error_responses(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"}]'
        module = importlib.import_module("apifox_mcp.tools.crud_tools")
        imports = []

        def fake_request(method, endpoint, data=None, params=None, use_public_api=True):
            if endpoint.endswith("/import-openapi?locale=zh-CN"):
                imports.append(json_loads(data["input"]))
                return {"success": True, "data": {"data": {"counters": {"endpointCreated": 5}}}}
            raise AssertionError(endpoint)

        module._make_request = fake_request

        result = module.generate_crud_apis(
            project_id="7575229",
            resource_name="order",
            resource_name_cn="订单",
            base_path="/orders",
            model_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "订单ID"},
                    "name": {"type": "string", "description": "订单名称"},
                },
                "required": ["name"],
            },
        )

        self.assertIn("CRUD 接口批量生成成功", result)
        self.assertNotIn("自动添加标准错误响应", result)
        self.assertNotIn("ErrorResponse", imports[0]["components"]["schemas"])
        for path_item in imports[0]["paths"].values():
            for operation in path_item.values():
                responses = operation["responses"]
                self.assertNotIn("401", responses)
                self.assertNotIn("500", responses)

    def test_batch_get_api_endpoint_summaries_returns_small_context(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"}]'
        module = importlib.import_module("apifox_mcp.tools.api_tools")

        module._make_request = lambda *args, **kwargs: {"success": True, "data": make_openapi_fixture()}

        result = module.batch_get_api_endpoint_summaries(
            project_id="7575229",
            items=[{"path": "/orders", "method": "POST"}],
        )

        self.assertIn("旧标题", result)
        self.assertIn("参数: 1", result)
        self.assertNotIn("components", result)

    def test_batch_patch_api_endpoint_titles_preserves_details(self):
        os.environ["APIFOX_TOKEN"] = "token"
        os.environ["APIFOX_PROJECTS"] = '[{"name":"主项目","id":"7575229"}]'
        module = importlib.import_module("apifox_mcp.tools.api_tools")
        openapi_data = make_openapi_fixture()
        imports = []

        def fake_request(method, endpoint, data=None, params=None, use_public_api=True):
            if endpoint.endswith("/export-openapi?locale=zh-CN"):
                if imports:
                    after = deepcopy(openapi_data)
                    after["paths"]["/orders"]["post"]["summary"] = "批量新标题"
                    return {"success": True, "data": after}
                return {"success": True, "data": deepcopy(openapi_data)}
            if endpoint.endswith("/import-openapi?locale=zh-CN"):
                imported = json_loads(data["input"])
                imports.append(imported)
                operation = imported["paths"]["/orders"]["post"]
                self.assertEqual(operation["summary"], "批量新标题")
                self.assertEqual(operation["parameters"][0]["name"], "source")
                return {"success": True, "data": {"data": {"counters": {"endpointUpdated": 1}}}}
            raise AssertionError(endpoint)

        module._make_request = fake_request

        result = module.batch_patch_api_endpoint_titles(
            project_id="7575229",
            items=[{"path": "/orders", "method": "POST", "title": "批量新标题"}],
        )

        self.assertIn("批量更新完成", result)
        self.assertIn("写后复核", result)

def json_loads(text):
    import json

    return json.loads(text)


def make_openapi_fixture():
    return {
        "openapi": "3.1.0",
        "info": {"title": "测试项目", "version": "1.0.0"},
        "paths": {
            "/orders": {
                "post": {
                    "summary": "旧标题",
                    "description": "旧描述",
                    "tags": ["订单"],
                    "parameters": [
                        {
                            "name": "source",
                            "in": "query",
                            "required": False,
                            "description": "调用来源",
                            "schema": {"type": "string"},
                            "example": "codex",
                        }
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/CreateOrderRequest"},
                                "example": {
                                    "name": "订单",
                                    "metadata": {"owner": "codex"},
                                },
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "成功",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/OrderResponse"},
                                    "example": {"id": 1, "status": "created"},
                                }
                            },
                        },
                        "400": {"description": "请求错误"},
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "CreateOrderRequest": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "名称"},
                        "metadata": {"type": "object", "description": "元数据"},
                    },
                },
                "OrderResponse": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "description": "ID"},
                        "status": {"type": "string", "description": "状态"},
                    },
                },
            }
        },
    }


if __name__ == "__main__":
    unittest.main()
