# 工业规则节点规划

## 文档目的

本文档用于收口工业现场更需要的规则判定、结果回传和输入接入节点规划。

当前项目主线以单帧判定、现场本地部署、流程编排和结果可回传为主。后续继续扩展节点时，优先补工业语义节点，不优先继续加深更重的视频模型能力。

相机、PLC、工业缺陷扩展节点和 OpenCV 常用算子这类更广义的工业扩展规划，现已单独整理到 [industrial-extension-node-plan.md](industrial-extension-node-plan.md)，避免把规则节点主线和现场扩展体系混在同一份文档里。

当前状态：

- 第 1 批 `core.vision.regions-*` 已接通
- 第 2 批 `ROI / coverage / overlap` 当前已接通 `roi-create / regions-intersection-metrics / regions-coverage-check / regions-inside-check / regions-offset-check`
- 第 3 批可解释完整性指标首轮已全部接通：`region-component-count / region-largest-component-ratio / region-hole-count / region-gap-check / region-span-metrics / region-continuity-score`
- 第 4 批工业判定节点当前已接通 `threshold-check / range-check / presence-check / ok-ng-decision / alarm-condition / process-decision`
- 第 4 批结果回传节点当前已接通 `result-record / alarm-record / json-save-local / csv-append-local / http-post`
- 第 4 批输入接入节点当前已接通 `image-load-local / image-list-local / directory-scan / directory-batch-window`
- `core.vision.detections-to-regions` 当前已接通，可把 deployment detection 或其他 `detections.v1` 结果桥接进现有工业规则链
- `core.vision.segments-to-regions` 当前也已接通，可把外部或中间节点输出的 `segments.v1(mask / polygon / bbox)` 结果桥接进现有工业规则链
- `core.logic.value-to-segments / value-to-regions` 当前也已接通，可把目录批处理或列表循环中的逐项 `value.v1` 恢复回标准 `segments.v1 / regions.v1`
- `core.io.directory-scan` 当前也已支持 `min_stable_age_seconds` 与 `dedupe_by`，`core.io.directory-batch-window` 当前已支持运行时 `start_index / batch_size / cursor` 输入，更适合现场批次推进
- `core.io.json-load-local` 与 `core.io.directory-poll-window` 当前也已接通，可把“本地 cursor JSON 恢复 + 当前无新文件时 has_work=false + 批次 cursor 再落盘”这层目录轮询守护语义独立出来
- 工业单帧规则样例当前已补到 `docs/examples/workflows/industrial_single_frame_sealant_quality_gate.*`、`industrial_single_frame_segments_continuity_gate.*`、`industrial_single_frame_glue_roi_callback.*`、`industrial_single_frame_glue_polygon_roi_changeover.*` 与 `industrial_single_frame_yolox_position_gate.*`
- 工业本地批量输入样例当前已补到 `docs/examples/workflows/industrial_local_directory_batch_input.*`、`industrial_local_directory_batch_segments_continuity_gate.*`、`industrial_local_directory_batch_regions_continuity_gate.*`、`industrial_local_directory_batch_yolox_position_gate.*` 与 `industrial_local_directory_polling_cursor_guard.*`
- 当前仍待收口的主要缺口已经不再是大块能力面，而是少数残留节点、样例闭环和现场易用性优化

## 适用边界

- 优先面向单帧工业判定
- 视频结果优先先转成 `regions.v1` 再复用同一批规则节点
- 节点应保持可解释、可组合、可追溯
- 不在这一阶段引入大型规则 DSL 或抽象工艺引擎

## 分层原则

- `core.vision.*`：模型无关的视觉结果处理节点
- `core.rule.*`：工业语义更直白的规则判定节点
- `core.output.*`：结果保存、返回、报警对象输出
- `core.io.*`：本地单图与目录输入
- `custom.*`：硬件、协议、环境依赖强的接入能力，例如相机、RTSP、MES/PLC 专有协议

## payload 约定

### 优先复用的 payload

- `regions.v1`
- `segments.v1`
- `image-ref.v1`
- `image-refs.v1`
- `value.v1`
- `boolean.v1`
- `response-body.v1`
- `http-response.v1`

