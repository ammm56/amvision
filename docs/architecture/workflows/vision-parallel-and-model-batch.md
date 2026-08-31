# 视觉并行与模型批量节点设计

> 状态：已实现并完成开发环境真实数据验收。本文固定 Hough Circles、显式 Parallel、五类模型 Batch 节点、payload 互操作和同步 deployment 调用边界；后续变更仍需同步更新公开契约和验证证据。

## 文档目的

本文解决以下已经在真实 Workflow Preview 中确认的问题：

- Hough Circles 当前在读取完整图片时隐式执行灰度转换，Search ROI 不能减少这部分整图开销。
- Grayscale 产生单通道矩阵后，execution image registry 又把它转换成 BGR24，造成额外颜色转换和约三倍图片字节占用。
- `Parallel Start` / `Parallel End` 已能并发显式分支，但默认 `serialized` 的同类节点不会并发，`value.v1` 边界也需要完整的强类型 bridge 才能复用结构化结果。
- 当前 24 个 classification 单图节点被拆成两条 12 项 For Each 分支，单次模型计算约 8 至 10 ms，节点平均耗时却约 34 ms，主要额外成本来自逐图节点生命周期、gateway 往返、LocalBuffer 准备和实例获取/释放。

目标不是增加应用专用节点，也不是自动并发整张 DAG，而是用通用基础节点、稳定 payload 和确定性执行边界把实际 Workflow 推进到接近理论耗时。

## 已确认的硬约束

- 普通节点不提供 `parallel` 开关。并行只由 `Parallel Start` / `Parallel End` 的画布边界表达。
- `Parallel Start.max_concurrency` 是唯一的分支并发上限，不等于分支数量，也不保证更大的值一定更快。
- Hough Circles 的 ROI 灰度参数必须在节点参数面板可见，默认启用；只转换解析后的 Search ROI，显式关闭时要求输入已经是灰度图。
- Hough Circles 启用灰度转换时，必须先解析并裁剪 Search ROI，再对该 ROI 转灰度；不得先转换整图。
- 五类模型 Batch 节点按 detection、classification、segmentation、pose、OBB 的任务语义区分，不按 YOLOX、YOLOv8、YOLO11、YOLO26、RF-DETR 等模型家族区分。
- Batch 节点的复杂功能由共享 runtime 实现；Workflow App、工位、托盘、ROI 数量和 deployment instance 数量不得进入节点名称或固定行为。
- 同步 Batch 调用不新增容量等待队列、自动重试、隐式拆批或节点内部线程池。没有空闲实例时继续立即返回 `deployment_inference_busy`。
- Batch 输出必须能经显式 bridge 恢复为已有单项 payload，继续接入现有通用节点；不得产生只能由当前 App 或一个专用汇总节点识别的结果。
- 图片主体继续位于 `image-ref.v1` / LocalBuffer 数据面。Batch inline JSON 不嵌套临时 memory、BufferRef 或 FrameRef locator。

## 优化前基线证据

以下数据是实现前用于定位问题的开发数据和 Workflow Preview Run 基线，不是修改后的 Trigger 和长时间内存结论：

- 四个 Hough Circles 单节点耗时约 115 至 341 ms；整图 Grayscale 与四个 Hough 的近期合计平均约 1009 ms。
- Hough 的主要耗时除整图灰度外，还包含候选径向采样和 robust circle fitting。
- 32 张现有图片、四个 ROI 共 128 个 Hough case 中，把 `maximum_candidates` 从 40 降至 12 虽明显降低耗时，但已出现少量结果偏移，因此不能直接修改默认值替代结构优化。
- 当前两条 classification 分支分别约 509 ms 和 502 ms，Parallel 完成约 528 ms。
- classification 单节点平均约 34.5 ms，gateway 约 18.8 ms，daemon 约 9.9 ms，模型 infer 约 7.8 ms。
- 近期 Preview 的 72 次 classification 均成功，两个实例各处理相同数量；当前证据不能替代修改后的正式 Runtime、Trigger 和长期内存验收。

实现和验收必须保留原始运行数据、运行类型、样本数、warm/cold 状态和诊断开关，不能只记录一个总耗时。

## 实现与实际验收结果

