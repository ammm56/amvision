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
- 当前已经有正式的视频输入 contract：`video-ref.v1`、`frame-window.v1`、`tracks.v1`，并已落地第一批 core 视频节点。
- `YOLOE / SAM3` 第一阶段都是单图 custom node；视频/多帧属于下一阶段扩展。
- 当前项目仍然不直接接相机、PLC、传感器等物理设备；视频第一阶段默认从本地磁盘载入。

## 核心结论

- 本地磁盘视频载入应先做成 core 节点，而不是 `SAM3` 专用节点。
- `SAM3` 视频/多帧能力应建立在通用视频输入节点和通用时序 payload 上。
- 视频后的分割/跟踪结果也不应只为 `SAM3` 独占，应优先抽象成通用 payload 和通用结果节点。
- 物理视频源、相机、RTSP、工业采集卡、触发桥接等仍然留在后续 custom node pack 中实现，不进入当前 core 主链。

## 视频工具运行时边界

### 当前最小实现

- 当前第一批视频节点已经接通，但底层仍以 `OpenCV VideoCapture` 为最小实现。
- 这条路径适合先打通 `video-ref.v1`、`frame-window.v1` 和 core 节点边界，不代表长期正式视频工具链已经定型。
- 当前应把 `OpenCV` 视为“最小可用实现”和“测试/开发阶段实现”，而不是长期唯一视频运行时。

### 正式目标

- 正式视频工具运行时应收敛到 `ffmpeg/ffprobe`。
- `ffprobe` 优先负责视频元数据探测、时长、帧率、分辨率和容器信息读取。
- `ffmpeg` 优先负责抽帧、重编码、视频 overlay、clip 导出和最终视频保存。
- `OpenCV` 后续只保留为最小 fallback 或测试用途，不作为正式视频工具链主路径。

### 为什么不放到 `data/`

- `ffmpeg/ffprobe` 属于应用运行时工具，不属于模型资产、数据资产或用户可变业务目录。
- `data/` 目录在本项目里用于本地数据、模型权重、运行产物和维护产物；不应用来承载跨平台运行时二进制。
- 因此 `ffmpeg` 不应放在 `data/files/`、`data/maintenance/` 或模型目录树下。

### Windows 中使用 `exe` 还是 `dll`

- Windows 下正式调用入口应是 `ffmpeg.exe` 和 `ffprobe.exe`。
- 相关 `.dll` 属于这些可执行文件的运行时依赖，应与 `exe` 放在同一目录或可解析目录中。
- 本项目后续应调用 `ffmpeg.exe` / `ffprobe.exe`，而不是直接调用某个 `dll`。
- 因此 Windows 目录约定的重点是“提供 `exe` 入口，并随附同目录依赖 `dll`”，不是单独暴露 `dll` 给节点或 workflow 使用。

## `ffmpeg/ffprobe` 目录约定

### 仓库中的运行时目录约定

开发与装配阶段建议使用如下目录：

```text
runtimes/
└─ third_party/
   └─ ffmpeg/
      ├─ windows-x64/
      │  └─ bin/
      │     ├─ ffmpeg.exe
      │     ├─ ffprobe.exe
      │     └─ *.dll
      └─ linux-x64/
         └─ bin/
            ├─ ffmpeg
            └─ ffprobe
```

说明：

- `windows-x64/bin/` 下必须同时放 `ffmpeg.exe`、`ffprobe.exe` 和它们依赖的 `dll`。
- `linux-x64/bin/` 下放对应的 `ffmpeg`、`ffprobe` 可执行文件。
- 如后续增加 `arm64`、`ubuntu-22.04-x64` 等平台细分，应继续在 `third_party/ffmpeg/` 下按平台拆分，不回写到 `data/`。

### 发布目录中的工具目录约定

发布目录建议复制到：

```text
release/
└─ full/
   └─ tools/
      └─ ffmpeg/
         └─ bin/
            ├─ ffmpeg.exe / ffmpeg
            ├─ ffprobe.exe / ffprobe
            └─ 相关 dll（Windows）
```

