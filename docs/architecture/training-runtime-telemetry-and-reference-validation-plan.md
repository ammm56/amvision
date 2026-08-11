# 训练运行时、实时指标与参考实现验收方案

## 目的

本文定义 YOLOX、YOLOv8、YOLO11、YOLO26 和 RF-DETR 的训练运行时重构、
实时指标协议、数据集基线及真实训练验收规则。目标是消除模型任务之间重复且不一致
的训练控制代码，使准确率、资源利用率、checkpoint 恢复和页面展示都可以复现、
比较和审计。

当前仍处于 v1 开发阶段。本方案直接替换旧训练参数和旧执行协议，不增加迁移层，
不保留已经确认无效的字段或兼容分支。

## 已确认的事实

### Pose 核心实现

- YOLOv8、YOLO11、YOLO26 Pose 的模型结构、固定输入 forward 和核心 loss 已与
  `projectsrc/ultralytics` 参考快照完成数值比较。
- 17 点预训练 checkpoint 的三组参考回归通过；另以 21 点、单类别、nano 随机
  初始化模型核对，raw head 输出最大绝对误差不超过 `4.2e-6`，total loss
  最大绝对误差不超过 `5.8e-6`。
- YOLO26 Pose 的 one-to-many 和 one-to-one 分支均已进入训练 loss。历史 200 轮
  任务不能解释为“只训练了 one-to-many 分支”。
- 当前证据只证明模型图和单步 loss 一致，尚不能代替数据增强、优化器时间序列、
  完整数据读取、长训练收敛和吞吐量验收。

### 历史 hand-keypoints 任务

历史任务使用的不是官方全量配置，而是：

- `hand-keypoints-clean-v1`，train/val/test 为 `2048/256/256`
- 每个 split 最多取 512 张
- nano、`384x384`、固定 batch 32、FP16
- validation 间隔 20 轮
- 21 点 head 不能加载 17 点预训练 head，只能 warm start 可兼容的 backbone、neck
  和 detection 参数

因此该任务的 AP 不能与官方全量 `640x640`、不同初始化或不同 scale 的结果直接
比较。后续准确率结论必须来自同数据、同初始化、同输入、同增强、同 batch 和同
评估 split 的受控 A/B。

### hand-keypoints 数据

原始目录包含 18,776 张 train 和 7,992 张 val。它是 Ultralytics 官方数据，
但参考 verifier 与平台严格校验的接受边界不同：参考 verifier 对归一化坐标保留
约 1% 容差并忽略越界样本；平台工业数据规则不应静默保留越界标注。现有派生集
还删除了重复图并修复了 bbox/关键点，且只保留较小子集。

后续保留原始目录不变，并生成两类可追溯 DatasetVersion：

1. `reference-parity`：同一确定性文件列表同时供参考实现和项目实现使用，只用于
   定位实现差异。
2. `strict-production`：拒绝或显式修复越界标注、移除跨 split 重复，生成独立 test，
   输出逐样本修复与剔除报告，用于平台最终验收。

两类数据不得混在同一准确率表中。

`strict-production` 全量派生集现已生成到 `hand-keypoints-full-v1`：train 18,724、
validation 3,977、test 3,976，共 26,677 张；91 个 SHA-256 重复项已移除，
3,349 个越界 bbox 和 1,548 个越界可见关键点已按显式规则修复，专项审计无 error。
原 `hand-keypoints-clean-v1` 仍只用于 smoke。

### VOC2012 实例分割

原始 `VOC2012` 目录包含：

- 17,125 张 JPEG 和 17,125 个 XML
- 2,913 张 `SegmentationClass` 与 2,913 张 `SegmentationObject`
- segmentation train/val 为 1,464/1,449，二者无交集
- 6,934 个实例 id；背景为 0，void/boundary 为 255

