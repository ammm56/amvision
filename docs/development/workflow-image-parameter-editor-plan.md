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
4. 图像交互工具由节点执行时返回的 `debug_preview.interaction` 声明，避免节点 catalog、页面代码和 runtime 输出出现多套参数辅助协议。
5. `ImageViewer` 当前是只读查看器，后续要改成统一交互式图片面板时，需要保留只读模式。生产 runtime 的图片查看仍是只读；只有 workflow graph editor 传入交互上下文时才允许 overlay 编辑和参数写回。

## 目标边界

- 节点执行仍只读取稳定的 `parameters`，不读取前端临时交互状态。
- 前端负责显示图像、绘制 overlay、把交互结果转换为参数并写回节点。
- 后端节点负责按参数执行算法，返回结果、摘要和可选调试图；调试图必须同时满足节点参数开关和 execution metadata 总开关。
- 参数保存仍落在 workflow template 的节点 `parameters` 中，便于版本化、复制、回滚和现场调整。
- 不新增空盘检测专用节点；缺基础能力时只补通用节点。

## OpenCV 搜索节点执行规则

Circle、Line、Contour、Edge 和集合型拟合节点统一遵守以下规则：

- 查找结果默认上限为 10，调用方可以显式调整，但不能使用 `None` 表示无限结果。
- `ROI Grid Create` 等按用户明确行列生成数据的节点不套用查找结果上限；该类节点改为校验越界并按 `reject / clip / allow` 策略处理。
- 高成本算法先在 `Search ROI` 内执行；超过处理预算时按 `processing_max_long_edge` 等比例缩小，所有结果坐标、尺寸和半径必须还原到原图坐标系。
- 未限制 Search ROI、半径和处理预算的高分辨率 `Hough Circles` 请求在进入 OpenCV 前直接拒绝，避免不可取消的 C 调用长期占满 CPU。
- Contour 先完成过滤和稳定排序，再截断结果；不得依赖 OpenCV 返回顺序决定业务结果。
- Workflow preview、runtime 和临时 application worker 在进程启动阶段统一限制 OpenCV、OMP、MKL 和 OpenBLAS 线程数；节点执行过程中不修改进程全局线程配置。
- `debug_image_panel_enabled` 与执行元数据总开关必须同时打开才生成 Debug Preview。关闭时不编码、不保存、不复制预览图，中间图继续使用内存矩阵或 image-ref 链路。

这些规则由 OpenCV shared runtime 统一实现，节点只声明算法参数和结果语义，避免每个节点维护不同的性能保护逻辑。

## 来料托盘应用的已验证链路

`workflow-app-20260718122522` 使用通用节点组成定位和分类链路，不包含托盘专用节点：

```text
Image
→ 四个独立 Search ROI
→ Hough Circles（每路按 Search ROI 中心距离选择 1 个结果）
→ Quadrilateral From Circle Centers
→ Perspective Transform
→ ROI Grid Create（4 × 6）
→ Crop Export（memory）
→ 通用 List Split / 三分支 Classification（top_k=1）
→ Ordered Merge
→ Slot Classification Summary
```

四个圆输入分别连接 `top_left / top_right / bottom_right / bottom_left`，角点语义由图连接显式表达；节点不根据结果位置猜测角点。`Quadrilateral From Circle Centers` 支持按局部坐标轴设置四边 outset，用于从定位孔圆心恢复托盘有效边界。

三张 5472×3648 现场图片的四个定位圆结果波动约 1–3 px，透视后的 24 个 ROI 顺序和覆盖范围稳定。三分支只是当前应用按 3 个 DeploymentInstance 进程配置的图连接方式；List Split、Classification 和 Ordered Merge 都是可复用基础节点，其他 Workflow App 可按实际资源连接 1 路或更多分支。

