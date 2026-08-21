# ADR-0004：按后端和设备拆分模型发布运行时配置

- 状态：已接受并实现

## 背景

当前模型发布主要通过 `instance_count` 表达运行实例数量。OpenVINO predictor 对 FP32 通常使用插件默认编译属性，TensorRT predictor 则为每个 session 反序列化 engine、创建 execution context 和 CUDA stream。

随着 OpenVINO CPU、GPU、NPU 和 TensorRT 同时进入正式发布链，下面这些概念容易被混用：

- 平台模型实例数量
- OpenVINO CPU 推理线程数
- OpenVINO CPU / GPU stream 数
- OpenVINO NPU 插件推导出的请求能力
- TensorRT engine 副本、execution context 和 CUDA stream
- 同一进程内 session 隔离与独立进程故障隔离

开发机器和现场机器的 CPU、GPU、NPU 型号也可能不同。发布记录需要保存明确的 requested 值。常驻 deployment 数量与实时推理并发量是不同概念；CPU 线程配置不能把已加载但空闲的模型当作正在独占物理核心。

## 决策

模型发布运行时配置采用下面的分层：

1. 平台部署策略保存 `instance_count`、`isolation_level`、`overflow_policy`、`performance_goal` 和 `device_id`。
2. OpenVINO CPU、GPU、NPU 和 TensorRT 分别使用后端专属 options，不建立一个包含所有低层字段的扁平通用表。
3. 发布记录区分 requested 和 effective 配置。OpenVINO CPU 新建发布默认使用创建时主机物理核心数，用户可显式选择 `auto`；硬件迁移后不自动改写 requested。
4. OpenVINO CPU resource manager 在 worker 启动前只按当前 deployment 自身的 `instance_count` 和主机物理核心数生成 effective 线程数。不同常驻 deployment 共享 CPU，不互相扣减静态预算，也不因其他空闲 deployment 已启动而拒绝启动。GPU 和 NPU 仍按各自设备能力独立管理。
5. TensorRT engine 构建参数属于 `ModelBuild`，execution context、CUDA stream 和内存策略属于 deployment runtime。
6. 默认保持工业同步推理和 `overflow_policy=reject`，不在本次配置扩展中引入内部等待队列或隐式 batching。
7. 同一进程内多个 session 不表述为进程级故障隔离；需要故障隔离时显式使用 `isolation_level=process`。
8. TensorRT optimization profile 的前端形态和部署校验只读取所选 `ModelBuild` 的 engine capability 元数据，不按模型系列或任务类型维护条件分支；静态 engine 固定 profile 0，动态多 profile 才允许选择。

详细字段、设备矩阵和实施顺序见 [模型发布运行时配置](../architecture/models/deployment-runtime.md)。

## 备选方案

### 所有后端共用一组扁平参数

未采用。`inference_num_threads` 只适用于 OpenVINO CPU，OpenVINO NPU 的 `num_streams` 当前是只读结果，TensorRT 也不使用 OpenVINO stream 语义。扁平字段会产生无效配置和错误前端。

### 只保存 `auto`，不提供明确的 CPU 默认线程数

未采用。工业现场需要复现发布时的节拍配置。OpenVINO CPU 默认保存创建时物理核心数，同时保留 `auto` 选项；换机后 requested 不变，effective 由启动时按本 deployment 实例数重新计算。

### 按全部常驻 deployment 静态预留 CPU 线程

未采用。常驻只表示模型已经加载，不表示模型正在同时推理。静态预留会让空闲 deployment 长期占满账面核心，并错误阻止其他模型启动。当前按每个 deployment 自身实例数裁剪 effective 配置，保留 requested/effective 两套数据；真正同时调用多个 deployment 时由 OpenVINO 和操作系统共享调度，并通过 benchmark 与 soak 评估延迟。

### 只保留 OpenVINO 或 TensorRT 自动配置

未采用。自动配置适合作为默认值，但工业现场需要显式调优、固定 benchmark 条件和查看实际生效值。

### 把多个 session 直接定义为故障隔离实例

未采用。同一 deployment 子进程中的 session 不能提供完整进程隔离。隔离级别必须独立建模。

## 影响

- deployment schema、runtime target、predictor loader、健康状态和前端表单需要共同扩展。
- OpenVINO compile properties 需要从各模型 predictor 中抽到共享 adapter。
- 运行时必须查询目标设备 capability，并返回 requested、effective 和 warnings。
- TensorRT conversion report 和 `ModelBuild.metadata` 记录 engine shape/profile 摘要；deployment 页面按静态、动态单 profile、动态多 profile 三种能力分别隐藏、只读展示或提供受限选择。
- benchmark 和 soak 结果必须记录目标硬件、驱动、runtime 版本和实际配置。
- deployment API 一次性切换到完整 `runtime_configuration`，不接受旧扁平字段；旧 deployment 数据由迁移删除。
