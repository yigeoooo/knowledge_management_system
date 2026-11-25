# knowledge_front 前端开发说明

## 1. 项目职责

`knowledge_front` 是知识库管理系统的 Vue 3 前端项目，使用 Element Plus，负责：

- 用户登录、退出和登录状态维护
- 根据后端返回的页面权限动态创建路由和菜单
- 知识问答页面和答案来源展示
- 超级管理员的知识库、文档、机器人、用户、角色和页面权限管理

前端不保存 PostgreSQL、MinIO、DeepSeek 或阿里云百炼的密钥。所有密钥只由 `knowledge_back` 使用。

## 2. 本地运行约定

后端 API 默认地址：

```text
http://127.0.0.1:5000/api/v1
```

建议使用前端环境变量配置：

```text
VITE_API_BASE_URL=/api/v1
```

当前前端通过 Vite 的 `/api` 代理访问 `http://127.0.0.1:5000`，无需 CORS。生产环境也应采用同源 HTTPS 反向代理，不把服务端密钥放入 `VITE_*` 变量。启动步骤见项目根目录 [README](../../README.md)。

## 3. 登录和动态路由

1. 公开首页为 `/`，点击登录入口进入 `/login`，调用 `POST /auth/login`。
2. 短期 `access_token` 仅保存在内存。刷新令牌由后端写入 HttpOnly、SameSite=Strict Cookie；非本地环境启用 Secure。刷新接口要求 JSON 请求体，刷新时轮换 Cookie。
3. 根据响应中的 `pages` 数组动态创建路由和菜单。
4. 路由守卫在进入页面前检查登录状态和页面路由。
5. API 返回 401 时尝试刷新令牌；刷新失败则清理状态并返回登录页。
6. API 返回 403 时进入无权限页面。

后端页面数据示例：

```json
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
```

前端根据 `component_key` 映射本地组件。组件映射表必须由前端维护，不能直接把后端返回的任意字符串当作可执行代码。

## 4. 页面范围

普通用户页面：

- `/login`
- `/qa`
- `/profile`

超级管理员额外页面：

- `/dashboard`
- `/knowledge-bases`
- `/create-document`
- `/documents`
- `/robots`
- `/users`
- `/roles`
- `/pages`
- `/role-permissions`
- `/qa-logs`
- `/audit-logs`

页面列表以数据库 `pages` 表和登录接口返回结果为准。上面的路径是推荐初始路由，不是绕过后端权限的安全机制。

工作台的快捷入口、统计卡片及知识问答按钮根据当前 `session.pages` 生成，只展示已授权、可见且已注册的页面；不展示按钮资源和隐藏页面。快捷入口按页面排序，移除平台建设进度。`GET /dashboard` 校验当前角色的工作台权限，只返回已授权页面对应的统计字段；`super_admin` 直接放行，其他角色未获工作台授权时返回 403。

## 5. 网页提问

前端提问接口：

```text
POST /api/v1/web/query
Authorization: Bearer <access_token>
```

请求内容：

```json
{
  "knowledge_base_id": "kb-uuid",
  "question": "如何部署系统？",
  "request_id": "web-req-001"
}
```

页面需要展示：

- 问题和答案
- 加载状态
- 检索来源文档、版本、标题路径和文本片段
- 没有检索依据时的明确提示
- 超时、登录失效和模型服务失败提示

进入页面和切换知识库时，调用 `POST /api/v1/web/suggested-questions`，请求只含 `knowledge_base_id`。展示返回的最多三个 `questions`，点击后填入输入框并保留该项的 `suggestion_token`，提交时携带该凭据以保留原始来源；编辑问题后清除凭据。加载期间显示骨架，失败提供重试，空知识库不使用写死问题补位。

问答为单轮非流式；答案及右侧来源通过共享的 Markdown 渲染器及 DOMPurify 展示，保留编号引用。网络错误重试复用 `request_id`，同一请求不会重复写日志；收到结果后主动再次发送使用新编号。推荐超时为 120 秒，问答超时为 300 秒（含服务端生成、审阅及最多一次纠正）；切换知识库或离开页面取消当前请求并丢弃迟到响应。根据 `answer_status` 显示正常回答、`partial` 部分有依据、`insufficient_evidence` 资料不足或 `sources_only` 相关资料；不把这些状态当作红色服务错误。

