"""Database comments shared by model metadata and generated SQL migrations."""

COMMON = {
    "id": "记录主键，UUID 格式，由应用生成；初始化数据由 SQL 生成。",
    "created_at": "记录创建时间，带时区，应用统一使用 UTC。",
    "updated_at": "记录最后修改时间，带时区，应用更新时维护。",
    "created_by": "创建此记录的用户 ID，关联 users.id；系统初始化时可为空。",
    "description": "供管理人员阅读的用途或业务描述，可为空。",
    "status": "业务启用状态：active 启用、disabled 停用；具体归档状态见所属表说明。",
    "user_id": "关联的网页用户 ID，关联 users.id。",
    "ip_address": "客户端 IP 地址；反向代理部署须按可信代理配置获取。",
    "error_message": "操作失败的可读原因；不得写入密钥或密码。",
}

SCHEMA = {
    "users": (
        "平台用户：保存登录账号、密码和所属角色；不对外提供密码字段。",
        {
            "username": "唯一登录用户名；初始化超级管理员用户名为 root。",
            "display_name": "在页面和个人信息中展示的用户名称。",
            "password_hash": "Argon2 密码哈希，网页登录验证只使用此字段。",
            "password_plaintext": "按项目要求保留的当前原始明文密码，供数据库管理员找回；敏感信息，不返回 Web API，重置密码时同步更新。",
            "role_id": "所属角色 ID，关联 roles.id；第一版一个用户对应一个角色。",
            "status": "用户状态：active 启用、disabled 停用、deleted 已逻辑删除；已删除用户不展示、不能登录，保留历史关联且用户名不复用。",
        },
    ),
    "roles": (
        "用户角色：包含普通用户 user 和超级管理员 super_admin，可扩展其他角色。",
        {
            "code": "唯一角色编码；后端管理接口使用 super_admin 编码校验管理员身份。",
            "name": "角色的中文显示名称。",
            "is_system": "是否为系统内置角色；true 表示内置角色。",
        },
    ),
    "pages": (
        "页面资源目录：定义前端动态路由与菜单元数据；页面权限不替代后端 API 鉴权。",
        {
            "code": "唯一页面资源编码，用于权限映射和前端路由标识。",
            "name": "页面中文名称，在导航与页面标题中展示。",
            "route_path": "唯一前端路由路径，例如 /documents。",
            "route_name": "前端路由的逻辑名称。",
            "component_key": "前端本地组件白名单中的键名，不允许当作可执行代码。",
            "parent_id": "父页面 ID，关联 pages.id；为空表示顶级资源。",
            "page_type": "资源类型：menu 菜单、page 页面、button 按钮、hidden 隐藏路由。",
            "sort_order": "菜单显示顺序，数值越小越靠前。",
            "is_visible": "是否在菜单中显示；隐藏菜单不等于撤销访问权限。",
        },
    ),
    "role_page_permissions": (
        "角色页面授权：将角色与可访问页面关联，角色和页面共同构成主键。",
        {
            "role_id": "被授权的角色 ID，关联 roles.id。",
            "page_id": "被授权的页面资源 ID，关联 pages.id。",
            "can_view": "是否允许访问此页面；仅 true 且页面启用时返回到前端。",
        },
    ),
    "user_sessions": (
        "登录会话：保存刷新令牌的 SHA-256 哈希与会话有效期，支持轮换刷新和退出撤销。",
        {
            "refresh_token_hash": "不透明刷新令牌的 SHA-256 哈希；原始令牌仅放入 HttpOnly Cookie。",
            "expires_at": "会话绝对失效时间；超过时间即使 JWT 未过期也拒绝访问。",
            "revoked_at": "会话撤销时间；为空表示未主动撤销。",
            "user_agent": "登录客户端 User-Agent 摘要，用于追踪会话来源。",
        },
    ),
    "knowledge_bases": (
        "知识库：组织文档与检索范围；状态包括 active 启用、disabled 停用、archived 归档。",
        {
            "code": "唯一知识库编码，机器人请求通过此编码选择知识库。",
            "name": "知识库显示名称。",
            "status": "知识库状态：active 可查询、disabled 暂停服务、archived 已归档。",
        },
    ),
    "robots": (
        "机器人登记：保存设备身份和启用状态；第一版不绑定知识库，查询时提供知识库编码。",
        {
            "serial_no": "机器人唯一序列号，机器人接口用于校验注册身份。",
            "name": "机器人显示名称。",
            "last_request_at": "最近一次请求知识服务的时间，可为空。",
        },
    ),
    "documents": (
        "逻辑文档：归属于一个知识库，关联多个版本；仅当前成功索引的版本参与检索。",
        {
            "knowledge_base_id": "所属知识库 ID，关联 knowledge_bases.id。",
            "title": "文档显示标题。",
            "current_version_id": "当前可检索版本 ID，关联 document_versions.id；索引成功后才能切换。",
            "status": "文档状态：active 有效、archived 已归档。",
        },
    ),
    "document_versions": (
        "文档版本：每次上传创建独立版本和 MinIO 对象，保留历史内容与处理状态。",
        {
            "document_id": "所属逻辑文档 ID，关联 documents.id。",
            "version_no": "文档内递增版本号，与 document_id 联合唯一。",
            "minio_bucket": "存放原始 Markdown 文件的私有 MinIO 存储桶名称。",
            "minio_object_key": "唯一 MinIO 对象键；不保存服务器本地文件路径。",
            "filename": "用户上传的原始文件名。",
            "content_type": "文件媒体类型，通常为 text/markdown。",
            "file_size": "原始文件大小，单位为字节。",
            "content_hash": "原始文件内容的 SHA-256 校验摘要。",
            "status": "处理状态：UPLOADED 已上传、PARSING 解析中、CHUNKING 切片中、EMBEDDING 向量化中、INDEXED 可检索、FAILED 失败。",
            "chunk_count": "此版本实际生成的文档切片数量。",
            "embedding_model": "生成此版本向量使用的 Embedding 模型名称及版本。",
        },
    ),
    "document_chunks": (
        "文档切片与向量：保存可检索文本及其来源；向量维度需由首次真实 DashScope 返回确认后约束。",
        {
            "document_version_id": "所属文档版本 ID，关联 document_versions.id。",
            "chunk_index": "版本内切片序号，与 document_version_id 联合唯一。",
            "content": "切片纯文本，供检索和回答引用使用。",
            "heading_path": "切片所属 Markdown 标题层级路径。",
            "token_count": "切片估算或实际 token 数量。",
            "embedding": "pgvector 向量；初始化不指定维度，接入模型后必须校验固定维度再建立向量索引。",
            "metadata": "切片附加信息，JSON 对象，可记录行号、代码块和表格位置。",
        },
    ),
    "index_tasks": (
        "异步文档处理任务：记录索引、重建或删除任务的状态、重试次数和错误。",
        {
            "document_version_id": "目标文档版本 ID，关联 document_versions.id。",
            "task_type": "任务类型：INDEX 首次索引、REINDEX 重新索引、DELETE 删除清理。",
            "status": "执行状态：PENDING 待处理、RUNNING 执行中、SUCCESS 成功、FAILED 失败。",
            "attempts": "已执行尝试次数，初始为 0。",
            "started_at": "任务最近一次开始执行时间。",
            "finished_at": "任务最近一次执行结束时间。",
        },
    ),
    "qa_logs": (
        "问答日志：记录网页和机器人请求、答案、引用与耗时；request_id 用于请求幂等。",
        {
            "request_id": "唯一请求编号，重复请求应复用已有结果。",
            "source_type": "请求来源：WEB 网页用户、ROBOT 机器人。",
            "robot_id": "发起请求的机器人 ID，关联 robots.id；网页请求为空。",
            "knowledge_base_id": "本次检索的知识库 ID，关联 knowledge_bases.id。",
            "question": "用户或机器人提交的原始问题文本。",
            "answer": "最终生成的回答文本；失败时可以为空。",
            "sources": "回答引用来源的 JSON 数据，包含文档、版本、标题路径和片段。",
            "retrieval_count": "本次向量检索实际召回的切片数量。",
            "model_name": "本次答案生成使用的大语言模型名称。",
            "status": "问答结果：SUCCESS 成功、FAILED 失败。",
            "latency_ms": "完整问答请求处理耗时，单位为毫秒。",
        },
    ),
    "audit_logs": (
        "审计日志：记录登录、退出和管理操作，便于追踪操作者、目标资源与变更来源。",
        {
            "action": "操作名称，例如 auth.login、auth.logout、user.create。",
            "resource_type": "操作目标资源类型，例如 user、document、knowledge_base。",
            "resource_id": "操作目标资源的 UUID；不使用外键以保留历史审计信息。",
            "detail": "操作详情 JSON；不应包含密码、令牌、API 密钥等敏感值。",
        },
    ),
}


def describe_schema(metadata):
    for name, table in metadata.tables.items():
        description, fields = SCHEMA[name]
        table.comment = description
        for column in table.columns:
            column.comment = fields.get(column.name) or COMMON[column.name]
