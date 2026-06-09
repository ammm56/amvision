# 当前实现状态

## 文档目的

本文档用于同步当前主干已经落地的整体框架、主要代码落点、YOLOX 端到端能力范围、`YOLOE / SAM3` custom node 现状，以及下一步收敛重点。

本文档补充 [system-overview.md](system-overview.md) 的长期架构视角，重点回答“当前代码已经做到哪里”。

## 适用范围

- backend-service、BackgroundTaskManager、deployment process supervisor 的当前装配方式
- YOLOX 训练、人工验证、评估、转换、部署和推理的已落地链路
- `YOLOE / SAM3` project-native custom node 的当前能力边界
- 当前公开 REST / WebSocket 资源面与主要运行时矩阵
- 下一步优先补强事项

## 当前结论

- 以 YOLOX 为中心的训练 -> 人工验证 -> 数据集级评估 -> 转换 -> DeploymentInstance 发布 -> 同步 / 异步推理接口闭环已经打通。
- backend-service 当前承担 REST / WebSocket 控制面和 deployment process supervisor，全部队列消费者已经收敛到独立 worker profile。
- 当前公开 REST v1 已覆盖 auth、本地用户与权限管理、datasets、dataset-exports、models、detection training tasks、classification/segmentation/pose/obb training tasks、detection/classification/segmentation/pose/obb validation sessions、deployment-instances、inference-tasks，以及 yolox training tasks、validation-sessions、conversion-tasks、evaluation-tasks、projects 目录与对象读取、workflow runtime 资源和 tasks。
- workflow 公开资源面已经拆成 preview-runs、execution-policies、app-runtimes、runs 和 trigger-sources；当前开始把状态集合、snapshot 路径和 preview cleanup 规则收敛到共享 contracts 语义，避免 route、service、maintenance 和文档继续各写一份。
- 当前公开 WebSocket 已覆盖 auth、system、tasks、workflows.preview-runs、workflows.runs、workflows.app-runtimes、deployments 和 projects 八类资源流；统一的路由分层、重连规则和项目级聚合流边界已整理到 [websocket-architecture.md](websocket-architecture.md)。
- backend-service 当前已经补齐本地前端接入所需的 CORS、hybrid auth、Project 目录接口和 Project 内对象读取接口；主要工作台列表接口已经统一到 offset/limit + 响应头分页规则。
- backend-service 当前已经补齐本地用户、权限范围、session/refresh token、长期调用 user token 和 auth.events 审计流；在线 provider 只保留目录发现与后续扩展边界。
- `YOLOE / SAM3` 当前已经不是骨架：两者都已接通 project-native custom node runtime，不依赖 `projectsrc/` 或已安装官方包执行推理；其中 `YOLOE` 已覆盖 `prompt-free / text-prompt / visual-prompt` 三条节点链，`SAM3` 已覆盖 `interactive-segment / semantic-segment / video-interactive-segment / video-semantic-segment` 四条节点链。
- `YOLOE text-prompt` 当前支持同一 `prompt_id` 下 positive / negative 文本组合；`YOLOE visual-prompt` 当前支持 `box / point / polygon / mask` 四类提示及同一 `prompt_id` 下混合提示聚合。`SAM3 interactive-segment` 当前支持 `box / point / polygon / mask`；`SAM3 semantic-segment` 当前支持同一 `prompt_id` 下 grouped positive / negative 文本提示；`SAM3 video-interactive-segment` 当前支持 `frame-window.v1 + prompt-regions.v1 -> tracks.v1` 的 `memory-prototype-state` 多帧链，也已提供更重的 `memory-attention-tracker` 可选模式，并继续保留 `stateful-mask-propagation` 与 shared prompt 兼容模式；`SAM3 video-semantic-segment` 当前支持 `frame-window.v1 + text-prompts.v1 -> tracks.v1` 的共享文本多帧语义分割链。`stateful-semantic-propagation` 与后续 `memory-prototype` 风格 semantic 视频模式当前仍处于预留规划，不是当前阶段的硬阻塞缺口。
- `SAM3` 当前的实际使用也已经分层明确：简单任务可直接使用单帧 `interactive-segment`；短窗口或变化小的视频可使用 `shared-prompts-across-window`；中等复杂度视频可使用 `stateful-mask-propagation`；更复杂的多帧跟踪当前默认推荐 `memory-prototype-state`；更长窗口、更大位移或更复杂遮挡场景可按需切到 `memory-attention-tracker`。`video-semantic-segment` 当前则保持更克制的 shared-text 路线，适合当前以单帧判定和视频复盘为主的工业现场；只有在明确需要跨帧语义区域稳定性、面积统计或连续工艺区域趋势分析时，才值得继续推进 `stateful-semantic-propagation`。
- `YOLOE / SAM3` 当前不仅有单图 smoke、soak 和 `WorkflowAppRuntime` 受控接入验证；`SAM3 video-semantic-segment` 当前也已经补了 `WorkflowAppRuntime` 受控接入 smoke，以及“本地视频 -> decode -> video-semantic/video-interactive -> overlay -> save -> video-body” 两条显式 integration 闭环。
- 视频 workflow 的使用面当前也已经补到可直接预览和调试：`core.io.frame-window-preview` 会把 `frame-window.v1` 转成 `gallery-preview`；`core.logic.payload-to-value + core.logic.value-field-extract` 可以把 `tracks.v1 / regions.v1 / frame-window.v1 / video-ref.v1` 顺畅桥接到现有 `table-preview / value-preview`；`core.output.video-body` 则负责把最终 `video-ref.v1` 转成正式可播放 `response-body.v1`。
- `SAM3 video-interactive-segment(memory-attention-tracker)` 当前已经把 `history_limit / prototype_momentum / attention_temperature / prototype_blend_weight / max_memory_tokens_per_entry` 正式开放到节点参数面，并提供现场样例 workflow：`docs/examples/workflows/sam3_video_memory_attention_review.template.json`。
- 从工业场景角度看，当前视频能力已经覆盖“单帧判定、视频复盘、交互跟踪、语义区域观察”的主线；后续更值得继续补的是现场明确需要的稳定性增强、规则判定和协议回传，而不是默认把所有视频链都推到最重模式。
- 对当前以单帧判定为主的工业现场，下一批最值得补的是 `core.vision.regions-*`、ROI/coverage、`core.rule.*`、`result-record` 和本地单图/目录输入节点；分批清单已整理到 [industrial-rule-node-plan.md](industrial-rule-node-plan.md)。
- 当前工业规则节点已经开始进入实现：第 1 批 `core.vision.regions-filter / regions-select-best / regions-count / regions-area-sum / regions-area-ratio / regions-bbox-metrics / regions-score-summary` 已接通；第 2 批 `core.vision.roi-create / regions-intersection-metrics / regions-coverage-check / regions-inside-check / regions-offset-check` 也已接通，其中 `roi-create` 当前既支持固定参数，也支持 `value.v1` 动态 ROI 输入，已经可以先完成单帧面积、占比、覆盖率、落位和越界这条工业判定前置链。
- 工业检测/分割主链到规则链之间当前也已补了标准桥接：`core.vision.detections-to-regions` 已接通，当前 deployment detection 或其他输出 `detections.v1` 的模型节点，已经可以先把 bbox 检测结果规整成 `regions.v1`；`core.vision.segments-to-regions` 当前也已接通，外部系统或中间节点如果输出 `segments.v1(mask / polygon / bbox)`，现在也可以统一规整成 `regions.v1` 再进入现有工业规则节点。针对目录批处理或列表迭代这类 `value.v1` 场景，当前也已补 `core.logic.value-to-segments / value-to-regions`，用于把逐项 value 恢复回正式 `segments.v1 / regions.v1` 再接回同一套规则链。`YOLOE / SAM3` 当前仍然直接输出 `regions.v1`，不需要再额外桥接。
- 第 4 批工业判定最小闭环当前也已开始进入实现：`core.rule.threshold-check / presence-check / ok-ng-decision` 与 `core.output.result-record` 已接通，当前已经可以把面积、覆盖率、落位、越界这类前置指标进一步收成 `OK / NG` 和统一结果对象。
- 第 4 批工业语义判定当前也继续往前收了一层：`core.rule.alarm-condition / process-decision` 已接通，`result-record` 也已补齐可选 `alarm` 输入，当前已经可以把多路规则条件直接收成 `OK / NG + reason + conditions + alarm` 的现场结果对象，不必在 workflow 里手工再拼一层。
- 本地单帧工业输入输出闭环当前也已开始接通：`core.io.image-load-local / directory-scan` 与 `core.output.json-save-local / http-post` 已补齐，当前已经可以把“本地图像输入 -> 区域规则 -> OK/NG -> 本地 JSON 落盘或 HTTP 回传”这条现场最常见单帧判定链先闭起来。
- 第 4 批工业规则节点当前又往前收了一层：`core.rule.range-check`、`core.output.alarm-record`、`core.output.csv-append-local`、`core.io.image-list-local`、`core.io.directory-batch-window` 已补齐，当前已经可以把“目录扫描 -> 批次切片 -> 本地图像批量载入 -> 规则判定 -> OK/NG / 报警对象 -> JSON / CSV / HTTP 回传”这条更贴现场的小批量单帧链先收起来。
- `core.io.directory-scan` 当前也已补齐更贴现场的目录输入语义：支持 `min_stable_age_seconds` 文件稳定期过滤、`dedupe_by` 去重策略和更完整的扫描摘要；`core.io.directory-batch-window` 已支持运行时 `start_index / batch_size / cursor` 输入，用于表达“当前批次窗口 + 下一步 cursor”这类推进语义，并继续沿用严格报错边界；`core.io.directory-poll-window` 与 `core.io.json-load-local` 当前也已接通，用于“本地 JSON cursor 恢复 + 当前无新文件时返回 has_work=false”的目录轮询守护语义。
- 目录批处理这条主线当前又收了一层：`core.io.directory-cursor-normalize / directory-cursor-advance / core.output.batch-record / core.io.batch-files-relocate` 已接通，当前已经可以把“本地 JSON cursor 恢复 -> window 输出推进 -> 批次归档对象 -> processed/archive/failed/quarantine 文件归档”这层正式从手工字段约定里抽出来；其中 `batch-files-relocate` 首版默认使用更保守的 `copy + rename`，同时也已支持 `move / overwrite / skip / preserve_subdirectories / dry_run`。
- 输出收口这条线也继续往前走了一步：`core.output.workflow-result / core.output.batch-result-summary` 已接通，当前已经可以把 `result-record / batch-record / metrics / files / trace_id / event_id` 收成统一 `workflow-result.v1`，并把一批 `result-record.v1` 收成独立批次摘要对象；后续 trigger-source、结果回传和目录批次归档不再需要继续手工拼这些中间字段。
- TriggerSource 侧也开始把目录输入真正收成正式入口：`directory-poll` 与 `directory-watch` 当前都已接入 backend-service。前者负责本地目录周期扫描、文件稳定期过滤、扩展名筛选、batch 提交以及本地 checkpoint 恢复；后者负责本地目录事件监听、稳定期过滤、batch 提交以及本地 checkpoint 去重恢复，并支持 `force_polling=true` 的受控事件探测模式。目录触发这一层当前已经从“规划阶段”进入“已实现、待继续补现场样例和更细守护语义”的阶段。
- 第 3 批可解释完整性指标当前已接通完整首轮：`core.vision.region-component-count / region-largest-component-ratio / region-hole-count / region-gap-check / region-span-metrics / region-continuity-score` 已接通，当前已经可以把分割或检测得到的 `regions.v1` 进一步收成“碎片数量 / 主体完整度 / 空洞数量 / 是否明显断裂 / 长轴短轴跨度 / 连续性分数”这类更贴工艺解释和量测的原子指标。
- 工业 workflow 示例当前也已经补到更贴现场的使用说明：`industrial_single_frame_sealant_quality_gate.*`、`industrial_single_frame_segments_continuity_gate.*`、`industrial_single_frame_glue_roi_callback.*`、`industrial_single_frame_glue_polygon_roi_changeover.*`、`industrial_single_frame_regions_overlay_review.*`、`industrial_single_frame_segments_overlay_review.*`、`industrial_single_frame_yoloe_text_overlay_review.*`、`industrial_single_frame_yoloe_visual_overlay_review.*`、`industrial_single_frame_sam3_semantic_overlay_review.*`、`industrial_single_frame_sam3_interactive_overlay_review.*`、`industrial_single_frame_yolox_position_gate.*`、`industrial_single_frame_line_pair_measure_gate.*`、`industrial_single_frame_circle_concentricity_gate.*`、`industrial_local_directory_batch_input.*`、`industrial_local_directory_batch_segments_continuity_gate.*`、`industrial_local_directory_batch_regions_continuity_gate.*`、`industrial_local_directory_batch_yolox_position_gate.*` 与 `industrial_local_directory_polling_cursor_guard.*` 已接通文档测试；其中 `segments_continuity_gate` 当前把“分割输出 `segments.v1` -> `segments-to-regions` -> 连续性规则链”这条正式闭环补通，`glue_polygon_roi_changeover` 当前把多边形 ROI 换型这层 checked-in，`regions_overlay_review` 与 `segments_overlay_review` 则把 `draw-roi / mask-overlay` 这层 checked-in 到“复核图 + result-record”主线上，分别覆盖“上游已是标准 `regions.v1`”和“上游仍是 `segments.v1` 需要先桥接”的两种现场入口，`yoloe_text_overlay_review`、`yoloe_visual_overlay_review`、`sam3_semantic_overlay_review` 与 `sam3_interactive_overlay_review` 则继续把这条复核主线直接前移到本项目自带的 YOLOE / SAM3 节点本身，分别覆盖“文本开放词汇检测”“视觉提示检测”“文本语义分割”和“交互分割”四种单帧直连使用面，`yolox_position_gate` 则把“已发布 detection deployment -> detections.v1 -> regions.v1 -> presence / inside / offset 工业规则链”这条正式闭环补通，`line_pair_measure_gate` 当前把“双边线 -> 槽宽 / 平行度 / 中点距 -> OK/NG”这条传统几何量测链补成正式模板，`circle_concentricity_gate` 当前把“双圆 -> 孔径 / 同心度 / 圆度 -> OK/NG”这条圆形量测链补成正式模板，`industrial_local_directory_batch_input` 把“目录扫描 -> 批次窗口 -> 图片载入”的现场小批量输入准备样例单独收成模板，`industrial_local_directory_batch_segments_continuity_gate` 与 `industrial_local_directory_batch_regions_continuity_gate` 则把“目录批次 -> segments.v1 / regions.v1 -> 连续性规则链 -> CSV / JSON 归档”两类分割上游入口正式接到同一套批处理骨架，`industrial_local_directory_batch_yolox_position_gate` 把目录批次主线正式接到“逐图检测 -> 规则判定 -> CSV 持续归档 -> 批次 JSON 汇总”的闭环，而 `industrial_local_directory_polling_cursor_guard` 则把“目录轮询守护 / cursor 落盘恢复 / 批次归档 JSON”这层独立收口。
- 当前仍未实现、但已经明确值得继续补的待办，现已按 `core / custom / trigger-source / output-integration` 四层收口到 [industrial-rule-node-plan.md](industrial-rule-node-plan.md) 的“未实现正式待办”一节，便于后续按层次推进，而不是继续把工业需求混成一个大列表。
- 对更广义的工业扩展面，当前也已单独补出 [industrial-extension-node-plan.md](industrial-extension-node-plan.md)，把相机连接方式分层、PLC 协议分层、工业缺陷核心节点和 OpenCV 常用算子路线单独收口，避免继续把这些需求都挤进单帧规则文档里。
- 该扩展规划当前也已进一步收口到更贴近实际落地的阶段边界：相机先默认实现 `USB / UVC` 一层，PLC 先默认实现 `Modbus TCP` 一层；工业缺陷 / 异常能力则拆成 `core 原子指标`、`custom.opencv 传统流程` 和后续 `custom.anomaly 深度学习模型` 三层推进，避免把完整缺陷流程直接塞进 core。
- 相机接入这条线当前也已经从“只有规划”进入前两批正式实现：`custom_nodes/camera_usb_uvc_nodes/` 已默认启用，当前不仅有首批 `enumerate-devices / capture-frame`，也已补齐第二批 `open-device / read-latest-frame / get-parameter / set-parameter / close-device`。现在已经可以先把“本机 USB / UVC 相机枚举 -> 打开会话 -> 重复单帧采图 / 参数调整 -> 标准 `image-ref.v1` -> 检测/分割/工业规则链”这条更贴现场调试的相机主线跑起来。
- `opencv_basic_nodes` 当前也已补完前三批更贴工业现场的传统视觉节点：第一批 `grayscale / resize / adaptive-threshold / otsu-threshold / contour-filter / min-area-rect / contours-to-regions` 已接通，第二批 `image-diff / absdiff-threshold / connected-components` 已接通，第三批 `hough-lines / hough-circles / fit-line / min-enclosing-circle` 也已接通；其中 `contours-to-regions` 当前会把 contour 结果直接规整成标准 `regions.v1` 接入既有工业规则链，`min-area-rect` 当前新增 `rotated-rects.v1`，`hough-lines` 与 `fit-line` 当前统一输出 `lines.v1`，`hough-circles` 与 `min-enclosing-circle` 当前统一输出 `circles.v1`，并已由 `custom.opencv.payload-to-value` 统一桥接回 `value.v1` 以便继续做响应拼装和调试预览；而 `image-diff -> absdiff-threshold -> connected-components` 当前已经能把参考图差异或缺陷前景直接规整成带 `mask_image` 的 `regions.v1`，继续接入既有面积、覆盖率、连续性和 OK/NG 工业规则链。
- 传统几何结果往工业量测和规则层也继续收了一层：`custom.opencv.point-distance / point-to-line-distance / line-angle / circle-diameter / parallelism-metrics / concentricity-metrics / slot-width` 当前已接通，分别把 `value.v1 / lines.v1 / circles.v1` 直接收成可继续进入 `threshold-check / range-check / process-decision` 的数值 `value.v1`；`core.vision.linearity-check / circularity-check` 当前也已接通，并保持只依赖标准 `regions.v1`，用于把分割、轮廓或连通域结果统一收成“是否足够直 / 是否足够圆”的工业语义判定。
- 几何量测与区域调试面当前也已补到第一轮完整可用：`custom.opencv.draw-contours / draw-lines / draw-circles / draw-roi / draw-measurements / mask-overlay` 已接通，当前已经可以把 `contours.v1 / lines.v1 / circles.v1 / roi.v1 / regions.v1` 以及量测 summary 直接画回原图，便于现场复核槽宽、平行度、孔径、同心度、检测范围和分割缺陷覆盖层，而不需要只看数值结果猜测哪里出了问题。
- workflow 与 trigger-source 直接依赖这层当前也已经收稳：`requirements.txt` 已显式纳入 `httpx2` 与 `watchfiles`，`fastapi.testclient / starlette.testclient` 的已知弃用 warning 已按当前环境确认消失，不再依赖隐式安装状态。
- `core.vision.reference-diff-metrics / foreign-object-check / surface-uniformity-check` 当前也已接通：现在已经可以把参考图差异前景按 `image` 或 `ROI` 作用域汇总成 `总差异面积 / 占比 / 最大异常块 / 平均异常块 / 有效区域数量`，并直接收成“异物/多余物”或“表面均匀性”这两类更贴工业现场语义的 OK/NG 判定。
- 当前代码形态仍然是“模块化单体 + 本地队列 + 本地对象存储 + 独立 deployment 子进程”。下一步重点应转向拓扑收敛、运行时硬化和平台泛化，而不是继续补 YOLOX 基础闭环缺口。