当前唯一可用的 classification Deployment 为 `yolo11-s-pcbpetslot-20260719115221`，OpenVINO CPU、3 instances、5 个槽位类别。几何定位与 ROI 验证通过不等于分类模型验证通过；现场图片类别结果异常时应单独检查训练数据域、类别定义和模型评估，不能通过修改几何节点隐藏模型问题。

## 现有相关节点清单

| 类型 | 节点 | 当前用途 | 需要的图像交互 |
| --- | --- | --- | --- |
| ROI 创建 | `core.vision.roi-create` | 创建 bbox / polygon ROI | 在图上画 bbox / polygon |
| ROI 网格 | `core.vision.roi-grid-create` | 按行列生成槽位 ROI | 在图上选原点、单格尺寸、行列方向和步距 |
| ROI 转换 | `core.logic.value-to-roi` | 把 value 转成 ROI | 跟随 ROI 创建节点，通常不单独交互 |
| 裁剪 | `custom.opencv.crop` | 根据输入 `roi.v1` 裁图 | 不取参，只消费 ROI |
| 透视变换 | `custom.opencv.perspective-transform` | 四点透视矫正 | 在图上点选 4 个角点，写回 `source_points` |
| 平面变换 | `custom.opencv.planar-transform-bridge` | 透视结果和 ROI 坐标互转 | 复用透视四点和输出尺寸 |
| 轮廓转 ROI | `core.vision.roi-from-contour` | 从 contour 生成 ROI | 在 debug 图上点选 contour，写回 `selected_contour_index` |
| Hough 圆 | `custom.opencv.hough-circles` | 快速产生一个或多个候选圆，并可执行径向边缘精定位 | Search ROI 固定搜索范围；Reference Circle 只写参考圆心、半径和容差，不得覆盖 Search ROI |
| Circle Measure | `custom.opencv.circle-measure` | 已知近似圆位置时执行亚像素径向边缘测量和 robust circle fitting | 在固定 Search ROI 中选择 Reference Circle，输出拟合误差、圆弧覆盖率和结构化拒绝原因 |
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

### 高分辨率图片显示边界

现场常见工业相机图片会达到 20MP、4K、8K 或更高。高分辨率支持必须分清“算法取参”和“前端预览”两条链路，不能为了页面显示性能把算法输入或交互取参图改成缩略图。

- 生产链路、Preview Run 算法链路和节点间 image-ref 数据继续使用原始图像，默认保持 BGR24 / BufferRef / FrameRef / 原始 storage-ref，不因为前端显示需求缩放。
- ROI、circle、line、template-region、point-pair、match-line、homography-overlay 等交互式参数面板必须使用原图坐标系和原图像素尺寸。`适配`、`100%`、放大、缩小、平移都只是显示变换，写回参数始终是原图像素坐标。
- 节点卡片底部小预览、`core.io.image-preview` 和普通 debug preview 可以使用显示图优化性能。只有当图片超过阈值时才生成显示图；当前以超过 1920x1080 像素量或长边超过 1920px 作为阈值，display 图长边统一控制在 1920px，并按原始长宽比缩放，横图、竖图和细长图都以最大尺寸边作为长边。
- 缩略显示图只用于“看一眼”和节点卡片预览，不参与算法、取参、坐标计算、保存参数、workflow runtime 调用或 TriggerSource 高频调用。
- 交互式图片面板打开时必须能拿到原始图像引用。可以后续扩展 tile / pyramid / region decode viewer 来改善 20MP/8K 的浏览性能，但不能把交互图替换成缩略图。
- preview payload 后续应显式区分 `source_image` 和 `display_image`：`source_width/source_height` 表示原图坐标空间，`display_width/display_height` 表示前端小预览显示图尺寸。没有该字段时前端按旧 payload 的 `width/height` 作为原图尺寸处理。
- `ImageViewer` 的 overlay、鼠标点选、拖拽框选和参数写回统一使用 `source_width/source_height`。节点卡片里的 `<img>` 可以显示 `display_image`，但双击进入交互面板后要切回 `source_image` 或按原图坐标工作的高分辨率查看模式。
- 高分辨率图片优化优先目标是减少前端卡片小图解码、base64 体积和不必要 PNG/JPEG 编码；不允许牺牲工业取参精度。

