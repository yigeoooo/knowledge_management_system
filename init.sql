-- DEXFORCE 知识平台：PostgreSQL 16 + pgvector 完整初始化脚本
-- 用法：psql -h 127.0.0.1 -U root -d knowledge_db -v ON_ERROR_STOP=1 -f init.sql
-- 目标数据库必须为空；本脚本不删除或覆盖现有表。数据库账号需有建表和创建扩展权限。
-- 网页初始账号：root
-- 网页初始密码：Dexforce@Root2026!
-- SQL 中同时保存 Argon2 校验哈希和项目要求的原始密码列。
-- 导入后可以直接登录；无需运行 Python 初始化命令。
-- 脚本包含业务结构、全部表/字段备注、12 个页面、2 个角色、权限和默认知识库。
-- 向量列暂不约束维度，待真实 Embedding 返回确定后再建立维度约束和 HNSW 索引。
-- 所有结构和数据在同一事务内初始化；请将 psql 的 ON_ERROR_STOP 设为 1。

BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> f58a8310884a

CREATE TABLE pages (
    code VARCHAR(100) NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    route_path VARCHAR(255) NOT NULL, 
    route_name VARCHAR(100) NOT NULL, 
    component_key VARCHAR(255) NOT NULL, 
    parent_id UUID, 
    page_type VARCHAR(30) NOT NULL, 
    sort_order INTEGER NOT NULL, 
    is_visible BOOLEAN NOT NULL, 
    status VARCHAR(30) NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(parent_id) REFERENCES pages (id), 
    UNIQUE (code), 
    UNIQUE (route_path)
);

CREATE TABLE roles (
    code VARCHAR(50) NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    is_system BOOLEAN NOT NULL, 
    status VARCHAR(30) NOT NULL, 
    description TEXT, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (code)
);

CREATE TABLE role_page_permissions (
    role_id UUID NOT NULL, 
    page_id UUID NOT NULL, 
    can_view BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (role_id, page_id), 
    FOREIGN KEY(page_id) REFERENCES pages (id), 
    FOREIGN KEY(role_id) REFERENCES roles (id)
);

CREATE TABLE users (
    username VARCHAR(100) NOT NULL, 
    display_name VARCHAR(100) NOT NULL, 
    password_hash VARCHAR(255) NOT NULL, 
    role_id UUID NOT NULL, 
    status VARCHAR(30) NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(role_id) REFERENCES roles (id), 
    UNIQUE (username)
);

CREATE TABLE audit_logs (
    user_id UUID, 
    action VARCHAR(100) NOT NULL, 
    resource_type VARCHAR(50) NOT NULL, 
    resource_id UUID, 
    detail JSON NOT NULL, 
    ip_address VARCHAR(64), 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE knowledge_bases (
    code VARCHAR(100) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    description TEXT, 
    status VARCHAR(30) NOT NULL, 
    created_by UUID, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(created_by) REFERENCES users (id), 
    UNIQUE (code)
);

CREATE TABLE user_sessions (
    user_id UUID NOT NULL, 
    refresh_token_hash VARCHAR(64) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    revoked_at TIMESTAMP WITH TIME ZONE, 
    user_agent TEXT, 
    ip_address VARCHAR(64), 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    UNIQUE (refresh_token_hash)
);

CREATE INDEX ix_user_sessions_user_id ON user_sessions (user_id);

INSERT INTO alembic_version (version_num) VALUES ('f58a8310884a') RETURNING alembic_version.version_num;

-- Running upgrade f58a8310884a -> 904e450aa189

CREATE EXTENSION IF NOT EXISTS vector;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE robots (
    serial_no VARCHAR(100) NOT NULL, 
    name VARCHAR(200), 
    description TEXT, 
    status VARCHAR(30) NOT NULL, 
    last_request_at TIMESTAMP WITH TIME ZONE, 
    created_by UUID, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(created_by) REFERENCES users (id), 
    UNIQUE (serial_no)
);

CREATE TABLE documents (
    knowledge_base_id UUID NOT NULL, 
    title VARCHAR(255) NOT NULL, 
    current_version_id UUID, 
    status VARCHAR(30) NOT NULL, 
    created_by UUID, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(created_by) REFERENCES users (id), 
    FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id)
);

CREATE INDEX idx_documents_kb_status ON documents (knowledge_base_id, status);

