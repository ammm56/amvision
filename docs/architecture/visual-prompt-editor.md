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

Point、Box、Polygon 应用时同时写入只读的 `prompt_source_identity`。节点再次执行时用当前 image-ref 的内容 SHA、image handle 或 object key 重新计算标识；标识不一致时直接拒绝旧坐标，不能把当前图片重新包装进 payload 后绕过失效检查。

## Mask 持久化

- 画布内存只用于编辑草稿。
- 应用时通过 Project 写接口保存 PNG。
- object key 使用 `projects/<project_id>/inputs/workflow-applications/<application_id>/prompt-masks/<id>.png`。
- workflow JSON 只保存 `mask_object_key`，不保存 Base64。
- 服务端统一二值化为 0/255，并拒绝空文件、无法解码图片和无前景 Mask。
- workflow 同时保存源图稳定标识；即使新旧图片尺寸相同，只要 object key、image handle 或内容 SHA 变化，旧 Mask 也必须失效。
- 再次打开编辑器时从 ObjectStore 读取已有 Mask，恢复为半透明画布后继续编辑。
- Undo/Redo 只保留有限历史，当前最多 12 个完整画布快照；鼠标移动期间不扫描整张图片，避免长时间编辑造成浏览器内存和 CPU 持续增长。

## 多对象语义

同一 `prompt_id` 表示一个对象。一个对象可以有多个 Positive/Negative Point；至少包含一个 Positive Point。Box、Polygon、Mask 当前各自作为单一对象提示，不能与同一 id 的其他类型混用。

批量 Visual Prompt Editor 只能在对象列表、原子工具和后端分组语义全部一致，并且原子节点通过现场稳定性验收后进入 Catalog。禁止把每个点击点分别执行分割，再在界面上伪装成多点对象。当前实现阶段先完成并验证原子节点与 Mask Editor，不提前发布半成品多对象编辑器。

## 验收

- Point、Box、Polygon 只有应用后生效。
- 越界点、零面积 Box、自交 Polygon、少于三个点的 Polygon 无法应用。
- Mask 支持撤销重做；空 Mask、无前景 Mask和尺寸不匹配 Mask 无法应用。
- workflow 文档中不存在 Mask Base64。
- 相同源图修改 Prompt 时模型视觉 Backbone 不重复执行。