### 计划新增的通用 payload

- `roi.v1`
  - 用于矩形或多边形 ROI
  - 由 `core.vision.roi-create` 产生
- `result-record.v1`
  - 用于统一 `OK / NG / reason / metrics / refs / alarm`
- `alarm-record.v1`
  - 用于统一报警级别、报警码、报警文案和来源条件

说明：
- `directory-scan` 第一阶段先输出 `value.v1` 文件记录列表，不急着单独引入 `file-list.v1`
- `segments.v1` 当前主要作为桥接输入，用于 `core.vision.segments-to-regions` 把 mask / polygon / bbox 分割结果统一收进 `regions.v1`

## 第 1 批：core.vision.regions-* 基础结果统计节点

这批节点服务“有没有、有几个、面积多大、占比多少、位置是否偏移、分数是否过低”这类最常见的工业判定前置计算。

### 节点清单

#### core.vision.regions-filter

- 放置位置：`core`
- 输入：`regions.v1`
- 输出：`regions.v1`、`value.v1(summary)`
- 作用：按 `class_name / score / prompt_id / track_id / state / area` 过滤区域
- 现场场景：缺陷筛选、只保留指定目标、先清洗低分结果

#### core.vision.regions-select-best

- 放置位置：`core`
- 输入：`regions.v1`
- 输出：`regions.v1`、`value.v1(summary)`
- 作用：按最大面积、最高分或第一项选择最优区域
- 现场场景：一图只取一个主目标、只保留最大缺陷、只取最高可信结果

#### core.vision.regions-count

- 放置位置：`core`
- 输入：`regions.v1`
- 输出：`value.v1`
- 作用：统计区域数量
- 现场场景：目标存在性、数量是否达标、计数判定

#### core.vision.regions-area-sum

- 放置位置：`core`
- 输入：`regions.v1`
- 输出：`value.v1`
- 作用：统计总面积
- 现场场景：缺陷总面积、覆盖总面积、工艺区域面积累计

#### core.vision.regions-area-ratio

- 放置位置：`core`
- 输入：`regions.v1`、`image-ref.v1(可选)`
- 输出：`value.v1`
- 作用：把总面积换算为来源图像面积占比
- 现场场景：点胶覆盖率、涂层面积占比、污染面积占比

#### core.vision.regions-bbox-metrics

- 放置位置：`core`
- 输入：`regions.v1`
- 输出：`value.v1`
- 作用：提取宽、高、长宽比、中心点等 bbox 派生指标
- 现场场景：位置偏移、尺寸偏差、主目标尺寸规则

#### core.vision.regions-score-summary

- 放置位置：`core`
- 输入：`regions.v1`
- 输出：`value.v1`
- 作用：输出 `min / max / avg / median score`
- 现场场景：结果质量检查、最低置信度门槛、模型稳定性观察

### 第 1 批实现顺序

1. `regions-filter`
2. `regions-count`
3. `regions-area-sum`
4. `regions-area-ratio`
5. `regions-select-best`
6. `regions-bbox-metrics`
7. `regions-score-summary`

## 第 2 批：ROI / coverage / overlap 规则前置节点

这批节点服务点胶、涂层、工位落位、越界和覆盖率判断。

### 节点清单

#### core.vision.roi-create

- 放置位置：`core`
- 输入：参数或 `value.v1`
- 输出：`roi.v1`、`value.v1(summary)`
- 作用：创建矩形或多边形 ROI
- 现场场景：工位区、关注区、禁入区、基准区

#### core.vision.regions-intersection-metrics

- 放置位置：`core`
- 输入：`regions.v1`、`roi.v1`
- 输出：`value.v1`
- 作用：计算交集面积、覆盖率、IoU、区域内占比
- 现场场景：点胶覆盖率、缺陷与工位区交集、越界度量

#### core.vision.regions-coverage-check

- 放置位置：`core`
- 输入：`regions.v1`、`roi.v1`
- 输出：`boolean.v1`、`value.v1(metrics)`
- 作用：判断覆盖率是否达标
- 现场场景：胶线覆盖是否到位、涂层是否满足工艺覆盖要求

#### core.vision.regions-inside-check

