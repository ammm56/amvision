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