CREATE TABLE qa_logs (
    request_id VARCHAR(100) NOT NULL, 
    source_type VARCHAR(20) NOT NULL, 
    user_id UUID, 
    robot_id UUID, 
    knowledge_base_id UUID NOT NULL, 
    question TEXT NOT NULL, 
    answer TEXT, 
    sources JSON, 
    retrieval_count INTEGER, 
    model_name VARCHAR(200), 
    status VARCHAR(30) NOT NULL, 
    error_message TEXT, 
    latency_ms INTEGER, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id), 
    FOREIGN KEY(robot_id) REFERENCES robots (id), 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    UNIQUE (request_id)
);

CREATE TABLE document_versions (
    document_id UUID NOT NULL, 
    version_no INTEGER NOT NULL, 
    minio_bucket VARCHAR(100) NOT NULL, 
    minio_object_key VARCHAR(500) NOT NULL, 
    filename VARCHAR(255) NOT NULL, 
    content_type VARCHAR(100), 
    file_size BIGINT NOT NULL, 
    content_hash VARCHAR(64), 
    status VARCHAR(30) NOT NULL, 
    chunk_count INTEGER NOT NULL, 
    embedding_model VARCHAR(200), 
    error_message TEXT, 
    created_by UUID, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(created_by) REFERENCES users (id), 
    FOREIGN KEY(document_id) REFERENCES documents (id), 
    UNIQUE (document_id, version_no), 
    UNIQUE (minio_object_key)
);

CREATE TABLE document_chunks (
    document_version_id UUID NOT NULL, 
    chunk_index INTEGER NOT NULL, 
    content TEXT NOT NULL, 
    heading_path TEXT, 
    token_count INTEGER, 
    embedding VECTOR NOT NULL, 
    metadata JSON NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(document_version_id) REFERENCES document_versions (id), 
    UNIQUE (document_version_id, chunk_index)
);

CREATE TABLE index_tasks (
    document_version_id UUID NOT NULL, 
    task_type VARCHAR(30) NOT NULL, 
    status VARCHAR(30) NOT NULL, 
    attempts INTEGER NOT NULL, 
    error_message TEXT, 
    started_at TIMESTAMP WITH TIME ZONE, 
    finished_at TIMESTAMP WITH TIME ZONE, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(document_version_id) REFERENCES document_versions (id)
);

ALTER TABLE documents ADD CONSTRAINT fk_documents_current_version FOREIGN KEY(current_version_id) REFERENCES document_versions (id);

UPDATE alembic_version SET version_num='904e450aa189' WHERE alembic_version.version_num = 'f58a8310884a';

-- Running upgrade 904e450aa189 -> 16bb29ab4421

COMMENT ON TABLE alembic_version IS '数据库结构迁移版本表，由 Alembic 管理，用于后续增量升级。';

COMMENT ON COLUMN alembic_version.version_num IS '当前已应用的 Alembic 迁移版本标识。';

COMMENT ON COLUMN audit_logs.user_id IS '关联的网页用户 ID，关联 users.id。';

COMMENT ON COLUMN audit_logs.action IS '操作名称，例如 auth.login、auth.logout、user.create。';

COMMENT ON COLUMN audit_logs.resource_type IS '操作目标资源类型，例如 user、document、knowledge_base。';

COMMENT ON COLUMN audit_logs.resource_id IS '操作目标资源的 UUID；不使用外键以保留历史审计信息。';

COMMENT ON COLUMN audit_logs.detail IS '操作详情 JSON；不应包含密码、令牌、API 密钥等敏感值。';

COMMENT ON COLUMN audit_logs.ip_address IS '客户端 IP 地址；反向代理部署须按可信代理配置获取。';

COMMENT ON COLUMN audit_logs.id IS '记录主键，UUID 格式，由应用生成；初始化数据由 SQL 生成。';

COMMENT ON COLUMN audit_logs.created_at IS '记录创建时间，带时区，应用统一使用 UTC。';

COMMENT ON COLUMN audit_logs.updated_at IS '记录最后修改时间，带时区，应用更新时维护。';

COMMENT ON TABLE audit_logs IS '审计日志：记录登录、退出和管理操作，便于追踪操作者、目标资源与变更来源。';

COMMENT ON COLUMN document_chunks.document_version_id IS '所属文档版本 ID，关联 document_versions.id。';

