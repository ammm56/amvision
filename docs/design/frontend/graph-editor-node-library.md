# 图编辑节点库与分类依据

> 2026-10-29 最新范围：此前整页稿已撤回；以[当前实现基准](graph-editor-current-baseline.md)为准。本文的字段、参考研究和节点库内部规划保留，不作为重画导航、顶部、节点尺寸或整页布局的授权。

更新：2026-10-29。来源为当前工作区 Core 定义及自定义节点包 manifest/catalog 的只读核对，共11个来源、493项定义。数量是源码快照，包含开发包，不代表运行服务已经启用全部节点；界面以当前服务返回且有权使用的 Catalog 为准，不硬编码数量。

同日浏览器运行目录实际显示11个来源、489项：Core 226、OpenCV 188、Barcode 49、Camera 9、Connector 2、Database 1、HTTP 1、PLC 4、SAM3 5、YOLOE 3、Hello World 1。模型推理13项，生命周期5项。局部图采用此运行快照；未核实的类别数量不显示。其余节点通过结果区滚动访问，图中8张可见卡片不表示仅支持8个节点。

## 交互

- 来源 → 类别 → 节点三列，搜索覆盖名称、描述、分类、包和标签。
- 默认卡片；节点列右上切换卡片/列表。两种视图都显示名称与简短用途，正式名称英文、用途中文。
- 单击条目直接添加并关闭节点库；从端口拖出打开时按兼容端口过滤并延续现有自动连线。没有底部添加/说明栏，没有二次确认。
- 空结果、不可用包、版本不兼容、端口无匹配要分别反馈；不可用条目不能冒充可添加。
- 卡片/列表只是呈现方式，不改变节点分类、参数、执行语义；当前位置与搜索条件在切换时保留。
- 专用 Barcode 预设选择属于专属编辑步骤，不把它的确认方式推广到通用节点选择。
- 来源/类别/结果独立滚动；不压缩字体硬塞全量节点。新增包自动进入来源层，不为每个包增加全局导航。

依据：[节点库组件](../../../frontend/web-ui/src/workflows/workflow-editor/components/WorkflowNodePicker.vue)、[节点选择逻辑](../../../frontend/web-ui/src/workflows/workflow-editor/nodes/useWorkflowNodePicker.ts)。卡片/列表切换是本轮目标设计，不能据静态稿宣称已实现。

## 两列导航与呈现

第一列保留旧稿的短名、来源图标、数量：Core、OpenCV、Barcode、Camera、Connector、Database、HTTP、PLC、SAM3、YOLOE、Hello World。普通图标保持中性，来源图标不自动复制到画布节点标题。

第二列采用用途树，分组用于检索而不改变Catalog分类ID。OpenCV为图像、掩膜、分割、特征、匹配、几何、标定、测量、检查、输出；输出下是绘制和工作流。Core为输入、逻辑、结果、模型等用途组；输入下有提示/文件/图像，模型下有推理/生命周期。各叶子映射下表的完整分类；新增类别按其父路径显示，不能因未手写UI而消失。专业包仍保持独立来源。

第三列独立标题显示当前类别及数量，右侧卡片/列表切换。结果名称14px/400，短用途12px/400，最长两行；名称过长自然换行而不截掉关键后缀。卡片区域可滚动，不能把源码493项误写成每次都已启用493项。

## 完整源码清单

### Core（230）

包：`core`。

