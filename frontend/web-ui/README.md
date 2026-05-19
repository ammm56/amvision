# amvision Web UI

浏览器前端 Web UI 使用 Vue 3、TypeScript、Vite、Pinia、Vue Router 和 Reka UI。

## 开发命令

```powershell
npm install
npm run dev
npm run typecheck
npm run build
npm run test
```

默认开发服务地址为 `http://127.0.0.1:5173`。

## runtime config

前端启动时优先读取 `/runtime-config.local.json`，再读取 `/runtime-config.json`，读取失败时回退到 Vite 环境变量和默认本地地址。

本地开发可复制 `public/runtime-config.template.json` 为 `public/runtime-config.local.json`。模板默认使用后端本地 seed 的长期 user token，明确退出后会记录人工登录标记。

## 类型来源

第一阶段先在 `src/shared/contracts/generated/api.ts` 维护最小公开类型。后续接入 OpenAPI 类型生成时，生成文件继续放在 `src/shared/contracts/generated/`。