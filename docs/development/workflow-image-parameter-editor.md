# Workflow 图像交互取参

Workflow 编辑器已经通过统一 `ImageViewer` 支持节点 Preview 图片上的交互取参。该能力属于编辑器通用层，不属于某个空盘、满盘或模型节点的私有 UI。

## 当前入口

1. 对目标节点执行 Preview。
2. 从节点底部 Preview display 打开大图。
3. 根据节点 `parameter_ui_schema` 选择可用工具。
4. 在原图坐标系中绘制或调整几何对象。
5. 将参数写回当前节点。
6. 可直接重新 Preview，并保持图片查看器上下文。

主要代码：

- `frontend/web-ui/src/shared/ui/components/ImageViewer.vue`
- `frontend/web-ui/src/shared/ui/image-viewer/ImageGeometryEditorOverlay.vue`
- `frontend/web-ui/src/workflows/workflow-editor/preview/useWorkflowPreviewDisplays.ts`
- `frontend/web-ui/src/workflows/workflow-editor/pages/WorkflowEditorPage.vue`
- `backend/nodes/definition_metadata.py`

## 支持的交互

- bbox / rectangle ROI
- polygon / contour
- positive / negative point
- circle 与半径
- line 与方向
- template ROI + search ROI
- 网格和参考几何所需参数

工具是否出现由节点定义的 UI schema 决定。前端不能按 `node_type_id` 堆积业务特例，也不能为某个节点另做一套图片坐标系统。

## 坐标规则

- 节点参数始终保存原图坐标，不保存缩放后的屏幕坐标。
- 视口缩放、平移和高 DPI 只影响显示。
- bbox、polygon、point、circle 和 line 的编辑结果必须限制在图片有效范围。
- Preview 返回的新图片尺寸变化时，旧几何不能静默套用；应按节点定义重新验证。
- ROI 与 transform 带来源尺寸或坐标系元数据时，执行层必须核对，不能隐式按 bbox 或当前图片猜测。

## 性能边界

- Preview 上传图片先进入 LocalBuffer，再以 `image-ref.v1` 传入执行链。
- 不把大 BMP 转成 Base64 JSON 在 API、Workflow Runtime 或节点进程间反复复制。
- 图片查看器使用已有 Preview display，不为属性面板再创建重复图片副本。
- 交互只更新前端草稿；只有显式 Preview 或保存才进入后端。

## 验收

- 缩放和平移后绘制结果仍对应原图坐标。
- 修改、删除和重新选择几何对象可用。
- Template/Search 两阶段取参不会互相覆盖。
- 写回后重新 Preview 使用新参数，查看器可重新打开目标节点结果。
- 无 UI schema 的节点不显示无效工具。
- 亮色、暗色和高分辨率图片下工具、handle 与 overlay 可辨认且不遮挡主要内容。
