# 模型转换执行与发布

> 当前状态：统一进程监督、可跨重启恢复的 Attempt 总 deadline、数据库 publication reservation、同文件系统原子 rename 和 rename 后 recovery 均已落地。任务状态与持续验证见 [Task 执行、暂停与终态](../platform/task-execution.md)。

模型转换由 conversion Worker Profile 执行。HTTP 请求在同一 Unit of Work 中创建 conversion 业务记录、正式 Task/Event 和 QueueOutboxMessage；Dispatcher 提交后再写队列。转换链固定为：

```text
Task/TaskAttempt
  → 受监督 attempt 进程树
  → attempt staging
  → 文件完整性门禁
  → 来源模型数值一致性门禁
  → OpenVINO/TensorRT runtime smoke
  → builds 目录原子发布
  → ModelBuild/ModelFile 单 UoW 批量登记
  → Task succeeded
```

## 进程与超时

- attempt 和 OpenVINO/TensorRT helper 的工作目录与 `PYTHONPATH` 均使用实际 `backend` 包的父目录，不按转换工具文件的目录深度推算。源码开发使用仓库代码根目录及当前 conda Python；发行包使用 `app/` 代码根目录及同目录 Bundled Python，不新增系统依赖。
- 受监督 attempt 子进程使用一个硬 deadline，不按单个转换步骤重新计时；父进程验证和发布使用同一剩余预算，持久 UTC deadline 支持 lease recovery 后继续计算，不能重置计时。
- Windows 先启动等待放行的 bootstrap，把 bootstrap 加入启用 kill-on-close 的 Job Object 后才允许真实 converter 启动；绑定失败时 converter 不会运行。POSIX 使用独立 process group。
- timeout 或协作取消先请求进程树退出，grace 到期后终止整个 Job/process group，并有界等待强制清理完成。
- stdout、stderr 持续排空；单个保留文件默认最多 16 MiB，内存 tail 默认各 64 KiB。文件到达上限或写入失败后仍继续 drain，避免 pipe 反压死锁，不使用 `capture_output` 聚合全部日志。
- 总 Attempt deadline 在首次 claim 时由不可变 Task spec 固化：基础预算 7200 秒，包含 TensorRT 时为 10800 秒；lease recovery 不重新计时。`helper_timeout_seconds` 只作为 helper 上限，实际时限始终取该上限与 Attempt 剩余预算的较小值。`termination_grace_seconds` 的模型默认值为 15 秒，仓库 `config/backend-worker.json` 显式配置为 5 秒；实际使用解析后的 Worker 配置。

## Staging 与发布门禁

每次 attempt 写入独立的 `attempts/<attempt-id>/staging`。只有下列条件全部成立时，`artifacts/builds` 才会通过同文件系统 rename 发布到任务最终目录：

- 请求的目标格式全部生成；
- 主文件和 OpenVINO XML/BIN 配对文件存在且非空；
- ONNX 来源数值摘要为 finite，并通过 allclose 或模型专用 accepted 容差；
- OpenVINO 模型能在 CPU runtime 完成一次推理，结果与来源 ONNX 一致；
- TensorRT 正式 engine 实际执行全部输出，并与同输入的来源 ONNX 通过数值门禁；只完成反序列化或创建 context 不算通过。RF-DETR 的 trtexec 路径遵守相同门禁。

### 类别映射与来源选择

转换、部署、推理和 workflow 使用同一 ModelVersion 的有序类别映射。`labels` 文件和 `metadata.category_names` 同时登记时必须逐项一致；缺少、空白、重复、非法类型或索引顺序冲突都在正式任务提交前拒绝。运行时快照的类别列表也使用相同校验，禁止静默过滤条目后错配模型输出索引。

类别内容规则由 `domain/datasets/category_names.py` 统一定义；导入发布版本、模型登记、运行时解析复用该规则。类别名称内的 ASCII 或 Unicode 换行分隔符在导入时拒绝，不能把一个类别写成标签文件的多行；前端转换选择遵守相同的单行约束。

