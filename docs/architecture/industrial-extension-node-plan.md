# 工业扩展节点规划

## 文档目的

本文档用于补齐工业现场扩展节点规划中过于粗的部分，重点收口以下四类内容：

- 相机接入节点分层
- PLC / 协议节点分层
- 工业瑕疵 / 异常检测仍欠缺的核心节点
- OpenCV 与传统机器视觉常用算子节点规划

本文档不替代 [industrial-rule-node-plan.md](industrial-rule-node-plan.md)。

- `industrial-rule-node-plan.md` 重点解决单帧工业规则判定、结果回传和目录输入主线
- 本文档重点解决更广义的工业扩展节点体系，尤其是 `custom.*`、`core.cv.*` 和现场接入边界

## 当前现状

当前仓库已经有几类 custom node pack：

- `camera_usb_uvc_nodes`
- `yoloe_open_vocab_nodes`
- `sam3_segment_nodes`
- `opencv_basic_nodes`
- `opencv_defect_nodes`
- `opencv_shape_nodes`
- `opencv_measurement_nodes`
- `opencv_geometry_nodes`
- `opencv_matching_nodes`
- `barcode_display_nodes`
- `barcode_protocol_nodes`
- `plc_modbus_tcp_nodes`

其中 `opencv_basic_nodes` 当前已经有：

- `binary-threshold`
- `canny`
- `gaussian-blur`
- `morphology`
- `grayscale`
- `resize`
- `crop`
- `normalize`
- `clahe`
- `median-blur`
- `bilateral-filter`
- `adaptive-threshold`
- `otsu-threshold`
- `invert`
- `sobel`
- `laplacian`
- `draw-detections`
- `draw-contours`
- `draw-lines`
- `draw-circles`
- `draw-roi`
- `draw-measurements`
- `mask-overlay`
- `crop-export`
- `gallery-preview`
- `payload-to-value`

其中 `opencv_geometry_nodes` 当前已经有：

- `rotation-correct`
- `perspective-transform`
- `affine-transform`
- `undistort`
- `remap`

其中 `opencv_measurement_nodes` 当前已经有：

- `measure`
- `caliper-edge`
- `point-distance`
- `point-to-line-distance`
- `line-angle`
- `circle-diameter`
- `slot-width`
- `parallelism-metrics`
- `concentricity-metrics`

其中 `opencv_defect_nodes` 当前已经有：

- `image-diff`
- `absdiff-threshold`
- `connected-components`
- `fill-holes`
- `distance-transform`

其中 `opencv_shape_nodes` 当前已经有：

- `contour`
- `contour-filter`
- `contour-approx`
- `min-area-rect`
- `convex-hull`
- `fit-ellipse`
- `contours-to-regions`
- `hough-lines`
- `hough-circles`
- `fit-line`
- `min-enclosing-circle`

其中 `opencv_matching_nodes` 当前已经有：

- `template-match`
- `orb-keypoints`
- `orb-match`
- `homography-estimate`

当前 `custom_nodes/opencv_basic_nodes/` 的物理目录名仍是旧形态，但 manifest id 已经是 `opencv.basic-nodes`。经过前五轮试点拆分后，这个 pack 当前主要承载预处理与调试渲染两类能力，后续仍不适合继续把所有新节点都堆进同一个目录。

其中前五轮 pack 拆分试点当前已落地：

- 共享 backend helper 已从 `custom_nodes/opencv_basic_nodes/backend/support.py` 抽到 `custom_nodes/_opencv_shared/backend/support.py`
- OpenCV custom payload 规则 当前也已统一收进 `custom_nodes/_opencv_shared/workflow/payload_contracts.json`
- `rotation-correct / perspective-transform / affine-transform / undistort / remap / planar-transform-bridge` 已正式迁入 `custom_nodes/opencv_geometry_nodes/`
- `measure / caliper-edge / point-distance / point-to-line-distance / line-angle / circle-diameter / slot-width / parallelism-metrics / concentricity-metrics` 已正式迁入 `custom_nodes/opencv_measurement_nodes/`
- `contour / contour-filter / contour-approx / convex-hull / min-area-rect / fit-ellipse / contours-to-regions / hough-lines / hough-circles / fit-line / min-enclosing-circle` 已正式迁入 `custom_nodes/opencv_shape_nodes/`
- `image-diff / absdiff-threshold / connected-components / fill-holes / distance-transform` 已正式迁入 `custom_nodes/opencv_defect_nodes/`
- `template-match / orb-keypoints / orb-match / homography-estimate` 已正式迁入 `custom_nodes/opencv_matching_nodes/`
- 公开 `node_type_id` 保持不变，当前仍统一使用 `custom.opencv.*`
- checked-in 样例 `industrial_single_frame_calibrated_template_edge_gate.*`、`industrial_single_frame_calibrated_orb_homography_gate.*`、`industrial_single_frame_calibrated_orb_bridged_template_edge_gate.*`、`industrial_single_frame_line_pair_measure_gate.*` 与 `industrial_single_frame_circle_concentricity_gate.*` 继续作为拆包后的主线验证入口；`test_opencv_matching_nodes.py` 继续作为 ORB / homography 参考对位链的定向运行时回归入口
- checked-in 样例 `industrial_single_frame_reference_diff_watershed_surface_gate.*` 当前也已补入验证入口，专门覆盖 `opencv.defect-nodes` 中 `heatmap-preview / watershed / connected-components` 到工业规则链的现场闭环。

其中第一批更贴工业现场的传统视觉补强当前已接通：

- `custom.opencv.grayscale`
- `custom.opencv.resize`
- `custom.opencv.adaptive-threshold`
- `custom.opencv.otsu-threshold`
- `custom.opencv.contour-filter`
- `custom.opencv.min-area-rect`
- `custom.opencv.contours-to-regions`

其中 `min-area-rect` 当前新增 `rotated-rects.v1` 结构化 payload，`payload-to-value` 也已支持把它包装回 `value.v1` 继续参与响应拼装或调试预览。

其中当前最贴工业单帧现场的预处理基础层在 `opencv.basic-nodes` 中已接通：

- `custom.opencv.crop`
- `custom.opencv.normalize`
- `custom.opencv.clahe`
- `custom.opencv.median-blur`
- `custom.opencv.bilateral-filter`
- `custom.opencv.invert`

这组节点当前已经可以先把“ROI 收紧、亮度区间规整、局部对比增强、噪声抑制、黑白方向翻转”这层前置链独立收起来，再接后续差异、轮廓、量测和工业规则节点。

其中几何与标定矫正层当前已独立收进 `opencv.geometry-nodes`：

- `custom.opencv.rotation-correct`
- `custom.opencv.perspective-transform`
- `custom.opencv.affine-transform`
- `custom.opencv.undistort`
- `custom.opencv.remap`

这组节点当前已经可以把“姿态矫正、透视面矫正、仿射矫正、镜头畸变矫正和像素级几何重映射”这层从原大 pack 中独立收起来，作为后续 `geometry` 家族继续拆包的第一轮基线。

其中定位与量测层当前也已独立收进 `opencv.measurement-nodes`：

- `custom.opencv.measure`
- `custom.opencv.caliper-edge`
- `custom.opencv.point-distance`
- `custom.opencv.point-to-line-distance`
- `custom.opencv.line-angle`
- `custom.opencv.circle-diameter`
- `custom.opencv.slot-width`
- `custom.opencv.parallelism-metrics`
- `custom.opencv.concentricity-metrics`

