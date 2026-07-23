# 模型发布运行时配置

## 文档目的

本文档固定模型发布时的运行资源概念、OpenVINO CPU / GPU / NPU 参数边界、TensorRT 构建期与运行期参数边界，以及后续 API、前端和 runtime adapter 的实现顺序。

本文档用于避免下面几类实现偏差：

- 把 `instance_count`、`NUM_STREAMS`、`INFERENCE_NUM_THREADS` 都解释成同一种“模型实例数”
- 把 OpenVINO CPU 参数原样套到 GPU、NPU 或 TensorRT
- 把当前机器探测到的核心数永久保存成跨机器默认值
- 只修改一个 predictor，导致相同后端在不同模型或任务中行为不一致
- 为提高并发吞吐而改变工业现场同步调用、立即返回结果的语义
- 把同一进程内的多个 session 误认为进程级故障隔离

## 当前状态

截至 2026-07-23，本文档描述的是目标设计和实施约束，不表示相关字段已经进入公开 API 或前端。

当前实现仍有下面这些限制：

- `DeploymentInstance` 主要通过 `instance_count` 表达实例数量。
- deployment runtime pool 为每个实例分别延迟加载一个模型 session；同一 deployment 的这些 session 位于同一个 deployment 子进程中。
- OpenVINO FP32 predictor 通常不传性能属性，由 OpenVINO 按设备和模型使用默认配置；FP16 路径主要传 `inference_precision`。
- TensorRT session 当前分别反序列化 engine、创建一个 execution context 和一个 CUDA stream。
- TensorRT 当前公开运行设置主要覆盖 pinned output host buffer，没有正式拆分 engine 副本、execution context、CUDA stream、CUDA Graph 和 optimization profile。
- 当前实现不能把 `instance_count` 等同于进程数，也不能据此宣称单个实例崩溃不会影响同一 deployment 中的其他实例。

后续实现必须先在共享 deployment/runtime contract 中形成统一边界，再由各模型 predictor 适配；不得只在单个 YOLO 或 RF-DETR predictor 中增加孤立字段。

## 核心规则

模型发布运行时配置长期遵守下面这些规则：

1. `instance_count` 是本项目的部署概念，不是 OpenVINO 或 TensorRT 原生属性。
2. OpenVINO 的 `performance_hint` 是高层性能目标，不是延迟 SLA，也不固定等于某个线程数或 stream 数。
3. `inference_num_threads` 只表示 OpenVINO CPU 推理线程限制，不用于 OpenVINO GPU、NPU 或 TensorRT。
4. OpenVINO `num_streams` 在 CPU 和 GPU 上可配置；NPU 是否可写必须以目标机器插件返回的 `supported_properties` 为准，当前 OpenVINO NPU 文档将其列为只读结果。
5. TensorRT 使用 engine、execution context 和 CUDA stream 表达运行并发，不能复用 OpenVINO 字段名掩盖不同语义。
6. TensorRT engine 构建参数与部署运行参数必须分开保存；运行期不能假装修改已经固化到 engine 的构建选项。
7. 默认配置使用 `auto` 或空值表达“在目标机器解析”，不能把开发机器物理核心数固化为跨机器默认值。
8. 运行状态同时返回请求值和实际生效值，现场性能分析不得只读取创建请求。
9. CPU、GPU 或 NPU 的资源估算用于提示和诊断，不得仅因目标机器核心数或计算单元数量变化而拒绝创建、启动或运行。
10. 工业同步推理默认保持立即执行、立即返回结果的调用边界；本规划不引入内部等待队列，不自动把 workflow 的多次同步调用合并成 list、batch 或隐藏队列，也不自动改写显式并行分支。

## 概念边界

### `instance_count`

`instance_count` 表示一个 `DeploymentInstance` 期望创建多少个可独立占用的推理运行单元。它属于平台部署策略。

它不直接说明：

- OpenVINO 编译了多少个 stream
- 每个 OpenVINO CPU 模型使用多少线程
- TensorRT engine 是否共享权重
- TensorRT 有多少 auxiliary stream
- 是否存在进程级故障隔离

后续如果需要明确故障边界，应增加独立的 `isolation_level`：

- `session`：同一 deployment 进程内的独立 session 或 execution context
- `process`：每个运行单元使用独立进程

