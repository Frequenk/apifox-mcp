"""
API 接口管理工具
================

提供 HTTP 接口的 CRUD 操作。

⚠️ 强制规范：
1. 所有接口必须有中文描述
2. 所有 Schema 字段必须有 description 说明
3. 必须提供成功响应 (2xx)；错误响应只在调用方明确传入时写入
4. 【重要】所有 Schema 必须定义为公共组件（components/schemas），
   禁止内联定义！本模块会自动将传入的 schema 提取为公共组件并使用 $ref 引用。
"""

import copy
import json
from typing import Optional, List, Dict, Tuple, Any

from ..config import (
    mcp, logger, HTTP_METHODS,
    HTTP_STATUS_CODES, API_STATUS
)
from ..operation_log import _snapshot_endpoint, operation_logger
from ..utils import _validate_config, _make_request, _build_openapi_spec, _resolve_project_id


def _export_openapi(project_id: str) -> Dict[str, Any]:
    """导出完整 OpenAPI 文档。"""
    export_payload = {
        "scope": {"type": "ALL"},
        "options": {"includeApifoxExtensionProperties": True, "addFoldersToTags": False},
        "oasVersion": "3.1",
        "exportFormat": "JSON"
    }
    result = _make_request("POST", f"/projects/{project_id}/export-openapi?locale=zh-CN", data=export_payload)
    if not result["success"]:
        raise RuntimeError(result.get("error", "未知错误"))
    return result.get("data", {})


def _get_operation(openapi_data: Dict[str, Any], path: str, method: str) -> Tuple[Dict[str, Any], str]:
    """从 OpenAPI 文档中获取指定 operation。"""
    method_lower = method.lower()
    paths = openapi_data.get("paths", {})
    if path not in paths:
        raise KeyError(f"未找到路径为 {path} 的接口")
    if method_lower not in paths[path]:
        raise KeyError(f"未找到 {method.upper()} {path} 接口")
    return paths[path][method_lower], method_lower


def _endpoint_log_context(openapi_data: Dict[str, Any]) -> Dict[str, Any]:
    components = copy.deepcopy(openapi_data.get("components", {}))
    return {"before_components": components} if components else {}


def _operation_snapshot(operation: Dict[str, Any]) -> Dict[str, Any]:
    """生成用于对比的 operation 快照。"""
    request_json = operation.get("requestBody", {}).get("content", {}).get("application/json", {})
    responses = operation.get("responses", {})
    return {
        "summary": operation.get("summary", ""),
        "description": operation.get("description", ""),
        "tags": operation.get("tags", []),
        "parameters": operation.get("parameters", []),
        "request_body": operation.get("requestBody"),
        "request_example": request_json.get("example"),
        "responses": responses,
        "response_codes": sorted(responses.keys()),
    }


def _build_single_operation_spec(openapi_data: Dict[str, Any], path: str, method_lower: str, operation: Dict[str, Any]) -> Dict[str, Any]:
    """构建只包含目标 operation 但保留全量 components 的导入文档。"""
    spec = {
        "openapi": "3.0.0",
        "info": openapi_data.get("info", {"title": "Apifox API", "version": "1.0.0"}),
        "paths": {path: {method_lower: operation}},
    }
    if openapi_data.get("components"):
        spec["components"] = openapi_data["components"]
    if openapi_data.get("tags"):
        spec["tags"] = openapi_data["tags"]
    return spec