## 6. 管理页面

获得对应页面权限的角色调用 Flask 管理接口完成数据修改。`super_admin` 自动获得全部启用页面及对应接口权限；其他角色由后端逐次校验角色页面授权。知识库页面支持创建、编辑、停用和归档；创建成功后，若同时获得文档管理页面权限，可直接进入该知识库的文档管理页面。文档必须先选择所属知识库；上传 Markdown、TXT、PDF、Word、图片或视频时，前端先请求预签名地址，然后上传到 MinIO，最后调用上传完成接口触发索引任务。预签名上传失败时使用同源回退接口。前端不直接使用 MinIO Access Key。Markdown/TXT 可在线编辑并保存为新版本，DOCX 上传后保留原始文件用于下载，并由 `/text-preview` 转换为安全富文本 HTML 展示标题、字体、颜色、列表和表格；其他类型通过上传新版本更新。问答页面调用 `/web/query` 获取回答及来源；`/web/search` 保留为纯检索接口。

文档修改应按新版本提交；文档删除、知识库停用、机器人停用和用户停用都需要显示二次确认，并在操作完成后刷新后端状态。

`/robots` 使用独立的 `RobotManagementView.vue`，支持序列号或名称搜索、状态筛选、分页、注册、详情、编辑、启用／停用。机器人 DELETE 接口采用停用语义，保留机器人记录和问答日志关联；重新启用通过编辑表单将状态改为启用。所有机器人管理接口按机器人管理页面权限校验，序列号由后端保证唯一。

状态筛选的清空值统一为 `''`（`value-on-clear=""`），列表请求使用 `lib/query.ts` 的 `queryParams`，省略空字符串、`undefined` 和 `null` 参数。未选择状态时查询当前权限和其他条件范围内的全部状态；选择后按该状态查询。后端列表接口兼容空白及旧客户端序列化的 `status=undefined`／`status=null`，均按未筛选处理；已有状态枚举校验继续生效。

## 7. 用户管理（已接入）

`/users` 使用独立的 `UsersView.vue`，提供新增／编辑弹窗、用户详情抽屉、启用状态开关、删除确认和分页查询。筛选条件 `q`（显示名称包含查询）与 `status`（`active`／`disabled`）可同时使用，后端执行搜索和分页。列表、详情均不返回密码字段。

新增用户必须设置密码；编辑时新密码留空表示保留。修改身份、权限或密码会撤销原会话，修改当前登录用户的用户名或密码会返回登录页。删除采用 `deleted` 状态保留历史关联，界面不再展示此账号；删除末页最后一条记录时会自动返回仍有数据的页码。

Root 和当前登录账号的状态、角色、删除操作由前后端共同保护；Root 用户名固定。用户管理 API 见后端需求文档和根目录 README。

## 8. 角色管理（已接入）

`/roles` 使用独立的角色管理页面，支持按名称或编码分页查询、新增、编辑、切换系统／自定义类型、启用／停用和删除。角色编码唯一，编辑角色的编码、名称或类型不受当前用户数影响；停用角色会使该角色下的用户无法登录。`super_admin` 角色的关键字段受保护，仍被用户使用的角色不能删除。角色写接口要求角色管理页面权限，角色页面权限配置页可读取角色选项；`super_admin` 直接放行。

`/role-permissions` 支持选择角色并勾选页面访问权限，点击保存后通过 `PUT /roles/{id}/pages` 覆盖该角色的授权。接口会校验页面 ID、拒绝重复资源并写入审计日志；`super_admin` 必须保留全部启用页面权限。相关用户刷新或重新登录后获得新的页面列表。

`/qa-logs` 的每条问答记录都可以打开居中的详情对话框，查看历史问题、回答、状态、知识库、模型、耗时、召回数量和引用资料。机器人详情、用户详情等信息展示统一使用 Dialog，不使用右侧抽屉。

