"""
目录管理工具
============

提供目录（标签/文件夹）管理功能。
"""

import copy
import json

from ..config import mcp, logger
from ..operation_log import _snapshot_folder, operation_logger
from ..utils import _validate_config, _make_request, _resolve_project_id


def _export_openapi(project_id: str):
    export_payload = {"scope": {"type": "ALL"}, "options": {"includeApifoxExtensionProperties": True, "addFoldersToTags": True}, "oasVersion": "3.1", "exportFormat": "JSON"}
    result = _make_request("POST", f"/projects/{project_id}/export-openapi?locale=zh-CN", data=export_payload)
    if not result["success"]:
        raise RuntimeError(result.get("error", "未知错误"))
    return result.get("data", {})


@mcp.tool()
def list_folders(project_id: str) -> str:
    """列出指定 Apifox 项目中的所有目录结构，project_id 必须来自 check_apifox_config 输出的项目列表。"""
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)
    
    logger.info("正在获取目录列表...")
    
    export_payload = {"scope": {"type": "ALL"}, "options": {"includeApifoxExtensionProperties": True, "addFoldersToTags": True}, "oasVersion": "3.1", "exportFormat": "JSON"}
    result = _make_request("POST", f"/projects/{resolved_project_id}/export-openapi?locale=zh-CN", data=export_payload)
    
    if not result["success"]:
        return f"❌ 获取目录列表失败: {result.get('error', '未知错误')}"
    
    openapi_data = result.get("data", {})
    tags = openapi_data.get("tags", [])
    paths = openapi_data.get("paths", {})
    
    tag_counts = {}
    for path, methods in paths.items():
        for method, details in methods.items():
            if method in ["get", "post", "put", "delete", "patch"]:
                for tag in details.get("tags", []):
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
    
    if not tags and not tag_counts:
        return "📭 当前项目中没有目录（标签）"
    
    output_lines = ["📂 目录列表", "=" * 50]
    
    for tag in tags:
        tag_name = tag.get("name", "未命名") if isinstance(tag, dict) else tag
        count = tag_counts.get(tag_name, 0)
        output_lines.append(f"📁 {tag_name} ({count} 个接口)")
    
    for tag_name, count in tag_counts.items():
        if tag_name not in [t.get("name", t) if isinstance(t, dict) else t for t in tags]:
            output_lines.append(f"📁 {tag_name} ({count} 个接口)")
    
    return "\n".join(output_lines)


@mcp.tool()
def delete_folder(project_id: str, folder_name: str, confirm: bool = False) -> str:
    """删除指定 Apifox 项目中的目录（标签），并记录操作日志。"""
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)

    if not confirm:
        return f"⚠️ 安全提示: 删除操作不可撤销!\n\n请确认要删除目录: {folder_name}\n\n如果确认删除，请将 confirm 参数设为 True:\ndelete_folder(folder_name=\"{folder_name}\", confirm=True)"

    try:
        openapi_data = _export_openapi(resolved_project_id)
        before = _snapshot_folder(openapi_data, folder_name)
    except (RuntimeError, KeyError) as exc:
        return f"❌ 删除失败: {exc}"

    delete_spec = copy.deepcopy(openapi_data)
    delete_spec["tags"] = [
        tag for tag in delete_spec.get("tags", [])
        if (tag.get("name") if isinstance(tag, dict) else tag) != folder_name
    ]
    for methods in delete_spec.get("paths", {}).values():
        for operation in methods.values():
            if isinstance(operation, dict):
                operation["tags"] = [tag for tag in operation.get("tags", []) if tag != folder_name]

    import_spec = {
        "openapi": "3.0.0",
        "info": delete_spec.get("info", {"title": "Apifox API", "version": "1.0.0"}),
        "paths": delete_spec.get("paths", {}),
        "tags": delete_spec.get("tags", []),
    }
    if delete_spec.get("components"):
        import_spec["components"] = delete_spec["components"]

    import_payload = {
        "input": json.dumps(import_spec),
        "options": {
            "targetEndpointFolderId": 0,
            "targetSchemaFolderId": 0,
            "endpointOverwriteBehavior": "OVERWRITE_EXISTING",
            "schemaOverwriteBehavior": "OVERWRITE_EXISTING",
        },
    }
    result = _make_request("POST", f"/projects/{resolved_project_id}/import-openapi?locale=zh-CN", data=import_payload)
    if not result["success"]:
        operation_logger.record(
            operation="delete",
            resource_type="folder",
            project_id=resolved_project_id,
            target={"folder_name": folder_name},
            before=before,
            after=None,
            status="failed",
            error=result.get("error", "未知错误"),
        )
        return f"❌ 删除失败: {result.get('error', '未知错误')}"

    try:
        after_openapi_data = _export_openapi(resolved_project_id)
        _snapshot_folder(after_openapi_data, folder_name)
        verify_error = "删除后复核失败: 目标仍存在"
        log_entry = operation_logger.record(
            operation="delete",
            resource_type="folder",
            project_id=resolved_project_id,
            target={"folder_name": folder_name},
            before=before,
            after=None,
            status="failed",
            error=verify_error,
        )
        return f"⚠️ 目录删除请求已提交，但未实际删除\n\n📁 目录: {folder_name}\n操作日志: {log_entry['id']}\n\n写后复核:\n   • {verify_error}\n\n请在 Apifox 客户端中手动删除，或检查 Apifox OpenAPI 导入覆盖策略。"
    except KeyError:
        pass
    except RuntimeError as exc:
        log_entry = operation_logger.record(
            operation="delete",
            resource_type="folder",
            project_id=resolved_project_id,
            target={"folder_name": folder_name},
            before=before,
            after=None,
            status="failed",
            error=f"删除后复核失败: {exc}",
        )
        return f"⚠️ 目录删除请求已提交，但写后复核失败: {exc}\n\n操作日志: {log_entry['id']}"

    log_entry = operation_logger.record(
        operation="delete",
        resource_type="folder",
        project_id=resolved_project_id,
        target={"folder_name": folder_name},
        before=before,
        after=None,
    )
    return f"✅ 目录删除请求已提交\n\n📁 目录: {folder_name}\n操作日志: {log_entry['id']}\n\n⚠️ 如果 Apifox 未删除该目录，请在客户端中手动删除。"


@mcp.tool() 
def create_folder(project_id: str, folder_name: str, description: str = "") -> str:
    """在指定 Apifox 项目中创建新目录（标签）。"""
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    
    return f"""📁 创建目录提示

Apifox 的目录系统基于标签（Tags），目录会在创建接口时自动生成。

要创建目录 "{folder_name}"，请使用以下方式：

方式1: 创建新接口时指定标签
create_api_endpoint(
    title="示例接口",
    path="/example",
    method="GET",
    tags=["{folder_name}"],  # 这会自动创建目录
    ...
)

方式2: 使用 add_tag_to_api 工具为现有接口添加标签
add_tag_to_api(
    path="/existing-api",
    method="GET", 
    tags=["{folder_name}"]
)

💡 提示: 也可以在 Apifox 客户端中直接创建目录。"""
