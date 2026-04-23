"""
配置模块
========

包含 MCP 服务初始化、环境变量配置和常量定义。
"""

import os
import logging
import functools
import traceback
from mcp.server.fastmcp import FastMCP

# ============================================================
# 日志配置
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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
                    logger.error(
                        "MCP 工具执行异常: %s",
                        func.__name__,
                        exc_info=True,
                    )
                    return (
                        f"❌ MCP 工具执行异常: {func.__name__}: {exc}\n"
                        f"{traceback.format_exc(limit=8)}"
                    )

            return decorator(wrapper)

        return safe_decorator


# ============================================================
# MCP 服务初始化
# ============================================================
mcp = SafeFastMCP(
    name="Apifox-Builder",
)

# ============================================================
# 环境变量配置
# ============================================================
APIFOX_TOKEN = os.getenv("APIFOX_TOKEN")  # Apifox 开放 API 令牌
APIFOX_PROJECTS = os.getenv("APIFOX_PROJECTS")  # Apifox 项目列表，JSON 数组
APIFOX_BASE_URL = os.getenv("APIFOX_BASE_URL")

if (APIFOX_BASE_URL is None):
    APIFOX_BASE_URL = "https://api.apifox.com"

# Apifox API 基础地址
APIFOX_PUBLIC_API = APIFOX_BASE_URL + "/v1"
APIFOX_INTERNAL_API = APIFOX_BASE_URL + "/api/v1"
APIFOX_API_VERSION = "2024-03-28"

# ============================================================
# 常量定义
# ============================================================

# 接口状态枚举
API_STATUS = {
    "developing": "开发中",
    "testing": "测试中", 
    "released": "已发布",
    "deprecated": "已废弃"
}

# 请求体类型枚举
REQUEST_BODY_TYPES = ["none", "json", "form-data", "x-www-form-urlencoded", "raw", "binary"]

# HTTP 方法枚举
HTTP_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]

# 常见 HTTP 状态码及其含义
HTTP_STATUS_CODES = {
    200: "成功",
    201: "创建成功",
    204: "无内容",
    400: "请求错误",
    401: "未授权",
    403: "禁止访问",
    404: "未找到",
    405: "方法不允许",
    409: "冲突",
    422: "无法处理的实体",
    429: "请求过多",
    500: "服务器内部错误",
    502: "网关错误",
    503: "服务不可用"
}

# JSON Schema 基本类型
SCHEMA_TYPES = ["string", "integer", "number", "boolean", "array", "object", "null"]
