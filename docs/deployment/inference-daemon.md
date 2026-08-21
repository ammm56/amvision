# 独立 inference daemon

## 进程边界

正式发布配置使用 `inference_daemon.runtime_owner=daemon`。此时 backend-service 只保留 REST、WebSocket 和持久化控制客户端，不创建模型 deployment 子进程。`backend.inference_daemon.main` 是独立入口，持有以下资源：

- detection、classification、segmentation、pose、OBB 的 sync / async deployment supervisor
- async inference gateway dispatcher
- deployment 期望状态恢复协调器
- 本地持久化控制队列 dispatcher
- 跨平台 mmap inference mailbox
- 仅供持久异步任务暂存图片的 daemon 私有 LocalBufferBroker

`runtime_owner=embedded` 只供不启动独立进程的隔离单元测试。完整开发环境和正式发布均使用 `runtime_owner=daemon`。

## 启动与探测

发行目录根启动器在数据库迁移成功后启动 inference daemon，并同时校验 ready 日志和真实控制队列往返，再启动 backend-service 和 worker。开发环境的唯一命令入口见 [development-environment.md](development-environment.md)，本文不重复维护启动命令。

`--probe` 通过实际控制队列往返判断 daemon 是否可达。`GET /api/v1/system/diagnostics` 的 `services.inference_daemon` 使用 1 秒短探测返回 `ok` 或 `unavailable`，不会仅根据客户端对象存在就误报健康。

## 恢复语义

每个 DeploymentInstance 的 `sync`、`async` 通道分别持久化：

- `desired_state`：API 请求的目标状态
- `observed_state`：controller 最近确认的状态
- `generation`：启停命令 fencing token
- controller lease、PID、heartbeat、重启与连续失败计数
- 下一次重试时间和最近错误

daemon 启动后扫描 `desired_state=running` 的记录并恢复进程。进程崩溃和启动失败使用指数退避；generation 防止较早的 start 结果覆盖较新的 stop 请求；数据库 lease 防止同一 deployment 被两个 daemon 同时恢复。新 daemon 接管旧 owner 时，最坏需要等待 `controller_lease_seconds` 到期，正式默认值为 15 秒。

backend-service 不可达不会改变 daemon 中已运行模型进程的期望状态。daemon 不可达时，deployment status/health 返回结构化降级状态，仍允许把持久化期望状态改成 `stopped`，避免恢复后意外拉起。

## 控制面和推理热路径

启停、预热、重置、状态、健康检查和恢复意图继续使用本地持久化控制队列。这些低频操作需要在 service 或 daemon 重启后保留，不以最低延迟为首要目标。

`infer` 不使用持久化文件队列。backend-service 和 inference daemon 通过同一个跨平台 mmap v1 mailbox 交换 JSON 控制信息和结构化推理结果；图片主体不进入 mailbox：

- `BufferRef` / `FrameRef` 只传 path、offset、size、shape、dtype、layout、pixel format、broker epoch 和 generation。
- deployment worker 只读映射 LocalBufferBroker 已配置 pool 的对应区间。raw BGR24 直接返回 `memoryview`，由统一 raw-aware loader 构造 NumPy view。
- 普通 HTTP 上传或 storage image-ref 在 API 边界仍可使用 ObjectStore。同步调用由 backend-service 写入主 LocalBuffer；持久异步任务先保留可恢复的 ObjectStore 引用，daemon 消费任务后再写入私有短期 LocalBuffer。两者进入模型子进程时都只剩 BufferRef/FrameRef。
- 要求结果图片时，backend-service 先分配 writing lease，daemon 把图片直接写入该 LocalBuffer 槽位，mmap 响应只返回实际长度和媒体类型，backend-service 再提交和读取结果。
- mmap 已完成时，本次临时输入和结果 lease 立即释放；timeout、daemon 重启等传输状态不确定时不立即复用槽位，而是保留到有界 TTL 后由 Broker 回收。daemon 拒绝写入剩余有效期不足的结果 lease。
- 热路径禁止 inline image bytes、base64、PNG 临时编码和 `runtime/inputs/inference-control/` 临时图片。

mmap mailbox、原子槽位锁文件和 JSON 协议使用同一份实现覆盖 Windows、Ubuntu x64、Ubuntu ARM64 和 macOS ARM。不使用 TCP/HTTP、Windows named pipe、Unix domain socket 或平台专用系统调用作为核心推理通道。请求和响应带 daemon `server_epoch`、64 位 `generation`、64 位 `owner_token`、monotonic deadline 和 CRC32；超时或调用进程崩溃后的槽位由 daemon 回收。

描述符使用两阶段发布：先写完 body、generation、owner token、deadline、长度和 CRC32，最后单独发布 `REQUEST` 或 `RESPONSE` state。超过内联响应容量的结构化结果写入固定溢出页池；每页记录 descriptor、generation、owner、ordinal、长度和 CRC32，页不要求连续，client 按 ordinal 组合。请求发布、`REQUEST -> PROCESSING`、deadline 取消、`PROCESSING -> RESPONSE` 和 client ACK 使用同一跨进程 guard 串行化；页和描述符由 daemon 在 ACK、取消、超时或重启时统一回收。daemon 对 mailbox 持有生命周期单实例锁，禁止重叠 daemon 清空仍在使用的资源；停机先将 `server_epoch` 置为不可用，重启再发布新的 `server_epoch`，在途请求立即返回取消错误。当前 mailbox 协议固定为 v1，实现只接受当前描述符和固定页池布局。

