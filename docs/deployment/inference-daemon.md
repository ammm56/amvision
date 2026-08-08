# 独立 inference daemon

## 进程边界

正式发布配置使用 `inference_daemon.runtime_owner=daemon`。此时 backend-service 只保留 REST、WebSocket 和持久化控制客户端，不创建模型 deployment 子进程。`backend.inference_daemon.main` 是独立入口，持有以下资源：

- detection、classification、segmentation、pose、OBB 的 sync / async deployment supervisor
- async inference gateway dispatcher
- deployment 期望状态恢复协调器
- 本地持久化控制队列 dispatcher
- 跨平台 mmap inference mailbox

开发和单元测试可使用 `runtime_owner=embedded`，但该模式不是正式发布默认拓扑。

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

`infer` 不使用持久化文件队列。backend-service 和 inference daemon 通过同一个跨平台 mmap mailbox 交换小型 JSON 元数据；图片主体不进入 mailbox：

- `BufferRef` / `FrameRef` 只传 path、offset、size、shape、dtype、layout、pixel format、broker epoch 和 generation。
- deployment worker 只读映射 LocalBufferBroker 已配置 pool 的对应区间。raw BGR24 直接返回 `memoryview`，由统一 raw-aware loader 构造 NumPy view。
- 普通 HTTP 上传或 storage image-ref 继续使用 ObjectStore 引用，适合低频调用和可追溯输入。
- 热路径禁止 inline image bytes、base64、PNG 临时编码和 `runtime/inputs/inference-control/` 临时图片。

mmap mailbox、原子槽位锁文件和 JSON 协议使用同一份实现覆盖 Windows、Ubuntu x64、Ubuntu ARM64 和 macOS ARM。不使用 TCP/HTTP、Windows named pipe、Unix domain socket 或平台专用系统调用作为核心推理通道。请求和响应带 generation、deadline 和 CRC32；超时或调用进程崩溃后的槽位由 daemon 回收。

槽位使用两阶段发布：先写完 body、generation、deadline、长度和 CRC32，最后单独发布 `REQUEST` 或 `RESPONSE` state。`REQUEST -> PROCESSING`、deadline 取消和 `PROCESSING -> RESPONSE` 使用同一跨进程 guard 串行化，避免扫描线程读取半写入 header，也避免取消状态被迟到响应覆盖。generation 不一致属于协议错误，不使用业务重试掩盖。

### mmap mailbox 配置

`config/backend-service.json` 中的配置如下：

```json
{
  "inference_daemon": {
    "mmap_mailbox": {
      "enabled": true,
      "slot_count": 128,
      "message_capacity_bytes": 524288,
      "poll_interval_seconds": 0.001
    }
  }
}
```

- `slot_count` 是可同时等待或执行的 inference 消息数量，不是 LocalBufferBroker 图片槽位数量。默认 128 可以覆盖 80 路 Workflow 分支同时提交；真正同时执行的 handler 数仍受 `control_max_concurrent_requests` 限制。
- `message_capacity_bytes` 是每个槽位中请求 JSON 区和响应 JSON 区各自的容量。默认 512 KiB 不限制 2K、4K 或 20MP 图片，因为图片主体不进入 mailbox。
- 单个 mailbox 文件的逻辑大小约为 `文件头 + slot_count × (槽位头 + 2 × message_capacity_bytes)`；默认约 128 MiB。增大容量会按槽位数量成倍增加映射文件大小。
- `poll_interval_seconds` 默认 1ms。继续降低会提高空闲扫描 CPU，增大会直接增加短请求唤醒延迟。

普通 detection、classification、pose、OBB 的小型 JSON 结果通常不需要调大 `message_capacity_bytes`。大型 mask、预览图或调试图片应继续使用 BufferRef 或 ObjectStore 引用，不应通过无限增大 mailbox 承载图片内容。

### 与 LocalBufferBroker 图片 pool 的关系

mailbox 只协调推理请求，LocalBufferBroker pool 才保存图片。以 raw BGR24 为例：

- 2048×1080：约 6.33 MiB。
- 2560×1440：约 10.55 MiB。
- 3840×2160：约 23.73 MiB。
- 5000×4000：约 57.22 MiB。

当前 `image-1080p` 单槽 16 MiB，可以容纳常见 2K/QHD raw BGR24；当前默认 `image-4k` 单槽 128 MiB，可以容纳上述 2K、4K 和 20MP 输入。是否能写入由 `local_buffer_broker.pools[].slot_size_bytes` 决定，与 mailbox 的 512 KiB 无关。

默认不建立“推理专用图片 pool”。Workflow、OpenCV 和 deployment worker 应共同引用同一 BufferRef；把图片复制到另一个推理 pool 会增加一次大内存复制并重新引入容量管理。只有需要独立生产者配额、不同 TTL、严格隔离或专用 backpressure 策略时，才增加一个通用命名的 LocalBufferBroker pool，并由入口直接写入该 pool，而不是在推理前复制。

每个控制请求使用独立响应队列。daemon 定期按 `queue.response_queue_retention_seconds` 清理客户端超时后遗留的 `inference-control-response-*` 目录。请求队列使用 lease 恢复，瞬时文件系统错误只记录日志并继续消费，不会终止 dispatcher。

## 运维边界

- SQLite 正式同机多进程模式启用 foreign keys、busy timeout 和 WAL；迁移到 MySQL/PostgreSQL 时继续通过 Repository 和 Unit of Work，不在应用层增加方言 SQL。
- 根启动器仍是整套发行进程的前台生命周期管理器。需要进程自动拉起时，应由 Windows Service、systemd 或现场进程管理器监督根启动器；daemon 自身负责恢复其内部 deployment，而不是替代操作系统服务管理器。
- 独立升级前先保持数据库 schema 向前兼容，再替换 daemon 代码并重启。daemon 会按持久化期望状态恢复 deployment。
