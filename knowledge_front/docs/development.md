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
- `/documents`
- `/robots`
- `/users`
- `/roles`
- `/pages`
- `/role-permissions`
- `/qa-logs`
- `/audit-logs`

页面列表以数据库 `pages` 表和登录接口返回结果为准。上面的路径是推荐初始路由，不是绕过后端权限的安全机制。

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

超级管理员页面调用 Flask 管理接口完成数据修改。知识库页面支持创建、编辑、停用和归档；创建成功后可直接进入该知识库的文档管理页面。文档必须先选择所属知识库；上传 Markdown、TXT、PDF、Word、图片或视频时，前端先请求预签名地址，然后上传到 MinIO，最后调用上传完成接口触发索引任务。预签名上传失败时使用同源回退接口。前端不直接使用 MinIO Access Key。Markdown/TXT 可在线编辑并保存为新版本，其他类型通过上传新版本更新。问答页面调用 `/web/query` 获取回答及来源；`/web/search` 保留为纯检索接口。

文档修改应按新版本提交；文档删除、知识库停用、机器人停用和用户停用都需要显示二次确认，并在操作完成后刷新后端状态。

`/robots` 使用独立的 `RobotManagementView.vue`，支持序列号或名称搜索、状态筛选、分页、注册、详情、编辑、启用／停用。机器人 DELETE 接口采用停用语义，保留机器人记录和问答日志关联；重新启用通过编辑表单将状态改为启用。所有管理接口仅允许超级管理员访问，序列号由后端保证唯一。

状态筛选的清空值统一为 `''`（`value-on-clear=""`），列表请求使用 `lib/query.ts` 的 `queryParams`，省略空字符串、`undefined` 和 `null` 参数。未选择状态时查询当前权限和其他条件范围内的全部状态；选择后按该状态查询。后端列表接口兼容空白及旧客户端序列化的 `status=undefined`／`status=null`，均按未筛选处理；已有状态枚举校验继续生效。

## 7. 用户管理（已接入）

`/users` 使用独立的 `UsersView.vue`，提供新增／编辑弹窗、用户详情抽屉、启用状态开关、删除确认和分页查询。筛选条件 `q`（显示名称包含查询）与 `status`（`active`／`disabled`）可同时使用，后端执行搜索和分页。列表、详情均不返回密码字段。

新增用户必须设置密码；编辑时新密码留空表示保留。修改身份、权限或密码会撤销原会话，修改当前登录用户的用户名或密码会返回登录页。删除采用 `deleted` 状态保留历史关联，界面不再展示此账号；删除末页最后一条记录时会自动返回仍有数据的页码。

Root 和当前登录账号的状态、角色、删除操作由前后端共同保护；Root 用户名固定。用户管理 API 见后端需求文档和根目录 README。

## 8. 角色管理（已接入）

`/roles` 使用独立的角色管理页面，支持按名称或编码分页查询、新增、编辑、切换系统／自定义类型、启用／停用和删除。角色编码唯一，编辑角色的编码、名称或类型不受当前用户数影响；停用角色会使该角色下的用户无法登录。`super_admin` 角色的关键字段受保护，仍被用户使用的角色不能删除。角色接口由后端超级管理员权限统一保护。

`/role-permissions` 支持选择角色并勾选页面访问权限，点击保存后通过 `PUT /roles/{id}/pages` 覆盖该角色的授权。接口会校验页面 ID、拒绝重复资源并写入审计日志；`super_admin` 必须保留全部启用页面权限。相关用户刷新或重新登录后获得新的页面列表。

