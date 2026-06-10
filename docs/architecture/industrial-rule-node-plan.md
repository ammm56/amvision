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
- `core.io.directory-cursor-normalize / directory-cursor-advance / core.output.batch-record / core.io.batch-files-relocate` 当前也已接通，目录游标规整、窗口推进、批次归档对象和批次文件归档这 4 层已不再需要继续靠 `object-create + 手工字段约定` 拼装；其中 `batch-files-relocate` 当前首版默认 `copy + rename`，并已支持 `move / overwrite / skip / preserve_subdirectories / dry_run`
- `core.output.workflow-result / core.output.batch-result-summary` 当前也已接通，统一 workflow 交付对象和批次结果摘要都已从零散 `value.v1` 字段拼装里收出来，后续 trigger-source / 结果回传可以直接复用这两个中间结果对象
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
- 当前批量输入链已经不只停在输入准备：`directory-scan -> directory-batch-window -> for-each -> image-load-local -> yolox-detection -> 工业规则链 -> csv/json 归档`，以及 `directory-scan -> directory-batch-window -> for-each -> value-to-segments / value-to-regions -> 工业规则链 -> csv/json 归档` 这两类 checked-in 主线都已补通；目录轮询守护这一层当前也已有 `json-load-local -> directory-poll-window -> json-save-local` 的 checked-in 样例。目录游标规整、推进与批次归档首轮也已接通，目录 TriggerSource 这一层当前也已补到 `directory-poll + directory-watch` 两条正式入口；当前更值得继续收口的是批次结果摘要、目录触发现场样例、文件归档规范，以及更贴现场的接入说明
- 当前 detection / segmentation 结果虽然已可通过 `core.vision.detections-to-regions` 与 `core.vision.segments-to-regions` 进入规则链，但还没有继续往前补更细的调试与适配辅助节点

## 未实现正式待办

这一节只列当前还未实现、但已经比较明确值得继续补的节点或适配层，并按 `core / custom / trigger-source / output-integration` 四层分开。

说明：

- `core` 只放模型无关、协议无关、无硬件依赖的通用节点
- `custom` 放设备、厂商 SDK、现场环境差异较大的 workflow 节点
- `trigger-source` 不是普通 workflow 节点，而是 runtime 外部触发适配层
- `output-integration` 重点是结果回传和外部系统交付，不等同于当前已经实现的通用 `json-save-local / csv-append-local / http-post`

### 一、core 层待办

#### P1：目录批处理剩余收口

- 当前这一组已全部实现，`core` 层没有新的 P1 目录批处理缺口；后续自然转到 trigger-source 常驻触发和更贴现场的结果交付

#### P2：模型结果到规则链的辅助收口

- `core.vision.batch-items-align-check`
  - 作用：检查 `batch_files` 与 `request_segments_items / request_regions_items` 是否一一对齐，并输出可读摘要
  - 原因：当前目录批处理分割样例默认按索引对齐，没有自动回配或显式校验节点
- `core.vision.regions-debug-summary`
  - 作用：输出 `class_name / prompt_id / area / score / source kind` 这类更适合现场排障的摘要对象
  - 原因：当前已有 `regions-score-summary` 等指标，但还缺一个更偏“上游结果调试”的统一摘要节点

### 二、custom 层待办

#### P2：现场输入与设备桥接

- `custom.video.rtsp-read-frame`
  - 作用：从 RTSP 或等价流地址读取一帧或一小段窗口，输出 `image-ref.v1` 或 `frame-window.v1`
  - 原因：当前视频链更偏本地文件输入，还没有把现场流输入纳入 workflow 节点面
- `custom.protocol.mes-request-context`
  - 作用：读取工单、批号、工位号、产品型号等上下文对象，供规则链和结果回传使用
  - 原因：当前流程里虽可用 `value.v1` 手工传上下文，但还没有更贴现场的接入节点

说明：

- USB/UVC 相机抓帧这条主线已经由 `custom.camera.usb.capture-frame` 等节点落地，不再把“泛化 capture-frame”继续挂成未实现待办
- PLC 主动读写这条主线已经由 `custom.plc.modbus.read-value / write-value / wait-condition` 落地；后续继续扩时，按协议 pack 细分，不再回到“generic plc-read-write”表述

