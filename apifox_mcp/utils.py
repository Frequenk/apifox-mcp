"""项目配置解析工具。"""

import json
from typing import Dict, List, Optional

from .config import APIFOX_PROJECTS


def _get_projects() -> List[Dict[str, str]]:
    if not APIFOX_PROJECTS:
        return []
    try:
        parsed = json.loads(APIFOX_PROJECTS)
    except json.JSONDecodeError as exc:
        raise ValueError(f"APIFOX_PROJECTS 不是合法 JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise ValueError("APIFOX_PROJECTS 必须是 JSON 数组")

    projects = []
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise ValueError(f"APIFOX_PROJECTS[{index}] 必须是对象")
        project_id = str(item.get("id", "")).strip()
        name = str(item.get("name", "")).strip()
        if not project_id or not name:
            raise ValueError(f"APIFOX_PROJECTS[{index}] 必须包含 name 和 id")
        projects.append({"name": name, "id": project_id})
    return projects


def _resolve_project_id(project_id: Optional[str]) -> str:
    projects = _get_projects()
    if not project_id or not str(project_id).strip():
        if len(projects) == 1:
            return projects[0]["id"]
        raise ValueError("必须提供 project_id，可使用项目名称或 ID")

    normalized = str(project_id).strip()
    for project in projects:
        if normalized in {project["id"], project["name"]}:
            return project["id"]
    choices = ", ".join(f"{item['name']}({item['id']})" for item in projects) or "无"
    raise ValueError(f"未配置的 project_id: {normalized}；可用项目: {choices}")
