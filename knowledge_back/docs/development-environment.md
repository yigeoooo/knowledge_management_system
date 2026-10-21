# 开发环境说明

> 2026-10-21 更新：Flask 认证与只读管理 API、Vue 首页/登录及全部页面框架已实现。新环境使用根目录 `init.sql` 初始化数据库，前后端启动步骤以 [根目录 README](../../README.md) 为准。以下保留 PostgreSQL、MinIO 和云模型服务的详细环境约定。

## 1. 环境划分

项目分为本地开发环境和服务器开发环境，采用前后端分离结构。前端项目目录为 `knowledge_front`，后端项目目录为 `knowledge_back`。两套环境使用相同的服务边界：Vue 前端、Flask API、PostgreSQL + pgvector、MinIO、异步索引 Worker、DeepSeek API 和阿里云百炼 Embedding API。环境差异通过环境变量、网络绑定、数据目录和密钥管理区分。

当前仓库提供的是本地容器编排文件和服务器部署模板。服务器需要由部署人员在目标主机上执行，仓库本身不包含服务器密钥。

当前仓库已经启动本机 PostgreSQL + pgvector 容器 `kbs-postgres`，并通过 AIStor 镜像单独启动了 `kbs-minio`。MinIO 不由 PostgreSQL Compose 文件管理，避免 Compose 与已存在的 AIStor 容器冲突。

本次配置后的状态：

| 组件 | 状态 |
|---|---|
| PostgreSQL 16 + pgvector | 已启动，`127.0.0.1:5432`，数据库用户 `root` |
| MinIO AIStor | 已启动，`127.0.0.1:9000` API、`127.0.0.1:9001` Console |
| 阿里云百炼 Embedding | 云服务配置完成，不需要本地模型容器 |
| DeepSeek Chat | 云服务配置完成 |

## 2. 本地开发环境

### 2.1 本地文档目录

Markdown 文档导入目录固定为：

```text
/home/yigeoooo/文档/knowledge_doc
```

该目录作为本地导入来源。后端读取文件后，将原文件写入 MinIO，并在 PostgreSQL 中登记文档元数据。不要把该目录的绝对路径直接作为数据库中的文档路径；数据库保存 MinIO 的 `bucket` 和 `object_key`。

目录不存在时创建：

```bash
mkdir -p /home/yigeoooo/文档/knowledge_doc
```

### 2.2 本地服务

`docker-compose.local.yml` 提供 PostgreSQL + pgvector。MinIO 使用 AIStor 镜像单独启动：

| 服务 | 地址 | 用途 |
|---|---|---|
| PostgreSQL + pgvector | `127.0.0.1:5432` | 业务数据和向量检索 |
| MinIO API | `127.0.0.1:9000` | 原始 Markdown 对象存储 |
| MinIO Console | `http://127.0.0.1:9001` | 本地对象管理 |

启动：

```bash
cd knowledge_back
docker compose --env-file .env.local -f docker-compose.local.yml up -d
```

启动或重建 MinIO（AIStor）：

```bash
cd knowledge_back
mkdir -p /home/yigeoooo/minio/data
docker pull quay.io/minio/aistor/minio:latest
docker rm -f kbs-minio 2>/dev/null || true
set -a
. .env.local
set +a
docker run -dt \
  -e MINIO_ROOT_USER="$MINIO_ACCESS_KEY" \
  -e MINIO_ROOT_PASSWORD="$MINIO_SECRET_KEY" \
  -p 9000:9000 -p 9001:9001 \
  -v /home/yigeoooo/project/knowledge_management_system/knowledge_back/docs/minio.license:/minio.license \
  -v /home/yigeoooo/minio/data:/mnt/data \
  --name kbs-minio \
  quay.io/minio/aistor/minio:latest \
  server /mnt/data --license /minio.license --console-address ":9001"
```

许可证文件必须存在于：

```text
/home/yigeoooo/project/knowledge_management_system/knowledge_back/docs/minio.license
```

该许可证文件已加入 `.gitignore`，不得提交到仓库。MinIO 数据持久化目录为 `/home/yigeoooo/minio/data`。

查看状态：

```bash
cd knowledge_back
docker compose --env-file .env.local -f docker-compose.local.yml ps
```

停止服务：

```bash
cd knowledge_back
docker compose --env-file .env.local -f docker-compose.local.yml down
```

停止 MinIO：

```bash
docker stop kbs-minio
```

删除 MinIO 容器不会删除 `/home/yigeoooo/minio/data` 中的数据；删除该目录才会清除对象数据。

停止并删除 PostgreSQL 数据卷是破坏性操作，只能在确认不需要本地数据库数据时执行。该命令不会删除 MinIO 数据：

```bash
cd knowledge_back
docker compose --env-file .env.local -f docker-compose.local.yml down -v
```

如需清空 MinIO 对象，必须在确认数据不再需要后单独删除 `/home/yigeoooo/minio/data`。

### 2.3 pgvector 验证

首次创建 PostgreSQL 容器时，`docker/postgres/init/001-enable-extensions.sql` 会启用 `vector` 和 `pgcrypto` 扩展。验证命令：

```bash
docker exec kbs-postgres psql -U root -d knowledge_db \
  -c "SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pgcrypto');"
```

如果数据库卷已经存在，初始化脚本不会再次执行，可以手动执行：

```bash
docker exec kbs-postgres psql -U root -d knowledge_db \
  -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pgcrypto;"
```

验证 MinIO API：

```bash
curl -fsS http://127.0.0.1:9000/minio/health/live
```

AIStor Console 地址为 `http://127.0.0.1:9001`。后端使用 `.env.local` 中的 `MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY` 和 `MINIO_BUCKET` 访问对象存储。

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

服务器上使用 Docker Compose 或 systemd 管理以下服务：

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

