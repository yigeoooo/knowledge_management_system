# 知识库管理系统开发需求文档

## 1. 文档目的

本文档定义知识库管理系统第一版的业务范围、角色权限、核心流程、数据模型、接口和非功能要求，作为前后端开发、数据库设计和测试验收的共同依据。

本文档中的业务流程指知识库管理系统流程，系统主要解决以下问题：

1. 管理员上传 Markdown 文档并构建可检索的知识库。
2. 普通用户通过网页向知识库提问。
3. 已注册机器人通过 HTTP 请求向指定知识库提问。
4. 管理员可以管理机器人、知识库文件、用户、角色和页面权限。

## 2. 系统边界和技术约束

| 模块 | 技术和职责 |
|---|---|
| Web 前端 | `knowledge_front`：Vue 3 + Element Plus，负责登录、页面渲染、知识库管理和网页提问 |
| 后端 API | `knowledge_back`：Flask，负责认证、权限、文档管理、问答编排和任务状态 |
| 关系数据库 | PostgreSQL，保存用户、角色、页面、知识库元数据、文档切片、问答日志 |
| 向量检索 | PostgreSQL + pgvector |
| 对象存储 | MinIO，保存原始 Markdown 文件 |
| 异步处理 | Worker + 任务队列，负责解析、切片和 Embedding |
| Embedding | 阿里云百炼 Embedding 云服务，文档和问题必须使用同一模型版本 |
| 大语言模型 | DeepSeek OpenAI 兼容 API |

原始文件存储在 MinIO，数据库保存 MinIO 的 `bucket`、`object_key` 和业务元数据。数据库不保存服务器本地文件路径，也不把 MinIO 作为用户权限和业务状态的来源。

第一版采用一个系统可以包含多个知识库的设计。机器人不和知识库建立关联，机器人请求中通过知识库 `code` 指定目标知识库。因此任何已注册且启用的机器人，只要提供有效的知识库 `code`，就可以查询该知识库。以后如果需要限制机器人访问范围，再增加机器人和知识库的关联表。

## 3. 角色和权限模型

系统采用“用户—角色—页面路由”的权限模型。用户登录后，后端返回该用户可以访问的页面路由，前端根据路由渲染菜单和页面；后端接口仍然必须独立校验权限，不能只依赖前端隐藏页面。

### 3.1 内置角色

| 角色 | 说明 | 页面范围 |
|---|---|---|
| 普通用户 | 使用知识库进行查询 | 只能访问知识库问答、网页提问及个人信息页面 |
| 超级管理员 | 系统维护和开发管理人员 | 可访问所有已注册页面和管理接口 |

角色不直接硬编码在前端。系统初始化时创建内置角色和页面路由，并插入角色与页面的关联数据。

### 3.2 页面权限规则

页面权限表至少保存以下信息：

- 页面名称
- 前端路由路径
- 路由名称或组件标识
- 父级路由
- 页面类型：菜单、页面、按钮或隐藏路由
- 是否启用
- 排序号

角色页面权限表保存某个角色可以访问哪些页面。第一版可以先按“页面访问”控制；如果后续要限制页面内按钮，再将按钮也作为一种页面资源或增加接口权限表。

### 3.3 权限加载流程

```text
用户提交用户名和密码
    ↓
后端校验密码和用户状态
    ↓
查询 user.role_id
    ↓
查询 role_page_permissions → pages
    ↓
返回 access_token、用户信息、可访问页面路由
    ↓
前端保存登录状态并动态生成路由和菜单
```

页面路由权限只负责前端导航和页面访问提示。所有管理 API 还必须在 Flask 中验证当前用户角色和目标权限。

## 4. 总体业务流程

### 4.1 用户登录和页面加载

1. 用户访问登录页。
2. 前端提交用户名和密码到登录接口。
3. 后端查询用户，使用密码哈希校验密码。
4. 检查用户状态是否为 `active`。
5. 根据用户角色查询启用的页面路由。
6. 返回访问令牌、刷新令牌、用户信息和页面列表。
7. 前端根据页面列表动态注册路由和菜单。
8. 后续所有需要登录的请求携带 `Authorization: Bearer <access_token>`。
9. Access Token 过期时使用刷新令牌换取新的 Access Token；退出登录时撤销会话。

