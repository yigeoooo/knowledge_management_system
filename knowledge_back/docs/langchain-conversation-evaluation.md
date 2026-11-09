# LangChain / LangGraph 对多轮知识问答的适用性评估

日期：2026-11-09。范围：设计研究，仅核对官方文档及现有代码，没有安装依赖或执行模型调用。

## 结论

可以引入，但作用应限定为模型调用适配、消息处理和问答流程编排。用户/机器人会话归属、历史分页、软删除、管理员查询、数据库事务和请求幂等仍由现有 Flask + SQLAlchemy 业务模块负责。

本项目已经有混合检索、文档版本过滤、证据引用、独立审阅和有限修复，适合明确的工作流。建议使用 LangGraph 的 `StateGraph` 表达流程，按实际需要使用 LangChain 的模型与消息能力；不需要把知识问答改成让模型自主决定步骤的通用 Agent。

这是一项可选的内部实现选择。即使不接入框架，当前技术栈也能完成网页/机器人多轮会话。框架不会直接提供本项目所需的管理员页面或会话权限。

## 已核对的官方能力

| 能力 | 官方说明 | 对本项目的含义 |
|---|---|---|
| 单会话记忆 | LangChain short-term memory 的范围是一个 thread/conversation；可借助 checkpointer 持久化。跨 thread memory 是另一项能力。[1] | 与用户要求的单会话记忆一致；不需要跨会话 Store。 |
| 消息裁剪和摘要 | 官方提供消息裁剪方法及 `SummarizationMiddleware`，可按 token/message 阈值压缩旧消息、保留近期消息。[1][2] | 能提供工具和实现参考，但摘要是否忠实、是否覆盖遗漏内容、失败时如何降级仍需项目定义。 |
| 工作流 | 官方区分预先定义代码路径的 workflows 和动态选择过程/工具的 agents。[3] | 现有“检索→生成→审阅→修复”属于 workflow，适合 `StateGraph`。 |
| 持久化 | Checkpointer 按 thread 保存图状态；有独立 `langgraph-checkpoint-postgres` 包。Store 用于跨线程数据。[4][5] | 能复用 PostgreSQL，但检查点表不应成为管理员查询的业务会话表。 |
| 恢复执行 | 相同 thread ID 不等于自动恢复；恢复、输入新消息及历史重放有不同调用方式。重放后续节点会重新执行模型/API 调用。[5] | 不能把超时后再提交相同 thread ID 当成完整幂等方案。 |
| 外部副作用 | 官方要求考虑重放与幂等；未完成任务可能再次执行。[6] | 模型调用可能重复计费，业务答案写入仍需唯一键、租约和条件更新。 |
| DeepSeek | 有 `langchain-deepseek` 的 `ChatDeepSeek`，集成页列出结构化输出、流式输出、异步和 token usage 等能力。[7] | 可替换手写 HTTP adapter；实际模型、兼容网关的支持范围必须另外验证，不能仅凭统一接口假定支持。 |

本次访问的旧 `durable-execution` 文档地址转到持久化总览；执行恢复细节以上述当前 checkpointers 和 Functional API 官方页面为准。

## 建议接入位置

```text
网页 / 机器人 HTTP 接口
    ↓
会话业务模块（身份、归属、软删除、顺序、幂等）
    ↓
PostgreSQL 待处理问答 + Worker（领取、租约、状态）
    ↓
LangGraph 问答工作流
    ├─ 读取服务端会话上下文
    ├─ 指代解释 / 独立检索问题
    ├─ 现有混合检索与当前版本过滤
    ├─ 生成带 evidence_ids 的回答
    ├─ 独立证据审阅 → 至多一次修复
    └─ 输出最终结果
    ↓
会话业务模块条件提交答案，更新会话摘要
```

网页和机器人走同一问答工作流，输入携带经业务层校验的 `conversation_id`、`turn_id`、上下文版本、问题及知识库标识。前端/机器人不能直接传入任意 graph thread ID、checkpoint ID 来读取或重放其他会话。

LangGraph 节点可以调用现有 Python 函数；无需把 pgvector 查询、MinIO、文档处理器全部替换成 LangChain 集成。现有 `retrieval_service` 的关键词与向量融合、邻居片段、代表章节等行为值得保留。

模型调用可在 `integrations/ai` 内接入 `ChatDeepSeek`，保留 `complete_json` 或新的项目自有窄接口，避免业务代码到处依赖框架对象。引入后仍需保持当前的超时预算、错误脱敏、输出 schema 验证和格式修复规则；统一模型 adapter 的重试与图节点重试，防止层层重试放大调用次数。

## 记忆、业务历史、检查点分别负责什么

建议业务库作为最终会话事实来源：

