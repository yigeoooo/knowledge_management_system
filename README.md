# 智能知识库平台

Vue 3 + Element Plus + Flask 的知识库管理系统。

## 1. 项目结构

```text
knowledge_management_system/
├── README.md                 # 本文件：初始化和运行说明
├── init.sql                  # 完整数据库结构、字段备注和初始化数据
├── knowledge_back/
│   ├── app/                  # Flask API、认证、权限、模型
│   ├── migrations/           # Alembic 后续增量迁移
│   ├── tests/                # 后端测试
│   ├── pyproject.toml        # Python 依赖
│   ├── uv.lock               # 后端依赖锁定
│   ├── .env.example          # 后端配置模板
│   ├── docker-compose.local.yml
│   └── docs/                 # 业务需求和开发环境说明
└── knowledge_front/
    ├── src/                  # 首页、登录页、工作台和管理页面
    ├── public/brand/         # 公司 Logo 与 favicon
    ├── package.json
    ├── package-lock.json
    ├── .env.example          # 前端配置模板
    └── vite.config.ts        # 开发服务器和 API 代理
```

## 2. 环境要求

| 组件            | 要求                                     |
| --------------- | ---------------------------------------- |
| Node.js         | 推荐 22 LTS，至少 22.12（或 20.19+）     |
| npm             | 随 Node.js 安装                          |
| Python          | 3.11+，当前开发环境为 3.13               |
| uv              | Python 依赖与虚拟环境管理工具            |
| PostgreSQL      | 16，安装 pgvector 和 pgcrypto 扩展       |
| Docker / Podman | 可选，用于运行仓库提供的 PostgreSQL 容器 |
| MinIO           | 后续文档上传使用，首页和登录阶段不依赖它 |

所有下方命令默认在项目根目录开始执行；前端和后端需要分别使用一个终端。

## 3. 配置并初始化数据库

### 3.1 后端配置文件

首次启动时复制模板；已有 `.env.local` 的开发环境直接沿用，不要覆盖。

```bash
cp knowledge_back/.env.example knowledge_back/.env.local
```

修改 `knowledge_back/.env.local` 中的数据库连接配置：

```dotenv
APP_ENV=local
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=knowledge_db
POSTGRES_USER=root
POSTGRES_PASSWORD=填写你的数据库密码
```

这里的 `POSTGRES_PASSWORD` 是 **PostgreSQL 连接密码**，与后文 Root 网页登录密码无关。文档存储需要 MinIO，索引和检索需要 DashScope，推荐问题和回答生成需要 DeepSeek；在后端文件中配置实际值，禁止放入前端 `VITE_*` 环境变量。

本地开发时 JWT 密钥自动生成在被 Git 忽略的 `knowledge_back/.runtime/jwt-secret`。也可以在 `.env.local` 中设置至少 32 字符的 `JWT_SECRET_KEY`。非本地环境必须显式设置此密钥，并通过 HTTPS 访问。

### 3.2 启动 PostgreSQL

如果已经有 PostgreSQL 16 + pgvector 和空数据库 `knowledge_db`，可直接跳到下一步。文档管理还需要一个私有 MinIO 服务；使用项目 Compose 时会同时启动 `kbs-minio`。`MINIO_BUCKET` 作为历史对象的兼容桶保留，新建知识库时后端会按知识库 UUID 创建独立 Bucket。

如需使用本项目提供的容器：

```bash
cd knowledge_back
docker compose --env-file .env.local -f docker-compose.local.yml up -d
cd ..
```

容器名为 `kbs-postgres` 和 `kbs-minio`，数据库名、用户、MinIO 凭据来自 `.env.local`。本地浏览器访问预签名 URL 时，`MINIO_PUBLIC_ENDPOINT` 应填写浏览器可访问的地址（通常为 `127.0.0.1:9000`）。已有数据库卷的密码不会随着修改环境文件自动改变；请填入现有数据库实际凭据。