普通用户登录后只显示问答和提问页面。超级管理员可以显示用户管理、角色管理、页面权限、机器人管理、知识库管理、文档管理和问答日志等页面。

### 4.2 知识库创建流程

1. 超级管理员进入知识库管理页面。
2. 填写知识库名称、唯一 `code` 和描述。
3. 后端检查 `code` 是否重复。
4. 创建知识库记录，状态为 `active`。
5. 管理员可以将知识库设为停用、恢复或归档。

知识库 `code` 是机器人请求中使用的外部标识；数据库内部仍使用 UUID 作为主键。

### 4.3 机器人注册流程

1. 超级管理员打开机器人管理页面。
2. 填写机器人序列号、名称和描述。
3. 后端检查序列号是否唯一。
4. 创建机器人记录，默认状态为 `active`。
5. 机器人可以调用机器人问答接口。
6. 管理员停用机器人后，该序列号不能继续提问。

机器人接口暂时只验证：

```text
serial_no 存在
serial_no 状态为 active
knowledge_base_code 存在
knowledge_base 状态为 active
```

机器人不要求登录，也不要求和知识库建立关联。序列号属于身份标识而不是强安全凭证，接口应至少使用 HTTPS、限流、请求日志和请求大小限制。

### 4.4 文档上传和索引流程

1. 超级管理员在指定知识库下点击上传。
2. 后端校验用户登录状态、角色、文件扩展名和大小。
3. 后端生成 MinIO 预签名上传 URL，或由后端接收文件后上传到 MinIO。
4. 前端上传 Markdown 文件。
5. 前端调用上传完成接口。
6. 后端创建文档和文档版本记录，状态为 `UPLOADED`。
7. 后端创建异步索引任务。
8. Worker 从 MinIO 读取原文件，解析 Markdown 结构。
9. Worker 按标题、段落、代码块和表格进行切片。
10. Worker 批量生成 Embedding。
11. Worker 将切片和向量写入 PostgreSQL。
12. 所有切片成功后，版本状态变为 `INDEXED`，文档当前版本指向该版本。
13. 任一步骤失败时，版本状态变为 `FAILED`，保存错误信息并支持重试。

推荐初始切片参数为每块 400～800 tokens、重叠 50～100 tokens，实际参数应通过测试调整。切片中应保留标题路径，避免上下文丢失。

### 4.5 文档浏览、下载、修改和删除流程

#### 浏览和下载

1. 超级管理员请求知识库文档列表。
2. 后端从 PostgreSQL 返回文档元数据和处理状态。
3. 用户点击预览或下载时，后端生成短时有效的 MinIO 预签名 URL。
4. 前端使用预签名 URL 读取文件。

#### 修改

1. 管理员下载当前 Markdown 内容。
2. 前端允许编辑文本。
3. 修改后的内容上传为新的 MinIO 对象。
4. 后端创建新的文档版本，不直接覆盖当前版本。
5. 旧版本保持可追溯，新版本进入 `PROCESSING`。
6. 新版本索引成功后，将文档的当前版本切换到新版本。

#### 删除

1. 管理员请求删除文档。
2. 后端校验权限并将文档标记为删除或归档。
3. 删除或失效对应版本的向量切片。
4. 删除 MinIO 对象；删除失败时记录清理任务并重试。

### 4.6 网页提问流程

网页提问必须验证登录状态。

1. 用户登录后进入提问页面。
2. 用户选择知识库并输入问题。
3. 前端调用网页提问接口，携带 Bearer Token。
4. 后端验证 Token、用户状态和知识库状态。
5. 后端调用阿里云百炼 Embedding 云服务处理问题。
6. 在指定知识库中检索状态为 `INDEXED` 的文档切片。
7. 可选使用关键词检索或重排模型提高召回质量。
8. 将问题、检索片段和来源信息提交给大语言模型。
9. 要求模型只根据检索内容回答，无法找到依据时明确说明。
10. 返回答案、来源文档、标题和请求编号。
11. 将问答记录写入 `qa_logs`。

### 4.7 机器人提问流程

请求示例：

```json
{
  "serial_no": "ROBOT-001",
  "knowledge_base_code": "product_manual",
  "question": "设备如何安装？",
  "request_id": "req-202610210001"
}
```

处理流程：