## 本轮更新（P0 + P1-8 + P3-14 + P3-15）已落地事项

### P0 修复

- RF-DETR detection 已并入统一 detection 训练/转换控制面；`/models/detection/...` 正式主链现在覆盖 `yolox / yolov8 / yolo11 / yolo26 / rfdetr`。
- RF-DETR segmentation 已接通 project-native 模型、训练、`onnx / onnx-optimized / openvino-ir / tensorrt-engine` 转换、DeploymentInstance 主链与端到端 smoke；当前正式任务链已验证 `training -> conversion -> deployment -> onnxruntime infer`，并已在真实工具链环境下补通 `training -> conversion(openvino-ir) -> deployment(openvino) -> infer` 与 `training -> conversion(tensorrt-engine) -> deployment(tensorrt) -> infer` 两条 smoke，运行时已补到 `pytorch / onnxruntime / openvino / tensorrt` 四后端 session。
- 非 Detection 训练管理 API 已补齐：classification/segmentation/pose/obb 各有 list/detail/save/pause/terminate/resume/delete 7 个端点。
- OBB 训练损失已从占位 MSE 替换为完整实现：probiou + 旋转框 TAL + DFL + 角度损失（`backend/service/application/models/obb_loss.py`）。
- Pose 训练损失已从占位 MSE 替换为完整实现：detection 损失 + 关键点位置损失 + 可见性 mask（`backend/service/application/models/pose_loss.py`）。
- model_scale 命名统一：全部 YOLO11/YOLO26 配置和默认值从 `"n"` 改为 `"nano"`。
- workflow core nodes 已新增 SAHI 大图切片推理节点 `core.model.sahi-inference`；当前节点复用已发布 detection deployment 主链完成切片推理、坐标回映射和 `nms / nmm / none` 三种重叠合并，不绕开 DeploymentInstance 与 PublishedInferenceGateway 正式边界。
- `YOLOE` custom node 当前已接通 project-native runtime：`prompt-free-detect`、`text-prompt-detect`、`visual-prompt-detect` 都直接读取本地 `yoloe` 预训练权重，输出 `detections.v1 + regions.v1`；`text-prompt` 支持按 `prompt_id` 聚合 positive/negative 文本，`visual-prompt` 支持 `box / point / polygon / mask` 以及同一 `prompt_id` 下混合视觉提示。
- `SAM3` custom node 当前已接通 project-native runtime：`interactive-segment` 直接读取本地 `sam3.pt`，支持 `box / point / polygon / mask` 四类几何提示；`semantic-segment` 直接读取本地 `sam3.pt` 的 detector 分支，支持按 `prompt_id` 聚合 positive/negative 文本提示并输出 `regions.v1`；`video-interactive-segment` 当前直接复用 `frame-window.v1` 与单图 interactive runtime，按 `prompt_id` 稳定映射 `track_id`，默认走 `memory-prototype-state` 并输出 `tracks.v1`，也已提供基于跨帧 token memory 的 `memory-attention-tracker` 可选模式；`video-semantic-segment` 当前会把共享 `text-prompts.v1` 跨帧执行在 `frame-window.v1` 上，并继续以 `prompt_id` 作为稳定 `track_id` 输出 `tracks.v1`。更强的 `stateful-semantic-propagation` 与后续 semantic memory 模式目前仍保留为现场明确需要时再实现的预留能力。
- `SAM3 video-interactive-segment` 当前已经补了三类定向回归：更长窗口、更大位移和更多对象数；同时也已补 `memory-attention-tracker` 的常规回归、真实本地 smoke、显式视频闭环 integration，以及长窗口/多对象复合场景 benchmark。轻量逻辑回归放在 `tests/`，真实本地 `sam3.pt` 的视频链 smoke 与 benchmark 放在 `tests/integration/`，继续保持显式执行。
- 视频 workflow 的通用结果节点当前已补到 `core.vision.tracks-filter`、`core.vision.tracks-to-regions`、`core.io.video-overlay-render` 和 `core.io.video-save`，已经可以先在通用层完成时序结果筛选、按帧拆分、结果渲染和重新编码保存。
- 视频 workflow 的通用预览与交互辅助节点当前已补到 `core.io.frame-window-preview`、`core.output.video-body` 与 `core.logic.value-field-extract`；配合既有 `core.logic.payload-to-value`、`core.io.table-preview`、`core.io.value-preview`，当前已经能把视频帧窗口、跟踪结果、分帧 regions 和最终保存视频分别接到 workflow editor 的缩略预览、调试表格和正式响应播放器。

