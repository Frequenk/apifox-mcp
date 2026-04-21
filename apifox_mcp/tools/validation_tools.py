"""
API 一致性校验工具
==================

提供 API 路径命名和响应格式的一致性检查。
"""

import re
from typing import Optional, List, Dict

from ..config import mcp, logger
from ..utils import _validate_config, _make_request, _resolve_project_id


# ============================================================
# 命名风格检查器
# ============================================================


def _check_kebab_case(segment: str) -> bool:
    """检查是否符合 kebab-case（小写字母+连字符）"""
    if segment.startswith("{") and segment.endswith("}"):
        return True  # 路径参数不检查
    return bool(re.match(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$", segment))


def _check_snake_case(segment: str) -> bool:
    """检查是否符合 snake_case（小写字母+下划线）"""
    if segment.startswith("{") and segment.endswith("}"):
        return True
    return bool(re.match(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$", segment))


def _check_camel_case(segment: str) -> bool:
    """检查是否符合 camelCase"""
    if segment.startswith("{") and segment.endswith("}"):
        return True
    return bool(re.match(r"^[a-z][a-zA-Z0-9]*$", segment))


def _get_style_checker(style: str):
    """获取对应风格的检查函数"""
    checkers = {
        "kebab-case": _check_kebab_case,
        "snake_case": _check_snake_case,
        "camelCase": _check_camel_case
    }
    return checkers.get(style, _check_kebab_case)


def _check_path_param_naming(segment: str) -> List[str]:
    """检查路径参数命名问题"""
    issues = []
    if segment.startswith("{") and segment.endswith("}"):
        param_name = segment[1:-1]
        # 检查是否使用了大写
        if param_name != param_name.lower():
            issues.append(f"路径参数 {segment} 应使用小写: {{{param_name.lower()}}}")
        # 检查是否使用了特殊字符
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", param_name):
            issues.append(f"路径参数 {segment} 包含无效字符")
    return issues


@mcp.tool()
def check_path_naming_convention(project_id: str, style: str = "kebab-case") -> str:
    """
    检查所有 API 路径是否符合命名规范。
    
    Args:
        project_id: 目标 Apifox 项目 ID，必须来自 check_apifox_config 输出的项目列表
        style: 命名风格，可选值:
               - "kebab-case" (推荐): /user-profiles, /order-items
               - "snake_case": /user_profiles, /order_items
               - "camelCase": /userProfiles, /orderItems
        
    Returns:
        路径命名规范检查报告
        
    检查项：
    - 路径段是否符合指定命名风格
    - 路径是否全部小写（kebab-case 和 snake_case）
    - 路径参数是否使用小写 {id} 而非 {ID}
    - 是否有混合使用不同风格的情况
    """
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)
    
    if style not in ["kebab-case", "snake_case", "camelCase"]:
        return f"❌ 不支持的命名风格: {style}，可选: kebab-case, snake_case, camelCase"
    
    logger.info(f"正在检查 API 路径命名规范 (风格: {style})...")
    
    export_payload = {
        "scope": {"type": "ALL"},
        "options": {"includeApifoxExtensionProperties": True},
        "oasVersion": "3.1",
        "exportFormat": "JSON"
    }
    
    result = _make_request("POST", f"/projects/{resolved_project_id}/export-openapi?locale=zh-CN", data=export_payload)
    
    if not result["success"]:
        return f"❌ 获取失败: {result.get('error', '未知错误')}"
    
    paths = result.get("data", {}).get("paths", {})
    
    if not paths:
        return "📭 当前项目中没有接口"
    
    checker = _get_style_checker(style)
    issues = []
    valid_count = 0
    total_count = 0
    
    for path in paths.keys():
        total_count += 1
        path_issues = []
        
        # 分割路径段
        segments = [s for s in path.split("/") if s]
        
        for segment in segments:
            # 检查路径参数
            param_issues = _check_path_param_naming(segment)
            path_issues.extend(param_issues)
            
            # 检查命名风格
            if not segment.startswith("{") and not checker(segment):
                path_issues.append(f"段 '{segment}' 不符合 {style} 风格")
        
        if path_issues:
            issues.append({"path": path, "issues": path_issues})
        else:
            valid_count += 1
    
    # 生成报告
    output = [
        f"📋 路径命名规范检查报告",
        "=" * 60,
        f"📍 检查风格: {style}",
        f"📊 总路径数: {total_count}",
        f"✅ 符合规范: {valid_count} 个",
        f"❌ 不符合规范: {len(issues)} 个",
        ""
    ]
    
    if issues:
        output.append("=" * 60)
        output.append("❌ 不符合规范的路径:")
        output.append("")
        
        for item in issues[:20]:  # 最多显示20个
            output.append(f"📍 {item['path']}")
            for issue in item["issues"]:
                output.append(f"   ⚠️ {issue}")
            output.append("")
        
        if len(issues) > 20:
            output.append(f"... 还有 {len(issues) - 20} 个路径有问题")
        
        output.append("")
        output.append("💡 建议统一使用 kebab-case 风格 (如 /user-profiles)")
    else:
        output.append("🎉 所有路径都符合命名规范!")
    
    return "\n".join(output)


@mcp.tool()
def check_response_consistency(project_id: str) -> str:
    """
    检查所有 API 的响应格式是否统一。
    
    Returns:
        响应格式一致性检查报告
        
    检查项：
    - 成功响应结构是否一致
    - 分页响应是否使用统一字段名
    - 错误响应结构是否一致
    """
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)
    
    logger.info("正在检查 API 响应格式一致性...")
    
    export_payload = {
        "scope": {"type": "ALL"},
        "options": {"includeApifoxExtensionProperties": True},
        "oasVersion": "3.1",
        "exportFormat": "JSON"
    }
    
    result = _make_request("POST", f"/projects/{resolved_project_id}/export-openapi?locale=zh-CN", data=export_payload)
    
    if not result["success"]:
        return f"❌ 获取失败: {result.get('error', '未知错误')}"
    
    paths = result.get("data", {}).get("paths", {})
    
    if not paths:
        return "📭 当前项目中没有接口"
    
    # 收集响应结构统计
    response_patterns = {}  # 记录不同的响应结构
    pagination_fields = {}  # 分页字段统计
    error_patterns = {}  # 错误响应结构
    total_apis = 0
    
    for path, methods in paths.items():
        for method, details in methods.items():
            if method not in ["get", "post", "put", "delete", "patch"]:
                continue
            
            total_apis += 1
            responses = details.get("responses", {})
            
            for code_str, resp in responses.items():
                code = int(code_str) if code_str.isdigit() else 0
                content = resp.get("content", {})
                
                for media_type, media_def in content.items():
                    schema = media_def.get("schema", {})
                    props = schema.get("properties", {})
                    prop_names = tuple(sorted(props.keys()))
                    
                    if 200 <= code < 300:
                        # 成功响应
                        pattern = prop_names if prop_names else ("empty",)
                        response_patterns[pattern] = response_patterns.get(pattern, 0) + 1
                        
                        # 检查分页字段
                        for field in ["page", "pageNum", "pageNumber", "current"]:
                            if field in props:
                                pagination_fields[field] = pagination_fields.get(field, 0) + 1
                        for field in ["pageSize", "page_size", "size", "limit"]:
                            if field in props:
                                pagination_fields[field] = pagination_fields.get(field, 0) + 1
                        for field in ["total", "totalCount", "total_count"]:
                            if field in props:
                                pagination_fields[field] = pagination_fields.get(field, 0) + 1
                    
                    elif 400 <= code < 600:
                        # 错误响应
                        pattern = prop_names if prop_names else ("empty",)
                        error_patterns[pattern] = error_patterns.get(pattern, 0) + 1
    
    # 生成报告
    output = [
        "📋 响应格式一致性检查报告",
        "=" * 60,
        f"📊 总接口数: {total_apis}",
        ""
    ]
    
    # 成功响应结构分析
    output.append("━━━ 成功响应结构分析 ━━━")
    if len(response_patterns) <= 3:
        output.append(f"✅ 响应结构较为统一 ({len(response_patterns)} 种)")
    else:
        output.append(f"⚠️ 响应结构不统一 ({len(response_patterns)} 种)")
    
    for pattern, count in sorted(response_patterns.items(), key=lambda x: -x[1])[:5]:
        fields = ", ".join(pattern) if pattern != ("empty",) else "无字段"
        output.append(f"   • [{fields}]: {count} 个接口")
    
    # 分页字段分析
    if pagination_fields:
        output.append("")
        output.append("━━━ 分页字段分析 ━━━")
        
        page_variants = [f for f in pagination_fields if f in ["page", "pageNum", "pageNumber", "current"]]
        size_variants = [f for f in pagination_fields if f in ["pageSize", "page_size", "size", "limit"]]
        total_variants = [f for f in pagination_fields if f in ["total", "totalCount", "total_count"]]
        
        if len(page_variants) > 1:
            output.append(f"⚠️ 页码字段不统一: {', '.join(page_variants)}")
        if len(size_variants) > 1:
            output.append(f"⚠️ 每页数量字段不统一: {', '.join(size_variants)}")
        if len(total_variants) > 1:
            output.append(f"⚠️ 总数字段不统一: {', '.join(total_variants)}")
        
        if len(page_variants) <= 1 and len(size_variants) <= 1 and len(total_variants) <= 1:
            output.append("✅ 分页字段命名统一")
        
        for field, count in sorted(pagination_fields.items(), key=lambda x: -x[1]):
            output.append(f"   • {field}: {count} 次")
    
    # 错误响应结构分析
    output.append("")
    output.append("━━━ 错误响应结构分析 ━━━")
    if len(error_patterns) <= 2:
        output.append(f"✅ 错误响应结构统一 ({len(error_patterns)} 种)")
    else:
        output.append(f"⚠️ 错误响应结构不统一 ({len(error_patterns)} 种)")
    
    for pattern, count in sorted(error_patterns.items(), key=lambda x: -x[1])[:3]:
        fields = ", ".join(pattern) if pattern != ("empty",) else "无字段"
        output.append(f"   • [{fields}]: {count} 个响应")
    
    # 建议
    output.append("")
    output.append("━━━ 建议 ━━━")
    output.append("💡 建议团队按业务约定统一成功响应、分页字段和错误响应结构")
    output.append("   分页: {items, total, page, page_size}")
    
    return "\n".join(output)