这组节点当前已经可以把“轮廓度量、基准边量测、距离 / 角度 / 直径 / 槽宽 / 平行度 / 同心度”这条工业单帧量测主线单独收起来，再继续接 `core.rule.*` 与 `core.output.*`。

其中第二批更贴缺陷/差异流程的原子节点当前也已独立收进 `opencv.defect-nodes`：

- `custom.opencv.image-diff`
- `custom.opencv.absdiff-threshold`
- `custom.opencv.connected-components`

当前已经可以直接接成：

- `reference image -> image-diff -> absdiff-threshold -> connected-components -> regions.v1`

其中 `connected-components` 当前会为每个 component 生成 `mask_image`，避免后续继续接面积、完整性、空洞或差异规则链时丢失真实前景几何。

其中第二优先级的形状与形态补强层当前也已分层收口：

- `custom.opencv.contour-approx`
- `custom.opencv.convex-hull`
- `custom.opencv.fit-ellipse`
- `custom.opencv.fill-holes`
- `custom.opencv.distance-transform`

这组节点当前已经可以把“轮廓精修、外形包络、椭圆拟合、孔洞填充、距离场预览”这条中间层收起来，继续服务孔位、椭圆件、涂布完整性和空腔/中心性分析。

其中边缘 / 线圆与边缘预增强层当前也已接通：

- `custom.opencv.sobel`
- `custom.opencv.laplacian`
- `custom.opencv.hough-lines`
- `custom.opencv.hough-circles`
- `custom.opencv.fit-line`
- `custom.opencv.min-enclosing-circle`

这组节点当前已经可以把“边缘预增强 -> 线 / 圆抽取 -> 结构化几何结果”这条链接通，继续服务边线完整性、孔位、圆度、边缘轮廓和定位辅助。

其中匹配层当前也已接通：

- `custom.opencv.template-match`
- `custom.opencv.orb-keypoints`
- `custom.opencv.orb-match`
- `custom.opencv.homography-estimate`

这组节点当前已经可以把“模板定位”和“局部特征参考对位”这两条定位链从量测链前面单独收起来，再继续衔接 `opencv.measurement-nodes` 与后续工业规则链。

其中渲染、导出与桥接层当前也已接通：

- `custom.opencv.draw-contours`
- `custom.opencv.draw-lines`
- `custom.opencv.draw-circles`
- `custom.opencv.draw-roi`
- `custom.opencv.draw-measurements`
- `custom.opencv.mask-overlay`
- `custom.opencv.crop-export`
- `custom.opencv.gallery-preview`
- `custom.opencv.payload-to-value`

这组节点当前已经可以把“现场调试复核、规则依据叠加、裁剪导出和结果桥接回通用响应体”这层使用面收起来。

按当前真实状态看，这套能力已经能覆盖工业单帧现场一条较完整的传统机器视觉主线。当前更主要的问题不是“有没有 OpenCV 节点”，而是：

- pack 边界与目录命名已经不再匹配真实能力宽度
- 节点分层还需要从“一个大 pack”进一步收成稳定能力族
- 相机与 PLC 这类现场接入没有按连接方式、协议族和厂商 SDK 分层
- 工业缺陷 / 异常检测仍缺少更重的深层异常模型与少数形态学节点
- 复杂配准、热力图预览和更重的异常处理链仍保留在后续规划中

## 当前阶段收口决策

这一节用于把当前阶段真正要做的范围收窄，避免规划无限扩张。

### 一、相机

当前阶段只默认实现：

- `custom.camera.usb_uvc_nodes`

当前阶段先不实现、仅保留规划：

- `custom.camera.rtsp_nodes`
- `custom.camera.genicam_nodes`
- `custom.camera.basler_pylon_nodes`
- `custom.camera.hikrobot_mvs_nodes`
- `custom.camera.dahua_mvsdk_nodes`
- `custom.camera.mindvision_nodes`
- `custom.camera.framegrabber_nodes`

理由：

- USB / UVC 是最低门槛、最容易先打通现场单帧采图的一层
- 其他工业相机层都明显依赖具体现场设备、SDK 安装和参数语义
- 当前应先把“能采、能调、能接 workflow”这条最短主线做稳

当前已落地：

- `custom_nodes/camera_usb_uvc_nodes/` 已作为第一层相机 custom node pack 落地，并默认启用
- 当前前三批节点已收口为 `custom.camera.usb.enumerate-devices`、`custom.camera.usb.capture-frame`、`custom.camera.usb.open-device`、`custom.camera.usb.start-stream`、`custom.camera.usb.read-window`、`custom.camera.usb.read-latest-frame`、`custom.camera.usb.get-parameter`、`custom.camera.usb.set-parameter` 与 `custom.camera.usb.close-device`
- 当前实现边界保持在项目内 `OpenCV VideoCapture` 适配层，不依赖厂商 SDK、`projectsrc/` 目录或额外 Python 相机包
- 当前已经支持会话型单帧重复采图、基础参数控制与后台采流窗口读取；后续重点转向更细参数族、目录/触发源接入与非 UVC 相机层
- 当前也已补出第一批 checked-in workflow 样例：`camera_usb_uvc_enumerate_capture_preview.*`、`camera_usb_uvc_session_single_frame_review.*` 与 `camera_usb_uvc_stream_window_preview.*`，用于分别验证“枚举与直采”“会话调参与单帧复核”“后台采流与窗口预览”三条最短使用面
- 当前也已进一步补出两条直连工业规则链的 checked-in workflow 样例：`industrial_single_frame_usb_uvc_yolox_position_gate.*` 与 `industrial_single_frame_usb_uvc_sam3_semantic_continuity_gate.*`，用于验证“相机直采 -> 检测/分割 -> 规则判定 -> result-record”这条更贴现场的单帧主线

### 二、PLC

当前阶段只默认实现：

- `custom.plc.modbus_tcp_nodes`

当前阶段先不实现、仅保留规划：

- `custom.plc.s7_nodes`
- `custom.plc.mitsubishi_mc_nodes`
- `custom.plc.opcua_nodes`
- `custom.plc.fins_nodes`
- `custom.plc.ethernet_ip_nodes`

理由：

- Modbus TCP 最基础、跨品牌、实现边界最清楚
- S7 / MC 虽然现场常见，但连接、地址、数据类型和调试成本都更重
- 当前应先把 PLC 的第一条正式协议主线做稳，而不是同时铺多种协议

当前已落地：

- `custom_nodes/plc_modbus_tcp_nodes/` 已作为默认启用的第一层 PLC custom node pack 落地
- 当前对外节点面已收口为 `read-value / write-value / wait-condition / write-result-signals`
- 当前 pack 已切到项目内最小 Modbus TCP runtime，不依赖 `projectsrc/` 目录或额外第三方 Python 包直接执行
- 当前仍只覆盖 workflow 内主动读写与等待条件，不包含常驻轮询 trigger-source、S7、MC、OPC UA 或厂商 PLC SDK 语义
- 当前已额外整理一份现场联调短清单：[plc-modbus-field-debug-checklist.md](plc-modbus-field-debug-checklist.md)

### 三、工业缺陷 / 异常检测

当前阶段默认不把整套“缺陷 / 异常流程节点”直接塞进 core。

当前阶段建议拆成三层：

- `core.vision.*`
  - 只保留稳定、可解释、模型无关、算法无关的原子指标与检查节点
- `custom.opencv.*`
  - 承担传统 OpenCV 缺陷流程、差异检测、轮廓检测、表面异常启发式流程
- `custom.anomaly.*`
  - 后续深度学习异常检测模型节点，单独建模、单独演进