- 放置位置：`core`
- 输入：`regions.v1`、`roi.v1`
- 输出：`boolean.v1`、`value.v1(metrics)`
- 作用：判断区域是否在指定范围内
- 现场场景：工件是否落位、缺陷是否出现在关注区、印刷是否越界

#### core.vision.regions-offset-check

- 放置位置：`core`
- 输入：`regions.v1`、`roi.v1`
- 输出：`boolean.v1`、`value.v1(metrics)`
- 作用：判断中心偏移、边界偏移是否超限
- 现场场景：贴合偏差、焊点偏心、工件姿态偏移

### 第 2 批实现顺序

1. `roi-create`
2. `regions-intersection-metrics`
3. `regions-coverage-check`
4. `regions-inside-check`
5. `regions-offset-check`

## 第 3 批：连续性 / 完整性 / 断裂原子指标

这批节点用于可解释的完整性和连续性分析，不做一体化黑盒 continuity 引擎。

### 节点清单

#### core.vision.region-component-count

- 放置位置：`core`
- 输入：`regions.v1`
- 输出：`value.v1`
- 作用：统计连通域数量
- 现场场景：焊缝断裂、胶线碎片化、目标完整性检查

#### core.vision.region-largest-component-ratio

- 放置位置：`core`
- 输入：`regions.v1`
- 输出：`value.v1`
- 作用：统计最大连通域占整体比例
- 现场场景：主体是否完整、碎裂比例是否超限

#### core.vision.region-hole-count

- 放置位置：`core`
- 输入：`regions.v1`
- 输出：`value.v1`
- 作用：统计空洞数量
- 现场场景：涂层空洞、填充缺口、密封不连续

#### core.vision.region-span-metrics

- 放置位置：`core`
- 输入：`regions.v1`
- 输出：`value.v1`
- 作用：输出主方向长度、厚度、跨度和细长度
- 现场场景：焊缝长度、胶线厚度、涂布跨度

#### core.vision.region-gap-check

- 放置位置：`core`
- 输入：`regions.v1`
- 输出：`boolean.v1`、`value.v1(metrics)`
- 作用：判断是否存在明显断裂或缺口
- 现场场景：焊缝断开、胶线断胶、长条区域中断

#### core.vision.region-continuity-score

- 放置位置：`core`
- 输入：`regions.v1`
- 输出：`value.v1`
- 作用：基于原子指标生成连续性分数
- 现场场景：需要对连续性做分级评分的现场

### 第 3 批实现顺序

1. `region-component-count`
2. `region-largest-component-ratio`
3. `region-hole-count`
4. `region-gap-check`
5. `region-span-metrics`
6. `region-continuity-score`

当前状态：

- 已实现 `region-component-count`
- 已实现 `region-largest-component-ratio`
- 已实现 `region-hole-count`
- 已实现 `region-gap-check`
- 已实现 `region-span-metrics`
- 已实现 `region-continuity-score`

## 第 4 批：工业判定 / 结果回传 / 输入接入节点

这批节点服务最终 `OK / NG`、报警、结果落盘和本地图像批处理输入。

### 工业判定节点

#### core.rule.threshold-check

- 放置位置：`core`
- 输入：`value.v1`
- 输出：`boolean.v1`、`value.v1`
- 作用：对单个数值做阈值判断

#### core.rule.range-check

- 放置位置：`core`
- 输入：`value.v1`
- 输出：`boolean.v1`、`value.v1`
- 作用：判断是否在范围内

#### core.rule.presence-check

- 放置位置：`core`
- 输入：`regions.v1` 或 `value.v1`
- 输出：`boolean.v1`、`value.v1`
- 作用：判断目标是否存在、数量是否达标

#### core.rule.ok-ng-decision

- 放置位置：`core`
- 输入：多个 `boolean.v1`
- 输出：`result-record.v1` 或 `value.v1`
- 作用：收成最终 `OK / NG`

#### core.rule.alarm-condition

- 放置位置：`core`
- 输入：条件和上下文值
- 输出：`alarm-record.v1`
- 作用：生成报警级别、报警码、报警文案

#### core.rule.process-decision

