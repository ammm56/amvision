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

默认开发服务地址为 `http://127.0.0.1:5601`。

## runtime config

前端启动时优先读取 `/runtime-config.local.json`，再读取 `/runtime-config.json`，读取失败时回退到 Vite 环境变量和默认本地地址。

本地开发可复制 `public/runtime-config.template.json` 为 `public/runtime-config.local.json`。模板默认使用后端本地 seed 的长期 user token，明确退出后会记录人工登录标记。

## 类型来源

第一阶段先在 `src/shared/contracts/generated/api.ts` 维护最小公开类型。后续接入 OpenAPI 类型生成时，生成文件继续放在 `src/shared/contracts/generated/`。

## 模型任务详情生命周期

- 训练、转换详情按 `taskType` 和 `taskId` 确定页面归属。切换任务时清空旧详情、指标、文件选择和确认弹窗，并取消旧读取；返回同一任务也使用新的请求代次。
- 详情、文件列表和文件预览分别隔离请求，同一类读取只接受最新返回。卸载后不再提交请求结果或启动订阅。
- 暂停、保存、终止、恢复、登记模型和删除使用点击时已加载的任务身份。页面切换不撤销已经提交的服务端操作，但旧操作的返回不得更新新页面或触发跳转。
- 任务事件和训练遥测只接收当前连接所属任务的消息。任务切换、停止和卸载关闭连接并取消重连；同一任务刷新复用现有连接。
- 生命周期回归位于 `tests/frontend/models/test_task_detail_lifecycle.ts`、`test_task_stream_lifecycle.ts` 和 `test_model_task_read_cancellation.ts`。测试使用真实 Vue Router 和可控制完成顺序的请求，不依赖训练进程或 GPU；实现保持 Vue 3 和离线部署边界不变。