### 3.3 通过 SQL 初始化

**数据库结构和初始数据均在根目录 `init.sql` 中。只需导入 SQL，不需要执行 Python 初始化程序。**

脚本用于一个空数据库。已有业务表的当前开发环境已经初始化，正常启动时跳过本步骤；不要对已有数据库反复导入。脚本不会删除旧表，重复导入会因表已存在而停止。

方式一：使用本机 `psql`，在项目根目录执行，按提示输入数据库连接密码：

```bash
psql -h 127.0.0.1 -p 5432 -U root -d knowledge_db \
  -v ON_ERROR_STOP=1 -f init.sql
```

方式二：使用上一步启动的容器，不需要本机安装 `psql`：

```bash
docker exec -i kbs-postgres psql -U root -d knowledge_db \
  -v ON_ERROR_STOP=1 < init.sql
```

如修改过数据库用户名或库名，请相应替换命令中的 `root` 和 `knowledge_db`。

`init.sql` 在一个事务中创建：

- `vector`、`pgcrypto` 扩展。
- 13 张业务表：用户、角色、页面、角色页面权限、登录会话、知识库、机器人、文档、文档版本、文档切片、索引任务、问答日志、审计日志。
- Alembic 版本表，供后续增量升级使用。
- 每张表及每个字段的中文数据库备注。
- `user`、`super_admin` 两个内置角色。
- 13 个后台页面；普通用户拥有知识问答和个人信息权限；超级管理员拥有全部页面权限。
- Root 管理员、默认知识库 `general` 和一条初始化审计记录。

向量列暂使用不限定维度的 `vector`。接入 DashScope 后，需要根据真实响应确认维度，再增加固定维度约束和向量索引。

### 3.4 初始网页登录账号

| 项目     | 初始值                      |
| -------- | --------------------------- |
| 用户名   | `root`                      |
| 密码     | `Dexforce@Root2026!`        |
| 角色     | `super_admin`（超级管理员） |
| 页面权限 | 全部 13 个后台页面          |

上述初始密码也明确写在 `init.sql` 中，导入后即可登录。SQL 中的 `password_hash` 是对应的 Argon2 哈希，登录校验使用此字段。

按当前需求，`users.password_plaintext` 另保存原始明文密码，创建用户或重置密码时同步更新。这个敏感字段和密码哈希均不会通过用户列表或个人信息 API 返回。拥有数据库读取权限的人可以看到明文密码，请限制数据库访问；正式部署前修改公开的初始密码。不应仅手动修改明文列，否则不会改变登录密码。

管理员可通过后端维护命令重置密码，交互输入不会显示在命令行参数中：

```bash
cd knowledge_back
uv run flask --app app set-password --username root
```

重置会同时更新密码哈希、明文列，并撤销该用户现有登录会话。

## 4. 启动后端（终端一）

在项目根目录打开终端：

```bash
cd knowledge_back
uv sync --locked
uv run flask --app app run --host 127.0.0.1 --port 5000
```

后端启动时自动读取 `knowledge_back/.env.local`。首次 `uv sync` 会创建 `.venv` 并安装依赖。

| 地址                                  | 用途                 |
| ------------------------------------- | -------------------- |
| `http://127.0.0.1:5000/api/v1`        | API 前缀             |
| `http://127.0.0.1:5000/api/v1/health` | 服务和数据库连接状态 |

健康接口正常返回 `code: 0`，`data.status` 和 `data.database` 均为 `ok`。

以上是本地开发服务器启动方式。正式环境可使用 Gunicorn + 同源反向代理；当前限流默认保存在单进程内存中，多进程部署应配置共享的 `RATELIMIT_STORAGE_URI`。

## 5. 启动前端（终端二）

另开一个终端，从项目根目录执行：

```bash
cd knowledge_front
npm ci
npm run dev
```

浏览器打开：**http://127.0.0.1:5173/**

先显示品牌首页，点击“登录平台”或“进入知识平台”，再使用 Root 初始账号登录。