def _summarize_snapshot_diff(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    """输出更新前后的关键差异和潜在风险。"""
    lines = []
    for key, label in [
        ("summary", "名称"),
        ("description", "描述"),
        ("tags", "标签"),
        ("response_codes", "响应码"),
    ]:
        if before.get(key) != after.get(key):
            lines.append(f"   • {label}: {before.get(key)!r} -> {after.get(key)!r}")

    before_params = before.get("parameters") or []
    after_params = after.get("parameters") or []
    if len(after_params) < len(before_params):
        lines.append(f"   ⚠️ 参数数量减少: {len(before_params)} -> {len(after_params)}")
    elif len(after_params) != len(before_params):
        lines.append(f"   • 参数数量: {len(before_params)} -> {len(after_params)}")

    if before.get("request_body") and not after.get("request_body"):
        lines.append("   ⚠️ 请求体被移除")
    if before.get("request_example") and not after.get("request_example"):
        lines.append("   ⚠️ 请求示例被移除")

    before_responses = before.get("responses") or {}
    after_responses = after.get("responses") or {}
    if len(after_responses) < len(before_responses):
        lines.append(f"   ⚠️ 响应数量减少: {len(before_responses)} -> {len(after_responses)}")

    return lines or ["   • 无关键差异"]


def _detect_unexpected_loss(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    """检测 patch 写入后不应出现的信息丢失。"""
    losses = []
    if len(after.get("parameters") or []) < len(before.get("parameters") or []):
        losses.append("参数数量减少")
    if before.get("request_body") and not after.get("request_body"):
        losses.append("请求体消失")
    if before.get("request_example") and not after.get("request_example"):
        losses.append("请求示例消失")
    if len(after.get("responses") or {}) < len(before.get("responses") or {}):
        losses.append("响应数量减少")
    return losses


def _format_json(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _compact_spec_preview(openapi_spec: Dict[str, Any], path: str, method: str, changed_fields: Optional[List[str]] = None) -> str:
    operation = openapi_spec.get("paths", {}).get(path, {}).get(method.lower(), {})
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    response_codes = sorted((operation.get("responses") or {}).keys())
    lines = [
        f"   • 目标: {method.upper()} {path}",
        f"   • 名称: {operation.get('summary', '')}",
        f"   • 字段: {', '.join(changed_fields or []) or '完整接口定义'}",
        f"   • 参数数量: {len(operation.get('parameters', []))}",
        f"   • 响应码: {', '.join(response_codes) or '无'}",
        f"   • components/schemas 数量: {len(schemas)}",
        "   • OpenAPI 明细已省略，避免占用过多上下文",
    ]
    return "\n".join(lines)


def _validate_schema_has_descriptions(schema: Dict, path: str = "") -> List[str]:
    """检查 Schema 中的每个字段是否都有 description"""
    missing = []
    if not schema:
        return missing
    
    properties = schema.get("properties", {})
    for prop_name, prop_def in properties.items():
        full_path = f"{path}.{prop_name}" if path else prop_name
        if not prop_def.get("description"):
            missing.append(full_path)
        # 递归检查嵌套对象
        if prop_def.get("type") == "object" and prop_def.get("properties"):
            missing.extend(_validate_schema_has_descriptions(prop_def, full_path))
        # 检查数组元素
        if prop_def.get("type") == "array" and prop_def.get("items"):
            items = prop_def["items"]
            if items.get("type") == "object" and items.get("properties"):
                missing.extend(_validate_schema_has_descriptions(items, f"{full_path}[]"))
    
    return missing


def _normalize_explicit_responses(responses: Optional[List[Dict]]) -> List[Dict]:
    """仅保留调用方显式传入的响应定义，不做自动补齐。"""
    return list(responses or [])


@mcp.tool()
def list_api_endpoints(
    project_id: str,
    folder_id: Optional[int] = None,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 50
) -> str:
    """
    列出 Apifox 项目中的所有 HTTP 接口。
    
    通过导出 OpenAPI 格式数据来获取接口列表。
    可以通过关键词进行筛选。
    
    Args:
        project_id: 【必填】目标 Apifox 项目 ID，必须来自 check_apifox_config 输出的项目列表
        folder_id: (可选) 目录 ID 筛选 (暂不支持)
        status: (可选) 按状态筛选 (暂不支持)
        keyword: (可选) 按关键词搜索接口名称或路径
        limit: 返回数量限制，默认 50
        
    Returns:
        接口列表信息
    """
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)
    
    logger.info("正在通过导出 API 获取接口列表...")
    
    export_payload = {
        "scope": {"type": "ALL"},
        "options": {"includeApifoxExtensionProperties": True, "addFoldersToTags": False},
        "oasVersion": "3.1",
        "exportFormat": "JSON"
    }
    
    result = _make_request(
        "POST", 
        f"/projects/{resolved_project_id}/export-openapi?locale=zh-CN",
        data=export_payload,
        use_public_api=True
    )
    
    if not result["success"]:
        return f"❌ 获取接口列表失败: {result.get('error', '未知错误')}"
    
    openapi_data = result.get("data", {})
    paths = openapi_data.get("paths", {})
    
    if not paths:
        return "📭 当前项目中没有接口"
    
    apis = []
    for path, methods in paths.items():
        for method, details in methods.items():
            if method in ["get", "post", "put", "delete", "patch", "head", "options"]:
                api_info = {
                    "method": method,
                    "path": path,
                    "name": details.get("summary", details.get("operationId", "未命名")),
                    "description": details.get("description", ""),
                    "tags": details.get("tags", []),
                    "status": details.get("x-apifox-status", "unknown")
                }
                apis.append(api_info)
    
    if keyword:
        keyword_lower = keyword.lower()
        apis = [api for api in apis if 
                keyword_lower in api.get("name", "").lower() or 
                keyword_lower in api.get("path", "").lower()]
    
    output_lines = [
        f"📋 接口列表 (共 {len(apis)} 个)",
        "=" * 70
    ]
    
    for api in apis[:limit]:
        method = api.get("method", "???").upper()
        path = api.get("path", "")
        name = api.get("name", "未命名")
        tags = ", ".join(api.get("tags", [])) if api.get("tags") else ""
        
        line = f"[{method:6}] {path:40} | {name}"
        if tags:
            line += f" [{tags}]"
        output_lines.append(line)
    
    if len(apis) > limit:
        output_lines.append(f"\n... 还有 {len(apis) - limit} 个接口未显示")
    
    return "\n".join(output_lines)


@mcp.tool()
def get_api_endpoint_snapshot(project_id: str, path: str, method: str) -> str:
    """
    获取接口的完整结构化快照，包含参数、请求体、响应、示例和组件引用。

    用途：
    - 修改旧接口前先读取完整上下文
    - 判断局部更新是否会影响参数、请求体或响应定义
    - 需要完整 OpenAPI operation 时优先使用本工具，而不是 get_api_endpoint_detail
    """
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)

    try:
        openapi_data = _export_openapi(resolved_project_id)
        operation, _ = _get_operation(openapi_data, path, method)
    except (RuntimeError, KeyError) as exc:
        return f"❌ 获取失败: {exc}"

    snapshot = _operation_snapshot(operation)
    snapshot["path"] = path
    snapshot["method"] = method.upper()
    snapshot["components"] = openapi_data.get("components", {})
    return _format_json(snapshot)


@mcp.tool()
def patch_api_endpoint_metadata(
    project_id: str,
    path: str,
    method: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    dry_run: bool = False
) -> str:
    """
    安全地局部更新接口元信息，只修改名称、描述和标签。

    本工具会先导出完整接口定义，只替换指定字段，并保留原有参数、请求体、响应、示例和 components。
    修改旧接口的名称、介绍、标签时应优先使用本工具，不要使用 update_api_endpoint。
    """
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)

    if title is None and description is None and tags is None:
        return "⚠️ 未提供任何要修改的字段，请至少提供 title、description 或 tags"

    try:
        openapi_data = _export_openapi(resolved_project_id)
        operation, method_lower = _get_operation(openapi_data, path, method)
    except (RuntimeError, KeyError) as exc:
        return f"❌ 获取失败: {exc}"

    updated_operation = copy.deepcopy(operation)
    before = _operation_snapshot(operation)

    if title is not None:
        updated_operation["summary"] = title
    if description is not None:
        updated_operation["description"] = description
    if tags is not None:
        updated_operation["tags"] = tags

    after = _operation_snapshot(updated_operation)
    diff_lines = _summarize_snapshot_diff(before, after)
    openapi_spec = _build_single_operation_spec(openapi_data, path, method_lower, updated_operation)

    if dry_run:
        changed_fields = []
        if title is not None:
            changed_fields.append("summary")
        if description is not None:
            changed_fields.append("description")
        if tags is not None:
            changed_fields.append("tags")
        return (
            "🔎 DRY-RUN: 接口元信息将按以下方式更新，不会写入 Apifox\n\n"
            "变更摘要:\n" + "\n".join(diff_lines) +
            "\n\n紧凑预览:\n" + _compact_spec_preview(openapi_spec, path, method, changed_fields)
        )

    import_payload = {
        "input": json.dumps(openapi_spec),
        "options": {
            "targetEndpointFolderId": 0,
            "targetSchemaFolderId": 0,
            "endpointOverwriteBehavior": "OVERWRITE_EXISTING",
            "schemaOverwriteBehavior": "OVERWRITE_EXISTING"
        }
    }

    result = _make_request("POST", f"/projects/{resolved_project_id}/import-openapi?locale=zh-CN", data=import_payload)
    if not result["success"]:
        operation_logger.record(
            operation="patch",
            resource_type="endpoint",
            project_id=resolved_project_id,
            target={"path": path, "method": method.upper()},
            before=operation,
            after=None,
            status="failed",
            error=result.get("error", "未知错误"),
            context=_endpoint_log_context(openapi_data),
        )
        return f"❌ 更新失败: {result.get('error', '未知错误')}"

    try:
        after_openapi_data = _export_openapi(resolved_project_id)
        after_operation, _ = _get_operation(after_openapi_data, path, method)
        post_write = _operation_snapshot(after_operation)
        post_diff_lines = _summarize_snapshot_diff(before, post_write)
        losses = _detect_unexpected_loss(before, post_write)
    except (RuntimeError, KeyError) as exc:
        operation_logger.record(
            operation="patch",
            resource_type="endpoint",
            project_id=resolved_project_id,
            target={"path": path, "method": method.upper()},
            before=operation,
            after=updated_operation,
            status="failed",
            error=f"写后复核失败: {exc}",
            context=_endpoint_log_context(openapi_data),
        )
        return "⚠️ 接口元信息已写入，但写后复核失败: " + str(exc)

    log_entry = operation_logger.record(
        operation="patch",
        resource_type="endpoint",
        project_id=resolved_project_id,
        target={"path": path, "method": method.upper()},
        before=operation,
        after=after_operation,
        context=_endpoint_log_context(openapi_data),
    )

    output = ["✅ 接口元信息更新成功", "", "写后复核:", *post_diff_lines]
    if losses:
        output.append("")
        output.append("⚠️ 检测到非预期信息丢失: " + ", ".join(losses))
    output.append("")
    output.append(f"操作日志: {log_entry['id']}")
    return "\n".join(output)