- 放置位置：`core`
- 输入：`regions / metrics / booleans`
- 输出：`result-record.v1`
- 作用：生成最终工艺判定对象

### 结果回传节点

#### core.output.result-record

- 放置位置：`core`
- 输入：`value / boolean / refs`
- 输出：`result-record.v1`
- 作用：统一 `OK / NG / reason / metrics / refs`

#### core.output.alarm-record

- 放置位置：`core`
- 输入：条件与上下文
- 输出：`alarm-record.v1`
- 作用：统一报警输出

#### core.output.json-save-local

- 放置位置：`core`
- 输入：`result-record.v1` 或 `value.v1`
- 输出：`value.v1(summary)`
- 作用：本地保存 JSON 结果

#### core.output.csv-append-local

- 放置位置：`core`
- 输入：`result-record.v1` 或 `value.v1`
- 输出：`value.v1(summary)`
- 作用：本地累计 CSV / 日志

#### core.output.http-post

- 放置位置：`core`
- 输入：`result-record.v1 / alarm-record.v1 / value.v1`
- 输出：`value.v1(summary)`
- 作用：通用 HTTP 结果回传

### 输入接入节点

#### core.io.image-load-local

- 放置位置：`core`
- 输入：路径参数或 `value.v1(path)`
- 输出：`image-ref.v1`、`value.v1(summary)`
- 作用：本地单图载入

#### core.io.image-list-local

- 放置位置：`core`
- 输入：目录或路径列表
- 输出：`image-refs.v1`、`value.v1(summary)`
- 作用：小批量本地图像载入

#### core.io.directory-scan

- 放置位置：`core`
- 输入：目录路径
- 输出：`value.v1(file_records)`
- 作用：扫描目录中的待处理文件

#### core.io.directory-batch-window

- 放置位置：`core`
- 输入：`value.v1(file_records)`
- 输出：`image-refs.v1` 或 `value.v1(batch_records)`
- 作用：按批组织待处理文件窗口

### 第 4 批实现顺序

1. `threshold-check`
2. `range-check`
3. `presence-check`
4. `ok-ng-decision`
5. `result-record`
6. `image-load-local`
7. `directory-scan`
8. `json-save-local`
9. `http-post`

### 第 4 批当前已接通子集

- 工业判定最小闭环：
  - `threshold-check`
  - `presence-check`
  - `ok-ng-decision`
  - `result-record`
- 工业语义封装进一步补齐：
  - `alarm-condition`
  - `process-decision`
- 本地输入与现场回传闭环：
  - `image-load-local`
  - `directory-scan`
  - `json-save-local`
  - `http-post`
- 范围判断、报警对象与小批量输入：
  - `range-check`
  - `alarm-record`
  - `csv-append-local`
  - `image-list-local`
  - `directory-batch-window`

## 当前优先级判断

按工业单帧判定真实价值排序，当前最值得继续收口的是：

1. 工业单帧 workflow 样例继续往“更接近现场使用”收一层，例如补更多换型、多 ROI 或小批量现场模板
2. `roi-create`、批量输入和结果回传的参数面继续做易用性优化，优先补多边形 ROI 样例、批次推进和结果字段规范化
3. 继续补少量重点测试和文档，不把耗时长链放入默认测试
4. 更重的视频语义稳定增强继续保持后置，不作为当前工业单帧主线优先项

## 当前明确不优先的方向

- 不先做大型规则 DSL
- 不先做抽象工艺引擎
- 不优先继续深挖 `video-semantic` 时序增强
- 不把相机、RTSP、采集卡、PLC、MES 专有接入直接塞进 `core`

## 当前剩余缺口

