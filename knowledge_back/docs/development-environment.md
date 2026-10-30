# 开发环境说明

> 2026-10-30 更新：已加入 MinIO 知识库文件对象存储、文档版本、预览下载、在线文本编辑和 PostgreSQL 索引 Worker。新环境使用根目录 `init.sql` 初始化数据库；前后端启动步骤以 [根目录 README](../../README.md) 为准，完整安装命令见 [install.md](../../install.md)。

## 1. 环境划分

项目分为本地开发环境和服务器开发环境，采用前后端分离结构。前端项目目录为 `knowledge_front`，后端项目目录为 `knowledge_back`。两套环境使用相同的服务边界：Vue 前端、Flask API、PostgreSQL + pgvector、MinIO、异步索引 Worker、DeepSeek API 和阿里云百炼 Embedding API。环境差异通过环境变量、网络绑定、数据目录和密钥管理区分。

当前仓库提供的是本地容器启动命令和服务器部署建议。服务器需要由部署人员在目标主机上执行，仓库本身不包含服务器密钥。

当前仓库使用 `kbs-postgres` 和 `kbs-minio` 两个独立容器。PostgreSQL 使用 pgvector 镜像，MinIO 使用 AIStor 镜像；两者均按 [install.md](../../install.md) 的命令启动。

本次配置后的状态：

| 组件 | 状态 |
|---|---|
| PostgreSQL 16 + pgvector | 已启动，`127.0.0.1:5432`，数据库用户 `root` |
| MinIO AIStor | 已启动，`127.0.0.1:9000` API、`127.0.0.1:9001` Console |
| 阿里云百炼 Embedding | 云服务配置完成，不需要本地模型容器 |
| DeepSeek Chat | 云服务配置完成 |

## 2. 本地开发环境

### 2.1 本地文档目录

知识库文件导入目录固定为：

```text
/home/yigeoooo/文档/knowledge_doc
```

该目录作为本地导入来源。后端读取文件后，将原文件写入 MinIO，并在 PostgreSQL 中登记文档元数据。不要把该目录的绝对路径直接作为数据库中的文档路径；数据库保存 MinIO 的 `bucket` 和 `object_key`。

目录不存在时创建：

```bash
mkdir -p /home/yigeoooo/文档/knowledge_doc
```

### 2.2 本地服务

PostgreSQL 和 MinIO 使用独立 Docker 容器启动，完整安装和初始化命令见 [install.md](../../install.md)：

| 服务 | 地址 | 用途 |
|---|---|---|
| PostgreSQL + pgvector | `127.0.0.1:5432` | 业务数据和向量检索 |
| MinIO API | `127.0.0.1:9000` | 原始 Markdown 对象存储 |
| MinIO Console | `http://127.0.0.1:9001` | 本地对象管理 |

许可证文件必须存在于 `knowledge_back/docs/minio.license`，该文件已加入 `.gitignore`，不得提交到仓库。

查看状态：

```bash
docker ps --filter name=kbs-postgres --filter name=kbs-minio
```

停止 MinIO：

```bash
docker stop kbs-minio
```

删除 MinIO 容器不会删除项目 `.runtime/minio-data` 中的数据；删除该目录才会清除对象数据。

删除 `kbs_postgres_data` 或 MinIO 数据目录是破坏性操作，只能在确认不需要本地数据时执行。

### 2.3 pgvector 验证

执行根目录 `init.sql` 初始化数据库时会启用 `vector` 和 `pgcrypto` 扩展。验证命令：

```bash
docker exec kbs-postgres psql -U root -d knowledge_db \
  -c "SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pgcrypto');"
```

验证 MinIO API：

```bash
curl -fsS http://127.0.0.1:9000/minio/health/live
```

AIStor Console 地址为 `http://127.0.0.1:9001`。后端使用 `.env.local` 中的 `MINIO_ENDPOINT`、`MINIO_ACCESS_KEY` 和 `MINIO_SECRET_KEY` 访问对象存储。`MINIO_BUCKET` 作为历史对象的兼容桶保留；创建知识库时会自动创建以知识库 UUID 派生的独立 Bucket，文档版本的 `minio_bucket` 保存实际使用的桶名。

### 2.4 DeepSeek 和阿里云百炼配置

DeepSeek 对话模型使用 OpenAI 兼容接口：

```text
Base URL: https://api.deepseek.com
API Key: DEEPSEEK_API_KEY
```