### P1-8 Bootstrap 重构

- `build_runtime` 中 5 种 task_type 的 deployment supervisor 构建从 ~150 行重复代码重构为参数化工厂函数。
- `start_runtime`/`stop_runtime` 从逐字段 if-else 改为 `iter_all_deployment_supervisors()` 迭代。

### P3-14 非 Detection 转换路由修复

- classification/segmentation/pose/obb 转换路由从使用缺少 planner 的基类改为使用正确的模型专属服务类（`SqlAlchemyYoloV8/11/26ConversionTaskService`）。

### P3-15 数据集导入删除 API

- 新增 `DELETE /api/v1/datasets/imports/{dataset_import_id}` 端点，支持删除 completed/failed 状态的导入记录并清理关联文件。

## 当前整体框架

### backend-service 控制面

- FastAPI 应用入口位于 `backend/service/api/app.py`，负责装配 settings、数据库会话、本地对象存储、本地队列、中间件、异常处理、REST 路由和 WebSocket 路由。
- backend-service settings 位于 `backend/service/settings.py`，当前已经统一管理 CORS、auth mode、本地 auth TTL、auth provider 目录、静态 token 和 Project 目录配置。
- 启动编排位于 `backend/service/api/bootstrap.py`，负责在应用生命周期内初始化 SessionFactory、LocalDatasetStorage、LocalFileQueueBackend 和 deployment process supervisor。
- REST v1 路由汇总位于 `backend/service/api/rest/v1/router.py`，当前已经挂载 auth、system、projects、workflows、workflow runtime、datasets、dataset-exports、models、detection-training-tasks、classification-training-tasks、segmentation-training-tasks、pose-training-tasks、obb-training-tasks、detection-validation-sessions、classification-validation-sessions、segmentation-validation-sessions、pose-validation-sessions、obb-validation-sessions、deployment-instances、inference-tasks、yolox-training-tasks、validation-sessions、conversion-tasks、evaluation-tasks 和 tasks。
- REST v1 列表分页辅助函数位于 `backend/service/api/rest/v1/pagination.py`，当前用于 projects、workflow templates、template versions、applications、execution-policies、preview-runs、app-runtimes 和 trigger-sources。
- WebSocket 路由位于 `backend/service/api/ws/router.py`，当前已经公开 auth、system、tasks、workflow preview-runs、workflow runs、workflow app-runtimes、deployments 和 projects 聚合流入口。