前端默认请求同源 `/api/v1`，Vite 会将 `/api` 请求代理到 `http://127.0.0.1:5000`。本地运行无需额外配置 CORS，也不必创建前端 `.env.local`。如果需要显式配置，可复制前端模板：

```bash
cp .env.example .env.local
```

模板内容是：

```dotenv
VITE_API_BASE_URL=/api/v1
```

如果后端端口改变，需要同时修改 `knowledge_front/vite.config.ts` 的代理目标。建议始终使用 `127.0.0.1:5173` 访问本地前端，避免来回切换 `localhost` 导致浏览器会话不同。

构建生产静态文件：

```bash
cd knowledge_front
npm run build
```

产物位于 `knowledge_front/dist/`。部署时需将 `/api` 代理到 Flask，并为前端路由配置 SPA 回退到 `index.html`。`npm run preview` 仅用于预览静态构建产物，不包含完整生产 API 代理配置。

## 6. 当前页面与功能状态

| 页面         | 路径                | 当前状态                                                                     |
| ------------ | ------------------- | ---------------------------------------------------------------------------- |
| 品牌首页     | `/`                 | 已实现，公开访问，适配移动端                                                 |
| 登录         | `/login`            | 已接入真实认证、校验和错误提示                                               |
| 工作台       | `/dashboard`        | 按角色页面权限展示统计与快捷入口                                                         |
| 知识问答     | `/qa`               | 基于文档的动态推荐问题、单轮问答、编号引用、来源预览和失败重试                 |
| 知识库管理   | `/knowledge-bases`  | 创建、编辑、停用、归档和分页搜索；写操作按知识库管理页面权限校验                   |
| 创建文档 | `/create-document` | 从零编写 Word 或 Markdown，保存到知识库并自动建立索引 |
| 文档管理     | `/documents`        | 按知识库管理 Markdown、TXT、PDF、Word、图片和视频；支持 MinIO 上传、预览、下载、在线文本编辑、版本与索引任务 |
| 机器人管理   | `/robots`           | 机器人注册、详情、编辑、启用／停用、序列号或名称搜索与状态筛选                 |
| 用户管理     | `/users`            | 新增、详情、编辑、密码重置、启用／停用、删除、显示名称模糊搜索与状态组合筛选 |
| 角色管理     | `/roles`            | 角色分页查询、新增、编辑类型、启停与删除；super_admin 受保护                    |
| 页面路由     | `/pages`            | 数据库列表和搜索；编辑待开发                                                 |
| 角色页面权限 | `/role-permissions` | 按角色勾选、覆盖保存页面访问权限                                               |
| 问答日志     | `/qa-logs`          | 问题搜索、WEB／ROBOT 来源筛选、提问人显示和问答详情对话框                       |
| 审计日志     | `/audit-logs`       | 展示登录、退出及账号维护等实际记录，操作人显示姓名                                           |
| 个人信息     | `/profile`          | 当前用户信息与已授权页面                                                     |

所有页面都采用 Element Plus 组件并统一为黑白橙主题。尚未接入的操作按钮明确禁用，不会生成模拟业务结果。

知识问答统一使用 `/qa`。已有环境在项目根目录执行以下增量 SQL，删除旧的“网页提问测试”页面及所有角色对它的权限绑定；新环境导入最新 `init.sql` 即可：

```bash
docker exec -i kbs-postgres psql -U root -d knowledge_db \
  -v ON_ERROR_STOP=1 < knowledge_back/sql/2026-10-21-remove-web-query-page.sql
```

该脚本可重复执行，只调整页面和权限数据。执行后刷新浏览器页面，重新加载菜单及页面权限。

### 页面授权与创建文档

`super_admin` 自动拥有所有已启用页面和对应功能权限，不依赖逐条角色页面关联。其他角色获得某个页面权限后，即可使用该页面对应的读写接口；权限未授予、被撤销或页面停用时，后端返回 403。用户和角色本身仍须启用；Root 和超级管理员角色的保护规则继续生效。