| 分类 | 节点 |
| --- | --- |
| `core.input.prompt`（8） | Box Prompt；Mask Editor；Mask Prompt；Point Prompt；Polygon Prompt；Prompt Regions Merge；Text Prompt；Text Prompts Merge |
| `core.io.file`（20） | Batch Files Relocate；Directory Batch Window；Directory Cursor Advance；Directory Cursor Normalize；Directory Latest File；Directory Poll Window；Directory Scan；File Metadata；File Read JSON；File Read Text；File Refs Metadata List；File Summary；Load Local JSON；Read JSONL；Load Local Text；Append CSV；Save JSON；Append JSONL；Storage Retention Cleanup；Save Text |
| `core.logic.value`（7） | File Refs Get Item；Boolean Value；JSON Parse Text；Number Value；String Value；Text To Value；Value To JSON Text |
| `core.logic.transform`（30） | Image Base64 Coalesce；Image Ref Coalesce；Number Function；Number Operation；Unit Convert；Categories Batch To Items；Coalesce；Detections Batch To Items；Detections Items；Extract Field；Format Date Time；Format String；Numeric Table To Value；Merge Numeric Tables；OBBs Batch To Items；Payload To Value；Poses Batch To Items；Scalar To String；Segments Batch To Items；Concat Strings；Value Exists；Extract Value Field；Value To Categories；Value To Circles；Value To Detections；Value To Image Ref；Value To Image Refs；Value To OBBs；Value To Poses；Value To ROI |
| `core.io.image`（8） | Image Base64 Decode；Image Base64 Encode；Image Encode；Get Image Ref；Image Refs To Value List；Save Image；Load Local Image List；Load Local Image |
| `core.ui.preview`（5） | Image Preview；Table Preview；Value Display；Value Preview；Frame Window Preview |
| `core.inspection.record`（5） | Alarm Record；Batch Record；Batch Result Summary；Result Record；Workflow Result |
| `core.io.response`（4） | HTTP Response；Image Body；Response Envelope；Video Body |
| `core.io.input`（6） | Template File Input；Template Files Input；Template Image Input；Template Object Input；Template Text Input；Template Value Input |
| `core.logic.condition`（4） | Boolean And；Boolean Not；Boolean Or；Compare Values |
| `core.logic.collection`（17） | Array Summary；All；Any；Reduce；Count by Rules；Append List Item；Create List；Create List (Legacy Ordered)；Filter List；Group List；List Item；Get List Item；Get List Length；Map List；Sort List；Split List；Unique List |
| `core.logic.branch`（7） | Conditional End；Conditional Start；If Else Select；Match Case；Switch；Switch End；Switch Start |
| `core.logic.iteration`（4） | Delay；For Each End；For Each Start；Loop Control |
| `core.logic.parallel`（2） | Parallel End；Parallel Start |
| `core.logic.object`（9） | Create Object；Create Object (Legacy Positional)；Object Field；Merge Objects；Merge Objects (Legacy Ordered)；Pick Object Fields；Remove Object Fields；Set Object Path；Update Object Fields (Legacy Positional) |
| `core.logic.rule`（7） | Alarm Condition；Check Limits；OK / NG Decision；Presence Check；Process Decision；Range Check；Threshold Check |
| `core.logic.variable`（3） | Delete Variable；Get Variable；Set Variable |
| `core.model.inference`（13） | Slot Classification Summary；Classification；Classification Batch；Detection；Detection Batch；OBB；OBB Batch；Pose；Pose Batch；Segmentation；Segmentation Batch；SAHI Inference；Submit Inference |
| `core.dataset.export`（2） | Package Dataset Export；Submit Dataset Export |
| `core.dataset.import`（1） | Submit Dataset Import |
| `core.deployment.runtime`（7） | Create Deployment；Get Deployment Health；Reset Deployment；Start Deployment；Get Deployment Status；Stop Deployment；Warmup Deployment |
| `core.model.lifecycle`（5） | Submit Conversion；Package Evaluation Result；Submit Evaluation；Submit Training；Create Validation Session |
| `core.task.observation`（2） | Get Task Detail；Wait Task Terminal State |
| `core.io.video`（5） | Load Local Video；Save Video；Render Video Overlay；Decode Video Frames；Get Frame |
| `core.vision.video`（2） | Filter Tracks；Tracks To Regions |
| `core.vision.continuity`（8） | Region Component Count；Region Continuity Score；Region Gap Check；Region Hole Count；Region Largest Component Ratio；Region Span Metrics；Edge Break Check；Edge Profile Gap Check |
| `core.vision.defect`（8） | Defect Cluster Count；Defect Density；Defect Largest Cluster Ratio；Foreground Change Ratio；Foreign Object Check；Reference Diff Metrics；Surface Uniformity Check；Surface Uniformity Metrics |
| `core.vision.geometry`（5） | Circularity Check；Linearity Check；Pair Offset Check；Reference Mark Align Check；Spacing Check |
| `core.vision.assembly`（4） | Corner Missing Check；Hole Pattern Check；Multi Part Presence Check；Sequence Order Check |
| `core.vision.region`（12） | Classification Items To Regions；Detections To Regions；Region Area Ratio；Sum Region Area；Region BBox Metrics；Count Regions；Filter Regions；Region Score Summary；Select Best Region；Segments To Regions；Value To Regions；Value To Segments |
| `core.vision.position`（4） | Regions Coverage Check；Regions Inside Check；Regions Intersection Metrics；Regions Offset Check |
| `core.vision.roi`（6） | Create ROI；ROI From Contour；ROI From Rotated Rect；ROI Grid Create；ROI List Create；ROI List Item Get |

