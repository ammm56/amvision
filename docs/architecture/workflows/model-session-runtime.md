# Workflow Model Session 运行时

## 文档目的

本文固定 Workflow App 中 `Load Checkpoint` 类节点的通用生命周期。该机制不属于 SAM3 专用实现，后续其他需要在图内加载的模型也必须接入同一边界。

## 隔离和所有权

- 默认所有者是单个 `WorkflowAppRuntime`。
- 每个 runtime 独立加载模型，不与其他 runtime、Preview 或服务全局对象池共享。
- 一个 `Load Checkpoint` 节点实例对应一个独立 session lease；同一图内放置两个 loader 时也不做隐藏合并。
- 模型对象只存在于 runtime worker 进程，不进入图 payload、数据库或跨进程消息。
- 图中传递的是带 scope、loader node id 和 generation 的只读引用。
- runtime 停止、启动失败或进程退出时，必须释放其全部 lease。

## 启动顺序

Runtime worker 读取固定 application/template snapshot 后，先计算图中全部启用的
`Load Checkpoint` 节点和直接消费者。不同 loader 通过受限线程池并行执行各自完整的
启动协议：

1. 解析模型资产和 checkpoint。
2. 创建独立 session lease。
3. 把模型移动到 loader 配置的目标设备。
4. 使用 provider 定义的固定最小输入执行 warmup。
5. 验证 warmup 输出、实际设备、精度和能力。
6. 全部 loader 成功后一次性发布新 lease，随后才上报 runtime `running`。

同一个 loader 内的步骤保持严格顺序，不拆散 load、warmup 和 validate。不同 loader
互不共享模型对象和执行锁，默认最多使用
`workflow_runtime.model_startup_parallelism=2` 个加载线程，避免无限并发导致 CPU、
内存和显存峰值失控。该并行只发生在启动阶段，不引入推理请求并发。

任一步骤失败时关闭本轮全部新 session，不发布半初始化 lease；runtime 启动失败，
不接收第一条生产请求。已有且 fingerprint 未变化的 Preview lease 保持可用，配置变化
的旧 generation 在新模型加载前先释放，避免新旧模型同时驻留。控制面等待时间使用
`workflow_runtime.model_startup_timeout_seconds`，默认 600 秒。

## 执行规则

- 同一 lease 使用单锁串行执行。
- 多个下游模型节点可以复用同一 loader 输出，但不能并发调用同一模型对象。
- 不增加模型请求队列、跨请求动态批处理、图片合并或跨 AppRuntime 调度。
- 允许单次节点调用内部对同一图片、同一类型的 Prompt 做 decoder batching；这不改变 lease 的单锁串行边界。
- Workflow worker 原有的一次一条 `WorkflowRun` 处理方式保持不变。
- session 引用必须与当前 scope、generation、model family 和 capability 同时匹配；旧引用不能复用。

## Preview 与其他执行形态

- 已启动的 `WorkflowAppRuntime` 使用 `runtime:<workflow_runtime_id>` 作为 scope。
- 编辑器同步 Preview 使用 `preview:<project_id>:<application_id>` 作为稳定 scope。每次 Preview 仍保存独立 snapshot，但 snapshot 路径不参与模型所有权，避免相同应用重复加载 checkpoint。
- 同一 Preview scope 在一次完整 graph execution 期间只允许一个请求进入；重复点击或并发 API 请求立即返回资源占用错误，不在模型锁后排队。
- Loader 参数、节点类型或直接消费者集合不变时复用原 generation；发生变化时先关闭旧 lease，再加载、warmup 和验证新 generation。
- Loader 被删除或禁用时，manager 必须在下一次 Preview 前关闭对应的孤立 lease。
- API 进程保留的 Preview scope 数量由 `workflow_runtime.preview_model_session_scope_limit` 限制，默认只保留最近使用的 1 个应用。切换应用时先释放空闲旧 scope；旧 scope 仍在执行时拒绝新 Preview，不能并发堆叠模型。
- 删除 Workflow App 时同步释放其本机 Preview scope；服务关闭时仍执行最终 `close_all`。
- 隔离 snapshot 子进程和临时 application 子进程在本进程内创建 manager，执行结束即关闭全部 session。
- Preview scope 与生产 runtime scope 永不共享模型对象。

## 扩展接口

模型 node pack 通过 loader node type 注册 `WorkflowModelSessionProvider`。Provider 必须实现：

- `load`：解析资产、加载 checkpoint、移动设备并返回实际运行信息。
- `warmup`：使用固定受控输入完成预热。
- `validate`：验证可用于生产的最小输出。
- `close`：释放模型和设备资源。

通用 manager 负责 scope、generation、串行锁、健康摘要和失败清理；provider 不自行建立服务级全局缓存。

scope 锁必须覆盖 `prepare + loader 输出 + 全图执行 + Run cleanup`，不能只锁单个推理调用。否则编辑图变更可能在旧 Run 的 loader 输出和 Segment 消费之间替换 generation。

## 健康信息

Runtime health summary 公开以下非敏感信息：

- isolation
- execution policy
- scope id 和 manager 当前管理的 scope 数量
- ready session 数量
- loader node id
- generation
- model family 和 asset id
- 实际 device 和 precision
- capabilities
- warmup/validation 状态
- loader 启动并行策略、并行上限、checkpoint 读取/模型构建和 warmup 耗时

健康信息不公开 checkpoint 本地绝对路径，也不保存模型对象。

## 磁盘图片复用

`storage` 类型的 `image-ref.v1` 使用 runtime scope 隔离的只读解码缓存。该缓存用于
Mask、模板图和其他长期不变的 ObjectStore 图片：

- key 包含 scope、object key、文件大小、mtime、ctime、媒体类型和解码模式。
- 文件未变化时，多次 Workflow Run 只读取和解码一次；同一 Run 的不同节点也共用同一矩阵。
- 文件版本变化时自动生成新 key，旧值只保留到 LRU 回收。
- `memory`、`buffer` 和 `frame` 输入不得跨 Run 缓存。
- 缓存条目数和总字节分别由 `storage_image_cache_max_entries` 和
  `storage_image_cache_max_bytes` 约束。
- AppRuntime 健康摘要公开缓存条目、字节数、命中、未命中、LRU 回收和在途
  decode 数量，不公开 object key、磁盘路径或图片内容。
- Preview scope 被回收、应用删除、runtime worker 停止或服务关闭时确定性清理对应缓存。

共享矩阵始终标记为只读；需要修改输入的节点必须显式请求副本。该规则避免节点间污染，
同时防止长期运行时因无界图片缓存造成内存增长。

## 明确不做

- 跨 AppRuntime 模型共享
- 服务全局模型池
- 同一 session 并发推理
- 模型请求排队系统
- 跨请求自动 batching
- 图片拼接后推理
- runtime ready 后再延迟加载 checkpoint

这些约束优先保证现场单应用的边界清晰、性能可预测和长期稳定运行。

PyTorch CUDA caching allocator 可以在第一次真实尺寸推理后把 reserved memory 保留在当前进程中，任务管理器不一定立即下降；该行为应在固定高水位后稳定。Preview scope、ready session 数量或 generation 未变化时，显存仍持续按 Run 线性增长才属于泄漏。