`/create-document` 提供 Markdown 编辑与实时预览，以及 Word 可视化编辑（标题、加粗、斜体、下划线、列表、链接、代码块和普通表格）。填写标题、编写正文后选择知识库，点击“保存到知识库”，系统生成 `.md` 或 `.docx` 文件，保存到该知识库的 MinIO Bucket，创建文档版本并排队索引。Word 表格内容也参与索引。正文最多 200,000 字符，Word 支持常见文字格式及合并表格。

文档管理中打开 `.docx` 的详情，点击“在线编辑”可继续修改正文，点击“保存为新版本”后上传并自动索引。原版本仍可预览、下载；重复保存重试不会重复建版本，基于过期版本的保存会提示冲突。编辑内容未保存时，关闭详情或离开页面会提示确认。系统内创建的 DOCX 保留完整编辑数据，外部 DOCX 支持标题、字体/颜色/强调、段落对齐/间距/缩进、简单及嵌套列表、链接、分页和合并表格。旧 `.doc` 需另存为 `.docx`；含图片、修订、公式、分栏等当前编辑器无法表示的文档会提示上传新版本修改，避免静默删除内容。页眉页脚随原文件保留，当前编辑区域仅编辑正文。

知识问答及问答记录详情中的 DOCX 引用按记录的版本恢复格式，只展示引用范围；无需重新上传或重新索引。原文件不可用或无法定位引用范围时，继续展示原引用文字。


草稿保留在当前浏览器标签页；离开或切换格式前会提示。保存失败保留正文，重试不会重复创建文档。成功后显示处理状态，可继续创建下一篇；只有获得文档管理权限的角色才显示文档管理入口。

已有数据库需要执行以下增量 SQL 注册新页面；新环境使用最新 `init.sql` 即可。新页面默认只为超级管理员开放，其他角色在“角色页面权限”中勾选“创建文档”后使用。

```bash
docker exec -i kbs-postgres psql -U root -d knowledge_db \
  -v ON_ERROR_STOP=1 < knowledge_back/sql/2026-10-27-document-create-page.sql
```

修改后重启 Flask，刷新浏览器以获取最新菜单和权限。

### 用户管理

拥有用户管理页面权限的角色进入 `/users` 后可以：

- **新增用户**：填写用户名、显示名称、角色、状态及初始密码；密码为 12–1024 个字符，用户名唯一且不含空格。
- **查看与查询**：点击“详情”查看用户资料；按显示名称进行不区分大小写的包含查询，可同时选择启用／停用状态；支持分页和每页条数切换。
- **编辑用户**：修改用户名、显示名称、角色或状态；新密码留空表示保留原密码，填写后会同步更新哈希和原始密码列。
- **启用／停用**：通过列表开关或编辑弹窗操作；停用需要确认，并撤销现有登录会话。
- **删除用户**：确认后逻辑删除，从列表和统计中移除，清除可用密码并撤销会话；保留历史文档和审计关联，已删除用户名不能再次注册。

Root 账号不能改用户名、改角色、停用或删除；当前登录账号不能修改自身角色、停用或删除。修改自己的用户名或密码后会返回登录页。修改其他用户的用户名、密码、角色或状态后，对方需要重新登录。所有写操作在后端校验对应页面权限，并写入审计日志。

### 角色管理

拥有角色管理页面权限的角色进入 `/roles` 后可以按角色名称或编码查询，并进行角色新增、编辑、切换系统／自定义类型、启用／停用和删除。角色编码在数据库中保持唯一，编辑角色编码、名称或类型不受该角色当前用户数影响；角色停用后，该角色下的用户无法登录。`super_admin` 角色的编码、系统类型、启用状态、删除操作受保护。仍有用户使用的角色不能删除，需先调整用户角色。角色写操作会记录审计日志。

