# 七用途提示词与实时工具

当前只支持七用途流程：机器人身份、对话规划、回答生成、回答审阅、摘要、问题推荐和推荐审阅。旧用途与迁移按钮已移除，不再兼容旧提示词快照。

## 初始化与升级

执行 `flask db upgrade`，或在空数据库使用根目录 `init.sql`，版本为 `b94c0d523e18`。本次迁移删除旧提示词及其版本，写入七份全新、已发布的 v1；不需要额外点击迁移或发布。迁移不可降级，执行前应备份提示词数据。后续编辑仍通过正常版本与评测发布流程处理。

机器人、文档、聊天记录和评测历史保留；正在等待或执行的旧问答与评测标记失败，防止继续使用旧快照。历史实验可查看，但旧环境的重试和发布需要重新创建实验。

机器人管理支持搜索城市、选择时区，列表和详情显示绑定城市及 IANA 时区。城市保存提供商 ID 和可读名称。机器人自我介绍使用数据库中的名称。

## 天气配置

当前实现和风天气适配器，需要 `QWEATHER_HOST`（账号专属 `xxx.qweatherapi.com` 域名，不含协议）和 `QWEATHER_API_KEY`，写入运行环境或 `.env.local`。密钥不进入提示词、快照和工具结果。未配置时不启用天气工具；当前时间使用服务端时钟和明确时区。

实现城市查询、当前天气和3日预报。多地点结果不按热门排序猜选；明确地点失败不改查默认地点。实况超过30分钟、预报更新时间超过12小时会拒绝。工具总预算15秒，HTTP单请求最多4秒，响应最多256KiB。第一版没有跨请求缓存和自动重试；结果记录 `cache_hit=false`，避免缓存延长数据时效。真实服务覆盖和账号权限仍需配置后在线验证。

## 固定样本

题目编辑的“实时评测固定样本”接受以下结构。`fixtures` 按规范化工具参数精确匹配；缺少匹配会使该侧执行失败，绝不联网补齐。两侧共享相同 runtime 和 fixtures。没有配置的题目冻结为固定UTC时钟、空地点、空时区及空样本。

```json
{
  "runtime": {
    "now": "2026-11-12T00:00:00+00:00",
    "timezone": "Asia/Shanghai",
    "default_location": "宜宾市"
  },
  "fixtures": [{
    "request": {
      "name": "get_weather",
      "location": "宜宾市",
      "location_source": "default",
      "date": null,
      "mode": "now",
      "timezone": null
    },
    "result": {
      "status": "success",
      "location": "宜宾市",
      "timezone": "Asia/Shanghai",
      "date": "2026-11-12",
      "mode": "now",
      "source": "fixture-qweather",
      "updated_at": "2026-11-12T00:00:00+00:00",
      "fetched_at": "2026-11-12T00:00:00+00:00",
      "expires_at": "2026-11-12T00:05:00+00:00",
      "units": {"temperature": "°C"},
      "data": {"temp": "18", "text": "晴"}
    }
  }]
}
```

失败样本使用 `{"status":"error","reason":"unavailable"}`。地点缺失和时区缺失由后端直接判断。样本只用于评测接口，不从机器人用户请求接收。模型参数规划准确性需要真实模型评测，单元测试中的模型替身不能证明语义准确率。

## 接口与追踪

- 机器人创建/编辑支持 `default_location`、`timezone`；响应包含 `default_location_name`。
- 城市查询：`GET /api/v1/robots/location-options?q=...`。
- 时区选项：`GET /api/v1/robots/timezone-options`。
- 原 `/prompts/consolidation/prepare` 和 `/prompts/consolidation/publish` 已移除。
- 逐题结果和本地问答追踪记录提示词组合、运行时与工具来源、参数、时效和耗时。

回答由独立生成与审阅处理工具及文档证据。工具结果不伪装成文档引用。
