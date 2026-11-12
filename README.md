# DEXFORCE 智能知识库平台

Vue 3 + Element Plus 前端和 Flask 后端组成的知识库管理系统，支持 PostgreSQL + pgvector、MinIO AIStor、文档索引和基于文档的问答。

支持独立会话记忆、历史续问与软删除，管理员按用户或机器人查看完整对话，并可导出排版后的 Word 会话记录。机器人绑定知识库后，通过首问和续问两个接口发送请求、等待最终答案，无需轮询；模型适配使用 LangChain，问答流程使用 LangGraph。详见 [会话架构](knowledge_back/docs/conversation-design.md) 和 [机器人接口](knowledge_back/docs/robot-conversation-api.md)。

管理员可在“机器人问答”（`/robot-qa`）选择机器人，直接测试首问、连续追问、新对话和历史会话。页面调用实际机器人接口，答案为简洁的单段纯文本，测试记录归属所选机器人，可在问答日志中查看。

## 安装依赖和初始化

首次使用请按 [install.md](./install.md) 完成 PostgreSQL、pgvector、MinIO、后端环境变量和项目依赖配置。

## 启动后端

在项目根目录打开终端，执行：

```bash
cd knowledge_back
uv sync --locked
uv run flask --app app db upgrade
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

RAG v2 使用 LangChain 文档与检索接口、结构化模型输出和 LangGraph 多阶段流程。问答日志可逐轮查看 LangSmith 处理流程，采用居中详情弹窗，支持本地诊断回退。配置、记忆边界、索引升级和评测命令见 [RAG 架构与运行](knowledge_back/docs/rag-architecture.md)。

### 提示词与质量评测

管理员新增“提示词管理”和“质量评测”页面，支持数据库版本管理、草稿试测、人工标注、同题对比和发布回退。详见 [操作说明](knowledge_back/docs/prompt-evaluation-guide.md)。升级执行 `uv run flask --app app db upgrade` 并重启后端；生产环境增加 `uv run flask --app app evaluation-worker`。
