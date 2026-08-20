# Workflow 前端流程与节点通信

## 节点目录

前端通过 `GET /api/v1/workflows/node-catalog` 读取 Core Node 与 Custom Node 的统一目录，消费以下事实：

- `node_type_id`、显示名称、分类和版本来源
- 输入输出端口与 `payload_type_id`
- 参数 schema 与参数 UI schema
- runtime kind、能力标签和运行要求

画布只保存节点实例、边、分组、参数和 UI state；节点定义不复制进 Template。连线时前端先做端口与 payload 轻量校验，后端 validate 和保存接口执行最终校验。

## Workflow App 编辑

当前工作台以 Workflow App 为中心：

1. 列表页进入新建或现有 App。
2. 图编辑器加载 Application、Template、Node Catalog 和当前草稿。
3. 画布编辑节点、连线、分组、输入输出和节点参数。
4. 保存时通过单一 App bundle 请求提交 Application 与 Template，避免两份文档跨请求撕裂。
5. 服务端在 lifecycle claim 内校验并原子保存 bundle；前端只在成功响应后清除 dirty state。

旧的独立 Template/Application 编辑路由已重定向到 App 工作台。

## Preview

Preview 使用编辑态快照，不创建生产 Runtime：

- 浏览器上传图片后使用 LocalBuffer/ObjectStore `image-ref.v1`，避免大图 Base64 JSON 复制。
- Preview 在后端当前进程执行可信节点，不为每个节点创建隔离子进程。
- 事件追加写入 Preview 的事件文件；生产 Runtime 不走 Preview 事件持久化路径。
- 属性面板显示原始 Preview JSON。
- 已执行节点在画布节点下方显示一位小数毫秒耗时；循环体节点显示最后一次执行耗时，ForEach End 与 Parallel End 显示对应结构总耗时。
- `request_parse_ms`、`graph_execute_ms`、`event_persist_ms` 与 `response_serialize_ms` 用于阶段诊断。

Node Preview 只执行目标节点的祖先闭包。图像取参面板必须先完成上传与参数写回，再生成同一份 inline snapshot 发起 Preview。

## 发布与版本

发布会创建不可变 Workflow App Version。页面按需分页读取版本，并支持：

- 草稿与已发布版本比较
- archive/restore
- 新建 Runtime 时选择版本
- 已停止 Runtime 选择目标版本
- failed revision 重置后重新选择同一版本
- breaking contract 显式确认

Runtime 和 Trigger id 保持稳定；版本变化通过新的 revision 与递增 generation 生效。页面必须显示 active version、desired version、generation 和状态，不能把选择版本误写成创建新的 Runtime/Trigger。

## 正式 Runtime 与 Trigger

正式链路：

```text
Workflow App Version
        ↓ select/create
Workflow Runtime Revision + generation
        ↓ start
长期 Workflow Worker
        ↓ invoke / async run
Workflow Run
        ↑
Trigger Source（可选）
```

同步 invoke 用于即时请求响应，异步 run 用于持久化任务。页面按 Runtime 精确分页读取 revisions、runs 和 Trigger，不使用“项目前 100 条后再本地过滤”的不完整视图。

成功 Run 显示固定的 version、revision、generation、snapshot fingerprint 和 worker instance；切版不会改写历史 Run 来源。

## 状态恢复

- 页面进入或 WebSocket 重连后先重新读取资源快照。
- 事件流只用于增量刷新，不能替代详情接口。
- 控制动作进行中禁用重复提交。
- API 409 的 generation、版本状态或资源占用详情原样转成可操作提示。
- 浏览器离开页面不会停止长期 Runtime、Trigger 或后台任务。

公开契约见 [Workflow API](../api/workflows.md)、[Workflow App 版本](../api/workflow-app-versions.md) 和 [Workflow Runtime](workflow-runtime.md)。