- 当前工业单帧样例虽然已经有 checked-in 的“segments.v1 -> segments-to-regions -> 工业规则链”和“YOLOX detection -> detections-to-regions -> 工业规则链”模板，但还没有覆盖更多模型来源和更多规则组合
- `roi-create` 虽然已支持运行时 `value.v1` 动态 ROI，但当前仓库里还没有覆盖更多多边形 ROI 和现场换型配置的样例
- 当前批量输入链已经不只停在输入准备：`directory-scan -> directory-batch-window -> for-each -> image-load-local -> yolox-detection -> 工业规则链 -> csv/json 归档`，以及 `directory-scan -> directory-batch-window -> for-each -> value-to-segments / value-to-regions -> 工业规则链 -> csv/json 归档` 这两类 checked-in 主线都已补通；目录轮询守护这一层当前也已有 `json-load-local -> directory-poll-window -> json-save-local` 的 checked-in 样例，当前更值得继续收口的是目录游标长期策略、归档字段规范，以及更贴现场的接入说明
- 当前 detection / segmentation 结果虽然已可通过 `core.vision.detections-to-regions` 与 `core.vision.segments-to-regions` 进入规则链，但还没有继续往前补更细的调试与适配辅助节点

## 未实现正式待办

这一节只列当前还未实现、但已经比较明确值得继续补的节点或适配层，并按 `core / custom / trigger-source / output-integration` 四层分开。

说明：

- `core` 只放模型无关、协议无关、无硬件依赖的通用节点
- `custom` 放设备、厂商 SDK、现场环境差异较大的 workflow 节点
- `trigger-source` 不是普通 workflow 节点，而是 runtime 外部触发适配层
- `output-integration` 重点是结果回传和外部系统交付，不等同于当前已经实现的通用 `json-save-local / csv-append-local / http-post`

### 一、core 层待办

#### P1：目录推进与批次归档收口

- `core.io.directory-cursor-normalize`
  - 作用：把本地 JSON、运行时输入或默认值统一规整为稳定 cursor 对象，补齐 `last_path / next_start_index / completed / no_work_reason` 这类字段
  - 原因：当前 cursor 主要靠 `value.v1 + 约定字段` 表达，已经能用，但还没有专门的规整节点
  - 配套建议：后续可视情况增加 `directory-cursor.v1`
- `core.io.directory-cursor-advance`
  - 作用：根据当前 `directory-batch-window` 或 `directory-poll-window` 的输出，统一生成下一步 cursor
  - 原因：当前 cursor 推进主要散在窗口节点 summary/cursor 中，后续如果要支持 reset、重扫、回退和跳过策略，最好独立出来
- `core.output.batch-record`
  - 作用：把 `scan_summary / window_summary / batch_cursor / batch_files / inspection_results` 统一收成标准批次归档对象
  - 原因：当前批次归档主要靠 `object-create + json-save-local` 组合完成，能用，但还没有正式规范化节点
  - 配套建议：后续可视情况增加 `batch-record.v1`
- `core.io.batch-files-relocate`
  - 作用：把当前批次文件按规则移动或复制到 `processed / archive / failed / quarantine` 目录
  - 原因：当前目录批处理主线已经能“读、判定、归档 JSON/CSV”，但还不能把已处理文件正式归档到现场约定目录
  - 说明：这类节点需要额外谨慎处理覆盖、重名、幂等和失败回滚

#### P2：模型结果到规则链的辅助收口

- `core.vision.batch-items-align-check`
  - 作用：检查 `batch_files` 与 `request_segments_items / request_regions_items` 是否一一对齐，并输出可读摘要
  - 原因：当前目录批处理分割样例默认按索引对齐，没有自动回配或显式校验节点
- `core.vision.regions-debug-summary`
  - 作用：输出 `class_name / prompt_id / area / score / source kind` 这类更适合现场排障的摘要对象
  - 原因：当前已有 `regions-score-summary` 等指标，但还缺一个更偏“上游结果调试”的统一摘要节点

### 二、custom 层待办

#### P2：现场输入与设备桥接

- `custom.camera.capture-frame`
  - 作用：从本地相机或采集卡抓取单帧，输出 `image-ref.v1`
  - 原因：当前工业主线仍以本地图像和本地目录输入为主，还没有正式相机接入节点
- `custom.video.rtsp-read-frame`
  - 作用：从 RTSP 或等价流地址读取一帧或一小段窗口，输出 `image-ref.v1` 或 `frame-window.v1`
  - 原因：当前视频链更偏本地文件输入，还没有把现场流输入纳入 workflow 节点面
