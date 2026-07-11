# Workflow 图像交互取参规划

本文档记录 ROI、找圆、找直线、找边、模板区域等 VisionMaster / Halcon 式图像交互取参能力的实现规划。该能力属于 workflow editor 通用能力，不属于空盘检测、满盘检测或某个业务节点的专用实现。

## 当前 Preview Run 超时

当前图编辑器 Preview Run 已调整为更适合视觉调试的默认值：

- 后端 `create_preview_run` 默认执行超时：120 秒。
- 前端图编辑器创建 Preview Run 时显式传入 `timeoutSeconds=120`。
- sync 等待超时约为 140 秒：120 秒执行时间 + 15 秒子进程启动宽限 + 5 秒等待余量。

该调整只解决调试图较大、节点较多时的等待上限问题，不替代 workflow 自身性能优化。大循环、大图和大量中间结果仍应减少不必要的 preview 节点，并默认关闭完整 `node_records`。

## 审查结论

当前规划方向是正确的：以节点底部 preview display 为入口，复用现有 `WorkflowNodePreviewDisplay.vue`、`useWorkflowPreviewDisplays.ts` 和 `ImageViewer.vue`，不在属性面板里另做缩略图。规划仍需要补齐以下落地点，后续实现必须按这些边界收口：

1. 只靠节点参数开关不够安全。生产 runtime 可能直接执行已保存的 workflow template，如果用户忘记关闭调试面板，仍会发生 BGR24 / BufferRef / FrameRef 到 PNG/JPEG/base64 的转换。因此必须使用双开关：节点参数 `debug_image_panel_enabled=true`，并且执行元数据 `debug_image_panels_enabled=true` 时，节点才生成调试图片。
2. 现有前端只从 `node_records.outputs` 中识别 `payload.type` 以 `-preview` 结尾的输出。普通视觉节点要显示节点底部图片，必须输出兼容 `image-preview` 或 `gallery-preview` 的 `debug_preview` 输出，而不是发明另一套显示路径。
3. 现有图编辑器 `retain_node_records_enabled` 只按 `node_type_id.endsWith('-preview')` 判断。后续需要改成同时检查启用节点中是否存在 `debug_image_panel_enabled=true`，否则普通节点虽然生成了 `debug_preview`，前端也拿不到 node_records。
4. `NodeDefinition.metadata` 和 `parameter_ui_schema` 前后端都已经存在，可以承载 `parameter_assist`，不需要先改合同大结构。但具体 metadata 结构要统一，避免每个节点自己造字段。
5. `ImageViewer` 当前是只读查看器，后续要改成统一交互式图片面板时，需要保留只读模式。生产 runtime 的图片查看仍是只读；只有 workflow graph editor 传入交互上下文时才允许 overlay 编辑和参数写回。

## 目标边界

- 节点执行仍只读取稳定的 `parameters`，不读取前端临时交互状态。
- 前端负责显示图像、绘制 overlay、把交互结果转换为参数并写回节点。
- 后端节点负责按参数执行算法，返回结果、摘要和可选调试图；调试图必须同时满足节点参数开关和 execution metadata 总开关。
- 参数保存仍落在 workflow template 的节点 `parameters` 中，便于版本化、复制、回滚和现场调整。
- 不新增空盘检测专用节点；缺基础能力时只补通用节点。

## 现有相关节点清单

