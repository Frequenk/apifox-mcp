"""
Apifox MCP 服务器包
==================

提供与 Apifox API 交互的 MCP 工具集。
"""

from .config import logger, mcp

__version__ = "2.1.0"
__all__ = ["logger", "mcp"]
