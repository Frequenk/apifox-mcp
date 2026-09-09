"""MCP 服务与 Apifox 连接配置。"""

import functools
import logging
import os

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ApifoxMCP")


class SafeFastMCP(FastMCP):
    """统一兜住工具异常，避免单个工具异常导致 MCP transport 关闭。"""

    def tool(self, *args, **kwargs):
        decorator = super().tool(*args, **kwargs)

        def safe_decorator(func):
            @functools.wraps(func)
            def wrapper(*func_args, **func_kwargs):
                try:
                    return func(*func_args, **func_kwargs)
                except Exception as exc:
                    code = getattr(exc, "code", "tool_error")
                    if code == "tool_error":
                        logger.exception("MCP 工具执行异常: %s", func.__name__)
                    else:
                        logger.warning("MCP 工具业务错误: %s: %s", func.__name__, exc)
                    error = {
                        "code": code,
                        "tool": func.__name__,
                        "message": str(exc),
                    }
                    details = getattr(exc, "details", None)
                    recovery = getattr(exc, "recovery", None)
                    if details is not None:
                        error["details"] = details
                    if recovery:
                        error["recovery"] = recovery
                    return {
                        "ok": False,
                        "error": error,
                    }

            return decorator(wrapper)

        return safe_decorator


mcp = SafeFastMCP(
    name="Apifox-Builder",
    instructions=(
        "正常流程直接使用 search_api_documents 定位目标，再用 read_api_documents 读取目标及其依赖。"
        "get_apifox_status 仅用于查看配置和排查连接，只有需要真实探活时才传 probe=true。"
        "所有写入统一使用 apply_api_document_changes；该工具会分组导入并自动回读验证。"
        "不要自行请求完整项目 OpenAPI，也不要在写入后额外读取，除非工具返回验证失败。"
    ),
)

APIFOX_TOKEN = os.getenv("APIFOX_TOKEN")
APIFOX_PROJECTS = os.getenv("APIFOX_PROJECTS")
APIFOX_BASE_URL = os.getenv("APIFOX_BASE_URL")

if APIFOX_BASE_URL is None:
    APIFOX_BASE_URL = "https://api.apifox.com"

APIFOX_PUBLIC_API = APIFOX_BASE_URL + "/v1"
APIFOX_API_VERSION = "2024-03-28"
