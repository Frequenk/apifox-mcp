"""
Apifox MCP 服务器入口
=====================

启动 MCP 服务器，加载所有工具。
"""

# 导入所有工具模块以注册装饰器
from . import tools  # noqa: F401
from .config import logger, mcp


def main():
    """启动 MCP 服务器"""
    logger.info("正在启动 Apifox MCP 服务器 v2.0.0...")
    logger.info(
        "可用工具: get_apifox_status, search_api_documents, read_api_documents, apply_api_document_changes, audit_api_documents, list_change_logs, undo_change"
    )
    mcp.run()


if __name__ == "__main__":
    main()
