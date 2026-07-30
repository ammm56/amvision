# SAM3 自定义节点实现边界

## 文档目的

本文档固定 SAM3 自定义节点的节点协议、模型所有权、SAM3.1 Multiplex 视频传播、
资源生命周期和验收边界。实现不得依赖 `projectsrc/`；该目录只用于开发期对照。

当前系统、节点包和节点定义版本统一为 `0.1.3`。

## 节点与共享协议

SAM3 保持独立 custom node pack：

- `SAM3 Load Checkpoint`
- `SAM3 Interactive Segment`
- `SAM3 Semantic Segment`
- `SAM3 Video Interactive Segment`
- `SAM3 Video Semantic Segment`

核心 Prompt 节点生产通用 `text-prompts.v1` 和 `prompt-regions.v1`。SAM3 只消费
共享协议，不增加模型专用 Prompt payload。

视觉 Prompt 固定规则：

- Point 使用同一对象的 `positive_points_xy` 和 `negative_points_xy`。
- Box 使用 `bboxes_xyxy`，Polygon 使用 `polygons_xy`，都允许多个对象。
- Mask 只接受已应用、含前景且源图标识匹配的 ObjectStore 图片。
- 同一个 `prompt_id` 不能混合不同几何类型。
- 源图变化后，坐标和 Mask 立即失效。

## 模型资产与参数

- Loader 通过 `model_asset_id` 引用本地 manifest，不提供虚构的 Model Scale。
- 当前默认 checkpoint 是 `sam3.1_multiplex.pt`。
- checkpoint 使用 `weights_only=True` 读取，并校验 Parameter 缺失、shape mismatch
  和所需分支。
- `device` 只允许当前 PyTorch runtime 实际支持的 CPU 或 CUDA 设备。
- CPU 只允许 FP32；CUDA 按硬件能力允许 FP32、FP16、BF16。
- Loader 独占 `model_asset_id / device / precision`。
- Segment 节点只声明推理和后处理参数，不重复声明模型参数。

## Checkpoint owner 与共享边界

一个 `SAM3 Load Checkpoint` generation 对应一个 checkpoint owner：

1. checkpoint 文件只读取一次并在 CPU 拆分 detector/tracker 分支。
2. 所需能力视图共用一个 ViT trunk。
3. Interactive 保留 `interactive_convs`、Prompt Encoder 和 Interactive Mask Decoder。
4. Semantic 保留 `convs`、文本编码、Image-Text Encoder 和 Semantic Head。
5. 视频 Propagation 保留 `propagation_convs`、Memory Transformer、Mask Memory
   Encoder 和 Multiplex Mask Decoder。

这里只共享权重和结构一致的 ViT trunk。训练目标不同的 neck、Prompt Encoder、
Semantic Head、Interactive Decoder 和 Propagation Decoder 不强行共享。

每个 owner 只缓存最近一张图片的 trunk feature。缓存键包含 session generation、
checkpoint SHA、设备、精度、推理配置和图片内容 SHA。新图片立即替换旧 feature，
不建立跨应用或无限 LRU。

## SAM3.1 Multiplex 视频传播

### Video Interactive

1. 首帧使用 Interactive Prompt 生成 Mask logits 和 decoder object token。
2. object token 经 checkpoint 中的 `interactive_obj_ptr_proj` 得到 object pointer。
3. 首帧 Mask、图像 feature、object pointer 写入请求内 conditioning memory。
4. 后续帧通过 Propagation neck、Memory Transformer 和 16-slot bucket decoder
   联合传播。

### Video Semantic

1. 首帧通过 Semantic 文本分割产生对象 Mask。
2. 该 Mask 作为 Interactive mask prompt，仅用于生成训练匹配的 object pointer。
3. Semantic Mask 与 object pointer 初始化 conditioning memory。
4. 后续帧与 Video Interactive 共用同一 Multiplex propagation。

### 固定模型参数

- Mask memory：1 个 conditioning frame + 最近 6 个 non-conditioning frame。
- Object pointer：最多 16 帧。
- Multiplex bucket：每个 bucket 固定 16 个对象 slot；超过 16 个对象时按输入顺序
  建立多个 bucket，输出按同一顺序 demux。