密钥只放在本地 `.env.local` 或私有交接文档中。Flask 后端读取环境变量，前端不得接触密钥。

DeepSeek 只负责最终答案生成。Embedding 使用阿里云百炼的 `dashscope.MultiModalEmbedding.call`：

```text
Base URL: https://llm-f9r7idf9omepz6cl.cn-beijing.maas.aliyuncs.com/api/v1
Model: qwen3-vl-embedding
Input: [{"text": "..."}]
API Key: DASHSCOPE_API_KEY
```

图片和视频使用同一个接口，将输入项改为 `[{"image": "https://..."}]` 或
`[{"video": "https://..."}]`。本项目 Worker 会为 MinIO 对象生成短时预签名 URL，
因此 `MINIO_PUBLIC_ENDPOINT` 必须是 DashScope 服务可以访问的地址；`127.0.0.1` 只适合浏览器本机访问，不能作为云服务读取媒体的地址。
文字查询仍使用 `[{"text": "..."}]`，模型返回的向量可以和图片、视频向量直接计算相似度。
如果使用自建部署或 MaaS 网关，请将该网关实际的多模态 Embedding 路径配置到
`DASHSCOPE_EMBEDDING_URL`；默认路径只适用于标准 DashScope API。

调用方式：

```python
import os
import dashscope

dashscope.base_http_api_url = os.environ["DASHSCOPE_BASE_URL"]
response = dashscope.MultiModalEmbedding.call(
    model=os.environ["DASHSCOPE_EMBEDDING_MODEL"],
    input=[{"text": "通用多模态表征模型示例"}],
    api_key=os.environ["DASHSCOPE_API_KEY"],
)
```

文档和问题必须使用同一个百炼模型和向量维度。`qwen3-vl-embedding` 的实际向量维度以接口返回结果为准，首次调用必须记录并校验维度，再创建 PostgreSQL `vector(n)` 列。Embedding 请求失败时，索引任务进入 `FAILED`，不能使用 DeepSeek Chat 的文本结果替代向量。

## 3. 服务器开发环境

### 3.1 推荐部署结构

服务器上使用 Docker 或 systemd 管理以下服务：

```text
Nginx/Caddy
    ↓
Vue 静态文件 + Flask API
    ↓
PostgreSQL + pgvector
MinIO
异步 Worker
```

PostgreSQL、MinIO 和 Worker 只绑定内网或 Docker 网络。公网只暴露 Nginx/Caddy 的 HTTPS 端口。MinIO Console 不应直接暴露公网。

### 3.2 服务器配置

1. 复制 `.env.server.example` 到服务器的私密配置位置。
2. 将 `LOCAL_DOCUMENT_DIR` 改为服务器实际的挂载目录，例如 `/srv/knowledge-management/documents`。
3. 使用强随机 PostgreSQL、MinIO 和 JWT 密钥。
4. `DEEPSEEK_API_KEY` 只注入 Flask 和 Worker 容器。
5. PostgreSQL 和 MinIO 数据目录使用持久化磁盘。
6. 配置 PostgreSQL 备份和 MinIO 对象备份。
7. 服务器发布前执行数据库迁移、pgvector 扩展检查和健康检查。

### 3.3 服务器与本地的差异

| 项目 | 本地 | 服务器 |
|---|---|---|
| 访问范围 | 绑定 `127.0.0.1` | 通过 HTTPS 反向代理访问 |
| 数据 | PostgreSQL Docker volume；MinIO `/home/yigeoooo/minio/data` | 独立持久化磁盘和备份 |
| 文档目录 | `/home/yigeoooo/文档/knowledge_doc` | 服务器挂载目录 |
| MinIO Console | 可本地访问 | 仅内网或管理员通道 |
| 密钥 | `.env.local` 和私有文档 | Secret 管理器或服务器私有文件 |
| 日志 | 本地容器日志 | 集中日志和告警 |

## 4. 启动检查清单

后端启动时应检查：

1. PostgreSQL 可以连接。
2. `vector` 扩展存在。
3. MinIO endpoint 可以访问。
4. 使用 root 凭据访问 MinIO，配置的 bucket 存在或可以创建。
5. `LOCAL_DOCUMENT_DIR` 存在且后端有读取权限。
6. DeepSeek Base URL 和 Chat API Key 已配置。
7. DeepSeek Chat 和阿里云百炼 Embedding 配置完整；Embedding 服务不可用时，索引服务应处于失败状态并给出明确错误。