@mcp.tool()
def batch_get_api_endpoint_summaries(
    project_id: str,
    items: List[Dict[str, str]]
) -> str:
    """
    批量获取接口轻量摘要，适合只需要名称、描述、标签、参数数量和响应码的场景。

    items 格式: [{"path": "/orders", "method": "POST"}]
    本工具不会返回完整 schema/components，避免占用过多上下文。
    """
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)

    try:
        openapi_data = _export_openapi(resolved_project_id)
    except RuntimeError as exc:
        return f"❌ 获取失败: {exc}"

    output = [f"📋 接口轻量摘要 (共 {len(items)} 个)", "=" * 60]
    for item in items:
        path = item.get("path", "")
        method = item.get("method", "GET")
        try:
            operation, _ = _get_operation(openapi_data, path, method)
            responses = operation.get("responses", {})
            output.append(f"[{method.upper():6}] {path}")
            output.append(f"   名称: {operation.get('summary', '未命名')}")
            output.append(f"   描述: {operation.get('description', '')[:120]}")
            output.append(f"   标签: {', '.join(operation.get('tags', [])) or '无'}")
            output.append(f"   参数: {len(operation.get('parameters', []))}")
            output.append(f"   响应码: {', '.join(sorted(responses.keys())) or '无'}")
        except KeyError as exc:
            output.append(f"[{method.upper():6}] {path}")
            output.append(f"   ❌ {exc}")
    return "\n".join(output)