理由：

- 如果把完整工业缺陷流程都塞进 core，核心节点会迅速臃肿
- 传统 OpenCV 方法与深度学习异常模型迭代节奏完全不同，不应绑在一个层里
- core 更适合承载“稳定共用的度量和规则原子”，而不是整套现场算法流水线

## 分层原则

### 一、core 层

`core` 只放以下能力：

- 不依赖厂商 SDK
- 不依赖具体协议栈
- 不依赖具体设备型号
- 能在 Windows / Ubuntu 常规运行时里稳定复用
- 对 workflow 具有长期通用价值

当前阶段再增加一条硬约束：

- 不把依赖 OpenCV 具体启发式流程、厂商 SDK、现场阈值经验或具体异常模型的整套节点直接塞进 core

建议继续把 `core` 细分为：

- `core.io.*`
  - 本地文件、目录、视频、通用输入输出
- `core.cv.*`
  - 原始图像处理、几何变换、传统视觉算子、形状与量测原语
- `core.vision.*`
  - 结构化视觉结果处理、检测/分割/轨迹桥接、缺陷指标和工业解释性指标
- `core.rule.*`
  - OK / NG、阈值、范围、报警、工艺规则
- `core.output.*`
  - JSON / CSV / HTTP、统一结果对象、批次结果汇总

### 二、custom 层

`custom` 只放以下能力：

- 依赖设备 SDK
- 依赖厂商运行时
- 依赖协议驱动
- 依赖现场网络或硬件连接方式
- 不同客户现场差异很大

建议命名继续按能力族拆 pack，而不是做一个“大杂烩工业节点包”：

- `custom.camera.*`
- `custom.plc.*`
- `custom.protocol.*`
- `custom.output.*`
- `custom.opencv.*`
- `custom.anomaly.*`

### 三、trigger-source 层

这一层不是普通 workflow 节点。

这一层的职责是：

- 常驻监听外部事件
- 把事件映射成 `WorkflowRun` 或 `WorkflowAppRuntime invoke`
- 管理幂等、去抖、健康状态和重连

这一层不应承担：

- 图像处理
- 工艺判定
- 重量级业务逻辑

### 四、为什么要分层

如果不分层，后面会很快混乱：

- USB 相机与 Basler / Hikrobot / Dahua 工业相机会混成一类
- Modbus TCP 与 S7 / MC 这类协议会混成一类
- OpenCV 原始算子、结构化视觉结果和业务规则会混成一类
- 常驻监听器和一次性 workflow 节点会混成一类

## 相机节点规划

### 适用原则

相机接入至少要先按“连接方式”和“SDK 依赖”分层，而不是统称“相机节点”。

建议分为 5 层：

### 第一层：通用 USB / UVC 相机

建议 pack：

- `custom.camera.usb_uvc_nodes`

适用对象：

- 普通 USB 摄像头
- UVC 兼容工业相机
- 调试机上的低门槛单帧采集

建议节点：

- `custom.camera.usb.enumerate-devices`（已实现）
- `custom.camera.usb.open-device`（已实现）
- `custom.camera.usb.capture-frame`（已实现）
- `custom.camera.usb.start-stream`（已实现）
- `custom.camera.usb.read-latest-frame`（已实现）
- `custom.camera.usb.read-window`（已实现）
- `custom.camera.usb.close-device`（已实现）
- `custom.camera.usb.get-parameter`（已实现）
- `custom.camera.usb.set-parameter`（已实现）

说明：

- 这一层优先解决“最简单能用”的相机接入
- 适合现场调试、开发验证、轻量单帧判定
- 不应假设它能覆盖所有工业相机场景
- 当前阶段实现时，先以这一层为唯一默认相机方向
- 当前已先把“枚举设备 -> 打开会话 -> 重复采集单帧 -> 参数读取/写入 -> 关闭句柄 -> 输出标准 `image-ref.v1`”这条单帧主线收通

### 第二层：RTSP / 网络视频流

建议 pack：

- `custom.camera.rtsp_nodes`

适用对象：

- 网络摄像头
- NVR / 边缘网关转出的 RTSP
- 只提供流地址、不提供工业 SDK 的现场

建议节点：

- `custom.camera.rtsp.open-stream`
- `custom.camera.rtsp.read-frame`
- `custom.camera.rtsp.read-window`
- `custom.camera.rtsp.snapshot`
- `custom.camera.rtsp.close-stream`

说明：

- 这一层更接近视频流输入，而不是工业相机 SDK 控制
- 适合巡检、复盘、低频抓图
- 不适合替代工业触发采图

### 第三层：通用工业相机抽象层

建议 pack：

- `custom.camera.genicam_nodes`

适用对象：

- 具备较好 GenICam 兼容性的 GigE Vision / USB3 Vision 工业相机

建议节点：

- `custom.camera.genicam.enumerate-devices`
- `custom.camera.genicam.open-device`
- `custom.camera.genicam.capture-frame`
- `custom.camera.genicam.software-trigger`
- `custom.camera.genicam.get-parameter`
- `custom.camera.genicam.set-parameter`
- `custom.camera.genicam.read-latest-frame`
- `custom.camera.genicam.close-device`

说明：

- 这一层只有在实际验证过稳定性后才值得推进
- 很多工业相机即使号称兼容标准，现场仍常常要落回厂商 SDK
- 不应把这一层当成“所有工业相机的最终统一方案”

### 第四层：厂商 SDK 相机节点包

建议按厂商独立拆 pack：

- `custom.camera.basler_pylon_nodes`
- `custom.camera.hikrobot_mvs_nodes`
- `custom.camera.dahua_mvsdk_nodes`
- `custom.camera.mindvision_nodes`

每个 pack 的建议节点族尽量一致：

- `enumerate-devices`
- `open-device`
- `capture-frame`
- `software-trigger`
- `start-stream`
- `read-latest-frame`
- `get-parameter`
- `set-parameter`
- `close-device`

说明：

- 这才是工业现场长期最常见、也最现实的接法
- 不同厂商 SDK 安装、设备发现、触发模式、曝光参数、像素格式和异常恢复方式差异很大
- 必须分 pack，不要做成一个“大而全 industrial-camera 节点包”

### 第五层：采集卡 / Frame Grabber / Camera Link / CoaXPress

建议 pack：

- `custom.camera.framegrabber_nodes`

适用对象：

- Camera Link
- CoaXPress
- 依赖采集卡 SDK 的高带宽工业视觉现场

建议节点：

- `enumerate-boards`
- `enumerate-channels`
- `open-channel`
- `capture-frame`
- `start-grab`
- `read-latest-frame`
- `stop-grab`
- `close-channel`

说明：

- 这一层通常是更后期能力
- 很多现场需要先有成熟客户或设备驱动边界，再单独做

### 相机节点与 trigger-source 的边界

同样是相机，不应只做一种形态。

建议分清 3 类能力：

- workflow 节点
  - 适合人工调试、低频采图、单次抓帧
- trigger-source
  - 适合持续监听软件触发、目录落图、PLC 信号联动后采图
- 长驻 runtime / daemon
  - 适合高频流读取、缓存最新帧、统一健康检查

建议不要把“持续取流”直接塞进普通一次性 workflow 节点里长期空转。

## PLC / 协议节点规划

PLC 也必须按协议族和设备边界分层，不能只写“PLC 节点”。

### 第一层：Modbus TCP

建议 pack：

- `custom.plc.modbus_tcp_nodes`

原因：