已有数据库如需同步 `roles.is_system` 字段备注，可执行 `knowledge_back/sql/2026-10-21-role-type.sql`；新环境使用根目录 `init.sql` 即可。

### 角色页面权限

拥有“角色页面权限”页面授权的角色进入 `/role-permissions` 后选择角色，勾选页面并点击“保存权限”即可覆盖该角色的页面访问范围。保存接口为 `PUT /api/v1/roles/{id}/pages`，请求体为 `{ "page_ids": ["页面 UUID"] }`；空数组会清空普通角色的页面权限，重复或不存在的页面 ID 会被拒绝。`super_admin` 必须保留全部启用页面权限，权限变更会记录审计日志。相关用户刷新或重新登录后会收到新的页面列表。

本次无需重建数据库。已有 `status VARCHAR(30)` 列可直接支持删除状态。如需同步字段备注与迁移版本，在项目根目录导入增量 SQL：

```bash
docker exec -i kbs-postgres psql -U root -d knowledge_db \
  -v ON_ERROR_STOP=1 < knowledge_back/sql/2026-10-21-user-management.sql
```

新环境直接使用根目录 `init.sql`，无需另行导入该增量脚本。后端没有开启自动重载时，修改代码后需要重启 Flask；前端 `npm run dev` 会自动更新。

### 文档索引 Worker

文档上传完成后，后端会创建 PostgreSQL 中的 `index_tasks` 待处理任务，并自动唤醒当前 Flask 进程内的索引 Worker。开发环境不需要另开终端；如果服务重启后需要恢复遗留任务，仍可手动运行以下命令：

```bash
cd knowledge_back
uv run flask --app app index-worker
```

Worker 从 MinIO 读取文件。Markdown、TXT、PDF 和 DOCX 会提取文本、切片并调用 DashScope Embedding；图片和视频会调用同一多模态 Embedding 模型生成媒体向量，DOC 文件保留原始文件并标记为已就绪。设置 `MINIO_PUBLIC_ENDPOINT` 为 DashScope 可访问的地址，Worker 会向模型提交短时预签名媒体 URL。使用自建或部署模型时，把实际 Embedding 路径填入 `DASHSCOPE_EMBEDDING_URL`，避免把只支持聊天或 OpenAI 兼容路径的地址当成多模态服务地址。单次处理任务可使用 `--once`，生产环境建议将 Worker 作为独立进程托管。

认证已实现：Argon2 密码校验、15 分钟 Access Token、HttpOnly 刷新 Cookie、刷新令牌轮换、退出撤销、后端管理接口鉴权以及动态页面路由。Access Token 只保存在前端内存，刷新页面时通过 Cookie 恢复会话。

### 知识问答与推荐问题

进入 `/qa` 或切换知识库时，页面通过 `POST /api/v1/web/suggested-questions` 从当前启用知识库中随机抽取已索引的当前版本文本，优先不同文档和章节，由 DeepSeek 整理并审阅最多三个可回答的问题。点击推荐只填入输入框，用户点击发送后才开始问答，同时携带绑定用户、知识库、问题与原始切片的签名凭据；即使重新检索漏掉该片段，也会优先纳入原始资料。编辑问题后会清除凭据。内容不足时可以少于三条；图片、视频及未索引文档不会被编造成推荐问题。推荐不缓存、不写入问答日志，仍可直接输入问题。

发送问题调用 `POST /api/v1/web/query`。具体问题结合 DashScope 语义检索与标题、章节、正文关键词匹配（各最多 24 个候选），按排名融合并补齐相邻片段；流程和主题概述额外抽取相关文档的代表章节；“这个知识库包含什么”等通用概览直接覆盖多篇文档。最多提交 10 个文本切片、24000 个字符，并明确概览覆盖范围，不把局部片段当成全文。代码块不再按任意 3000 字位置截断，媒体仍单独作为相关资料展示。

