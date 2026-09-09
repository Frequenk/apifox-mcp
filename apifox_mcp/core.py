"""Apifox OpenAPI 访问、缓存和结构处理核心。"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import requests

from .config import APIFOX_API_VERSION, APIFOX_PUBLIC_API, APIFOX_TOKEN

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}


class ApifoxError(RuntimeError):
    """Apifox 调用或文档处理失败。"""

    def __init__(
        self,
        message: str,
        code: str = "tool_error",
        details: Optional[Dict[str, Any]] = None,
        recovery: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details
        self.recovery = recovery


@dataclass
class RequestMetrics:
    request_count: int = 0
    elapsed_ms: int = 0
    request_bytes: int = 0
    response_bytes: int = 0

    def snapshot(self) -> Dict[str, int]:
        return {
            "request_count": self.request_count,
            "elapsed_ms": self.elapsed_ms,
            "request_bytes": self.request_bytes,
            "response_bytes": self.response_bytes,
        }


class ApifoxClient:
    """复用连接的 Apifox HTTP 客户端。"""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.metrics = RequestMetrics()

    def reset_metrics(self) -> None:
        self.metrics = RequestMetrics()

    def request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        started = time.perf_counter()
        body = json.dumps(data, ensure_ascii=False) if data is not None else ""
        try:
            response = self.session.request(
                method=method,
                url=f"{APIFOX_PUBLIC_API}{endpoint}",
                json=data,
                headers={
                    "Authorization": f"Bearer {APIFOX_TOKEN}",
                    "Content-Type": "application/json",
                    "X-Apifox-Api-Version": APIFOX_API_VERSION,
                },
                timeout=30,
            )
        except requests.Timeout as exc:
            raise ApifoxError("请求超时，请检查网络连接") from exc
        except requests.ConnectionError as exc:
            raise ApifoxError("网络连接失败") from exc
        finally:
            elapsed = int((time.perf_counter() - started) * 1000)
            self.metrics.request_count += 1
            self.metrics.elapsed_ms += elapsed
            self.metrics.request_bytes += len(body.encode("utf-8"))

        self.metrics.response_bytes += len(response.content)
        if response.status_code not in {200, 201, 204}:
            try:
                error_data = response.json()
                detail = error_data.get("message") or error_data.get("errorMessage") or error_data.get("error")
            except (ValueError, AttributeError):
                detail = response.text[:300]
            raise ApifoxError(f"HTTP {response.status_code}: {detail or '未知错误'}")

        if not response.text:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}


class OpenApiRepository:
    """提供统一缓存、导入和强制回读。"""

    def __init__(self, client: Optional[ApifoxClient] = None) -> None:
        self.client = client or ApifoxClient()
        self.cache_ttl = int(os.getenv("APIFOX_MCP_CACHE_TTL_SECONDS", "300"))
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    def export(self, project_id: str, force: bool = False) -> Tuple[Dict[str, Any], bool]:
        cached = self._cache.get(project_id)
        if not force and cached and time.time() - cached[0] <= self.cache_ttl:
            return copy.deepcopy(cached[1]), True

        payload = {
            "scope": {"type": "ALL"},
            "options": {"includeApifoxExtensionProperties": True, "addFoldersToTags": False},
            "oasVersion": "3.1",
            "exportFormat": "JSON",
        }
        data = self.client.request(
            "POST",
            f"/projects/{project_id}/export-openapi?locale=zh-CN",
            payload,
        )
        self._cache[project_id] = (time.time(), copy.deepcopy(data))
        return data, False

    def import_spec(self, project_id: str, spec: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "input": json.dumps(spec, ensure_ascii=False),
            "options": {
                "targetEndpointFolderId": 0,
                "targetSchemaFolderId": 0,
                "endpointOverwriteBehavior": "OVERWRITE_EXISTING",
                "schemaOverwriteBehavior": "OVERWRITE_EXISTING",
            },
        }
        result = self.client.request(
            "POST",
            f"/projects/{project_id}/import-openapi?locale=zh-CN",
            payload,
        )
        self._cache.pop(project_id, None)
        return result

    def invalidate(self, project_id: str) -> None:
        self._cache.pop(project_id, None)

    def cache_state(self) -> Dict[str, Any]:
        now = time.time()
        return {project_id: self.cache_summary(project_id, now=now) for project_id in self._cache}

    def cache_summary(self, project_id: str, now: Optional[float] = None) -> Dict[str, Any]:
        cached = self._cache.get(project_id)
        if not cached:
            return {"available": False, "fresh": False}
        saved_at, document = cached
        current_time = time.time() if now is None else now
        age_seconds = max(0.0, current_time - saved_at)
        endpoint_count = sum(
            1
            for path_item in document.get("paths", {}).values()
            if isinstance(path_item, dict)
            for method in path_item
            if method.lower() in HTTP_METHODS
        )
        return {
            "available": True,
            "fresh": age_seconds <= self.cache_ttl,
            "age_seconds": round(age_seconds, 3),
            "title": document.get("info", {}).get("title", ""),
            "endpoint_count": endpoint_count,
            "schema_count": len(document.get("components", {}).get("schemas", {})),
        }


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def iter_refs(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            yield ref.rsplit("/", 1)[-1]
        for child in value.values():
            yield from iter_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_refs(child)


def dependency_closure(document: Dict[str, Any], seeds: Iterable[str]) -> Dict[str, Any]:
    schemas = document.get("components", {}).get("schemas", {})
    pending = list(dict.fromkeys(seeds))
    seen: Set[str] = set()
    result: Dict[str, Any] = {}
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        schema = schemas.get(name)
        if schema is None:
            continue
        result[name] = copy.deepcopy(schema)
        pending.extend(ref for ref in iter_refs(schema) if ref not in seen)
    return {name: result[name] for name in sorted(result)}


def missing_refs(value: Any, schemas: Dict[str, Any]) -> List[str]:
    return sorted({name for name in iter_refs(value) if name not in schemas})


def deep_merge(target: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """对象递归合并，数组和标量整体替换。"""
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)
    return target


def remove_json_pointer(target: Dict[str, Any], pointer: str) -> None:
    if not pointer.startswith("/"):
        raise ApifoxError(f"remove_paths 必须使用 JSON Pointer: {pointer}")
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    parent: Any = target
    for part in parts[:-1]:
        if isinstance(parent, list):
            parent = parent[int(part)]
        elif isinstance(parent, dict) and part in parent:
            parent = parent[part]
        else:
            raise ApifoxError(f"remove_paths 不存在: {pointer}")
    leaf = parts[-1]
    if isinstance(parent, list):
        del parent[int(leaf)]
    elif isinstance(parent, dict) and leaf in parent:
        del parent[leaf]
    else:
        raise ApifoxError(f"remove_paths 不存在: {pointer}")


def subset_mismatches(expected: Any, actual: Any, path: str = "") -> List[str]:
    mismatches: List[str] = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path or '/'}: 类型不一致"]
        for key, value in expected.items():
            child_path = f"{path}/{key}"
            if key not in actual:
                mismatches.append(f"{child_path}: 缺失")
            else:
                mismatches.extend(subset_mismatches(value, actual[key], child_path))
        return mismatches
    if isinstance(expected, list):
        if expected != actual:
            mismatches.append(f"{path or '/'}: 数组不一致")
        return mismatches
    if expected != actual:
        mismatches.append(f"{path or '/'}: {actual!r} != {expected!r}")
    return mismatches


def missing_descriptions(schema: Dict[str, Any], path: str = "") -> List[str]:
    missing: List[str] = []
    properties = schema.get("properties") or {}
    for name, definition in properties.items():
        child_path = f"{path}.{name}" if path else name
        if not isinstance(definition, dict):
            missing.append(child_path)
            continue
        if not definition.get("description"):
            missing.append(child_path)
        missing.extend(missing_descriptions(definition, child_path))
        items = definition.get("items")
        if isinstance(items, dict):
            missing.extend(missing_descriptions(items, f"{child_path}[]"))
    return missing


def strip_examples(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: strip_examples(child) for key, child in value.items() if key not in {"example", "examples"}}
    if isinstance(value, list):
        return [strip_examples(child) for child in value]
    return value


def build_minimal_spec(
    document: Dict[str, Any],
    endpoint_keys: Iterable[Tuple[str, str]],
    schema_names: Iterable[str],
    include_tags: bool = False,
) -> Dict[str, Any]:
    paths: Dict[str, Any] = {}
    seed_refs: List[str] = list(schema_names)
    for path, method in endpoint_keys:
        operation = document.get("paths", {}).get(path, {}).get(method.lower())
        if operation is None:
            continue
        paths.setdefault(path, {})[method.lower()] = copy.deepcopy(operation)
        seed_refs.extend(iter_refs(operation))

    components = dependency_closure(document, seed_refs)
    spec: Dict[str, Any] = {
        "openapi": "3.1.0",
        "info": copy.deepcopy(document.get("info") or {"title": "Apifox MCP", "version": "2.1.0"}),
        "paths": paths,
    }
    if components:
        spec["components"] = {"schemas": components}
    if include_tags and document.get("tags"):
        spec["tags"] = copy.deepcopy(document["tags"])
    return spec


def select_operation_sections(operation: Dict[str, Any], sections: Optional[List[str]]) -> Dict[str, Any]:
    if not sections:
        return copy.deepcopy(operation)
    selected: Dict[str, Any] = {}
    mapping = {
        "metadata": ["summary", "description", "tags", "operationId", "x-apifox-status"],
        "parameters": ["parameters"],
        "request": ["requestBody"],
        "responses": ["responses"],
    }
    for section in sections:
        for key in mapping.get(section, []):
            if key in operation:
                selected[key] = copy.deepcopy(operation[key])
    return selected


def json_pointer_get(value: Any, pointer: str) -> Any:
    if pointer in {"", "/"}:
        return value
    current = value
    for part in pointer.lstrip("/").split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        current = current[int(key)] if isinstance(current, list) else current[key]
    return current