2026-08-29 使用现有模型、两实例 OpenVINO CPU deployment、现场图片和正式 Workflow Runtime 完成验收。原应用保持不变，建立了两个独立副本：

| 用途 | 原应用 | 验证副本 | 发布版本 |
| --- | --- | --- | --- |
| 3570 治具空盘，24 项分类与 4 个圆定位 | `workflow-app-20260804015118` | `workflow-app-20260829184603` | Batch 并行验证 |
| 3570 塑盒满盘，80 项分类 | `workflow-app-20260804015507` | `workflow-app-20260829184604` | Batch 并行验证 |

实现结果：

- `Grayscale` 保留真实 `gray8/HW`；Hough Circles 的 `convert_roi_to_grayscale` 在面板中可见且默认启用，只转换解析后的 Search ROI，避免直接连接 BGR/BGRA 时失败。
- Hough Circles 已完成无共享可变状态审计并声明 `thread-safe`，但是否并行仍只由显式 `Parallel Start` / `Parallel End` 决定。
- `circles.v1` 已提升为核心公共 payload 合约，与 OpenCV 节点包共享完全一致的 schema；核心 typed bridge 不再依赖自定义包先加载。
- detection、classification、segmentation、pose、OBB 五类 Batch 节点、统一有序 Batch 信封、五类 Batch-to-value bridge 和对称 typed bridge 已实现。
- gateway、inference daemon、deployment worker 和 runtime pool 已实现单次 `infer_batch`。Batch 在整个调用中固定占用一个实例，按输入顺序执行；无实例时立即 busy，不等待、不排队、不重试、不拆批。
- Workflow memory 图片使用 LocalBuffer 批量控制操作分配和提交；结束时按本次节点 owner 一次释放，错误路径仍保留逐 lease 条件释放兜底。Batch JSON 不暴露临时 locator。

Hough 结果与性能：

- 对 9 张现场图片、4 个 ROI 共 36 个实际 case 比较 `maximum_candidates=40` 和 4/8/12/16。`16` 在 36/36 case 中与 `40` 的最终圆结果完全一致；因此只在验证副本中显式设置为 `16`，没有修改节点默认值 `40`。
- 同一张 5472×3648 图片上，Hough 显式 Parallel 的 `max_concurrency=1/2/4` 分别实测。并发 2 和 4 因 OpenCV/CPU/内存带宽竞争没有降低 wall time；最终应用明确保存 `max_concurrency=1`，仍保留显式 Parallel 边界，避免运行环境变化时改图结构。
- 原应用 Preview 的 graph/total 为 1778.081/2383.894 ms；验证副本相同最终参数的最佳 warm 数据为 1055.590/1187.341 ms，最终发布前复核为 1183.742/1305.530 ms。按最终复核计算分别降低约 33.4%/45.2%，圆心和半径保持一致。

Classification Batch 结果与性能：

- 24 项正式 Runtime 调试调用中，两路 12 项 Batch 分别固定命中 `instance-0` 和 `instance-1`，节点耗时 154.507/162.651 ms，daemon Batch 耗时 121.477/123.342 ms；输入暂存 18.816/21.352 ms，gateway 124.684/127.252 ms，释放 10.322/13.637 ms。
- 30 次连续正式同步 Workflow 调用为 30/30 成功，端到端 mean/min/P95/max 为 831.3/779.0/946.2/966.0 ms；每次 Workflow 内只有两路 Batch 并发，没有制造额外同步请求洪峰。
- 80 项应用在相同现场输入上的结果统计与原应用一致：`count=80`、`empty=16`、`full=0`、`abnormal=64`。原应用 Preview graph/total 为 1973.389/2554.580 ms；Batch 副本首次为 1340.314/1566.177 ms，最终 LocalBuffer 控制面优化后复核为 1238.820/1469.404 ms；正式 Runtime 单次端到端为 1185.6 ms。业务判定仍为原规则的 `ng`，本次优化没有改写标签和判定规则。

Trigger、LocalBuffer 与内存结果：

