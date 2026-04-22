"""
统一批量写操作工具
==================

按顺序执行接口、Schema、目录的创建/更新/局部更新操作。
"""

from typing import Any, Dict, List

from ..config import mcp
from ..utils import _validate_config, _resolve_project_id
from . import api_tools, folder_tools, schema_tools


@mcp.tool()
def batch_execute(project_id: str, items: List[Dict[str, Any]], dry_run: bool = False) -> str:
    """
    统一批量执行写操作。

    单个 item 失败不会阻塞后续 item。dry_run=True 时只预览，不写入 Apifox。
    """
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)

    if not items:
        return "⚠️ items 不能为空"

    outputs = [f"📋 批量操作结果 (共 {len(items)} 个)", "=" * 60]
    success_count = 0
    failure_count = 0

    for item in items:
        operation = str(item.get("operation", "")).lower()
        resource_type = str(item.get("resource_type", "")).lower()
        label = _describe_item(operation, resource_type, item)

        if dry_run:
            validation_errors = _validate_item(operation, resource_type, item)
            if validation_errors:
                failure_count += 1
                outputs.append(f"❌ [{operation}/{resource_type}] {label} — DRY-RUN: 缺少必填字段: {', '.join(validation_errors)}")
            else:
                success_count += 1
                outputs.append(f"🔎 [{operation}/{resource_type}] {label} — DRY-RUN: 参数校验通过")
            continue

        try:
            result = _execute_one(resolved_project_id, operation, resource_type, item)
        except Exception as exc:  # MCP 工具应把单项异常转成结果文本，继续后续项。
            result = f"❌ 执行失败: {exc}"

        detail_lines = _compact_result(result)
        if _is_success(result):
            success_count += 1
            outputs.append(f"✅ [{operation}/{resource_type}] {label} — {detail_lines[0]}")
        else:
            failure_count += 1
            outputs.append(f"❌ [{operation}/{resource_type}] {label} — {detail_lines[0]}")
        outputs.extend(f"   {line}" for line in detail_lines[1:])

    outputs.append("")
    if dry_run:
        outputs.append(f"汇总: {success_count} 可执行, {failure_count} 不可执行")
    else:
        outputs.append(f"汇总: {success_count} 成功, {failure_count} 失败")
    return "\n".join(outputs)


def _execute_one(project_id: str, operation: str, resource_type: str, item: Dict[str, Any]) -> str:
    if resource_type == "endpoint":
        return _execute_endpoint(project_id, operation, item)
    if resource_type == "schema":
        return _execute_schema(project_id, operation, item)
    if resource_type == "folder":
        return _execute_folder(project_id, operation, item)
    return f"❌ 不支持的 resource_type: {resource_type}"


def _execute_endpoint(project_id: str, operation: str, item: Dict[str, Any]) -> str:
    if operation == "delete":
        return _manual_delete_guidance("endpoint", item)
    if operation == "create":
        return api_tools.create_api_endpoint(project_id=project_id, **_without_control_fields(item))
    if operation == "update":
        if not item.get("confirm_replace"):
            return "❌ update/endpoint 必须设置 confirm_replace=true"
        return api_tools.update_api_endpoint(project_id=project_id, **_without_control_fields(item))
    if operation == "patch":
        return api_tools.patch_api_endpoint_metadata(
            project_id=project_id,
            path=item.get("path", ""),
            method=item.get("method", "GET"),
            title=item.get("title"),
            description=item.get("description"),
            tags=item.get("tags"),
            dry_run=bool(item.get("dry_run", False)),
        )
    return f"❌ 不支持的 endpoint 操作: {operation}"


def _execute_schema(project_id: str, operation: str, item: Dict[str, Any]) -> str:
    if operation == "delete":
        return _manual_delete_guidance("schema", item)
    if operation == "create":
        return schema_tools.create_schema(project_id=project_id, **_without_control_fields(item))
    if operation == "update":
        return schema_tools.update_schema(project_id=project_id, **_without_control_fields(item))
    return f"❌ 不支持的 schema 操作: {operation}"


def _execute_folder(project_id: str, operation: str, item: Dict[str, Any]) -> str:
    if operation == "delete":
        return _manual_delete_guidance("folder", item)
    if operation == "create":
        return folder_tools.create_folder(
            project_id=project_id,
            folder_name=item.get("folder_name", ""),
            description=item.get("description", ""),
        )
    return f"❌ 不支持的 folder 操作: {operation}"


def _validate_item(operation: str, resource_type: str, item: Dict[str, Any]) -> List[str]:
    if operation == "delete":
        return ["MCP 不执行删除，请在 Apifox 客户端手动删除"]

    required_fields = {
        ("endpoint", "create"): ["title", "path", "method", "description", "response_schema", "response_example"],
        ("endpoint", "update"): ["path", "method", "title", "description", "response_schema", "response_example", "confirm_replace"],
        ("endpoint", "patch"): ["path", "method"],
        ("schema", "create"): ["name", "schema_type"],
        ("schema", "update"): ["name"],
        ("folder", "create"): ["folder_name"],
    }
    required = required_fields.get((resource_type, operation))
    if required is None:
        return [f"不支持的操作 {operation}/{resource_type}"]
    missing = [field for field in required if not item.get(field)]
    if resource_type == "endpoint" and operation == "patch":
        if item.get("title") is None and item.get("description") is None and item.get("tags") is None:
            missing.append("title/description/tags 之一")
    return missing


def _manual_delete_guidance(resource_type: str, item: Dict[str, Any]) -> str:
    target = _describe_item("delete", resource_type, item)
    return f"❌ MCP 不执行删除操作。请在 Apifox 客户端手动删除: {resource_type} {target}"


def _without_control_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in item.items()
        if key not in {"operation", "resource_type"}
    }


def _is_success(result: str) -> bool:
    first = _first_line(result)
    return (
        not result.startswith("❌")
        and not result.startswith("🚫")
        and not result.startswith("⚠️")
        and "失败" not in first
    )


def _first_line(result: str) -> str:
    return result.splitlines()[0] if result else "无返回内容"


def _compact_result(result: str, limit: int = 8) -> List[str]:
    lines = [line.strip() for line in result.splitlines() if line.strip()]
    if not lines:
        return ["无返回内容"]
    if len(lines) <= limit:
        return lines
    return lines[:limit] + [f"... 省略 {len(lines) - limit} 行详情"]


def _describe_item(operation: str, resource_type: str, item: Dict[str, Any]) -> str:
    if resource_type == "endpoint":
        return f"{str(item.get('method', 'GET')).upper()} {item.get('path', '')}".strip()
    if resource_type == "schema":
        return str(item.get("name", ""))
    if resource_type == "folder":
        return str(item.get("folder_name", ""))
    return f"{operation}/{resource_type}"