| 类型 | 节点 | 当前用途 | 需要的图像交互 |
| --- | --- | --- | --- |
| ROI 创建 | `core.vision.roi-create` | 创建 bbox / polygon ROI | 在图上画 bbox / polygon |
| ROI 网格 | `core.vision.roi-grid-create` | 按行列生成槽位 ROI | 在图上选原点、单格尺寸、行列方向和步距 |
| ROI 转换 | `core.logic.value-to-roi` | 把 value 转成 ROI | 跟随 ROI 创建节点，通常不单独交互 |
| 裁剪 | `custom.opencv.crop` | 根据输入 `roi.v1` 裁图 | 不取参，只消费 ROI |
| 透视变换 | `custom.opencv.perspective-transform` | 四点透视矫正 | 在图上点选 4 个角点，写回 `source_points` |
| 平面变换 | `custom.opencv.planar-transform-bridge` | 透视结果和 ROI 坐标互转 | 复用透视四点和输出尺寸 |
| 轮廓转 ROI | `core.vision.roi-from-contour` | 从 contour 生成 ROI | 参数来自 contour，后续可在结果图上确认 contour 或选择 index |
| Hough 圆 | `custom.opencv.hough-circles` | 找圆孔或圆形特征 | 在图上选搜索 ROI、估计半径范围和目标圆 |
| Hough 线 | `custom.opencv.hough-lines` | 找直线或边线 | 在图上选搜索 ROI、线段、角度范围和方向 |
| 拟合线 | `custom.opencv.fit-line` | 从轮廓拟合直线 | 在图上选 contour 或搜索 ROI |
| 最小外接矩形 | `custom.opencv.min-area-rect` | 计算旋转矩形 | 在图上选择候选 contour 或结果 index |
| 最小外接圆 | `custom.opencv.min-enclosing-circle` | 计算圆形区域 | 在图上选择候选 contour 或结果 index |
| 模板匹配 | `custom.opencv.template-match` | 局部模板定位 | 在图上框选模板 ROI 和搜索 ROI |
| 画 ROI | `custom.opencv.draw-roi` | 调试叠加 ROI | 可显示参数结果，不负责取参 |
| 画圆 | `custom.opencv.draw-circles` | 调试叠加圆 | 可显示参数结果，不负责取参 |
| 画线 | `custom.opencv.draw-lines` | 调试叠加线 | 可显示参数结果，不负责取参 |
| 测量 | `custom.opencv.caliper-edge`、`custom.opencv.line-angle`、`custom.opencv.point-to-line-distance`、`custom.opencv.circle-diameter` | 边缘和几何测量 | 需要线、点、圆、搜索 ROI 的统一编辑能力 |

以上节点已经覆盖空盘检测第一阶段需要的主要基础能力。当前缺口不是节点不存在，而是参数仍主要依赖文本输入，现场调试效率和准确性不足。

## 图片面板交互设计

### 节点底部调试图片面板

图像交互取参不放在属性面板里显示缩略图，而是沿用现有 Image Preview / Gallery Preview 的节点底部显示方式。节点参数中增加调试开关，默认关闭；只有编辑调试时手动打开，Preview Run 才在节点底部输出缩略图。

- 默认关闭：生产 `WorkflowAppRuntime`、TriggerSource 和模型高帧率调用不生成缩略图，避免把 BGR24 / BufferRef / FrameRef 转成 PNG/JPEG/base64 造成额外耗时。
- 手动打开：编辑调试时在节点参数里打开统一参数 `debug_image_panel_enabled=true`。生产 runtime 即使该参数误开，只要 execution metadata 没有打开 `debug_image_panels_enabled=true`，节点也不能生成调试图片。
- 输出位置：缩略图显示在节点卡片底部，和现在 `core.io.image-preview`、`custom.opencv.gallery-preview` 的体验一致。
- 图像来源：优先使用该节点本次执行的输入图或输出图；需要额外叠加 ROI、circle、line 时，节点通过 `debug_preview` 输出兼容 `image-preview` 的 payload，并携带 overlay 数据。
- 返回方式：调试面板优先使用 `storage-ref` / Preview Run artifact，避免大图 inline-base64；只有小图或明确配置时才使用 inline-base64。
- 节点记录：打开调试面板时 Preview Run 需要保留对应节点记录；关闭时不保留完整 `node_records`，只保留最终输出和错误信息。前端 `retain_node_records_enabled` 判定必须同时识别 `*-preview` 节点和 `debug_image_panel_enabled=true` 的普通节点。

### 统一交互式图片面板

双击节点底部缩略图进入统一交互式图片面板。现有 `WorkflowNodePreviewDisplay.vue`、`useWorkflowPreviewDisplays.ts` 和共享 `ImageViewer.vue` 是改造基础，不再新增一套独立图片查看器。

