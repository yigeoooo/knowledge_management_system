# knowledge_front

Vue 3 + Element Plus 前端项目。完整初始化与运行说明见 [项目根目录 README](../README.md)，开发约定见 [docs/development.md](docs/development.md)。

```bash
npm ci
npm run dev
```

访问 `http://127.0.0.1:5173/`，先进入首页再登录。后端需单独启动在 `http://127.0.0.1:5000`，开发服务器会代理 `/api` 请求。

生产构建：`npm run build`，产物位于 `dist/`。

本项目只配置后端 API 地址，不保存 PostgreSQL、MinIO、DeepSeek 或阿里云百炼密钥。