COMMENT ON COLUMN document_chunks.chunk_index IS '版本内切片序号，与 document_version_id 联合唯一。';

COMMENT ON COLUMN document_chunks.content IS '切片纯文本，供检索和回答引用使用。';

COMMENT ON COLUMN document_chunks.heading_path IS '切片所属 Markdown 标题层级路径。';

COMMENT ON COLUMN document_chunks.token_count IS '切片估算或实际 token 数量。';

COMMENT ON COLUMN document_chunks.embedding IS 'pgvector 向量；初始化不指定维度，接入模型后必须校验固定维度再建立向量索引。';

COMMENT ON COLUMN document_chunks.metadata IS '切片附加信息，JSON 对象，可记录行号、代码块和表格位置。';

COMMENT ON COLUMN document_chunks.id IS '记录主键，UUID 格式，由应用生成；初始化数据由 SQL 生成。';

COMMENT ON COLUMN document_chunks.created_at IS '记录创建时间，带时区，应用统一使用 UTC。';

COMMENT ON COLUMN document_chunks.updated_at IS '记录最后修改时间，带时区，应用更新时维护。';

COMMENT ON TABLE document_chunks IS '文档切片与向量：保存可检索文本及其来源；向量维度需由首次真实 DashScope 返回确认后约束。';

COMMENT ON COLUMN document_versions.document_id IS '所属逻辑文档 ID，关联 documents.id。';

COMMENT ON COLUMN document_versions.version_no IS '文档内递增版本号，与 document_id 联合唯一。';

COMMENT ON COLUMN document_versions.minio_bucket IS '存放原始 Markdown 文件的私有 MinIO 存储桶名称。';

COMMENT ON COLUMN document_versions.minio_object_key IS '唯一 MinIO 对象键；不保存服务器本地文件路径。';

COMMENT ON COLUMN document_versions.filename IS '用户上传的原始文件名。';

COMMENT ON COLUMN document_versions.content_type IS '文件媒体类型，通常为 text/markdown。';

COMMENT ON COLUMN document_versions.file_size IS '原始文件大小，单位为字节。';

COMMENT ON COLUMN document_versions.content_hash IS '原始文件内容的 SHA-256 校验摘要。';

COMMENT ON COLUMN document_versions.status IS '处理状态：UPLOADED 已上传、PARSING 解析中、CHUNKING 切片中、EMBEDDING 向量化中、INDEXED 可检索、FAILED 失败。';

COMMENT ON COLUMN document_versions.chunk_count IS '此版本实际生成的文档切片数量。';

COMMENT ON COLUMN document_versions.embedding_model IS '生成此版本向量使用的 Embedding 模型名称及版本。';

COMMENT ON COLUMN document_versions.error_message IS '操作失败的可读原因；不得写入密钥或密码。';

COMMENT ON COLUMN document_versions.created_by IS '创建此记录的用户 ID，关联 users.id；系统初始化时可为空。';

COMMENT ON COLUMN document_versions.id IS '记录主键，UUID 格式，由应用生成；初始化数据由 SQL 生成。';

COMMENT ON COLUMN document_versions.created_at IS '记录创建时间，带时区，应用统一使用 UTC。';

COMMENT ON COLUMN document_versions.updated_at IS '记录最后修改时间，带时区，应用更新时维护。';

COMMENT ON TABLE document_versions IS '文档版本：每次上传创建独立版本和 MinIO 对象，保留历史内容与处理状态。';

COMMENT ON COLUMN documents.knowledge_base_id IS '所属知识库 ID，关联 knowledge_bases.id。';

COMMENT ON COLUMN documents.title IS '文档显示标题。';

COMMENT ON COLUMN documents.current_version_id IS '当前可检索版本 ID，关联 document_versions.id；索引成功后才能切换。';

COMMENT ON COLUMN documents.status IS '文档状态：active 有效、archived 已归档。';

COMMENT ON COLUMN documents.created_by IS '创建此记录的用户 ID，关联 users.id；系统初始化时可为空。';

COMMENT ON COLUMN documents.id IS '记录主键，UUID 格式，由应用生成；初始化数据由 SQL 生成。';

COMMENT ON COLUMN documents.created_at IS '记录创建时间，带时区，应用统一使用 UTC。';

