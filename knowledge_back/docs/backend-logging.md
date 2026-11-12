# 后端控制台日志

按原方式启动 Flask 或后台 worker 即可，无需数据库迁移。日志使用 Python 标准 logging 输出到控制台 stderr，格式为时间、级别、线程、模块、请求编号和内容。

## 可以看到什么

- `HTTP ->`：请求方法、路径、查询参数、JSON 或表单参数。重复查询参数保留全部值。
- `HTTP <-`：响应状态码、总耗时。4xx 使用 WARNING，5xx 使用 ERROR。
- `HTTP multipart`：表单字段及已解析的上传文件名称、类型、大小（客户端未提供大小时为 null）；不读取文件内容。
- `SQL`：实际执行的 SQL 模板、执行耗时和驱动返回的影响行数。SELECT 的行数可能是 `-1`，代表驱动未提供，不是执行失败。耗时统计到数据库驱动执行结束，不包含后续 ORM 对象构建。
- `SQL SLOW` / `SQL FAILED`：慢查询和数据库错误，即使关闭普通 SQL 日志仍会输出。
- 异常：类型、错误原因、调用堆栈及代码位置。数据库错误保留主要原因和 SQLSTATE，省略可能含业务值的 DETAIL / 绑定参数。参数校验、未登录等常见 4xx 只打印原因，不刷堆栈。
- 问答、评测和索引后台任务：开始、完成及失败日志；失败时打印堆栈和轮次、实验或任务 ID。评测失败同时记录题目 ID 与 baseline / candidate，便于定位哪一侧调用出错。

一次请求的示例（省略较长的时间和模块前缀）：

```text
INFO  [request_id=demo-123] HTTP -> POST /api/v1/... query={} body={"question": "8个人要多少钱？"}
INFO  [request_id=demo-123] SQL duration=1.24ms rows=1 statement=SELECT ... WHERE id = %(id_1)s
INFO  [request_id=demo-123] HTTP <- POST /api/v1/... status=200 duration=38.25ms
```

客户端可传 `X-Request-ID`；未传或格式不合法时后端生成，响应头也会返回。后台线程没有 HTTP 请求上下文时显示 `request_id=-`，通过任务 ID、线程和时间关联。Werkzeug 原来的简略访问行被关闭，避免重复刷屏。

## 配置

在 `knowledge_back/.env.local` 中设置，修改后重启后端和独立 worker：

```dotenv
LOG_LEVEL=INFO
LOG_SQL_ENABLED=true
LOG_SQL_SLOW_MS=500
LOG_MAX_BODY_BYTES=8192
```

| 配置 | 作用 |
| --- | --- |
| `LOG_LEVEL` | `DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL`，默认 INFO。设为 WARNING 后普通请求与普通 SQL 不再输出。 |
| `LOG_SQL_ENABLED` | 本地默认 true，服务器和测试默认 false；控制普通 SQL，慢 SQL 与失败 SQL仍按级别输出。 |
| `LOG_SQL_SLOW_MS` | 慢 SQL 阈值，默认 500 毫秒，0 表示所有 SQL 均作为慢查询输出。 |
| `LOG_MAX_BODY_BYTES` | 默认 8192 字节。请求体超过此限制时仅记录大小；SQL、已解析表单及序列化参数的展示长度也受限，截断带标记。 |

密码、令牌、Authorization、Cookie、API Key 等字段会递归脱敏；SQL 使用占位符，不输出绑定值，避免把密码、文档正文和向量全部打印出来。请求头、完整响应体、二进制内容不逐条打印。无效 JSON 只记录“无法解析”，不输出原文。日志读取不会消费接口后续需要的请求体或文件流。

控制台异常信息只用于后端排查，接口继续返回简洁的错误信息；未捕获异常统一返回带 `request_id` 的 JSON 500 响应。数据库错误保持原来的 JSON 503 响应。本次没有数据库结构变化，不需要修改 `init.sql`。