- 最基础
- 跨品牌
- 现场接入门槛低
- 适合作为第一批正式 PLC 节点
- 当前阶段实现时，先以这一层为唯一默认 PLC 方向

建议节点：

- `custom.plc.modbus.read-value`
- `custom.plc.modbus.write-value`
- `custom.plc.modbus.wait-condition`
- `custom.plc.modbus.write-result-signals`

当前实现说明：

- 当前第一批节点已经全部落地，并保持在 `value.v1` 统一输入输出边界上，便于先与现场 workflow、规则节点和结果回传节点拼成最小闭环
- 当前 `read-value / write-value` 都支持通过可选 `request` 输入做运行时覆盖，便于把 host、unit_id、register_address、data_type、value 等参数从上游结果或现场配置动态传入
- 当前 `read-value / write-value` 直接按 `00001 / 10001 / 30001 / 400001` 这类逻辑地址语义接点位，不再要求 workflow 侧先区分 coils / input registers / holding registers
- 当前 `data_type` 已补齐到 `bool / uint8 / int8 / uint16 / int16 / uint32 / int32 / uint64 / int64 / float / double / string`
- `wait-condition` 当前适合等待 ready 位、确认位、状态字或阈值条件；`wait_timeout_seconds = null` 表示无限等待，但真正长期常驻监听仍应归到后续 TriggerSource 类实现，不承担 TriggerSource 常驻守护职责
- 当前仓库已补三条 checked-in Modbus 样例：`plc_modbus_wait_status_word_ready_mask.*`、`plc_modbus_wait_status_word_alarm_mask.*`，以及把 `wait-condition -> write-value -> result-record -> http-post` 串成现场握手回传闭环的 `plc_modbus_wait_ready_ack_callback.*`

### Modbus 结果回写节点设计

建议节点：

- `custom.plc.modbus.write-result-signals`

定位：

- 放在 `custom_nodes/plc_modbus_tcp_nodes/`
- 继续复用现有 shared Modbus TCP transport 与 `write-value` 的地址、数据类型和编码语义
- 第一阶段只做 Modbus TCP 结果回写，不抽象成“通用 PLC 输出节点”
- 后续如果需要 S7 / MC / OPC UA 回写，分别在对应协议 pack 中做同型节点

目标场景：

- 把 `result-record.v1` 中的 `OK / NG / reason / metrics / alarm`
- 或 `alarm-record.v1` 中的 `active / level / code / message`
- 映射成 PLC 现场可消费的线圈位、状态字、结果码或简短文本

建议输入端口：

- `result`
  - 类型：`result-record.v1`
  - 必填
  - 作用：主结果对象来源
- `alarm`
  - 类型：`alarm-record.v1`
  - 选填
  - 作用：当报警对象独立存在时，直接作为附加信号来源
- `request`
  - 类型：`value.v1`
  - 选填
  - 作用：运行时覆盖 host、port、unit_id、部分信号字面值或信号映射启停，不单独创造第二套节点协议

建议输出端口：

- `result`
  - 类型：`value.v1`
  - 作用：返回本次写回摘要，供后续 `result-record / http-post / json-save-local` 继续归档或排障

建议输出摘要字段：

- `transport`
- `operation`
- `host`
- `port`
- `unit_id`
- `mapping_count`
- `written_count`
- `skipped_count`
- `failed_count`
- `written_items`
- `skipped_items`
- `failed_items`
- `request_source`

其中：

- `written_items` 建议至少记录 `signal_name / register_address / data_type / value`
- `skipped_items` 建议记录 `signal_name / reason`
- `failed_items` 建议记录 `signal_name / register_address / error`

建议参数面：

- `host`
- `port`
- `unit_id`
- `timeout_seconds`
- `retries`
- `continue_on_error`
- `default_word_order`
- `default_byte_position`
- `default_string_encoding`
- `signal_mappings`

设计原则：

- `host / port / unit_id / timeout_seconds / retries` 继续沿用现有 `read-value / write-value` 语义
- `continue_on_error = false` 作为默认值，更贴现场“写关键结果失败就显式报错”的预期
- 仅在确有需求时再通过 `request` 做运行时覆盖，不把静态配置和动态输入混成难以排障的一层

`signal_mappings` 建议结构：

- `signal_name`
  - 例如 `ok`、`ng`、`alarm_active`、`alarm_code`、`result_code`、`reason_text`
- `enabled`
  - 是否启用该映射
- `source_scope`
  - 建议枚举：`result`、`alarm`、`request`、`literal`
- `source_path`
  - 例如 `ok`、`ok_ng`、`reason`、`metrics.coverage_ratio`、`conditions.coverage_ok`、`code`
- `register_address`
  - 直接使用 `00001 / 10001 / 30001 / 400001` 这类逻辑地址
- `data_type`
  - 继续复用 `bool / uint8 / int8 / uint16 / int16 / uint32 / int32 / uint64 / int64 / float / double / string`
- `literal_value`
  - 仅 `source_scope = literal` 时使用
- `true_value`
  - 布尔值或 `OK/NG` 状态映射到寄存器数值时使用
- `false_value`
  - 与 `true_value` 成对出现
- `word_order`
- `byte_position`
- `string_length`
- `string_encoding`
- `skip_when_missing`
  - 当源值不存在时是否跳过；建议默认 `true`

`source_scope + source_path` 建议约定：

- `result + ok`
  - 读取 `result-record.v1.ok`
- `result + ok_ng`
  - 读取 `result-record.v1.ok_ng`
- `result + reason`
  - 读取 `result-record.v1.reason`
- `result + metrics.coverage_ratio`
  - 读取 `result-record.v1.metrics.coverage_ratio`
- `result + conditions.coverage_ok`
  - 读取 `result-record.v1.conditions.coverage_ok`
- `result + alarm.active`
  - 读取 `result-record.v1.alarm.active`
- `alarm + code`
  - 读取独立 `alarm-record.v1.code`
- `request + signal_values.result_code`
  - 读取运行时覆盖值，例如上游把站点内码先收成 `value.v1`

地址映射建议：

- 线圈位或简单握手位，优先写 `0xxxx`
  - 例如 `ok`、`ng`、`alarm_active`、`ack_needed`
- 数值型结果码、批号片段、简短状态字，优先写 `4xxxx`
  - 例如 `result_code`、`alarm_code`、`product_code`
- 只读输入类地址 `1xxxx / 3xxxx` 不作为默认结果回写目标；如果现场确有特殊网关语义，再由配置显式放开

建议的第一阶段典型映射：

- `ok -> 00001(bool)`
- `ng -> 00002(bool)`
- `alarm_active -> 00003(bool)`
- `ack_needed -> 00004(bool)`
- `result_code -> 400001(uint16 或 string)`
- `alarm_code -> 400011(uint16 或 string)`
- `reason_text -> 400021(string)`

运行时覆盖建议：

- `request.host / request.port / request.unit_id`
  - 覆盖连接目标
- `request.signal_values.<signal_name>`
  - 覆盖单个信号最终写入值
- `request.disabled_signals`
  - 临时跳过部分映射

第一阶段不建议支持：

- 不做任意表达式求值
- 不做一次节点里跨多个 PLC 协议写回
- 不做自动清零所有未映射位
- 不做“推断现场寄存器布局”的隐式逻辑

失败策略建议：

- 默认按 `signal_mappings` 顺序串行写入，便于现场抓包与排障
- 任一关键写入失败时，默认抛错并中断，除非显式开启 `continue_on_error`
- 对 `skip_when_missing = true` 的映射，源值不存在时记入 `skipped_items`，但不算失败
- 输出摘要里必须保留每个 signal 的写入结果，避免只返回一个总成功/失败布尔值

