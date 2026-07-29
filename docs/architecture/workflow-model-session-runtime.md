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

Runtime worker 读取固定 application/template snapshot 后，按图中启用的 `Load Checkpoint` 节点顺序串行执行：

1. 解析模型资产和 checkpoint。
2. 创建独立 session lease。
3. 把模型移动到 loader 配置的目标设备。
4. 使用 provider 定义的固定最小输入执行 warmup。
5. 验证 warmup 输出、实际设备、精度和能力。
6. 全部 loader 成功后才上报 runtime `running`。

任一步骤失败时关闭当前 scope 已创建的全部 session，runtime 启动失败，不接收第一条生产请求。控制面等待时间使用 `workflow_runtime.model_startup_timeout_seconds`，默认 600 秒。

## 执行规则

- 同一 lease 使用单锁串行执行。
- 多个下游模型节点可以复用同一 loader 输出，但不能并发调用同一模型对象。
- 不增加模型请求队列、动态批处理、图片合并或跨 AppRuntime 调度。
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

健康信息不公开 checkpoint 本地绝对路径，也不保存模型对象。

## 明确不做

- 跨 AppRuntime 模型共享
- 服务全局模型池
- 同一 session 并发推理
- 模型请求排队系统
- 自动 batching
- 图片拼接后推理
- runtime ready 后再延迟加载 checkpoint

这些约束优先保证现场单应用的边界清晰、性能可预测和长期稳定运行。

PyTorch CUDA caching allocator 可以在第一次真实尺寸推理后把 reserved memory 保留在当前进程中，任务管理器不一定立即下降；该行为应在固定高水位后稳定。Preview scope、ready session 数量或 generation 未变化时，显存仍持续按 Run 线性增长才属于泄漏。