后端为原文段落编号，模型按段落引用生成回答，再由独立审阅请求核对每块事实、命令、数字和步骤是否得到资料支持。支持同义改写、Markdown 格式变化和跨段概括，不要求模型逐字抄写引文。兼容 JSON 代码围栏和字符串布尔值等无歧义差异，格式或依据校验失败自动纠正一次。纠正后只返回已核实的部分；仍无法整理时返回相关原文，网络或服务故障才返回错误。审阅仍依赖模型判断，真实资料上的回答质量需要持续验收。答案支持 Markdown、表格、代码块和右侧编号来源。本期仍为单轮非流式问答，不携带历史对话；`/web/search` 保留为纯检索接口。

后端 `.env.local` 需要有效的 `DEEPSEEK_BASE_URL`、`DEEPSEEK_API_KEY`、`DEEPSEEK_CHAT_MODEL` 和现有 DashScope 配置。`DEEPSEEK_TIMEOUT_SECONDS` 默认 60 秒（单次限制在 5–90 秒）；`QA_MIN_SIMILARITY` 默认 0.3，用于语义候选筛选，应按真实文档和问题调优。正常生成与审阅共两次模型调用，纠正时最多四次；推荐阶段总时间预算为 90 秒，回答阶段为 150 秒，每次调用受剩余预算约束。前端推荐超时 120 秒，问答超时 300 秒（还包含 Embedding）；生产反向代理和 Gunicorn 的超时也应覆盖这一时长。

问答记录使用现有 `qa_logs`，状态包括处理中、成功、部分有依据、依据不足、仅返回资料或服务失败。同一用户、知识库、问题和 `request_id` 的已完成结果可复用；处理中返回冲突提示，服务失败可以用相同编号重试，超过 10 分钟的遗留处理中记录允许重新接管。前端收到结果后再次主动发送会使用新编号；网络中断重试保留原编号。跨用户或不同问题复用编号会被拒绝。无需改表或重新导入 `init.sql`；如需同步字段备注，可执行 `knowledge_back/sql/2026-10-23-qa-output-status.sql`。修改配置或后端代码后重启 Flask。

机器人管理已接入注册、详情、编辑、启用／停用、分页搜索、状态筛选和审计；删除接口采用停用语义以保留问答日志中的机器人关联。知识库管理已接入 CRUD、状态控制、审计和独立 MinIO Bucket；文档管理已接入 MinIO 对象存储、版本、预览、下载、在线 Markdown/TXT/DOCX 编辑、PDF/DOCX 文本提取和 PostgreSQL 索引任务。生产环境可以继续使用独立的 `uv run flask --app app index-worker` 进程作为任务恢复和扩展吞吐的 Worker。

### 机器人问答接口

`POST /api/v1/robot/query` 接收 JSON，不需要用户登录 Token。先校验 `serial_no` 对应机器人已注册且启用，再按 `knowledge_base_code` 查找启用的知识库，随后复用网页问答的检索、答案生成和依据审阅流程。

```bash
curl -X POST 'http://127.0.0.1:5000/api/v1/robot/query' \
  -H 'Content-Type: application/json' \
  -d '{
    "serial_no": "ROBOT-001",
    "knowledge_base_code": "product_manual",
    "question": "设备如何安装？",
    "request_id": "robot-req-001"
  }'
```

四个字段均必填：`serial_no`、`knowledge_base_code` 为 1–100 个字符，`question` 为 1–2000 个字符，`request_id` 为 1–100 位字母、数字或 `._-`，建议使用 UUID。与网页问答一样采用单轮非流式回答，不接受 `top_k`、`stream` 或历史消息。客户端超时建议设为 300 秒。

成功响应保留统一 JSON 包装，`data` 仅含纯文字 `answer`，不返回引用列表、引用编号、预览链接、模型或耗时等字段。客户端使用 `response.json()["data"]["answer"]` 读取。回答保留段落、步骤和必要的代码内容，移除 Markdown 排版标记；资料不足时直接返回文字说明。

