# 安装、初始化与基础配置

本文用于本地准备完整运行环境。命令默认在项目根目录执行，数据库和 MinIO 使用 Docker 单容器运行，整个流程不使用 Docker Compose。

文档中的 CHANGE_ME_POSTGRES_PASSWORD、CHANGE_ME_MINIO_ROOT_PASSWORD、CHANGE_ME_JWT_SECRET_KEY、CHANGE_ME_DEEPSEEK_API_KEY 和 CHANGE_ME_DASHSCOPE_API_KEY 必须替换成自己的值后再执行。不要把真实密码、API Key 或 MinIO 许可证提交到 Git。

## 0. 准备环境

需要 Docker、Node.js 22 LTS（或 20.19+）、Python 3.11+、Bash 和 uv：

```bash
docker --version
node --version
npm --version
python3 --version
uv --version
```

如果没有 uv，执行：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

进入仓库根目录：

```bash
cd /path/to/knowledge_management_system
export KBS_ROOT="$PWD"
test -f "$KBS_ROOT/init.sql"
```

将 /path/to/knowledge_management_system 替换成实际路径。下面所有命令都从该根目录执行。

## 1. 写入后端配置

复制下面的命令，先把 CHANGE_ME_ 开头的值替换为自己的密码和 API Key，再执行。DASHSCOPE_BASE_URL 和 Embedding 模型是项目当前默认配置；如果使用其他百炼网关，请改成对应地址和模型。

```bash
cat > "$KBS_ROOT/knowledge_back/.env.local" <<'ENV_FILE'
APP_ENV=local
APP_HOST=127.0.0.1
APP_PORT=5000

POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=knowledge_db
POSTGRES_USER=root
POSTGRES_PASSWORD=CHANGE_ME_POSTGRES_PASSWORD

MINIO_ENDPOINT=127.0.0.1:9000
MINIO_PUBLIC_ENDPOINT=127.0.0.1:9000
MINIO_ACCESS_KEY=root
MINIO_SECRET_KEY=CHANGE_ME_MINIO_ROOT_PASSWORD
MINIO_BUCKET=knowledge-documents
MINIO_SECURE=false
MINIO_URL_SECONDS=600

JWT_SECRET_KEY=CHANGE_ME_JWT_SECRET_KEY
MAX_DOCUMENT_SIZE=209715200

DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=CHANGE_ME_DEEPSEEK_API_KEY
DEEPSEEK_CHAT_MODEL=deepseek-chat
DEEPSEEK_TIMEOUT_SECONDS=60
QA_MIN_SIMILARITY=0.3

DASHSCOPE_BASE_URL=https://llm-f9r7idf9omepz6cl.cn-beijing.maas.aliyuncs.com/api/v1
DASHSCOPE_API_KEY=CHANGE_ME_DASHSCOPE_API_KEY
DASHSCOPE_EMBEDDING_MODEL=qwen3-vl-embedding
DASHSCOPE_EMBEDDING_URL=
DASHSCOPE_EMBEDDING_MODE=multimodal
DASHSCOPE_EMBEDDING_DIMENSION=
DASHSCOPE_EMBEDDING_MAX_VIDEO_FRAMES=16
EMBEDDING_PROVIDER=dashscope
INDEX_WORKER_AUTOSTART=true
RATELIMIT_STORAGE_URI=memory://
ENV_FILE

mkdir -p "$KBS_ROOT/.runtime/documents" "$KBS_ROOT/.runtime/minio-data"
chmod 600 "$KBS_ROOT/knowledge_back/.env.local"

if grep -q 'CHANGE_ME_' "$KBS_ROOT/knowledge_back/.env.local"; then
  echo "请先将 .env.local 中的 CHANGE_ME_ 值替换为自己的配置"
  exit 1
fi
```

POSTGRES_PASSWORD 是 PostgreSQL 连接密码；MINIO_ROOT_PASSWORD 是 MinIO Console 和 S3 API 密码；JWT_SECRET_KEY 至少 32 个字符。DeepSeek 用于生成回答，DashScope 用于文档和问题向量化，完整使用文档问答时两个 API Key 都要有效。远程部署时，MINIO_PUBLIC_ENDPOINT 必须改成 DashScope 可以访问的 MinIO 地址。

## 2. 安装 PostgreSQL 16 和 pgvector

加载配置并启动 PostgreSQL。pgvector/pgvector:pg16 已经包含 pgvector 扩展。

```bash
set -a
. "$KBS_ROOT/knowledge_back/.env.local"
set +a

docker pull pgvector/pgvector:pg16
docker volume create kbs_postgres_data

if docker container inspect kbs-postgres >/dev/null 2>&1; then
  docker start kbs-postgres >/dev/null 2>&1 || true
else
  docker run -d \
    --name kbs-postgres \
    --restart unless-stopped \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -p "$POSTGRES_PORT:5432" \
    -v kbs_postgres_data:/var/lib/postgresql/data \
    pgvector/pgvector:pg16
fi
```

等待数据库就绪：

```bash
set -a
. "$KBS_ROOT/knowledge_back/.env.local"
set +a

until docker exec kbs-postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do
  sleep 2
done
```

在空数据库中导入根目录的 init.sql。脚本会创建 vector、pgcrypto、业务表、权限、默认知识库和 Root 管理员。

