# 模型转换执行与发布

> 当前状态：本页描述已经落地的 Conversion 执行与发布基础。可跨重启恢复的总 deadline、统一进程监督层、publication commit fence 和 rename 后恢复规则已由 [ADR-0006](../../decisions/ADR-0006-task-execution-and-runtime-reliability.md) 接受，但尚未完整实现；详细步骤见 [任务执行与运行时可靠性实施基线](../../development/task-runtime-reliability-implementation.md)。下文“整个 attempt 硬 deadline”目前主要由受监督子进程保证，不能解读为父进程发布边界已经完成同等治理。

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

- 受监督 attempt 子进程使用一个硬 deadline，不按单个转换步骤重新计时；父进程验证、发布和跨恢复剩余预算仍按上述实施基线收敛。
- Windows 使用 Job Object，POSIX 使用独立 process group；timeout 会终止完整子孙进程树。
- stdout、stderr 持续排空到 attempt 日志，只在内存保留有界 tail，不使用 `capture_output` 聚合全部日志。
- `attempt_timeout_seconds`、`helper_timeout_seconds` 和 `termination_grace_seconds` 是 backend-worker 私有初始值，可通过本地配置或环境变量覆盖，不进入公开转换 API。

## Staging 与发布门禁

每次 attempt 写入独立的 `attempts/<attempt-id>/staging`。只有下列条件全部成立时，`artifacts/builds` 才会通过同文件系统 rename 发布到任务最终目录：

- 请求的目标格式全部生成；
- 主文件和 OpenVINO XML/BIN 配对文件存在且非空；
- ONNX 来源数值摘要为 finite，并通过 allclose 或模型专用 accepted 容差；
- OpenVINO 模型能在 CPU runtime 完成一次推理，结果与来源 ONNX 一致；
- TensorRT engine 能反序列化并创建 execution context；RF-DETR trtexec 路径实际加载并执行 engine。

失败和 timeout 不会发布 staging，也不会把半成品登记为 ModelBuild。

## DB 登记与恢复

同一 conversion 的全部 ModelBuild 和 ModelFile 在一个 Unit of Work 中提交。任何一个目标登记失败时，整批 DB 记录回滚。

文件原子发布和 DB 事务之间使用 attempt `publication.json` 记录恢复状态：

- `publishing`
- `published_pending_registration`
- `registered`
- `orphan_reclaimed`

Worker 启动时按 DB 真相执行一次恢复：已有 ModelBuild 时修复 marker；只有任务已进入 `failed`、`timed_out`、`cancelled` 或已删除、没有任何 DB build 且超过 grace 的目录才会被回收。仍在运行或状态不明确的记录只报告未解决，不做破坏性删除。

原子文件发布后、DB 登记或 Task 终态提交前发生崩溃时，恢复执行者从 publication 中读取固化的完整 run result，重新验证正式文件并登记或核对 ModelBuild/ModelFile，不重新运行模型转换。

Task 和 TaskAttempt 对整个 attempt 分别记录 `succeeded`、`failed` 或 `timed_out`；timeout 使用退出码 124。持久队列先以 `task_id + attempt_no` 领取 TaskAttempt，终态写入同时校验 worker id 与 heartbeat owner；同一 consumer id 重启也不能让旧执行者越过 fencing。Task 业务终态先落库，随后 Attempt 终态 CAS，双向崩溃窗口由 finalization recovery 收敛。

## GPU 资源边界

包含 `tensorrt-engine` 或来源 runtime 明确使用 CUDA 的 Conversion attempt 获取 GPU `exclusive` lease。lease 在受监督 attempt 子进程启动前获得，并覆盖 staging 校验和原子发布；来源和目标都只使用 CPU 时不获取 GPU 锁。子进程的 `CUDA_VISIBLE_DEVICES` 使用 lease 解析出的原始 GPU UUID 或 MIG UUID，不使用 hash、带前缀的内部键或不稳定的 `cuda:n` 跨进程身份。可见设备缩减为单个 UUID 后，子进程来源 runtime 统一使用 `cuda:0`。

共享目录、busy/timeout 策略、Deployment shared reservation 和崩溃释放规则见 [GPU 设备资源协调](device-resource-coordination.md)。