### custom node 扩展面

- `custom_nodes/yoloe_open_vocab_nodes/` 当前已经具备完整 pack 骨架、catalog、project-native runtime、真实本地资产 smoke 和 grouped prompt summary；pack `metadata.phase` 已收口到 `implemented`，并默认启用。
- `custom_nodes/sam3_segment_nodes/` 当前已经具备完整 pack 骨架、catalog、project-native runtime、真实本地资产 smoke、共享后处理增强和第一阶段视频多帧节点；pack 与节点定义的 `metadata.phase` 都已收口到 `implemented`，并默认启用。
- `custom_nodes/camera_usb_uvc_nodes/` 当前已经作为第一层相机 custom node pack 落地，默认启用；对外节点面当前已收口为 `enumerate-devices / capture-frame / open-device / read-latest-frame / get-parameter / set-parameter / close-device`，其中 `open-device -> read-latest-frame -> close-device` 负责会话型重复采图，`get-parameter / set-parameter` 负责基础分辨率、帧率和常用 UVC 参数调试。当前实现基于项目内 `OpenCV VideoCapture` 适配层，节点已支持运行时 request 覆盖、标准 `image-ref.v1` 输出、`camera-session.v1` 会话 payload 以及结构化采集摘要；后台流式 `start-stream / read-window` 仍保留为下一阶段。
- `custom_nodes/plc_modbus_tcp_nodes/` 当前已经作为第一层 PLC custom node pack 落地，默认启用；对外节点面已收口为 `read-value / write-value / wait-condition` 三个通用节点，直接按 `0xxxx / 1xxxx / 3xxxx / 4xxxx` 地址语义覆盖工业现场最基础的 Modbus TCP 主动读写与等待条件主线。当前 `data_type` 已覆盖 `bool / uint8 / int8 / uint16 / int16 / uint32 / int32 / uint64 / int64 / float / double / string`，`wait-condition` 还已支持 `wait_timeout_seconds = null` 表示无限等待。
- `backend/service/infrastructure/integrations/modbus/` 当前已经补出共享 Modbus TCP transport，并已接入第一阶段 `plc-register` TriggerSource adapter；实现上不再把低层 client 只锁死在 custom node pack 内部。当前 TriggerSource 只支持 `modbus-tcp + polling + async submit`，`enable` 在没有可用 adapter 时也会显式失败并写回 `observed_state = failed`，避免停留在“已启用但未运行”的模糊状态。
- `plc-register` 当前还已经补出一条 checked-in 的正式样例链：`docs/examples/workflows/plc_register_modbus_tcp_async_result_record.*` 与 `docs/api/examples/workflows/08-plc-register-modbus-tcp-async-result-record/` 把 `plc-register -> workflow app runtime -> result-record -> http-post` 串成了完整示例，并把当前 `payload / event -> response-body.v1 -> payload-to-value` 的输入边界一并写入文档。
- PLC 这条线当前还已单独整理出一份更短的现场清单：[plc-modbus-field-debug-checklist.md](plc-modbus-field-debug-checklist.md)。这份文档只回答三件事：当前已经实现了什么、当前还没实现什么、现场联调建议先按什么顺序跑。
- `YOLOE / SAM3` 在 workflow app 侧的接入顺序、`metadata.phase` / `enabledByDefault` 解释和现场排障路径，当前已经单独整理到 [yoloe-sam3-workflow-app-operations.md](yoloe-sam3-workflow-app-operations.md)。
- `YOLOE / SAM3` 预训练资产统一从 `data/files/models/pretrained/` 读取：`YOLOE` 使用本地 segmentation 权重与 `text-encoders` 资产，`SAM3` 使用本地 `sam3.pt`。
- 当前 `YOLOE / SAM3` 都已经补了定向稳定性回归：多 prompt 组合、本地资产 smoke、异常预训练目录、空提示/非法提示、CPU 会话缓存复用。
- 当前 `YOLOE / SAM3` 已在目标机器上补了显式 CPU/GPU soak / benchmark 基线与 1 轮更长时长/更大图尺寸扩展 soak；`SAM3 video-interactive memory-attention` 也已补 1 轮长窗口/多对象复合场景 benchmark。结果记录见 [yoloe-sam3-soak-baseline.md](yoloe-sam3-soak-baseline.md)；相关测试文件位于 `tests/integration/`，默认不参与常规收集。
- 当前 `YOLOE / SAM3` 已补显式 `WorkflowAppRuntime` 接入 smoke：测试会临时把 pack 置为 `enabledByDefault = false`，再覆盖 `disable -> enable -> create -> start -> invoke -> stop` 最小 runtime 闭环；相关测试文件位于 `tests/integration/test_yoloe_sam3_workflow_app_runtime_smoke.py`。
- `custom_nodes/plc_modbus_tcp_nodes/` 当前 pack 已切到项目内最小 Modbus TCP runtime，不依赖 `projectsrc/` 目录或额外第三方 Python 包直接运行；当前还没有继续扩到 S7 / MC / OPC UA，也没有把 PLC 轮询守护混进普通 workflow 节点。
- `docs/examples/workflows/` 当前也已补三条更贴现场的 Modbus 样例：`plc_modbus_wait_status_word_ready_mask.*` 用 `bitmask_all_set` 等待 ready 状态字全部置位，`plc_modbus_wait_status_word_alarm_mask.*` 用 `bitmask_any_set` 等待任一报警位命中，`plc_modbus_wait_ready_ack_callback.*` 则把 `wait-condition -> write-value -> result-record -> http-post` 串成一条更贴现场的握手回传闭环。