- 为 24 项副本创建并启用 `local-shared-memory-workflow-runtime-c9013239760d4eeca4f5b4f5db5a83d4`。仓库内 .NET Framework SDK 使用 59,885,622 字节 BMP 完成 warmup 2 次和正式 20 次调用，正式调用 20/20 成功；端到端 P50/P95 为 969.113/1080.357 ms，SDK 写 LocalBuffer 平均 4.393 ms。
- Trigger 结束后 mailbox `used_page_count=0`、`pending_request_count=0`、`active_task_count=0`；LocalBuffer `active_lease_count=0`、allocated/published/revoking/quarantined 均为 0，2 GiB arena 全部可用。
- 30 次正式 Runtime 调用后，24 项 Runtime Working Set 从 223.1 MiB 到 224.2 MiB，未持续单调增长。Trigger 调用后约增加一份 59 MiB 输入映射 Working Set，Private Bytes 只增加约 3.5 MiB；这是受限 mmap page residency，不是未释放 lease。
- 审计发现 inference daemon 被强制结束时 Windows 会留下 5 个 deployment 孤儿进程，额外占用约 3.9 GiB Working Set。deployment worker 已增加父进程 watchdog；真实故障注入中强制结束 daemon 后，5/5 子进程在 3 秒检查点前全部退出。
- daemon 重启后的第一个旧 epoch 同步调用明确失败且不重试；epoch 刷新后的 Trigger 连续调用全部成功。这是受控重启边界，不把失败隐藏成排队或自动重试。
- 完整 backend 冷重载后，两个 Batch 并行验证 Runtime 均自动恢复为 `running/running`；分别使用现场治具空盘和塑盒满盘 BMP 再执行一次同步调用，两次都为 `succeeded`。24 项输出仍为 `count=24/passed=true`；80 项输出仍保留原业务规则的统计和判定。
- 完成控制面内存修复并再次冷重载后，现场复核运行 `workflow-run-7c361566eb43464d9d2cac9054c44a37` 和 `workflow-run-344dc5e1f50b44faa4bc952b99e59dd0` 均为 `succeeded`。数据库时间戳计算的端到端 wall time 分别为 1019.764 ms 和 990.395 ms；结果仍为 24/24 empty/pass 和 80/80、16 empty、64 abnormal、业务 `ng`。
- 两个验证 Runtime 冷启动空闲时分别约 100 MiB RSS、78 MiB USS，执行现场大图后约 221 至 228 MiB RSS、195 至 197 MiB USS，均无 PyTorch 映射。开发库中另有 8 个 `desired_state=running` 的 Stage 9 benchmark Runtime，每个空闲约 77 至 78 MiB USS；这些是显式运行资源，不是重复恢复或 lease 泄漏，系统不会用隐藏的空闲休眠改变其状态。

### 2026-08-30 v4 复验与资源修复

本轮使用 `workflow-app-20260830050503` 的独立验证版本
`workflow-app-version-adee8f6b693e414496265f1589a15038`，正式 Runtime 为
`workflow-runtime-8c257afd0c144890a58592c8a15586e9`、generation 4。应用明确保存以下参数，不依赖隐藏默认行为：

- 四个 Hough Circles 的 `ROI Grayscale=true`，输入直接连接 BGR 图片引用；原整图 `Grayscale` 节点保留但显式禁用。
- Hough 的 `Parallel Start.max_concurrency=1`；两路 Classification Batch 的 `max_concurrency=2`。
- 删除节点时同步清理 `member_node_ids`；普通点击没有坐标变化时不重算分组成员，避免节点卡片尺寸变化导致 Parallel 分组静默漂移。

同一张 5472×3648 现场 BMP 的 Preview 实测如下：

| Hough 并行度 | 四个 Hough 节点耗时 | Parallel wall time | 结论 |
| --- | --- | --- | --- |
| 1 | 102.9 / 100.4 / 107.5 / 110.7 ms | 447.0 ms | 最稳定，作为 v4 正式参数 |
| 2 | 251.0 / 171.3 / 198.0 / 178.6 ms | 448.5 ms | 无 wall time 收益 |
| 4 | 736.4 / 741.1 / 670.7 / 747.2 ms | 775.1 ms | CPU 与内存带宽争用，明显更慢 |