### Barcode Nodes（49）

包：`barcode.nodes`。

| 分类 | 节点 |
| --- | --- |
| `barcode.compose`（2） | Barcode Crop Decode；QR Crop Decode Remap |
| `barcode.decode`（41） | Decode All GS1 Barcodes；Decode All Industrial Barcodes；Decode All Linear Barcodes；Decode All Matrix Barcodes；Decode All Readable Barcodes；Decode All Retail Barcodes；Aztec Code Decode；Aztec Rune Decode；Codabar Decode；Code 128 Decode；Code 32 Decode；Code 39 Extended Decode；Code 39 Standard Decode；Code 93 Decode；Compact PDF417 Decode；Decode DataBar Family；DataBar Expanded Decode；DataBar Expanded Stacked Decode；DataBar Limited Decode；DataBar Omnidirectional Decode；DataBar Stacked Decode；Data Matrix ECC200 Decode；EAN-13 Decode；EAN-2 Decode；EAN-5 Decode；EAN-8 Decode；Decode EAN/UPC Family；ISBN Decode；ITF-14 Decode；ITF Decode；MaxiCode Decode；MicroPDF417 Decode；Micro QR Code Decode；PDF417 Decode；PZN Decode；QR Code Decode；QR Code Model 1 Decode；QR Code Model 2 Decode；rMQR Decode；UPC-A Decode；UPC-E Decode |
| `barcode.display`（1） | Barcode Display Response |
| `barcode.logic`（3） | Barcode Match Exists；Filter Barcode Results；Summarize Barcode Results |
| `barcode.render`（1） | Draw Barcode Results |
| `barcode.transform`（1） | Barcode Results To Value |

### Camera Nodes（9）

包：`camera.nodes`。

| 分类 | 节点 |
| --- | --- |
| `camera.usb`（9） | Capture USB/UVC Frame；Close USB/UVC Device；Enumerate USB/UVC Devices；Get USB/UVC Parameter；Open USB/UVC Device；Read Latest USB/UVC Frame；Read USB/UVC Window；Set USB/UVC Parameter；Start USB/UVC Stream |

### Connector Nodes（2）

包：`connector.nodes`。

| 分类 | 节点 |
| --- | --- |
| `connector.inspection.array`（1） | Pin Array Locate |
| `connector.measurement.dimension`（1） | Connector Measure |

### Database Nodes（1）

包：`database.nodes`。

| 分类 | 节点 |
| --- | --- |
| `database.sql.write`（1） | SQL Upsert |

### Hello World Nodes（1）

包：`hello.world-nodes`。

| 分类 | 节点 |
| --- | --- |
| `example.hello`（1） | Hello World Message |

### HTTP Nodes（1）

包：`http.nodes`。

| 分类 | 节点 |
| --- | --- |
| `http.request`（1） | HTTP Request |

### OpenCV Nodes（188）

包：`opencv.nodes`。