### 后台执行与 runtime 面

- 队列消费者分别落在 `backend/workers/datasets/`、`backend/workers/training/`、`backend/workers/conversion/`、`backend/workers/evaluation/` 和 `backend/workers/inference/`。
- 当前独立 worker 已经支持通过 `config/backend-worker.json` 的 `task_manager.enabled_consumer_kinds` 统一装配六类消费者，也支持通过 `runtimes/manifests/worker-profiles/*.json` 以单一职责 profile 启动独立 worker。
- deployment 运行时位于 `backend/service/application/runtime/`，当前由 `yolox_deployment_process_supervisor.py` 管理父进程监督、由 `yolox_deployment_process_worker.py` 管理子进程内模型会话、warmup、keep_warm 和健康状态。
- runtime 适配与统一预测入口位于 `yolox_predictor.py`、`model_runtime.py`、`yolox_inference_runtime_pool.py` 和 `yolox_runtime_target.py`，用于把 pytorch、onnxruntime、openvino、tensorrt 收敛为统一推理契约。

### 关键对象与执行边界

- DatasetExport 是训练和评估的正式执行边界，不直接让训练或评估逻辑读取原始 DatasetVersion 目录结构。
- TrainingTask 负责把训练结果登记为 ModelVersion，并关联 checkpoint、summary、metrics、labels 等输出文件。
- `/models/detection/training-tasks` 当前已经成为 detection 训练的正式公开主链，统一覆盖 `yolox / yolov8 / yolo11 / yolo26 / rfdetr` 五类模型的创建、查询、save、pause、resume、terminate 和输出文件读取。
- ValidationSession 用于训练后的单图人工验证，解决“模型看起来是否正确”的快速抽样检查。
- EvaluationTask 负责基于 DatasetExport 做数据集级回归评估，输出 report、detections 和可选 result-package。
- ConversionTask 负责把 ModelVersion 转成一个或多个 ModelBuild，形成正式部署输入。
- DeploymentInstance 负责把 ModelVersion 或 ModelBuild 绑定到 runtime backend、device、precision 和 deployment metadata。
- InferenceTask 与同步 `/infer` 都只绑定 DeploymentInstance，不直接暴露 checkpoint 路径。

