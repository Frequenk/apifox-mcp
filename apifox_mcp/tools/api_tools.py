"""
API 接口管理工具
================

提供 HTTP 接口的 CRUD 操作。

⚠️ 强制规范：
1. 所有接口必须有中文描述
2. 所有 Schema 字段必须有 description 说明
3. 必须提供成功响应 (2xx) 和错误响应 (4xx/5xx)
4. 【重要】所有 Schema 必须定义为公共组件（components/schemas），
   禁止内联定义！本模块会自动将传入的 schema 提取为公共组件并使用 $ref 引用。
"""

import json
from typing import Optional, List, Dict

from ..config import (
    mcp, logger, HTTP_METHODS,
    HTTP_STATUS_CODES, API_STATUS
)
from ..utils import _validate_config, _make_request, _build_openapi_spec, _resolve_project_id


# ============================================================
# 标准错误响应模板 - 完整的 4xx/5xx 响应
# ============================================================

STANDARD_ERROR_SCHEMA = {
    "type": "object",
    "properties": {
        "code": {"type": "integer", "description": "错误码"},
        "message": {"type": "string", "description": "错误信息"},
        "details": {"type": "object", "description": "详细信息"}
    },
    "required": ["code", "message"]
}

STANDARD_ERROR_RESPONSES = {
    # 4xx 客户端错误
    400: {
        "code": 400,
        "name": "请求参数错误",
        "schema": STANDARD_ERROR_SCHEMA,
        "example": {"code": 400, "message": "请求参数错误", "details": {"field": "name", "reason": "不能为空"}}
    },
    401: {
        "code": 401,
        "name": "未授权",
        "schema": STANDARD_ERROR_SCHEMA,
        "example": {"code": 401, "message": "未授权，请先登录"}
    },
    403: {
        "code": 403,
        "name": "禁止访问",
        "schema": STANDARD_ERROR_SCHEMA,
        "example": {"code": 403, "message": "无权限访问此资源"}
    },
    404: {
        "code": 404,
        "name": "资源不存在",
        "schema": STANDARD_ERROR_SCHEMA,
        "example": {"code": 404, "message": "请求的资源不存在"}
    },
    409: {
        "code": 409,
        "name": "资源冲突",
        "schema": STANDARD_ERROR_SCHEMA,
        "example": {"code": 409, "message": "资源已存在或状态冲突"}
    },
    422: {
        "code": 422,
        "name": "实体无法处理",
        "schema": STANDARD_ERROR_SCHEMA,
        "example": {"code": 422, "message": "请求格式正确但语义错误", "details": {"field": "email", "reason": "格式不正确"}}
    },
    # 5xx 服务端错误
    500: {
        "code": 500,
        "name": "服务器内部错误",
        "schema": STANDARD_ERROR_SCHEMA,
        "example": {"code": 500, "message": "服务器内部错误，请稍后重试"}
    },
    502: {
        "code": 502,
        "name": "网关错误",
        "schema": STANDARD_ERROR_SCHEMA,
        "example": {"code": 502, "message": "网关错误，上游服务不可用"}
    },
    503: {
        "code": 503,
        "name": "服务不可用",
        "schema": STANDARD_ERROR_SCHEMA,
        "example": {"code": 503, "message": "服务暂时不可用，请稍后重试"}
    }
}

# 所有 API 必需的错误响应码
REQUIRED_4XX_CODES = [400, 401, 403, 404]  # 所有 API 都需要
REQUIRED_5XX_CODES = [500, 502, 503]  # 所有 API 都需要
OPTIONAL_4XX_CODES = [409, 422]  # POST/PUT/PATCH 可能需要


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


def _auto_fill_error_responses(responses: Optional[List[Dict]], method: str) -> List[Dict]:
    """自动补充所有标准错误响应 (4xx + 5xx)"""
    if responses is None:
        responses = []
    
    existing_codes = {r.get("code") for r in responses}
    
    # 所有 API 必需的错误响应
    required_codes = REQUIRED_4XX_CODES + REQUIRED_5XX_CODES
    
    # POST/PUT/PATCH 额外需要 409, 422
    if method in ["POST", "PUT", "PATCH"]:
        required_codes = required_codes + OPTIONAL_4XX_CODES
    
    # 添加缺失的错误响应
    for code in required_codes:
        if code not in existing_codes and code in STANDARD_ERROR_RESPONSES:
            responses.append(STANDARD_ERROR_RESPONSES[code].copy())
    
    return responses


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
    
    ⚠️ 系统会自动添加标准错误响应（400/404/500），无需手动定义。
    
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
        
        responses: (可选) 自定义响应列表，用于覆盖默认错误响应
                   系统会自动添加 400/401/403/404/409/422/500/502/503 错误响应
    
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
    
    # 自动补充错误响应
    final_responses = _auto_fill_error_responses(responses, method_upper)
    
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
            # Schema 使用覆盖策略，避免重复创建相同的 Schema（如 ErrorResponse）,
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
        return f"❌ 创建失败: {result.get('error', '未知错误')}"
    
    counters = result.get("data", {}).get("data", {}).get("counters", {})
    created = counters.get("endpointCreated", 0)
    updated = counters.get("endpointUpdated", 0)
    
    if created == 0 and updated == 0:
        return f"⚠️ 接口可能已存在或创建失败，请检查 Apifox 项目"
    
    response_codes = [r.get("code") for r in final_responses]
    action = "创建" if created > 0 else "更新"
    
    return f"""✅ 接口{action}成功!

📋 接口信息:
   • 名称: {title}
   • 路径: {method_upper} {path}
   • 描述: {description[:50]}{'...' if len(description) > 50 else ''}
   • 标签: {', '.join(tags) if tags else '无'}
   • 响应码: {', '.join(map(str, sorted(response_codes)))}
   
💡 系统已自动添加标准错误响应 (400/404/500)"""


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
    folder_id: int = 0
) -> str:
    """
    更新 Apifox 项目中的现有 HTTP 接口。
    
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
        其他参数同 create_api_endpoint
        
    Returns:
        更新结果信息
    """
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)
    
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
    
    # 自动补充错误响应
    final_responses = _auto_fill_error_responses(responses, final_method)
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
    result = _make_request("POST", f"/projects/{resolved_project_id}/import-openapi?locale=zh-CN", data=import_payload)
    
    if not result["success"]:
        return f"❌ 更新失败: {result.get('error', '未知错误')}"
    
    counters = result.get("data", {}).get("data", {}).get("counters", {})
    updated = counters.get("endpointUpdated", 0)
    action = "更新" if updated > 0 else "创建"
    
    return f"""✅ 接口{action}成功!

📋 接口信息:
   • 名称: {title}
   • 路径: {final_method} {final_path}
   • 描述: {description[:50]}{'...' if len(description) > 50 else ''}"""


@mcp.tool()
def delete_api_endpoint(project_id: str, path: str, method: str, confirm: bool = False) -> str:
    """删除 Apifox 项目中的 HTTP 接口。⚠️ 此操作不可撤销！"""
    config_error = _validate_config(project_id)
    if config_error:
        return config_error
    resolved_project_id = _resolve_project_id(project_id)
    
    method_upper = method.upper()
    
    if not confirm:
        return f"⚠️ 安全提示: 删除操作不可撤销!\n\n请确认要删除接口: {method_upper} {path}\n\n如确认删除，请设置 confirm=True"
    
    return f"⚠️ 公开 API 暂不支持直接删除接口\n\n请在 Apifox 客户端中手动删除: {method_upper} {path}\n项目 ID: {resolved_project_id}"


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
