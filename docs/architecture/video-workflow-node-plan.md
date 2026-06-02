# 视频 Workflow 节点规划

## 文档目的

本文档用于固定视频输入、多帧时序 payload、`SAM3` 视频/多帧能力和通用视频后处理节点的分层边界，避免后续实现过程中把“通用视频能力”和“模型专用视频能力”混在一起。

本文档重点回答：

- 哪些 payload contract 先进入 core catalog
- 第一批 core 视频节点先做哪些
- `SAM3` 视频/多帧节点应该放在哪一层
- 通用视频结果与跟踪结果应该如何抽象

## 当前边界

- 当前系统底层已经有 `image-ref.v1` 的 `frame` 传输形态，以及 `LocalBufferBroker` 的 `FrameRef` / ring frame 基础设施。
- 当前还没有正式的视频输入 contract，也没有通用的 core 视频节点。
- `YOLOE / SAM3` 第一阶段都是单图 custom node；视频/多帧属于下一阶段扩展。
- 当前项目仍然不直接接相机、PLC、传感器等物理设备；视频第一阶段默认从本地磁盘载入。

## 核心结论

- 本地磁盘视频载入应先做成 core 节点，而不是 `SAM3` 专用节点。
- `SAM3` 视频/多帧能力应建立在通用视频输入节点和通用时序 payload 上。
- 视频后的分割/跟踪结果也不应只为 `SAM3` 独占，应优先抽象成通用 payload 和通用结果节点。
- 物理视频源、相机、RTSP、工业采集卡、触发桥接等仍然留在后续 custom node pack 中实现，不进入当前 core 主链。

## 第一批通用 payload contract

第一批先固定 3 个通用 payload contract：

1. `video-ref.v1`
2. `frame-window.v1`
3. `tracks.v1`

### 1. `video-ref.v1`

用途：

- 表示一个可被 workflow 节点消费的视频源引用
- 第一阶段优先覆盖本地磁盘视频
- 后续可扩展到 `storage`、对象存储内视频或其他受控来源

第一阶段字段建议：

- `transport_kind`
- `local_path`
- `object_key`
- `media_type`
- `frame_count`
- `fps`
- `width`
- `height`
- `duration_ms`

第一阶段 transport：

- `local-path`
- `storage`

说明：

- 当前第一阶段以 `local-path` 为主。
- `storage` 预留给后续把视频资产写入本地 ObjectStore 的场景。
- 不在第一阶段引入 `buffer` 或 `frame` 级视频源 contract；连续帧仍然通过 `frame-window.v1` 和后续 `FrameRef` 路径承接。

### 2. `frame-window.v1`

用途：

- 表示从某个视频源中解码出来的一组时间连续或离散帧
- 供多帧模型、时序规则节点、跟踪节点和视频预览/保存节点复用

第一阶段字段建议：

- `source_video`
- `count`
- `window_start_index`
- `window_end_index`
- `items`

`items` 每项字段建议：

- `frame_index`
- `timestamp_ms`
- `image`

说明：

- `image` 继续复用 `image-ref.v1`
- 第一阶段先只做“已经解码好的帧窗口”，不在 contract 中塞复杂的缓存/复用策略

### 3. `tracks.v1`

用途：

- 表示视频或多帧处理后的对象跟踪、时序 region 或时序分割结果
- 供结果过滤、渲染、导出、保存和协议上报节点复用

第一阶段字段建议：

- `source_video`
- `count`
- `items`

`items` 每项字段建议：

- `track_id`
- `frame_index`
- `timestamp_ms`
- `score`
- `class_id`
- `class_name`
- `bbox_xyxy`
- `polygon_xy`
- `mask_image`
- `region_id`
- `state`

说明：

- 第一阶段先只固定 contract，不在这一步里直接实现复杂跟踪逻辑。
- `tracks.v1` 不只服务 `SAM3`，后续其他 tracking / video segmentation / 视频规则节点也应复用。

## 第一批 core 视频节点

第一批 core 视频节点先固定 3 个：

1. `core.io.video-load-local`
2. `core.io.video-decode-frames`
3. `core.io.frame-window-item-get`

