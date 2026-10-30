# DEXFORCE 智能知识库平台

Vue 3 + Element Plus 前端和 Flask 后端组成的知识库管理系统，支持 PostgreSQL + pgvector、MinIO AIStor、文档索引和基于文档的问答。

## 安装依赖和初始化

首次使用请按 [install.md](./install.md) 完成 PostgreSQL、pgvector、MinIO、后端环境变量和项目依赖配置。

## 启动后端

在项目根目录打开终端，执行：

```bash
cd knowledge_back
uv sync --locked
uv run flask --app app run --host 127.0.0.1 --port 5000
```

后端 API 地址：`http://127.0.0.1:5000/api/v1`

健康检查：`http://127.0.0.1:5000/api/v1/health`

## 启动前端

另开一个终端，在项目根目录执行：

```bash
cd knowledge_front
npm ci
npm run dev -- --host 0.0.0.0
```

浏览器访问：<http://127.0.0.1:5173/>

前端通过 Vite 将 `/api` 请求代理到本地 Flask 服务，因此前后端都按上面的默认端口启动即可。