说明：

- 最终发布包通常只应携带目标平台所需的一套工具，不建议把 Windows 和 Linux 两套二进制同时打进同一个最终交付包。
- 仓库可以保留跨平台装配来源目录，最终 `assemble-release` 或等价装配步骤应按目标平台挑选一套复制进发布目录。

## `ffmpeg/ffprobe` 查找策略

后续运行时代码建议按如下优先级查找：

1. 显式配置路径
2. 发布目录自带工具路径
3. 仓库运行时目录
4. 系统 `PATH` 中的 `ffmpeg/ffprobe`（仅作为非默认 fallback）

### 1. 显式配置路径

- 允许后续在运行时配置或维护配置中显式指定 `ffmpeg` 根目录或 `ffmpeg.exe` / `ffprobe.exe` 路径。
- 这是最优先的入口，适合定制发行包、便携部署或客户现场定制目录。

### 2. 发布目录自带工具路径

- 当服务运行在打包后的发布目录时，优先查找 `release/.../tools/ffmpeg/bin/`。
- 这条路径代表“项目自带工具链”，应优先于系统环境变量。

### 3. 仓库运行时目录

- 开发环境下，如发布目录不存在，可回退查找 `runtimes/third_party/ffmpeg/<platform>/bin/`。
- 这条路径主要服务本地开发和测试。

### 4. 系统 `PATH` fallback

- 只有在显式配置、发布目录和仓库运行时目录都找不到时，才考虑尝试系统 `PATH`。
- 这条 fallback 仅用于诊断或临时兼容，不应作为默认部署前提。
- 文档和发布说明中不应把“目标机自行安装系统 ffmpeg”写成默认要求。

## 从 `OpenCV` 到 `ffmpeg/ffprobe` 的替换步骤

### 第 1 步：保留当前 core 节点与 payload contract

- 继续保留：
  - `video-ref.v1`
  - `frame-window.v1`
  - `tracks.v1`
  - `core.io.video-load-local`
  - `core.io.video-decode-frames`
- 先稳定 workflow contract，不在切换工具链时改节点输入输出。

### 第 2 步：先引入 `ffprobe` 元数据探测 helper

- 在视频运行时支持层新增 `ffprobe` 查找和调用 helper。
- `video-load-local` 的元数据探测优先切到 `ffprobe`。
- `OpenCV` 元数据读取保留为 fallback。

### 第 3 步：再引入 `ffmpeg` 解码 helper

- 为 `video-decode-frames` 增加基于 `ffmpeg` 的抽帧实现。
- 初期允许：
  - `ffmpeg` 主路径
  - `OpenCV` fallback
- 但默认首选应切到 `ffmpeg`。

### 第 4 步：新增视频导出与渲染节点时直接使用 `ffmpeg`

- 以下节点后续应直接建立在 `ffmpeg` 上：
  - `core.io.video-overlay-render`
  - `core.io.video-save`
- 不建议先用 `OpenCV VideoWriter` 做正式版再二次迁移。

### 第 5 步：在发布装配中补正式工具链

- 把 `ffmpeg/ffprobe` 纳入发布装配目录。
- 平台差异通过运行时 manifest 和发布装配逻辑管理，而不是靠节点里写死绝对路径。

## 当前实现与后续切换关系

- 当前视频节点已经可用，但工具链层仍是 `OpenCV` 最小实现。
- 后续切到 `ffmpeg/ffprobe` 时，应保持 payload contract、core 节点 id 和 workflow 连接方式不变。
- 也就是说，替换的是“节点内部工具实现”，不是“视频 workflow 抽象层”。

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

### 4. `core.io.frame-window-preview`

职责：

- 把 `frame-window.v1` 采样整理成 `gallery-preview` response body
- 直接复用 workflow editor 现有图库缩略预览能力
- 让视频链在不新增前端协议的前提下具备多帧可视化能力

输入：

- `frames`：`frame-window.v1`

参数：

- `title`
- `sample_mode`
- `max_items`
- `response_transport_mode`

输出：