## 当前运行时与发布矩阵

### 训练、验证与评估

- 当前真实训练链路基于 PyTorch checkpoint，训练期 validation 已在训练任务内部接通。
- 当前正式 `/models/{task_type}/validation-sessions` 已覆盖 `detection / classification / segmentation / pose / obb` 五类任务，并统一支持 `pytorch / onnxruntime / openvino / tensorrt` 四类 runtime backend；session 持久化已显式保存 `model_build_id` 与 `runtime_artifact_*` 字段，旧 session 数据仍可回退到 checkpoint 语义读取。
- 当前 `evaluation-tasks` 用于数据集级回归评估，最小执行边界为 `coco-detection-v1` DatasetExport。

### 转换输出

- 当前 conversion 已真实接通 `onnx`、`onnx-optimized`、`openvino-ir` 和 `tensorrt-engine` 四类目标。
- 当前 OpenVINO IR 创建接口按 `fp32` / `fp16` 拆分。
- 当前 TensorRT engine 创建接口按 `fp32` / `fp16` 拆分，并把 build precision 与 TensorRT 版本回写到 `ModelBuild.metadata`。

### 部署运行时

- 当前 deployment 已真实接通 `pytorch fp32/fp16 cpu/cuda`。
- 当前 deployment 已真实接通 `onnxruntime fp32 cpu`。
- 当前 deployment 已真实接通 `openvino fp32 auto/cpu/gpu/npu + fp16 gpu/npu`。
- 当前 deployment 已真实接通 `tensorrt fp32/fp16 cuda`。
- 当前每个 DeploymentInstance 在 sync 和 async 两个通道上各自拥有独立的 deployment 子进程监督单元，不共享会话池。

