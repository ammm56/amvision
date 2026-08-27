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

发行目录根启动器在数据库迁移成功后启动 inference daemon，并同时校验 ready 日志和真实 mmap ping，再启动 backend-service 和 worker。开发环境的唯一命令入口见 [development-environment.md](development-environment.md)，本文不重复维护启动命令。

`--probe` 通过实际 mmap ping 判断 daemon 和 mailbox 是否可达。`GET /api/v1/system/diagnostics` 的 `services.inference_daemon` 使用 1 秒短探测返回 `ok` 或 `unavailable`，不会仅根据客户端对象存在就误报健康。

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

`start`、`stop`、`warmup`、`reset` 和恢复意图使用本地持久化控制队列。`ping`、`status`、`health` 是无副作用读操作，与 `infer` 一样使用 mmap v1，不创建临时响应队列。

`infer` 不使用持久化文件队列。backend-service 和 inference daemon 通过独立的 LocalMessage Mailbox Channel 交换 JSON 控制信息和结构化推理结果；图片主体不进入 Channel：

- `BufferRef` / `FrameRef` 只传 path、offset、size、shape、dtype、layout、pixel format、broker epoch 和 generation。
- deployment worker 只读映射 LocalBufferBroker 已配置 pool 的对应区间。raw BGR24 直接返回 `memoryview`，由统一 raw-aware loader 构造 NumPy view。
- 普通 HTTP 上传或 storage image-ref 在 API 边界仍可使用 ObjectStore。同步调用由 backend-service 写入主 LocalBuffer；持久异步任务先保留可恢复的 ObjectStore 引用，daemon 消费任务后再写入私有短期 LocalBuffer。两者进入模型子进程时都只剩 BufferRef/FrameRef。
- 要求结果图片时，backend-service 先分配 writing lease，daemon 把图片直接写入该 LocalBuffer 槽位，mmap 响应只返回实际长度和媒体类型，backend-service 再提交和读取结果。
- mmap 已完成时，本次临时输入和结果 lease 立即释放；timeout、daemon 重启等传输状态不确定时不立即复用槽位，而是保留到有界 TTL 后由 Broker 回收。daemon 拒绝写入剩余有效期不足的结果 lease。
- 热路径禁止 inline image bytes、base64、PNG 临时编码和 `runtime/inputs/inference-control/` 临时图片。

Inference Mailbox 复用项目级 LocalMessage common/Mailbox engine，覆盖 Windows、Ubuntu x64、Ubuntu ARM64 和 macOS ARM。不使用 TCP/HTTP、Windows named pipe、Unix domain socket 或平台专用系统调用作为核心推理通道。请求和响应带 daemon owner epoch、64 位 `generation`、64 位 `owner_token`、monotonic deadline 和 CRC32；超时或调用进程崩溃后的 descriptor 由 daemon 回收。

描述符使用两阶段发布：先写完 body 和 header，最后单独发布 `REQUEST` 或 `RESPONSE`。超过 inline 容量的结构化结果进入固定 overflow page chain；连续页不足时允许非连续链。请求发布、`REQUEST -> PROCESSING`、取消、`PROCESSING -> RESPONSE` 和 ACK 使用同一 descriptor guard；daemon 根据 allocator 记录在 ACK、取消、超时或重启时统一回收。完整布局、压缩、CRC、所有权和异常恢复见 [Inference mailbox v1](../architecture/platform/inference-mailbox-v1.md)。

### Inference Mailbox 配置

`config/backend-service.json` 中的配置如下：

```json
{
  "inference_daemon": {
    "mmap_mailbox": {
      "enabled": true
    },
    "max_concurrent_inference_requests": 16
  }
}
```