### 1. `core.io.video-load-local`

职责：

- 从本地磁盘读取一个视频文件路径
- 探测基础元数据
- 输出 `video-ref.v1`

输入：

- 可选 `path`：`value.v1`

参数：

- `local_path`

输出：

- `video`：`video-ref.v1`
- `summary`：`value.v1`

第一阶段说明：

- 允许“参数写死路径”或“从上游动态输入路径”两种方式
- 只做本地文件探测，不做解码

### 2. `core.io.video-decode-frames`

职责：

- 按给定帧范围把视频解码为 `frame-window.v1`

输入：

- `video`：`video-ref.v1`

参数：

- `start_frame`
- `end_frame`
- `step`
- `max_frames`
- `encode_format`

输出：

- `frames`：`frame-window.v1`
- `summary`：`value.v1`

第一阶段说明：

- 第一阶段只做“按帧索引解码”
- 输出帧图继续注册成 `image-ref.v1`
- 不在第一阶段引入复杂缓存或后台视频解码 worker

### 3. `core.io.frame-window-item-get`

职责：

- 从 `frame-window.v1` 里按索引取出单帧

输入：

- `frames`：`frame-window.v1`
- 可选 `index`：`value.v1`

参数：

- `index`
- `allow_negative`

输出：

- `image`：`image-ref.v1`
- `frame_meta`：`value.v1`

第一阶段说明：

- 这个节点给单帧模型复用视频链提供最小桥接能力
- 也方便 preview / 调试 / 条件判断 / 抽样保存

## `SAM3` 视频 / 多帧的分层位置

### 应该属于 `SAM3` pack 的部分

- `custom.sam3.video-interactive-segment`
- `custom.sam3.video-semantic-segment`
- `SAM3` 专用的多帧状态管理
- `SAM3` 专用 memory / tracker 状态逻辑

### 不应该属于 `SAM3` pack 的部分

- 本地视频载入
- 通用视频解码
- 通用帧窗口 payload
- 通用跟踪结果 payload
- 通用结果渲染 / 视频保存 / 跟踪过滤节点

## 模型推理后的通用节点

在 `SAM3` 视频/多帧节点之后，应继续补一批通用后处理/结果节点：

1. `core.vision.tracks-filter`
2. `core.vision.tracks-to-regions`
3. `core.io.video-overlay-render`
4. `core.io.video-save`

### `core.vision.tracks-filter`

- 按 `score / class / track_id / state / area` 过滤 `tracks.v1`

### `core.vision.tracks-to-regions`

- 把 `tracks.v1` 拆成当前帧或指定帧的 `regions.v1`

### `core.io.video-overlay-render`

- 把 `tracks.v1` 或 `regions.v1` 渲染回视频帧

### `core.io.video-save`

- 把视频结果重新编码并保存到本地或 ObjectStore

## 实现顺序

### 第 1 批

1. 把 `video-ref.v1 / frame-window.v1 / tracks.v1` 接进 core payload contract
2. 实现 `core.io.video-load-local`
3. 实现 `core.io.video-decode-frames`

### 第 2 批

4. 实现 `core.io.frame-window-item-get`
5. 补 `frame-window.v1` 相关调试/预览节点
6. 为本地视频输入补最小 smoke 和定向回归

### 第 3 批

7. 实现 `custom.sam3.video-interactive-segment`
8. 引入 `tracks.v1` 正式输出
9. 再补 `tracks-filter / tracks-to-regions / video-overlay-render / video-save`

## 当前这轮代码实现范围

当前这轮先实现：

1. `video-ref.v1`
2. `frame-window.v1`
3. `tracks.v1`
4. `core.io.video-load-local`
5. `core.io.video-decode-frames`

当前这轮暂不实现：

1. `core.io.frame-window-item-get`
2. `SAM3` 视频/多帧节点
3. `tracks.v1` 的真实跟踪生成节点
4. 视频 overlay / save 节点

## 下一步

- 先完成当前这轮的 contract 与 core 节点实现
- 跑定向回归
- 再开始 `core.io.frame-window-item-get`
- 之后再进 `SAM3` 视频/多帧 project-native runtime
