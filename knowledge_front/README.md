# knowledge_front

Vue 3 + Element Plus 前端项目。完整初始化与运行说明见 [项目根目录 README](../README.md)，开发约定见 [docs/development.md](docs/development.md)。

```bash
npm ci
npm run dev
```

访问 `http://127.0.0.1:5173/`，先进入首页再登录。后端需单独启动在 `http://127.0.0.1:5000`，开发服务器会代理 `/api` 请求。

生产构建：`npm run build`，产物位于 `dist/`。

状态筛选浏览器回归：`npm run test:e2e`。测试使用本机 Google Chrome，自动在 `127.0.0.1:4174` 启动测试前端，通过模拟 API 检查六个管理页面的状态选择、清空、刷新和组合查询，无需启动后端或连接业务数据库。

本项目只配置后端 API 地址，不保存 PostgreSQL、MinIO、DeepSeek 或阿里云百炼密钥。
