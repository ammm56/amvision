# Workflow 三路并行列表分支

## 目的

本文固定 Workflow 图中通用三路并行列表处理的设计、实现边界和使用方式，避免后续把当前现场应用的 80 个 ROI、classification 或 3 个 deployment instance 写成项目专用逻辑。

该能力属于核心 Workflow 编排基础设施，所有 Workflow App 都可以使用。分支内部可以放模型推理、OCR、条码识别、传统视觉、规则处理、格式转换或其他普通节点。

## 当前现场场景

当前 `workflow-app-20260718114943` 的实际输入包含 80 个 ROI 图片引用，classification 发布服务配置了 3 个 deployment instance。原图使用一个 For Each 串行调用 80 次 classification，模型推理节点累计约 1.77 秒，是该 Workflow Run 的主要耗时。

这个场景是首个验证对象，不是节点契约的一部分：

- 通用节点不知道 ROI、托盘、插槽或 classification。
- 通用节点不读取 deployment 配置，也不根据实例数自动改变分支数。
- 当前应用由编排人员明确选择三路节点，并在图中放置三条 For Each 与三个模型推理节点。
- 其他应用可以在三条分支内使用不同节点，或直接传递普通 JSON 列表。

## 明确的图结构

```text
List
  |
Parallel List Split 3
  |-- part_1 -> For Each -> branch nodes -> For Each End --|
  |-- part_2 -> For Each -> branch nodes -> For Each End --|-> Ordered List Merge 3 -> downstream
  `-- part_3 -> For Each -> branch nodes -> For Each End --|
```

现场 80 项输入按连续区间平衡拆分：

```text
part_1 = item 0..26   (27)
part_2 = item 27..53  (27)
part_3 = item 54..79  (26)
```

有序合并始终按 `part_1 -> part_2 -> part_3` 连接结果，与线程完成先后无关，因此下游槽位序号和原始输入顺序保持一致。

## Core nodes

### Parallel List Split 3

- node type id：`core.logic.parallel-list-split-3`
- category：`logic.parallel`
- 输入：`items / value.v1`
- 输出：`part_1`、`part_2`、`part_3`，均为 `value.v1`
- 行为：把数组平衡拆成三个连续分区；空数组输出三个空分区
- 角色：普通列表数据节点，同时是显式三路并行开始边界

### Ordered List Merge 3

- node type id：`core.logic.parallel-list-merge-3`
- category：`logic.parallel`
- 输入：`part_1`、`part_2`、`part_3`，均为 `value.v1`
- 输出：`items / value.v1`、`count / value.v1`
- 行为：严格按端口编号连接三个数组
- 角色：普通列表数据节点，同时是显式三路并行结束边界

节点定义使用 metadata localization，中文、英文、日文和韩文界面统一通过现有节点本地化解析器显示，不在 Vue 组件中写死文本。

## 执行规则

- 只并行执行一对 Split 3 / Merge 3 边界内的三条显式分支。
- 每条分支内部继续按原有 DAG 和 For Each 规则顺序执行。
- 最大分支 worker 数固定为 3，不创建无界线程。
- Merge 等待三条分支全部结束后执行。
- 节点记录按分支 1、2、3 的固定顺序合并，执行事件携带 `parallel_branch_index`。
- 任一分支失败时，取消尚未开始的 sibling future；已经开始的分支完成自身 `finally` 和资源释放后，整个边界返回失败。
- 分支内部节点不能跨分支连线、直接输出到边界外或直接作为模板输出。
- 分支可以读取拆分节点之前已经完成的外部依赖。
- 当前不支持并行边界嵌套；需要嵌套时先根据真实需求重新评估资源上限。
- 图中其他无依赖节点不会因为该能力自动并行，避免改变已有 Workflow App 的执行顺序。

## 运行上下文和资源边界

三个分支共享同一次 Workflow Run 的服务上下文；上下文中已有的 deployment 配置、进程句柄和运行状态缓存继续按原有 Workflow Run 生命周期复用。每条分支使用各自的节点输出表、For Each `item/index` 和分支执行记录，不能用共享可变变量传递分支结果。

并发基础设施要求：

- `ExecutionImageRegistry` 的注册、读取、释放操作必须线程安全。
- LocalBufferBroker client 的 request/response 必须成对串行，避免共享 response queue 返回错误的 `request_id`。
- mmap cache 的 seek/read/write 必须加锁，因为一个 mmap view 的文件游标不能被多个线程同时修改。
- cleanup list 和 cleanup lock 在拆分前创建并由三个分支共享，确保任一分支登记的 lease、临时文件或 deployment cleanup 都由父 Workflow Run 回收。
- deployment 进程句柄继续由父进程 supervisor 管理，不能复制到 Workflow 子线程。

## 不包含的行为

第一阶段不实现以下隐式能力：

- 不增加 `infer_batch` 模型协议。
- 不让单个 Classification 节点内部隐藏线程池。
- 不自动把任意列表识别为图片或 ROI。
- 不根据 deployment instance 数量自动改写图。
- 不自动并行整个 DAG。
- 不创建托盘、插槽或某个 Workflow App 专用节点。
- 不把最后不足三项的批次补空或重复推理；完整列表在进入 For Each 前已拆成 27、27、26 这类有效分区。

后续只有在三分支实测仍显示 LocalBuffer / IPC 是主要瓶颈时，才单独评估原图引用加 ROI 描述、批量 BufferRef 或模型 runtime batch。这些优化不能改变本组三路基础节点的公开数据语义。

## 当前应用调整建议

将现场应用改图时：

1. 在 `Image Refs To Value List` 后放置 `Parallel List Split 3`。
2. 建立三条独立的 For Each、Value To Image Ref、Classification、Payload To Value、For Each End 分支。
3. 三个 Classification 节点选择同一个 deployment instance id，运行时由该 deployment 的 3 个实例承接并发请求。
4. 三个 For Each End 分别连接 `Ordered List Merge 3` 的对应端口。
5. Merge 输出继续连接现有 `Slot Classification Summary`，后续节点不变。
6. 当前汇总只使用 top1 时，将三个 Classification 的 `top_k` 设为 1。
7. 轮廓只用于 minAreaRect 时，将 Contour `approximation` 设为 `simple`，并用现场图验证几何偏差。

应用模板属于现场数据，不由 core node 注册代码自动改写。保存前必须在 Preview Run 中确认 80 项顺序、分类结果和最终摘要一致。

## 验证要求

- 0、1、2、3、80、81 项拆分后数量正确，合并结果与输入完全一致。
- 三条分支最大同时执行数为 3，单条分支内部仍为 1。
- 分支完成顺序变化不影响最终数组顺序。
- 分支错误包含原始失败节点和 `parallel_branch_index`。
- 高频运行后 LocalBuffer `free_count` 回到基线，无 orphan lease、线程和临时文件。
- 当前 80 项 classification 场景需要同时记录 Workflow 总耗时、三条分支耗时和 deployment instance 分布。
- 前端亮色、暗色及四种语言下节点名称、端口和说明均可读。
