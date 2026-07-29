# Visual Prompt 图片编辑

## 目的和边界

本文固定 workflow 图片 Prompt 的通用编辑边界。该能力属于 Core 节点和编辑器，不属于 SAM3 专用 UI，SAM3、YOLOE、OpenCV ROI 和后续交互式视觉节点应复用同一套图片、坐标和 ObjectStore 规则。

当前协议固定为 `prompt-regions.v1`。开发阶段直接同步所有节点包、示例和测试，不创建 `v2`，也不长期维护旧字段。

## 原子编辑节点

- Point Prompt：单击创建一个点，Positive/Negative 可切换。
- Box Prompt：拖拽创建 `bbox_xyxy`。
- Polygon Prompt：点击顶点并闭合，至少三个点且不能自交。
- Mask Editor：Brush、Eraser、Fill、Clear、Undo、Redo，输出二值 `image-ref.v1`。
- Mask Prompt：把 Mask 图片引用包装为 `prompt-regions.v1`。

默认几何只用于草稿显示，只有“应用”操作才写回节点参数。图片变化后旧坐标或 Mask 必须失效。前端校验用于防呆，后端必须再次检查边界、面积、拓扑、前景像素和尺寸。

Point、Box、Polygon 应用时同时写入只读的 `prompt_source_identity`。节点再次执行时用当前 image-ref 的稳定来源重新计算标识；memory 图片必须携带内容 SHA，storage 图片使用 object key，`image_handle` 只作为旧 payload 缺少稳定来源时的单次执行兜底。标识不一致时直接拒绝旧坐标，不能把当前图片重新包装进 payload 后绕过失效检查。

## Mask 持久化

- 画布内存只用于编辑草稿。
- 未点击“应用”时，浏览器可以维护一张全透明草稿画布，但不得上传 ObjectStore、
  写入 workflow 或产生 `mask_image`。
- 全黑 Mask 不是默认值，也不是有效 Prompt；没有前景像素时“应用”必须保持禁用。
- 应用时通过 Project 写接口保存 PNG。
- object key 使用 `projects/<project_id>/inputs/workflow-applications/<application_id>/prompt-masks/<id>.png`。
- workflow JSON 只保存 `mask_object_key`，不保存 Base64。
- 服务端统一二值化为 0/255，并拒绝空文件、无法解码图片和无前景 Mask。
- workflow 同时保存源图稳定标识；即使新旧图片尺寸相同，只要 object key 或内容 SHA 变化，旧 Mask 也必须失效。每次 Preview 随机生成的 memory `image_handle` 不能作为跨运行失效依据。
- 再次打开编辑器时从 ObjectStore 读取已有 Mask，恢复为半透明画布后继续编辑。
- Undo/Redo 只保留有限历史，当前最多 12 个完整画布快照；鼠标移动期间不扫描整张图片，避免长时间编辑造成浏览器内存和 CPU 持续增长。

源图发生变化时，旧 Mask 立即停止产生 `mask_image`，但 Mask Editor 仍应产生新源图的
`debug_preview`，使编辑器可以清除旧引用并重新绘制。不能先抛出错误再要求通过同一个
调试图入口修复，否则会形成交互死锁。

## 节点级编辑 Preview

含有 `prompt.editor` capability 的 Point、Box、Polygon、Mask 节点共用 Workflow
Preview 的节点级执行机制。画布节点右键菜单提供 `Preview Node Run`：

1. 请求使用 `execution_scope.kind=node` 和 `target_node_id`。
2. 后端只执行目标节点的全部祖先依赖和目标节点。
3. 不执行目标节点的下游节点；与本次祖先闭包无关的模型 session 不加载，也不释放同一应用已经持有的模型 lease。
4. 目标节点的 `debug_preview` 返回后只刷新节点调试图，不自动打开 ImageViewer；用户点击调试图后才进入编辑面板。
5. 用户应用参数后，再执行一次相同范围的节点级 Preview。

“应用并 Preview”是一个原子编辑动作。ImageViewer 只能向父页面发送一次组合事件；父页面
必须先等待 Mask 上传、`mask_object_key` 与 `mask_source_identity` 写回当前图，再基于更新后
的图快照启动节点级 Preview。禁止把异步“应用”和“Preview”作为两个并列事件触发。
上传和参数写回期间，节点应用按钮、页面保存、完整 Preview 和节点级 Preview 都必须锁定，
避免保存旧参数或生成旧快照。

节点级 Preview 只属于编辑器调试协议，不进入生产 AppRuntime。完整 Preview 和正式
AppRuntime 仍按完整图执行，不能因为编辑能力引入部分成功或空 Prompt。

`Preview Node Run` 位于节点右键菜单最后一项，在完整 `Preview Run` 之后。两者都只执行
用户明确选择的动作：节点级执行完成后不能附带打开编辑器等第二个交互动作。

完整 Preview 的最终状态可以是 `failed`，但本次已经完成节点的 `node_records` 仍应
保留。前端必须用本次运行记录刷新调试图，不能回退显示上一次成功运行。节点级 Preview
同样保留目标节点记录，以便 Point、Box、Polygon 和 Mask 共用同一显示链路。

## 多对象语义

同一 `prompt_id` 表示一个对象。一个对象可以有多个 Positive/Negative Point；至少包含一个 Positive Point。Box、Polygon、Mask 当前各自作为单一对象提示，不能与同一 id 的其他类型混用。

批量 Visual Prompt Editor 只能在对象列表、原子工具和后端分组语义全部一致，并且原子节点通过现场稳定性验收后进入 Catalog。禁止把每个点击点分别执行分割，再在界面上伪装成多点对象。当前实现阶段先完成并验证原子节点与 Mask Editor，不提前发布半成品多对象编辑器。

## 验收

- Point、Box、Polygon 只有应用后生效。
- 越界点、零面积 Box、自交 Polygon、少于三个点的 Polygon 无法应用。
- Mask 支持撤销重做；空 Mask、无前景 Mask和尺寸不匹配 Mask 无法应用。
- 有效 Mask 必须同时写回 `mask_object_key` 和当前源图的
  `mask_source_identity`；缺少任一字段均视为尚未应用，不能流入 Mask Prompt。
- 同一 Base64 或 memory 图片跨 Preview 的 `content_sha256` 保持一致；临时
  `image_handle` 变化不能使已应用 Mask 失效。
- “应用并 Preview”只产生一次节点级 Preview，并且该 Preview 的 inline template 已包含
  本次上传返回的 `mask_object_key`。
- 未应用 Mask 时，Mask Editor 只有 `debug_preview`，没有 `mask_image`。
- 下游失败时，本次运行已经完成的上游调试图仍可查看。
- `Preview Node Run` 不执行选中节点的任何下游节点。
- workflow 文档中不存在 Mask Base64。
- 相同源图修改 Prompt 时模型视觉 Backbone 不重复执行。