@mcp.tool()
def batch_patch_api_endpoint_titles(
    project_id: str,
    items: List[Dict[str, str]],
    dry_run: bool = False
) -> str:
    """
    批量安全修改接口名称，只更新 summary，保留原参数、请求体、响应、示例和 components。

    items 格式: [{"path": "/orders", "method": "POST", "title": "新名称"}]
    """
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)

    if not items:
        return "⚠️ items 不能为空"

    try:
        openapi_data = _export_openapi(resolved_project_id)
    except RuntimeError as exc:
        return f"❌ 获取失败: {exc}"

    outputs = [f"📋 批量接口名称更新 (共 {len(items)} 个)", "=" * 60]
    planned_specs = []

    for item in items:
        path = item.get("path", "")
        method = item.get("method", "GET")
        title = item.get("title", "")
        if not path or not method or not title:
            outputs.append(f"❌ 参数不完整: {item}")
            continue
        try:
            operation, method_lower = _get_operation(openapi_data, path, method)
        except KeyError as exc:
            outputs.append(f"❌ {method.upper()} {path}: {exc}")
            continue

        updated_operation = copy.deepcopy(operation)
        before = _operation_snapshot(operation)
        updated_operation["summary"] = title
        after = _operation_snapshot(updated_operation)
        diff_lines = _summarize_snapshot_diff(before, after)
        spec = _build_single_operation_spec(openapi_data, path, method_lower, updated_operation)
        planned_specs.append((path, method, before, spec))
        outputs.append(f"[{method.upper():6}] {path}")
        outputs.extend(diff_lines)

    if dry_run:
        outputs.append("")
        outputs.append("🔎 DRY-RUN: 不会写入 Apifox")
        return "\n".join(outputs)

    for path, method, before, spec in planned_specs:
        import_payload = {
            "input": json.dumps(spec),
            "options": {
                "targetEndpointFolderId": 0,
                "targetSchemaFolderId": 0,
                "endpointOverwriteBehavior": "OVERWRITE_EXISTING",
                "schemaOverwriteBehavior": "OVERWRITE_EXISTING"
            }
        }
        result = _make_request("POST", f"/projects/{resolved_project_id}/import-openapi?locale=zh-CN", data=import_payload)
        if not result["success"]:
            operation_logger.record(
                operation="patch",
                resource_type="endpoint",
                project_id=resolved_project_id,
                target={"path": path, "method": method.upper()},
                before=before,
                after=None,
                status="failed",
                error=result.get("error", "未知错误"),
                context=_endpoint_log_context(openapi_data),
            )
            outputs.append(f"❌ {method.upper()} {path}: 更新失败: {result.get('error', '未知错误')}")
            continue

        try:
            after_openapi_data = _export_openapi(resolved_project_id)
            after_operation, _ = _get_operation(after_openapi_data, path, method)
            post_write = _operation_snapshot(after_operation)
            losses = _detect_unexpected_loss(before, post_write)
            log_entry = operation_logger.record(
                operation="patch",
                resource_type="endpoint",
                project_id=resolved_project_id,
                target={"path": path, "method": method.upper()},
                before=before,
                after=after_operation,
                context=_endpoint_log_context(openapi_data),
            )
            outputs.append(f"✅ {method.upper()} {path}: 写后复核完成")
            outputs.append(f"   操作日志: {log_entry['id']}")
            if losses:
                outputs.append(f"⚠️ {method.upper()} {path}: 非预期信息丢失: {', '.join(losses)}")
        except (RuntimeError, KeyError) as exc:
            operation_logger.record(
                operation="patch",
                resource_type="endpoint",
                project_id=resolved_project_id,
                target={"path": path, "method": method.upper()},
                before=before,
                after=spec["paths"][path][method.lower()],
                status="failed",
                error=f"写后复核失败: {exc}",
                context=_endpoint_log_context(openapi_data),
            )
            outputs.append(f"⚠️ {method.upper()} {path}: 写后复核失败: {exc}")

    outputs.append("")
    outputs.append("✅ 批量更新完成")
    return "\n".join(outputs)


