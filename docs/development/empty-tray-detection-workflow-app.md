# 空盘检测 Workflow App 开发说明

## 适用范围

本文档固定 `workflow-app-20260710020359` 的开发目标、实现边界和节点组合规划，防止后续实现时把空盘检测、满盘检测、缺料检测和错位检测混在同一个应用里。

当前应用只回答一个问题：输入托盘图像是否为正常空盘。

## 当前应用

- Workflow App：`workflow-app-20260710020359`
- 应用名称：空盘检测应用
- Template：`workflow-graph-20260710020359`
- Template 文件：`data/files/workflows/projects/project-1/templates/workflow-graph-20260710020359/versions/1.0.0/template.json`
- Application 文件：`data/files/workflows/projects/project-1/applications/workflow-app-20260710020359/application.json`

当前应用已经有两个输入：

- `request_image_ref`：生产默认输入，适合 ZeroMQ / LocalBuffer / BGR24 高性能链路。
- `request_image_base64`：HTTP 调试或前端 Preview Run 兜底输入。

## 明确不做

- 不在本应用中实现满盘检测通过逻辑。
- 不在本应用中实现缺料检测通过逻辑。
- 不在本应用中实现独立错位检测应用逻辑。
- 不在本阶段接 YOLO 分类或检测模型。
- 不新增 `tray-empty-check`、`tray-slot-occupancy` 这类业务专用节点。
- 不新增专用节点包。
- 不把大量业务判断写死到 Python 节点代码里。

如果现有节点能力不足，只补通用基础节点。基础节点必须能被后续满盘检测、缺料检测、错位检测、阵列 ROI 检测等其他 workflow app 复用。

## 样本用途

开发图片目录：

`data/files/developer/空盘满盘检测`

当前样本：

- `空盘_1080p_01.jpg`：空盘检测的正常样本和空盘参考图。
- `空盘_1080p_圆_01.jpg`：圆孔特征模板。
- `空盘_1080p_插槽_01.jpg`：插槽特征模板。
- `满盘_1080p_01.jpg`：空盘检测负样本。
- `缺料_1080p_01.jpg`、`缺料_1080p_02.jpg`、`缺料_1080p_03.jpg`：空盘检测负样本。
- `错位_1080p_01.jpg`：空盘检测负样本，用于验证定位或对齐失败。
- 720p 图片：分辨率缩放和鲁棒性辅助验证，不作为第一阶段主调参样本。

满盘、缺料和错位图片在本应用中只用于验证“不是正常空盘”能否被拒绝，不用于建立满盘应用的通过规则。

## 输出目标

正常空盘输出：

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "is_empty": true,
    "state": "empty_ok",
    "tray_present": true,
    "alignment_ok": true,
    "abnormal_area_ratio": 0.001,
    "abnormal_region_count": 0,
    "reason": "empty tray passed"
  }
}
```

非空盘、缺料、错位或其它异常输出：

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "is_empty": false,
    "state": "not_empty_or_abnormal",
    "tray_present": true,
    "alignment_ok": false,
    "abnormal_area_ratio": 0.083,
    "abnormal_region_count": 12,
    "reason": "empty tray check failed"
  }
}
```

字段含义：

- `is_empty`：是否为正常空盘。
- `state`：空盘检测状态，不表达满盘检测状态。
- `tray_present`：托盘是否能被基础定位链识别。
- `alignment_ok`：基础定位或对齐是否满足当前空盘检测要求。
- `abnormal_area_ratio`：相对空盘参考图的异常前景面积占比。
- `abnormal_region_count`：异常连通区域数量。
- `reason`：简短原因。

## 节点总原则

本应用用基础节点组合完成目标。节点分支可同时保留在同一个 workflow app 中，不使用的分支通过 `enabled=false` 关闭。

前端和后端当前都支持节点禁用：

- 前端节点可显示禁用状态。
- 后端 `WorkflowGraphExecutor` 会跳过 `enabled=false` 的节点。

调试阶段可打开 Image Preview、Mask Overlay、Draw Regions 等节点；生产链路默认关闭这些节点，避免图片编码和预览输出拖慢速度。

## 公共输入层

公共输入层保持当前结构：

```text
request_image_base64
 -> Image Base64 Decode
 -> Image Ref Coalesce fallback

request_image_ref
 -> Image Ref Coalesce primary
```

输出统一为当前待检测图像：

```text
Image Ref Coalesce.image
```

生产链路优先使用 `request_image_ref`。

## 分支 A：空盘参考差分主线

默认启用。第一阶段优先完成这条主线。

目标：用当前图像与 `空盘_1080p_01.jpg` 的差异判断是否为正常空盘。

节点链路：

```text
Image Ref Coalesce
 -> Perspective Transform 或固定 ROI Crop
 -> Load Local Image: 空盘_1080p_01.jpg
 -> 对参考图执行同样的 Perspective Transform 或固定 ROI Crop
 -> Image Diff
 -> Absdiff Threshold
 -> Morphology
 -> Connected Components
 -> Regions Count
 -> Regions Area Ratio
 -> Range Check
 -> Presence Check
 -> Process Decision
 -> Response Envelope
```

第一阶段允许先不用自动定位，使用固定 ROI 或固定 `source_points` 把链路跑通。固定参数跑通后，再加定位和对齐校验。

判定规则：

- `abnormal_region_count <= max_empty_abnormal_regions`
- `abnormal_area_ratio <= max_empty_abnormal_area_ratio`
- 上述条件都满足时，`is_empty=true`。