因此没有为 Hough 增加节点内部线程池、自动并发或动态调度。当前机器和图片上的最简稳定实现就是显式 Parallel 边界加并行度 1；运行环境或 OpenCV 配置改变后必须重新实测，不能自动改成 2 或 4。

v4 正式 Runtime 顺序调用 100 次为 100/100 成功，数据库端到端
mean/min/max 为 615.8/571.0/859.0 ms。每次 Workflow 内两路 12 项
Classification Batch 并发调用两个 deployment instance，24 项结果持续为
`count=24`、`expected_count_matched=true`、`passed=true`、
`problem_count=0`。没有增加同步请求队列、等待、自动重试或额外并发压力。

同一 v4 Runtime 的 local-shared-memory Trigger 使用仓库 .NET Framework x64
SDK 和 59,885,622 字节 BMP 完成两轮各 100 次严格顺序 soak，两轮均为
100/100 成功。第一轮 latency mean/P50/P95/P99/min/max 为
820.873/810.414/972.551/1110.648/749.464/1284.114 ms；第二轮为
827.606/811.887/1000.053/1113.453/748.882/1250.473 ms。Trigger mailbox
在调用后保持 `pending_request_count=0`、`active_task_count=0`、
`used_page_count=0`，SDK 结果 `Dispose` 完成 ACK。
控制面只在 per-source 内存健康计数中同步更新 `last_triggered_at`，不为每次高速
Trigger 增加数据库写入。后端冷重载后的真实 encoded-file 调用成功，公开健康接口
返回非空最后触发时间；调用后 128 个 mailbox descriptor 全部空闲、512 个 page
全部可用，pending/active 均为 0。

资源审计还定位并修复了一个确定的 Windows 句柄保留问题：
`WorkflowRuntimeService._workflow_run_event_locks` 原来按每个历史 run id 永久保存
一把 `threading.Lock`。隔离进程中 5000 把锁精确增加 5000 个句柄，真实 backend
也表现为约每次 Workflow 增加 1 个句柄。锁表改为弱引用后，同一 run 的并发事件
写入仍共享同一把锁，最后一个写入者退出后锁自动释放，不改变执行、等待或调度语义。
冷重载后的第一轮 100 次从 1594 增至 1639 handles，同时工作线程从 103 增至
112，属于首次执行热身；第二轮再执行 100 次 handles 从 1639 降至 1638，Private
Bytes 从 1226.86 MiB 到 1226.89 MiB，不再按 run 线性增长。v4 worker 执行后约
130.8 MiB Private / 176.6 MiB Working Set，inference daemon 保持 499 handles / 571.29 MiB Private。

冷重载后的开发环境还完成了进程树口径复核。backend 树共 17 个进程，包括控制面、
LocalBuffer broker 和数据库中显式保持 running 的 Runtime，合计约 1861.2 MiB USS；
其中 v4 worker 约 87.8 MiB USS / 128.0 MiB Private / 174.8 MiB Working Set。
inference daemon 与 5 个 deployment worker 合计约 2687.4 MiB USS，Vite 开发进程约
152.0 MiB USS；三个开发进程树合计约 4700.6 MiB USS。Windows `Private Bytes`
会同时反映保留地址空间，RSS 求和也会重复计算共享 DLL 映射，因此容量审计以 USS、
进程数量和多轮趋势共同判断。该高基线来自显式运行配置，不按调用次数增长；生产配置
应停止不使用的 Runtime 和 deployment，不增加隐藏休眠或调用时冷启动。

## Hough Circles 输入处理设计

### 可见参数

新增以下参数，并同时进入 NodeDefinition 参数 schema、参数 UI schema 和 Debug Image Panel controls：

| 字段 | 面板名称 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `convert_roi_to_grayscale` | `ROI Grayscale` | `true` | 只对解析后的 Search ROI 执行 BGR/BGRA 到 Gray 转换；显式关闭时要求灰度输入 |

该参数属于 `Input Processing` 分组，不得只存在于后端参数或隐藏调试面板中。

### 关闭时的行为

- `gray8` 或解码后二维 `uint8` 输入直接进入 ROI、CLAHE、blur、Hough 和 refinement 链路。
- 默认配置接受 BGR/BGRA 输入并只转换 Search ROI；显式关闭 `ROI Grayscale` 时立即返回稳定参数错误并提示连接 `Grayscale`。
- 节点不得暗中选取单个通道、调用 `IMREAD_GRAYSCALE` 或复制整图。

