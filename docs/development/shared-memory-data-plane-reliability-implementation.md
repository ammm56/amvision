# LocalBuffer 与 Trigger 数据面验收

## 当前状态

固定总容量 arena、buddy allocator、持久 descriptor、BufferRef/FrameRef、guard/reclaim、Python/.NET SDK、frame channel 和正式调用点已完成原子迁移；源码故障、容量、完整回归和有界真实传输门禁已通过。

后续 LocalMessage 阶段 7 已完成本机 10,000 次 Trigger 压力与独立发行装配；该结果不等同于重新组装目标发行环境中的 LocalBuffer/Deployment/Workflow 混合持续认证。目标发行环境 10,000 次数据面压力与 24 小时混合 soak 仍按实际部署资源执行，不能由源码短测或 Mailbox 单链路计数替代。

本文只保留持续验收矩阵。已完成的旧 pool 迁移步骤不再作为操作计划；当前实现分别见：

- [LocalBufferBroker](../architecture/platform/local-buffer-broker.md)：allocator、locator/receipt、guards、回收与容量守恒。
- [图片数据面](../architecture/platform/image-data-plane.md)：节点、同步推理和持久异步的图片边界。
- [本机共享内存 Trigger](../architecture/workflows/local-shared-memory-trigger.md)：准入、图片 handoff、deadline 与 ACK。
- [本机结构化消息通道](../architecture/platform/local-message-channel.md)：已经迁移的三条结构化链路。
- [LocalMessage 验收](local-message-channel-implementation.md)：已完成压力与剩余发布认证。

## 验证入口与运行约束

`tests/test_local_buffer_buddy_allocator.py`、`tests/test_local_buffer_mmap_arena.py`、`tests/test_local_buffer_external_leases.py`、`tests/test_local_buffer_arena_pool.py`、`tests/test_workflow_trigger_mailbox.py` 和 `tests/test_workflow_trigger_mailbox_supervisor.py` 覆盖容量、守恒、引用、guard、恢复与交接。真实链路使用 `tests/integration/deployment_workflow_trigger_soak.py`。

开发命令先执行 `conda activate amvision`；测试文件只进入 `.tmp/<name>`。正式 data root 和发行 root 不混用，停止本次进程并确认 owner/view 释放后清理临时产物。Windows x64 是当前强杀恢复和跨语言锁语义认证基线；其他平台需要独立验证。

## 验证矩阵

### 正确性与恢复

- 1 byte、1 MiB边界前后、2/4/8/64/512 MiB、1 GiB分配；超上限明确失败。
- 100,000 次随机分配/释放后容量完全回到基线。
- 相同allocation/free序列始终返回相同offset；默认低地址小图压力后，高地址完整1 GiB root在容量允许时保持可分配。
- 多线程/多进程同时 allocate/commit/read/release无重叠和重复释放。
- Broker 重启时 SDK 分别位于 allocation reply前后、guard前后、写入中、commit前后和读取中。
- backend/Broker/worker 在持有 owner lock、writer guard、reader guard 和 publication guard 时分别被强制结束；下一次启动必须取得 owner、提高 epoch并正常调用，遗留 `.lock` 文件不得形成假死锁。
- 已有 mmap 缺少或损坏 `access.guard` 时 owner/client/SDK 必须拒绝且不自动修复；Windows 持有 guard identity 时删除、rename和replace必须失败。
- 导出 view 未释放时关闭必须报告 `close_blocked`并保留 owner；释放 view 后重试关闭成功，连续多次 close/release 不重复 unlock或丢失 handle。
- 旧 epoch/generation/owner、错误 offset/capacity、越界 view和损坏 descriptor全部拒绝。
- reclaim在发布REVOKING后必须持续持有writer和全部reader guards直到FREE/merge；旧SDK在探测与回收竞态中不能把guard带入新generation。
- reader/writer挂起时进入REVOKING/QUARANTINED，其他extent继续工作；guard释放后恢复。
- hard reserve开启/关闭语义与health一致。
- frame channel任一extent分配/初始化失败时全量回滚，外部无法观察半创建channel。
- frame channel、普通 lease、External input、output lease并发混合无容量泄漏；general/hard reserve分域及arena总容量守恒式始终成立。
- 主arena与daemon私有arena使用不同稳定arena id，错误domain locator无法映射或读取。
- backend、Broker、worker和.NET SDK非64-bit启动门禁直接失败，仓库中不存在32-bit容量配置与兼容分支。

### Trigger mailbox

- 512 KiB边界前后、1/8/16/32 MiB结构化结果。
- 16并发混合小响应和多页响应；page pool碎片化后非连续chain可用。
- client在请求写入、PROCESSING、response读取和ACK各阶段退出。
- daemon在多页写入中退出重启；CRC、owner/generation、page loop/越界损坏明确隔离当前descriptor。
- page pool满载时inline请求成功；满载不重跑Workflow。
- request deadline覆盖结果构建、序列化、压缩、page分配、output handoff和成功RESPONSE publication，且只消费一次。
- 成功、failed、deadline、busy和capacity等所有可读取RESPONSE都有独立ACK deadline；图片输出lease在RESPONSE前批量更新为同一deadline。
- batch output handoff部分失败时不发布部分图片；请求deadline在handoff后到期时释放输出并改发最小deadline响应。
- `cancel_reason`三种原因逐一传播到当前run，RESPONSE与cancel并发时只有一个终态获胜。

### 图片与业务准确率

- raw BGR24/gray8与基准矩阵逐字节一致；BMP/PNG/JPEG解码与现有OpenCV基准一致。
- 1080p、4K、20MP BGR24和57.1 MiB真实BMP覆盖HTTP Base64、ZeroMQ和local-shared-memory。
- 同一Workflow保留两个并行分支、24次真实推理和双Deployment实例；分类/检测/分割/姿态/OBB输出不得因allocator变化而改变。
- 图片返回在Dispose前有效，Dispose后view失效并只ACK一次。

### 性能与长期稳定

- allocator allocate/commit/release P95 相对固定slot基线不得回退超过 `max(1 ms, 10%)`。
- 1080p local-shared-memory数据面P95不得回退超过10%。
- 20MP BGR24 local-shared-memory **数据面** P50/P95继续至少比同机ZeroMQ数据面降低40%，P99不得高于ZeroMQ。数据面按两个入口各自的SDK总耗时减去服务端同一Workflow Runtime invoke公共耗时计算；端到端分位数另行报告，不能混用平均值相减。
- 同一开发环境、模型、图片、warmup和并发下，local-shared-memory端到端P95/P99相对重构前自身基线不得回退超过 `max(5 ms, 10%)`。
- raw BGR24 backend路径不执行encode/decode，不产生整图Python `bytes`副本；调用方直写SDK Span时不建立整张中间数组。
- 每次实现门禁的10,000次混合lease/Trigger soak后，active/WRITING/REVOKING/QUARANTINED、descriptor/page、Runtime token全部回到基线；宣称生产/发行验证完成前还必须执行24小时持续soak并满足同一资源回收标准。
- 无ERROR/WARNING/Traceback、重复释放、所有权失效、静默串图、CRC错误或不受控mmap增长。
