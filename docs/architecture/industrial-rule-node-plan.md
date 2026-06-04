# 工业规则节点规划

## 文档目的

本文档用于收口工业现场更需要的规则判定、结果回传和输入接入节点规划。

当前项目主线以单帧判定、现场本地部署、流程编排和结果可回传为主。后续继续扩展节点时，优先补工业语义节点，不优先继续加深更重的视频模型能力。

当前状态：

- 第 1 批 `core.vision.regions-*` 已接通
- 第 2 批 `ROI / coverage / overlap` 当前已接通 `roi-create / regions-intersection-metrics / regions-coverage-check / regions-inside-check / regions-offset-check`
- 第 3 批可解释完整性指标首轮已全部接通：`region-component-count / region-largest-component-ratio / region-hole-count / region-gap-check / region-span-metrics / region-continuity-score`
- 第 4 批工业判定节点当前已接通 `threshold-check / range-check / presence-check / ok-ng-decision / alarm-condition / process-decision`
- 第 4 批结果回传节点当前已接通 `result-record / alarm-record / json-save-local / csv-append-local / http-post`
- 第 4 批输入接入节点当前已接通 `image-load-local / image-list-local / directory-scan / directory-batch-window`
- 工业单帧规则样例当前已补到 `docs/examples/workflows/industrial_single_frame_sealant_quality_gate.*` 与 `industrial_single_frame_glue_roi_callback.*`
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
- 输出：`http-response.v1` 或 `value.v1(summary)`
- 作用：通用 HTTP 结果回传

#### core.output.webhook-post

- 放置位置：`core`
- 输入：`result-record.v1 / alarm-record.v1 / value.v1`
- 输出：`http-response.v1` 或 `value.v1(summary)`
- 作用：Webhook 回调

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

1. 第 4 批剩余缺口收口，优先处理 `webhook-post` 是否保留为独立节点
2. 工业单帧 workflow 样例继续往“更接近现场使用”收一层，例如补一条带上游 `regions.v1` 产出说明或显式 runtime 闭环
3. `roi-create`、批量输入和结果回传的参数面继续做易用性优化，优先补动态 ROI、批次推进和结果字段规范化
4. 继续补少量重点测试和文档，不把耗时长链放入默认测试
5. 更重的视频语义稳定增强继续保持后置，不作为当前工业单帧主线优先项

## 当前明确不优先的方向

- 不先做大型规则 DSL
- 不先做抽象工艺引擎
- 不优先继续深挖 `video-semantic` 时序增强
- 不把相机、RTSP、采集卡、PLC、MES 专有接入直接塞进 `core`

## 当前剩余缺口

- `core.output.webhook-post` 当前仍只存在于规划中，仓库里还没有对应节点实现；需要决定是保留为 `http-post` 的轻包装节点，还是直接从规划里移除，统一使用 `http-post`
- 当前工业单帧样例默认假设上游已经提供 `regions.v1`，还没有补一条“本地图像输入 + 上游模型结果接入说明 + 规则判定 + 结果回传”的更完整现场闭环说明
- `roi-create` 当前以固定参数创建 ROI 为主，还没有把运行时 `value.v1` 动态 ROI 输入收成正式能力
- 当前批量输入链已经有 `directory-scan -> directory-batch-window -> image-list-local`，但还没有补更贴现场的批次推进约定与使用说明

## 下一步执行顺序

1. 先决定并收口 `webhook-post`，避免第 4 批在规划上一直处于“看起来未完成”的状态
2. 再补一条更贴现场的工业单帧闭环说明或 workflow 样例，把上游 `regions.v1` 来源和下游 JSON / CSV / HTTP 回传链说明清楚
3. 然后收 `roi-create` 的动态输入和批量输入使用面，让目录扫描和 ROI 调整更顺手
4. 最后再看是否需要继续扩更多工业规则原子节点，而不是直接跳去更重的视频能力