COMMENT ON COLUMN documents.updated_at IS '记录最后修改时间，带时区，应用更新时维护。';

COMMENT ON TABLE documents IS '逻辑文档：归属于一个知识库，关联多个版本；仅当前成功索引的版本参与检索。';

COMMENT ON COLUMN index_tasks.document_version_id IS '目标文档版本 ID，关联 document_versions.id。';

COMMENT ON COLUMN index_tasks.task_type IS '任务类型：INDEX 首次索引、REINDEX 重新索引、DELETE 删除清理。';

COMMENT ON COLUMN index_tasks.status IS '执行状态：PENDING 待处理、RUNNING 执行中、SUCCESS 成功、FAILED 失败。';

COMMENT ON COLUMN index_tasks.attempts IS '已执行尝试次数，初始为 0。';

COMMENT ON COLUMN index_tasks.error_message IS '操作失败的可读原因；不得写入密钥或密码。';

COMMENT ON COLUMN index_tasks.started_at IS '任务最近一次开始执行时间。';

COMMENT ON COLUMN index_tasks.finished_at IS '任务最近一次执行结束时间。';

COMMENT ON COLUMN index_tasks.id IS '记录主键，UUID 格式，由应用生成；初始化数据由 SQL 生成。';

COMMENT ON COLUMN index_tasks.created_at IS '记录创建时间，带时区，应用统一使用 UTC。';

COMMENT ON COLUMN index_tasks.updated_at IS '记录最后修改时间，带时区，应用更新时维护。';

COMMENT ON TABLE index_tasks IS '异步文档处理任务：记录索引、重建或删除任务的状态、重试次数和错误。';

COMMENT ON COLUMN knowledge_bases.code IS '唯一知识库编码，机器人请求通过此编码选择知识库。';

COMMENT ON COLUMN knowledge_bases.name IS '知识库显示名称。';

COMMENT ON COLUMN knowledge_bases.description IS '供管理人员阅读的用途或业务描述，可为空。';

COMMENT ON COLUMN knowledge_bases.status IS '知识库状态：active 可查询、disabled 暂停服务、archived 已归档。';

COMMENT ON COLUMN knowledge_bases.created_by IS '创建此记录的用户 ID，关联 users.id；系统初始化时可为空。';

COMMENT ON COLUMN knowledge_bases.id IS '记录主键，UUID 格式，由应用生成；初始化数据由 SQL 生成。';

COMMENT ON COLUMN knowledge_bases.created_at IS '记录创建时间，带时区，应用统一使用 UTC。';

COMMENT ON COLUMN knowledge_bases.updated_at IS '记录最后修改时间，带时区，应用更新时维护。';

COMMENT ON TABLE knowledge_bases IS '知识库：组织文档与检索范围；状态包括 active 启用、disabled 停用、archived 归档。';

COMMENT ON COLUMN pages.code IS '唯一页面资源编码，用于权限映射和前端路由标识。';

COMMENT ON COLUMN pages.name IS '页面中文名称，在导航与页面标题中展示。';

COMMENT ON COLUMN pages.route_path IS '唯一前端路由路径，例如 /documents。';

COMMENT ON COLUMN pages.route_name IS '前端路由的逻辑名称。';

COMMENT ON COLUMN pages.component_key IS '前端本地组件白名单中的键名，不允许当作可执行代码。';

COMMENT ON COLUMN pages.parent_id IS '父页面 ID，关联 pages.id；为空表示顶级资源。';

COMMENT ON COLUMN pages.page_type IS '资源类型：menu 菜单、page 页面、button 按钮、hidden 隐藏路由。';

COMMENT ON COLUMN pages.sort_order IS '菜单显示顺序，数值越小越靠前。';

COMMENT ON COLUMN pages.is_visible IS '是否在菜单中显示；隐藏菜单不等于撤销访问权限。';

COMMENT ON COLUMN pages.status IS '业务启用状态：active 启用、disabled 停用；具体归档状态见所属表说明。';

COMMENT ON COLUMN pages.id IS '记录主键，UUID 格式，由应用生成；初始化数据由 SQL 生成。';

COMMENT ON COLUMN pages.created_at IS '记录创建时间，带时区，应用统一使用 UTC。';

COMMENT ON COLUMN pages.updated_at IS '记录最后修改时间，带时区，应用更新时维护。';