前端的训练初始化选择和转换来源选择由各自的状态模块维护。转换来源直接绑定实际模型及版本，不依赖预训练目录是否存在，也不借用预训练模型身份显示训练产物。切换 Project 或任务类型会清空旧来源；过期请求结果不得写回新选择。

### 正式链路验收

`tests/integration/test_classification_conversion_publication_chain.py` 使用显式指定的真实 YOLO11 classification 训练版本，按 ONNX / ONNX-optimized / OpenVINO FP32、FP16 / TensorRT FP32、FP16 检查 API 提交、正式 worker、受监督转换子进程、文件发布、ModelBuild 登记、sync/async 独立部署进程、类别输出、workflow、reset 和 stop。每个目标会验证其全部已发布构建，不能只检查 runner 临时输出。

开发环境在激活 `amvision` 后通过环境变量 `AMVISION_CLASSIFICATION_SMOKE_MODEL_VERSION_ID` 指定现有训练版本，再显式运行该 integration 测试。源模型、checkpoint 和调试数据集只读，数据库、队列、对象存储、daemon 和 worker 在 `.tmp/` 中隔离；测试结束回收自己启动的进程并按项目约定清理临时文件。TensorRT 目标需要 CUDA GPU、驱动及项目配置的同版本 TensorRT wheel / DLL，不使用 `projectsrc/` 作为运行时依赖。

`tests/integration/test_classification_training_publication_chain.py` 补充训练前的验收：使用正式格式的确定性小数据集，经导入、导出，分别调用 YOLOv8 / YOLO11 / YOLO26 原生 full core 分类训练入口执行 2 个 epoch，再验证逐轮 validation、独立 test 和 evaluation、checkpoint/labels 登记、ONNX / OpenVINO / TensorRT FP32 转换、sync/async 常驻进程推理及 workflow。小数据集只用于执行链验证，不代表模型精度验收，也不替换模型实现。激活 `amvision` 后设置 `AMVISION_RUN_TRAINING_PUBLICATION_SMOKE=1`，运行该文件即可重复验收；未显式启用时跳过 GPU 集成测试。

#### 2026-10-12 本地验收记录

- 来源为 `model-version-208efe5760e7` 的真实 YOLO11 classification 训练 checkpoint；标签文件和版本元数据均包含同序的 3 个类别，原始训练输出保持不变。
- Windows 环境中 OpenVINO FP32、FP16 和 TensorRT FP32、FP16 的 4 个真实用例全部通过。每个用例同时验证 ONNX、ONNX-optimized 和请求目标的正式发布构建，并逐个执行 sync/async 常驻部署、推理、workflow、reset 和 stop。
- 转换摘要响应补全 `runtime_backend`、`runtime_precision` 后，再次运行 OpenVINO FP16 的正式链路，验证任务摘要与已登记 ModelBuild 完全一致。
- 后端相关回归 408 项通过；前端 160 个测试文件、658 项测试通过，类型检查和生产构建通过。模型/任务契约回归覆盖当前支持的 18 个组合；这不等于 18 个组合均完成真实硬件全链路验收，也不包含重新训练或 DDP 验收。
- 构建页面在桌面和窄屏下验证了来源选择、类别数量和表单版本身份。应用内浏览器的开发页面仍出现 HMR 反复重连，同端口原生 HMR 连接的 8 秒对照未断开；该浏览器连接问题不记为已解决，也不据此断言服务端已发生故障。

#### 2026-10-12 追加全链路复审

