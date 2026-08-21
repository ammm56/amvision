# LocalBufferBroker

## 定位

LocalBufferBroker 是同一主机内 backend-service、deployment runtime、Workflow Runtime 和其他 Worker 之间传递大图片与视频帧的共享内存数据面。控制消息只携带引用和元数据，像素字节由消费者直接读取 mmap，避免 Base64、JSON 和多次内存复制。

LocalBuffer 不是持久化存储、任务队列或跨主机传输协议。

## 进程与组件

- `LocalBufferBrokerSupervisor` 管理 broker companion process；
- broker process 管理 mmap pool、slot、lease 和控制协议；
- `LocalBufferClient` 负责 allocate、commit、acquire、release 和状态查询；
- `DirectMmapReader` 按引用直接读取共享内存；
- backend-service takeover 在 owner 进程异常时收敛本机 broker 状态。

正式独立 daemon 拓扑有两个互不重叠的 owner root：backend-service 管理主图片池，inference daemon 管理 `inference-daemon-private` 异步暂存池。每个 root 仍只有一个 broker owner；同步调用不会复制到私有池。

实现位于 `backend/service/application/local_buffers/` 和 `backend/service/infrastructure/local_buffers/`。

## 引用模型

`BufferRef`/`FrameRef` 至少携带能唯一定位本次所有权的信息：buffer/slot identity、generation、owner、deadline、长度、shape、dtype、layout、pixel format 和校验元数据。

generation 与 owner fence 用于阻止已回收 slot 的旧引用读取新数据。deadline 用于诊断和清理失联 lease，不等同于请求超时后的无条件回收。

## 生命周期

```text
allocate -> write -> commit -> acquire -> read -> release
```

1. producer 请求可容纳目标字节数的 slot；
2. producer 写入 mmap 并提交 shape、dtype、format 等元数据；
3. consumer 按引用 acquire lease；
4. consumer 直接读取 mmap；
5. 每个 owner 在 finally 中 release；
6. 所有 lease 释放后，slot 才能安全回到池中。

超时、取消、进程退出和 Runtime 切版都必须携带 generation/owner 条件释放。不能仅按 slot id 回收，否则会破坏正在处理的新一代引用。

## 调用链

- Web Preview 上传大图片后转换为 LocalBuffer `image-ref.v1`；
- deployment sync/async 调用传递 BufferRef，不复制整张图片；
- storage 或 inline 同步 deployment 输入由 backend-service 写入主 LocalBuffer；持久异步任务由 daemon 领取后写入私有短期 LocalBuffer；
- 需要返回结果图片时，backend-service 先分配 writing lease，daemon 直接写入，提交后再由 API/Workflow 边界决定返回或持久化；
- Workflow 节点间优先复用一次执行内 memory handle；跨进程时使用 LocalBuffer；
- Trigger 调用解析为当前 Runtime 可消费的图片引用；
- 需要长期保留或跨重启使用的结果转存 ObjectStore 或明确的磁盘保存位置。

## 满载语义

LocalBuffer 与推理执行面都采用有界资源：

- 可用 slot 或推理线程不足时立即返回结构化冲突；
- 不在 broker 内引入业务请求队列；
- 不做隐式重试；
- 调用方按请求结果决定是否再次调用。

这种语义让过载可观测，并避免队列过期、恢复和长尾延迟复杂性。

## 健康与诊断

健康信息应能定位：

- pool 总容量、已用容量和 slot 数；
- active owner/lease 数；
- slot generation、owner、deadline；
- allocate/acquire/release 失败原因；
- broker pid、instance identity 和 heartbeat；
- orphan/recovery 计数。

服务健康页的 backend-worker/broker 状态来自真实进程拓扑与 heartbeat；缺少 topology identity、过期 heartbeat 或 companion process 不可用时显示 degraded，而不是使用旧兼容状态推断健康。

## 稳定性规则

- broker 只由 full Supervisor 或明确的 backend-service takeover 管理，不手工重复启动；
- 每个 broker root 只有一个有效 owner；backend 主池和 daemon 私有异步暂存池不得使用同一 root；
- producer/consumer 所有路径必须在 finally 释放 lease；
- status/health 不修改 slot 所有权；
- 日志按日期轮转，异常必须包含 buffer/slot/generation/owner/deadline；
- mmap 文件只在确认无有效 owner 后回收。

## 明确边界

- 不支持跨主机共享内存；跨主机使用协议适配或持久化对象。
- 不把 LocalBuffer 引用写成长期公开业务资源。
- 不以 Base64 作为性能回退主链路。
- GPU IPC、RDMA 等能力不在当前实现范围，不能写入公开 capability。

相关文档：[高性能图片数据面](image-data-plane.md)、[Workflow Runtime](../workflows/runtime.md)、[模型部署运行时策略](../models/deployment-runtime.md)。