`wait-condition` 使用边界建议：

| 方式 | 当前支持状态 | 典型设置 | 适用场景 | 边界 |
| --- | --- | --- | --- | --- |
| 有限等待 | 已实现 | `wait_timeout_seconds = 5 ~ 300` | 调试联机、有限节拍放行、需要超时即报错的设备确认 | 仍属于一次 workflow 调用里的同步等待，不负责后台常驻监听 |
| 无限等待 | 已实现 | `wait_timeout_seconds = null` | 人工上料确认、换型确认、上游工位节拍不固定但本次流程必须等放行 | 适合“等到满足再继续”，但不适合做长期守护或统一事件源 |
| TriggerSource 常驻监听 | 未来规划 | 由 TriggerSource 自身的轮询周期、去抖、事件投递策略控制 | PLC 位变化主动触发 workflow、长期驻留、统一监听多个地址或设备 | 不应继续塞进普通 `wait-condition` 节点，否则普通 workflow 与守护型集成边界会混乱 |

### 第二层：Siemens S7

建议 pack：

- `custom.plc.s7_nodes`

建议节点：

- `custom.plc.s7.read`
- `custom.plc.s7.write`
- `custom.plc.s7.batch-read`
- `custom.plc.s7.batch-write`
- `custom.plc.s7.wait-condition`

说明：

- S7 常见于较多设备和产线
- 地址语义、数据类型打包和连接管理都与 Modbus 明显不同
- 必须独立成 pack

### 第三层：Mitsubishi MC

建议 pack：

- `custom.plc.mitsubishi_mc_nodes`

建议节点：

- `custom.plc.mc.read`
- `custom.plc.mc.write`
- `custom.plc.mc.batch-read`
- `custom.plc.mc.batch-write`
- `custom.plc.mc.wait-condition`

### 第四层：后续协议族

后续可视现场需要增加：

- `custom.plc.opcua_nodes`
- `custom.plc.fins_nodes`
- `custom.plc.ethernet_ip_nodes`

这些不应抢在 Modbus TCP / S7 / MC 前面。

### PLC 节点与 trigger-source 的边界

PLC 能力也应至少拆成两类：

- workflow 内主动读写节点
  - 适合任务执行时做握手、读当前工位号、写 OK/NG 信号
- trigger-source / listener
  - 适合持续轮询或订阅 PLC 状态变化，并在边沿到达时触发 workflow

建议后续 trigger-source 方向：

- `modbus-poll-trigger`
- `s7-poll-trigger`
- `mc-poll-trigger`

### Modbus TCP trigger-source 当前进度与后续待办

当前判断：

- `modbus tcp trigger-source` 值得做，而且是 PLC 这条线最自然的下一步
- 这一层不应做成普通 workflow 节点，而应落到 `WorkflowTriggerSource + ProtocolAdapter` 体系
- 触发源负责常驻轮询、边沿判定、去抖、幂等与创建 `WorkflowRun`
- workflow 图继续负责后续业务逻辑，例如写 ack、写 OK/NG、`result-record` 和 `http-post`

当前边界：

- `custom_nodes/plc_modbus_tcp_nodes/` 继续只承载 workflow 内主动读写、等待条件与结果回写
- `backend/service/infrastructure/integrations/modbus/` 承载共享 Modbus TCP transport
- 当前 `plc-register` trigger-source adapter 已直接复用共享 transport，不反向依赖 custom node pack

第一阶段已收口为：

- `trigger_kind = plc-register`
- `transport_config.driver = modbus-tcp`
- 地址语义统一使用 `0xxxx / 1xxxx / 3xxxx / 4xxxx`
- 第一阶段只支持 polling，不同时引入 S7 / MC / OPC UA / 厂商 SDK
- 第一阶段默认 `submit_mode = async`
- workflow 完成后的 PLC 回写、HTTP 回传、JSON/CSV 归档继续放在图里，不塞进 adapter

建议事件配置形状：

- `transport_config`
  - `driver`
  - `host`
  - `port`
  - `unit_id`
  - `register_address`
  - `data_type`
  - `word_order`
  - `byte_position`
  - `timeout_seconds`
  - `retries`
  - `poll_interval_ms`
  - `reconnect_interval_ms`
- `match_rule`
  - `operator`
  - `expected_value`
  - `stable_match_count`
  - `trigger_mode`
  - `cooldown_ms`
  - `emit_initial_match`

建议标准化后的原始事件 payload：

- `observed_value`
- `previous_observed_value`
- `matched`
- `register_address`
- `register_area`
- `data_type`
- `host`
- `port`
- `unit_id`
- `occurred_at`
- `sequence_id`
- `response_meta`

当前已落地能力：

- `plc-register` 在未注册 adapter 时，`enable` 会显式失败，不再静默停留在“已启用但未运行”的暧昧状态
- `PlcRegisterTriggerAdapter` 已注册到 `TriggerSourceSupervisor`
- 当前已实现 `modbus-tcp + polling + async submit`
- 当前已补最小 adapter 组件测试，以及 `enable / disable / health` API 测试

实施状态：

1. 抽共享 transport
   - 已完成；Modbus TCP 低层 client 已从 custom node pack 抽到 backend shared integration 层
2. 收控制面行为
   - 已完成；`plc-register` 在未注册 adapter 时，`enable` 会显式失败，而不是静默停留在“已启用但未运行”的暧昧状态
3. 落 `PlcRegisterTriggerAdapter`
   - 已完成第一阶段：已注册到 `TriggerSourceSupervisor`，当前只做 polling + async submit
4. 补输入映射与结果样例
   - 已完成 checked-in 正式样例；当前已提供 `plc-register` 的 TriggerSource 请求样例，以及 `plc-register -> workflow app runtime -> result-record / http-post` 的完整 workflow app 示例
5. 补最小测试
   - 已完成；当前已覆盖 adapter 组件测试、`enable / disable / health` API 测试，以及触发事件标准化与 input binding 映射测试

后续待办：

- `custom.plc.modbus.write-result-signals` 已完成第一阶段骨架与最小运行时，当前已可把 `result-record / alarm-record -> Modbus coils / registers` 这条结果回写主线接通；后续更自然的是补 checked-in workflow 样例与现场联调说明
- 继续扩 `plc-register` 的现场语义，例如多地址监听、更多边沿/状态模式和更细的健康观测字段
- 继续规划 `modbus tcp trigger-source` 之外的协议类型，例如 S7 / MC / OPC UA，但保持分协议拆层，不混成一个大 adapter

暂不建议先做的内容：

- 不先做 `sync-reply` PLC trigger-source
- 不先做多个 PLC 协议共用一个大 adapter
- 不先把 workflow 内 `wait-condition` 改造成常驻 listener
- 不先把 PLC 结果回写塞进 TriggerSource 结果分发层

## 工业瑕疵 / 异常检测仍欠缺的核心节点

当前已有一批 `regions-*`、`roi-*`、`continuity-*` 节点，但对工业缺陷与异常检测来说，还缺少更贴现场的一层。

这里要先分清楚：本节说的“核心节点”，不是把完整缺陷算法都塞进 core，而是只列值得长期复用的共用原子层。

### 这一层是不是传统 OpenCV 方法

不完全是。

这一层更准确地说是：

- 面向缺陷/异常结果的共用原子指标
- 面向图像差异、表面均匀性、结构异常和装配关系的稳定检查原语
- 既可以接传统 OpenCV 流程结果，也可以接后续深度学习异常模型结果

