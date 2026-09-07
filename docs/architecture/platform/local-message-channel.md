# 本机结构化消息通道

## 当前实现与分工

LocalMessage 为同机结构化消息提供共用的二进制契约、CRC、owner identity、路径校验、生命周期和健康基础设施。Training Telemetry、Inference Mailbox 和 Workflow Trigger 均已迁移；它们只共享实现，各自持有物理文件、owner、epoch、容量和故障边界。

| 链路 | 传输与内容 | owner |
| --- | --- | --- |
| 同步 Inference | Mailbox；infer/ping/status/health、参数、结果、BufferRef/FrameRef | inference daemon |
| 本机共享内存 Trigger | Mailbox；PREPARE/WRITING 业务扩展、请求、回执与图片引用 | backend-service 的 Trigger supervisor |
| Training Telemetry | EventRing；batch、epoch、validation、runtime 指标 | 每个训练 worker session |
| Workflow Runtime 命令/事件 | `multiprocessing.Queue`；请求、结果、主动 heartbeat、状态、取消 | Workflow manager/worker |
| PublishedInferenceGateway / Broker | 原有 response router、Queue/pipe 与同进程直达机制 | 各自 dispatcher/supervisor |
| Runtime 显示 | 独立有界 socket 交接到 backend，再经 WebSocket 发送 | Runtime worker/观察连接 |

图片 bytes 继续由 [LocalBufferBroker](local-buffer-broker.md) 承担；checkpoint、数据库状态、Outbox、持久任务和长期文件不进入 LocalMessage。

## 文件与默认 profile

所有正式文件从 `local_memory.root_dir` 派生，默认布局为：

```text
data/buffers/
├─ local-buffer/                         图片 arena、metadata、guards、owner
└─ local-message/
   ├─ inference/                        Mailbox、access.guard、owner.lock
   ├─ workflow-trigger/                 Mailbox、access.guard、owner.lock
   └─ training-telemetry/               每 worker session 的 EventRing 与 owner lock
```

普通配置只选择通道启用状态与业务策略。传输容量由 `backend/contracts/ipc/local_message_profiles.py` 冻结并写入 header：

| 项目 | Trigger Mailbox | Inference Mailbox | Training EventRing |
| --- | ---: | ---: | ---: |
| descriptor / slot 数 | 128 descriptors | 128 descriptors | 512 slots |
| request inline | 64 KiB | 64 KiB | — |
| response inline / event payload | 64 KiB | 256 KiB | 4 KiB |
| response page pool | 512 × 256 KiB | 512 × 256 KiB | — |
| 单响应业务正文上限 | 32 MiB | 32 MiB | — |
| poll 间隔 | 1 ms | 1 ms | 50 ms；发现扫描 100 ms |

Mailbox wire 额外保留 64 KiB envelope 空间，每个 response 最多 129 pages。request 有界且只使用 inline；response 超过 inline 时由 server 分配完整 page-chain。符合阈值且至少节省 12.5% 时使用 zlib。容量不足立即返回分类错误，不扩文件、不重跑 handler、不切换其他 transport。

## Mailbox 生命周期

```text
FREE → WRITING_REQUEST → REQUEST → PROCESSING → RESPONSE → ACK/reclaim → FREE
```

Trigger 的 PREPARE/WRITING 是业务扩展，不写入通用 EventRing。身份由 owner epoch、descriptor index/generation、owner token 和 deadline 共同确定；写 body/metadata 后才发布 state。响应 page 与完整正文校验 CRC。ACK、取消、timeout、client 退出和 owner 重启都必须归还对应 descriptor/pages，不能按不可信链释放其他请求的资源。

owner.lock 是持续持有的 OS 文件锁，文件存在不代表 owner 存活。Mailbox mapping 生命周期固定 access.guard 文件身份，guard 后再次核验 descriptor。关闭先拒绝新操作，再关闭 view/mapping/guard，最后释放 owner；活动 view 阻塞关闭时保留句柄并允许重试。

请求发布后不自动重放。owner epoch 改变时当前调用失败，下一次独立请求才重新打开新 owner。Inference 的 start/stop/warmup/reset 继续使用持久控制队列，不进入 Mailbox。

## 训练遥测

```text
训练 batch/epoch/validation/runtime callback
  → TrainingTelemetryPoint
  → TrainingTelemetryMmapPublisher / EventPublisherPort
  → 每 worker session 独立 EventRing
  → TrainingTelemetryMmapReceiver / EventReaderPort
  → TrainingTelemetryBroker（有界 replay）
  → service event bus / WebSocket
  → useTrainingTelemetry / 训练详情页
```

EventRing 是单 producer 的非阻塞覆盖式事件流。sequence、epoch/session、CRC 和 cursor 检测缺口；不存在 Mailbox descriptor、response page、ACK 或 reader/writer access.guard。producer 退出后由 owner lock 判定存活并清理退休文件。

业务遥测包含 task/attempt、model/task type、阶段、epoch/step、学习率、metrics 和 runtime 采样。发布默认按 100 ms 节流；service broker 同时限制任务数和单任务历史。batch 点不写 TaskEvent 表。页面断线或落后时读取快照并恢复订阅；该流不保证每个 batch 必达。

训练暂停/终止仍以数据库控制请求为事实源，checkpoint 和训练输出使用 ObjectStore。遥测不是训练控制命令、模型权重共享或持久训练日志。

## Queue 保留决定

阶段 5 同机比较表明，候选 mmap 虽降低部分 P99 尾峰，但三档 payload 的 P95、CPU 和 page fault 未达到迁移门槛，因此正式保留 Queue/pipe。

Workflow response Queue 承载主动 heartbeat、状态与异步结果；PublishedInferenceGateway 支持并发请求及乱序路由；Broker 有每 client route 和同进程直达。四个窄 Mailbox/Event port 不覆盖这些不同语义，不为形式统一创建新的 mmap Channel。

## 代码与验收

- contracts：`backend/contracts/ipc/`。
- application ports：`backend/service/application/message_channels/`。
- 通用 engine：`backend/service/infrastructure/ipc/local_message/`。
- 业务 adapter：同级 `inference_mailbox.py`、`workflow_trigger_mailbox.py`、`training_telemetry.py`。
- 训练业务点与 broker：`backend/service/application/models/training/training_telemetry.py`。
- 前端订阅：`frontend/web-ui/src/modules/models/composables/useTrainingTelemetry.ts`。

代码迁移、源码故障门禁、本机 10,000 次压力与发行装配已经完成，真实目标发行环境 24 小时混合 soak 仍待验收。测试范围与完成条件只在[LocalMessage 验收](../../development/local-message-channel-implementation.md)维护。设计取舍见 [ADR-0009](../../decisions/ADR-0009-local-message-channel.md)。
