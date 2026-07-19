# Workflow Parallel 分支

## 目的

本文固定 Workflow 图中通用 Parallel 分支的公开契约、执行边界和使用方式。节点实现不能绑定某个 Workflow App、模型类型、ROI 数量或 deployment instance 数量。

当前 `workflow-app-20260718114943` 使用 80 个 ROI，classification 发布服务配置了 3 个 deployment instances。该信息只决定当前应用应画 3 条分支并把 `max_concurrency` 设置为 3，不属于任何基础节点的名称、端口或固定行为。

## 设计原则

- 节点名称、端口名称、参数名和 category 保持 English，与现有 `For Each Start`、`For Each End`、`Get List Item` 等节点一致。
- 不新增 `logic.parallel` category。List 数据处理放在 `logic.collection`，执行边界放在 `logic.iteration`。
- 分支数量由 `Parallel Start` 输出端实际连接的分支数量决定，可以是 1、3、10 或其他正数。
- `max_concurrency` 是资源上限，不是分支数量。10 条分支可以设置为 3 路受控并发，也可以在资源允许时设置为 10。
- 执行器只并发显式 `Parallel Start` / `Parallel End` 边界，不自动并发整张 DAG。
- 分支结果始终按 `Parallel Start` 输出连线在模板中的稳定顺序合并，与线程完成顺序无关。

## 基础节点

### Split List

- node type id：`core.logic.list-split`
- category：`logic.collection`
- 输入：`Items / value.v1`
- 输出：`Partitions / value.v1`、`Count / value.v1`
- 参数：`partition_count`，范围 1 到 1024
- 行为：按原始顺序平衡生成指定数量的连续 partitions

`Split List` 是普通 List 数据节点，不直接创建动态端口。节点端口契约保持静态，使用多个现有 `Get List Item` 节点按 index 取得需要的 partition，因此用户可以明确画出任意数量的分支。

### Parallel Start

- node type id：`core.logic.parallel-start`
- category：`logic.iteration`
- 输入：`Value / value.v1`
- 输出：`Value / value.v1`
- 参数：`max_concurrency`，范围 1 到 64，默认 4
- 行为：原样转发 Value；输出连线数量声明实际分支数量

### Parallel End

- node type id：`core.logic.parallel-end`
- category：`logic.iteration`
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

## 当前应用配置

当前 80 ROI、3 deployment instances 的应用建议配置：

1. `Split List.partition_count = 3`，得到 27、27、26 三个 partitions。
2. `Parallel Start.max_concurrency = 3`。
3. 使用三个 `Get List Item`，index 分别为 0、1、2。
4. 每条分支放置独立的 For Each、Value To Image Ref、Classification、Payload To Value 和 For Each End。
5. 三条 For Each End 连接同一个 `Parallel End.Results`，并设置 `mode = concat`。
6. Parallel End 输出继续连接现有 `Slot Classification Summary`，后续节点不变。
7. 当前汇总只使用 top1 时，将三个 Classification 的 `top_k` 设置为 1。

以上数字只存在于当前 Workflow App 的节点参数和画布连线中。其他应用可以使用 1、10 或更多分支，也可以在分支内调用 detection、segmentation、pose、OBB、OCR 或非模型节点。

## 验证要求

- 1、3、10 个分支均能保存、加载和运行。
- 80 项按 3 partitions 拆分后为 27、27、26，concat 后与输入顺序完全一致。
- 10 个分支配 `max_concurrency=3` 时，同时运行数不超过 3，但结果仍包含全部 10 个分支。
- 空 partitions 不制造占位结果。
- 分支完成顺序变化不影响最终 Results 顺序。
- 高频运行后 LocalBuffer `free_count` 回到基线，无 orphan lease、线程和临时文件。