### 统一交互式图片面板

双击节点底部缩略图进入统一交互式图片面板。现有 `WorkflowNodePreviewDisplay.vue`、`useWorkflowPreviewDisplays.ts` 和共享 `ImageViewer.vue` 是改造基础，不再新增一套独立图片查看器。

- 复用现有大图查看、缩放、拖拽和双击查看逻辑。
- 在 `ImageViewer` 基础上增加 overlay 编辑层，支持 bbox、polygon、circle、line、point、grid、template-region。
- 面板右侧或顶部显示当前工具对应的参数字段，参数变化和 overlay 同步。
- 确认后写回当前节点 `parameters`，取消时不修改参数。
- 坐标以原始图像像素为准，不以显示缩放坐标为准。
- 交互式图片面板只在 workflow graph editor 中可编辑；生产 runtime 返回的图片查看仍按普通只读预览处理。
- 交互式图片面板中的 `适配` 按窗口可视区域等比缩放完整显示原图，`100%` 表示按原图像素 1:1 查看；两者都只改变显示比例，不改变图像数据和坐标系。

### 工具和参数映射

| 工具 | 写回参数 | 适用节点 |
| --- | --- | --- |
| bbox | `bbox_xyxy` | `core.vision.roi-create`、搜索 ROI 类节点 |
| polygon | `polygon_xy`、`source_points`；四点透视时同时估算 `output_width`、`output_height` | `core.vision.roi-create`、`custom.opencv.perspective-transform` |
| circle | `center_x`、`center_y`、`radius`，或 `reference_center_xy`、`reference_radius_px`、`center_tolerance_px`、`radius_tolerance_px` | `custom.opencv.hough-circles`、`custom.opencv.circle-measure`、`custom.opencv.min-enclosing-circle` |
| line | `line_xyxy`、`search_bbox_xyxy`、`min_line_length`、`angle_min_deg`、`angle_max_deg`、`angle_deg` | `custom.opencv.hough-lines`、`custom.opencv.fit-line`、`custom.opencv.rotation-correct`、测量节点 |
| grid | `origin_x`、`origin_y`、`roi_width`、`roi_height`、`step_x`、`step_y`、`rows`、`columns` | `core.vision.roi-grid-create` |
| template-region | `template_bbox_xyxy`、`search_bbox_xyxy` 或输入模板图来源 | `custom.opencv.template-match` |
| point-pair | `source_points`、`target_points`、`debug_manual_pair_lines_xyxy` | `custom.opencv.affine-transform`、`custom.opencv.orb-match`、`custom.opencv.homography-estimate` |
| match-line | `debug_selected_match_ids` | `custom.opencv.orb-match`、`custom.opencv.homography-estimate` |
| homography-overlay | `debug_selected_projection_id` | `custom.opencv.homography-estimate` |

Hough Circles 和 Circle Measure 的图形语义必须保持独立：Search ROI 使用蓝色虚线矩形，Reference Circle 使用紫色虚线圆，普通候选使用橙色实线圆，最终选中圆使用绿色粗实线和圆心十字，被拒绝候选仅在 Debug Preview 中使用红色或灰色虚线。颜色由亮色、暗色主题变量提供，节点实现不得写死组件颜色。精定位链路使用有界 RANSAC 初始化和 Huber/Tukey IRLS，并限制候选数、径向采样数和拟合迭代次数。

## 节点定义扩展方式

交互取参能力统一由节点本次 `debug_preview.interaction` 输出声明，前端不从节点类型名猜测工具，也不在页面层硬编码算法默认值。`parameter_ui_schema` 继续负责普通参数表单，不承载复杂图像交互状态。

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

节点 `debug_preview.interaction` 示例：