### 开启时的行为

处理顺序固定为：

```text
image-ref.v1
  -> IMREAD_UNCHANGED / raw view
  -> resolve Search ROI
  -> crop view
  -> BGR/BGRA to Gray for ROI only
  -> optional CLAHE
  -> optional median blur
  -> HoughCircles
  -> radial samples / robust fitting
  -> add ROI offset
  -> circles.v1
```

- 输入本身已经是二维 gray8 时不重复转换。
- 未连接 ROI 且 `search_bbox_xyxy` 为空时，解析后的 Search ROI 是整图；Summary 和面板必须明确显示这一范围。
- 图片宽高和最终 circle 坐标继续使用原图坐标系。
- Debug Preview 可以使用原图绘制 overlay，但生产未启用 Debug Preview 时不得生成调试图片。

### Summary 与计时

Hough Summary 至少增加：

```json
{
  "input_pixel_format": "gray8",
  "roi_grayscale_requested": false,
  "roi_grayscale_applied": false,
  "grayscale_scope": "none",
  "grayscale_bbox_xyxy": [0, 0, 0, 0],
  "timings": {
    "image_load_ms": 0,
    "roi_resolve_ms": 0,
    "roi_grayscale_ms": 0,
    "hough_ms": 0,
    "candidate_refinement_ms": 0
  }
}
```

生产默认关闭详细 timing 时可以省略 `timings`，但灰度请求、实际执行状态和有效 Search ROI 仍应保留在节点 Summary 中。

## gray8 图片数据面

`image-ref.v1` 已有 `shape`、`dtype`、`layout` 和 `pixel_format` 字段；gray8 继续使用同一公开 payload，不新增 Hough 专用图片类型。

raw gray8 使用以下元数据：

```json
{
  "media_type": "image/raw",
  "pixel_format": "gray8",
  "dtype": "uint8",
  "layout": "HW",
  "shape": [3648, 5472],
  "width": 5472,
  "height": 3648
}
```

实现要求：

- `register_image_matrix` 保留二维连续 `uint8` matrix 为 gray8，不转换回 BGR24。
- execution image registry 的 memory fast path、LocalBuffer BufferRef 和通用 raw loader 都必须识别 gray8。
- gray8 字节长度必须等于 `width * height`。
- content hash 必须基于准确表示，不能让同样字节但不同 `shape/dtype/layout/pixel_format` 被错误复用。
- 默认要求彩色输入的旧节点继续显式请求 BGR，避免 gray8 改造使旧节点收到意外二维矩阵。
- `Grayscale` 读取输入时使用 unchanged 语义；输入已经是 gray8 且没有显式 `save_location` 时直接透传，不创建重复 image handle 或 LocalBuffer lease；显式保存时仍按保存契约写出文件。
- 5472×3648 的 gray8 主体约 20 MB；同尺寸 BGR24 约 60 MB。内存验收必须证明 Grayscale 后不再同时常驻一份由该输出产生的伪 BGR24 灰度图。

## Parallel 同类节点设计

### 当前能力和限制

现有执行器已经使用有界线程池执行显式 Parallel 分支，并按模板中的稳定分支顺序合并结果。是否能让同类节点同时执行，由 `NodeDefinition.concurrency_policy` 决定：

- `thread-safe`：同类型实例可以并发。
- `serialized`：默认值；同一 `node_type_id` 在一个 Workflow Run 内串行。
- `exclusive`：与其他 exclusive 节点互斥。
- `unsupported-in-parallel`：保存或执行前拒绝。

Hough Circles 已显式声明 `thread-safe`，但只有放入 `Parallel Start` / `Parallel End` 的不同分支后才可能并发；声明本身不会让普通 DAG 或同类节点自动并行。

### 选定方案

本阶段保留现有 `value.v1` Parallel 边界，不新增 graph control edge、动态端口或透明跨边界输出。原因是当前需求可以通过通用 bridge 完整表达，没有必要同时升级 WorkflowGraphEdge、编辑器连线和执行器格式。

补齐以下对称 bridge：