6,934 个实例都可以从 `SegmentationObject` 得到实例 mask，并从同位置的
`SegmentationClass` 像素得到唯一类别。正式解析器对 segmentation split 的 2,913
张图片完成全量审计：20 个类别、6,934 个 mask 实例均可解析；XML/mask 对照产生
22 条警告，涉及官方数据中的 8 张图片。mask bbox 与 XML bbox 并不总是高 IoU，
XML 对象数和类别也并非逐图严格等于 mask，不能把 XML 当作实例事实来源，也不能
仅用固定 IoU 阈值丢弃小目标。

`data/files/datasets/segmentation/voc2012` 已补齐 segmentation split 对应的 2,913
个 XML 和平台全量审计 manifest；图片与两个 indexed mask 均逐字节核对官方源目录，
维护脚本不会修改官方源数据。

## 目标架构

### 共享训练引擎

新增统一 `TrainingEngine`，负责所有模型共有的运行语义：

- 设备选择、AutoBatch、AMP、随机种子和 DataLoader 生命周期
- warm start、resume、EMA、optimizer、scheduler 和梯度累计
- batch/epoch/validation 控制点与暂停、终止、手动保存
- checkpoint 策略、best 指标策略和训练产物登记
- 标准化遥测、有限数校验、OOM 重试和资源摘要

模型实现只通过 adapter 提供以下能力：

- `build_model`
- `build_train_batch`
- `forward_loss`
- `validate`
- `checkpoint_state`
- `metric_schema`

YOLO family 和 task 的差异继续保留在 core adapter 中；训练生命周期不再复制到
每个 trainer。RF-DETR 的 Lightning callback 接入同一个控制和遥测边界，模型
内部 checkpoint 格式仍由 RF-DETR adapter 负责。

### 公开运行参数

旧的顶层 `batch_size` 和 `precision` 由明确策略替换：

```text
runtime:
  device: auto | cpu | cuda | cuda:N
  batch:
    mode: auto | fixed
    size: integer                 # fixed 时必填
    target_memory_fraction: 0.60 # auto 默认值
    min_size: 1
    max_size: optional
  amp:
    mode: auto | enabled | disabled
    dtype: auto | fp16 | bf16
  dataloader:
    workers: auto | integer
    prefetch_factor: 2
    pin_memory: auto | enabled | disabled
    persistent_workers: auto | enabled | disabled
checkpoint:
  interval_epochs: 5
  keep_periodic: 2
validation:
  interval_epochs: 5
```

页面默认选择 AutoBatch 和 AMP 自动模式，并明确展示最终解析出的 batch、AMP dtype、
梯度累计数、worker 数和目标显存比例。CPU 自动关闭 AMP；CUDA 自动模式先执行
有限的数值能力检查，再选择可用 dtype。开发正确性矩阵固定
`initialization=random`，不自动选择预训练模型；预训练 warm start 只作为显式的
独立生产训练选项。

### AutoBatch

AutoBatch 不能只按空模型 forward 估算。probe 必须包含当前 task 的 forward、loss
和 backward，并使用真实输入尺寸与具有代表性的目标密度：

1. 从训练 split 选择目标数量或 mask 面积接近 P90 的样本。
2. 从小 batch 开始指数增长，OOM 后在安全区间二分搜索。
3. 保留目标显存余量，默认只使用约 60% 总显存。
4. 清理 probe 梯度、optimizer 临时状态和 CUDA cache，重新构建正式训练状态。
5. 第一轮单卡训练最多允许三次 OOM 降 batch 重试；每次重建 DataLoader、
   optimizer、scheduler 和梯度累计状态。
6. 记录 probe 过程、最终 batch、峰值显存和降级原因。

吞吐优化同时覆盖 Windows worker spawn、pinned memory、persistent worker、预取和
validation batch；不能只增大模型 batch 后继续让单样本 validation 长时间占用 GPU。

### Checkpoint 策略

训练引擎只在以下条件构建和写入 checkpoint：