### 三、trigger-source 层待办

这一层不是普通节点，而是 runtime 外部触发适配器；当前 `zeromq-topic`、`directory-poll`、`directory-watch` 与 `plc-register(modbus-tcp + polling)` 都已经存在，因此这里只列尚未补齐或只完成第一阶段的触发类型。

当前边界说明：

- 当前已经具备 WorkflowAppRuntime 的主动 HTTP 调用入口，可通过 `invoke / invoke/upload` 直接提交 workflow 输入
- 因此“HTTP 触发”当前不是主缺口；真正还没做的是“被动 webhook 资源”这类固定回调入口、签名校验、幂等键和冷却控制语义

#### P1：目录触发

- 当前这一项已实现：`directory-poll`
  - 作用：按固定周期扫描目录中新到达且已稳定落地的文件，并把 batch 文件列表、扫描摘要和批次上下文提交到 WorkflowAppRuntime
  - 当前状态：已支持本地 checkpoint 恢复、扩展名筛选、稳定期过滤和 async submit
- 当前这一项也已实现：`directory-watch`
  - 作用：基于目录创建、修改或稳定落地事件触发 WorkflowRun
  - 当前状态：已支持本地 checkpoint 去重恢复、稳定期过滤、batch 提交、`force_polling=true` 受控事件探测和 async submit

#### P2：协议触发扩展

- `http-webhook-trigger`
  - 作用：接收外部系统被动推送的路径、工单或图像引用，再映射到 workflow 输入
  - 原因：当前主动 `invoke` 已可满足大量集成场景；只有确实需要“固定 URL 被动接收 + 签名/幂等/限流”时，才需要单独的 webhook TriggerSource 资源
- `mqtt-topic`
  - 作用：订阅现场消息总线中的事件，再映射到 WorkflowRun
  - 原因：部分现场会通过边缘网关或消息中间件转发状态变化，不适合塞进普通 workflow 节点

### 四、output-integration 层待办

#### P1：统一结果对象与交付边界

- 当前这一项已实现：`core.output.workflow-result`
  - 作用：把 `status / code / message / data / metrics / files / trace_id / event_id` 收成统一 `workflow-result.v1`
  - 当前状态：已可与 `result-record / batch-record / http-post / trigger-source` 结果调度链对接

#### P2：现场协议回传

- `custom.output.mes-http-post`
  - 放置位置：`custom`
  - 作用：在现有 `core.output.http-post` 之上补一层面向 MES / 上位机常见接口的受限包装，把 `result-record / workflow-result / core.output.batch-result-summary` 输出的 `summary(value)` 重组为更贴现场的请求体
  - 原因：现场 MES 接口千差万别，这一层不适合塞进 `core.output.*`；第一阶段只做受限通用层，不做“万能 MES 适配器”，厂商或项目专有接口继续通过后续 custom pack 扩展
  - 建议形态：单独 custom pack，建议后续放在 `custom_nodes/output_mes_http_nodes/` 或等价目录，不与通用 `core.output.http-post` 混写
  - 当前状态：第一阶段 pack / specs / catalog / runtime 已落地，当前已支持 `result-record.v1 / workflow-result.v1 / summary(value.v1) + request(value.v1)` 的受限 JSON 回传，以及 `prepared_request` 调试输出

第一阶段输入输出契约：

- 输入端口：
  - `result`：`result-record.v1`，可选
  - `workflow_result`：`workflow-result.v1`，可选
  - `summary`：`value.v1`，可选
    - 说明：这里的 `summary` 主要对接 `core.output.batch-result-summary` 的输出；当前不是单独的 `batch-result-summary.v1` payload
  - `request`：`value.v1`，可选
    - 说明：用于补充工单号、批次号、设备号、工位号、人工确认结果、外部请求上下文和运行时覆盖字段