@mcp.tool()
def create_api_endpoint(
    project_id: str,
    title: str, 
    path: str, 
    method: str, 
    description: str,
    response_schema: Dict,
    response_example: Dict,
    folder_id: int = 0,
    status: str = "developing",
    tags: Optional[List[str]] = None,
    query_params: Optional[List[Dict]] = None,
    path_params: Optional[List[Dict]] = None,
    header_params: Optional[List[Dict]] = None,
    request_body_type: str = "json",
    request_body_schema: Optional[Dict] = None,
    request_body_example: Optional[Dict] = None,
    responses: Optional[List[Dict]] = None
) -> str:
    """
    在 Apifox 项目中创建一个新的 HTTP 接口。
    
    ⚠️ 强制要求 - 以下内容必须提供：
    1. title: 中文业务名称（如"创建订单"）
    2. description: 中文接口描述（说明接口用途）
    3. response_schema: 成功响应的 JSON Schema（字段必须有 description）
    4. response_example: 成功响应的示例数据
    5. POST/PUT/PATCH 必须提供 request_body_schema 和 request_body_example
    
    ⚠️ 错误响应不会自动补齐；如需 400/401/500 等响应，请通过 responses 显式传入。
    
    Args:
        project_id: 【必填】目标 Apifox 项目 ID，必须来自 check_apifox_config 输出的项目列表
        title: 【必填】接口中文业务名称
               ✅ 正确: "创建订单", "获取用户详情", "更新商品信息"
               ❌ 错误: "POST /orders", "createOrder", "get_user"
               
        path: 【必填】RESTful 接口路径
              示例: "/orders", "/users/{id}"
              
        method: 【必填】HTTP 方法: GET, POST, PUT, DELETE, PATCH
        
        description: 【必填】接口业务说明，用于描述接口的元信息和业务上下文
                     ⚠️ 只写业务说明，不要包含请求/响应示例！
                     
                     ✅ 正确格式（推荐使用结构化说明）:
                        "【版本】v1\n【环境】REST 接口（后端服务）\n【前置条件】需要用户登录\n【鉴权】Bearer Token"
                     
                     ✅ 也可以使用简短描述:
                        "用户名密码登录换取 access_token，无需鉴权"
                     
                     ❌ 错误（不要在这里写示例）:
                        "POST /api/v1/auth/token ... 成功响应: {\"access_token\":...}"
               
        response_schema: 【必填】成功响应 (200) 的 JSON Schema
                         ⚠️ 每个字段必须有 description 说明
                         示例: {
                             "type": "object",
                             "properties": {
                                 "id": {"type": "integer", "description": "订单ID"},
                                 "status": {"type": "string", "description": "订单状态"}
                             },
                             "required": ["id", "status"]
                         }
                         
        response_example: 【必填】成功响应示例数据
                          ⚠️ 必须是真实的、有意义的数据值，按业务实际响应结构填写
                          示例: {"id": 10001, "status": "pending", "createdAt": "2024-01-01T12:00:00Z"}
                          
        folder_id: 目录 ID，默认 0 (根目录)
        
        status: 接口状态，默认 "developing"
                
        tags: 标签列表，如 ["订单管理", "核心接口"]
              
        query_params: Query 参数列表
                      格式: [{"name": "page", "type": "integer", "required": false, "description": "页码"}]
                      ⚠️ 每个参数必须有 description
                      
        path_params: Path 参数列表，格式同上
        
        header_params: Header 参数列表，格式同上
                       
        request_body_type: 请求体类型: none 或 json，默认 json
                           
        request_body_schema: 【POST/PUT/PATCH 必填】请求体 JSON Schema
                             ⚠️ 每个字段必须有 description 说明
                             
        request_body_example: 【POST/PUT/PATCH 必填】请求体示例数据
                              ⚠️ 必须是真实数据，如: {"name": "张三", "email": "zhangsan@example.com"}
                              ❌ 错误: {"name": "string", "age": 0}
        
        responses: (可选) 显式响应列表。不会自动补齐任何错误响应。
    
    Returns:
        创建结果信息
        
    Example:
        >>> create_api_endpoint(
        ...     title="创建订单",
        ...     path="/orders",
        ...     method="POST",
        ...     description="创建新订单，需要传入商品列表和收货地址信息",
        ...     tags=["订单管理"],
        ...     request_body_schema={
        ...         "type": "object",
        ...         "properties": {
        ...             "items": {"type": "array", "description": "商品列表", "items": {"type": "object"}},
        ...             "address": {"type": "string", "description": "收货地址"}
        ...         },
        ...         "required": ["items", "address"]
        ...     },
        ...     request_body_example={"items": [{"id": 1, "qty": 2}], "address": "北京市朝阳区"},
        ...     response_schema={
        ...         "type": "object",
        ...         "properties": {
        ...             "orderId": {"type": "integer", "description": "订单ID"},
        ...             "status": {"type": "string", "description": "订单状态"}
        ...         }
        ...     },
        ...     response_example={"orderId": 10001, "status": "pending"}
        ... )
    """
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)
    
    method_upper = method.upper()
    if method_upper not in HTTP_METHODS:
        return f"❌ 错误: 无效的 HTTP 方法 '{method}'，支持: {', '.join(HTTP_METHODS)}"
    
    # ============ 接口查重检查 ============
    logger.info(f"正在检查接口是否已存在: {method_upper} {path}")
    
    export_payload = {
        "scope": {"type": "ALL"},
        "options": {"includeApifoxExtensionProperties": True, "addFoldersToTags": False},
        "oasVersion": "3.1",
        "exportFormat": "JSON"
    }
    
    check_result = _make_request(
        "POST", 
        f"/projects/{resolved_project_id}/export-openapi?locale=zh-CN",
        data=export_payload,
        use_public_api=True
    )
    
    if check_result["success"]:
        existing_paths = check_result.get("data", {}).get("paths", {})
        if path in existing_paths:
            path_methods = existing_paths[path]
            if method_upper.lower() in path_methods:
                existing_api = path_methods[method_upper.lower()]
                existing_title = existing_api.get("summary", "未命名")
                return f"""❌ 接口已存在，无法创建!

📋 冲突接口信息:
   • 路径: {method_upper} {path}
   • 名称: {existing_title}
   • 标签: {', '.join(existing_api.get('tags', [])) or '无'}

💡 解决方案:
   1. 如需更新现有接口，请使用 update_api_endpoint 工具
   2. 如需创建新接口，请使用不同的路径
   3. 如需删除后重建，请先在 Apifox 中删除现有接口"""
    
    errors = []
    
    # 1. 校验 title 格式
    title_lower = title.lower().strip()
    invalid_patterns = [
        title_lower.startswith(('get ', 'post ', 'put ', 'delete ', 'patch ')),
        title_lower.startswith(('get/', 'post/', 'put/', 'delete/', 'patch/')),
        title.startswith('/'),
        '_' in title and title.replace('_', '').replace('/', '').isalpha(),
    ]
    if any(invalid_patterns):
        errors.append(f"❌ title 格式错误: \"{title}\" 不是有效的业务名称，应使用中文如 \"创建订单\"")
    
    # 检查是否有角色前缀（如 "学生-获取课程列表" 应该是 "获取课程列表"）
    if '-' in title or '—' in title:
        errors.append(f"❌ title 格式错误: \"{title}\" 不应包含角色前缀。应直接描述动作，如 \"获取课程列表\" 而非 \"学生-获取课程列表\"")
    
    # 2. 校验 description 非空
    if not description or not description.strip():
        errors.append("❌ description 不能为空，请提供接口的中文描述")
    
    # 3. 校验 POST/PUT/PATCH 必须有请求体
    if method_upper in ['POST', 'PUT', 'PATCH']:
        if not request_body_schema:
            errors.append(f"❌ {method_upper} 请求必须提供 request_body_schema")
        if not request_body_example:
            errors.append(f"❌ {method_upper} 请求必须提供 request_body_example")
    
    # 4. 校验 response_schema 字段有 description
    if response_schema:
        missing = _validate_schema_has_descriptions(response_schema)
        if missing:
            errors.append(f"❌ response_schema 以下字段缺少 description: {', '.join(missing)}")
    
    # 5. 校验 request_body_schema 字段有 description
    if request_body_schema:
        missing = _validate_schema_has_descriptions(request_body_schema)
        if missing:
            errors.append(f"❌ request_body_schema 以下字段缺少 description: {', '.join(missing)}")
    
    # 6. 校验参数有 description
    for params, name in [(query_params, "query_params"), (path_params, "path_params"), (header_params, "header_params")]:
        if params:
            for p in params:
                if not p.get("description"):
                    errors.append(f"❌ {name} 参数 \"{p.get('name')}\" 缺少 description")
    
    # 7. 校验示例值不是占位符
    def _has_placeholder_values(example: Dict, path: str = "") -> List[str]:
        """检查示例数据是否包含占位符值"""
        placeholders = []
        if not isinstance(example, dict):
            return placeholders
        for key, value in example.items():
            full_path = f"{path}.{key}" if path else key
            if value == "string" or value == "":
                placeholders.append(f"{full_path}=\"string\"")
            elif value == 0 and key not in ["id", "code", "count", "total", "page", "size", "status"]:
                # 只对明显不应该是0的字段报错
                pass  # 0 有时是有效值，不做严格校验
            elif isinstance(value, dict):
                placeholders.extend(_has_placeholder_values(value, full_path))
        return placeholders
    
    if response_example:
        phs = _has_placeholder_values(response_example)
        if phs:
            errors.append(f"❌ response_example 包含占位符值: {', '.join(phs[:3])}。请使用真实的示例数据")
    
    if request_body_example:
        phs = _has_placeholder_values(request_body_example)
        if phs:
            errors.append(f"❌ request_body_example 包含占位符值: {', '.join(phs[:3])}。请使用真实的示例数据")
    
    # 如果有错误，返回所有错误
    if errors:
        return "🚫 接口定义不完整，请修正以下问题：\n\n" + "\n".join(errors)
    
    # 只保留显式传入的额外响应，不自动补齐错误响应
    final_responses = _normalize_explicit_responses(responses)
    
    # 添加成功响应
    success_response = {
        "code": 200,
        "name": "成功",
        "schema": response_schema,
        "example": response_example
    }
    # 确保成功响应在最前面
    final_responses = [r for r in final_responses if r.get("code") != 200]
    final_responses.insert(0, success_response)
    
    # 构建 OpenAPI 规范
    openapi_spec = _build_openapi_spec(
        title=title,
        path=path,
        method=method_upper,
        description=description,
        tags=tags,
        query_params=query_params,
        path_params=path_params,
        header_params=header_params,
        request_body_type=request_body_type,
        request_body_schema=request_body_schema,
        request_body_example=request_body_example,
        responses=final_responses,
        response_schema=None,
        response_example=None
    )
    
    import_payload = {
        "input": json.dumps(openapi_spec),
        "options": {
            "targetEndpointFolderId": folder_id,
            "targetSchemaFolderId": 0,
            "endpointOverwriteBehavior": "CREATE_NEW",  # 接口不覆盖，避免意外修改
            # Schema 使用覆盖策略，避免重复创建相同的 Schema
            "schemaOverwriteBehavior": "OVERWRITE_EXISTING"
        }
    }
    
    logger.info(f"正在创建接口: {method_upper} {path}")
    result = _make_request(
        "POST", 
        f"/projects/{resolved_project_id}/import-openapi?locale=zh-CN",
        data=import_payload
    )
    
    if not result["success"]:
        operation_logger.record(
            operation="create",
            resource_type="endpoint",
            project_id=resolved_project_id,
            target={"path": path, "method": method_upper},
            before=None,
            after=openapi_spec["paths"][path][method_upper.lower()],
            status="failed",
            error=result.get("error", "未知错误"),
        )
        return f"❌ 创建失败: {result.get('error', '未知错误')}"
    
    counters = result.get("data", {}).get("data", {}).get("counters", {})
    created = counters.get("endpointCreated", 0)
    updated = counters.get("endpointUpdated", 0)
    
    if created == 0 and updated == 0:
        return f"⚠️ 接口可能已存在或创建失败，请检查 Apifox 项目"
    
    response_codes = [r.get("code") for r in final_responses]
    action = "创建" if created > 0 else "更新"

    log_entry = operation_logger.record(
        operation="create",
        resource_type="endpoint",
        project_id=resolved_project_id,
        target={"path": path, "method": method_upper},
        before=None,
        after=openapi_spec["paths"][path][method_upper.lower()],
    )
    
    return f"""✅ 接口{action}成功!

📋 接口信息:
   • 名称: {title}
   • 路径: {method_upper} {path}
   • 描述: {description[:50]}{'...' if len(description) > 50 else ''}
   • 标签: {', '.join(tags) if tags else '无'}
   • 响应码: {', '.join(map(str, sorted(response_codes)))}
   • 操作日志: {log_entry['id']}
   
💡 错误响应未自动补齐；如需错误响应，请在 responses 中显式传入。"""