1. 校验请求格式和问题长度。
2. 根据 `serial_no` 查询机器人。
3. 检查机器人存在且状态为 `active`。
4. 根据 `knowledge_base_code` 查询知识库。
5. 检查知识库存在且状态为 `active`。
6. 使用知识库内部 UUID 作为向量查询过滤条件。
7. 检索、重排、调用大语言模型并生成答案。
8. 返回答案和来源。
9. 写入 `qa_logs`，其中 `source_type = ROBOT`。

机器人请求不使用网页用户的登录 Token。

## 5. 状态定义

### 5.1 用户状态

```text
active      可登录
disabled    禁止登录
```

### 5.2 角色和页面状态

```text
active      可被查询和使用
disabled    不再返回给前端
```

### 5.3 知识库状态

```text
active      可上传、检索
disabled    暂停检索和修改
archived    只读保存
```

### 5.4 文档和文档版本状态

```text
UPLOADED    原文件已保存，等待处理
PROCESSING  正在解析、切片或生成向量
INDEXED     已完成索引，可以检索
FAILED      处理失败，可以重试
ARCHIVED    版本或文档已归档
```

## 6. 数据库设计

### 6.1 用户表 `users`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | 用户 ID |
| username | varchar(100) | UNIQUE NOT NULL | 登录名 |
| password_hash | varchar(255) | NOT NULL | 密码哈希，禁止保存明文密码 |
| display_name | varchar(100) |  | 显示名称 |
| role_id | uuid | FK roles.id | 用户角色 |
| status | varchar(30) | NOT NULL | `active`/`disabled` |
| last_login_at | timestamp |  | 最近登录时间 |
| created_at | timestamp | NOT NULL | 创建时间 |
| updated_at | timestamp | NOT NULL | 修改时间 |

### 6.2 角色表 `roles`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | 角色 ID |
| code | varchar(50) | UNIQUE NOT NULL | `user`、`super_admin` 等 |
| name | varchar(100) | NOT NULL | 角色名称 |
| description | text |  | 说明 |
| is_system | boolean | NOT NULL | 是否系统内置角色 |
| status | varchar(30) | NOT NULL | 是否启用 |
| created_at | timestamp | NOT NULL | 创建时间 |
| updated_at | timestamp | NOT NULL | 修改时间 |

第一版至少初始化 `user` 和 `super_admin` 两个角色。

### 6.3 页面路由表 `pages`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | 页面 ID |
| code | varchar(100) | UNIQUE NOT NULL | 页面资源编码 |
| name | varchar(100) | NOT NULL | 页面名称 |
| route_path | varchar(255) | UNIQUE NOT NULL | Vue 路由路径 |
| route_name | varchar(100) |  | Vue 路由名称 |
| component_key | varchar(255) |  | 前端组件标识 |
| parent_id | uuid | FK pages.id | 父级页面 |
| page_type | varchar(30) | NOT NULL | `menu`/`page`/`button`/`hidden` |
| sort_order | integer | NOT NULL | 菜单排序 |
| is_visible | boolean | NOT NULL | 是否显示在菜单 |
| status | varchar(30) | NOT NULL | 是否启用 |
| created_at | timestamp | NOT NULL | 创建时间 |
| updated_at | timestamp | NOT NULL | 修改时间 |

页面路由数据由后端返回，前端使用 `route_path`、`route_name` 和 `component_key` 动态构建页面。

### 6.4 角色页面权限表 `role_page_permissions`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| role_id | uuid | PK/FK roles.id | 角色 ID |
| page_id | uuid | PK/FK pages.id | 页面 ID |
| can_view | boolean | NOT NULL | 是否允许访问 |
| created_at | timestamp | NOT NULL | 创建时间 |

主键为 `(role_id, page_id)`。普通用户只插入问答和提问页面；超级管理员插入所有启用页面。

### 6.5 登录会话表 `user_sessions`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | 会话 ID |
| user_id | uuid | FK users.id | 用户 |
| refresh_token_hash | varchar(255) |  | 刷新令牌哈希 |
| expires_at | timestamp | NOT NULL | 过期时间 |
| revoked_at | timestamp |  | 撤销时间 |
| user_agent | text |  | 客户端信息 |
| ip_address | varchar(64) |  | 登录 IP |
| created_at | timestamp | NOT NULL | 创建时间 |