不能继续通过 `instance_count` 同时表达副本数量、并发容量和故障隔离。

### `performance_hint`

OpenVINO `performance_hint` 是设备插件可以解释的高层目标：

- `LATENCY`：优先缩短单个推理请求的响应时间。
- `THROUGHPUT`：优先提高持续并发请求的总吞吐量，单个请求延迟可能增加。
- `CUMULATIVE_THROUGHPUT`：主要用于 `AUTO` 或多设备组合，让多个设备共同提供吞吐量。
- 未设置：由目标插件使用默认行为。

`LATENCY` 不表示“固定使用全部核心”。以 CPU 为例，OpenVINO 会根据处理器拓扑、模型精度、P-core / E-core 和平台策略推导 `num_streams`、推理线程数、超线程和绑核行为。

显式设置低层参数后，低层参数会限制或覆盖 high-level hint 推导出的部分结果。因此前端必须把 `performance_hint` 表述为“性能目标”，不能表述为“线程模式”。

### 请求值和实际值

发布配置必须分开保存或返回下面两组值：

```text
requested:
  inference_num_threads: auto
  num_streams: auto
  performance_hint: latency

effective:
  inference_num_threads: 8
  num_streams: 1
  performance_hint: latency
```

`requested` 表示发布记录的稳定意图，`effective` 表示当前目标机器、当前驱动和当前 runtime 插件上的实际结果。

从 16 核机器迁移到 6 核机器时：

- `requested=auto` 保持不变
- `effective` 在新机器重新解析
- 不因核心数变化拒绝启动
- 健康状态和诊断结果明确显示新的实际值

用户显式填写数值时保留该请求值。目标插件不支持或目标硬件范围发生变化时，runtime adapter 应返回明确的降级或裁剪说明，不得静默伪装成原值已经生效。

## 参数支持矩阵

| 参数或概念 | 所属层次 | OpenVINO CPU | OpenVINO GPU | OpenVINO NPU | TensorRT |
| --- | --- | --- | --- | --- | --- |
| `instance_count` | 平台部署策略 | 支持 | 支持 | 支持 | 支持 |
| `isolation_level` | 平台部署策略 | 规划 | 规划 | 规划 | 规划 |
| `performance_goal` | 平台通用意图 | 可映射 | 可映射 | 可映射 | 只能形成推荐配置 |
| `performance_hint` | OpenVINO高层属性 | 支持 | 支持 | 支持 | 不适用 |
| `inference_num_threads` | OpenVINO CPU低层属性 | 支持 | 不适用 | 不适用 | 不适用 |
| `num_streams` | OpenVINO设备并发属性 | 可写 | 可写 | 按插件能力；当前文档为只读 | 不适用 |
| `num_requests` | OpenVINO请求提示 | 支持 | 支持 | 支持 | 不适用 |
| execution context | TensorRT运行状态 | 不适用 | 不适用 | 不适用 | 支持 |
| CUDA stream | TensorRT运行状态 | 不适用 | 不适用 | 不适用 | 支持 |
| auxiliary stream | TensorRT engine构建和运行 | 不适用 | 不适用 | 不适用 | 支持 |

## OpenVINO 设备配置

### CPU

OpenVINO CPU 的常用运行参数包括：

- `performance_hint`
- `inference_num_threads`
- `num_streams`
- `scheduling_core_type`
- `enable_hyper_threading`
- `enable_cpu_pinning`
- `num_requests`

其中：

- `inference_num_threads` 限制 CPU 推理可使用的逻辑处理器数量。
- `num_streams` 限制可并行处理的 infer request 数量。
- `scheduling_core_type` 用于 P-core / E-core 混合处理器。
- `enable_hyper_threading` 和 `enable_cpu_pinning` 的默认行为与平台、核心类型和性能目标有关。

CPU 发布表单可以提供“自动”和显式线程数，但默认保存值应为 `auto`。前端可以显示“自动，当前设备预计 8”，不能把探测值 8 当作可移植默认值落库。

下面的计算只能用于诊断：

```text
estimated_thread_demand =
  active_instance_count × effective_inference_num_threads
```