- 输入约束：
  - `result / workflow_result / summary` 三者中，第一阶段要求“最多一个主业务输入”
  - `request` 只能作为补充上下文或运行时覆盖，不作为默认主业务输入
  - 当主业务输入缺失，或三者同时提供多个时，节点直接报错，不做隐式优先级猜测
- 输出端口：
  - `response`：`value.v1`
    - 作用：沿用 `core.output.http-post` 风格，输出 `ok / status_code / headers / body_json 或 body_text / url / method`
  - `prepared_request`：`value.v1`
    - 作用：输出实际组装后的 `method / url / query / headers / body` 调试摘要，用于现场排障和 workflow 预览
    - 约束：敏感字段如 `Authorization`、token、password 必须脱敏，不直接回显明文

第一阶段主业务输入的推荐语义：

- `result-record.v1`
  - 适合单帧判定、OK/NG、报警和工艺规则结果回传
  - 典型取值路径：`ok_ng`、`reason`、`metrics.*`、`conditions.*`、`alarm.active`、`alarm.code`、`metadata.*`
- `workflow-result.v1`
  - 适合把整条 workflow 的统一交付结果回传给 MES、上位机或中间网关
  - 典型取值路径：`status`、`code`、`message`、`data`、`metrics`、`files`、`trace_id`、`event_id`、`metadata`
- `summary(value.v1)`
  - 适合目录批次、小批量归档和班次级摘要回传
  - 典型来源：`core.output.batch-result-summary`
  - 典型取值路径：`ok_count`、`ng_count`、`alarm_count`、`pass_ratio`、`summary_source`、`record_result_count`
- `request(value.v1)`
  - 适合补充站点现场上下文
  - 典型取值路径：`work_order_id`、`lot_id`、`station_id`、`device_id`、`operator_id`、`part_no`、`line_id`

第一阶段受限参数面：

- `url`
  - 必填，目标接口地址
- `method`
  - 仅支持 `POST / PUT`
  - 第一阶段先不开放 `PATCH / DELETE / GET`
- `timeout_seconds`
  - 请求超时秒数
- `require_success`
  - 是否把非 `2xx` 状态码视为失败
- `headers`
  - 静态请求头对象
  - 第一阶段只做静态 header，不做任意脚本拼装
- `auth_kind`
  - 仅支持 `none / bearer_token / header_static`
  - `bearer_token` 统一写入 `Authorization: Bearer ...`
  - `header_static` 用于少数现场约定的固定 header 鉴权
- `auth_token`
  - 与 `auth_kind` 配套使用
- `auth_header_name`
  - 仅在 `header_static` 下生效
- `query_template`
  - 可选静态 query 对象
- `query_mappings`
  - 把 `result / workflow_result / summary / request / literal` 中的字段映射到 query 参数
- `body_mode`
  - 仅支持 `json_object / json_envelope`
  - `json_object`：直接生成 JSON 对象作为请求体
  - `json_envelope`：把业务字段写入统一 envelope，对接常见 `code / message / data` 或 `site / line / payload` 风格
- `body_template`
  - 静态 JSON 对象骨架
  - 只允许对象结构，不允许字符串模板、Jinja 或脚本执行
- `field_mappings`
  - 把 `result / workflow_result / summary / request / literal` 中的字段映射到 `body_template` 的目标路径
  - 每条映射至少包含：
    - `target_path`
    - `source_kind`
  - 当 `source_kind != literal` 时，要求提供 `source_path`
  - 当 `source_kind = literal` 时，使用 `literal_value`
- `on_missing`
  - 节点级默认缺失策略，第一阶段仅支持 `error / skip / null`
  - 每条 `field_mapping / query_mapping` 可选单独覆盖；未提供时回落到节点级默认值
- `static_fields`
  - 写死到请求体中的固定字段，适合固定站点码、工艺号、设备别名等

第一阶段字段映射规则：