- 再次只读核对原训练版本 `model-version-208efe5760e7`：3 个类别、标签文件及顺序一致；五种任务类型的转换列表接口均返回成功。
- 导入边界复现了 COCO、YOLO 和 ImageNet 类别映射接受多行名称的问题，共 6 个失败用例。统一类别规则后，ASCII 和 Unicode 换行名称均在 DatasetVersion 发布前拒绝，训练登记、运行时与前端使用相同单行约束；正常数据的类别顺序不变。
- 新增三代分类真实全链路验收，发现 YOLOv8 最终训练报告遗漏 `implementation_mode`，已在其 core 执行结果中补齐并完成重训复验。三代均完成导入至三后端转换、常驻部署和 workflow；原始三分类版本另行通过 OpenVINO FP16、ONNX 和 ONNX-optimized 正式发布及 sync/async 推理复验。
- YOLOX 转换 API 测试曾同时启用后台和手动 Outbox 投递，后台先投递成功会使手动计数断言失败；现明确由测试手动驱动，保留投递数量及最终任务结果断言，生产队列行为不变。
- 修正后完整重跑相关后端回归：464 项通过；前端 160 个文件、668 项通过，类型检查、生产构建、ruff 和补丁格式检查通过。确认开发服务无活动任务、部署和流程后，通过正式服务接替入口加载修复，6 类 Worker 就绪，daemon 热路径探测及 API 检查通过。
- 本轮不包含全部 18 个模型任务组合的真实 GPU 全链路、所有 GPU/NPU 设备、长时间 soak 或 DDP；其他任务组合通过公共契约、worker 和运行时回归覆盖。RF-DETR ONNX 回归实际执行 full core 导出，但其 OpenVINO/TensorRT worker 单元用例使用构建替身，不能计作硬件验收。

失败和 timeout 不会发布 staging，也不会把半成品登记为 ModelBuild。

### 数值策略与观测边界

固定顺序输出使用原逐元素容差：fp32 为 `rtol=1e-3, atol=1e-4`，fp16 为 `rtol=2e-2, atol=5e-3`。OpenVINO 校验先核对输出数量，再按 ONNX 名称对应端口，不按编译后端口下标比较；CPU 转换验收显式使用 f32 计算，fp16 权重压缩仍由产物精度决定。TensorRT fp32 构建关闭 TF32，fp16 构建保留对应精度设置；构建精度的性能应按实际 engine 测量。

YOLO26 detection、segmentation、pose、obb 使用 `yolo26-topk-v3`：固定 anchor/class 顺序比较完整候选，再把同次观测执行的框、分数、类别及附加字段精确映射回候选，验证两阶段 TopK 的数量、唯一 anchor/class 对、排序及高分候选完整性。segmentation 的 proto 单独比较。相同 anchor 的不同类别可以同时选中。

跨后端候选使用原数值容差，同次执行的 Split/Gather/Concat 只复制元素，完整行映射与选择排序不使用模型容差。每个后端必须正确选取自身的最高分候选，不能借另一候选的跨后端误差放行漏选。近同分导致两个后端选中不同集合时，分别验证各自选择。候选分数最大绝对差仅保留为诊断信息；旧版 E/2E 放宽规则和只比较 score/class 的 detection 例外均已移除。

项目导出的 ONNX 通过 `amvision.yolo26.topk_validation.v2` 元数据记录内部候选张量映射。观测 ONNX/IR 仅在内存副本增加输出；TensorRT 额外构建内存中的候选观测 engine，同时执行原正式 engine。公开 ONNX、IR、engine 的输出布局不增加调试输出。映射缺失或观测失败会拒绝转换，不退回不完整的检查。

增加观测输出可能改变编译优化，观测 engine 不等同于正式 engine。候选与 processed 输出必须来自同一次观测调用，并按输出名称对应。PyTorch raw forward 的观测选择直接由其候选生成，另行检查公开 forward。每端还需通过正式/观测交接检查：正式结果自身精确满足观测候选的选择规则，或者正式结果与观测结果在原容差内逐实例完整对应（包括类别、框、分数和全部附加字段，不能重复占用）。proto 也必须对应。摘要通过 `public_observation_validation` 区分 `exact-candidate-selection` 与 `complete-output-equivalence`；后者证明输出数值等价，不声称读取了正式 engine 的内部候选。无法对应的近同分集合报告 `correspondence unverified` 并停止发布，不能据此断言模型本身损坏，也不能标记 accepted。图映射格式未变化，保留 v2 元数据键；验证策略版本单独升级。