它不能作为发布创建或启动的失败条件。全局 CPU device resource manager 负责汇总当前正在运行的 deployment 资源估算、给出超额订阅提示和记录 benchmark 上下文，不负责因硬件差异拒绝运行。

### GPU

OpenVINO GPU 的常用参数包括：

- `performance_hint`
- `num_streams`
- `num_requests`
- `inference_precision`
- `device_id`
- `queue_priority`
- `queue_throttle`
- `host_task_priority`
- `enable_loop_unrolling`
- `disable_winograd_convolution`

OpenVINO GPU 每个 stream 有对应的 host thread 和 OpenCL queue，但多个队列不保证 GPU kernel 一定真实并行，最终行为取决于硬件和驱动。

同一模型需要多个并发请求时，OpenVINO GPU multi-stream 可以共享权重，通常比重复加载多个模型实例节省显存。但平台仍可保留独立模型实例选项，用于明确的状态隔离或进程隔离场景。前端必须把“共享模型 multi-stream”和“独立实例”显示为不同概念。

`inference_num_threads` 不用于限制 GPU 计算资源。`compilation_num_threads` 只影响编译阶段，也不能替代 GPU stream 或并发设置。

### NPU

OpenVINO NPU 的常用参数包括：

- `performance_hint`
- `num_requests`
- `inference_precision`
- `turbo`
- `tiles`
- `compilation_mode_params`
- dynamic quantization 和 QDQ 优化选项
- `run_inferences_sequentially`

当前 OpenVINO NPU 文档中：

- `num_streams` 是插件返回的只读属性。
- `LATENCY` 下推荐 infer request 数通常为 1。
- `THROUGHPUT` 下推荐 infer request 数通常为 4。
- 默认性能目标是 `LATENCY`。

NPU 参数必须以目标机器的 `supported_properties`、`range_for_streams`、`range_for_async_infer_requests`、`optimal_number_of_infer_requests` 和设备信息为准。

下面这些选项只进入高级设置：

- `turbo`：可能增加功耗、热负载、内存占用和兼容性风险，不作为长期持续负载默认值。
- `tiles`：显式值可能降低跨 NPU SKU 可移植性。
- `compilation_mode_params`：属于编译器高级选项，版本兼容性必须单独记录。

前端不得为了表单统一而给 NPU 提供一个实际不可写的 `openvino_num_streams` 字段。

### AUTO 和多设备

OpenVINO `AUTO` 需要单独表达候选设备和调度意图：

- `LATENCY` 或 `THROUGHPUT` 通常选择适合的目标设备。
- `CUMULATIVE_THROUGHPUT` 可以让多个候选设备共同承担请求。
- startup fallback、runtime fallback 和 schedule policy 属于 AUTO 专属选项。

这些选项不能混入普通 CPU / GPU / NPU 基础表单。当前工业同步调用默认不自动启用 `CUMULATIVE_THROUGHPUT` 或 auto batching。

## TensorRT 配置边界

### 基本运行模型

TensorRT 使用下面的关系表达并发：

```text
serialized engine
  -> ICudaEngine
     -> one or more IExecutionContext
        -> one main CUDA stream per concurrent execution
        -> optional auxiliary streams inside one inference
```

一份 `ICudaEngine` 可以创建多个 execution context，并让多个 context 在各自 CUDA stream 上并行执行。一个 context 不得被多个并发执行无约束共享；并发执行需要独立 context、独立 stream 和正确的 device memory 生命周期。

平台后续需要明确区分：

- engine 副本数
- execution context 数量
- main CUDA stream 数量
- auxiliary stream 数量
- process 隔离数量

这些概念不能继续全部由 `instance_count` 表示。

### Engine 构建期参数

下面这些参数属于 conversion / engine build，不属于普通 deployment runtime 修改：

- FP32 / FP16 / INT8 / FP8 等精度
- dynamic shape 和 optimization profile 范围
- workspace / memory pool limit
- builder optimization level
- timing cache
- tactic 选择和 tactic source
- `max_aux_streams`
- sparsity、refit、版本兼容和硬件兼容设置

`max_aux_streams` 控制单次推理内部的层间并行。它可能降低单次推理延迟，也可能增加 activation memory，不能等同于 execution context 数量。

发布页面应只读展示 engine 的构建摘要。需要修改这些值时，应重新创建 `ModelBuild`，不能修改 deployment metadata 后假装 engine 已改变。

