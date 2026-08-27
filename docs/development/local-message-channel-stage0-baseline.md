# LocalMessage Channel 阶段 0 基线

## 状态

- 结论：阶段 0 通过，三个稳定默认 profile 已冻结
- 运行行为：未改变 composition root、正式配置、业务 transport 或正式 mmap 文件
- 原始报告：`.tmp/local-message-channel-stage0/baseline.json`
- 原始报告 SHA-256：`f98c11c3445b525c734ecbe4d09fb845f212d269a76caac68520647d8bd69271`
- 可提交证据：[local_message_channel_profiles.v1.fixture.json](../../tests/fixtures/local_message_channel_profiles.v1.fixture.json)

原始报告包含本机绝对路径和完整逐轮资源数据，因此保留在被 Git 忽略的 `.tmp/`。可提交 fixture 只保留 profile 裁决所需的长度、延迟、容量拒绝和最终常量，不复制业务 JSON。

## 复现命令

```powershell
conda activate amvision
python tests/integration/local_message_channel_stage0_benchmark.py `
  --output .tmp/local-message-channel-stage0/baseline.json `
  --rounds 5 `
  --warmup-iterations 10 `
  --inline-iterations 30 `
  --large-iterations 3 `
  --telemetry-iterations 30
```

工具只在 `.tmp/local-message-stage0-*` 中创建隔离文件。每个 suite 完成后更新显式 `.partial.json`，所有 suite 成功后才原子发布正式 `baseline.json`。

如 codec 或单项测量实现发生变化，可以按原 settings 只重跑对应 suite：

```powershell
python tests/integration/local_message_channel_stage0_benchmark.py `
  --output .tmp/local-message-channel-stage0/baseline.json `
  --refresh-suite queue
```

## 测量环境

| 项目 | 值 |
| --- | --- |
| 系统 | Windows 11 AMD64 |
| CPU | 8 physical / 16 logical cores |
| 内存 | 42,507,214,848 bytes |
| Python | 3.12.13, conda `amvision` |
| 电源策略 | 高性能 |
| multiprocessing | spawn |
| 基线提交 | `1e5bfb62a65c80377b7042e02b066b18dd89045d` |
| 比较方法 | 5 轮，使用各轮 P50/P95/P99 的中位数 |

Cold-create、Cold-reopen 和 Steady 分开采集。资源记录包含 CPU time、working set、page fault、context switch、线程、句柄和可观测 poll wakeup。

## Payload 证据

### 请求和遥测

| 样本 | 紧凑 JSON bytes |
| --- | ---: |
| Trigger PREPARE | 298 |
| Trigger REQUEST | 442 |
| Inference classification request | 314 |
| Inference detection request | 309 |
| Inference segmentation request | 312 |
| Inference pose request | 304 |
| Inference OBB request | 303 |
| Training telemetry | 477 |

统一 codec 冻结为 `pydantic-core` compact UTF-8 JSON。外部 `.NET` SDK 继续按同一 JSON 字段和 UTF-8 bytes fixture 验证，不共享 Python 对象。

### 推理响应 corpus

响应 corpus 使用当前五类正式序列化字段，不包含 preview image bytes。图片仍使用 LocalBuffer。

| 样本 | 紧凑 JSON bytes | 裁决 |
| --- | ---: | --- |
| detection，300 objects | 29,385 | inline |
| OBB，300 objects | 49,564 | inline |
| classification，1000 classes | 83,384 | Inference inline |
| pose，100 persons × 17 keypoints | 87,864 | Inference inline |
| segmentation，100 instances × 100 points | 185,964 | Inference inline |
| dense segmentation，100 × 1000 points | 1,738,464 | page-chain |

当前开发数据库另有 259 条 Workflow Preview 输出长度样本：P99 为 10,823.36 B，最大 33,678 B。由此为 Trigger 选择 64 KiB inline response，为常规结果保留接近两倍余量。

## 当前实现基线

### Cold

| Channel | Cold-create P50 | Cold-reopen P50 |
| --- | ---: | ---: |
| Workflow Trigger | 554.33 ms | 78.88 ms |
| Inference | 361.30 ms | 25.98 ms |
| Training Telemetry | 10.72 ms | 0.84 ms |

Trigger 与 Inference 当前固定文件均约 256 MiB。profile 收缩 inline 区并保持 128 MiB 独立 page pool，目标是减少逻辑文件、首次初始化和 descriptor 私有容量，同时不合并不同 Channel 的故障域。

### 大响应与容量

当前 128 MiB page pool 不承诺 16 个 32 MiB 结构化响应同时成功。满载仍应立即返回稳定容量错误，不排队、不重试、不重跑模型或 Workflow。