因此这层不等于“传统 OpenCV 方法本体”。

- 传统 OpenCV 流程本体，更适合放在 `custom.opencv.*`
- 深度学习异常检测模型，更适合放在 `custom.anomaly.*`
- `core.vision.*` 只保留共用的、解释性强的指标和检查节点

建议新增 4 个方向：

### 第一组：参考比对 / 差异类节点

建议放置位置：

- `core.cv.*` 或 `core.vision.*`

建议节点：

- `core.cv.image-diff`
- `core.cv.absdiff-threshold`
- `core.cv.reference-align`
- `core.vision.reference-diff-metrics`（已实现）
- `core.vision.foreground-change-ratio`（已实现）

适用场景：

- 漏装
- 多装
- 异物
- 表面残留
- 状态变化检测

### 第二组：表面缺陷 / 外观异常节点

建议节点：

- `core.vision.surface-uniformity-metrics`（已实现）
- `core.vision.surface-uniformity-check`（已实现）
- `core.vision.foreign-object-check`（已实现）
- `core.vision.defect-cluster-count`（已实现）
- `core.vision.defect-largest-cluster-ratio`（已实现）
- `core.vision.defect-density`（已实现）

适用场景：

- 脏污
- 油污
- 涂层不均
- 点状缺陷
- 大面积异常

### 第三组：边缘 / 轮廓 / 结构缺陷节点

建议节点：

- `core.vision.edge-break-check`（已实现）
- `core.vision.edge-profile-gap-check`（已实现）
- `core.vision.linearity-check`（已实现）
- `core.vision.circularity-check`（已实现）
- `core.vision.hole-pattern-check`（已实现）
- `core.vision.corner-missing-check`（已实现）

适用场景：

- 缺口
- 崩边
- 裂纹
- 孔缺失
- 圆度异常
- 轮廓变形

当前这组里已经进一步落地：

- `core.vision.defect-cluster-count`
- `core.vision.defect-largest-cluster-ratio`
- `core.vision.defect-density`
- `core.vision.edge-profile-gap-check`
- `core.vision.hole-pattern-check`
- `core.vision.corner-missing-check`

其中：

- `defect-cluster-* / defect-density` 当前统一复用 `regions.v1 + 可选 roi.v1`，更适合承接 `connected-components`、参考图差异或分割缺陷结果
- `edge-profile-gap-check` 当前提供显式 `horizontal / vertical` profile 语义，适合工位方向已知时，比完全依赖区域主方向的 `edge-break-check` 更稳定
- `hole-pattern-check` 当前适合做孔列数量、节距和离轴偏差检查，可直接覆盖安装孔、定位孔和孔阵列换型的一层常见规则
- `corner-missing-check` 当前适合做轴对齐零件的局部缺角检查，按目标角点窗口填充率输出更直白的 OK / NG 判定

### 第四组：装配 / 位置关系类节点

建议节点：

- `core.vision.multi-part-presence-check`（已实现）
- `core.vision.pair-offset-check`（已实现）
- `core.vision.reference-mark-align-check`（已实现）
- `core.vision.spacing-check`（已实现）
- `core.vision.sequence-order-check`（已实现）

适用场景：

- 装配缺件
- 多件相对位置异常
- 标记点对位异常
- 间距不对
- 排列顺序错误

## 工业缺陷 / 异常节点分层建议

这一部分是当前最关键的结构约束。

### 第一层：core 原子指标与检查

建议保留在 `core.vision.*` 或少量 `core.cv.*` 的，只应是这类能力：

- 差异面积占比
- 前景变化占比
- 表面均匀性度量
- 缺陷密度
- 缺陷聚类计数
- 边缘断裂检查
- 线性度 / 圆度 / 间距 / 装配关系检查

这一层的特点：

- 输入尽量标准化
  - `image-ref.v1`
  - `regions.v1`
  - `roi.v1`
  - `value.v1`
- 输出尽量标准化
  - `regions.v1`
  - `boolean.v1`
  - `value.v1`
- 不绑定某个具体缺陷算法
- 不绑定某个具体模型
- 不绑定某个现场厂商

### 第二层：传统 OpenCV 缺陷流程

建议放在：

- `custom_nodes/opencv_defect_nodes/`
- 对外 pack id 使用 `opencv.defect-nodes`
- 或按能力进一步拆成 `opencv.shape-nodes / opencv.measurement-nodes / opencv.matching-nodes`

这一层适合承载：

- 模板差异检测
- 背景差分
- blob / connected components 缺陷筛选
- 基于 contour 的外观缺陷流程
- 基于线、圆、边缘 profile 的结构缺陷流程
- 基于 morphology / threshold / filter 的表面异常流程

建议这层节点尽量把输出统一到：

- `image-ref.v1`
- `contours.v1`
- `measurements.v1`
- `regions.v1`
- `value.v1(summary)`

这样它们就能接到现有 `core.vision.*` 与 `core.rule.*` 主线。

### 第三层：深度学习异常检测模型

建议单独作为：

- `custom.anomaly.model_nodes`

后续如需要，再按模型族拆 pack：

- `custom.anomaly.padim_nodes`
- `custom.anomaly.patchcore_nodes`
- `custom.anomaly.efficientad_nodes`
- `custom.anomaly.draem_nodes`

这一层的职责是：

- 加载异常检测模型
- 输出异常分数、异常热力图、异常区域
- 再桥接到统一规则链

建议后续统一输出：

- `regions.v1`
- `value.v1(summary)`
- 预留 `anomaly-map.v1` 或 `heatmap.v1`

说明：

- 这样后续增加深度学习异常检测模型时，不需要重写整条工业规则链
- 传统 OpenCV 缺陷流程和深度学习异常模型，也能复用同一批 `core.rule.*` 与 `core.output.*`

## OpenCV 与传统机器视觉算子规划

### 当前判断

当前 `opencv_basic_nodes` 不是没有价值，但按真实实现宽度看，它已经不再只是“基础包”。虽然前四轮已经把几何矫正层独立拆到 `opencv.geometry-nodes`、把量测层独立拆到 `opencv.measurement-nodes`、把轮廓与线圆抽取层独立拆到 `opencv.shape-nodes`、把差异与缺陷后处理层独立拆到 `opencv.defect-nodes`，但剩余 pack 仍然同时承载预处理、匹配与调试渲染几类能力；如果继续在同一个目录里无限加节点，后续 catalog、测试、文档和发布维护成本仍会持续上升。

建议后续不要只在现有 pack 上无限加节点，而是按能力族拆成几包：

- `opencv.basic-nodes`
- `opencv.shape-nodes`
- `opencv.measurement-nodes`
- `opencv.geometry-nodes`
- `opencv.matching-nodes`
- `opencv.defect-nodes`

这样比一个越来越大的 `opencv_basic_nodes` 更容易维护。

第一轮拆分约束建议保持：

- 第一轮先拆 pack 边界、manifest、catalog 与测试归属，不主动改现有 `custom.opencv.*` 的 `node_type_id`
- 第一轮不直接打断现有 checked-in workflow、示例文档和上游引用路径
- 调试渲染、bridge 与导出节点第一轮先继续留在 `opencv.basic-nodes`，避免为此额外再开一个 `render` pack

### Pack 拆分映射表（第一版）