- 完成 `interval_epochs`，默认每 5 轮
- 有效 validation 指标严格改善，需要写 best
- 训练完成
- 暂停、终止或手动保存控制点
- 即将传播不可恢复异常且模型状态仍为有限值

每轮仍更新内存中的轻量训练状态，但不序列化完整模型。best 比较拒绝负数、NaN、
Inf，平值不覆盖已有 best。写入采用同目录临时文件、flush/fsync、原子 replace，
完成后登记大小、SHA-256、epoch、global step、代码版本和数据版本。执行层传递
checkpoint artifact 引用，不再长期持有和复制大块 `bytes`。

latest 与 best 分离：latest 用于恢复，best 用于最终 test 和模型登记。定期 latest
按保留数量回收；best 历史至少保留当前 best 和前一个 best，直到任务成功登记。

### 标准训练遥测

高频 batch 数据不写入任务事件表。独立训练 worker 先写入每个 worker 一个的有界
mmap ring，backend-service 接收后再进入进程内有界 broker；内嵌 worker 直接进入
同一 broker。`training.telemetry.v1` WebSocket 提供带游标的重放与重连，epoch 和
validation 快照仍持久化到指标文件。mmap ring 使用 generation、sequence 与 CRC
拒绝跨进程 torn payload，不为每个 batch 写 SQLite 或创建普通事件文件。

公共字段至少包括：

- `task_id / attempt_id / sequence / timestamp`
- `stage` 与 `granularity=batch|epoch|validation|runtime`
- 一基 `epoch`、零基 `epoch_index`、`step/steps_per_epoch/global_step`
- task 专属 loss 分量、epoch 加权均值和 batch EMA
- learning rate、optimizer step、AMP skipped step、梯度累计
- images/s、ETA、data/forward/backward/optimizer 时间
- GPU utilization、allocated/reserved/peak memory、CPU 与进程内存
- requested/resolved batch、AMP、device、worker 配置
- task 专属 validation 指标和 best 状态

每个 batch 的原始 loss 允许波动。页面必须分别标记 raw batch、EMA 和完整 epoch
加权均值，不能把 batch 快照当作 epoch 收敛曲线。worker 对高频事件节流和合并，
浏览器只保留有界 ring buffer；断线后从 cursor 恢复，缺口过大时读取一次 REST
snapshot。

### Vue 与 ECharts

`TrainingTaskDetailPage` 在挂载时订阅训练遥测，在任务结束或页面卸载时释放连接。
REST 仅负责首次快照、重连缺口和最终文件刷新，不再要求手动刷新页面。

ECharts 使用模块化按需导入，并将图表组件异步分包：

- train loss：task 专属分量、batch EMA、epoch mean
- validation：classification top-k、detection bbox AP、segmentation bbox/mask AP、
  pose OKS AP、OBB rotated AP
- learning rate
- throughput 与 data/compute 时间
- GPU utilization 与显存

长任务按像素宽度或 LTTB 下采样，不向 ECharts 传递无界点集。任务能力 schema
决定可见系列，不能在 Vue 页面通过模型名堆叠条件分支。

## VOC instance segmentation 导入与转换

新增 `voc-instance-seg-v1` 导入器，识别直接 VOC 根、`VOC2007`、`VOC2012` 和
`VOCdevkit/VOC20xx` 包装层。标准输入包含：

```text
VOC2012/
├─ Annotations/
├─ JPEGImages/
├─ SegmentationClass/
├─ SegmentationObject/
└─ ImageSets/Segmentation/
```

转换规则：

1. `SegmentationObject` 的非 0/255 id 定义实例像素。
2. 同一实例像素在 `SegmentationClass` 中的有效类别必须唯一；背景和 void 不参与。
3. canonical bbox 和 area 从实例 mask 计算，不用 XML bbox 覆盖 mask 几何。
4. XML 只用于同类最大总 IoU 二分匹配，并补充 `difficult/truncated/pose` 等元数据；
   不因小目标 bbox IoU 低而直接丢弃，也不覆盖 mask 类别和几何。