- `source_kind` 仅支持 `result / workflow_result / summary / request / literal`
- `target_path` 使用点路径表达对象写入位置，例如 `payload.metrics.coverage_ratio`
- `source_path` 使用点路径表达源对象读取位置，例如 `metrics.coverage_ratio`
- 第一阶段只支持对象字段路径，不支持数组切片、表达式、条件语句和自定义函数
- `query_mappings` 与 `field_mappings` 共享同一套 `source_kind / source_path / literal_value / on_missing` 规则
- 当 `body_mode = json_envelope` 时，建议通过 `body_template` 明确 envelope 结构，例如：
  - `{"site": "", "line": "", "payload": {}}`
  - 再通过 `field_mappings` 把业务结果写入 `payload.*`

第一阶段失败与排障边界：

- 主业务输入缺失或冲突时直接失败
- `url / method / auth_kind / body_mode / field_mappings` 参数非法时直接失败
- 字段映射失败时默认按 `on_missing = error` 处理
- HTTP 返回非 `2xx` 时，默认按 `require_success = true` 失败
- 第一阶段不内置自动重试、回退地址、幂等队列或本地补偿；这些属于上层 orchestration 或后续扩展能力
- `prepared_request` 应作为第一层现场排障入口，优先帮助确认：
  - 业务字段是否映射到了对的位置
  - 站点上下文字段是否带齐
  - 是否用了错误的 URL、header 或 envelope 结构

第一阶段明确不做：

- 不做厂商专有 MES SDK
- 不做任意 Python / Jinja / JavaScript 模板执行
- 不做 XML / SOAP / multipart / form-data
- 不做多步登录、会话保持、cookie 编排和复杂签名流程
- 不做任意 SQL、任意数据库写入或文件上传
- 不做自动字段猜测、自动 schema 发现或“给个接口就自己适配”
- 不做项目专有强绑定字段名；专有格式留给后续 custom pack

第一阶段最贴现场的典型场景：

- 单帧判定完成后，把 `result-record.v1` 按现场接口格式回传给上位机或 MES
- 目录批次完成后，把 `core.output.batch-result-summary` 的 `summary(value.v1)` 回传给批次统计接口
- 把 `workflow-result.v1` 连同 `request` 中的工单号、站点号、设备号一起封装后回传给中间网关

- `custom.plc.modbus.write-result-signals`
  - 作用：把 `OK / NG / alarm / ack-needed / result-code` 等结果写回 Modbus TCP 的 coils 或 holding registers
  - 原因：工业现场常见的最终动作不是保存 JSON，而是写状态位或报码；这一层必须先与当前 Modbus TCP pack 对齐，而不是抽象成“通用 PLC 信号写入”
- `custom.output.local-db-upsert`
  - 放置位置：`custom`
  - 作用：把结果写入本地 SQLite/MySQL/PostgreSQL 中已知结构的结果表，用于工作站追溯、统计和后续补传
  - 原因：当前已有 JSON/CSV，本地数据库归档还没有正式节点；第一阶段不做任意 SQL 或任意表结构自动推断，而是要求显式表名、唯一键和字段映射
  - 当前状态：第一阶段 pack / specs / catalog / runtime 已落地，当前已支持 `result-record.v1 / workflow-result.v1 / summary(value.v1) + request(value.v1)` 的受限单表单行 upsert，以及 `prepared_row` 调试输出
  - 推荐实现原则：
    - 不暴露 `raw_sql / where_sql / set_sql / on_conflict_sql` 这类可执行 SQL 输入
    - 不把数据库方言细节直接泄漏到 workflow 节点使用面
    - 不直接复用平台主业务库中的聚合 Repository 去写现场自定义结果表
    - 第一阶段建议使用 `SQLAlchemy 2` 受限实现：
      - 连接与事务：`Engine / Session / transaction`
      - 表结构访问：`MetaData + Table` 与受控 reflection
      - upsert 语义：按 `SQLite / MySQL / PostgreSQL` 分别走 SQLAlchemy 方言能力，而不是手写原生 SQL 字符串
    - 如果后续要写平台自有固定结果表，那是另一层正式 application/repository 能力，不等同于这个 custom integration 节点

第一阶段输入输出契约：

- 输入端口：
  - `result`：`result-record.v1`，可选
  - `workflow_result`：`workflow-result.v1`，可选
  - `summary`：`value.v1`，可选
    - 说明：这里的 `summary` 主要对接 `core.output.batch-result-summary` 的输出
  - `request`：`value.v1`，可选
    - 说明：用于补充工单号、批次号、设备号、站点号、班次号和运行时上下文
