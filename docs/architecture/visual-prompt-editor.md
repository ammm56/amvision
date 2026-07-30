# Visual Prompt 图片编辑

## 目的和边界

本文固定 workflow 图片 Prompt 的通用编辑边界。该能力属于 Core 节点和编辑器，不属于 SAM3 专用 UI，SAM3、YOLOE、OpenCV ROI 和后续交互式视觉节点应复用同一套图片、坐标和 ObjectStore 规则。

当前协议固定为 `prompt-regions.v1`。开发阶段直接同步所有节点包、示例和测试，不创建 `v2`，也不长期维护旧字段。

## 原子编辑节点

- Point Prompt：在同一节点内分别维护 Positive 与 Negative 点数组，至少需要一个 Positive 点。
- Box Prompt：连续拖拽创建多个 `bbox_xyxy`，每个 Box 表示一个独立对象。
- Polygon Prompt：连续创建多个多边形，每个多边形至少三个点且不能自交。
- Mask Editor：Brush、Eraser、Fill、Clear、Undo、Redo，输出二值 `image-ref.v1`。
- Mask Prompt：把 Mask 图片引用包装为 `prompt-regions.v1`。

默认几何只用于草稿显示，只有“应用”操作才写回节点参数。图片变化后旧坐标或 Mask 必须失效。前端校验用于防呆，后端必须再次检查边界、面积、拓扑、前景像素和尺寸。

“应用参数”只负责校验并写回当前节点，不自动运行 Preview；写回成功或失败必须在
ImageViewer 内给出明确反馈。“应用并 Preview”在写回成功后只启动一次节点级 Preview，
两者不能复用成两个同时触发的异步事件。

Point、Box、Polygon 应用时同时写入只读的 `prompt_source_identity`。节点再次执行时用当前 image-ref 的稳定来源重新计算标识；memory 图片必须携带内容 SHA，storage 图片使用 object key，`image_handle` 只作为旧 payload 缺少稳定来源时的单次执行兜底。标识不一致时直接拒绝旧坐标，不能把当前图片重新包装进 payload 后绕过失效检查。

Point、Box、Polygon 编辑面板每次打开时必须以当前 workflow 图中的节点参数初始化草稿，
不能把最后一次 Preview 携带的 `initial_*` 数据当成最终状态。应用参数后应立即同步当前
调试图的交互元数据；关闭面板、重新打开面板或页面重新载入后，已有 Positive/Negative
点数组、Box 数组和 Polygon 数组都必须重新绘制，不要求先执行新的 Preview。

## 可复用几何编辑层

图片上的 Point、Box 和 Polygon 不由各节点分别实现鼠标交互。前端统一使用共享的
`ImageGeometryEditorOverlay`，它只处理图片坐标系中的几何集合，不依赖 SAM3 节点或
Workflow API。后续数据集标注、OpenCV ROI 和测量工具可复用同一层。

- Point：每个点是独立条目，悬停后显示单项删除入口；Positive 与 Negative 使用不同颜色，
  但共同写回同一个对象的点数组。
- Box：每个框可单独选中、删除、拖动；四条边和四个角均可缩放。
- Polygon：每个多边形可单独选中、删除、整体拖动；顶点可单独拖动，外接框的边和角可按
  比例缩放整个多边形。
- 所有操作都限制在源图边界内；零面积 Box、少于三个点或自交 Polygon 不能应用。
- 打开面板时已有几何视为“已应用”；任何新增、删除、移动或缩放后切换为“有未应用的修改”。
  “应用参数”在等待写回、成功和失败时必须显示持续可见的状态，不能只依赖瞬时提示。

## Mask 持久化

Mask Editor 的已应用状态由 `mask_object_key` 与
`mask_source_identity` 共同组成，两个字段必须原子写回节点。交互面板从
节点级 Preview 的 Mask tool 读取明确的 `source_identity`，不能通过通用
`apply_parameters` 旁路传递。应用时按
`project/application/node/content-sha256` 的 ObjectStore 路径保存不可变二值
PNG。相同内容会复用，旧工作流版本引用不会被后续编辑覆盖。Prompt 资源回收
必须由应用资源清理策略统一处理，不能在新 Mask 写入时直接删除旧内容。当前编辑器删除
Mask Editor 只修改尚未保存的图，不立即删除文件；应用保存成功后，以当前模板仍引用的
`mask_object_key` 为准清理未引用 PNG。删除整个 Workflow Application 时删除该应用的
`prompt-masks` 根目录。