5. XML 数量、类别和对象匹配差异产生结构化 warning，mask 仍完整导入；多类像素、
   尺寸不一致、空 mask、无法解析的自定义类别和 split 冲突才产生结构化 error。
6. canonical segmentation 优先存 compressed COCO RLE，保留孔洞和不连通区域。
7. COCO instance export 保持无损；YOLO polygon export 只有在轮廓往返面积和 IoU
   达到阈值时允许，否则明确拒绝该样本或整个导出，禁止静默丢孔洞。

原始 VOC2012 没有带标注的 test。平台开发基准以确定性 hash 将官方 val 再划分为
validation/test，并记录派生规则；官方 train 不参与最终 test。

## 当前实现状态（2026-08-10）

已经完成的 v1 基础能力：

- 训练创建 API 已统一使用 `execution.batch`、`execution.amp`、
  `execution.checkpoint` 和 `execution.validation`，旧顶层执行参数已删除。
- YOLOX、YOLOv8、YOLO11、YOLO26 与 RF-DETR 已接入共享 BatchPolicy、
  AmpPolicy 和 CheckpointPolicy；CUDA AMP 保留 FP32 主权重，checkpoint 默认间隔和
  validation 默认间隔均为 5 轮。
- 所有正式训练入口已接入共享 `TrainingEngine shared-v1`。自动 batch 在首个已完成
  epoch 之前发生 CUDA OOM 时按上限二分降级，清理异常 traceback 对 Tensor 的引用，
  并从原始不可变请求重建 model、optimizer、scheduler 和 DataLoader；fixed batch、
  resume 和首轮之后的 OOM 不做隐式改参。
- 训练详情页在原 `/models/:taskType/training-tasks/:taskId` 页面内，通过
  `tasks.events` 合并持久化 epoch/validation，通过 `training.telemetry.v1` 合并瞬时
  batch 指标，并用异步加载的 ECharts 展示训练、验证和 learning rate 历史；初始
  和断线缺口仍以 REST snapshot 补齐，不需要进入独立图表页面或手动刷新。
- YOLOX、YOLOv8/11/26 detection、三代 YOLO 的 classification/segmentation/pose/OBB
  以及 RF-DETR detection/segmentation 均已接入 batch 遥测。YOLOv8 OBB 历史上把
  batch progress 错送到 epoch callback 的路径已删除，batch 不再写 TaskEvent 或
  epoch 指标文件。
- 标准独立 worker 已通过每 worker 有界 mmap ring 接入 backend-service broker；
  producer 正常退出和异常退出均可由 receiver 回收，Windows 进程存活检查使用只读
  Win32 handle，不发送 signal。
- runtime 遥测已包含实际 batch 与解析模式、OOM 恢复次数、全程/epoch/batch 耗时、
  step/s、近似 sample/s、ETA、CUDA allocated/reserved/peak/free/total memory 和 GPU
  utilization。YOLOX 和三代 YOLO 的训练主循环还记录 forward+loss、
  backward+optimizer 与 batch compute 的低开销 host wall-time，不为遥测强制同步
  CUDA。训练详情页已增加吞吐/batch time、阶段耗时与 GPU/显存 ECharts，采样状态
  按 task 有界保留且非有限值不会进入协议。
- 三代 YOLO 的 classification、detection、segmentation、pose、OBB 以及 RF-DETR
  detection/segmentation 的训练结果均由 TrainingEngine 写入真实运行快照；训练摘要
  以最终解析出的 batch、AMP dtype 和 device 为准，并单独保留请求配置，不能再用
  API 默认值冒充实际运行值。RF-DETR 模型版本的 runtime metadata 也不再硬编码 CPU。
