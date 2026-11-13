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
            "code": "唯一角色编码；super_admin 放行全部功能，其他角色按页面授权校验。",
            "name": "角色的中文显示名称。",
            "is_system": "角色类型：true 系统角色、false 自定义角色；管理员可创建或切换类型。",
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
            "code": "唯一知识库编码，用于管理与检索；机器人通过绑定 ID 选择知识库。",
            "name": "知识库显示名称。",
            "status": "知识库状态：active 可查询、disabled 暂停服务、archived 已归档。",
        },
    ),
    "robots": (
        "机器人登记：保存设备身份、启用状态及当前绑定知识库；换绑时递增绑定版本。",
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
            "status": "文档状态：active 有效、archived 已归档；归档后保留历史版本。",
        },
    ),
    "document_versions": (
        "文档版本：每次上传创建独立版本和 MinIO 对象，保留历史内容与处理状态。",
        {
            "document_id": "所属逻辑文档 ID，关联 documents.id。",
            "version_no": "文档内递增版本号，与 document_id 联合唯一。",
            "minio_bucket": "存放原始知识库文件的私有 MinIO 存储桶名称。",
            "minio_object_key": "唯一 MinIO 对象键；按知识库、文档和版本组织，不保存服务器本地文件路径。",
            "filename": "用户上传的原始文件名；支持 Markdown、TXT、PDF、Word、图片和视频。",
            "content_type": "文件媒体类型，用于预览和下载响应。",
            "file_size": "原始文件大小，单位为字节。",
            "content_hash": "原始文件内容的 SHA-256 校验摘要。",
            "status": "处理状态：PENDING_UPLOAD 待上传、UPLOADED 已上传、PROCESSING 处理中、EMBEDDING 向量化中、INDEXED 文本/图片/视频可检索或其他文件已就绪、FAILED 失败、ARCHIVED 已归档。",
            "chunk_count": "此版本实际生成的文档切片数量。",
            "embedding_model": "生成此版本向量使用的 Embedding 模型名称及版本。",
        },
    ),
    "document_chunks": (
        "文档切片与向量：保存可检索文本及其来源；向量维度需由首次真实 DashScope 返回确认后约束。",
        {
            "document_version_id": "所属文档版本 ID，关联 document_versions.id。",
            "chunk_index": "版本内切片序号，与 document_version_id 联合唯一。",
            "content": "文本切片或媒体文件标识，供检索和回答引用使用。",
            "heading_path": "切片所属 Markdown 标题层级路径。",
            "token_count": "切片估算或实际 token 数量。",
            "embedding": "pgvector 向量；初始化不指定维度，接入模型后必须校验固定维度再建立向量索引。",
            "metadata": "切片附加信息，JSON 对象，可记录行号、代码块、表格位置和 image/video 模态。",
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
            "status": "问答状态：PROCESSING 处理中、SUCCESS 成功、PARTIAL 部分有依据、NO_EVIDENCE 依据不足、SOURCES_ONLY 仅返回资料、FAILED 服务失败。",
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


SCHEMA["document_versions"][1].update({"index_profile": "实际索引配置快照；旧索引为空。", "index_config_hash": "索引配置的 SHA256 摘要。"})
SCHEMA["qa_logs"][1]["execution_trace"] = "RAG 运行版本、阶段耗时、召回分数及 token 用量。"

SCHEMA["robots"][1].update({
    "knowledge_base_id": "当前绑定知识库；存量未配置机器人为空且不可问答。",
    "binding_version": "每次换绑递增，旧会话不能跨绑定版本继续。",
    "default_location_name": "天气城市编号对应的可读地区名称。",
    "default_location": "管理员明确配置的默认查询地点，可为空。",
    "timezone": "管理员配置的 IANA 时区，可为空。",
})
SCHEMA["qa_logs"][1].update({
    "conversation_id": "所属会话；历史兼容记录可为空。",
    "turn_no": "会话内单调递增轮次。",
    "resolved_question": "结合当前会话理解后的独立检索问题。",
    "answer_kind": "knowledge 知识回答、clarification 澄清、chat 闲聊、general 通识、realtime 实时信息能力说明。",
    "context_snapshot": "本轮使用的摘要和历史原文快照。",
    "lease_token": "执行租约唯一标识，防止过期任务写回。",
    "lease_expires_at": "租约到期时间。",
    "attempts": "本轮后台执行次数。",
    "suggestion_anchor": "服务端校验后的推荐问题引用切片。",
    "status": "PENDING 排队、PROCESSING 执行、SUCCESS 成功、PARTIAL 部分、NO_EVIDENCE 无依据、SOURCES_ONLY 仅资料、FAILED 失败、CANCELLED 取消。",
})
SCHEMA["qa_conversations"] = ("独立会话：用户或机器人归属，单会话记忆和软删除。", {
    "source_type": "WEB 用户或 ROBOT 设备，归属二选一。",
    "robot_id": "机器人所有者。",
    "knowledge_base_id": "创建时固定的知识库。",
    "robot_binding_version": "创建时机器人绑定版本。",
    "title": "首问截取的会话标题。",
    "creation_request_id": "创建会话的幂等请求编号。",
    "next_turn_no": "下一轮编号。",
    "last_message_at": "最近提交问题时间。",
    "deleted_at": "用户软删除时间；管理员仍可审计。",
    "closed_at": "会话关闭时间，关闭后只读。",
    "closed_reason": "关闭原因，例如 knowledge_base_changed。",
    "memory_summary": "仅此会话的早期消息摘要。",
    "summary_through_turn_no": "摘要覆盖截止轮次。",
    "memory_version": "摘要写入版本。",
})


SCHEMA['qa_logs'][1]['prompt_snapshot'] = '本轮使用的不可变提示词版本与正文快照，重试复用。'
SCHEMA['prompt_templates'] = ('提示词用途与当前发布版本。', {
    'archived': '历史用途归档标记；保留原版本。', 'key': '稳定用途键。', 'name': '展示名称。', 'active_version': '当前已发布版本号。', 'generation': '发布代数，用于并发检查。'})
SCHEMA['prompt_versions'] = ('不可变提示词版本；保存草稿产生新版本。', {
    'prompt_key': '所属提示词用途。', 'version': '用途内递增版本号。', 'content': '系统提示词正文。', 'note': '修改说明。'})
SCHEMA['evaluation_datasets'] = ('每个知识库唯一的评测集。', {'name': '评测集名称。', 'knowledge_base_id': '评测知识库，每个知识库最多一个评测集。'})
SCHEMA['evaluation_examples'] = ('评测题目及参考标注；保存时选择草稿或启用，修改递增修订号。', {
    'dataset_id': '所属评测集。', 'name': '集内唯一名称。', 'inputs': '问题、历史语境与机器人标志。', 'reference': '预期文档 ID 与标题快照、答案要点与状态。',
    'revision': '内容修订号。', 'reviewed_by': '题目启用确认人；为空时为草稿。', 'reviewed_at': '题目启用确认时间。'})
SCHEMA['evaluation_runs'] = ('固定输入及提示词快照的成对评测任务。', {
    'dataset_id': '来源评测集。', 'name': '实验名称。', 'status': 'PENDING、RUNNING、COMPLETED 或 FAILED。',
    'snapshot': '测试题、提示词、索引和运行配置快照。', 'results': '逐题基线与候选答案、指标和人工评分。',
    'lease_token': '任务执行令牌。', 'lease_expires_at': '租约到期时间。', 'attempts': '执行尝试次数。'})


def describe_schema(metadata):
    for name, table in metadata.tables.items():
        description, fields = SCHEMA[name]
        table.comment = description
        for column in table.columns:
            column.comment = fields.get(column.name) or COMMON[column.name]