### 6.6 知识库表 `knowledge_bases`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | 内部 ID |
| code | varchar(100) | UNIQUE NOT NULL | 机器人请求使用的编码 |
| name | varchar(200) | NOT NULL | 名称 |
| description | text |  | 描述 |
| status | varchar(30) | NOT NULL | `active`/`disabled`/`archived` |
| created_by | uuid | FK users.id | 创建人 |
| created_at | timestamp | NOT NULL | 创建时间 |
| updated_at | timestamp | NOT NULL | 修改时间 |

### 6.7 机器人表 `robots`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | 内部 ID |
| serial_no | varchar(100) | UNIQUE NOT NULL | 机器人唯一序列号 |
| name | varchar(200) |  | 机器人名称 |
| description | text |  | 说明 |
| status | varchar(30) | NOT NULL | `active`/`disabled` |
| last_request_at | timestamp |  | 最近请求时间 |
| created_by | uuid | FK users.id | 注册管理员 |
| created_at | timestamp | NOT NULL | 创建时间 |
| updated_at | timestamp | NOT NULL | 修改时间 |

当前不设置 `robot_id` 和 `knowledge_base_id` 的关联表。

### 6.8 文档逻辑表 `documents`

一个文档逻辑记录可以有多个版本，只有当前版本参与默认检索。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | 文档 ID |
| knowledge_base_id | uuid | FK knowledge_bases.id | 所属知识库 |
| title | varchar(255) | NOT NULL | 文档标题 |
| current_version_id | uuid |  | 当前版本 |
| status | varchar(30) | NOT NULL | `active`/`archived` |
| created_by | uuid | FK users.id | 上传人 |
| created_at | timestamp | NOT NULL | 创建时间 |
| updated_at | timestamp | NOT NULL | 修改时间 |

`current_version_id` 可以在版本表创建后通过外键补充，避免建表时循环依赖。

### 6.9 文档版本表 `document_versions`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | 版本 ID |
| document_id | uuid | FK documents.id | 逻辑文档 |
| version_no | integer | UNIQUE(document_id, version_no) | 版本号 |
| minio_bucket | varchar(100) | NOT NULL | MinIO bucket |
| minio_object_key | varchar(500) | NOT NULL | MinIO object key |
| filename | varchar(255) | NOT NULL | 原始文件名 |
| content_type | varchar(100) |  | 文件类型 |
| file_size | bigint |  | 文件大小 |
| content_hash | varchar(64) |  | SHA-256 |
| status | varchar(30) | NOT NULL | 版本处理状态 |
| chunk_count | integer | NOT NULL | 切片数量 |
| embedding_model | varchar(200) |  | Embedding 模型版本 |
| error_message | text |  | 失败原因 |
| created_by | uuid | FK users.id | 上传人 |
| created_at | timestamp | NOT NULL | 创建时间 |
| updated_at | timestamp | NOT NULL | 修改时间 |

### 6.10 文档切片表 `document_chunks`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | 切片 ID |
| document_version_id | uuid | FK document_versions.id | 文档版本 |
| chunk_index | integer | UNIQUE(version_id, chunk_index) | 切片序号 |
| content | text | NOT NULL | 切片文本 |
| heading_path | text |  | 标题路径 |
| token_count | integer |  | token 数 |
| embedding | vector(维度) | NOT NULL | 向量，维度由模型决定 |
| metadata | jsonb |  | 行号、代码块、表格等信息 |
| created_at | timestamp | NOT NULL | 创建时间 |

建议建立以下索引：

```sql
CREATE INDEX idx_documents_kb_status
    ON documents (knowledge_base_id, status);

CREATE INDEX idx_document_versions_document
    ON document_versions (document_id, version_no);

CREATE INDEX idx_chunks_version
    ON document_chunks (document_version_id);

CREATE INDEX idx_chunks_embedding
    ON document_chunks USING hnsw (embedding vector_cosine_ops);
```

### 6.11 索引任务表 `index_tasks`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | 任务 ID |
| document_version_id | uuid | FK document_versions.id | 文档版本 |
| task_type | varchar(30) | NOT NULL | `INDEX`/`REINDEX`/`DELETE` |
| status | varchar(30) | NOT NULL | `PENDING`/`RUNNING`/`SUCCESS`/`FAILED` |
| attempts | integer | NOT NULL | 重试次数 |
| error_message | text |  | 错误信息 |
| started_at | timestamp |  | 开始时间 |
| finished_at | timestamp |  | 完成时间 |
| created_at | timestamp | NOT NULL | 创建时间 |