- segmentation、pose、OBB validation 已统一使用训练期最终解析出的 batch：一次
  batched GPU forward 后按图片切分 output/target 并分配连续 image id，再执行逐图
  后处理与 COCO/OKS/rotated evaluator。output 首维与 target 数不一致时立即失败；
  classification 和 detection evaluator 同样显式关闭 DataLoader，防止 persistent
  worker 在周期验证中泄漏。
- 姿态训练期指标已拆为 bbox `map50/map50_95` 与关键点
  `oks_ap50/oks_ap50_95`；best checkpoint 明确按有效 `val_oks_ap50_95` 比较，
  数据集级评估报告也同时输出 bbox AP 和 OKS AP。
- best 比较会拒绝负数、NaN 和 Inf，平值不覆盖；暂停、终止、手动保存、周期、
  best 改善和最终轮均进入统一 checkpoint 决策。
- `voc-instance-seg-v1` 已完成导入、导出和格式注册；canonical annotation 使用
  compressed COCO RLE，VOC 往返测试保持实例像素、类别和 split 一致。
- VOC2012 官方 segmentation split 已完成 2,913 个样本、6,934 个 mask 实例的全量
  审计，开发副本已补齐 XML 和审计 manifest；22 条官方 XML/mask 差异作为警告保留。
- 真实隔离门禁 `gate-yolov8-auto-batch-20260810` 已完成 CUDA AutoBatch、AMP、训练、
  独立评估、ONNX/OpenVINO/TensorRT、三产物独立加载和 sync/async 推理；4 张训练样本
  自动解析实际 batch=4。门禁同时发现并修复 detection 一基循环被二次加一的问题，
  `gate-yolov8-epoch-contract-20260810` 的训练/验证产物已核对为
  `epoch=1`、`epoch_index=0`、`evaluated_epochs=[1]`。
- 真实隔离门禁 `gate-runtime-summary-20260810` 使用 YOLOv8m Pose、640 输入和
  `hand-keypoints-full-v1` 的 128 张/split 完成训练、val、独立 test 与 ONNX 转换。
  AutoBatch 实际解析为 46，AMP 实际为 FP16，训练摘要与 metrics runtime 均记录
  `cuda:0`；val/test 各输出 `128 × 300 = 38,400` 条逐图预测，验证了批量前向、
  output 切片和 image id 对齐。该门禁只有 1 轮且随机初始化，AP=0 只作为链路证据，
  不作为准确率结论。

尚未完成、不得标记为工业验收通过的部分：

- TrainingEngine 的 adapter 边界仍需继续收敛；checkpoint 仍需完成以 artifact 引用
  代替大块 bytes、fsync/原子 replace、best 历史和 periodic 保留回收。
- runtime 已有总体、epoch、batch 以及 YOLO 主循环的 forward/backward host 分段；
  data loading、独立 optimizer 阶段、RF-DETR Lightning 内部细分和 CPU/进程内存
  尚未完成。
- hand-keypoints/VOC2012 的参考 A/B、100/200 轮训练、三种转换和 sync/async 推理
  验收矩阵。

2026-08-10 曾用 `hand-keypoints-clean-v1` 启动 YOLOv8m/640 的 100 轮诊断任务，
在第 63 轮正式暂停。第 50 轮 OKS AP50/AP50-95 为 0.245882/0.085204；对该 best
checkpoint 的独立诊断显示 bbox 定位明显好于关键点 OKS。由于该任务仍使用 2,560 张
smoke 子集，它只能暴露指标和数据选择问题，不能作为官方全量准确率验收。对应长训练
不会续跑；后续矩阵通过 `--dataset-dir data/files/datasets/pose/hand-keypoints-full-v1`
显式选择全量规范集。

因此当前页面已具备 epoch 历史、batch 瞬时数据和 GPU/吞吐资源遥测，训练入口也已
统一获得首轮 OOM 恢复语义；原子 checkpoint artifact、剩余阶段计时和真实长训练
完成前，仍不能给出工业准确率或吞吐结论。

