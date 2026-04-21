import importlib
import os
import sys
import types
import unittest


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

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)
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


if __name__ == "__main__":
    unittest.main()