- `body`：`response-body.v1`

第一阶段说明：

- 先复用现有 `gallery-preview` body 形态，不单独发明 `video-preview` 前端协议
- `sample_mode` 当前支持 `uniform / head`
- 典型用法是 `video-decode-frames -> frame-window-preview`

### 5. `core.output.video-body`

职责：

- 把最终 `video-ref.v1` 转成正式 `response-body.v1`
- 让 workflow app 的响应面板直接播放保存后的视频结果
- 与 `image-body` 保持同一层级，作为“正式输出节点”而不是调试预览节点

输入：

- `video`：`video-ref.v1`

参数：

- `title`
- `output_object_key`

输出：

- `body`：`response-body.v1`

第一阶段说明：

- `frame-window-preview` 负责“多帧调试和缩略预览”
- `video-body` 负责“最终视频结果的正式可播放响应”
- 两者都复用 `response-body.v1` 总协议，但职责不同，不应合并成一个万能节点

### 6. `core.logic.value-field-extract`

职责：

- 从 `value.v1` 中按点分路径提取字段
- 让 `payload-to-value` 输出可以自然接到 `table-preview / value-preview / object-create`

输入：

- `value`：`value.v1`

参数：

- `path`

输出：

- `value`：`value.v1`

第一阶段说明：

- 这个节点不是视频专属，但对 `tracks.v1 / regions.v1 / frame-window.v1` 的 workflow 使用面很重要
- 典型用法是 `tracks -> payload-to-value -> value-field-extract(items) -> table-preview`

## `SAM3` 视频 / 多帧的分层位置

### 应该属于 `SAM3` pack 的部分

- `custom.sam3.video-interactive-segment`
- `custom.sam3.video-semantic-segment`
- `SAM3` 专用的多帧状态管理
- `SAM3` 专用 memory / tracker 状态逻辑

当前已落地的实现：

- `custom.sam3.video-interactive-segment`
- 输入：`frame-window.v1 + prompt-regions.v1`
- 输出：`tracks.v1`
- 当前默认策略：`memory-prototype-state`，`track_id` 继续稳定映射为 `prompt_id`
- 当前已不再只是 shared prompt 或单纯上一帧 mask 回灌；现在会维护对象原型和最近若干帧 mask 历史，并在当前帧特征上生成 memory prompt
- 当前也已提供更重的 `memory-attention-tracker` 可选模式：会维护跨帧 token memory、mask history 和 prototype，并在当前帧 low-res 特征上执行 attention 风格对象检索
- 当前已经补了更长窗口、更大位移和更多对象数的定向回归；默认轻量逻辑测试放在 `tests/`，真实本地 `sam3.pt` 的视频链 smoke 放在 `tests/integration/`，继续保持显式执行
- `custom.sam3.video-semantic-segment`
- 输入：`frame-window.v1 + text-prompts.v1`
- 输出：`tracks.v1`
- 当前策略：`shared-text-prompts-across-window`
- 当前按 `prompt_id` 稳定映射 `track_id`，并沿用单帧 `semantic-segment` 的 grouped positive/negative 文本语义与后处理规则

### `SAM3` 视频模式选择建议

当前 `SAM3` 视频线不是只有一种固定强度，而是按复杂度逐层增强：

1. `interactive-segment`
- 适合单帧、抽帧、人工修正和最小交互链

2. `video-interactive-segment + shared-prompts-across-window`
- 适合短窗口、变化很小、希望直接复用同一组 prompt 的场景

3. `video-interactive-segment + stateful-mask-propagation`
- 适合连续位移但形变不大、希望把上一帧 mask 延续到下一帧的场景

4. `video-interactive-segment + memory-prototype-state`
- 当前默认推荐模式
- 适合更复杂的位移、遮挡前后延续和一定程度的外观变化

5. `video-interactive-segment + memory-attention-tracker`
- 当前已实现的更重可选模式
- 适合更长时序、更复杂目标变化和更强的多目标视频跟踪
- 推理更重，建议只在 `memory-prototype-state` 不足时启用