### mmap mailbox 配置

`config/backend-service.json` 中的配置如下：

```json
{
  "inference_daemon": {
    "mmap_mailbox": {
      "enabled": true,
      "slot_count": 128,
      "message_capacity_bytes": 524288,
      "overflow_page_count": 256,
      "overflow_page_capacity_bytes": 524288,
      "max_overflow_pages_per_response": 64,
      "compression_threshold_bytes": 262144,
      "poll_interval_seconds": 0.001
    }
  }
}
```

- `slot_count` 是可同时等待或执行的 inference 消息数量，不是 LocalBufferBroker 图片槽位数量。默认 128 可以覆盖 80 路 Workflow 分支同时提交；真正同时执行的 handler 数仍受 `control_max_concurrent_requests` 限制。
- `message_capacity_bytes` 是每个槽位中请求 JSON 区和响应 JSON 区各自的容量。默认 512 KiB 不限制 2K、4K 或 20MP 图片，因为图片主体不进入 mailbox。
- `overflow_page_count` 和 `overflow_page_capacity_bytes` 定义进程级固定页池。默认 256 × 512 KiB，共 128 MiB，不在请求时扩文件或创建临时文件。
- 单个结构化响应上限为 `max(message_capacity_bytes, max_overflow_pages_per_response × overflow_page_capacity_bytes)`；默认为 32 MiB。上限同时约束压缩前 JSON 和编码后 body，防止解压膨胀。超限直接返回结构化容量错误，不退回控制队列。
- `compression_threshold_bytes` 默认 256 KiB。只在 zlib level 1 至少节省 12.5% 时采用压缩，避免对不可压缩结果浪费 CPU。
- 单个 mailbox 文件的逻辑大小约为 `文件头 + descriptor 区 + 固定页池`；默认约 256 MiB。descriptor 内联容量按 descriptor 数量成倍增长，页池容量只按页数增长，两者独立配置。
- `poll_interval_seconds` 默认 1ms。继续降低会提高空闲扫描 CPU，增大会直接增加短请求唤醒延迟。

detection、classification、segmentation、pose、OBB 的结构化结果全部走同一 mailbox。常见小结果使用 descriptor 内联响应区；较大的 segmentation polygon/RLE 等结果使用固定页池。预览图、绘制结果或调试图片必须使用 LocalBuffer 或显式持久化保存位置，不得放入页池。

### 与 LocalBufferBroker 图片 pool 的关系

mailbox 只保存控制信息和结构化结果，LocalBufferBroker pool 才保存输入和输出图片。以 raw BGR24 为例：

- 2048×1080：约 6.33 MiB。
- 2560×1440：约 10.55 MiB。
- 3840×2160：约 23.73 MiB。
- 5000×4000：约 57.22 MiB。

当前 `image-1080p` 单槽 16 MiB，可以容纳常见 2K/QHD raw BGR24；当前默认 `image-4k` 单槽 128 MiB，可以容纳上述 2K、4K 和 20MP 输入。是否能写入由 `local_buffer_broker.pools[].slot_size_bytes` 决定，与 mailbox 的 512 KiB 无关。

同步 Workflow、OpenCV 和 deployment worker 共同引用 backend 主池中的同一个 BufferRef，不建立同步“推理专用图片 pool”，也不在推理前复制图片。持久异步任务是不同边界：短期 BufferRef 不能写入可跨重启队列，因此队列保存 ObjectStore 引用；daemon 实际领取任务后，才把图片写入 `inference-daemon-private` 根目录下的私有 broker，模型 worker 完成后立即释放。worker 的路由只接受 backend 主池和 daemon 私有池这两组固定配置路径，不接受任意磁盘路径。

daemon 私有 broker 不是第三条业务传输协议，也不承载同步调用。它只解决异步队列“输入必须可恢复”和模型 worker“图片必须走 LocalBuffer”之间的生命周期转换。同步调用没有这次复制；异步调用只在真正开始执行时复制一次 ObjectStore 图片，且不会把图片 bytes 放进 mailbox 或进程 Queue。

异步结果图在模型进程与 daemon 之间使用 LocalBuffer。必须跨持久 gateway 响应队列时，daemon 把结果图写入本次请求的临时 ObjectStore 目录，队列只返回 object key；worker 读取后删除目录，超时残留由 retention cleanup 回收。响应队列不携带图片 bytes 或 Base64。

每个低频控制请求使用独立响应队列。daemon 定期按 `queue.response_queue_retention_seconds` 清理客户端超时后遗留的 `inference-control-response-*` 目录。控制请求必须携带明确 `expires_at`；缺少 deadline 的消息直接丢弃。请求队列使用 lease 恢复，瞬时文件系统错误只记录日志并继续消费，不会终止 dispatcher。

## 运维边界

- SQLite 正式同机多进程模式启用 foreign keys、busy timeout 和 WAL；迁移到 MySQL/PostgreSQL 时继续通过 Repository 和 Unit of Work，不在应用层增加方言 SQL。
- 根启动器仍是整套发行进程的前台生命周期管理器。需要进程自动拉起时，应由 Windows Service、systemd 或现场进程管理器监督根启动器；daemon 自身负责恢复其内部 deployment，而不是替代操作系统服务管理器。
- 独立升级前先保持数据库 schema 向前兼容，再替换 daemon 代码并重启。daemon 会按持久化期望状态恢复 deployment。
