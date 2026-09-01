# Workflow 前端流程与节点通信

## 节点目录

前端通过 `GET /api/v1/workflows/node-catalog` 读取 Core Node 与 Custom Node 的统一目录，消费以下事实：

- `node_type_id`、显示名称、分类和版本来源
- 输入输出端口与 `payload_type_id`
- 参数 schema、参数 UI schema 与参数输入绑定
- runtime kind、能力标签和运行要求

画布只保存节点实例、边、分组、参数和 UI state；节点定义不复制进 Template。连线时前端先做端口与 payload 轻量校验，后端 validate 和保存接口执行最终校验。

声明参数输入绑定的字段在参数行同时显示输入框和输入端口。端口未连接时输入框编辑固定回退值；端口已连接时输入框只读并显示来源，断开后恢复固定值。参数端口仍是正式 `input_ports`，不保存前端私有转换状态，也不提供每个节点实例的动态开关。

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

## 节点组

节点组是画布布局和批量状态工具，保存在 `amvision.workflow-graph-template.v1` 的 `groups` 中。组包含 id、名称、矩形、成员、颜色、折叠、锁定和启用状态。

- 节点完全位于组矩形内时成为成员；移动组会保持成员相对位置。
- 锁定只限制编辑器拖动和 resize；删除组不会删除节点或边。
- 启用/禁用会更新成员节点的最终 `enabled` 状态。
- Runtime 只消费节点的最终启用状态；组不会创建子图、线程池、事务或隔离进程。
- Parallel 与 ForEach 的执行语义仍由对应节点定义。

文档加载、保存和 preflight 必须校验组 id、尺寸、成员存在性和重复成员。

## 图像交互取参

统一 `ImageViewer` 根据节点 `parameter_ui_schema` 提供 bbox、polygon、point、circle、line、template ROI 和 search ROI 等工具。前端不按 `node_type_id` 堆积特例。

- 参数保存原图坐标，不保存缩放后的屏幕坐标。
- 缩放、平移和高 DPI 只影响显示。
- 几何必须限制在有效图片范围；图片尺寸变化后必须重新验证。
- 交互只修改草稿，显式 Preview 或保存后才进入后端。
- Viewer 复用节点 Preview display，不创建第二份大图数据。

## ROI 边界

单个 ROI 使用 `roi.v1`，列表使用 `roi-list.v1`。ROI 是几何 payload，不等同于裁剪图、检测结果或 overlay。

- 创建节点输出合法 id、类型、几何、面积和来源元数据。
- 列表、桥接和几何转换必须显式，不用模糊字典或位置数组替代。
- Crop、测量、匹配和规则节点只消费声明支持的 ROI 类型；polygon 不会静默降级为 bbox。
- Draw ROI / Draw ROIs 只生成可视化图片，不修改输入 ROI。
- 来源尺寸、transform 和坐标系存在时必须传播并核对。
- 保存位置只决定输出文件去向，不改变 ROI payload。

Preview 与正式 Runtime 对同一 ROI 链必须得到一致结果；NaN/Infinity、无效面积、来源尺寸不一致和不支持的隐式转换返回明确错误。

公开契约见 [Workflow API](../../api/workflows.md)、[Workflow App 版本](../../api/workflow-app-versions.md) 和 [Workflow Runtime](runtime.md)。