- 输入约束：
  - `result / workflow_result / summary` 三者中，第一阶段要求“最多一个主业务输入”
  - `request` 只能作为补充上下文或运行时覆盖，不作为默认主业务输入
  - 当主业务输入缺失，或三者同时提供多个时，节点直接报错，不做隐式优先级猜测
- 输出端口：
  - `result`：`value.v1`
    - 作用：输出 `database_kind / table_name / key_columns / written_row / row_source / affected_row_count` 这类受限摘要
    - 说明：第一阶段不承诺跨方言精确区分 `inserted` 还是 `updated`；统一按 `upsert attempted` 摘要返回
  - `prepared_row`：`value.v1`
    - 作用：输出最终组装后的单行记录对象，用于现场排障和 workflow 预览

第一阶段主业务输入的推荐语义：

- `result-record.v1`
  - 适合单帧判定、OK/NG、报警、工艺规则结果归档
  - 典型取值路径：`ok_ng`、`reason`、`metrics.*`、`conditions.*`、`alarm.active`、`alarm.code`、`metadata.*`
- `workflow-result.v1`
  - 适合把整条 workflow 的统一交付结果写入工作站结果表或批次状态表
  - 典型取值路径：`status`、`code`、`message`、`data`、`metrics`、`files`、`trace_id`、`event_id`、`metadata`
- `summary(value.v1)`
  - 适合目录批次、小批量归档和班次级摘要入库
  - 典型来源：`core.output.batch-result-summary`
  - 典型取值路径：`ok_count`、`ng_count`、`alarm_count`、`pass_ratio`、`summary_source`、`record_result_count`
- `request(value.v1)`
  - 适合补充现场上下文
  - 典型取值路径：`work_order_id`、`lot_id`、`station_id`、`device_id`、`operator_id`、`part_no`、`line_id`

第一阶段受限参数面：

- `database_url`
  - 必填，使用 SQLAlchemy URL 形式描述目标数据库连接
  - 第一阶段目标仍是本地工作站或现场已知数据库，不做云端托管 DB 编排
- `table_name`
  - 必填，目标表名
- `schema_name`
  - 可选，面向 PostgreSQL/MySQL 的 schema 或 database namespace
- `key_columns`
  - 必填，至少 1 个键列
  - 用于表达“冲突目标 / 唯一键 / 主键”这层 upsert 语义
- `row_template`
  - 可选静态对象骨架
- `column_mappings`
  - 必填数组
  - 把 `result / workflow_result / summary / request / literal` 中的字段映射到数据库列
- `static_fields`
  - 写死到记录行中的固定字段，适合站点码、设备别名、工艺号、线体编号
- `on_missing`
  - 节点级默认缺失策略，第一阶段仅支持 `error / skip / null`
  - 每条 `column_mapping` 可单独覆盖
- `update_columns`
  - 可选，显式指定允许在冲突时更新的列
  - 未提供时，默认使用“映射出的非键列”
- `skip_if_no_update_columns`
  - 可选布尔值
  - 当一行只有键列、没有任何可更新列时，是否直接跳过而不是报错
- `connect_timeout_seconds`
  - 可选，数据库连接超时
- `statement_timeout_seconds`
  - 可选，单次写入语句超时
- `echo_sql`
  - 第一阶段不开放
  - 原因：节点不应把 SQL 调试日志直接暴露成现场常用参数

第一阶段字段映射规则：

- `column_mappings` 每条至少包含：
  - `column_name`
  - `source_kind`
- 当 `source_kind != literal` 时，要求提供 `source_path`
- 当 `source_kind = literal` 时，使用 `literal_value`
- `source_kind` 仅支持 `result / workflow_result / summary / request / literal`
- `source_path` 使用点路径表达源对象读取位置，例如 `metrics.coverage_ratio`
- 第一阶段只支持“列名 -> 单值”映射，不支持表达式、聚合函数、自定义 SQL 函数、条件语句或 join
- 默认建议只写入标量、`null` 和 ISO-8601 文本时间值
- 对象或数组值第一阶段不直接假定数据库列一定支持 JSON；需要时应先在上游节点展开、扁平化或显式转成字符串

