# SAM3 自定义节点完整实现规划

## 文档目的

本文档固定 SAM3 自定义节点的实现边界、节点清单、参数规则、运行时结构和验收标准。

后续修改 SAM3 节点时以本文档为准，不能重新引入虚假的模型 Scale、自由文本设备参数、外部手工构造 Prompt 或逐帧结果冒充视频跟踪等实现。

## 目标边界

SAM3 继续作为独立 custom node pack，不进入核心模型主链。共享 Prompt payload 和 Prompt 构造节点属于核心 workflow 基础能力，供 SAM3、YOLOE 和后续开放词汇模型共同使用。

本项目运行时不得依赖 `projectsrc/`。SAM3 模型结构、checkpoint 映射和执行器必须在正式源码目录中实现并测试。

## 固定节点清单

### Core / Input / Prompt

- `Text Prompt`
- `Text Prompts Merge`
- `Point Prompt`
- `Box Prompt`
- `Polygon Prompt`
- `Mask Prompt`
- `Prompt Regions Merge`

这些节点分别生产或合并 `text-prompts.v1`、`prompt-regions.v1`。模型节点不接受普通字符串代替标准 Prompt payload。

### SAM3 / Image

- `SAM3 Interactive Segment`
- `SAM3 Semantic Segment`

### SAM3 / Video

- `SAM3 Video Interactive Segment`
- `SAM3 Video Semantic Segment`

## 模型资产规则

- 不使用 `nano / tiny / s / m / l / x / xx` 这类虚假 Scale。
- 节点通过 `model_asset_id` 引用本地已安装且校验通过的模型资产。
- 当前只有一份兼容资产时，模型选择仍显示为单选下拉，便于现场确认实际资产。
- 多份资产同时存在时，选项来自资产目录扫描结果，不能在 Catalog 中写死。
- 模型 manifest 必须声明模型版本、架构 id、checkpoint 路径、SHA-256、支持能力和最低运行环境。
- checkpoint 加载必须使用 `weights_only=True`，并校验缺失 key、意外 key 和 tensor shape。

## Device 与 Precision

- `device` 默认值为 `auto`。
- 可选设备只来自当前节点运行时真实支持的硬件，不直接复用系统检测到的全部设备。
- 当前 PyTorch SAM3 runtime 只允许 `cpu` 和 `cuda:<index>`。
- `precision` 与设备联动：
  - CPU 只允许 `fp32`
  - CUDA 允许 `fp32`、`fp16`
  - 只有 `torch.cuda.is_bf16_supported()` 为真时才允许 `bf16`
- 不允许把不支持的组合静默降级为其他设备或精度。

## 参数归属

四个节点共享：

- `model_asset_id`
- `device`
- `precision`
- `mask_threshold`
- `stability_offset`
- `min_component_area`
- `polygon_simplify_ratio`

只有 `SAM3 Video Interactive Segment` 可以声明：

- `tracking_mode`
- `history_limit`
- `prototype_momentum`
- `attention_temperature`
- `prototype_blend_weight`
- `max_memory_tokens_per_entry`

单图 Semantic 节点不能包含视频跟踪参数。

## 运行时规则

- 单图 Semantic 加载完整视觉骨干、文本编码、image-text encoder 和 semantic segmentation head；当前节点只输出 semantic mask，不输出 detector object query 结果。
- 单图 Interactive 使用完整 interactive predictor。
- Video Semantic 复用持久化 semantic session 逐帧执行，并在摘要中明确标记为 `per-frame-semantic`；在接入正式 detector-tracker 前不能宣称具备官方视频记忆传播。
- Video Interactive 使用持久化 interactive session 和项目内显式命名的 tracking mode，保留对象 id、Prompt 修正和遮挡恢复状态。
- 项目自定义 prototype/attention 跟踪算法如需保留，应作为明确命名的独立跟踪模式，不得描述为官方 SAM3 video predictor。
- 模型 session 进入有容量限制的 runtime pool，支持 LRU、显存释放、失败清理和显式关闭。
- SAM3 node pack 默认执行超时为 300 秒；WorkflowAppRuntime 冷启动调用必须使用不低于该值的 request timeout，或在接收现场请求前完成模型预热。
- 节点运行摘要必须记录实际模型资产、设备、精度、Prompt 数量、耗时和后处理参数。

## 版本与依赖

- 当前系统和 SAM3 node pack 版本统一为 `0.1.3`。
- SAM3 Catalog 的全部节点必须填写 `node_pack_version: 0.1.3`。
- manifest 和 NodeDefinition 必须声明 Torch、OpenCV、NumPy、Pillow 和 tokenizer 资产等真实运行依赖。
- 权重文件作为本地资产管理，不提交到 git。

## 验收标准

- 空 workflow 可以只通过画布节点构造 Text、Point、Box、Polygon、Mask Prompt 并连接 SAM3。
- Catalog 不显示不存在的模型资产。
- Device 和 Precision 下拉与当前 PyTorch 运行环境一致。
- 不支持的设备、精度或 checkpoint 必须在执行前返回明确错误。
- checkpoint 加载不存在未解释的 missing keys、unexpected keys 或 shape mismatch。
- 单图和视频节点分别覆盖空结果、多实例、正负文本、多对象、遮挡恢复和 Prompt 修正。
- CPU、CUDA、FP16、BF16 按支持矩阵测试；不支持的组合也必须有拒绝测试。
- manifest、Catalog、示例 workflow、架构文档和测试使用相同的节点版本与参数名。

## 当前实现状态

| 能力 | 状态 | 固定边界 |
| --- | --- | --- |
| Core Prompt 节点 | 已实现 | 7 个节点独立实现，统一输出 `text-prompts.v1` 或 `prompt-regions.v1` |
| SAM3 模型资产 | 已实现 | 使用 `model_asset_id`、`architecture_id` 和 SHA-256，不使用虚假 Scale |
| Device 与 Precision | 已实现 | Catalog 按本机 PyTorch 能力生成下拉选项，运行时再次校验组合 |
| Image Interactive | 已实现 | 严格加载 compatible checkpoint，支持 Point、Box、Polygon、Mask |
| Image Semantic | 已实现 | 加载视觉骨干、文本骨干、image-text encoder 与 semantic head |
| Video Interactive | 已实现 | 使用持久化 interactive session 和项目内明确命名的跟踪模式 |
| Video Semantic | 已实现 | 逐帧复用 semantic session，摘要固定标记 `per-frame-semantic` |
| 官方视频记忆传播 | 未宣称实现 | 未接入正式 detector-tracker 前，不把逐帧 semantic 输出描述为官方跟踪 |
| 后处理 | 已实现 | 四个节点统一支持阈值、稳定性、最小连通域和轮廓简化参数 |
| Runtime pool | 已实现 | Interactive 与 Semantic 分池、单实例 LRU、显式关闭和释放 |
| 示例与测试 | 已实现 | 包含 Prompt 画布闭环、Catalog、资产、CPU 和真实 checkpoint 回归 |

表中的“已实现”以本项目在本文定义的能力边界为准。后续若接入官方 detector-tracker、增加新的 checkpoint 架构或扩展硬件后端，必须先更新本文的固定边界、支持矩阵和验收标准，再修改 Catalog 与运行时。