## 实施顺序

### P0：冻结数值基线

1. 把 21 点 Pose forward/loss 数值比较固化为自动化测试。
2. 增加固定随机种子的预处理、mosaic/affine/flip、optimizer/warmup/scheduler、EMA
   时间序列参考测试。
3. 修正与当前 Ultralytics 8.4.47 不一致的 warmup iteration 与边界 step 语义。
4. 生成 hand-keypoints 的 reference-parity 和 strict-production 数据版本及报告。

### P0：共享训练运行时

1. 引入 `TrainingEngine` 与 family/task adapter。
2. 一次性替换旧 batch/precision 参数为 BatchPolicy、AmpPolicy、CheckpointPolicy
   和 ValidationPolicy。
3. 接通 AutoBatch、AMP 能力检查、OOM 降级、统一 checkpoint 和控制点。
4. 删除各训练器每轮序列化 checkpoint 的旧实现。
5. 覆盖 YOLOX detection、YOLO 三 family 的五类任务和 RF-DETR detection/
   segmentation。

### P0：实时训练数据

1. 定义并测试 `training.telemetry.v1`。
2. worker 发布 batch/runtime，服务持久化 epoch/validation snapshot。
3. 前端接入 WebSocket、游标重连和任务状态合并。
4. 增加按任务能力生成的 ECharts 图表与资源面板。

### P1：VOC2012

已完成 scanner/parser/validator、标准 VOC 开发副本、compressed COCO RLE canonical
表示、VOC indexed mask 往返导出以及 6,934 个实例的全量审计。COCO 导出沿用无损
RLE；YOLO polygon 仍必须通过现有可表达性门禁，不能表达孔洞、RLE 或多独立 polygon
的样本会明确拒绝，不能把有损近似作为“已转换成功”。

### P1：真实训练与全链验收

按以下顺序执行，前一层失败时停止后续长训练：

1. 1 batch：forward/loss/gradient 数值比较。
2. 5 轮：数据、AMP、AutoBatch、checkpoint、暂停/恢复和 WebSocket smoke。
3. 20 轮：loss、吞吐、显存和 validation 趋势门禁。
4. 100 轮：项目实现与参考实现同配置 A/B。
5. 200 轮：通过门禁后的最终训练、best test、三种转换、加载、sync/async 推理。

Pose 矩阵为 YOLOv8/YOLO11/YOLO26 × hand-keypoints；VOC instance segmentation
矩阵为 YOLOv8/YOLO11/YOLO26/RF-DETR × VOC2012。正确性矩阵全部使用随机初始化，
预训练结果单独记录，不能混入实现正确性结论。

## 验收门槛

- 同 checkpoint/随机权重的 core forward/loss/gradient 在既定浮点容差内通过。
- 同数据同配置 100/200 轮项目指标不得低于参考实现超过绝对 0.02 或相对 5%，
  取更严格者；未获得参考基线前不预设虚假的绝对 AP 承诺。
- 最终指标只来自 best checkpoint 和独立 test，不用 validation 冒充 test。
- 训练过程中不存在非有限 loss、gradient、metric 或被污染 checkpoint。
- CUDA 稳态显存满足目标比例；吞吐不低于同硬件参考实现的 85%。低于门槛时必须
  由 data/compute/IO 分段计时定位，不以单次 `nvidia-smi` 截图判断。
- 默认 200 轮 periodic latest 写盘次数不超过 40 次，另计严格改善的 best、手动
  保存和控制点保存。
- 暂停/终止在一个 batch 边界内响应，并生成可恢复的原子 checkpoint。
- WebSocket 重连不重复、不丢失 epoch 指标；高频 batch 数据不造成数据库和浏览器
  内存无界增长。
- 每个最终模型都完成 ONNX、OpenVINO、TensorRT 转换、独立加载、sync/async
  一次推理和与 PyTorch 输出的数值摘要比较。