第一阶段数据库边界：

- 每次节点执行只处理：
  - 单条记录
  - 单张表
  - 单次事务
- 目标表必须已存在
- 第一阶段不支持：
  - `create table`
  - 自动迁移
  - 自动加列
  - 任意 DDL
- 节点运行时应先校验：
  - 目标表存在
  - `key_columns` 存在
  - `column_mappings / static_fields` 涉及的列存在
- 平台主业务元数据库不应作为这个节点的默认写入目标
- 如果确实要写平台自有结果表，应优先走正式 application/repository 方案，而不是复用这个 custom node

第一阶段事务与实现边界：

- 一个节点执行对应一个受控数据库事务
- 写入失败时整条事务回滚
- 不做跨节点分布式事务
- 不做批量多行 upsert
- 不做多表联动写入
- 不做存储过程调用
- 不做任意 SQL 执行
- 实现上可以复用项目的 SQLAlchemy 基础设施风格，但不应把外部结果表硬塞进平台核心聚合 Repository

第一阶段失败与排障边界：

- 主业务输入缺失或冲突时直接失败
- `database_url / table_name / key_columns / column_mappings` 参数非法时直接失败
- 映射字段缺失时默认按 `on_missing = error` 处理
- 目标表不存在、键列不存在、目标列不存在时直接失败
- dialect 不支持当前受限 upsert 语义时直接失败，不自动降级成手写 SQL
- `prepared_row` 应作为第一层现场排障入口，优先帮助确认：
  - 行记录是否已经按预期组装
  - 键列是否带齐
  - 站点上下文字段是否带齐
  - 是否把不适合入库的对象值直接送进了列映射

第一阶段明确不做：

- 不做 `raw_sql`
- 不做任意 `select / update / delete / ddl`
- 不做 join、子查询、表达式列或数据库函数模板
- 不做任意表结构自动发现后“自己猜着写”
- 不做批量多行写入
- 不做平台主库业务聚合的通用写入口
- 不做数据库驱动安装管理；依赖仍需在 `requirements.txt` 中显式声明

第一阶段最贴现场的典型场景：

- 把 `result-record.v1` 写入工作站的 `inspection_results` 结果表
- 把 `workflow-result.v1` 写入批次状态表或站点回执表
- 把 `summary(value.v1)` 写入班次统计表或目录批处理结果表

## 当前建议的实现顺序

按工业现场主线，当前最自然的正式顺序是：

1. `core.io.directory-cursor-normalize`
2. `core.io.directory-cursor-advance`
3. `core.output.batch-record`
4. `core.io.batch-files-relocate`
5. `core.output.workflow-result`
6. `core.output.batch-result-summary`
7. `directory-poll` trigger-source
8. `directory-watch` trigger-source
9. 先按当前现场主线收 `custom.plc.modbus.write-result-signals`
10. `custom.output.mes-http-post` 第一阶段实现
11. `custom.output.local-db-upsert` 第一阶段实现
12. 最后按项目需要选择 `custom.video.* / custom.protocol.* / 更多协议 pack`

以上第 1 到第 11 项当前已实现，后续顺序自然顺延到第 12 项开始。

## 下一步执行顺序

1. 先补一条更贴现场的“模型输出 -> 规则判定 -> MES HTTP / PLC 回写 / JSON/CSV / Local DB 归档”正式样例，把工业单帧主线收成可直接联调的模板
2. 然后再决定是否需要把 `mes-http-post` 继续往更细的站点 envelope、签名或 header 策略扩一层，而不是一开始就做成万能接口节点
3. 再看 `local-db-upsert` 是否值得继续扩“多行批量写入 / 更细冲突策略 / JSON 列受控支持”，而不是回头放开可执行 SQL
4. 最后再看是否需要继续补更多 detection / segmentation 调试与适配辅助节点，而不是回头扩更重的视频能力