- `mmap_mailbox.enabled` 只控制 Inference Mailbox Channel 是否启用。
- `max_concurrent_inference_requests` 是业务 handler admission，默认 16。控制队列另用 `control_max_concurrent_requests`，两者互不混用。
- descriptor、inline、page、压缩阈值和 poll 几何由 `inference-mailbox.v1` profile 固定，不向普通配置暴露。当前 profile 为 128 descriptors、64 KiB request inline、256 KiB response inline、512 × 256 KiB pages、单响应最多 128 pages、32 MiB response 上限和 1 ms poll。
- 配置中出现已删除的 transport 几何字段会被拒绝，不保留旧配置双读。

detection、classification、segmentation、pose、OBB 的结构化结果全部走同一 mailbox。常见小结果使用 descriptor 内联响应区；较大的 segmentation polygon/RLE 等结果使用固定页池。预览图、绘制结果或调试图片必须使用 LocalBuffer 或显式持久化保存位置，不得放入页池。

### 与 LocalBufferBroker 图片 arena 的关系

mailbox 只保存控制信息和结构化结果，LocalBufferBroker 固定总容量 arena 保存输入和输出图片。以 raw BGR24 为例：

- 2048×1080：约 6.33 MiB。
- 2560×1440：约 10.55 MiB。
- 3840×2160：约 23.73 MiB。
- 5000×4000：约 57.22 MiB。

backend 主 arena 默认总容量 2 GiB、最小 block 1 MiB、单次连续分配上限 1 GiB。Broker 根据精确 `content_length` 动态选择最小可容纳的 1/2/4/.../1024 MiB buddy order，因此不同尺寸图片不会预占固定分辨率槽位。是否能写入由当前总空闲容量、最大连续块和单次分配上限共同决定，与 mailbox 的 512 KiB 无关；满载或碎片不足立即返回分类错误，不排队或切换传输协议。

同步 Workflow、OpenCV 和 deployment worker 共同引用 backend 主 arena 中的同一个 BufferRef，不建立同步“推理专用图片池”，也不在推理前复制图片。持久异步任务是不同边界：短期 BufferRef 不能写入可跨重启队列，因此队列保存 ObjectStore 引用；daemon 实际领取任务后，才把图片写入 `inference-daemon-private` arena，模型 worker 完成后立即释放。worker 的路由只接受 backend 主 arena 和 daemon 私有 arena 这两组固定配置路径，不接受任意磁盘路径。

daemon 私有 broker 不是第三条业务传输协议，也不承载同步调用。它只解决异步队列“输入必须可恢复”和模型 worker“图片必须走 LocalBuffer”之间的生命周期转换。同步调用没有这次复制；异步调用只在真正开始执行时复制一次 ObjectStore 图片，且不会把图片 bytes 放进 mailbox 或进程 Queue。

异步结果图在模型进程与 daemon 之间使用 LocalBuffer。必须跨持久 gateway 响应队列时，daemon 把结果图写入本次请求的临时 ObjectStore 目录，队列只返回 object key；worker 读取后删除目录，超时残留由 retention cleanup 回收。响应队列不携带图片 bytes 或 Base64。

每个变更控制请求使用独立响应队列。daemon 定期按 `queue.response_queue_retention_seconds` 清理客户端超时后遗留的 `inference-control-response-*` 目录。控制请求必须携带明确 `expires_at`；缺少 deadline 的消息直接丢弃。请求队列使用 lease 恢复，瞬时文件系统错误只记录日志并继续消费，不会终止 dispatcher。只读状态不会创建这些目录。

## 运维边界

- SQLite 正式同机多进程模式启用 foreign keys、busy timeout 和 WAL；迁移到 MySQL/PostgreSQL 时继续通过 Repository 和 Unit of Work，不在应用层增加方言 SQL。
- 根启动器仍是整套发行进程的前台生命周期管理器。需要进程自动拉起时，应由 Windows Service、systemd 或现场进程管理器监督根启动器；daemon 自身负责恢复其内部 deployment，而不是替代操作系统服务管理器。
- 独立升级前先保持数据库 schema 向前兼容，再替换 daemon 代码并重启。daemon 会按持久化期望状态恢复 deployment。