### 部署运行期参数

TensorRT deployment runtime 后续可以控制：

- CUDA device
- execution context 数量
- 每个并发 context 的 main CUDA stream
- optimization profile 选择
- CUDA Graph 是否启用
- context device memory 策略
- pinned input / output host buffer 策略
- 同步等待策略
- session 或 process 隔离级别

多个 context 并行时会竞争 SM、L2 和显存带宽。TensorRT engine 构建时选择的 tactic 可能假设整张 GPU 可用，并发运行后不一定仍是最优。因此每个 engine 的并发配置必须通过目标 GPU 上的真实 benchmark 验证，不能仅根据 context 数量线性估算性能。

同一 engine 共享多个 context 偏向显存效率；反序列化多个 engine 副本偏向状态隔离；独立进程才提供更强的进程级故障边界。三种模式都可以保留，但必须显式命名并记录实际内存开销。

## 目标配置结构

后续 schema 分成平台策略和后端专属配置。下面的结构用于固定概念，不代表已经发布的 API 字段：

```text
deployment_execution_policy:
  instance_count
  isolation_level: session | process
  overflow_policy: reject
  performance_goal: latency | throughput | balanced
  device_id

backend_options:
  openvino_cpu:
    performance_hint
    inference_num_threads
    num_streams
    scheduling_core_type
    enable_hyper_threading
    enable_cpu_pinning

  openvino_gpu:
    performance_hint
    num_streams
    num_requests
    inference_precision
    queue_priority
    queue_throttle

  openvino_npu:
    performance_hint
    num_requests
    inference_precision
    turbo
    tiles
    compilation_mode_params

  tensorrt:
    execution_context_count
    optimization_profile
    cuda_graph_enabled
    device_memory_strategy
    pinned_output_buffer_enabled
    pinned_output_buffer_max_bytes
```

`overflow_policy=reject` 固定当前同步调用的容量边界：运行单元全部占用时明确返回满载错误，不在 deployment runtime 内增加不可控等待队列。本配置不要求改变 workflow 的同步节点调用方式。

## Capability 和降级规则

后端不得根据静态字段表假定所有目标机器支持相同参数。创建或启动 deployment 时应：

1. 查询目标 backend 和 device 的 capability。
2. 解析 `auto` 值。
3. 应用目标设备支持的显式值。
4. 读取编译后或加载后的实际属性。
5. 返回 requested、effective、device summary 和 warnings。

硬件资源数量变化不构成失败条件。下面这些情况可以产生 warning：

- 显式线程数超过当前可用处理器数量并被 runtime 裁剪
- 当前 NPU driver 不支持某个高级属性
- GPU/NPU 属性在迁移后回退到 `auto`
- 估算出的活动 deployment CPU 线程总量明显超出当前物理核心数
- TensorRT context 并发高于已经验证的 benchmark profile

下面这些无法执行的情况仍应失败：

- 模型或算子不受目标设备支持且不存在有效 fallback
- TensorRT engine 与目标 GPU、TensorRT 或 CUDA 运行时不兼容
- 运行时产物损坏
- 显式配置值语法无效且无法安全降级

降级不能静默发生。健康状态、事件和部署详情必须能看到原因和实际值。

## 前端规则

发布界面按目标 backend 和 device 动态显示字段：

- 基础区只显示 device、instance count、隔离级别、性能目标和 precision。
- OpenVINO CPU 高级区显示线程、stream、核心类型、超线程和绑核。
- OpenVINO GPU 高级区显示 stream、请求数、队列和精度控制。
- OpenVINO NPU 高级区显示插件实际支持的属性；turbo、tiles 和编译器参数默认折叠。
- TensorRT 分开显示 engine 构建摘要和可编辑的 deployment runtime 参数。

所有 `auto` 字段同时显示当前设备的预估或实际值，例如：

```text
推理线程：自动（当前实际 8）
OpenVINO stream：自动（当前实际 1）
```

前端不得：

- 把逻辑处理器数直接标成物理核心数
- 把不支持的字段保存为看似成功的配置
- 把 OpenVINO GPU/NPU 或 TensorRT 参数塞进 CPU 表单
- 把单个 session 的健康状态描述成进程隔离