- 复用现有大图查看、缩放、拖拽和双击查看逻辑。
- 在 `ImageViewer` 基础上增加 overlay 编辑层，支持 bbox、polygon、circle、line、point、grid、template-region。
- 面板右侧或顶部显示当前工具对应的参数字段，参数变化和 overlay 同步。
- 确认后写回当前节点 `parameters`，取消时不修改参数。
- 坐标以原始图像像素为准，不以显示缩放坐标为准。
- 交互式图片面板只在 workflow graph editor 中可编辑；生产 runtime 返回的图片查看仍按普通只读预览处理。

### 工具和参数映射

| 工具 | 写回参数 | 适用节点 |
| --- | --- | --- |
| bbox | `bbox_xyxy` | `core.vision.roi-create`、搜索 ROI 类节点 |
| polygon | `polygon_xy`、`source_points`；四点透视时同时估算 `output_width`、`output_height` | `core.vision.roi-create`、`custom.opencv.perspective-transform` |
| circle | `center_x`、`center_y`、`radius`、`min_radius`、`max_radius` | `custom.opencv.hough-circles`、`custom.opencv.min-enclosing-circle` |
| line | `x1`、`y1`、`x2`、`y2`、`angle_deg` | `custom.opencv.hough-lines`、`custom.opencv.fit-line`、测量节点 |
| grid | `origin_x`、`origin_y`、`roi_width`、`roi_height`、`step_x`、`step_y`、`rows`、`columns` | `core.vision.roi-grid-create` |
| template-region | `template_roi`、`search_roi` 或输入模板图来源 | `custom.opencv.template-match` |

## 节点定义扩展方式

节点定义中增加前端可读的参数辅助信息，统一放在 `metadata.parameter_assist`。`parameter_ui_schema` 继续负责普通参数表单，不承载复杂图像交互状态。

节点参数统一增加调试开关，默认关闭：

```json
{
  "debug_image_panel_enabled": {
    "type": "boolean",
    "title": "调试图片面板",
    "description": "仅 workflow graph editor Preview Run 调试使用；生产 runtime 默认不会生成调试缩略图。",
    "default": false
  },
  "debug_image_panel_transport_mode": {
    "type": "string",
    "title": "调试图返回方式",
    "enum": ["storage-ref", "inline-base64"],
    "default": "storage-ref"
  }
}
```

节点 metadata 示例：

```json
{
  "parameter_assist": [
    {
      "image_input_port": "image",
      "preview_output_port": "debug_preview",
      "coordinate_space": "source-image",
      "tools": [
        {
          "tool": "polygon",
          "label": "透视四点",
          "target_parameters": ["source_points", "output_width", "output_height"],
          "min_points": 4,
          "max_points": 4
        }
      ]
    }
  ],
  "debug_image_panel": {
    "enabled_parameter": "debug_image_panel_enabled",
    "transport_parameter": "debug_image_panel_transport_mode",
    "preview_output_port": "debug_preview",
    "default_transport_mode": "storage-ref"
  }
}
```

节点输出约定：

- 需要图像交互取参的普通节点新增可选输出端口 `debug_preview`，payload type 使用 `response-body.v1` 或后续统一的 preview body type。
- `debug_preview` 的内容继续使用现有 `image-preview` / `gallery-preview` 结构，确保 `useWorkflowPreviewDisplays.ts` 可以复用。
- overlay 数据作为 preview payload 的附加字段，例如 `overlays`、`interaction`、`coordinate_space`，不写入业务输出端口。

复用现有 `image-preview` 结构的调试图片 payload 示例：

```json
{
  "type": "image-preview",
  "title": "Perspective Transform 调试图",
  "image": {
    "transport_kind": "storage-ref",
    "object_key": "workflows/runtime/preview-runs/{preview_run_id}/nodes/{node_id}/debug-preview.png",
    "media_type": "image/png",
    "width": 1920,
    "height": 1080
  },
  "overlays": [
    {
      "kind": "polygon",
      "id": "source_points",
      "label": "透视四点",
      "points_xy": [[120, 80], [1780, 90], [1760, 980], [140, 970]],
      "target_parameters": ["source_points"]
    }
  ],
  "interaction": {
    "mode": "edit",
    "coordinate_space": "source-image",
    "tools": [
      {
        "tool": "polygon",
        "label": "透视四点",
        "target_parameters": ["source_points", "output_width", "output_height"],
        "min_points": 4,
        "max_points": 4
      }
    ]
  }
}
```

