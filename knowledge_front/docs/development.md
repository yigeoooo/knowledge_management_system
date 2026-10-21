# knowledge_front 前端开发说明

## 1. 项目职责

`knowledge_front` 是知识库管理系统的 Vue 3 前端项目，使用 Element Plus，负责：

- 用户登录、退出和登录状态维护
- 根据后端返回的页面权限动态创建路由和菜单
- 普通用户的知识库问答页面
- 超级管理员的知识库、文档、机器人、用户、角色和页面权限管理
- 网页提问测试和答案来源展示

前端不保存 PostgreSQL、MinIO、DeepSeek 或阿里云百炼的密钥。所有密钥只由 `knowledge_back` 使用。

## 2. 本地运行约定

后端 API 默认地址：

```text
http://127.0.0.1:5000/api/v1
```

建议使用前端环境变量配置：

```text
VITE_API_BASE_URL=http://127.0.0.1:5000/api/v1
```

前端通过 Vite 代理或后端 CORS 访问 Flask API。生产环境将 API 地址改为 HTTPS 域名，不把服务端密钥放入 `VITE_*` 变量。

## 3. 登录和动态路由

1. 登录页调用 `POST /auth/login`。
2. 保存短期 `access_token`，刷新令牌按后端约定保存。
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
- `/ask`
- `/profile`

超级管理员额外页面：

- `/dashboard`
- `/knowledge-bases`
- `/documents`
- `/robots`
- `/users`
- `/roles`
- `/pages`
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
  "top_k": 5,
  "stream": false,
  "request_id": "web-req-001"
}
```

页面需要展示：

- 问题和答案
- 加载状态
- 检索来源文档、版本、标题路径和文本片段
- 没有检索依据时的明确提示
- 超时、登录失效和模型服务失败提示

## 6. 管理页面

超级管理员页面调用 Flask 管理接口完成数据修改。上传文件时，前端先请求预签名地址，然后上传到 MinIO，最后调用上传完成接口触发索引任务。前端不直接使用 MinIO Access Key。

文档修改应按新版本提交；文档删除、知识库停用、机器人停用和用户停用都需要显示二次确认，并在操作完成后刷新后端状态。