COMMENT ON TABLE pages IS '页面资源目录：定义前端动态路由与菜单元数据；页面权限不替代后端 API 鉴权。';

COMMENT ON COLUMN qa_logs.request_id IS '唯一请求编号，重复请求应复用已有结果。';

COMMENT ON COLUMN qa_logs.source_type IS '请求来源：WEB 网页用户、ROBOT 机器人。';

COMMENT ON COLUMN qa_logs.user_id IS '关联的网页用户 ID，关联 users.id。';

COMMENT ON COLUMN qa_logs.robot_id IS '发起请求的机器人 ID，关联 robots.id；网页请求为空。';

COMMENT ON COLUMN qa_logs.knowledge_base_id IS '本次检索的知识库 ID，关联 knowledge_bases.id。';

COMMENT ON COLUMN qa_logs.question IS '用户或机器人提交的原始问题文本。';

COMMENT ON COLUMN qa_logs.answer IS '最终生成的回答文本；失败时可以为空。';

COMMENT ON COLUMN qa_logs.sources IS '回答引用来源的 JSON 数据，包含文档、版本、标题路径和片段。';

COMMENT ON COLUMN qa_logs.retrieval_count IS '本次向量检索实际召回的切片数量。';

COMMENT ON COLUMN qa_logs.model_name IS '本次答案生成使用的大语言模型名称。';

COMMENT ON COLUMN qa_logs.status IS '问答结果：SUCCESS 成功、FAILED 失败。';

COMMENT ON COLUMN qa_logs.error_message IS '操作失败的可读原因；不得写入密钥或密码。';

COMMENT ON COLUMN qa_logs.latency_ms IS '完整问答请求处理耗时，单位为毫秒。';

COMMENT ON COLUMN qa_logs.id IS '记录主键，UUID 格式，由应用生成；初始化数据由 SQL 生成。';

COMMENT ON COLUMN qa_logs.created_at IS '记录创建时间，带时区，应用统一使用 UTC。';

COMMENT ON COLUMN qa_logs.updated_at IS '记录最后修改时间，带时区，应用更新时维护。';

COMMENT ON TABLE qa_logs IS '问答日志：记录网页和机器人请求、答案、引用与耗时；request_id 用于请求幂等。';

COMMENT ON COLUMN robots.serial_no IS '机器人唯一序列号，机器人接口用于校验注册身份。';

COMMENT ON COLUMN robots.name IS '机器人显示名称。';

COMMENT ON COLUMN robots.description IS '供管理人员阅读的用途或业务描述，可为空。';

COMMENT ON COLUMN robots.status IS '业务启用状态：active 启用、disabled 停用；具体归档状态见所属表说明。';

COMMENT ON COLUMN robots.last_request_at IS '最近一次请求知识服务的时间，可为空。';

COMMENT ON COLUMN robots.created_by IS '创建此记录的用户 ID，关联 users.id；系统初始化时可为空。';

COMMENT ON COLUMN robots.id IS '记录主键，UUID 格式，由应用生成；初始化数据由 SQL 生成。';

COMMENT ON COLUMN robots.created_at IS '记录创建时间，带时区，应用统一使用 UTC。';

COMMENT ON COLUMN robots.updated_at IS '记录最后修改时间，带时区，应用更新时维护。';

COMMENT ON TABLE robots IS '机器人登记：保存设备身份和启用状态；第一版不绑定知识库，查询时提供知识库编码。';

COMMENT ON COLUMN role_page_permissions.role_id IS '被授权的角色 ID，关联 roles.id。';

COMMENT ON COLUMN role_page_permissions.page_id IS '被授权的页面资源 ID，关联 pages.id。';

COMMENT ON COLUMN role_page_permissions.can_view IS '是否允许访问此页面；仅 true 且页面启用时返回到前端。';

COMMENT ON COLUMN role_page_permissions.created_at IS '记录创建时间，带时区，应用统一使用 UTC。';

COMMENT ON TABLE role_page_permissions IS '角色页面授权：将角色与可访问页面关联，角色和页面共同构成主键。';

COMMENT ON COLUMN roles.code IS '唯一角色编码；后端管理接口使用 super_admin 编码校验管理员身份。';

COMMENT ON COLUMN roles.name IS '角色的中文显示名称。';

COMMENT ON COLUMN roles.is_system IS '是否为系统内置角色；true 表示内置角色。';