问答日志支持按“全部来源 / 网页（WEB）/ 机器人（ROBOT）”筛选，可与问题关键词组合查询；切换或清除来源时回到第一页。列表和详情的“提问人”使用后端 `requester_name`：网页提问显示用户显示名称，机器人提问显示机器人名称（未命名时显示序列号），关联记录缺失时显示“未知用户 / 未知机器人”。来源通过 `GET /api/v1/qa-logs?source_type=WEB` 或 `source_type=ROBOT` 在后端过滤，分页总数同样按筛选结果计算。

问答页面和历史详情共用 `MarkdownContent.vue` 渲染答案和 Markdown 引用，支持标题、列表、表格与代码块，并通过 DOMPurify 清理 HTML。`SourceContent.vue` 按文件类型展示引用，PDF、TXT 和旧版 DOC 提取文本保留换行；DOCX 优先使用 `content_html`，由 `WordContent.vue` 通过 DOMPurify 及 CSS 属性白名单展示；无富文本时回退到原引用文字。PDF 中由字体映射产生的控制字符和兼容汉字由后端统一清理，新索引及历史引用均适用，无需重新上传文件。

审计日志使用后端返回的 `user_name` 展示“操作人”，不在表格中展示用户 ID。名称取用户的显示名称，缺失时使用用户名；无关联用户的系统操作显示“系统”，逻辑删除用户的历史操作仍保留姓名。

## 9. 创建文档

`/create-document` 使用 `CreateDocumentView.vue`，组件标识为 `DocumentCreate`，页面编码为 `document_create`。页面由角色授权控制，支持 Markdown 分栏编辑与预览，以及基于 Tiptap 的 Word 可视化编辑。保存调用 `POST /documents/create`；请求格式为 `{ knowledge_base_id, title, format, content, request_id }`，其中 `format` 为 `md` 或 `docx`，`content` 分别为 Markdown 字符串或 Tiptap JSON 文档。服务端生成真实文件，复用现有上传完成校验、MinIO 存储、索引任务和审计流程。

保存后通过 `GET /documents/created/{id}` 查询本人文档的处理状态，不需要文档管理权限；其他人的文档不会通过此接口暴露。相同内容的重试复用 UUID 请求编号，输入变化后使用新编号。草稿按用户保存在 `sessionStorage`，保存成功后清除；正文限制 200,000 字符。格式切换需确认清空正文，离开时提示未保存内容。Word 普通表格支持增行、增列和删除，支持合并单元格。


### 已有 Word 文档编辑与引用（2026-10-28）

`DocumentManagementView.vue` 对 DOCX 展示“在线编辑”，按所选版本调用 `GET /documents/{id}/word-content?version_id=...` 获取 Tiptap JSON，复用 `WordEditor.vue`。保存调用 `POST /documents/{id}/word-content`，提交 `{ base_version_id, content, request_id }`，成功返回新版本并重新加载预览。保存失败保留编辑器，未改变内容的重试复用 request_id；编辑时禁止切换版本和上传替换，取消、关闭和离开会检查未保存改动。

DOCX 详情和 Word 引用共享 `WordContent.vue` 的清理和格式样式。`content_html` 仅用于显示；答案、检索和日志原始引用文本继续使用 content。后端以引用 version_id 从对象存储恢复格式，历史日志不会被最新文档替换。

验证：后端 `tests/test_word_editing.py`、`tests/test_word_citations.py`；浏览器 `tests/word-editing.spec.ts` 会启动隔离 Flask/SQLite 服务，使用真实 DOCX 导入导出、保存、索引和下载接口，存储及 Embedding 使用测试替身。`tests/dashboard-and-log-rendering.spec.ts` 检查两个引用页面的格式和 HTML 清理。后端虚拟环境需先安装开发依赖，测试服务不连接业务数据库和 MinIO。


文档列表返回 `max_file_size`（字节），默认 209715200；文件选择和替换版本入口用此值校验，并显示上限。知识库/文档列表及详情返回 `created_by_name`、`updated_by_name`，列表两列显示用户显示名称，缺失时显示 `—`。
