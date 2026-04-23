"""
Apifox MCP 服务器入口
=====================

启动 MCP 服务器，加载所有工具。
"""

from .config import mcp, logger

# 导入所有工具模块以注册装饰器
from . import tools  # noqa: F401


def main():
    """启动 MCP 服务器"""
    logger.info("正在启动 Apifox MCP 服务器 v2.0.0...")
    logger.info("可用工具: check_apifox_config, list_api_endpoints, find_api_endpoints, get_api_endpoint_compact_detail, batch_get_api_endpoint_summaries, get_api_endpoint_detail, get_api_endpoint_snapshot, create_api_endpoint, patch_api_endpoint_metadata, patch_api_endpoint_operation, batch_patch_api_endpoint_titles, update_api_endpoint, batch_execute, list_operation_logs, undo_operation, list_schemas, create_schema, update_schema, get_schema_detail, list_folders, create_folder, list_tags, get_apis_by_tag, add_tag_to_api")
    mcp.run()


if __name__ == "__main__":
    main()
