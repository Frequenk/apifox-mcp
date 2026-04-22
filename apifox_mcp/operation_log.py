"""
操作日志
========

为写操作记录 before/after 快照，支持后续审计和撤销。
"""

from __future__ import annotations

import copy
import json
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class OperationLog:
    """本地 JSON 文件操作日志。"""

    def __init__(self, log_dir: str | Path | None = None) -> None:
        self.log_dir = Path(log_dir or os.environ.get("APIFOX_MCP_LOG_DIR", ".apifox-mcp-logs"))

    def record(
        self,
        operation: str,
        resource_type: str,
        project_id: str,
        target: Dict[str, Any],
        before: Optional[Dict[str, Any]],
        after: Optional[Dict[str, Any]],
        status: str = "completed",
        error: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """记录一次操作并返回日志内容。"""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now().astimezone()
        log_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
        entry = {
            "id": log_id,
            "timestamp": now.isoformat(timespec="seconds"),
            "operation": operation,
            "resource_type": resource_type,
            "project_id": str(project_id),
            "target": copy.deepcopy(target),
            "before": copy.deepcopy(before),
            "after": copy.deepcopy(after),
            "status": status,
            "error": error,
            "context": copy.deepcopy(context or {}),
        }
        path = self._path(log_id)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(entry, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(path)
        return entry

    def get(self, log_id: str) -> Dict[str, Any]:
        """读取指定日志。"""
        path = self._path(log_id)
        if not path.exists():
            raise FileNotFoundError(f"未找到操作日志: {log_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_logs(self, project_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """按时间倒序列出日志。"""
        if not self.log_dir.exists():
            return []

        logs = []
        for path in self.log_dir.glob("*.json"):
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if project_id is not None and str(entry.get("project_id")) != str(project_id):
                continue
            logs.append(entry)

        logs.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
        return logs[:limit]

    def _path(self, log_id: str) -> Path:
        return self.log_dir / f"{log_id}.json"


def _snapshot_endpoint(openapi_data: Dict[str, Any], path: str, method: str) -> Dict[str, Any]:
    """从 OpenAPI 中提取接口 operation 快照。"""
    method_lower = method.lower()
    paths = openapi_data.get("paths", {})
    if path not in paths:
        raise KeyError(f"未找到路径为 {path} 的接口")
    if method_lower not in paths[path]:
        raise KeyError(f"未找到 {method.upper()} {path} 接口")
    return copy.deepcopy(paths[path][method_lower])


def _snapshot_schema(openapi_data: Dict[str, Any], name: str) -> Dict[str, Any]:
    """从 OpenAPI 中提取 Schema 快照。"""
    schemas = openapi_data.get("components", {}).get("schemas", {})
    if name not in schemas:
        raise KeyError(f"未找到名为 {name} 的数据模型")
    return copy.deepcopy(schemas[name])


def _snapshot_folder(openapi_data: Dict[str, Any], folder_name: str) -> Dict[str, Any]:
    """从 OpenAPI tags 中提取目录快照。"""
    for tag in openapi_data.get("tags", []):
        if isinstance(tag, dict) and tag.get("name") == folder_name:
            return copy.deepcopy(tag)
        if tag == folder_name:
            return {"name": folder_name}
    raise KeyError(f"未找到目录: {folder_name}")


operation_logger = OperationLog()