满盘、缺料、错位图片在这条主线中应该触发 `is_empty=false`。

## 分支 B：圆孔特征定位校验

默认禁用，调试时启用。该分支只为当前空盘检测提供定位可信度，不做独立错位检测应用。

目标：用 `空盘_1080p_圆_01.jpg` 或 Hough Circles 检查托盘圆孔特征是否稳定。

节点链路：

```text
Image Ref Coalesce
 -> Template Match: 空盘_1080p_圆_01.jpg
 -> Regions Filter
 -> Regions Count
 -> Hole Pattern Check
 -> Range Check
```

可选链路：

```text
Image Ref Coalesce
 -> Grayscale / CLAHE
 -> Hough Circles
 -> Hole Pattern Check
 -> Range Check
```

用途：

- 检查托盘是否存在。
- 检查托盘是否明显错位。
- 检查圆孔数量、节距和排列是否稳定。

错位样本只用于验证该分支能失败。

## 分支 C：插槽模板辅助校验

默认禁用，作为备选验证分支。

目标：使用 `空盘_1080p_插槽_01.jpg` 验证空盘槽位结构是否可见和稳定。

节点链路：

```text
Image Ref Coalesce
 -> Template Match: 空盘_1080p_插槽_01.jpg
 -> Regions Filter
 -> Regions Count
 -> Presence Check
```

用途：

- 辅助确认槽位结构可见。
- 辅助排查强反光、遮挡和局部错位。
- 不作为第一阶段唯一判断来源。

## 分支 D：槽位 ROI 逐格判断

默认禁用。等通用 ROI 基础节点补齐后再启用。

目标：在标准图中按槽位 ROI 逐格判断空盘状态。该分支是后续提高稳定性的重点，但不应写成业务专用节点。

目标链路：

```text
Perspective Transform 后标准图
 -> ROI Grid Create
 -> For Each ROI
    -> Value To ROI
    -> Crop 当前槽位
    -> Crop 空盘参考图对应槽位
    -> Image Diff
    -> Absdiff Threshold
    -> Connected Components
    -> Regions Area Ratio
    -> Range Check
 -> Array Summary
 -> Process Decision
```

需要补的通用基础节点：

- `core.vision.roi-grid-create`：按行列、起点、槽位尺寸和间距生成 ROI 列表。
- `core.logic.value-to-roi`：把 value 中的 ROI 对象转换为 `roi.v1`。
- `core.logic.array-summary`：汇总多个 ROI 判断结果。

这些节点不得包含空盘业务语义，只处理 ROI、value、array 和基础统计。

## 调试预览分支

默认禁用。

可放入同一 workflow app 中：

```text
Mask Overlay
Draw Regions
Image Preview
Gallery Preview
```

用途：

- 查看差分图。
- 查看阈值图。
- 查看异常连通区域。
- 查看对齐后的标准图。

生产运行时默认关闭，避免返回 base64 图片或生成 overlay 图造成额外耗时。

## 默认启用状态

第一阶段：

| 分支 | 默认状态 | 说明 |
| --- | --- | --- |
| 公共输入层 | 启用 | 必须保留 |
| 分支 A 空盘参考差分主线 | 启用 | 第一阶段主判断 |
| 分支 B 圆孔特征定位校验 | 禁用 | 调试时打开 |
| 分支 C 插槽模板辅助校验 | 禁用 | 调试时打开 |
| 分支 D 槽位 ROI 逐格判断 | 禁用 | 待基础节点补齐后启用 |
| 调试预览分支 | 禁用 | 调参时打开 |

## 实施顺序

1. 保留现有 `request_image_ref` 和 `request_image_base64` 输入。
2. 完成分支 A：空盘参考差分主线。
3. 接入 `Response Envelope`，输出统一 JSON。
4. 使用 `空盘_1080p_01.jpg` 验证 `is_empty=true`。
5. 使用 `满盘_1080p_01.jpg`、`缺料_1080p_*.jpg`、`错位_1080p_01.jpg` 验证 `is_empty=false`。
6. 接入分支 B 和分支 C，默认禁用，只用于调试。
7. 如果需要槽位逐格判断，再补通用 ROI 基础节点并接入分支 D。
8. 调参稳定后再创建独立满盘检测 workflow app，不在当前 app 中增加满盘通过逻辑。

## 验收条件

- `空盘_1080p_01.jpg` Preview Run 返回 `is_empty=true`。
- `满盘_1080p_01.jpg` Preview Run 返回 `is_empty=false`。
- `缺料_1080p_01.jpg`、`缺料_1080p_02.jpg`、`缺料_1080p_03.jpg` Preview Run 返回 `is_empty=false`。
- `错位_1080p_01.jpg` Preview Run 返回 `is_empty=false` 或 `alignment_ok=false`。
- 默认启用节点只包含空盘检测主线。
- 满盘检测逻辑没有混入当前应用。
- 没有新增业务专用节点或专用节点包。
- 新增节点如有必要，只能是通用基础节点。

## 后续满盘检测应用边界

空盘检测确认稳定后，再新增独立 workflow app 做满盘检测。

满盘检测应用可以复用：

- 公共输入层。
- 透视变换或固定 ROI。
- 圆孔定位校验。
- 插槽模板匹配。
- ROI Grid。
- For Each ROI。
- Array Summary。

但满盘检测的判定规则、参考图和输出状态必须独立维护，不写入 `workflow-app-20260710020359`。