- `qa_conversations`：归属用户或机器人、知识库、标题、软删除、摘要及覆盖轮次。
- `qa_logs`：原始问答及引用，支持管理员审计和用户历史展示。
- 图的输入状态：本次从上述业务记录组装出的有限上下文，不自行读取其他会话。
- 可选 LangGraph checkpoints：某次执行的中间状态和恢复位置，不作为第二套完整业务聊天记录。

首版可只接入确定性图编排，不开启持久 checkpointer；Worker 失败后按业务状态从本轮重新执行。这样没有额外检查点表与业务表的一致性问题，但不能恢复到本轮某个已完成中间节点。

若后续确实需要节点级恢复，再加入 `PostgresSaver`，建议执行状态以本轮 `turn_id` 对应的内部 run/thread 隔离；会话记忆仍从业务库读取。官方也支持 conversation 与 thread 一一对应的传统聊天模式，但本项目已有独立历史与软删除需求，不必强制采取这个映射。

开启 checkpoint 后必须补齐：

1. 入队提交先于图调用。官方指出首个检查点持久化之前崩溃，无法从 checkpointer 区分“未调用”与“已接受但未保存”，建议在自己的存储中先写 admission/outbox。[5]
2. 同一会话串行；工作领取、租约和过期写入保护继续由业务层控制，checkpointer 不能代替 Worker 调度。
3. 最终答案业务写入有幂等键；图已结束但业务提交失败时，允许重试提交，不能创建第二轮问题。
4. 恢复前以及提交前检查会话是否删除、调用方是否停用、知识库及文档版本是否仍可用。失效资料不得借恢复流程重新变成当前证据。
5. 检查点是额外数据副本，要设计保留期限与清理。用户软删除会话后，即使检查点尚存在，也不能通过业务入口恢复继续对话。

这些是根据官方恢复语义作出的项目设计判断，不是 LangGraph 自动提供的业务保证。

## 摘要与结构化输出的实际边界

`SummarizationMiddleware` 官方示例挂在 `create_agent` 上。[2] 若本项目使用自定义 `StateGraph`，应建立显式摘要节点或调用项目的摘要函数；不能将该 middleware 当作可直接插入任意 Flask 函数的组件。

摘要只压缩对话语境，如对象、用户约束、正在讨论的步骤。原始历史保留，摘要有覆盖轮次并使用版本条件更新。新答案依然从当前有效知识库资料中取得证据；上一轮模型答案或摘要中的事实不能直接成为本轮事实来源。

结构化输出主要解决回答形状和字段解析。即使 `evidence_ids` 类型和 JSON schema 正确，也不能证明这些证据支持答案内容；必须保留当前 `grounding_service` 的真实段落校验和独立证据审阅。更换模型集成也不应移除 `NO_EVIDENCE`、`PARTIAL`、`SOURCES_ONLY` 等降级语义。

## 成本与采用顺序

| 方案 | 收益 | 代价 | 判断 |
|---|---|---|---|
| 保留 Python 编排 | 依赖少，沿用现有测试与行为 | 分支增多时需自行维护流程与观测 | 足以完成当前会话需求 |
| LangGraph 图 + 有界 LangChain 模型适配 | 流程、分支、有限修复路径更明确，未来扩展模型较方便 | 增加依赖、版本约束与适配测试 | 如果这次要引入生态，推荐此范围 |
| 同时引入持久 checkpointer / Agent Server / 通用 Agent | 提供更多恢复或托管能力 | 新增状态存储、部署与一致性复杂度，可能改变现有证据流程 | 当前没有必要一次性加入 |

建议先完成可审核的会话业务接口和状态模型，再把 `answer_service` 内部实现为固定图。LangSmith 为可选观测产品，不是运行 LangChain/LangGraph 的前提；本设计不要求启用云端追踪。

实施前使用真实 DeepSeek 配置做有限契约验证：JSON 完整性、超时、结构化输出模式、token 统计、引用审阅和有限重试行为。固定经验证的依赖版本；本次研究没有选定版本，也没有证明现有兼容网关已经支持所有框架能力。

## 官方来源

1. [LangChain — Short-term memory](https://docs.langchain.com/oss/python/langchain/short-term-memory)
2. [LangChain — Built-in middleware / Summarization](https://docs.langchain.com/oss/python/langchain/middleware/built-in#summarization)
3. [LangGraph — Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
4. [LangGraph — Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
5. [LangGraph — Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)
6. [LangGraph — Functional API / Determinism and idempotency](https://docs.langchain.com/oss/python/langgraph/functional-api)
7. [LangChain — ChatDeepSeek integration](https://docs.langchain.com/oss/python/integrations/chat/deepseek)