只读图片预览不提供 `interaction` 字段；交互式图片面板只解析新的 `interaction.tools[]`，不保留单 `tool` / `target_parameters` 旧格式。`polygon` 工具可声明 `min_points` / `max_points`：普通 ROI 至少 3 点，透视变换固定 4 点。

ImageViewer overlay 中多边形统一使用 `points_xy`；节点业务 payload 或写回参数仍按节点语义使用 `polygon_xy`、`source_points` 等字段。二者不要混用。

该信息只描述编辑器如何辅助生成参数，不改变节点核心执行协议。

## 实现阶段

1. 建立 `metadata.parameter_assist` 和 `debug_image_panel` 元数据格式，先覆盖 ROI、crop、perspective-transform、roi-grid-create。
2. 给第一批节点补 `debug_image_panel_enabled`、`debug_image_panel_transport_mode` 参数和 `debug_preview` 输出端口。
3. 后端节点生成调试图片时同时检查节点参数和 `execution_metadata.debug_image_panels_enabled`，默认 production runtime 不生成调试图。
4. 前端图编辑器创建 Preview Run 时发送 `execution_metadata.debug_image_panels_enabled=true`，并把 `shouldRetainPreviewNodeRecords` 改成同时识别 `*-preview` 节点和已打开调试图片面板的普通节点。
5. 前端扩展节点底部 preview display：普通节点的 `debug_preview` 也按现有 `image-preview` / `gallery-preview` 显示。
6. 将现有 `ImageViewer` 改造为统一交互式图片面板，保留只读模式，并在编辑模式实现 bbox、polygon、grid、circle、line 等基础 overlay。
7. 完成参数写回、撤销/取消、坐标换算和脏状态提示，确认后只写回节点 `parameters`。
8. 给 hough-circles、hough-lines、fit-line、template-match 增加 circle、line、template-region 取参能力。
9. 节点 catalog 逐步补齐 `parameter_assist`，并为典型 workflow 增加调试验证。
10. 对大图和高分辨率图像做性能保护：默认关闭调试图片面板，打开时优先 storage-ref / artifact，不把大图 base64 长期塞进节点参数或完整 node_records。

## 仍需注意的问题

- `debug_image_panel_enabled` 是调试参数，不应作为业务判断参数；发布前需要有明显状态提示，避免用户误以为它影响检测结果。
- 大图 overlay 坐标必须统一使用原图像素坐标；如果节点显示的是透视后的图，参数也写入透视图坐标，不自动混用原图坐标。
- ROI grid 的交互不仅是画框，还需要能拖动原点、单格宽高、行列数、步距和方向；否则现场调 36 个槽位仍然低效。
- template region 取参不能把模板图像本体塞进节点参数；模板图仍应走 image payload、artifact 或文件引用，参数只保存 ROI 和引用信息。
- 交互式图片面板要支持只读和编辑两种模式，避免 WorkflowAppDetailPage 或 runtime result 查看图片时出现可编辑控件。
- 对 `storage-ref` preview artifact 要继续使用 Preview Run 生命周期目录，避免调试图长期堆积。

## 空盘检测应用中的使用方式

`workflow-app-20260710020359` 只保留空盘检测一条主线：托盘定位、透视变换、圆孔或几何特征校验、槽位 ROI 网格、逐槽 OpenCV 空槽判断。图像交互取参用于快速获得和修正：

- 托盘四角 `source_points`。
- 标准图输出尺寸。
- 圆孔校验参数和半径范围。
- 36 个槽位的 ROI 网格原点、单格尺寸和步距。
- 每槽判断阈值所需的调试 ROI。

满盘、缺料和错位图片只作为该空盘应用的负样本，不在该应用中实现满盘通过逻辑。