```json
{
  "mode": "edit",
  "coordinate_space": "source-image",
  "tools": [
    {
      "tool": "line",
      "label": "方向线段",
      "target_parameters": ["search_bbox_xyxy", "min_line_length", "angle_min_deg", "angle_max_deg"],
      "angle_tolerance_deg": 8,
      "search_padding_ratio": 0.08,
      "search_padding_min": 8
    }
  ],
  "controls": []
}
```

节点定义仍只声明 `debug_preview` 输出端口和 debug 开关参数：

```json
{
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

### Geometry 节点交互边界

`opencv.geometry` 节点只负责几何变换和坐标桥接，不混入 ROI 创建、模板匹配或绘制职责。当前交互协议按节点实际参数划分：

- `perspective-transform`：使用 `polygon` 四点工具写回 `source_points`，并估算 `output_width / output_height`。
- `rotation-correct`：使用 `line` 工具从图中方向线写回 `angle_deg`，同时提供 `negate_angle / expand_canvas` 调试控件。
- `affine-transform`：使用 `point-pair` 工具收集三对源点和目标点，写回 `source_points / target_points`；也可继续读取显式 `matrix_2x3`。
- `undistort`：主要读取标定 config，不适合手动画 ROI 取参；调试图显示矫正结果和 valid ROI，提供 `alpha / crop_to_valid_roi / use_optimal_new_camera_matrix` 控件。
- `remap`：主要读取标定映射表或上游 mapping；调试图显示 remap 结果，提供边界填充值等快速确认控件。

这些节点的 debug preview 都必须默认关闭；打开时只服务编辑态 Preview Run，不进入生产 runtime 的固定开销。

### Matching 双图交互边界

`opencv.matching` 节点以双图调试图为核心，不把匹配语义降级成普通 line/polygon：

- `orb-match` 输出 `feature-matches.v1`，debug preview 使用 `match-line` 点选匹配线、`point-pair` 手动画左右图点对，并通过控件筛选匹配线数量、距离和显示状态。
- `homography-estimate` 输出 `planar-transform.v1`，debug preview 使用 `match-line` 点选内点线、`point-pair` 手动补充点对、`homography-overlay` 点选投影框。
- `template-match` 输出 `regions.v1`，使用 `template-region` 同时管理模板 ROI 和搜索 ROI。

双图 overlay 可以复用 `line_xyxy / points_xy / circle` 等基础绘制字段，但 `kind` 必须保留 `match-line / point-pair / homography-overlay` 这类业务语义，后续才能继续扩展匹配线过滤、点对编辑和投影框状态反馈。

## 实现阶段

1. 普通节点通过 `debug_preview.interaction` 声明图像取参工具，不再新增一套 `metadata.parameter_assist` 路径。
2. 给第一批节点补 `debug_image_panel_enabled`、`debug_image_panel_transport_mode` 参数和 `debug_preview` 输出端口。
3. 后端节点生成调试图片时同时检查节点参数和 `execution_metadata.debug_image_panels_enabled`，默认 production runtime 不生成调试图。
4. 前端图编辑器创建 Preview Run 时发送 `execution_metadata.debug_image_panels_enabled=true`，并把 `shouldRetainPreviewNodeRecords` 改成同时识别 `*-preview` 节点和已打开调试图片面板的普通节点。
5. 前端扩展节点底部 preview display：普通节点的 `debug_preview` 也按现有 `image-preview` / `gallery-preview` 显示。
6. 将现有 `ImageViewer` 改造为统一交互式图片面板，保留只读模式，并在编辑模式实现 bbox、polygon、grid、circle、line 等基础 overlay。
7. 完成参数写回、撤销/取消、坐标换算和脏状态提示，确认后只写回节点 `parameters`。
8. 给 hough-circles、hough-lines、fit-line、template-match 增加 circle、line、template-region 取参能力。
9. 为典型 workflow 增加调试验证，确认节点返回的 `debug_preview.interaction`、overlay 和参数写回保持一致。
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
