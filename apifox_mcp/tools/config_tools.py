"""
配置检查工具
============

提供 Apifox 配置状态检查功能。
"""

from ..config import (
    mcp, logger, APIFOX_TOKEN, APIFOX_PROJECTS,
    APIFOX_PUBLIC_API, APIFOX_API_VERSION
)
from ..utils import _make_request, _get_projects


@mcp.tool()
def check_apifox_config() -> str:
    """
    检查 Apifox 配置状态。
    
    验证环境变量是否正确配置，并测试与 Apifox API 的连接。
    建议在使用其他工具之前先调用此工具确认配置正确。
    
    Returns:
        配置检查结果
    """
    result_lines = ["🔧 Apifox 配置检查", "=" * 40]
    
    # 检查 Token
    if APIFOX_TOKEN:
        masked_token = APIFOX_TOKEN[:8] + "..." + APIFOX_TOKEN[-4:] if len(APIFOX_TOKEN) > 12 else "***"
        result_lines.append(f"✅ APIFOX_TOKEN: {masked_token}")
    else:
        result_lines.append("❌ APIFOX_TOKEN: 未设置")
    
    # 检查项目列表
    projects = []
    if APIFOX_PROJECTS:
        try:
            projects = _get_projects()
            result_lines.append(f"✅ APIFOX_PROJECTS: 已配置 {len(projects)} 个项目")
            for project in projects:
                result_lines.append(f"   • {project['name']}: {project['id']}")
        except ValueError as exc:
            result_lines.append(f"❌ APIFOX_PROJECTS: {exc}")
    else:
        result_lines.append("❌ APIFOX_PROJECTS: 未设置")
    
    # 显示 API 版本
    result_lines.append(f"📌 API 版本: {APIFOX_API_VERSION}")
    result_lines.append(f"📌 使用公开 API: {APIFOX_PUBLIC_API}")
    
    # 如果配置完整，尝试测试连接
    if APIFOX_TOKEN and projects:
        result_lines.append("")
        result_lines.append("🔗 测试 API 连接...")
        
        export_payload = {
            "scope": {"type": "ALL"},
            "options": {"includeApifoxExtensionProperties": False},
            "oasVersion": "3.1",
            "exportFormat": "JSON"
        }
        
        for project in projects:
            result = _make_request(
                "POST",
                f"/projects/{project['id']}/export-openapi?locale=zh-CN",
                data=export_payload
            )

            if result["success"]:
                openapi_data = result.get("data", {})
                info = openapi_data.get("info", {})
                project_name = info.get("title", project["name"])
                paths = openapi_data.get("paths", {})
                schemas = openapi_data.get("components", {}).get("schemas", {})

                result_lines.append(f"✅ {project['name']} ({project['id']}): 连接成功")
                result_lines.append(f"   项目名称: {project_name}")
                result_lines.append(f"   接口数量: {len(paths)} 个")
                result_lines.append(f"   数据模型: {len(schemas)} 个")
            else:
                result_lines.append(f"❌ {project['name']} ({project['id']}): 连接失败: {result.get('error', '未知错误')}")
                status_code = result.get("status_code")
                if status_code == 403:
                    result_lines.append("   权限不足，请确认令牌账号在该项目中有访问权限")
    else:
        result_lines.append("")
        result_lines.append("💡 请设置以下环境变量:")
        result_lines.append("   export APIFOX_TOKEN='your-token-here'")
        result_lines.append("   export APIFOX_PROJECTS='[{\"name\":\"主项目\",\"id\":\"7575229\"}]'")
    
    return "\n".join(result_lines)