- Propagation decoder：每个对象固定 3 个 checkpoint 候选，按 IoU head 选择最佳。
- Mask memory 输入：`sigmoid(logits) * 2 - 1`，并附加 conditioning 1/0 通道。
- 时序位置编码：使用 checkpoint 对应的 7 组 mask memory embedding 和
  SAM3 的一维 sin-half/cos-half object pointer 编码。

视频 mutable memory 只存在于一次节点执行，不写入模型 session，不跨请求残留。
同一 session 由 lease 串行保护，不实现请求并发、队列或图片合并。

## AppRuntime 生命周期

- 每个 Workflow AppRuntime 独立持有自己的 owner，不跨应用共享。
- Preview 使用稳定的 `preview:<project_id>:<application_id>` scope；非 Loader
  节点变化不会重建模型。
- Loader 配置、直接消费能力集合或 generation 变化时受控创建新 owner。
- 不同 Loader 可由通用受限线程池并行启动；单个 Loader 内保持确定的读取、构建、
  迁移、warmup、验证顺序。
- Runtime ready 前必须完成实际推理 warmup。视频能力必须完成首帧初始化和真实的
  第二帧 Multiplex propagation，不能只检查对象是否可构造。
- 关闭、删除或替换 Runtime 时，统一释放最近图像 feature、模型 Parameter 和
  非 Parameter 的 complex RoPE device cache，再清理 CUDA allocator cache。

complex RoPE 频率不能随 `Module.to(dtype=fp16)` 转成实数，否则会丢失虚部并破坏
注意力位置编码。它采用显式设备 cache，首次推理只迁移一次，owner 关闭时迁回 CPU。

## 诊断与性能

Loader 元数据记录：

- checkpoint read
- 模型构建和设备迁移
- 各能力 warmup
- 总启动耗时
- owner 能力视图与共享 trunk 验证

节点摘要记录：

- 实际资产、设备和精度
- preprocess、backbone、Prompt encoder、decoder、postprocess
- 最近图像 feature cache 命中
- Multiplex bucket、memory 和传播模式
- session lease 等待时间

摘要不得输出 checkpoint 绝对路径。显存保持不等于模型重新加载；性能分析必须区分
session 等待、cache miss、Backbone、decoder 和 CPU postprocess。

## 验收标准

- checkpoint 只读取一次，三个能力视图的 trunk 对象 identity 相同。
- 真实 checkpoint 的 Propagation Parameter 全部匹配，无 Parameter 缺失和 shape mismatch。
- 19 个以上对象经过多 bucket mux/demux 后顺序和 tensor 数据不变。
- 首帧 Prompt 初始化、第二帧 propagation、后续 memory 更新可执行。
- Video Semantic 首帧通过 Semantic Mask 和 Interactive object pointer 闭合传播链。
- 同图修改 Prompt 不重跑 trunk；新图只计算一次并替换旧 feature。
- 单 session 串行；并发请求不能同时进入同一个模型对象。
- 连续视频请求结束后不保留请求内 memory。
- Runtime close 后 owner、feature 和 RoPE GPU 引用全部释放。
- CPU/CUDA 和支持的精度组合分别验证；不支持组合明确拒绝。
- Catalog、manifest、节点实现、测试和本文档使用一致的 `0.1.3` 版本与参数。

## 当前状态

| 能力 | 状态 |
| --- | --- |
| Image Interactive | 已实现 |
| Image Semantic | 已实现 |
| Video Interactive Multiplex propagation | 已实现 |
| Video Semantic Multiplex propagation | 已实现 |
| 单 checkpoint owner 与共享 ViT trunk | 已实现 |
| 7 帧 memory、16 pointer、16-slot bucket decoder | 已实现 |
| 真实第二帧 warmup | 已实现 |
| 请求内视频状态隔离与 session 串行 | 已实现 |
| 资源释放和 complex RoPE cache 回收 | 已实现 |

旧的 prototype、启发式 memory-attention、逐帧 semantic 和 shared-prompt 跟踪模式
已被正式 Multiplex propagation 替代，不再作为 Catalog 或运行时兼容路径保留。
