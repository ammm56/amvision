# LocalMessage 通道验收

## 当前状态

Training Telemetry、Inference Mailbox 和 Workflow Trigger 已原子迁移到通用 engine，旧布局和双读路径已删除。阶段 0–6、阶段 7 源码故障与性能门禁、本机 10,000 次压力和独立发行装配均已完成；真实目标发行环境 24 小时混合 soak 尚待执行，因此 ADR-0009 仍未标记为完全实现。

当前模块、目录、容量、生命周期与训练遥测链路见[本机结构化消息通道](../architecture/platform/local-message-channel.md)。本文只维护性能裁决、持续验证和未完成发行门禁，不再保存已经结束的实现步骤。

## 可重复验证入口

| 范围 | 入口 |
| --- | --- |
| engine、CRC、guards、epoch、ACK、page-chain、EventRing | `tests/test_local_message_channel_engine.py` |
| 训练遥测与发现/回收 | `tests/test_training_telemetry.py`、`tests/test_training_telemetry_mmap.py` |
| Trigger 协议与 Runtime/LocalBuffer 交接 | `tests/test_workflow_trigger_mailbox.py`、`tests/test_workflow_trigger_mailbox_supervisor.py` |
| Inference、Trigger、Telemetry、Queue 基准 | `tests/integration/local_message_channel_stage*_benchmark.py` |
| 固定 profile 跨语言契约 | `tests/fixtures/local_message_channel_profiles.v1.fixture.json`、.NET ContractTests |
| 真实混合持续负载 | `tests/integration/deployment_workflow_trigger_soak.py` |

Python 命令先执行 `conda activate amvision`。测试根重定向到 `.tmp/<name>/buffers`，仍使用正式 layout；进程停止、owner/view 释放后清理临时文件。历史报告路径与 SHA 不能视为仓库中的永久验收资产；冻结测量见[阶段 0 基线](local-message-channel-stage0-baseline.md)。

## Queue 保留裁决

正式裁决为 `retain-queue`。候选基准使用阶段 1 的相同
`MailboxPort`、相同 wire envelope/bytes 和相同跨进程 echo 拓扑，比较
`MultiprocessingQueueMailbox*` 与只服务基准的 `MmapMailbox*`，未创建正式
`workflow-runtime/`、PublishedInferenceGateway 或 LocalBuffer Broker mmap 目录。

实际语义审计同时确认：

- Workflow Runtime response Queue 还承载主动 heartbeat、runtime state 和异步运行结果，不是严格的一问一答；
- PublishedInferenceGateway 使用 response router 支持并发请求和乱序响应，阶段 1 的 Queue MailboxClient 是单 endpoint 串行语义；
- LocalBuffer Broker 组合每 client response route、同进程直达和跨进程 pipe，不是单一 Queue Mailbox。

因此四个 LocalMessage port 只作为严格 Mailbox/Event 的协议边界，不强制覆盖上述
领域通道。保留链路不增加 JSON/bytes 二次编码、串行锁或形式化 wrapper；后续若要
迁移，必须先为对应异步语义单独设计 port 和基准，不能扩张当前 common schema。

冻结基准参数为 5 轮、每轮 10 次预热和 50 次稳态调用，Windows `spawn`、单 client/
server 跨进程，载荷为 1/6/64 KiB。结果如下（单位 ms，均为五轮中位数）：

| payload | Queue P50 / P95 / P99 | mmap P50 / P95 / P99 | 裁决 |
| ---: | ---: | ---: | --- |
| 1 KiB | 0.162 / 0.296 / 8.850 | 1.902 / 3.336 / 3.469 | 保留 Queue |
| 6 KiB | 0.189 / 0.301 / 8.601 | 2.159 / 3.837 / 4.127 | 保留 Queue |
| 64 KiB | 0.275 / 0.413 / 8.874 | 2.329 / 3.633 / 3.951 | 保留 Queue |

mmap 降低了 Windows Queue 的偶发 P99 尾峰，但三档 P95 均显著回退，CPU 中位数
约为 0.28–0.30 秒而 Queue 为 0.047–0.063 秒，page fault 也更高，未达到迁移门槛。
可复现工具为 `tests/integration/local_message_channel_stage5_queue_benchmark.py`，原始
历史报告临时路径为 `.tmp/local-message-channel-stage5/queue-benchmark.json`，SHA-256 为
`c38d188b4f7484371a4c3a873614b672d08f9ab496945e7c40efc945971fa219`。

基准和审计覆盖：

- 多轮中位P50、P95、P99与CPU；
- serialize/deserialize与poll/wakeup成本；
- working set、page fault、context switch、feeder/thread/handle数量；
- 进程退出、父进程崩溃、cancel和timeout清理；
- 长期运行内存、文件和Channel数量。

裁决规则保持为：只有 Mailbox 在至少 5 轮稳态采样中同时改善多轮中位 P95 和
P99 至少 10%，且至少一个指标绝对改善不小于 1 ms，同时 CPU、working set、page
fault、线程/句柄和关闭清理不差时，才另行更新 ADR 并原子切换对应链路。该候选基准未通过迁移门槛。

## 故障、性能与持续负载

状态：**源码与本机自动化门禁已完成；真实发行环境 24 小时混合 soak 待发布前执行。**

必须覆盖：

- 多Channel同时运行、独立满载、独立重启和独立epoch；
- Client/server在所有publication状态退出；
- page/ring CRC、循环、越界、owner/generation/epoch错误；
- request timeout、response ACK timeout、explicit cancel和client shutdown；
- telemetry wrap、gap、producer crash和receiver restart；
- owner持锁时强杀Mailbox server/Event producer/LocalBuffer owner，下一owner必须立即可取得OS lock并按新epoch恢复；遗留`.lock`文件不能造成假死锁；
- Mailbox `access.guard` 缺失、长度错误或被替换时fail closed且client不得修复；Windows持有identity handle时delete/rename/replace必须失败；
- 活动response/view阻塞close时保留owner与资源handle，释放view后重试close成功；重复close/release不重复unlock；
- Queue保留/迁移链路的shutdown与handle守恒；
- 真实HTTP、ZeroMQ、local-shared、Workflow Runtime、Trigger、Inference和training telemetry混合负载；
- 10,000次门禁后descriptor、page、ring、file、guard、thread、handle和Channel回到基线；
- 发布前24小时持续soak无泄漏、串包、CRC错误、owner失效或不受控文件增长。

性能阈值以阶段0同机、多轮中位基线为准，所有比较使用相同预热、消息分布、并发、运行时间和进程拓扑：

- inline消息P95/P99不得回退超过`max(1 ms, 10%)`；
- 1/8/16/32 MiB结构化response的P95/P99不得回退超过10%；
- 未迁移Queue的链路不得因port抽象产生超过`max(0.5 ms, 5%)`的P95/P99回退；
- CPU和working set不得回退超过10%，page fault、poll wakeup、线程和句柄不能出现无解释的持续增长；
- 不以平均值或单轮最好值替代多轮中位P95/P99，不把Workflow模型执行耗时算作IPC传输收益。

.NET `Amvar.Vision.ContractTests` 已有 .NET Framework 4.7.2 Release 跨语言 fixture 验证记录；这不替代真实发行持续负载验收。

## 发布完成条件

24 小时门禁必须在真实目标发行环境使用 bundled Python、backend-service、已预热 Deployment、Workflow Runtime、ZeroMQ TriggerSource、实际图片和访问令牌执行。mock、缩短时长、单链路压力或空发行包启动不能替代。通过后才更新 ADR 状态；验收失败保留错误分类、容量守恒与资源趋势，不能用更宽松的合成基准覆盖。