## 同步调用和 workflow 边界

模型 runtime 资源配置不改变 workflow 的业务语义：

- workflow inference node 仍同步调用已发布 `DeploymentInstance` 并立即取得结果。
- workflow 不负责决定 OpenVINO stream、CPU线程或TensorRT context。
- workflow 可以根据现场业务明确使用一个 For Each 或多条并行分支；deployment runtime 不自动合并、拆分或重写这些调用。
- deployment runtime 不因启用 throughput 配置就自动增加等待队列。
- 对批处理、异步聚合或跨请求调度的支持如果后续进入范围，必须作为独立能力设计，不能由本配置隐式启用。

## 实施顺序

### 第一阶段：共享 contract 和观测

- 定义平台部署策略和各 backend/device 的 tagged options。
- 增加 `requested`、`effective`、`warnings` 和 device capability 响应。
- 统一 OpenVINO compile properties 构造入口，避免各模型 predictor 各写一份。
- 不改变现有同步调用和满载行为。

### 第二阶段：OpenVINO CPU

- 接入 `performance_hint`、`inference_num_threads` 和 `num_streams`。
- 正确识别物理核心、逻辑处理器、P-core / E-core 和 NUMA 信息。
- 增加全局 CPU 资源估算和超额订阅提示，不设置硬启动门槛。
- 对单实例全核心、多实例分核和默认自动配置建立真实 benchmark。

### 第三阶段：OpenVINO GPU 和 NPU

- 运行时查询 `supported_properties`，动态构造发布表单和 compile properties。
- GPU 增加 multi-stream、request、precision 和队列控制。
- NPU 增加 performance hint、request、turbo 和高级编译选项；不伪造可写 `num_streams`。
- 增加不同驱动、不同 SKU 和硬件迁移回归。

### 第四阶段：TensorRT

- 将 engine 构建摘要与 deployment runtime 参数分开。
- 明确 engine 副本、execution context、CUDA stream 和 process isolation。
- 评估共享 engine 多 context 与独立 engine 副本的延迟、吞吐和显存。
- 增加 CUDA Graph、optimization profile 和 device memory 策略。

### 第五阶段：长期稳定性

- 每个 backend 建立单请求、受控并发和满载 benchmark。
- 建立冷启动、warmup、restart、模型切换和硬件迁移测试。
- 建立 CPU 内存、GPU 显存、NPU 内存、线程数、句柄数和延迟分位数的长期 soak 基线。
- 把有效配置、硬件摘要和 benchmark profile 记录到部署诊断中。

## 验收规则

相关实现完成时至少满足：

- 同一份发布配置使用 `auto` 时可以在不同核心数的 CPU 上启动。
- 硬件变化不会仅因资源预算估算而导致创建或启动失败。
- OpenVINO CPU、GPU、NPU 不共享错误的低层字段。
- TensorRT 构建参数不能在 deployment 页面被伪装成运行期可修改参数。
- 运行详情能够同时显示 requested 和 effective 配置。
- 所有 deployment task type 和 model type 复用同一套配置边界。
- workflow 同步调用语义不因本次配置扩展而改变。
- 并发性能必须由真实 benchmark 和长期 soak 证明，不能用实例数做线性推算。

## 官方参考

- [OpenVINO CPU Performance Hints and Thread Scheduling](https://docs.openvino.ai/2026/openvino-workflow/running-inference/inference-devices-and-modes/cpu-device/performance-hint-and-thread-scheduling.html)
- [OpenVINO GPU Device](https://docs.openvino.ai/2026/openvino-workflow/running-inference/inference-devices-and-modes/gpu-device.html)
- [OpenVINO NPU Device](https://docs.openvino.ai/2026/openvino-workflow/running-inference/inference-devices-and-modes/npu-device.html)
- [OpenVINO Automatic Device Selection](https://docs.openvino.ai/2026/openvino-workflow/running-inference/inference-devices-and-modes/auto-device-selection.html)
- [NVIDIA TensorRT Optimizing Performance](https://docs.nvidia.com/deeplearning/tensorrt/latest/performance/optimization.html)
- [NVIDIA TensorRT IExecutionContext](https://docs.nvidia.com/deeplearning/tensorrt/latest/_static/python-api/infer/Core/ExecutionContext.html)