@mcp.tool()
def update_api_endpoint(
    project_id: str,
    path: str,
    method: str,
    title: str,
    description: str,
    response_schema: Dict,
    response_example: Dict,
    new_path: Optional[str] = None,
    new_method: Optional[str] = None,
    tags: Optional[List[str]] = None,
    query_params: Optional[List[Dict]] = None,
    path_params: Optional[List[Dict]] = None,
    header_params: Optional[List[Dict]] = None,
    request_body_type: str = "json",
    request_body_schema: Optional[Dict] = None,
    request_body_example: Optional[Dict] = None,
    responses: Optional[List[Dict]] = None,
    folder_id: int = 0,
    confirm_replace: bool = False,
    dry_run: bool = False
) -> str:
    """
    全量替换 Apifox 项目中的现有 HTTP 接口。

    ⚠️ 危险：这是全量覆盖操作，未传入的参数、请求体、响应和示例可能会丢失。
    修改接口名称、描述或标签时，请优先使用 patch_api_endpoint_metadata。
    只有需要重建完整接口定义时才使用本工具，并设置 confirm_replace=True。
    
    ⚠️ 强制要求 - 同 create_api_endpoint，以下内容必须提供：
    1. title: 中文业务名称
    2. description: 接口业务说明（只写元信息，不写示例！）
    3. response_schema: 成功响应的 JSON Schema（字段必须有 description）
    4. response_example: 成功响应的示例数据
    5. POST/PUT/PATCH 必须提供 request_body_schema 和 request_body_example
    
    Args:
        project_id: 【必填】目标 Apifox 项目 ID，必须来自 check_apifox_config 输出的项目列表
        path: 【必填】现有接口路径
        method: 【必填】现有接口的 HTTP 方法
        title: 【必填】接口中文业务名称
        description: 【必填】接口中文描述
        response_schema: 【必填】成功响应 JSON Schema
        response_example: 【必填】成功响应示例
        new_path: 新路径（如需修改）
        new_method: 新 HTTP 方法（如需修改）
        confirm_replace: 是否确认执行全量覆盖，默认 False
        dry_run: 只生成即将导入的 OpenAPI，不写入 Apifox
        其他参数同 create_api_endpoint
        
    Returns:
        更新结果信息
    """
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)

    if not confirm_replace:
        return """⚠️ 已阻止全量覆盖操作。

update_api_endpoint 会全量覆盖接口定义，未传入的参数、请求体、响应和示例可能会丢失。

常见安全修改请使用:
   • patch_api_endpoint_metadata: 修改名称、描述、标签
   • get_api_endpoint_snapshot: 更新前读取完整接口快照

如果你确认要全量覆盖，请重新调用并设置 confirm_replace=True。"""
    
    method_upper = method.upper()
    if method_upper not in HTTP_METHODS:
        return f"❌ 错误: 无效的 HTTP 方法 '{method}'"
    
    final_path = new_path if new_path else path
    final_method = new_method.upper() if new_method else method_upper
    
    if new_method and new_method.upper() not in HTTP_METHODS:
        return f"❌ 错误: 无效的新 HTTP 方法 '{new_method}'"
    
    errors = []
    
    # 校验 title
    title_lower = title.lower().strip()
    invalid_patterns = [
        title_lower.startswith(('get ', 'post ', 'put ', 'delete ', 'patch ')),
        title.startswith('/'),
    ]
    if any(invalid_patterns):
        errors.append(f"❌ title 格式错误: \"{title}\"")
    
    # 检查是否有角色前缀
    if '-' in title or '—' in title:
        errors.append(f"❌ title 格式错误: \"{title}\" 不应包含角色前缀")
    
    # 校验 description
    if not description or not description.strip():
        errors.append("❌ description 不能为空")
    
    # 校验 POST/PUT/PATCH 请求体
    if final_method in ['POST', 'PUT', 'PATCH']:
        if not request_body_schema:
            errors.append(f"❌ {final_method} 请求必须提供 request_body_schema")
        if not request_body_example:
            errors.append(f"❌ {final_method} 请求必须提供 request_body_example")
    
    # 校验 Schema 字段 description
    if response_schema:
        missing = _validate_schema_has_descriptions(response_schema)
        if missing:
            errors.append(f"❌ response_schema 字段缺少 description: {', '.join(missing)}")
    
    if request_body_schema:
        missing = _validate_schema_has_descriptions(request_body_schema)
        if missing:
            errors.append(f"❌ request_body_schema 字段缺少 description: {', '.join(missing)}")
    
    if errors:
        return "🚫 接口定义不完整：\n\n" + "\n".join(errors)
    
    # 只保留显式传入的额外响应，不自动补齐错误响应
    final_responses = _normalize_explicit_responses(responses)
    success_response = {"code": 200, "name": "成功", "schema": response_schema, "example": response_example}
    final_responses = [r for r in final_responses if r.get("code") != 200]
    final_responses.insert(0, success_response)
    
    openapi_spec = _build_openapi_spec(
        title=title,
        path=final_path,
        method=final_method,
        description=description,
        tags=tags,
        query_params=query_params,
        path_params=path_params,
        header_params=header_params,
        request_body_type=request_body_type,
        request_body_schema=request_body_schema,
        request_body_example=request_body_example,
        responses=final_responses,
        response_schema=None,
        response_example=None
    )

    if dry_run:
        return "🔎 DRY-RUN: 将执行全量覆盖，不会写入 Apifox\n\n紧凑预览:\n" + _compact_spec_preview(openapi_spec, final_path, final_method)
    
    import_payload = {
        "input": json.dumps(openapi_spec),
        "options": {
            "targetEndpointFolderId": folder_id,
            "targetSchemaFolderId": 0,
            "endpointOverwriteBehavior": "OVERWRITE_EXISTING",
            "schemaOverwriteBehavior": "OVERWRITE_EXISTING"
        }
    }
    
    logger.info(f"正在更新接口: {final_method} {final_path}")
    before_operation = None
    before_context = {}
    try:
        before_openapi_data = _export_openapi(resolved_project_id)
        before_operation = _snapshot_endpoint(before_openapi_data, path, method_upper)
        before_context = _endpoint_log_context(before_openapi_data)
    except (RuntimeError, KeyError):
        before_operation = None

    result = _make_request("POST", f"/projects/{resolved_project_id}/import-openapi?locale=zh-CN", data=import_payload)
    
    if not result["success"]:
        operation_logger.record(
            operation="update",
            resource_type="endpoint",
            project_id=resolved_project_id,
            target={"path": path, "method": method_upper},
            before=before_operation,
            after=openapi_spec["paths"][final_path][final_method.lower()],
            status="failed",
            error=result.get("error", "未知错误"),
            context=before_context,
        )
        return f"❌ 更新失败: {result.get('error', '未知错误')}"
    
    try:
        after_openapi_data = _export_openapi(resolved_project_id)
        after_operation, _ = _get_operation(after_openapi_data, final_path, final_method)
        before_snapshot = _operation_snapshot(before_operation) if before_operation else {}
        after_snapshot = _operation_snapshot(after_operation)
        review_lines = _summarize_snapshot_diff(before_snapshot, after_snapshot) if before_snapshot else ["   • 写入后接口存在，无法生成 before 对比"]
        losses = _detect_unexpected_loss(before_snapshot, after_snapshot) if before_snapshot else []
    except (RuntimeError, KeyError) as exc:
        log_entry = operation_logger.record(
            operation="update",
            resource_type="endpoint",
            project_id=resolved_project_id,
            target={"path": path, "method": method_upper},
            before=before_operation,
            after=openapi_spec["paths"][final_path][final_method.lower()],
            status="failed",
            error=f"写后复核失败: {exc}",
            context=before_context,
        )
        return f"⚠️ 接口已写入，但写后复核失败: {exc}\n\n操作日志: {log_entry['id']}"

    counters = result.get("data", {}).get("data", {}).get("counters", {})
    updated = counters.get("endpointUpdated", 0)
    action = "更新" if updated > 0 else "创建"

    log_entry = operation_logger.record(
        operation="update",
        resource_type="endpoint",
        project_id=resolved_project_id,
        target={"path": path, "method": method_upper},
        before=before_operation,
        after=after_operation,
        context=before_context,
    )

    output = [
        f"✅ 接口{action}成功!",
        "",
        "📋 接口信息:",
        f"   • 名称: {title}",
        f"   • 路径: {final_method} {final_path}",
        f"   • 描述: {description[:50]}{'...' if len(description) > 50 else ''}",
        "",
        "写后复核:",
        *review_lines,
    ]
    if losses:
        output.append("")
        output.append("⚠️ 检测到非预期信息丢失: " + ", ".join(losses))
    output.append("")
    output.append(f"操作日志: {log_entry['id']}")
    
    return "\n".join(output)