### custom node 运行时

- `YOLOE` 和 `SAM3` 当前都不走 `DeploymentInstance` 主链，而是在 `WorkflowAppRuntime` 进程内按需首次加载并缓存；当前缓存 key 已稳定覆盖 checkpoint、device 和 precision。
- `YOLOE` 文本提示默认复用本地 `mobileclip_blt.ts + bpe_simple_vocab_16e6.txt.gz`；`SAM3 semantic` 复用项目内 tokenizer 代码与 checkpoint 自带语言骨干，不依赖在线下载或 Hugging Face snapshot。
- 当前 `YOLOE / SAM3` 的 smoke 已覆盖本地 project-native 推理链、输出 contract、缓存复用，以及 `WorkflowAppRuntime` 的 `disable -> enable -> invoke` 最小闭环；当前已经进入默认启用，但仍未进入长期发布服务或多机部署形态收口。

## 当前实现细节中需要明确的事实

- 当前公开的 sync / async deployment 控制面已经包含 `start`、`status`、`stop`、`warmup`、`health` 和 `reset`，并公开 keep_warm、pinned output buffer、restart_count safe counter 等长期运行观测字段。
- 当前 keep_warm 成功次数、失败次数和 deployment restart_count 都采用 JavaScript 安全整数窗口值加 rollover_count 的公开语义，避免长时间运行后的前端数值精度丢失。
- 当前 `backend/workers/main.py` 已经以统一 registry 装配 dataset import、dataset export、training、conversion、evaluation 和 inference 六类消费者；backend-service 不再托管任何队列消费者。
- 当前本地 auth 已拆成 session token、refresh token 和长期调用 user token 三类凭据，并通过 `/ws/v1/auth/events` 提供实时审计流；provider 目录里的在线 provider 当前只保留扩展边界。
- 当前 preview run snapshot 根目录已经稳定到 `workflows/runtime/preview-runs/{preview_run_id}/`，并继续通过显式 maintenance 命令 `cleanup-preview-runs` 清理；当前清理顺序仍是“先删数据库记录，再删 snapshot 目录”，还没有做到跨存储原子提交。
- 当前 app runtime snapshot 根目录已经稳定到 `workflows/runtime/app-runtimes/{workflow_runtime_id}/`；application、template 和 execution-policy snapshot 都按这个根目录组织，供 runtime worker 和后续发布形态复用。
- 当前仓库已经提供 `backend.maintenance.main`、Python launchers、bat/sh wrapper、worker profile manifest，以及 `assemble-release` 命令来生成单一 `full` 发行目录。
- 当前 release 组装会复制完整项目代码和仓库根目录的 `requirements.txt`，不做源码裁剪，也不再维护多套运行时依赖配置。
- 当前标准 maintenance 配置已经接通前端 dist 目录；`assemble-release` 会复制 `frontend/web-ui/dist/` 到发行目录里的 `frontend/`，补齐 `runtime-config.json`，并在覆盖发布时保留现有 `python/` 目录。
- 当前 `assemble-release` 也已把 `runtimes/third_party/ffmpeg/` 复制到发行目录里的 `tools/ffmpeg/`，`validate-layout` 现已把这层一并纳入发布目录检查。