### 6.12 问答日志表 `qa_logs`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | 记录 ID |
| request_id | varchar(100) | UNIQUE NOT NULL | 幂等请求编号 |
| source_type | varchar(20) | NOT NULL | `WEB`/`ROBOT` |
| user_id | uuid | FK users.id | 网页用户，可为空 |
| robot_id | uuid | FK robots.id | 机器人，可为空 |
| knowledge_base_id | uuid | FK knowledge_bases.id | 查询知识库 |
| question | text | NOT NULL | 问题 |
| answer | text |  | 答案 |
| sources | jsonb |  | 来源文档和标题 |
| retrieval_count | integer |  | 召回数量 |
| model_name | varchar(200) |  | 大模型名称 |
| status | varchar(30) | NOT NULL | `SUCCESS`/`FAILED` |
| error_message | text |  | 错误信息 |
| latency_ms | integer |  | 总耗时 |
| created_at | timestamp | NOT NULL | 创建时间 |

### 6.13 审计日志表 `audit_logs`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | 日志 ID |
| user_id | uuid | FK users.id | 操作用户 |
| action | varchar(100) | NOT NULL | 操作名称 |
| resource_type | varchar(50) | NOT NULL | 资源类型 |
| resource_id | uuid |  | 资源 ID |
| detail | jsonb |  | 操作详情 |
| ip_address | varchar(64) |  | IP |
| created_at | timestamp | NOT NULL | 时间 |

管理员新增用户、修改角色页面权限、上传或删除文档、注册机器人、修改知识库时应写入审计日志。

## 7. 接口设计

统一前缀为 `/api/v1`。接口返回格式建议统一为：

```json
{
  "code": 0,
  "message": "ok",
  "data": {},
  "request_id": "req-xxx"
}
```

失败时 `code` 使用业务错误码，HTTP 状态码仍应表达基本语义。

### 7.1 认证和当前用户

| 方法 | 路径 | 登录要求 | 说明 |
|---|---|---|---|
| POST | `/auth/login` | 否 | 用户登录并返回令牌和页面路由 |
| POST | `/auth/refresh` | refresh token | 刷新访问令牌 |
| POST | `/auth/logout` | 是 | 撤销当前会话 |
| GET | `/auth/me` | 是 | 获取当前用户和页面权限 |

登录请求：

```json
{
  "username": "admin",
  "password": "******"
}
```

登录响应至少包括：

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "expires_in": 3600,
  "user": {
    "id": "...",
    "username": "admin",
    "role": "super_admin"
  },
  "pages": [
    {
      "code": "document_management",
      "name": "文档管理",
      "route_path": "/documents",
      "route_name": "Documents",
      "component_key": "DocumentManagement",
      "parent_id": null,
      "page_type": "menu",
      "sort_order": 20
    }
  ]
}
```

### 7.2 用户、角色和页面权限

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/users` | 超级管理员 | 用户分页列表 |
| POST | `/users` | 超级管理员 | 创建用户 |
| PUT | `/users/{id}` | 超级管理员 | 修改用户、角色和状态 |
| POST | `/users/{id}/reset-password` | 超级管理员 | 重置密码 |
| GET | `/roles` | 超级管理员 | 角色列表 |
| POST | `/roles` | 超级管理员 | 创建角色 |
| PUT | `/roles/{id}` | 超级管理员 | 修改角色 |
| GET | `/roles/{id}/pages` | 超级管理员 | 查询角色页面 |
| PUT | `/roles/{id}/pages` | 超级管理员 | 覆盖角色页面权限 |
| GET | `/pages` | 超级管理员 | 页面路由列表 |
| POST | `/pages` | 超级管理员 | 新增页面路由 |
| PUT | `/pages/{id}` | 超级管理员 | 修改页面路由 |

`PUT /roles/{id}/pages` 请求示例：

```json
{
  "page_ids": ["page-uuid-1", "page-uuid-2"]
}
```