重新打开编辑面板时，节点级 Preview 会校验 `mask_source_identity`。源图未
变化时，Mask tool 返回当前 `mask_object_key`，前端把已有二值 Mask 重新绘制
到草稿画布后继续编辑；源图变化时不加载旧 Mask，也不产生 `mask_image`。

- 画布内存只用于编辑草稿。
- 未点击“应用”时，浏览器可以维护一张全透明草稿画布，但不得上传 ObjectStore、
  写入 workflow 或产生 `mask_image`。
- 全黑 Mask 不是默认值，也不是有效 Prompt；没有前景像素时“应用”必须保持禁用。
- 应用时通过 Project 写接口保存 PNG。
- object key 使用
  `projects/<project_id>/inputs/workflow-applications/<application_id>/prompt-masks/<node_id>/<content_sha256>.png`。
- workflow JSON 只保存 `mask_object_key`，不保存 Base64。
- 服务端统一二值化为 0/255，并拒绝空文件、无法解码图片和无前景 Mask。
- 浏览器 Canvas 的 Eraser 通过 alpha 清除像素；服务端解码 RGBA PNG 时必须把
  alpha 为 0 的像素视为背景，不能按灰度解码后丢失透明擦除结果。
- 已应用 Mask 使用唯一 ObjectStore key；同一 runtime scope 内文件版本未变化时，
  Mask Editor、Mask Prompt 和模型消费节点共用只读解码缓存，不重复读盘和 PNG 解码。
- 缓存有条目和字节硬上限；Mask key 或文件版本变化时自动失效，应用删除、scope 回收和
  runtime 停止时释放。
- workflow 同时保存源图稳定标识；即使新旧图片尺寸相同，只要 object key 或内容 SHA 变化，旧 Mask 也必须失效。每次 Preview 随机生成的 memory `image_handle` 不能作为跨运行失效依据。
- 再次打开编辑器时从 ObjectStore 读取已有 Mask，恢复为半透明画布后继续编辑。
- “应用参数”完成后，当前 Preview display 应立即切换到新 ObjectStore Mask；
  关闭再打开面板不要求额外执行 Preview，也不能恢复到上一次 Preview 的旧 Mask。
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

同一 `prompt_id` 表示一个对象。Point Prompt 节点中的 Positive/Negative 点数组使用同一个
`prompt_id`，共同约束同一个对象，并且至少包含一个 Positive Point。Box Prompt 与 Polygon
Prompt 节点可一次保存多个几何对象；节点会为每个 Box 或 Polygon 生成独立且稳定的
`prompt_id`。Mask 仍是一张 Mask 对应一个对象。任何对象都不能在同一个 `prompt_id` 下混合
Point、Box、Polygon 或 Mask 类型。

批量 Visual Prompt Editor 只能在对象列表、原子工具和后端分组语义全部一致，并且原子节点通过现场稳定性验收后进入 Catalog。禁止把每个点击点分别执行分割，再在界面上伪装成多点对象。当前实现阶段先完成并验证原子节点与 Mask Editor，不提前发布半成品多对象编辑器。

## 验收

- Point、Box、Polygon 只有应用后生效；“应用参数”成功时必须立即显示写回成功反馈。
- Point 同时保存多个 Positive/Negative 点；Box 与 Polygon 可分别保存多个独立对象。
- Point 可单项删除；Box 与 Polygon 可单项删除、移动和缩放；Polygon 顶点可编辑。
- Point、Box、Polygon 应用后关闭并重新打开编辑面板，已保存集合仍完整绘制。
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
- 删除 Mask Editor 并成功保存应用后，其未引用 PNG 被清理；删除应用后其 Prompt Mask
  根目录被清理。
- 相同源图修改 Prompt 时模型视觉 Backbone 不重复执行。