建议的现场调参起点：

- `history_limit = 6`
- `prototype_momentum = 0.72`
- `attention_temperature = 0.12`
- `prototype_blend_weight = 0.35`
- `max_memory_tokens_per_entry = 256`

workflow 编排时应根据任务实际复杂度选择，不必默认一律走最重模式；简单任务优先使用更轻的单帧或 shared prompt 版本，复杂任务再逐步切到更强的状态跟踪模式。

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
5. `core.io.frame-window-preview`
6. `core.output.video-body`

### `core.vision.tracks-filter`

- 按 `score / class / track_id / state / area` 过滤 `tracks.v1`

### `core.vision.tracks-to-regions`

- 把 `tracks.v1` 拆成当前帧或指定帧的 `regions.v1`

### `core.io.video-overlay-render`

- 把 `tracks.v1` 或 `regions.v1` 渲染回视频帧

### `core.io.video-save`

- 把视频结果重新编码并保存到本地或 ObjectStore

### `core.io.frame-window-preview`

- 把解码帧、overlay 结果或分帧 regions 结果采样整理成 gallery preview
- 适合作为视频 workflow 的默认调试/预览出口

### `core.output.video-body`

- 把最终保存后的视频整理成正式响应 body
- 适合作为 workflow app 的最终输出，不负责多帧缩略调试

## 当前推荐的 workflow 使用面

### 最小视频预览链

- `video-load-local`
- `video-decode-frames`
- `frame-window-preview`

### `SAM3` 视频跟踪预览链

- `video-load-local`
- `video-decode-frames`
- `custom.sam3.video-interactive-segment`
- `tracks-filter`
- `video-overlay-render`
- `frame-window-preview`
- 需要落盘并作为最终输出时再接 `video-save -> video-body`

### `SAM3 memory-attention` 现场样例链

- `video-load-local`
- `video-decode-frames`
- `custom.sam3.video-interactive-segment`
  - `tracking_mode = memory-attention-tracker`
- `tracks-filter`
- `video-overlay-render`
- `video-save`
- `video-body`

对应源 JSON：

- [docs/examples/workflows/sam3_video_memory_attention_review.template.json](../examples/workflows/sam3_video_memory_attention_review.template.json)
- [docs/examples/workflows/sam3_video_memory_attention_review.application.json](../examples/workflows/sam3_video_memory_attention_review.application.json)

### `tracks / regions` 表格调试链

- `custom.sam3.video-interactive-segment`
- `tracks-filter`
- `payload-to-value`
- `value-field-extract`，`path = items`
- `table-preview`

### 单帧调试链

- `video-load-local`
- `video-decode-frames`
- `frame-window-item-get`
- `interactive-segment`
- `image-preview`

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

### 第 4 批

10. 实现 `core.vision.tracks-filter`
11. 实现 `core.vision.tracks-to-regions`
12. 实现 `core.io.video-overlay-render`
13. 实现 `core.io.video-save`
14. 实现 `core.output.video-body`
15. 继续补 `memory-attention-tracker` 的长窗口回归、参数调优和工程化验证

## 当前这轮代码实现范围

当前这轮先实现：

1. `video-ref.v1`
2. `frame-window.v1`
3. `tracks.v1`
4. `core.io.video-load-local`
5. `core.io.video-decode-frames`
6. `core.io.frame-window-item-get`
7. `core.io.frame-window-preview`
8. `core.logic.value-field-extract`
9. `custom.sam3.video-interactive-segment` 第一阶段版本
10. `core.vision.tracks-filter`
11. `core.vision.tracks-to-regions`
12. `core.io.video-overlay-render`
13. `core.io.video-save`
14. `core.output.video-body`

当前这轮暂不实现：

1. upstream 全量视频 tracker / 多帧传播全能力

## 下一步

- 先继续补 `memory-attention-tracker` 的更长窗口回归、性能基线和现场使用说明
- 再补更长时长时序回归和视频链基准
- `video-body` 已作为正式输出层补齐；后续只再评估是否需要独立的 `video-preview` 节点