COMMENT ON COLUMN roles.status IS '业务启用状态：active 启用、disabled 停用；具体归档状态见所属表说明。';

COMMENT ON COLUMN roles.description IS '供管理人员阅读的用途或业务描述，可为空。';

COMMENT ON COLUMN roles.id IS '记录主键，UUID 格式，由应用生成；初始化数据由 SQL 生成。';

COMMENT ON COLUMN roles.created_at IS '记录创建时间，带时区，应用统一使用 UTC。';

COMMENT ON COLUMN roles.updated_at IS '记录最后修改时间，带时区，应用更新时维护。';

COMMENT ON TABLE roles IS '用户角色：包含普通用户 user 和超级管理员 super_admin，可扩展其他角色。';

COMMENT ON COLUMN user_sessions.user_id IS '关联的网页用户 ID，关联 users.id。';

COMMENT ON COLUMN user_sessions.refresh_token_hash IS '不透明刷新令牌的 SHA-256 哈希；原始令牌仅放入 HttpOnly Cookie。';

COMMENT ON COLUMN user_sessions.expires_at IS '会话绝对失效时间；超过时间即使 JWT 未过期也拒绝访问。';

COMMENT ON COLUMN user_sessions.revoked_at IS '会话撤销时间；为空表示未主动撤销。';

COMMENT ON COLUMN user_sessions.user_agent IS '登录客户端 User-Agent 摘要，用于追踪会话来源。';

COMMENT ON COLUMN user_sessions.ip_address IS '客户端 IP 地址；反向代理部署须按可信代理配置获取。';

COMMENT ON COLUMN user_sessions.id IS '记录主键，UUID 格式，由应用生成；初始化数据由 SQL 生成。';

COMMENT ON COLUMN user_sessions.created_at IS '记录创建时间，带时区，应用统一使用 UTC。';

COMMENT ON COLUMN user_sessions.updated_at IS '记录最后修改时间，带时区，应用更新时维护。';

COMMENT ON TABLE user_sessions IS '登录会话：保存刷新令牌的 SHA-256 哈希与会话有效期，支持轮换刷新和退出撤销。';

ALTER TABLE users ADD COLUMN password_plaintext VARCHAR(1024);

COMMENT ON COLUMN users.password_plaintext IS '按项目要求保留的当前原始明文密码，供数据库管理员找回；敏感信息，不返回 Web API，重置密码时同步更新。';

COMMENT ON COLUMN users.username IS '唯一登录用户名；初始化超级管理员用户名为 root。';

COMMENT ON COLUMN users.display_name IS '在页面和个人信息中展示的用户名称。';

COMMENT ON COLUMN users.password_hash IS 'Argon2 密码哈希，网页登录验证只使用此字段。';

COMMENT ON COLUMN users.role_id IS '所属角色 ID，关联 roles.id；第一版一个用户对应一个角色。';

COMMENT ON COLUMN users.status IS '用户状态：active 启用、disabled 停用、deleted 已逻辑删除；已删除用户不展示、不能登录，保留历史关联且用户名不复用。';

COMMENT ON COLUMN users.id IS '记录主键，UUID 格式，由应用生成；初始化数据由 SQL 生成。';

COMMENT ON COLUMN users.created_at IS '记录创建时间，带时区，应用统一使用 UTC。';

COMMENT ON COLUMN users.updated_at IS '记录最后修改时间，带时区，应用更新时维护。';

COMMENT ON TABLE users IS '平台用户：保存登录账号、密码和所属角色；不对外提供密码字段。';

UPDATE alembic_version SET version_num='16bb29ab4421' WHERE alembic_version.version_num = '904e450aa189';

-- Running upgrade 16bb29ab4421 -> 52c7a3d910e6（用户状态字段备注已在上方提供）
UPDATE alembic_version SET version_num='52c7a3d910e6' WHERE version_num = '16bb29ab4421';


-- 初始角色
INSERT INTO roles (id, code, name, description, is_system, status, created_at, updated_at) VALUES
(gen_random_uuid(), 'user', '普通用户', '访问知识问答与个人信息', true, 'active', now(), now()),
(gen_random_uuid(), 'super_admin', '超级管理员', '访问全部页面与管理接口', true, 'active', now(), now());

