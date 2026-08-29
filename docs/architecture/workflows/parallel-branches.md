# Workflow Parallel 分支

## 目的

本文固定 Workflow 图中通用 Parallel 分支的公开契约、执行边界和使用方式。节点实现不能绑定某个 Workflow App、模型类型、ROI 数量或 deployment instance 数量。

具体 Hough 同类节点和五类模型 Batch 节点设计见[视觉并行与模型批量节点设计](vision-parallel-and-model-batch.md)。其中 ROI 数量、图片数量和 deployment instance 数量只决定当前应用的画布分支与 `max_concurrency`，不属于任何基础节点的名称、端口或固定行为。

## 设计原则

- 节点名称、端口名称、参数名和 category 保持 English，与现有 `For Each Start`、`For Each End`、`Get List Item` 等节点一致。
- List 数据处理放在 `core.logic.collection`，并行执行边界放在
  `core.logic.parallel`。
- 分支数量由 `Parallel Start` 输出端实际连接的分支数量决定，可以是 1、3、10 或其他正数。
- `max_concurrency` 是资源上限，不是分支数量。10 条分支可以设置为 3 路受控并发，也可以在资源允许时设置为 10。
- 执行器只并发显式 `Parallel Start` / `Parallel End` 边界，不自动并发整张 DAG。
- 分支结果始终按 `Parallel Start` 输出连线在模板中的稳定顺序合并，与线程完成顺序无关。

## 基础节点

### Split List

- node type id：`core.logic.list-split`
- category：`core.logic.collection`
- 输入：`Items / value.v1`
- 输出：`Partitions / value.v1`、`Count / value.v1`
- 参数：`partition_count`，范围 1 到 1024
- 行为：按原始顺序平衡生成指定数量的连续 partitions

`Split List` 是普通 List 数据节点，不直接创建动态端口。节点端口契约保持静态，使用多个现有 `Get List Item` 节点按 index 取得需要的 partition，因此用户可以明确画出任意数量的分支。

### Parallel Start

- node type id：`core.logic.parallel-start`
- category：`core.logic.parallel`
- 输入：`Value / value.v1`
- 输出：`Value / value.v1`
- 参数：`max_concurrency`，范围 1 到 64，默认 4
- 行为：原样转发 Value；输出连线数量声明实际分支数量

### Parallel End

- node type id：`core.logic.parallel-end`
- category：`core.logic.parallel`
- 输入：`Results / value.v1`，`multiple=True`
- 输出：`Results / value.v1`、`Count / value.v1`
- 参数：`mode`
  - `collect`：每条分支结果作为一项收集
  - `concat`：要求每条分支结果都是 List，并按分支顺序连接成一个 List

## 图结构

```text
Items
  |
Split List(partition_count=N)
  |
Parallel Start(max_concurrency=M)
  |-- Get List Item(index=0) -> branch nodes --|
  |-- Get List Item(index=1) -> branch nodes --|-> Parallel End(mode=concat) -> downstream
  |                    ...                    |
  `-- Get List Item(index=N-1) -> branch nodes |