这些检查仅发生在转换阶段，不加入部署逐帧推理、Broker 或 Trigger 热路径。历史模型仍按原公开格式加载，旧验证报告不会自动升级为新策略通过；需要重新验证的产物生成新的 build。

segmentation 的正式 proto 另行直接按原容差跨后端比较，记录 `public_auxiliary_validation`；正式/观测交接的多个容差不得累加后替代该检查。

## DB 登记与恢复

`/api/v1` 的 detection 和其他任务类型的转换详情与列表统一返回 `builds[].runtime_backend`、`builds[].runtime_precision`，来自正式 Task result 的构建摘要，必须与已登记 ModelBuild 一致，不从文件后缀或 precision 默认值推断。本次只增加响应字段，不改变数据库结构。

同一 conversion 的全部 ModelBuild 和 ModelFile 在一个 Unit of Work 中提交。任何一个目标登记失败时，整批 DB 记录回滚。

发布先通过 `begin_conversion_publication()` 为当前 Attempt 建立数据库 reservation。rename 前再次核验 fence、取消请求和总 deadline；取消与发布按 reservation 的 CAS 结果决定能否继续。数据库 publication 状态与磁盘 marker 是两组不同状态，不能混用。

`complete_conversion_publication()` 在一个 Unit of Work 中登记 ModelBuild/ModelFile、把 reservation 置为 `registered`、同时结束 Task/Attempt 并写唯一终态事件。转换成功使用这个专用提交入口；通用 finalizer 不能绕过 publication 登记直接标记成功。

文件原子发布和 DB 事务之间使用 attempt `publication.json` 记录恢复状态：

- `publishing`
- `published_pending_registration`
- `registered`
- `orphan_reclaimed`

Worker 启动时按 DB 真相执行一次恢复：已有 ModelBuild 时修复 marker；只有任务已进入 `failed`、`timed_out`、`cancelled` 或已删除、没有任何 DB build 且超过 grace 的目录才会被回收。仍在运行或状态不明确的记录只报告未解决，不做破坏性删除。

原子文件发布后、DB 登记或 Task 终态提交前发生崩溃时，恢复执行者从 publication 中读取固化的完整 run result，重新验证正式文件并登记或核对 ModelBuild/ModelFile，不重新运行模型转换。文件尚未发布时继续遵守原 Attempt deadline；文件已成功 rename 后以完成登记和一致性恢复为主，不因旧转换预算到期丢弃已发布产物。

Task 和 TaskAttempt 对整个 attempt 分别记录 `succeeded`、`failed` 或 `timed_out`；timeout 使用退出码 124。持久队列先以 `task_id + attempt_no` 领取 TaskAttempt，终态写入同时校验 worker id 与 heartbeat owner；同一 consumer id 重启也不能让旧执行者越过 fencing。失败和超时由统一 finalizer 收敛，成功由 publication 专用事务收敛；Queue ACK 丢失后的再次领取读取匹配持久终态，不重放转换业务。

## GPU 资源边界

包含 `tensorrt-engine` 或来源 runtime 明确使用 CUDA 的 Conversion attempt 获取 GPU `exclusive` lease。lease 在受监督 attempt 子进程启动前获得，并覆盖 staging 校验和原子发布；来源和目标都只使用 CPU 时不获取 GPU 锁。子进程的 `CUDA_VISIBLE_DEVICES` 使用 lease 解析出的原始 GPU UUID 或 MIG UUID，不使用 hash、带前缀的内部键或不稳定的 `cuda:n` 跨进程身份。可见设备缩减为单个 UUID 后，子进程来源 runtime 统一使用 `cuda:0`。

共享目录、busy/timeout 策略、Deployment shared reservation 和崩溃释放规则见 [GPU 设备资源协调](device-resource-coordination.md)。