-- 初始页面：页面框架已就绪，部分业务操作按开发计划逐步接入。
INSERT INTO pages (id, code, name, route_path, route_name, component_key, parent_id, page_type, sort_order, is_visible, status, created_at, updated_at) VALUES
(gen_random_uuid(), 'dashboard', '工作台', '/dashboard', 'Dashboard', 'Dashboard', NULL, 'menu', 10, true, 'active', now(), now()),
(gen_random_uuid(), 'knowledge_qa', '知识问答', '/qa', 'KnowledgeQA', 'KnowledgeQA', NULL, 'menu', 20, true, 'active', now(), now()),
(gen_random_uuid(), 'knowledge_bases', '知识库管理', '/knowledge-bases', 'KnowledgeBaseManagement', 'KnowledgeBaseManagement', NULL, 'menu', 40, true, 'active', now(), now()),
(gen_random_uuid(), 'documents', '文档管理', '/documents', 'DocumentManagement', 'DocumentManagement', NULL, 'menu', 50, true, 'active', now(), now()),
(gen_random_uuid(), 'robots', '机器人管理', '/robots', 'RobotManagement', 'RobotManagement', NULL, 'menu', 60, true, 'active', now(), now()),
(gen_random_uuid(), 'users', '用户管理', '/users', 'UserManagement', 'UserManagement', NULL, 'menu', 70, true, 'active', now(), now()),
(gen_random_uuid(), 'roles', '角色管理', '/roles', 'RoleManagement', 'RoleManagement', NULL, 'menu', 80, true, 'active', now(), now()),
(gen_random_uuid(), 'pages', '页面路由', '/pages', 'PageManagement', 'PageManagement', NULL, 'menu', 81, true, 'active', now(), now()),
(gen_random_uuid(), 'role_permissions', '角色页面权限', '/role-permissions', 'RolePermissions', 'RolePermissions', NULL, 'menu', 82, true, 'active', now(), now()),
(gen_random_uuid(), 'qa_logs', '问答日志', '/qa-logs', 'QALogs', 'QALogs', NULL, 'menu', 90, true, 'active', now(), now()),
(gen_random_uuid(), 'audit_logs', '审计日志', '/audit-logs', 'AuditLogs', 'AuditLogs', NULL, 'menu', 95, true, 'active', now(), now()),
(gen_random_uuid(), 'profile', '个人信息', '/profile', 'Profile', 'Profile', NULL, 'menu', 100, true, 'active', now(), now());

-- 超级管理员被授予全部已注册页面权限。
INSERT INTO role_page_permissions (role_id, page_id, can_view, created_at)
SELECT r.id, p.id, true, now() FROM roles r CROSS JOIN pages p WHERE r.code = 'super_admin';

-- 普通用户仅允许知识问答及个人信息。
INSERT INTO role_page_permissions (role_id, page_id, can_view, created_at)
SELECT r.id, p.id, true, now() FROM roles r CROSS JOIN pages p
WHERE r.code = 'user' AND p.code IN ('knowledge_qa', 'profile');

-- 网页管理员 root：初始密码 Dexforce@Root2026!，并非 PostgreSQL 连接密码。
INSERT INTO users (id, username, display_name, password_hash, password_plaintext, role_id, status, created_at, updated_at)
SELECT gen_random_uuid(), 'root', 'Root 管理员', '$argon2id$v=19$m=65536,t=3,p=4$RVq+hz+j0lPnuI7CzAjyDA$vhlpR6yzfbhRA2u0XGvGSH/ThscGHz3xBrLJjvdlmmA', 'Dexforce@Root2026!', id, 'active', now(), now()
FROM roles WHERE code = 'super_admin';

-- 默认知识库：原始文档、索引和问答由后续业务功能写入。
INSERT INTO knowledge_bases (id, code, name, description, status, created_by, created_at, updated_at)
SELECT gen_random_uuid(), 'general', '通用知识库', '团队共享的产品资料、使用指南与技术文档', 'active', id, now(), now()
FROM users WHERE username = 'root';

-- 初始化审计
INSERT INTO audit_logs (id, user_id, action, resource_type, resource_id, detail, created_at, updated_at)
SELECT gen_random_uuid(), id, 'system.initialize', 'user', id,
'{"source":"init.sql","description":"初始化管理员与系统权限"}'::json, now(), now()
FROM users WHERE username = 'root';

COMMIT;