```

每条 `branch nodes` 可以使用 For Each、模型推理、OCR、条码识别、OpenCV、规则判断、格式转换或其他普通节点。Parallel 基础设施不知道分支中的数据是否为图片、ROI 或推理结果。

## 执行和校验规则

- 一对 `Parallel Start` / `Parallel End` 之间至少有一条完整分支。
- 每条 Start 输出连线必须最终向 End 的 `Results` 提供一个明确结果。
- End 的每条 Results 输入连线必须属于当前 Start 的一个分支。
- 分支内部节点不能跨分支连接、直接输出到边界外或直接作为模板输出。
- 分支可以读取 Parallel Start 之前已经完成的外部依赖。
- 当前不支持 Parallel 边界嵌套。
- worker 数为 `min(branch_count, max_concurrency)`，不会创建无界线程。
- 任一分支失败时保留真实失败节点、`parallel_branch_index`、Start id 和 End id。
- 已经开始的 sibling 分支完成自身 finally 和 cleanup 后，整个边界返回失败。

## 运行上下文和资源边界

各分支共享同一次 Workflow Run 的服务上下文，继续复用已有的 deployment 配置、进程句柄和运行状态缓存；节点输出表、For Each `item/index` 和分支记录相互隔离。

- `ExecutionImageRegistry` 的注册、读取和释放使用线程安全访问。
- LocalBufferBroker client 的 request/response 成对串行，避免共享 response queue 交叉消费。
- mmap cache 的 seek/read/write 受锁保护。
- cleanup list 和 cleanup lock 由父 Workflow Run 创建并供全部分支共享。
- deployment 进程句柄继续由父进程 supervisor 管理，不复制到 Workflow 子线程。

### Node concurrency contract

每个 `NodeDefinition` 通过 `concurrency_policy` 明确声明 Parallel 分支中的并发能力：

- `thread-safe`：节点可由多个分支同时调用；五类已发布模型推理节点使用该策略。
- `serialized`：默认策略；同一 `node_type_id` 在单次 Workflow Run 内串行调用，防止旧节点或自定义节点的可变状态产生竞态。
- `exclusive`：单次 Workflow Run 内与其他 `exclusive` 节点互斥，适合独占设备或进程内全局资源。
- `unsupported-in-parallel`：保存校验或执行边界启动前直接拒绝，不让不安全节点进入分支线程。

锁只在 Workflow worker 进程内创建。父进程向 `multiprocessing.Queue` 发送执行 metadata 前会剥离 cleanup lock、Parallel node locks 和分支标记；worker 收到请求后再创建当前进程的锁，避免 `threading.RLock` 被异步 pickle 后导致请求静默丢失。

### 同类节点和类型 bridge

- 同一个 `node_type_id` 可以出现在多条 Parallel 分支中；只有显式声明 `thread-safe` 时才会真正同时执行。
- 普通节点不增加 parallel checkbox。并行关系只存在于 Start/End 边界和画布连线中。
- 当前 Parallel v1 只收发 `value.v1`，强类型输入输出必须通过明确 bridge 进入和离开边界。
- `Payload To Value` 支持的结构化 payload 必须补齐对称 `Value To ...` 节点。当前设计至少补齐 image-refs、circles、detections、categories、poses 和 obbs；已有 segments bridge 继续使用。
- bridge 只校验和恢复 JSON 结构，不复制 `image-ref.v1` 的图片主体。
- Hough Circles 在完成 ExecutionImageRegistry、Debug Preview、cleanup、timing 和 OpenCV 全局状态审计前保持 `serialized`；不得只修改 Catalog 字段便宣称同类并行安全。

## 当前应用配置

当前 24 张 crop、2 个同步 deployment instances 的 classification 图目标配置：

1. `Split List.partition_count = 2`，得到两个保持原始顺序的 12 项 partitions。
2. `Parallel Start.max_concurrency = 2`。
3. 使用两个 `Get List Item`，index 分别为 0、1。
4. 每条分支执行 `Value To Image Refs -> Classification Batch -> Categories Batch To Value List`。
5. 两条结果连接同一个 `Parallel End.Results`，并设置 `mode = concat`。
6. Parallel End 输出继续连接通用 Classification Results Summary，后续规则链不变。

四个 Hough Circles 使用四条显式分支，但初始 `max_concurrency` 不直接固定为 4。gray8 和 ROI grayscale 落地后按 1、2、4 实测选择，当前验证优先从 2 开始。以上数字只存在于当前 Workflow App 的节点参数和画布连线中，其他应用可以选择不同分支数，也可以在分支内调用 detection、segmentation、pose、OBB、OCR 或非模型节点。

## 验证要求

- 1、3、10 个分支均能保存、加载和运行。
- 80 项按 3 partitions 拆分后为 27、27、26，concat 后与输入顺序完全一致。
- 10 个分支配 `max_concurrency=3` 时，同时运行数不超过 3，但结果仍包含全部 10 个分支。
- 空 partitions 不制造占位结果。
- 分支完成顺序变化不影响最终 Results 顺序。
- 同类 `serialized` 节点进入不同分支时仍保持串行；审计并声明 `thread-safe` 后才能观察到重叠执行。
- 24 项按两个 Batch 分支执行时，concat 后顺序和逐图执行一致，两个健康实例的 inference counter 都增长。
- 高频运行后 LocalBuffer `free_count` 回到基线，无 orphan lease、线程和临时文件。