| 目标 pack | 当前状态 | 建议收纳节点 | 说明 |
| --- | --- | --- | --- |
| `opencv.basic-nodes` | 已实现，仍待继续瘦身 | `grayscale / resize / crop / normalize / clahe / median-blur / bilateral-filter / gaussian-blur / adaptive-threshold / otsu-threshold / binary-threshold / invert / morphology / canny / sobel / laplacian / draw-detections / draw-contours / draw-lines / draw-circles / draw-roi / draw-measurements / mask-overlay / crop-export / gallery-preview / payload-to-value` | 承载基础预处理、通用调试渲染、桥接与导出。第一轮继续把 render / bridge 留在这里，不再额外增加新 pack。 |
| `opencv.shape-nodes` | 已实现，第三步拆分试点已完成 | `contour / contour-filter / contour-approx / convex-hull / min-area-rect / fit-ellipse / contours-to-regions / hough-lines / hough-circles / fit-line / min-enclosing-circle` | 承载轮廓、线圆、形状拟合和从图像几何结果到结构化 payload 的抽取层。当前已由 shape pack checked-in catalog 与量测 workflow 样例共同收口。 |
| `opencv.measurement-nodes` | 已实现，第二轮拆分试点已完成 | `measure / caliper-edge / point-distance / point-to-line-distance / line-angle / circle-diameter / slot-width / parallelism-metrics / concentricity-metrics` | 承载工业量测原语，避免和预处理或缺陷流程耦在同一 pack。当前已由 `line_pair_measure_gate / circle_concentricity_gate` 两条样例链收口。 |
| `opencv.geometry-nodes` | 已实现，第一轮拆分试点已完成 | `rotation-correct / perspective-transform / affine-transform / undistort / remap / planar-transform-bridge` | 承载姿态、标定、坐标变换和几何矫正能力。当前已作为 pack 拆分试点落地，并补齐 `planar-transform.v1 -> image-ref.v1 / roi.v1` 这层受控桥接。 |
| `opencv.matching-nodes` | 已实现，第五步拆分试点已完成 | `template-match / orb-keypoints / orb-match / homography-estimate` | 承载模板定位、局部特征匹配与平面对位链。当前 `template-match` 已从 `opencv.basic-nodes` 迁出，ORB / homography 也已落地，并补到 `local-features.v1 / feature-matches.v1 / planar-transform.v1` 三类共享 payload 规则。 |
| `opencv.defect-nodes` | 已实现，第四步拆分试点已完成 | `image-diff / absdiff-threshold / connected-components / fill-holes / distance-transform / watershed / skeletonize / heatmap-preview` | 承载差异、缺陷、形态学后处理与缺陷调试预览链。当前已落地 `image-diff / absdiff-threshold / connected-components / fill-holes / distance-transform / heatmap-preview / watershed / skeletonize`。 |

如果后续 `draw-* / overlay / preview` 这组节点继续明显增长，再考虑第二轮额外拆出 `opencv.render-nodes`。当前第一轮不需要先把问题拆得过细。

### 第一批最值得继续补的 OpenCV 常用算子

### 图像预处理

建议节点：

- `custom.opencv.grayscale`（已实现）
- `custom.opencv.resize`（已实现）
- `custom.opencv.crop`（已实现）
- `custom.opencv.normalize`（已实现）
- `custom.opencv.clahe`（已实现）
- `custom.opencv.median-blur`（已实现）
- `custom.opencv.bilateral-filter`（已实现）
- `custom.opencv.adaptive-threshold`（已实现）
- `custom.opencv.otsu-threshold`（已实现）
- `custom.opencv.invert`（已实现）

### 边缘与线条

建议节点：

- `custom.opencv.sobel`（已实现）
- `custom.opencv.laplacian`（已实现）
- `custom.opencv.hough-lines`（已实现）
- `custom.opencv.hough-circles`（已实现）
- `custom.opencv.fit-line`（已实现）
- `custom.opencv.min-enclosing-circle`（已实现）

### 轮廓与形状

建议节点：

- `custom.opencv.contour-filter`（已实现）
- `custom.opencv.contour-approx`（已实现）
- `custom.opencv.convex-hull`（已实现）
- `custom.opencv.min-area-rect`（已实现）
- `custom.opencv.fit-ellipse`（已实现）
- `custom.opencv.contours-to-regions`（已实现）

### 几何与标定

建议节点：

- `custom.opencv.perspective-transform`（已实现）
- `custom.opencv.affine-transform`（已实现）
- `custom.opencv.undistort`（已实现）
- `custom.opencv.remap`（已实现）
- `custom.opencv.rotation-correct`（已实现）

### 匹配与定位

建议节点：

- `custom.opencv.template-match`（已实现）
- `custom.opencv.orb-keypoints`（已实现）
- `custom.opencv.orb-match`（已实现）
- `custom.opencv.homography-estimate`（已实现）

说明：

- 当前使用面已经先补出 checked-in 样例 `industrial_single_frame_calibrated_template_edge_gate.*`，把 `json-load-local -> undistort / remap -> template-match / caliper-edge -> 工业规则链` 这条更贴现场的本地标定定位主线先收稳
- `industrial_single_frame_calibrated_orb_homography_gate.*` 也已补齐，把 `json-load-local -> undistort / remap -> orb-keypoints -> orb-match -> homography-estimate -> planar-transform-bridge -> 工业规则链` 这条更重的参考对位链正式收成 checked-in 模板
- ORB / homography 这条链保留为第二层更重配准能力，不抢在 template-match、ROI 和 caliper-edge 前面

#### ORB / Homography 项目内正式规格

`custom.opencv.orb-keypoints`

- 输入 payload：
  - `image`：`image-ref.v1`
  - `roi`：`roi.v1`，可选，只在指定搜索范围内提取局部特征
- 输出 payload：
  - `features`：`local-features.v1`
  - `summary`：`value.v1`
- `local-features.v1` 建议字段：
  - `feature_extractor`：固定为 `orb`
  - `descriptor_kind`：固定为 `orb`
  - `descriptor_dtype`：`uint8`
  - `descriptor_length`
  - `items`：`feature_id / x / y / size / angle_deg / response / octave / class_id`
  - `descriptors`：与 `items` 一一对应的二维整数数组
  - `source_image`、`roi_id`
- 节点边界：
  - 只负责局部特征点检测和描述子提取
  - 不负责特征匹配、几何变换估计、图像矫正、规则判定或可视化
- 现场使用方式：
  - 适合模板匹配不够稳、存在一定旋转缩放或局部视角变化时，先把参考图与现场图提取成可匹配特征

`custom.opencv.orb-match`

- 输入 payload：
  - `features_a`：`local-features.v1`
  - `features_b`：`local-features.v1`
- 输出 payload：
  - `matches`：`feature-matches.v1`
  - `summary`：`value.v1`
- `feature-matches.v1` 建议字段：
  - `matcher_kind`：如 `bf-hamming`
  - `cross_check`
  - `items`：`match_id / query_feature_id / train_feature_id / query_index / train_index / distance / query_xy / train_xy`
  - `source_a_image`、`source_b_image`
- 节点边界：
  - 只负责描述子匹配、比值过滤或交叉校验后的匹配结果整理
  - 不负责从匹配直接推出 homography，也不直接输出 warp 后图片
- 现场使用方式：
  - 适合把“参考图特征”和“现场图特征”之间的候选对应关系先显式暴露出来，便于人工看匹配密度和误匹配情况

`custom.opencv.homography-estimate`

- 输入 payload：
  - `matches`：`feature-matches.v1`
  - `features_a`：`local-features.v1`
  - `features_b`：`local-features.v1`