### 7.3 知识库管理

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/knowledge-bases` | 登录用户 | 查询可用知识库 |
| POST | `/knowledge-bases` | 超级管理员 | 创建知识库 |
| GET | `/knowledge-bases/{id}` | 登录用户 | 查询详情 |
| PUT | `/knowledge-bases/{id}` | 超级管理员 | 修改名称、描述、状态 |
| DELETE | `/knowledge-bases/{id}` | 超级管理员 | 归档知识库 |

普通用户只能读取状态为 `active` 的知识库，用于网页提问。

### 7.4 机器人管理

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/robots` | 超级管理员 | 机器人列表 |
| POST | `/robots` | 超级管理员 | 注册机器人 |
| GET | `/robots/{id}` | 超级管理员 | 机器人详情 |
| PUT | `/robots/{id}` | 超级管理员 | 修改名称、描述、状态 |
| DELETE | `/robots/{id}` | 超级管理员 | 停用或删除机器人 |

### 7.5 文档和 MinIO 文件

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/knowledge-bases/{id}/documents` | 超级管理员 | 文档分页列表 |
| POST | `/documents/presign-upload` | 超级管理员 | 获取 MinIO 上传地址 |
| POST | `/documents/complete` | 超级管理员 | 上传完成并创建索引任务 |
| GET | `/documents/{id}` | 超级管理员 | 文档和版本详情 |
| GET | `/documents/{id}/download-url` | 超级管理员 | 获取临时下载地址 |
| PUT | `/documents/{id}` | 超级管理员 | 上传新版本或修改文档信息 |
| POST | `/documents/{id}/reindex` | 超级管理员 | 重新建立索引 |
| DELETE | `/documents/{id}` | 超级管理员 | 归档文档并清理对象 |
| GET | `/tasks/{id}` | 超级管理员 | 查询索引任务状态 |

获取上传地址请求：

```json
{
  "knowledge_base_id": "kb-uuid",
  "filename": "部署说明.md",
  "content_type": "text/markdown",
  "file_size": 102400
}
```

返回 `upload_url`、`object_key` 和过期时间。前端完成 MinIO 上传后必须调用 `/documents/complete`，后端才创建正式文档版本和索引任务。

### 7.6 网页提问

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/web/query` | 登录用户 | 网页模拟提问 |
| GET | `/web/qa-logs` | 登录用户 | 查看自己的问答记录 |

请求示例：

```json
{
  "knowledge_base_id": "kb-uuid",
  "question": "如何部署系统？",
  "top_k": 5,
  "stream": false,
  "request_id": "web-req-001"
}
```

### 7.7 机器人提问

| 方法 | 路径 | 登录要求 | 说明 |
|---|---|---|---|
| POST | `/robot/query` | 不需要用户登录 | 校验机器人序列号后提问 |

请求示例：

```json
{
  "serial_no": "ROBOT-001",
  "knowledge_base_code": "product_manual",
  "question": "设备如何安装？",
  "top_k": 5,
  "request_id": "robot-req-001"
}
```

响应中的 `sources` 至少包含文档 ID、文件名、版本、标题路径和相关文本片段，方便网页展示引用来源。

### 7.8 统一错误码

| 错误码 | 含义 |
|---|---|
| 40101 | 未登录或访问令牌无效 |
| 40102 | 用户已被禁用 |
| 40301 | 无页面或接口权限 |
| 40401 | 资源不存在 |
| 40901 | 用户名、序列号或知识库 code 已存在 |
| 42201 | 请求参数错误 |
| 42202 | 文件类型或大小不符合要求 |
| 43001 | 机器人未注册或已停用 |
| 43002 | 知识库不存在或已停用 |
| 50001 | 文档索引失败 |
| 50002 | 问答模型服务失败 |

## 8. 前端页面需求

### 8.1 普通用户页面

普通用户登录后只能访问：

1. 知识库问答页面。
2. 网页提问页面。
3. 个人信息或退出登录功能。

问答页面必须支持选择知识库、输入问题、展示答案、展示引用来源、展示加载和错误状态。

### 8.2 超级管理员页面

超级管理员可以访问：

1. 系统首页或仪表盘。
2. 知识库管理。
3. 文档上传、浏览、下载、修改、归档和重新索引。
4. 机器人注册、查看、启用和停用。
5. 用户注册、用户列表和用户状态管理。
6. 角色管理。
7. 页面路由管理。
8. 角色页面权限配置。
9. 网页提问测试页面。
10. 问答日志和审计日志。