@mcp.tool()
def get_api_endpoint_detail(project_id: str, path: str, method: str) -> str:
    """获取 HTTP 接口的详细信息。"""
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)
    
    method_lower = method.lower()
    logger.info(f"正在获取接口详情: {method.upper()} {path}")
    
    export_payload = {
        "scope": {"type": "ALL"},
        "options": {"includeApifoxExtensionProperties": True, "addFoldersToTags": False},
        "oasVersion": "3.1",
        "exportFormat": "JSON"
    }
    
    result = _make_request("POST", f"/projects/{resolved_project_id}/export-openapi?locale=zh-CN", data=export_payload)
    
    if not result["success"]:
        return f"❌ 获取失败: {result.get('error', '未知错误')}"
    
    paths = result.get("data", {}).get("paths", {})
    
    if path not in paths:
        return f"❌ 未找到路径为 {path} 的接口"
    
    path_item = paths[path]
    if method_lower not in path_item:
        return f"❌ 未找到 {method.upper()} {path} 接口"
    
    api = path_item[method_lower]
    title = api.get("summary", "未命名")
    desc = api.get("description", "无")
    tags = api.get("tags", [])
    params = api.get("parameters", [])
    responses = api.get("responses", {})
    
    output = [
        f"📋 接口详情: {title}",
        "=" * 50,
        f"📍 路径: {method.upper()} {path}",
        f"📝 说明: {desc}",
        f"🏷️ 标签: {', '.join(tags) if tags else '无'}",
        "",
        f"📥 参数 ({len(params)} 个):"
    ]
    
    if params:
        for p in params:
            output.append(f"   • [{p.get('in')}] {p.get('name')}: {p.get('schema', {}).get('type', 'any')}")
    else:
        output.append("   无")
    
    output.append("")
    output.append(f"📤 响应 ({len(responses)} 个):")
    for code, resp in responses.items():
        output.append(f"   • {code}: {resp.get('description', '')}")
    
    return "\n".join(output)