| 场景，5 轮累计 | 成功 | 容量拒绝 |
| --- | ---: | ---: |
| Trigger 16 MiB，concurrency 16 | 55 | 30 |
| Trigger 32 MiB，concurrency 16 | 31 | 54 |
| Inference 32 MiB，concurrency 16 | 59 | 26 |

该结果不是扩大总页池的依据。32 MiB 是显式 Base64 兼容和极端结构化结果上限；默认图片输入输出继续使用 LocalBuffer。每个 Mailbox Channel 保留独立 128 MiB page pool，避免大响应扩大为全局共享 arena。

### Page geometry

32 MiB 不可压缩 payload 的逐页写、逐页读和 CRC 多轮中位 P99：

| page size | P99 |
| --- | ---: |
| 64 KiB | 37.8143 ms |
| 128 KiB | 36.0522 ms |
| 256 KiB | 35.9665 ms |
| 512 KiB | 41.3723 ms |

256 KiB 在 32 MiB 场景中最快，并把单响应链限制为 128 pages。64/128 KiB 在部分 8/16 MiB 单元接近或略快，但会显著增加 page header、遍历和恢复项数量，因此统一选择 256 KiB。

### Training Telemetry 策略

| 策略 | P99 | 结论 |
| --- | ---: | --- |
| poll 10 ms | 10.8387 ms | wakeup 偏高 |
| poll 50 ms | 50.6648 ms | 默认值 |
| poll 100 ms | 99.7221 ms | 操作反馈偏慢 |
| scan 100 ms | 40.6547 ms | 默认值 |
| scan 1000 ms | 927.5964 ms | 新 Worker 首点发现偏慢 |

训练发布节流 `min_publish_interval_seconds=0.1` 是领域策略，继续独立保留。Event profile 只冻结 ring geometry 和 reader 观察策略。

### Queue 三路裁决

当前开发文件队列观测到 3,952 条消息，最大文件为 5,846 B。正式比较保留三路：

1. 当前 Python object/pickle Queue；
2. `pydantic-core` JSON bytes Queue；
3. 阶段 5 才允许建立的同 envelope/bytes 候选 mmap。

64 KiB、concurrency 1 时，object/bytes P99 分别为 0.3291/0.4427 ms，绝对回退小于 0.5 ms；1 MiB 时为 4.8285/8.7574 ms，已超过未迁移 Queue 的门禁。当前真实 Queue 消息低于 6 KiB，因此阶段 1 可以实现未接入业务的 Queue adapter；阶段 5 不能把该结论扩大为任意 1 MiB Python object 的无损迁移，必须继续执行真实调用点门禁。

## 冻结 profile

代码定义见 [local_message_profiles.py](../../backend/contracts/ipc/local_message_profiles.py)。

| 字段 | Workflow Trigger Mailbox | Inference Mailbox | Training Event |
| --- | ---: | ---: | ---: |
| descriptor / slot count | 128 | 128 | 512 |
| inline request | 64 KiB | 64 KiB | - |
| inline response | 64 KiB | 256 KiB | - |
| event payload | - | - | 4 KiB |
| page size | 256 KiB | 256 KiB | - |
| page count | 512 | 512 | - |
| max pages / response | 128 | 128 | - |
| total page capacity | 128 MiB | 128 MiB | - |
| max response | 32 MiB | 32 MiB | - |
| Mailbox poll | 1 ms | 1 ms | - |
| Event poll | - | - | 50 ms |
| producer scan | - | - | 100 ms |

`max_concurrent_inference_requests`、Workflow Trigger executor 并发、reply timeout、ACK timeout 和训练发布节流不属于 profile。

## 阶段 0 裁决

- 三个 profile 已冻结，可以进入阶段 1 的未接业务 engine 实现。
- `local_memory.root_dir` 迁移必须是独立原子提交，不能与 engine 混合。
- 阶段 1 不修改 composition root，不读取正式 LocalMessage 文件，不迁移 Trigger、Inference 或 Telemetry。
- EventRing 的 owner guard/epoch/session 是异常退出权威依据；PID 只作为诊断元数据。
- `.NET` SDK 只提交 timeout duration；Python owner 在入口建立自身 clock domain 的绝对 monotonic deadline。
- 阶段 5 已按同一 `MailboxPort`、envelope/bytes 和跨进程拓扑完成候选基准，裁决为保留 Workflow Runtime、PublishedInferenceGateway 与 LocalBuffer Broker 的现有 Queue/pipe 传输；详细结果见[实施基线阶段 5](local-message-channel-implementation.md#阶段-5窄-port-与-queue-基准)。
