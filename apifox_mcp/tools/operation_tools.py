"""
操作日志工具
============
"""

import json
from typing import Any, Dict

from ..config import mcp
from ..operation_log import operation_logger
from ..utils import _make_request, _resolve_project_id, _validate_config


@mcp.tool()
def list_operation_logs(project_id: str = "", limit: int = 20) -> str:
    """列出最近的操作日志，可按 project_id 过滤。"""
    project_filter = project_id or None
    logs = operation_logger.list_logs(project_id=project_filter, limit=limit)
    if not logs:
        return "📭 暂无操作日志"

    output = [f"📋 操作日志 (共 {len(logs)} 条)", "=" * 60]
    for entry in logs:
        target = _format_target(entry.get("resource_type", ""), entry.get("target", {}))
        output.append(
            f"• {entry.get('id')} | {entry.get('timestamp')} | "
            f"{entry.get('operation')}/{entry.get('resource_type')} | {target} | {entry.get('status')}"
        )
    return "\n".join(output)


@mcp.tool()
def undo_operation(operation_id: str) -> str:
    """根据操作日志撤销一次写操作，撤销本身也会记录日志。"""
    try:
        entry = operation_logger.get(operation_id)
    except FileNotFoundError as exc:
        return f"❌ 撤销失败: {exc}"

    project_id = entry.get("project_id", "")
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)

    try:
        result = _undo_entry(resolved_project_id, entry)
    except Exception as exc:
        operation_logger.record(
            operation="undo",
            resource_type=entry.get("resource_type", "unknown"),
            project_id=resolved_project_id,
            target={"operation_id": operation_id, **entry.get("target", {})},
            before=entry.get("after"),
            after=entry.get("before"),
            status="failed",
            error=str(exc),
        )
        return f"❌ 撤销失败: {exc}"

    log_entry = operation_logger.record(
        operation="undo",
        resource_type=entry.get("resource_type", "unknown"),
        project_id=resolved_project_id,
        target={"operation_id": operation_id, **entry.get("target", {})},
        before=entry.get("after"),
        after=entry.get("before"),
    )
    return f"{result}\n\n撤销日志: {log_entry['id']}"


def _undo_entry(project_id: str, entry: Dict[str, Any]) -> str:
    operation = entry.get("operation")
    resource_type = entry.get("resource_type")
    target = entry.get("target", {})

    if resource_type == "endpoint" and operation == "create":
        return f"⚠️ 创建操作不能自动撤销。请在 Apifox 客户端手动删除接口: {target.get('method', '').upper()} {target.get('path', '')}"

    if resource_type == "endpoint" and operation in {"update", "patch"}:
        before = entry.get("before")
        if not before:
            raise ValueError("日志缺少 before 快照，无法恢复接口")
        target_with_context = {
            **target,
            "_components": entry.get("context", {}).get("before_components", {}),
        }
        return _import_endpoint_snapshot(project_id, target_with_context, before)

    if resource_type == "schema" and operation == "update":
        before = entry.get("before")
        if not before:
            raise ValueError("日志缺少 before 快照，无法恢复 Schema")
        return _import_schema_snapshot(project_id, target, before)

    if resource_type == "schema" and operation == "create":
        return f"⚠️ 创建操作不能自动撤销。请在 Apifox 客户端手动删除数据模型: {target.get('name', '')}"

    if resource_type == "folder" and operation == "create":
        return f"⚠️ 创建操作不能自动撤销。请在 Apifox 客户端手动删除目录/标签: {target.get('folder_name', '')}"

    raise ValueError(f"不支持撤销 {operation}/{resource_type}")


def _import_endpoint_snapshot(project_id: str, target: Dict[str, Any], operation_snapshot: Dict[str, Any]) -> str:
    path = target.get("path", "")
    method = target.get("method", "GET").lower()
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Undo Operation", "version": "1.0.0"},
        "paths": {path: {method: operation_snapshot}},
    }
    components = target.get("_components") or {}
    if components:
        spec["components"] = components
    result = _import_spec(project_id, spec)
    if not result["success"]:
        raise RuntimeError(result.get("error", "未知错误"))
    return f"✅ 已撤销接口操作: {method.upper()} {path}"


def _import_schema_snapshot(project_id: str, target: Dict[str, Any], schema_snapshot: Dict[str, Any]) -> str:
    name = target.get("name", "")
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Undo Operation", "version": "1.0.0"},
        "paths": {},
        "components": {"schemas": {name: schema_snapshot}},
    }
    result = _import_spec(project_id, spec)
    if not result["success"]:
        raise RuntimeError(result.get("error", "未知错误"))
    return f"✅ 已撤销 Schema 操作: {name}"


def _import_spec(project_id: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "input": json.dumps(spec),
        "options": {
            "targetEndpointFolderId": 0,
            "targetSchemaFolderId": 0,
            "endpointOverwriteBehavior": "OVERWRITE_EXISTING",
            "schemaOverwriteBehavior": "OVERWRITE_EXISTING",
        },
    }
    return _make_request("POST", f"/projects/{project_id}/import-openapi?locale=zh-CN", data=payload)


def _format_target(resource_type: str, target: Dict[str, Any]) -> str:
    if resource_type == "endpoint":
        return f"{target.get('method', '').upper()} {target.get('path', '')}".strip()
    if resource_type == "schema":
        return str(target.get("name", ""))
    if resource_type == "folder":
        return str(target.get("folder_name", ""))
    return str(target)