| 分类 | 节点 |
| --- | --- |
| `opencv.image.threshold`（4） | Adaptive Threshold；Binary Threshold；Color Range Threshold；Otsu Threshold |
| `opencv.mask.operation`（7） | Apply Mask；Mask Logic；Clear Border；Distance Transform；Fill Holes；Remove Small Components；Skeletonize |
| `opencv.image.filter`（6） | Bilateral Filter；Box Blur；Filter 2D；Gabor Filter；Gaussian Blur；Median Blur |
| `opencv.image.enhancement`（7） | Brightness Contrast；CLAHE；Gamma Correction；Histogram Equalize；Image Arithmetic；Invert；Normalize |
| `opencv.image.edge`（4） | Canny Edge；Laplacian；Scharr；Sobel |
| `opencv.image.color`（6） | Channel Merge；Channel Select；Channel Split；Color Convert；Grayscale；Image Type Convert |
| `opencv.image.transform`（24） | Crop；Image Composite；Image Concat；Image Create；Image Translate；Resize；Image Rectify Stereo；Affine Transform；Flip；Get Rect SubPix；Mapped ROI Crop；Pad Border；Perspective Transform；Planar Transform Bridge；Remap；ROI Array；Rotation Correct；Transform 2D Compose；Transform 2D Create；Transform 2D Invert；Transform Points；Transpose；Undistort；Warp Polar |
| `opencv.output.workflow`（2） | Crop Export；OpenCV Payload To Value |
| `opencv.output.render`（13） | Gallery Preview；Draw Calibration Reprojection；Draw Circles；Draw Contours；Draw Detections；Draw Ellipses；Draw Inspection Errors；Draw Lines；Draw Localizations；Draw Measurements；Draw Regions；Draw ROI；Draw ROIs |
| `opencv.inspection.statistics`（4） | Histogram；Image Quality Metrics；ROI Intensity Statistics；Blob Analysis |
| `opencv.image.basic`（1） | Image Decode |
| `opencv.inspection.batch`（5） | Image Refs Empty Check；Image Refs Occupied Check；Image Refs Slot Metrics；Image Refs Statistics；Slot Batch State |
| `opencv.matching.registration`（5） | Image Stitch；Circle Pattern Locate；ECC Align；Homography Estimate；Phase Correlation |
| `opencv.mask.morphology`（2） | Morphology；Morphology HitMiss |
| `opencv.calibration.camera`（11） | Calibration Diagnose；Calibration Observation Filter；Camera Calibrate；Chessboard Corners；Circle Grid Detect；Corner SubPix；Fisheye Calibrate；Planar Calibrate；Rectification Map；Stereo Calibrate；Stereo Rectify |
| `opencv.calibration.pose`（6） | Hand-Eye Calibrate；Project Points；Solve PnP；Undistort Points；Pixel To World；World To Pixel |
| `opencv.inspection.difference`（8） | Absdiff Threshold；Bead Inspect；Contour Deviation Inspect；Heatmap Preview；Image Diff；ROI Foreground Compare；Variation Inspect；Variation Model Build |
| `opencv.segmentation.region`（5） | Connected Components；Flood Fill；Region Difference；Region Intersection；Region Union |
| `opencv.segmentation.image`（4） | GrabCut；K-Means Segment；Watershed；Watershed Markers |
| `opencv.measurement.geometry`（11） | Circle Circle Relation；Line Circle Relation；Line Line Relation；Point Circle Relation；Ellipse Measure；Line Angle；Parallelism Metrics；Point Distance；Point To Line Distance；Rectangle Measure；Slot Width |
| `opencv.geometry.shape`（18） | Circle Create；Circles Select；Ellipse Create；Ellipses Select；Line Create；Lines Select；Point Create；Points Select；Convex Hull；Convexity Defects；Fit Ellipse；Fit Line；Hu Moments；Image Moments；Min Area Rect；Min Enclosing Circle；Region Properties；Shape Match |
| `opencv.geometry.detection`（7） | Line Deduplicate；Line Intersection；Quadrilateral From Circle Centers；Quadrilateral From Lines；Line Segment Detect；Hough Circles；Hough Lines |
| `opencv.feature.detection`（6） | AKAZE Keypoints；BRISK Keypoints；FAST Corners；Good Features To Track；ORB Keypoints；SIFT Keypoints |
| `opencv.matching.feature`（3） | Feature Locate；FLANN Match；ORB Match |
| `opencv.matching.template`（5） | Multi-scale Template Match；Rigid Locate；Rotation-scale Template Match；Shape Locate；Template Match |
| `opencv.measurement.edge`（5） | Caliper Edge；Edge Pair Measure；Gray Profile Measure；Line Measure；Measure |
| `opencv.measurement.circle`（4） | Circle Diameter；Concentricity Metrics；Radial Line Search；Circle Measure |
| `opencv.geometry.contour`（5） | Contour；Contour Approx；Contour Filter；Contours To Regions；Point Polygon Test |

### PLC Nodes（4）

包：`plc.nodes`。

| 分类 | 节点 |
| --- | --- |
| `plc.modbus_tcp.read`（1） | Read Modbus Value |
| `plc.modbus_tcp.wait`（1） | Wait Modbus Condition |
| `plc.modbus_tcp.write`（2） | Write Modbus Result Signals；Write Modbus Value |

### SAM3 Segment Nodes（5）

包：`sam3.segment-nodes`。

| 分类 | 节点 |
| --- | --- |
| `sam3.model.loader`（1） | SAM3 Load Checkpoint |
| `sam3.image.interactive`（1） | SAM3 Interactive Segment |
| `sam3.image.semantic`（1） | SAM3 Semantic Segment |
| `sam3.video.interactive`（1） | SAM3 Video Interactive Segment |
| `sam3.video.semantic`（1） | SAM3 Video Semantic Segment |

### YOLOE Open Vocabulary Nodes（3）

包：`yoloe.open-vocab-nodes`。

| 分类 | 节点 |
| --- | --- |
| `yoloe.detection`（3） | YOLOE Text Prompt Detect；YOLOE Visual Prompt Detect；YOLOE Prompt Free Detect |