- `Value To Image Refs`
- `Value To Circles`
- `Value To Detections`
- `Value To Categories`
- `Value To Poses`
- `Value To OBBs`
- 已有 `Value To Segments` 继续使用

bridge 只校验并恢复强类型结构，不复制图片主体。所有可进入 `Payload To Value` 的正式结构化模型和视觉 payload 都应具有对称的恢复路径；新增 payload 时必须同步检查这一规则。

Hough Circles 只有在以下审计完成后才能改为 `thread-safe`：

- handler 没有模块级可变状态。
- Debug Preview artifact 注册、ExecutionImageRegistry 和 cleanup collection 可并发访问。
- 分支 timing、Summary 和 workflow metadata 不发生无锁共享写。
- OpenCV 全局线程数不在节点 handler 内动态修改。
- Preview 与正式 Runtime 的并发结果、失败 cleanup 和顺序一致。

### 四个 Hough 的通用图

```text
Image Ref(BGR/BGRA/gray8)
  -> Payload To Value
  -> Parallel Start(max_concurrency=N)
      |-- Value To Image Ref -> Hough ROI-1 -> Payload To Value --|
      |-- Value To Image Ref -> Hough ROI-2 -> Payload To Value --|
      |-- Value To Image Ref -> Hough ROI-3 -> Payload To Value --|
      `-- Value To Image Ref -> Hough ROI-4 -> Payload To Value --|
  -> Parallel End(mode=collect)
  -> Get List Item x 4
  -> Value To Circles x 4
  -> downstream typed nodes