```bash
set -a
. "$KBS_ROOT/knowledge_back/.env.local"
set +a

SCHEMA_STATE="$(docker exec kbs-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
  "SELECT to_regclass('public.alembic_version')" | tr -d '[:space:]')"

if [ "$SCHEMA_STATE" = "alembic_version" ]; then
  echo "数据库已经初始化，跳过 init.sql"
else
  docker exec -i kbs-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -v ON_ERROR_STOP=1 < "$KBS_ROOT/init.sql"
fi
```

验证扩展：

```bash
set -a
. "$KBS_ROOT/knowledge_back/.env.local"
set +a

docker exec kbs-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pgcrypto') ORDER BY extname;"
```

init.sql 只用于空数据库。已有业务数据库不要重复导入，也不要删除 kbs_postgres_data 数据卷来重试。

## 3. 安装并配置 MinIO AIStor

有效 AIStor 许可证必须提前保存到 knowledge_back/docs/minio.license。该文件已被 Git 忽略。如果许可证放在其他位置，将下面 MINIO_LICENSE 改成实际绝对路径。

```bash
set -a
. "$KBS_ROOT/knowledge_back/.env.local"
set +a

MINIO_LICENSE="$KBS_ROOT/knowledge_back/docs/minio.license"
test -s "$MINIO_LICENSE" || {
  echo "缺少 MinIO 许可证：请将有效许可证保存到 $MINIO_LICENSE"
  exit 1
}

docker pull quay.io/minio/aistor/minio:latest
mkdir -p "$KBS_ROOT/.runtime/minio-data"

if docker container inspect kbs-minio >/dev/null 2>&1; then
  docker start kbs-minio >/dev/null 2>&1 || true
else
  docker run -dt \
    --name kbs-minio \
    --restart unless-stopped \
    -e MINIO_ROOT_USER="$MINIO_ACCESS_KEY" \
    -e MINIO_ROOT_PASSWORD="$MINIO_SECRET_KEY" \
    -p 9000:9000 \
    -p 9001:9001 \
    -v "$MINIO_LICENSE:/minio.license:ro" \
    -v "$KBS_ROOT/.runtime/minio-data:/mnt/data" \
    quay.io/minio/aistor/minio:latest \
    server /mnt/data \
    --license /minio.license \
    --console-address ":9001"
fi
```

等待 MinIO API 就绪：

```bash
set -a
. "$KBS_ROOT/knowledge_back/.env.local"
set +a

until curl -fsS http://127.0.0.1:9000/minio/health/live >/dev/null; do
  sleep 2
done
docker logs --tail 40 kbs-minio
```

访问地址：

| 地址 | 用途 |
| --- | --- |
| http://127.0.0.1:9000 | S3 API，后端使用 |
| http://127.0.0.1:9001 | AIStor Console，浏览器管理 |

登录用户名是 root，密码是 .env.local 中的 MINIO_ROOT_PASSWORD。后端会在创建知识库或上传文档时自动创建对应 Bucket，MINIO_BUCKET=knowledge-documents 用于历史对象兼容。

### MinIO 许可证管理

容器启动参数 --license /minio.license 会加载许可证。可以使用临时 MinIO Client 容器查看状态，Linux 主机执行：

```bash
set -a
. "$KBS_ROOT/knowledge_back/.env.local"
set +a

mc_kbs() {
  docker run --rm --network host minio/mc:latest "$@"
}

mc_kbs alias set kbs http://127.0.0.1:9000 "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"
mc_kbs mb --ignore-existing kbs/knowledge-documents
mc_kbs license info kbs
```

许可证注册、续期和恢复按官方文档执行：

```bash
mc_kbs() {
  docker run --rm --network host minio/mc:latest "$@"
}

mc_kbs license register kbs
mc_kbs license update kbs
mc_kbs admin config set kbs subnet "license=<LICENSE_TOKEN>"
mc_kbs license info kbs
```

将 <LICENSE_TOKEN> 换成实际 Token，不能把 Token 或许可证文件写入仓库。详见 [MinIO AIStor 许可证文档](https://docs.min.io/aistor/operations/licenses/)。

## 4. 安装前后端依赖

```bash
cd "$KBS_ROOT/knowledge_back"
uv sync --locked

cd "$KBS_ROOT/knowledge_front"
npm ci
```

## 5. 启动服务

后端和前端各使用一个终端。

后端：

```bash
cd "$KBS_ROOT/knowledge_back"
uv run flask --app app run --host 127.0.0.1 --port 5000
```

前端：

```bash
cd "$KBS_ROOT/knowledge_front"
npm run dev -- --host 0.0.0.0
```

检查后端：

```bash
curl -fsS http://127.0.0.1:5000/api/v1/health
```

浏览器访问 http://127.0.0.1:5173/。Root 初始登录账号和密码由 init.sql 创建，登录后请立即修改初始密码。

## 6. 常用命令

```bash
docker ps --filter name=kbs-postgres --filter name=kbs-minio
docker logs --tail 100 kbs-postgres
docker logs --tail 100 kbs-minio
docker stop kbs-postgres kbs-minio
docker start kbs-postgres kbs-minio
```

删除 kbs_postgres_data 或 .runtime/minio-data 会清除对应数据，确认不再需要数据后再删除。