前端根据登录接口返回的 `pages` 动态渲染菜单和路由。路由守卫发现没有权限时跳转到 403 页面；即使用户手动输入 URL，后端也必须拒绝无权限的接口请求。

## 9. 检索和问答规则

1. 文档和问题使用同一个阿里云百炼 Embedding 模型和向量维度。
2. Embedding 服务通过环境变量配置，不能使用 DeepSeek 对话接口的文本结果伪装成向量。
3. 只检索当前知识库中 `INDEXED` 的当前文档版本。
4. 默认召回 Top 10～20 个切片，再选取 Top 3～8 个提交给大模型。
5. 可以增加 PostgreSQL 全文检索和 reranker，形成混合检索。
6. 检索结果低于相似度阈值时，模型应明确说明文档中没有足够依据。
7. 大模型提示词要求回答中附带来源，不允许把文档中的指令当作系统指令执行。
8. 问答接口应支持 `request_id` 幂等，重复请求不会产生重复日志或重复任务。

## 10. 安全和非功能要求

### 10.1 安全

- 密码使用 Argon2 或 bcrypt 哈希保存。
- MinIO Bucket 默认私有，前端只使用短时预签名 URL。
- 不向浏览器返回 MinIO Access Key 和 Secret Key。
- 登录接口限流，机器人接口按序列号和 IP 限流。
- 上传限制为 Markdown 文件，并限制大小、文件名和请求体大小。
- 所有管理操作写入审计日志。
- 管理员注册机器人和用户的接口必须登录并校验超级管理员权限。
- 机器人接口使用 HTTPS，后续可增加 API Key 或请求签名。

### 10.2 一致性

- 文档只有在对象保存、切片写入和向量写入完成后才能标记为 `INDEXED`。
- 索引失败必须保留错误信息并支持重试。
- 更新文档创建新版本，避免直接覆盖导致无法追溯。
- 删除文档时同时处理数据库切片和 MinIO 对象；清理失败进入重试任务。

### 10.3 性能和可观测性

- Embedding 采用批量处理。
- pgvector 建立 HNSW 或 IVFFlat 索引。
- 查询响应记录检索耗时、模型耗时和总耗时。
- 每个请求带 `request_id` 或 `trace_id`。
- 记录索引任务、模型调用和异常日志。
- 大模型支持流式返回时，网页端使用 SSE 展示生成过程。

## 11. MVP 开发顺序

### 第一阶段：基础认证和权限

1. 用户登录、退出、刷新令牌。
2. 角色、页面和角色页面权限表。
3. 登录后返回页面路由。
4. Vue 动态菜单和路由守卫。
5. Flask 后端权限中间件。

### 第二阶段：知识库和文档

1. 知识库 CRUD。
2. MinIO 文件上传和下载。
3. 文档版本记录。
4. Markdown 解析、切片和索引任务。
5. pgvector 向量检索。

### 第三阶段：问答

1. 网页提问页面。
2. 网页提问接口和问答日志。
3. 机器人注册管理。
4. 机器人 `serial_no + knowledge_base_code` 提问接口。
5. 答案来源展示。

### 第四阶段：管理增强

1. 用户和角色管理。
2. 页面路由配置页面。
3. 文档版本回滚和重新索引。
4. 审计日志和统计页面。
5. 混合检索、reranker 和流式回答。

## 12. 第一版验收标准

1. 未登录用户不能访问网页提问接口和管理页面。
2. 普通用户登录后只能看到并访问问答和提问页面。
3. 超级管理员可以看到所有已启用页面，并能管理用户、角色、页面、知识库、文档和机器人。
4. 登录接口返回当前用户可访问的页面路由，前端可以动态渲染菜单。
5. 机器人不登录也能通过已注册的 `serial_no` 发起请求。
6. 未注册或已停用的机器人请求被拒绝。
7. 机器人可以通过 `knowledge_base_code` 查询指定知识库。
8. 原始 Markdown 文件保存于 MinIO，数据库保存对象信息和业务元数据。
9. 文档经过解析、切片和 Embedding 后才能参与检索。
10. 网页和机器人问答都返回答案、来源和请求编号。
11. 文档索引失败时可以查看错误原因并重新处理。
12. 所有用户、机器人、文档和问答管理操作可以追溯到操作日志。