```

四个 ROI 可以由 Parallel Start 之前已经完成的通用 ROI 节点提供。普通 Hough 节点不保存分支 id，不知道其他 Hough 是否存在。

四路 native/Python CPU 工作同时运行可能因 OpenCV 内部线程和内存带宽争用而变慢。v4 已实测 1、2、4，并按 wall time、资源占用和结果一致性选择 `max_concurrency=1`。后续只有在 CPU、OpenCV 配置或输入尺寸变化时才重新比较，不引入自动调参。

## 五类模型 Batch 节点

### 节点和端口

| Node type id | 显示名称 | 输入 | 强类型输出 |
| --- | --- | --- | --- |
| `core.model.detection-batch` | `Detection Batch` | `Images / image-refs.v1` | `Detections Batch / detections-batch.v1` |
| `core.model.classification-batch` | `Classification Batch` | `Images / image-refs.v1` | `Categories Batch / categories-batch.v1` |
| `core.model.segmentation-batch` | `Segmentation Batch` | `Images / image-refs.v1` | `Segments Batch / segments-batch.v1` |
| `core.model.pose-batch` | `Pose Batch` | `Images / image-refs.v1` | `Poses Batch / poses-batch.v1` |
| `core.model.obb-batch` | `OBB Batch` | `Images / image-refs.v1` | `OBBs Batch / obbs-batch.v1` |

各节点继续提供与对应单图节点一致的公共参数，例如 `deployment_instance_id`、score/mask/keypoint threshold、`top_k` 和 `extra_options`。第一版要求同一个 Batch 内使用同一 deployment 和同一组参数，不支持每项覆盖 deployment 或 threshold。

输入数量至少为 1。平台设置明确的 Batch item 上限并在调用前校验；超过上限直接报错，不自动拆成多个请求。

### 统一 Batch 信封

五个 payload 使用相同外层结构，`format_id`、`task_type` 和 `result_payload_type_id` 固定对应各自任务：

```json
{
  "format_id": "amvision.categories-batch.v1",
  "task_type": "classification",
  "result_payload_type_id": "categories.v1",
  "count": 12,
  "items": [
    {
      "item_index": 0,
      "item_id": "crop-1",
      "source": {
        "width": 320,
        "height": 320,
        "crop_index": 1,
        "bbox_xyxy": [0, 0, 320, 320],
        "content_sha256": "..."
      },
      "result": {
        "count": 5,
        "items": [],
        "top_item": {}
      }
    }
  ],
  "batch_latency_ms": 120,
  "metadata": {
    "deployment_instance_id": "...",
    "execution_mode": "sequential-reserved-instance"
  }
}
```

固定规则：

- `items` 与输入图片顺序一致，不按完成时间或 score 重排。
- `item_index` 从 0 开始；已有 `crop_index`、ROI id、bbox 等关联字段原样保留。
- `item_id` 优先使用输入显式 id，其次使用 `crop_index`，否则生成稳定的 `item-{index}`。
- `result` 必须是对应单项 payload contract 的有效对象。
- 外层 `source` 只保存非 locator 的关联信息。图片引用由原 `image-refs.v1` 链或独立 App output 继续传递。
- 第一版固定 fail-fast；任一项失败使 Batch 节点失败，并返回 `item_index`、`item_id` 和原始错误。不得返回未声明的半成功结构，也不得换实例重试。

### Batch 结果 bridge

新增以下 bridge，把有序 `items[*].result` 提取为 `value.v1` List：

- `Detections Batch To Value List`
- `Categories Batch To Value List`
- `Segments Batch To Value List`
- `Poses Batch To Value List`
- `OBBs Batch To Value List`

需要单项强类型结果时，继续使用通用 `Get List Item` 和 `Value To Detections/Categories/Segments/Poses/OBBs`。Batch 节点不重复输出一份 typed batch 和一份 value list，避免未连接时仍保留两份大型结构化结果。

## 同步 Batch runtime

### 请求边界

现有单图 `PublishedInferenceRequest.image_payload` 不能通过 Workflow 节点内循环解决 Batch 开销。新增独立 `PublishedInferenceBatchRequest` 和 gateway `infer_batch`，一次请求携带有序图片引用和一组公共推理参数。

执行顺序固定为：

1. Workflow Batch 节点校验全部 `image-refs.v1`。
2. 已是 BufferRef/FrameRef 的图片原样传递；execution memory 图片批量写入 LocalBuffer，并持有全部临时 lease。
3. gateway 发送一次 `infer_batch`。
4. deployment worker 使用非阻塞 `infer_slots.acquire(blocking=False)` 立即申请一个 slot。
5. runtime pool 只获取一次空闲且健康的实例。
6. 该实例按输入顺序处理全部图片。
7. gateway 一次返回有序结果。
8. `finally` 释放实例、reader guard 和全部临时 LocalBuffer lease。

第一版 `execution_mode` 固定为 `sequential-reserved-instance`。这不是模型 tensor native batch，而是把逐图 gateway 和实例生命周期合并。后续只有 runtime 明确声明兼容的动态 Batch capability 时，才允许增加显式 `native-batch` 模式；不能隐式改变精度、顺序或 engine profile。

### 容量语义

- Batch 开始时必须立即获得一个实例，并在整个 Batch 内保持占用。
- 无空闲实例时立即返回 `deployment_inference_busy`。
- 不等待另一个实例释放，不进入调度队列，不自动重试。
- 两个健康实例、两条同时开始的 Batch 分支且没有第三方调用占用时，两条分支必须各获得一个实例并全部成功。
- 存在第三方请求已经占满实例时，在禁止容量等待的前提下不能承诺本次 Workflow 仍成功；这属于明确的外部容量边界。

## 24 项 Classification 目标图

当前 Workflow 的通用替换结构为：

```text
Crop Export(image-refs.v1)
  -> Image Refs To Value List
  -> Split List(partition_count=2)
  -> Parallel Start(max_concurrency=2)
      |-- Get List Item(0)
      |     -> Value To Image Refs
      |     -> Classification Batch
      |     -> Categories Batch To Value List
      `-- Get List Item(1)
            -> Value To Image Refs
            -> Classification Batch
            -> Categories Batch To Value List
  -> Parallel End(mode=concat)
  -> Classification Results Summary
```

该结构只有两个模型节点、两次 gateway Batch 请求和两次实例获取。`Parallel End.concat` 按分支稳定顺序恢复 24 项结果。分类汇总继续消费现有单项 categories 对象，不需要当前 App 专用 Batch Summary。

按 daemon 单图约 9.9 ms 计算，每条 12 项分支的模型时间约 119 ms；两个实例并行时 Workflow wall time由较慢分支决定。目标是 warm p50 不高于 150 ms、warm p95 低于 200 ms。该目标必须由改造后的真实 Preview、正式 Runtime 和 Trigger 数据验证，不作为未测试的保证值。

