"""面向 AI 的 Apifox MCP v2 高层工具。"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Literal, Optional, Tuple

from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field

from ..config import APIFOX_API_VERSION, APIFOX_PUBLIC_API, APIFOX_TOKEN, mcp
from ..core import (
    HTTP_METHODS,
    ApifoxError,
    OpenApiRepository,
    build_minimal_spec,
    canonical_hash,
    deep_merge,
    dependency_closure,
    iter_refs,
    json_pointer_get,
    missing_descriptions,
    missing_refs,
    remove_json_pointer,
    select_operation_sections,
    strip_examples,
    subset_mismatches,
)
from ..operation_log import operation_logger
from ..utils import _get_projects, _resolve_project_id

repository = OpenApiRepository()


class EndpointTarget(BaseModel):
    path: str = Field(description="不含服务域名的接口路径")
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"] = "GET"


class EndpointChange(EndpointTarget):
    action: Literal["create", "patch", "replace"] = "patch"
    patch: Optional[Dict[str, Any]] = Field(default=None, description="要递归合并的 OpenAPI operation 片段")
    document: Optional[Dict[str, Any]] = Field(default=None, description="create/replace 使用的完整 OpenAPI operation")
    remove_paths: List[str] = Field(default_factory=list, description="相对 operation 的 JSON Pointer 列表")
    expected_revision: Optional[str] = Field(default=None, description="read_api_documents 返回的 revision")
    confirm_replace: bool = False


class SchemaChange(BaseModel):
    name: str
    action: Literal["create", "patch", "replace"] = "patch"
    patch: Optional[Dict[str, Any]] = Field(default=None, description="要递归合并的 JSON Schema 片段")
    document: Optional[Dict[str, Any]] = Field(default=None, description="create/replace 使用的完整 JSON Schema")
    remove_paths: List[str] = Field(default_factory=list, description="相对 Schema 的 JSON Pointer 列表")
    expected_revision: Optional[str] = None
    confirm_replace: bool = False


class FolderChange(BaseModel):
    name: str
    action: Literal["create"] = "create"
    description: str = ""


def _dict_item(item: Any) -> Dict[str, Any]:
    if isinstance(item, BaseModel):
        return item.model_dump(exclude_none=True)
    return dict(item)


def _dict_items(items: Optional[List[Any]]) -> List[Dict[str, Any]]:
    return [_dict_item(item) for item in (items or [])]


def _project_id(project_id: str) -> str:
    if not APIFOX_TOKEN:
        raise ApifoxError("缺少 APIFOX_TOKEN 环境变量")
    try:
        return _resolve_project_id(project_id)
    except ValueError as exc:
        raise ApifoxError(str(exc)) from exc


def _metrics(cache_hit: Optional[bool] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = repository.client.metrics.snapshot()
    if cache_hit is not None:
        result["cache_hit"] = cache_hit
    return result


def _operation(document: Dict[str, Any], path: str, method: str) -> Dict[str, Any]:
    operation = document.get("paths", {}).get(path, {}).get(method.lower())
    if operation is None:
        raise ApifoxError(f"未找到接口: {method.upper()} {path}")
    return operation


def _iter_operations(document: Dict[str, Any]):
    for path, path_item in (document.get("paths") or {}).items():
        for method, operation in (path_item or {}).items():
            if method in HTTP_METHODS and isinstance(operation, dict):
                yield path, method, operation


def _validate_schema_examples(spec: Dict[str, Any], endpoint_keys: List[Tuple[str, str]]) -> List[str]:
    issues: List[str] = []
    components = spec.get("components", {})
    for path, method in endpoint_keys:
        operation = spec.get("paths", {}).get(path, {}).get(method.lower(), {})
        bodies = []
        request_content = operation.get("requestBody", {}).get("content", {})
        bodies.extend((f"{method.upper()} {path} request", content) for content in request_content.values())
        for code, response in (operation.get("responses") or {}).items():
            bodies.extend(
                (f"{method.upper()} {path} response {code}", content)
                for content in response.get("content", {}).values()
            )
        for label, content in bodies:
            schema = content.get("schema")
            example = content.get("example")
            if not isinstance(schema, dict) or example is None:
                continue
            validation_schema = {**copy.deepcopy(schema), "components": copy.deepcopy(components)}
            for error in Draft202012Validator(validation_schema).iter_errors(example):
                location = "/".join(str(part) for part in error.absolute_path)
                issues.append(f"{label}{('/' + location) if location else ''}: {error.message}")
                if len(issues) >= 20:
                    return issues
    return issues


def _operation_schema_entries(operation: Dict[str, Any]):
    for media_type, content in operation.get("requestBody", {}).get("content", {}).items():
        schema = content.get("schema")
        if isinstance(schema, dict):
            yield f"requestBody/{media_type}", schema
    for code, response in (operation.get("responses") or {}).items():
        for media_type, content in response.get("content", {}).items():
            schema = content.get("schema")
            if isinstance(schema, dict):
                yield f"responses/{code}/{media_type}", schema


def _validate_document(
    spec: Dict[str, Any], changed_schemas: List[str], endpoint_keys: List[Tuple[str, str]]
) -> List[str]:
    issues: List[str] = []
    schemas = spec.get("components", {}).get("schemas", {})
    for name in changed_schemas:
        schema = schemas.get(name)
        if schema is None:
            issues.append(f"Schema 不存在: {name}")
            continue
        for field in missing_descriptions(schema):
            issues.append(f"{name}.{field} 缺少 description")
    for path, method in endpoint_keys:
        operation = spec.get("paths", {}).get(path, {}).get(method.lower(), {})
        label = f"{method.upper()} {path}"
        if not operation.get("summary"):
            issues.append(f"{label} 缺少 summary")
        if not operation.get("description"):
            issues.append(f"{label} 缺少 description")
        for parameter in operation.get("parameters") or []:
            if not parameter.get("description"):
                issues.append(f"{label} 参数 {parameter.get('name', '')} 缺少 description")
        success_responses = [
            response for code, response in (operation.get("responses") or {}).items() if str(code).startswith("2")
        ]
        if not success_responses:
            issues.append(f"{label} 缺少成功响应")
        for location, schema in _operation_schema_entries(operation):
            if "$ref" not in schema:
                issues.extend(f"{label} {location}.{field} 缺少 description" for field in missing_descriptions(schema))
    for ref in missing_refs(spec, schemas):
        issues.append(f"未解析的 $ref: {ref}")
    issues.extend(_validate_schema_examples(spec, endpoint_keys))
    return issues


def _pointer_exists(value: Any, pointer: str) -> bool:
    try:
        json_pointer_get(value, pointer)
        return True
    except (KeyError, IndexError, TypeError, ValueError):
        return False


@mcp.tool()
def get_apifox_status() -> Dict[str, Any]:
    """检查连接并返回可用项目；开始使用前调用。"""
    repository.client.reset_metrics()
    if not APIFOX_TOKEN:
        return {"ok": False, "error": {"code": "missing_token", "message": "缺少 APIFOX_TOKEN"}}

    projects = []
    for configured in _get_projects():
        try:
            document, cache_hit = repository.export(configured["id"])
            projects.append(
                {
                    **configured,
                    "connected": True,
                    "title": document.get("info", {}).get("title", configured["name"]),
                    "endpoint_count": sum(1 for _ in _iter_operations(document)),
                    "schema_count": len(document.get("components", {}).get("schemas", {})),
                    "cache_hit": cache_hit,
                }
            )
        except ApifoxError as exc:
            projects.append({**configured, "connected": False, "error": str(exc)})
    return {
        "ok": all(project.get("connected") for project in projects),
        "api": {"base_url": APIFOX_PUBLIC_API, "version": APIFOX_API_VERSION},
        "projects": projects,
        "metrics": _metrics(),
    }


@mcp.tool()
def search_api_documents(
    project_id: str,
    query: str = "",
    resource_types: Optional[List[Literal["endpoint", "schema"]]] = None,
    methods: Optional[List[Literal["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]]] = None,
    tags: Optional[List[str]] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """按关键词、路径、方法或标签搜索接口与 Schema。"""
    repository.client.reset_metrics()
    resolved = _project_id(project_id)
    document, cache_hit = repository.export(resolved)
    query_lower = query.lower().strip()
    wanted_types = set(resource_types or ["endpoint", "schema"])
    wanted_methods = {method.lower() for method in (methods or [])}
    wanted_tags = {tag.lower() for tag in (tags or [])}
    results: List[Dict[str, Any]] = []

    if "endpoint" in wanted_types:
        for path, method, operation in _iter_operations(document):
            operation_tags = [str(tag) for tag in operation.get("tags", [])]
            haystack = " ".join(
                [
                    path,
                    operation.get("summary", ""),
                    operation.get("description", ""),
                    " ".join(operation_tags),
                ]
            ).lower()
            if query_lower and query_lower not in haystack:
                continue
            if wanted_methods and method not in wanted_methods:
                continue
            if wanted_tags and not wanted_tags.intersection(tag.lower() for tag in operation_tags):
                continue
            results.append(
                {
                    "resource_type": "endpoint",
                    "path": path,
                    "method": method.upper(),
                    "summary": operation.get("summary", ""),
                    "tags": operation_tags,
                    "status": operation.get("x-apifox-status", "unknown"),
                }
            )

    if "schema" in wanted_types:
        for name, schema in document.get("components", {}).get("schemas", {}).items():
            haystack = f"{name} {schema.get('description', '')}".lower()
            if query_lower and query_lower not in haystack:
                continue
            results.append(
                {
                    "resource_type": "schema",
                    "name": name,
                    "type": schema.get("type", "object"),
                    "description": schema.get("description", ""),
                    "field_count": len(schema.get("properties", {})),
                }
            )

    return {
        "ok": True,
        "total": len(results),
        "results": results[: max(1, min(limit, 100))],
        "metrics": _metrics(cache_hit),
    }


@mcp.tool()
def read_api_documents(
    project_id: str,
    endpoints: Optional[List[EndpointTarget]] = None,
    schemas: Optional[List[str]] = None,
    sections: Optional[List[str]] = None,
    include_examples: bool = True,
    field_paths: Optional[List[str]] = None,
    force_refresh: bool = False,
    cursor: int = 0,
    max_output_chars: int = 80000,
) -> Dict[str, Any]:
    """批量读取目标接口或 Schema，只返回它们实际依赖的模型。"""
    repository.client.reset_metrics()
    resolved = _project_id(project_id)
    document, cache_hit = repository.export(resolved, force=force_refresh and cursor == 0)
    output_documents: List[Dict[str, Any]] = []
    endpoints = _dict_items(endpoints)

    for target in endpoints or []:
        path = str(target.get("path", ""))
        method = str(target.get("method", "GET")).lower()
        operation = _operation(document, path, method)
        selected = select_operation_sections(operation, sections)
        closure = dependency_closure(document, iter_refs(selected))
        item: Dict[str, Any] = {
            "target": {"resource_type": "endpoint", "path": path, "method": method.upper()},
            "revision": canonical_hash(operation),
            "operation": selected,
            "components": {"schemas": closure},
        }
        output_documents.append(item if include_examples else strip_examples(item))

    for name in schemas or []:
        schema = document.get("components", {}).get("schemas", {}).get(name)
        if schema is None:
            raise ApifoxError(f"未找到 Schema: {name}")
        closure = dependency_closure(document, [name])
        item = {
            "target": {"resource_type": "schema", "name": name},
            "revision": canonical_hash(schema),
            "schemas": closure,
        }
        output_documents.append(item if include_examples else strip_examples(item))

    if field_paths:
        selected_values = []
        for pointer in field_paths:
            try:
                selected_values.append({"path": pointer, "value": json_pointer_get(output_documents, pointer)})
            except (KeyError, IndexError, TypeError, ValueError):
                selected_values.append({"path": pointer, "error": "路径不存在"})
        output_documents = selected_values

    payload = {
        "ok": True,
        "documents": output_documents,
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    limit = max(10000, min(max_output_chars, 200000))
    if len(serialized) <= limit and cursor == 0:
        result = {**payload, "metrics": _metrics(cache_hit)}
        result["output_chars"] = len(serialized)
        return result

    start = max(0, cursor)
    end = min(len(serialized), start + limit)
    return {
        "ok": True,
        "paginated": True,
        "encoding": "json-text",
        "chunk": serialized[start:end],
        "cursor": start,
        "next_cursor": end if end < len(serialized) else None,
        "total_chars": len(serialized),
        "metrics": _metrics(cache_hit),
    }


def _apply_resource_changes(
    document: Dict[str, Any],
    endpoint_changes: List[Dict[str, Any]],
    schema_changes: List[Dict[str, Any]],
    folder_changes: List[Dict[str, Any]],
) -> Tuple[List[Tuple[str, str]], List[str], List[Dict[str, Any]]]:
    endpoint_keys: List[Tuple[str, str]] = []
    schema_names: List[str] = []
    applied: List[Dict[str, Any]] = []
    paths = document.setdefault("paths", {})
    schemas = document.setdefault("components", {}).setdefault("schemas", {})

    for change in endpoint_changes:
        path = str(change.get("path", ""))
        method = str(change.get("method", "GET")).lower()
        action = str(change.get("action", "patch")).lower()
        current = paths.get(path, {}).get(method)
        if action == "create":
            if current is not None:
                raise ApifoxError(f"接口已存在，不能 create: {method.upper()} {path}")
            updated = copy.deepcopy(change.get("document") or {})
            if not updated:
                raise ApifoxError(f"create 缺少 document: {method.upper()} {path}")
        elif action == "replace":
            if not change.get("confirm_replace"):
                raise ApifoxError(f"replace 必须设置 confirm_replace=true: {method.upper()} {path}")
            updated = copy.deepcopy(change.get("document") or {})
        else:
            if current is None:
                raise ApifoxError(f"接口不存在，不能 patch: {method.upper()} {path}")
            expected_revision = change.get("expected_revision")
            if expected_revision and expected_revision != canonical_hash(current):
                raise ApifoxError(f"接口已发生并发变化: {method.upper()} {path}")
            updated = copy.deepcopy(current)
            deep_merge(updated, change.get("patch") or {})
            for pointer in change.get("remove_paths") or []:
                remove_json_pointer(updated, pointer)
        paths.setdefault(path, {})[method] = updated
        endpoint_keys.append((path, method))
        applied.append({"resource_type": "endpoint", "path": path, "method": method.upper(), "action": action})

    for change in schema_changes:
        name = str(change.get("name", ""))
        action = str(change.get("action", "patch")).lower()
        current = schemas.get(name)
        if action == "create":
            if current is not None:
                raise ApifoxError(f"Schema 已存在，不能 create: {name}")
            updated = copy.deepcopy(change.get("document") or {})
            if not updated:
                raise ApifoxError(f"create 缺少 document: {name}")
        elif action == "replace":
            if not change.get("confirm_replace"):
                raise ApifoxError(f"replace 必须设置 confirm_replace=true: {name}")
            updated = copy.deepcopy(change.get("document") or {})
        else:
            if current is None:
                raise ApifoxError(f"Schema 不存在，不能 patch: {name}")
            expected_revision = change.get("expected_revision")
            if expected_revision and expected_revision != canonical_hash(current):
                raise ApifoxError(f"Schema 已发生并发变化: {name}")
            updated = copy.deepcopy(current)
            deep_merge(updated, change.get("patch") or {})
            for pointer in change.get("remove_paths") or []:
                remove_json_pointer(updated, pointer)
        schemas[name] = updated
        schema_names.append(name)
        applied.append({"resource_type": "schema", "name": name, "action": action})

    tags = document.setdefault("tags", [])
    existing_names = {tag.get("name") if isinstance(tag, dict) else tag for tag in tags}
    for change in folder_changes:
        if str(change.get("action", "create")).lower() != "create":
            raise ApifoxError("目录仅支持 create")
        name = str(change.get("name", ""))
        if name and name not in existing_names:
            tags.append({"name": name, "description": str(change.get("description", ""))})
            existing_names.add(name)
            applied.append({"resource_type": "folder", "name": name, "action": "create"})

    return endpoint_keys, schema_names, applied


def _verify_changes(
    after: Dict[str, Any],
    endpoint_changes: List[Dict[str, Any]],
    schema_changes: List[Dict[str, Any]],
    expected_spec: Dict[str, Any],
) -> List[str]:
    mismatches: List[str] = []
    for change in endpoint_changes:
        path = str(change.get("path", ""))
        method = str(change.get("method", "GET")).lower()
        actual = after.get("paths", {}).get(path, {}).get(method)
        if actual is None:
            mismatches.append(f"{method.upper()} {path}: 写入后不存在")
            continue
        expected = change.get("patch") if change.get("action", "patch") == "patch" else change.get("document")
        mismatches.extend(f"{method.upper()} {path}{item}" for item in subset_mismatches(expected or {}, actual))
        for pointer in change.get("remove_paths") or []:
            if _pointer_exists(actual, pointer):
                mismatches.append(f"{method.upper()} {path}{pointer}: 应删除但仍存在")

    schemas = after.get("components", {}).get("schemas", {})
    for change in schema_changes:
        name = str(change.get("name", ""))
        actual = schemas.get(name)
        if actual is None:
            mismatches.append(f"Schema {name}: 写入后不存在")
            continue
        expected = change.get("patch") if change.get("action", "patch") == "patch" else change.get("document")
        mismatches.extend(f"Schema {name}{item}" for item in subset_mismatches(expected or {}, actual))
        for pointer in change.get("remove_paths") or []:
            if _pointer_exists(actual, pointer):
                mismatches.append(f"Schema {name}{pointer}: 应删除但仍存在")
    for ref in missing_refs(
        build_minimal_spec(
            after,
            [(str(item.get("path", "")), str(item.get("method", "GET")).lower()) for item in endpoint_changes],
            [str(item.get("name", "")) for item in schema_changes],
        ),
        schemas,
    ):
        mismatches.append(f"写入后存在未解析引用: {ref}")

    # Apifox 可能返回成功计数，但把未随导入携带的嵌套引用变成空对象。
    for path, path_item in expected_spec.get("paths", {}).items():
        for method, expected_operation in path_item.items():
            actual_operation = after.get("paths", {}).get(path, {}).get(method)
            mismatches.extend(
                f"{method.upper()} {path}{item}" for item in subset_mismatches(expected_operation, actual_operation)
            )
    for name, expected_schema in expected_spec.get("components", {}).get("schemas", {}).items():
        actual_schema = schemas.get(name)
        mismatches.extend(f"Schema {name}{item}" for item in subset_mismatches(expected_schema, actual_schema))
    return list(dict.fromkeys(mismatches))


def _verify_spec_subset(expected_spec: Dict[str, Any], actual: Dict[str, Any]) -> List[str]:
    mismatches: List[str] = []
    for path, path_item in expected_spec.get("paths", {}).items():
        for method, expected_operation in path_item.items():
            actual_operation = actual.get("paths", {}).get(path, {}).get(method)
            mismatches.extend(
                f"{method.upper()} {path}{item}" for item in subset_mismatches(expected_operation, actual_operation)
            )
    actual_schemas = actual.get("components", {}).get("schemas", {})
    for name, expected_schema in expected_spec.get("components", {}).get("schemas", {}).items():
        mismatches.extend(
            f"Schema {name}{item}" for item in subset_mismatches(expected_schema, actual_schemas.get(name))
        )
    return list(dict.fromkeys(mismatches))


@mcp.tool()
def apply_api_document_changes(
    project_id: str,
    endpoint_changes: Optional[List[EndpointChange]] = None,
    schema_changes: Optional[List[SchemaChange]] = None,
    folder_changes: Optional[List[FolderChange]] = None,
    dry_run: bool = False,
    rollback_on_failure: bool = True,
) -> Dict[str, Any]:
    """分组创建或修改接口、Schema 和目录，并自动回读校验。"""
    repository.client.reset_metrics()
    resolved = _project_id(project_id)
    endpoint_changes = _dict_items(endpoint_changes)
    schema_changes = _dict_items(schema_changes)
    folder_changes = _dict_items(folder_changes)
    if not endpoint_changes and not schema_changes and not folder_changes:
        raise ApifoxError("至少提供一项变更")

    before, cache_hit = repository.export(resolved)
    working = copy.deepcopy(before)
    endpoint_keys, schema_names, applied = _apply_resource_changes(
        working, endpoint_changes, schema_changes, folder_changes
    )
    include_tags = bool(folder_changes)
    after_spec = build_minimal_spec(working, endpoint_keys, schema_names, include_tags)
    issues = _validate_document(after_spec, schema_names, endpoint_keys)
    if issues:
        return {"ok": False, "stage": "validation", "issues": issues, "metrics": _metrics(cache_hit)}

    before_existing_endpoints = [
        key for key in endpoint_keys if before.get("paths", {}).get(key[0], {}).get(key[1]) is not None
    ]
    before_existing_schemas = [name for name in schema_names if name in before.get("components", {}).get("schemas", {})]
    before_spec = build_minimal_spec(before, before_existing_endpoints, before_existing_schemas, include_tags)
    if canonical_hash(before_spec) == canonical_hash(after_spec):
        return {"ok": True, "status": "no_change", "changes": applied, "metrics": _metrics(cache_hit)}
    if dry_run:
        return {
            "ok": True,
            "status": "dry_run",
            "changes": applied,
            "import_bytes": len(json.dumps(after_spec, ensure_ascii=False).encode("utf-8")),
            "component_count": len(after_spec.get("components", {}).get("schemas", {})),
            "metrics": _metrics(cache_hit),
        }

    repository.import_spec(resolved, after_spec)
    after, _ = repository.export(resolved, force=True)
    mismatches = _verify_changes(after, endpoint_changes, schema_changes, after_spec)
    created = [item for item in applied if item["action"] == "create"]
    rolled_back = False
    rollback_error = None
    if mismatches and rollback_on_failure and (before_existing_endpoints or before_existing_schemas):
        try:
            repository.import_spec(resolved, before_spec)
            rollback_after, _ = repository.export(resolved, force=True)
            rollback_mismatches = _verify_spec_subset(before_spec, rollback_after)
            if rollback_mismatches:
                rollback_error = "; ".join(rollback_mismatches)
            else:
                rolled_back = True
        except ApifoxError as exc:
            rollback_error = str(exc)

    status = "completed" if not mismatches else "failed"
    log_entry = operation_logger.record(
        operation="apply",
        resource_type="transaction",
        project_id=resolved,
        target={"changes": applied},
        before=before_spec,
        after=after_spec,
        status=status,
        error="; ".join(mismatches) if mismatches else None,
        context={"created": created},
    )
    return {
        "ok": not mismatches,
        "status": status,
        "changes": applied,
        "verified": not mismatches,
        "mismatches": mismatches,
        "rolled_back": rolled_back,
        "rollback_error": rollback_error,
        "manual_cleanup": created if mismatches and created else [],
        "operation_id": log_entry["id"],
        "import_bytes": len(json.dumps(after_spec, ensure_ascii=False).encode("utf-8")),
        "component_count": len(after_spec.get("components", {}).get("schemas", {})),
        "metrics": _metrics(cache_hit),
    }


@mcp.tool()
def audit_api_documents(
    project_id: str,
    endpoints: Optional[List[EndpointTarget]] = None,
    tag: str = "",
) -> Dict[str, Any]:
    """审计响应、字段描述、示例和引用完整性。"""
    repository.client.reset_metrics()
    resolved = _project_id(project_id)
    document, cache_hit = repository.export(resolved)
    endpoints = _dict_items(endpoints)
    endpoint_filter = {
        (str(item.get("path", "")), str(item.get("method", "GET")).lower()) for item in (endpoints or [])
    }
    schemas = document.get("components", {}).get("schemas", {})
    findings: List[Dict[str, Any]] = []

    for path, method, operation in _iter_operations(document):
        if endpoint_filter and (path, method) not in endpoint_filter:
            continue
        if tag and tag not in operation.get("tags", []):
            continue
        issues: List[str] = []
        success = [
            response for code, response in (operation.get("responses") or {}).items() if str(code).startswith("2")
        ]
        if not success:
            issues.append("缺少成功响应")
        for response in success:
            content = response.get("content", {}).get("application/json", {})
            if not content.get("schema"):
                issues.append("成功响应缺少 Schema")
            if "example" not in content and "examples" not in content:
                issues.append("成功响应缺少 Example")
        closure = dependency_closure(document, iter_refs(operation))
        for name, schema in closure.items():
            issues.extend(f"{name}.{field} 缺少 description" for field in missing_descriptions(schema))
        for location, schema in _operation_schema_entries(operation):
            if "$ref" not in schema:
                issues.extend(f"{location}.{field} 缺少 description" for field in missing_descriptions(schema))
        issues.extend(f"未解析的 $ref: {name}" for name in missing_refs(operation, schemas))
        if issues:
            findings.append({"path": path, "method": method.upper(), "issues": sorted(set(issues))})

    return {
        "ok": not findings,
        "checked": len(endpoint_filter) if endpoint_filter else sum(1 for _ in _iter_operations(document)),
        "findings": findings,
        "metrics": _metrics(cache_hit),
    }


@mcp.tool()
def list_change_logs(project_id: str = "", limit: int = 20) -> Dict[str, Any]:
    """列出最近的分组写入和撤销日志。"""
    resolved = _resolve_project_id(project_id) if project_id else None
    logs = operation_logger.list_logs(project_id=resolved, limit=max(1, min(limit, 100)))
    return {
        "ok": True,
        "logs": [
            {
                "id": entry.get("id"),
                "timestamp": entry.get("timestamp"),
                "operation": entry.get("operation"),
                "resource_type": entry.get("resource_type"),
                "target": entry.get("target"),
                "status": entry.get("status"),
                "error": entry.get("error"),
            }
            for entry in logs
        ],
    }


@mcp.tool()
def undo_change(operation_id: str) -> Dict[str, Any]:
    """恢复一次可恢复的 v2 分组写入。"""
    repository.client.reset_metrics()
    entry = operation_logger.get(operation_id)
    if entry.get("operation") != "apply" or entry.get("resource_type") != "transaction":
        raise ApifoxError("仅支持撤销 v2 apply 事务")
    resolved = _project_id(str(entry.get("project_id", "")))
    before_spec = entry.get("before")
    if not before_spec:
        raise ApifoxError("日志缺少 before 快照")
    repository.import_spec(resolved, before_spec)
    repository.export(resolved, force=True)
    created = entry.get("context", {}).get("created", [])
    undo_log = operation_logger.record(
        operation="undo",
        resource_type="transaction",
        project_id=resolved,
        target={"operation_id": operation_id},
        before=entry.get("after"),
        after=before_spec,
        context={"created": created},
    )
    return {
        "ok": True,
        "restored": True,
        "manual_cleanup": created,
        "operation_id": undo_log["id"],
        "metrics": _metrics(),
    }