- 输出 payload：
  - `transform`：`planar-transform.v1`
  - `summary`：`value.v1`
- `planar-transform.v1` 建议字段：
  - `transform_kind`：固定为 `homography`
  - `matrix_3x3`
  - `inverse_matrix_3x3`，可选
  - `match_count`
  - `inlier_count`
  - `inlier_match_ids`
  - `reprojection_error`
  - `source_a_image`、`source_b_image`
- 节点边界：
  - 只负责根据匹配关系估计平面变换
  - 不负责直接执行图像 warp；真正做几何矫正仍应交给 `perspective-transform` 或后续 `affine-transform`
  - 不负责直接输出 OK/NG 规则结果
- 现场使用方式：
  - 适合复杂换型、参考板对位、视角有一定变化、单纯 bbox 模板匹配难以稳定覆盖的场景

为什么当前仍不建议默认先用：

- 工业单帧主线当前大多数还是固定工位、小位姿扰动，`template-match + ROI + caliper-edge` 更直白、可解释、调参成本更低
- ORB 对纹理、清晰度和反光更敏感，在低纹理、均匀表面或轻微虚焦场景下往往不如模板匹配稳
- 这条链虽然已经实现，但仍额外引入 `local-features.v1 / feature-matches.v1 / planar-transform.v1` 这组 payload 和更多调试维度，现场理解成本天然高于 template-match
- 当前仓库已经补出通用的 `planar-transform.v1 -> image-ref.v1 / roi.v1` 受控桥接节点 `custom.opencv.planar-transform-bridge`，可继续把 homography 结果显式接到参考帧 warp、ROI 投影和后续量测链
- 因此当前更合理的默认顺序仍然是先用本地标定定位模板和 `sobel / laplacian` 这类更直白的链，只有在模板定位不稳时再切到 ORB

### 二值 / 分割 / 形态学增强

建议节点：

- `custom.opencv.connected-components`（已实现）
- `custom.opencv.distance-transform`（已实现）
- `custom.opencv.watershed`（已实现）
- `custom.opencv.skeletonize`（已实现）
- `custom.opencv.fill-holes`（已实现）

说明：

- `skeletonize` 如果需要额外依赖，应单独说明，不要悄悄引入

### 第二批最值得补的量测节点

工业现场很多不是“分类”，而是“量测 + 容差”。

建议节点：

- `custom.opencv.caliper-edge`（已实现，`opencv.measurement-nodes`）
- `custom.opencv.point-distance`（已实现，`opencv.measurement-nodes`）
- `custom.opencv.point-to-line-distance`（已实现，`opencv.measurement-nodes`）
- `custom.opencv.line-angle`（已实现，`opencv.measurement-nodes`）
- `custom.opencv.circle-diameter`（已实现，`opencv.measurement-nodes`）
- `custom.opencv.slot-width`（已实现，`opencv.measurement-nodes`）
- `custom.opencv.parallelism-metrics`（已实现，`opencv.measurement-nodes`）
- `custom.opencv.concentricity-metrics`（已实现，`opencv.measurement-nodes`）

说明：

- 第一阶段不必一口气做成完整几何公差软件
- 先做最常见、可解释、易组合的量测原语

### 第三批最值得补的渲染与调试节点

建议节点：

- `custom.opencv.draw-contours`（已实现）
- `custom.opencv.draw-lines`（已实现）
- `custom.opencv.draw-circles`（已实现）
- `custom.opencv.draw-roi`（已实现）
- `custom.opencv.draw-measurements`（已实现）
- `custom.opencv.mask-overlay`（已实现）
- `custom.opencv.heatmap-preview`（已实现）

说明：

- 现场调试非常依赖“能不能把规则依据画出来”
- 渲染节点不是附属品，而是提高现场可用性的关键部分

## 推荐实现顺序

如果按工业现场价值排序，建议先后顺序如下：

### 第一阶段

- `custom.camera.usb_uvc_nodes`（前三批已实现：`enumerate-devices / capture-frame / open-device / start-stream / read-window / read-latest-frame / get-parameter / set-parameter / close-device`）
- `custom.plc.modbus_tcp_nodes`（主动读写 / wait-condition / write-result-signals 已实现）
- `custom.opencv.grayscale / resize / adaptive-threshold / otsu-threshold`（已实现）
- `custom.opencv.crop / normalize / clahe / median-blur / bilateral-filter / invert`（已实现，`opencv.basic-nodes`）
- `custom.opencv.rotation-correct / perspective-transform / affine-transform / undistort / remap`（已实现，`opencv.geometry-nodes`）
- `custom.opencv.contour-approx / convex-hull / fit-ellipse / fill-holes / distance-transform`（已实现）
- `custom.opencv.sobel / laplacian`（已实现）
- `custom.opencv.hough-lines / hough-circles`（已实现）
- `custom.opencv.fit-line / min-enclosing-circle`（已实现）
- `custom.opencv.contour-filter / min-area-rect / contours-to-regions`（已实现）
- `custom.opencv.connected-components / image-diff / absdiff-threshold`（已实现）
- `core.vision.reference-diff-metrics`（已实现）
- `core.vision.foreign-object-check`（已实现）
- `core.vision.surface-uniformity-check`（已实现）

### 第二阶段

- `custom.opencv.template-match`（已实现）
- `custom.opencv.orb-keypoints / orb-match / homography-estimate`（已实现）
- `custom.opencv.caliper-edge`（已实现）
- `custom.opencv.point-distance / point-to-line-distance / line-angle / circle-diameter / slot-width / parallelism-metrics / concentricity-metrics`（已实现）
- `core.vision.edge-break-check`（已实现）
- `core.vision.edge-profile-gap-check`（已实现）
- `core.vision.linearity-check`（已实现）
- `core.vision.circularity-check`（已实现）
- `core.vision.defect-cluster-count / defect-largest-cluster-ratio / defect-density`（已实现）
- `core.vision.hole-pattern-check / corner-missing-check`（已实现）
- `core.vision.multi-part-presence-check`（已实现）
- `core.vision.pair-offset-check`（已实现）
- `core.vision.reference-mark-align-check`（已实现）
- `core.vision.spacing-check`（已实现）
- `core.vision.sequence-order-check`（已实现）
- `custom.anomaly.model_nodes`

### 第三阶段

- `custom.camera.basler_pylon_nodes`
- `custom.camera.hikrobot_mvs_nodes`
- `custom.plc.s7_nodes`
- `custom.plc.mitsubishi_mc_nodes`
- `custom.camera.framegrabber_nodes`
- `custom.opencv.watershed / skeletonize / heatmap-preview`（已实现；后续只需继续补更贴现场的 checked-in workflow 与交付样例）
- `custom.anomaly.model_nodes`
- `trigger-source` 中的 `modbus-poll-trigger / s7-poll-trigger`

## 当前建议

从现在开始，不建议再把“工业扩展节点”简单写成：

- 相机节点
- PLC 节点
- OpenCV 节点

而应至少按下面这套结构推进：

- 相机：USB / RTSP / 通用工业相机 / 厂商 SDK / 采集卡
- PLC：Modbus TCP / S7 / Mitsubishi MC / 后续协议
- 缺陷 / 异常：`core 原子指标` / `custom.opencv 传统流程` / `custom.anomaly 深度学习模型`
- OpenCV：预处理 / 边缘线圆 / 轮廓形状 / 几何标定 / 匹配定位 / 量测 / 渲染调试 / 缺陷流程

这样后面真正进入实现时，才不会继续“节点名很多，但层次不清、维护困难、现场不好落地”。
