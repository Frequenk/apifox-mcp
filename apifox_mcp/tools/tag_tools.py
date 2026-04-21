"""
标签管理工具
============

提供标签的查询和管理功能。
"""

import json
from typing import List

from ..config import mcp, logger, API_STATUS
from ..utils import _validate_config, _make_request, _resolve_project_id


@mcp.tool()
def list_tags(project_id: str) -> str:
    """列出指定 Apifox 项目中所有的标签及其接口数量，project_id 必须来自 check_apifox_config 输出的项目列表。"""
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)
    
    logger.info("正在获取标签列表...")
    
    export_payload = {"scope": {"type": "ALL"}, "options": {"includeApifoxExtensionProperties": True}, "oasVersion": "3.1", "exportFormat": "JSON"}
    result = _make_request("POST", f"/projects/{resolved_project_id}/export-openapi?locale=zh-CN", data=export_payload)
    
    if not result["success"]:
        return f"❌ 获取标签失败: {result.get('error', '未知错误')}"
    
    openapi_data = result.get("data", {})
    paths = openapi_data.get("paths", {})
    tags_info = openapi_data.get("tags", [])
    
    tag_count = {}
    for path, methods in paths.items():
        for method, details in methods.items():
            if method in ["get", "post", "put", "delete", "patch", "head", "options"]:
                for tag in details.get("tags", ["未分类"]):
                    tag_count[tag] = tag_count.get(tag, 0) + 1
    
    output_lines = [f"🏷️ 标签列表 (共 {len(tag_count)} 个)", "=" * 50]
    
    sorted_tags = sorted(tag_count.items(), key=lambda x: (-x[1], x[0]))
    
    for tag_name, count in sorted_tags:
        tag_desc = ""
        for t in tags_info:
            if t.get("name") == tag_name:
                tag_desc = t.get("description", "")
                break
        
        line = f"  📌 {tag_name}: {count} 个接口"
        if tag_desc:
            line += f" - {tag_desc}"
        output_lines.append(line)
    
    output_lines.append("")
    output_lines.append("💡 提示: 创建接口时设置 tags 参数即可添加标签")
    
    return "\n".join(output_lines)


@mcp.tool()
def get_apis_by_tag(project_id: str, tag: str) -> str:
    """获取指定 Apifox 项目中指定标签下的所有接口。"""
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)
    
    logger.info(f"正在获取标签 '{tag}' 下的接口...")
    
    export_payload = {"scope": {"type": "ALL"}, "options": {"includeApifoxExtensionProperties": True}, "oasVersion": "3.1", "exportFormat": "JSON"}
    result = _make_request("POST", f"/projects/{resolved_project_id}/export-openapi?locale=zh-CN", data=export_payload)
    
    if not result["success"]:
        return f"❌ 获取接口失败: {result.get('error', '未知错误')}"
    
    paths = result.get("data", {}).get("paths", {})
    
    apis = []
    for path, methods in paths.items():
        for method, details in methods.items():
            if method in ["get", "post", "put", "delete", "patch", "head", "options"]:
                if tag in details.get("tags", []):
                    apis.append({"method": method, "path": path, "name": details.get("summary", "未命名"), "status": details.get("x-apifox-status", "unknown")})
    
    if not apis:
        return f"📭 标签 '{tag}' 下没有接口"
    
    output_lines = [f"🏷️ 标签: {tag}", f"📋 接口列表 (共 {len(apis)} 个)", "=" * 70]
    
    for api in apis:
        output_lines.append(f"[{api['method'].upper():6}] {api['path']:40} | {api['name']}")
    
    return "\n".join(output_lines)


@mcp.tool()
def add_tag_to_api(project_id: str, path: str, method: str, tags: List[str]) -> str:
    """为指定 Apifox 项目中的现有接口添加标签。"""
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)
    
    if not tags:
        return "⚠️ 请提供至少一个标签"
    
    method_upper = method.upper()
    logger.info(f"正在为接口 {method_upper} {path} 设置标签: {tags}")
    
    export_payload = {"scope": {"type": "ALL"}, "options": {"includeApifoxExtensionProperties": True, "addFoldersToTags": False}, "oasVersion": "3.1", "exportFormat": "JSON"}
    result = _make_request("POST", f"/projects/{resolved_project_id}/export-openapi?locale=zh-CN", data=export_payload)
    
    if not result["success"]:
        return f"❌ 获取接口失败: {result.get('error', '未知错误')}"
    
    paths = result.get("data", {}).get("paths", {})
    
    if path not in paths:
        return f"❌ 未找到路径为 {path} 的接口"
    
    path_item = paths[path]
    method_lower = method.lower()
    
    if method_lower not in path_item:
        return f"❌ 未找到 {method_upper} {path} 接口"
    
    api = path_item[method_lower]
    api["tags"] = tags
    
    openapi_spec = {"openapi": "3.0.0", "info": {"title": api.get("summary", "API"), "version": "1.0.0"}, "paths": {path: {method_lower: api}}}
    
    import_payload = {"input": json.dumps(openapi_spec), "options": {"targetEndpointFolderId": 0, "targetSchemaFolderId": 0, "endpointOverwriteBehavior": "OVERWRITE_EXISTING", "schemaOverwriteBehavior": "OVERWRITE_EXISTING"}}
    
    result = _make_request("POST", f"/projects/{resolved_project_id}/import-openapi?locale=zh-CN", data=import_payload)
    
    if not result["success"]:
        return f"❌ 更新失败: {result.get('error', '未知错误')}"
    
    return f"✅ 标签更新成功!\n\n   接口: {method_upper} {path}\n   新标签: {', '.join(tags)}"