- `custom.protocol.plc-read-write`
  - 作用：读写 PLC 或设备网关中的少量状态、寄存器和值对象
  - 原因：工业场景最终常常要和工位信号联动，但这类能力不应进入 core
- `custom.protocol.mes-request-context`
  - 作用：读取工单、批号、工位号、产品型号等上下文对象，供规则链和结果回传使用
  - 原因：当前流程里虽可用 `value.v1` 手工传上下文，但还没有更贴现场的接入节点

### 三、trigger-source 层待办

这一层不是普通节点，而是 runtime 外部触发适配器；当前 `zeromq-topic` 已经存在，因此这里只列尚未补齐的触发类型。

#### P1：目录触发

- `directory-poll`
  - 作用：按固定周期触发某个 WorkflowAppRuntime，并把目录路径、批次大小和必要上下文注入输入 binding
  - 原因：当前已有 `directory-poll-window` 样例，但仍需要由外部手工调用；还没有正式常驻目录轮询触发器
- `filesystem-watch`
  - 作用：基于文件创建、改名或稳定落地事件触发 WorkflowRun
  - 原因：有些现场更适合“文件一落地就触发”，而不是固定时间轮询

#### P2：协议触发扩展

- `http-webhook`
  - 作用：接收外部系统推送的路径、工单或图像引用，再映射到 workflow 输入
  - 原因：当前公开的 invoke 能力更偏主动调用，还没有专门的 webhook 触发资源
- `mqtt-topic`
  - 作用：订阅现场消息总线中的事件，再映射到 WorkflowRun
  - 原因：部分现场会通过边缘网关或消息中间件转发状态变化，不适合塞进普通 workflow 节点

### 四、output-integration 层待办

#### P1：统一结果对象与交付边界

- `core.output.workflow-result`
  - 作用：把 `status / code / message / data / metrics / files / trace_id` 收成统一交付对象
  - 原因：当前 `http-post` 能回传 JSON，但现场触发、协议桥接和统一结果调度仍缺少一个更正式的中间结果对象
  - 说明：这项虽然命名落在 `core.output.*`，但职责属于 output-integration 收口层
- `core.output.batch-result-summary`
  - 作用：把一批 `result-record.v1` 收成 `ok_count / ng_count / alarm_count / pass_ratio / batch_reason_summary`
  - 原因：当前已有单条 `result-record`，但目录批处理完成后还缺标准批次结果摘要节点

#### P2：现场协议回传

- `custom.output.mes-http-post`
  - 作用：把统一结果对象按 MES 或上位机接口约定重组后回传
  - 原因：当前只有通用 `http-post`，还没有面向现场业务字段的包装节点
- `custom.output.plc-signal-write`
  - 作用：把 `OK / NG / alarm / ack-needed` 之类结果写回 PLC、IO 网关或设备代理
  - 原因：工业现场常见的最终动作不是保存 JSON，而是写状态位或报码
- `custom.output.local-db-upsert`
  - 作用：把结果写入本地 SQLite/MySQL/PostgreSQL 表，用于工作站追溯和统计
  - 原因：当前已有 JSON/CSV，本地数据库归档还没有正式节点

## 当前建议的实现顺序

按工业现场主线，当前最自然的正式顺序是：

1. `core.io.directory-cursor-normalize`
2. `core.io.directory-cursor-advance`
3. `core.output.batch-record`
4. `core.io.batch-files-relocate`
5. `core.output.workflow-result`
6. `core.output.batch-result-summary`
7. `directory-poll` trigger-source
8. `filesystem-watch` trigger-source
9. 再按现场项目需要，选择 `custom.camera.* / custom.video.* / custom.protocol.* / custom.output.*`

## 下一步执行顺序

1. 先继续收目录推进语义和现场易用性，例如目录游标长期策略、文件稳定落地约定、批次归档字段规范与目录轮询触发接入说明
2. 再看是否需要补更多 detection / segmentation 调试与适配辅助节点，把模型结果到规则链的使用面继续打磨顺
3. 然后再评估规则结果对象、JSON/CSV 字段规范和目录批次归档结构是否需要进一步收口
4. 最后再看是否需要继续扩更多工业规则原子节点，而不是直接跳去更重的视频能力