## 下一步建议

### 1. 补强独立 worker 的运行时约束

- 明确不同部署形态下各 worker profile 的并发上限、资源绑定和故障隔离规则，避免只完成“职责拆分”而没有补齐运维边界。
- 为 inference、conversion、training 三类 profile 补充更细的现场部署建议和监控项。

### 2. 补强运行时回归与 benchmark

- 为 pytorch、onnxruntime、openvino、tensorrt 的已支持组合补齐最小 smoke test、精度回归和时延基线。
- 把 conversion report、evaluation report 与 deployment benchmark 的字段进一步收敛成可比较、可回滚的统一结构。

### 3. 从 YOLOX 闭环走向平台能力

- 以现有 YOLOX 链路为样板，继续抽象 `ModelRuntime`、`TrainingBackend`、`ConversionBackend` 和节点扩展边界，让 YOLOX 成为平台里的第一个完整实现，而不是唯一实现。
- 把更多 runtime 相关差异从具体路由和 YOLOX 细节里继续抽离到稳定接口。

### 4. 继续硬化工程化交付面

- 当前 `assemble-release` 已把同目录 Python 运行时占位/回迁、前端构建产物、`custom_nodes` 资产和 `ffmpeg/ffprobe` 工具目录纳入 `release/full/`。
- 下一步重点应转向发布目录的更细粒度验收、日志/指标/排障补充，以及 `full` 目录向现场派生变体时的裁剪规范。