```json
{
  "code": 0,
  "message": "ok",
  "request_id": "服务端请求追踪编号",
  "data": { "answer": "安装前请检查电源和接地。" }
}
```

请求写入问答记录并标记 `source_type=ROBOT`、关联机器人，同时更新机器人的最近请求时间。相同机器人、知识库、问题和请求编号可重试并复用已完成结果；跨机器人、跨网页用户或不同问题复用编号返回 `40901`。每次重试仍需通过机器人状态校验，历史请求重试也返回上述精简 JSON。

错误响应仍为统一 JSON（`code`、`message`、`request_id`、`data: null`）。未注册或停用返回 HTTP 403 / `43001`，知识库不存在或停用返回 HTTP 404 / `43002`，参数错误返回 HTTP 422 / `42201`。限流为每 IP 每分钟 60 次、每台已注册机器人每分钟 20 次，超过返回 HTTP 429。接口复用现有表，无需数据库迁移；更新后运行 `uv sync` 同步依赖并重启后端生效。

## 7. 常见问题

- **首页可以打开，登录提示连接失败**：确认后端已经在 `127.0.0.1:5000` 启动，并检查 Vite 代理目标。
- **后端提示数据服务暂不可用**：确认数据库已启动、`.env.local` 的连接密码正确，并已导入 `init.sql`。
- **导入提示表已存在**：目标库已初始化；不要覆盖或清空已有数据。现有环境正常启动即可，后续结构升级使用迁移。
- **修改 `password_plaintext` 后密码不生效**：该列不参与登录验证；使用 `set-password` 同步更新哈希和明文。
- **刷新页面后登录失效**：确认前后端使用同源代理。非本地环境会启用 Secure Cookie，必须通过 HTTPS。
- **登录页没有注册入口**：账号由管理员在“用户管理”页面新增，也可用 `uv run flask --app app create-user --username 用户名 --role user` 交互创建。
- **索引状态长时间停留在等待索引**：确认 MinIO、DashScope 配置正确；如果关闭了 `INDEX_WORKER_AUTOSTART`，请运行 `uv run flask --app app index-worker`。

后续数据库结构升级（已初始化的数据库）：

```bash
cd knowledge_back
uv run flask --app app db upgrade
```

本轮文档存储只新增索引和数据库备注，已有数据库可执行 `knowledge_back/sql/2026-10-22-document-storage.sql`；不需要重新导入根目录 `init.sql`。

## 8. 相关文档

- [完整业务需求](knowledge_back/docs/knowledge-base-management-system-requirements.md)
- [数据库、MinIO 与模型开发环境](knowledge_back/docs/development-environment.md)
- [前端开发说明](knowledge_front/docs/development.md)
- [数据库初始化 SQL](init.sql)

后端 `.env.local`、本地运行数据、第三方服务密钥和 MinIO 许可证均由 `.gitignore` 排除，不要提交到仓库。


### 上传大小与操作人显示

单文件默认上限为 **200 MB（209715200 字节）**。在 `knowledge_back/.env.local` 中添加或修改 `MAX_DOCUMENT_SIZE=209715200`，重启后端后生效；服务器通过部署环境中的同名变量配置。该变量同时控制上传信息校验、Flask 回退上传请求体、存储读取上限，文档列表返回 `max_file_size` 供前端校验及显示。模板位于 `knowledge_back/.env.example` 和 `.env.server.example`，代码默认值位于 `knowledge_back/app/config.py`。如果部署使用 Nginx，站点的 `client_max_body_size` 也应至少为 `200m`。

知识库管理和文档管理的列表展示“创建人”“最后修改人”，使用用户显示名称。创建人来自资源创建记录；最后修改人来自最近一次成功的创建、上传完成、在线编辑、属性修改或归档审计记录。下载、上传准备和重索引不计为内容修改。无用户记录时显示 `—`，不展示 ID；用户改名后列表同步使用新的显示名称。无需新增数据库字段或执行迁移。