## 实施顺序

1. 补齐 gray8 payload fields、matrix registry、memory/buffer raw loader 和回归测试。
2. 修改 Grayscale 的 gray8 输出和已灰度透传行为。
3. 修改 Hough Circles 的显式 ROI grayscale、面板、Summary 和阶段 timing。
4. 补齐 Value 与 image-refs、circles、五类模型结果的对称 bridge。
5. 审计并验证 Hough Circles `thread-safe`，再更新 NodeDefinition。
6. 新增 Batch request/result、gateway action、deployment worker action 和 runtime pool 的单实例 Batch 执行。
7. 基于同一共享实现注册五类 Batch 节点、五类 Batch payload 和五个 Batch To Value List bridge。
8. 将当前 24 classification 图迁移为两个 Batch 分支。
9. 执行 Preview、正式 Runtime、Trigger、LocalBuffer、长期 RSS 和错误恢复验收。

每一步完成后必须先核对公开契约、旧图兼容、错误 cleanup 和实际数据，再进入下一步。不得在 gray8、Parallel 或 Batch 尚未闭环时用当前 App 专用节点绕过缺口。

## 验收矩阵

### Hough 和 gray8

- 32 张现有图片、4 个 ROI、128 个 case 与当前结果对比。
- 对比 circle count、selected circle、圆心、半径、quality、rejection reason。
- `convert_roi_to_grayscale=false` 时彩色输入明确失败，gray8 输入不发生颜色转换。
- 默认 `convert_roi_to_grayscale=true` 时计时和内存证明确认只转换 Search ROI。
- 5472×3648 Grayscale 输出为约 20 MB gray8，不再注册约 60 MB BGR24。
- 1、2、4 路 Parallel 分别记录 p50、p95、CPU、Working Set-Private/USS 和结果一致性。

### Batch 正确性

- 五类 Batch 的每项结果与对应单图节点逐项比较。
- 输入顺序、`item_index`、`item_id`、`crop_index` 和 bbox 保持一致。
- Batch To Value List 后能接现有 For Each、regions、规则、汇总和输出节点。
- Batch JSON 不包含 memory handle、BufferRef、FrameRef 或 local path 等临时 locator。
- 任一项失败时 Batch fail-fast，错误定位到具体 item，实例和全部 lease 在 finally 释放。

### 两实例性能与稳定性

- 两个 classification Batch 每个 12 项，在两个健康实例上重复运行，成功率 100%。
- 两个实例的 inference counter 都增长，单次 Batch 内不在实例间迁移。
- warm p50 不高于 150 ms、warm p95 低于 200 ms；同时保留 gateway、daemon、infer 和节点阶段计时。
- 没有空闲实例时立即返回 busy，不观察到容量等待、排队或自动重试。
- 连续运行后 LocalBuffer active lease、active bytes 和 free extent 回到基线，无 orphan/revoking 增长。
- warmup 后 backend、Workflow worker、deployment worker 的 Private Bytes/USS 不持续单调增长；审计时区分文件映射 Working Set 与私有物理占用。

## 明确不做

- 不增加 Hough Batch、Tray Classification、24 Slot Classification 等应用专用节点。
- 不在 Hough、Classification 或其他普通节点上增加 parallel checkbox。
- 不自动识别 DAG 中的同类 sibling 并并行。
- 不把四个 ROI 固化进 Hough 参数。
- 不用降低 `maximum_candidates` 默认值掩盖整图灰度和 refinement 开销。
- 不让 Batch runtime 自动等待实例、排队、重试、拆批或并行轰击同一 deployment。
- 不把临时图片引用嵌入 Batch JSON 作为 Trigger 返回方式。
- 不因第一版 Batch 增加新的模型框架专用节点。

## 相关文档

- [Parallel 分支](parallel-branches.md)
- [节点系统](node-system.md)
- [Workflow JSON 规则](json-contracts.md)
- [Workflow Runtime](runtime.md)
- [高性能图片数据面](../platform/image-data-plane.md)
- [模型发布运行时配置](../models/deployment-runtime.md)
- [模型接入与工作流边界](../models/workflow-boundaries.md)
