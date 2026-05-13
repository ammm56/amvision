# LocalBufferBroker 规划

## 文档目的

本文档用于规划本项目中的本机高性能数据交换层，重点说明 Broker + mmap 文件池如何支撑 workflow 隔离进程、已发布推理服务和外部高速输入之间的大图数据传递。

本文档描述长期架构和分期实现。当前主干已经完成第 0 阶段和第 1 阶段的基础实现：BufferRef、FrameRef、BufferLease、mmap pool、LocalBufferBroker companion process、preview run / WorkflowAppRuntime / deployment worker 的 broker client 接入、direct mmap 读写数据面、LocalBufferBroker 状态事件队列、父进程响应隔离 router、workflow 执行结束释放 broker lease，以及 PublishedInferenceGateway 事件 dispatcher。第 2.2 阶段已经补入 owner 批量释放、expire_leases 触发入口和基础 pool 状态指标。第 2.3 阶段已经补入周期性 expire loop、最近 broker 错误记录，以及 backend-service health、workflow runtime health 和 deployment health 的 broker 摘要。第 3 阶段已经补入 ring buffer channel 的最小闭环：固定槽位 channel、FrameRef direct mmap 写读、覆盖后的旧 FrameRef 失效校验和基础帧指标。lease heartbeat、registry 恢复、目录扫描清理和更完整的配额策略仍属于后续阶段。

## 背景

workflow 编辑态试跑和已发布应用运行都需要保持独立进程隔离。发布推理服务也需要作为长期稳定运行的独立 worker，持有模型 session、实例池、keep-warm 和运行时状态。

这些进程之间需要频繁传递图片、视频帧和后续可能出现的 tensor。HTTP、JSON base64 或 ZeroMQ 大帧传输都不适合作为本机内部热路径的数据面。更合适的方式是把大数据放入本机可共享的 mmap 文件池，消息中只传递引用、偏移和形状信息。

## 目标

- 保留 preview run 的一请求一子进程隔离模型。
- 保留 WorkflowAppRuntime 的长期 worker 隔离模型。
- 保留 DeploymentInstance 推理 worker 的长期稳定运行模型。
- 支持 Windows、Ubuntu 和 macOS，不依赖单一操作系统专用机制。
- 避免在本机进程之间反复传输 base64、大 JSON 或 TCP 大包。
- 支持上位机、ZeroMQ、gRPC、HTTP、PLC、IO 和传感器入口统一转换为 workflow 输入。
- 为高频连续帧提供 ring buffer 模式，为单张图片和普通 preview 提供普通 buffer lease 模式。
- 提供按年运行所需的固定容量、租约、清理、背压、恢复和指标机制。

## 非目标

- 不替代 REST API、WebSocket、ZeroMQ、gRPC、MQTT、PLC 等外部触发或公开接入方式。
- 不把 workflow runtime、deployment worker 和 backend-service 合并成同一个进程。
- 不把 LocalBufferBroker 做成跨主机数据总线。
- 第一阶段不引入 CUDA IPC 或 GPU buffer 共享。
- 第一阶段不要求所有节点都改成 mmap 输入。

## 分层关系

```text
外部输入层
HTTP / ZeroMQ / gRPC / MQTT / PLC / IO / sensor
        |
        v
TriggerSource / Integration Adapter
        |
        v
WorkflowRun / PreviewRun / AppRuntime
        |
        v
隔离 workflow 执行进程
        |
        v
PublishedInferenceGateway
        |
        v
LocalBufferBroker
        |
        v
长期运行的 DeploymentInstance 推理 worker
```

ZeroMQ 属于外部高速输入或触发入口之一。LocalBufferBroker 属于本机内部数据交换层。两者不能混成同一层：ZeroMQ 负责把上位机或桥接进程的高速输入接入平台，LocalBufferBroker 负责平台内部隔离进程之间的大数据引用和生命周期管理。

## 推荐方案

第一阶段采用 Broker + mmap 文件池，第二阶段在同一套 Broker 上增加 ring buffer channel。

```text
LocalBufferBroker
  - 普通 mmap buffer pool：单图、preview、一次性 workflow 输入
  - mmap ring buffer channel：连续帧、高速上位机、相机流
  - lease registry：租约、TTL、引用计数、owner、状态
  - cleanup worker：超时回收、孤儿清理、目录扫描
  - metrics：容量、丢帧、超时、等待和回收统计
```

普通 buffer lease 和 ring buffer 都使用 file-backed mmap。区别在于分配策略：普通 lease 按请求分配一个区间，ring buffer 为固定输入源预先分配循环帧槽。

## 本项目实现方式

LocalBufferBroker 在目标运行形态中是本机独立 companion process，由 backend-service 或本地启动器负责启动、健康检查和停止。它不是对外公开服务，也不是新的远程微服务；它只服务同一台机器上的 backend-service、workflow preview 子进程、WorkflowAppRuntime worker、DeploymentInstance 推理 worker 和受控本地 adapter。

第 0 阶段已经在项目内实现合同模型、mmap pool 基础设施和本地 reader 接口，并稳定 BufferRef、FrameRef、BufferLease、槽位复用、generation 校验和 image-ref 解析规则。第 1 阶段已经把同一套 mmap pool 和 lease registry 包到 broker companion process 中，并把 workflow preview、WorkflowAppRuntime 和 deployment worker 接到 broker client。

建议运行形态如下：

```text
backend-service / local launcher
  |
  | supervise
  v
LocalBufferBroker process
  |
  | local control channel，不传大图
  v
file-backed mmap pool / ring buffer files
  ^
  |
workflow preview process / workflow runtime worker / deployment worker / local adapter
```

控制通道只负责 allocate、commit、read-validate、release、heartbeat 和 metrics，不承载大图。大图数据只写入 mmap 文件，调用方通过 BufferRef 或 FrameRef 传递 `path`、`offset`、`size`、`broker_epoch` 和 `generation`。

当前实现中，LocalBufferBroker client 的 `write_bytes` 已拆成 allocate、direct mmap write 和 commit，`read_buffer_ref` 已拆成 validate 和 direct mmap read；broker 控制动作只保留 allocate、commit、validate、release、release-owner、expire、status 和 shutdown 等状态事件。broker 进程通过父进程创建的事件队列接收控制事件，不再通过 host、port 或 authkey 暴露本地监听入口。多个 preview、runtime 和 deployment 子进程不会直接共享 broker response queue，backend-service 父进程会为每个 client channel 分配独立 response queue，并通过 router 按 request_id 分发响应。owner 批量释放支持按 owner_id 精确匹配或按 owner_id_prefix 兜底清理同一 workflow run 创建的 lease。

## 当前可用性核查

当前 broker + mmap 主链路已经可以在本机 backend-service 运行时使用，已完成的能力包括：

- BufferRef、FrameRef、BufferLease 合同和 image-ref 解析规则。
- 固定槽位 file-backed mmap pool、两阶段写入、读取校验、release、release-owner 和 expire_leases。
- LocalBufferBroker companion process、supervisor、client、父进程 response router 和周期性 expire loop。
- 普通 BufferRef direct mmap 写读，以及最小 ring channel 的 FrameRef direct mmap 写读。
- preview run、WorkflowAppRuntime worker 和 deployment worker 的 broker client 注入。
- YOLOX detection 节点通过 PublishedInferenceGateway 调用 backend-service 持有的长期 deployment worker。
- backend-service health、workflow runtime health 和 deployment health 中的 broker 摘要、输入计数和最近错误。
- OpenCV 与 Barcode/QR 自定义节点通过公共 `load_image_bytes` 读取图片，已经具备 memory、storage、buffer 和 frame 输入兼容能力。

仍不应视为完成的生产闭环包括：

- C# / .NET 外部调用方 SDK 首版已实现，并已支持 `net461;net472;netstandard2.1;net10.0`；Python、Go 和 C SDK 尚未实现。
- ZeroMQ TriggerSource 已具备普通 BufferRef 写入和 runtime submit 骨架，06/07 已补充同 app HTTP base64 + ZeroMQ image-ref 双输入 workflow app 请求体、TriggerSource 请求体和 C# SDK 调试命令，真实 backend-service 联调仍需完成。
- FrameRef 在创建 WorkflowRun 前固定为 BufferRef 的步骤尚未实现。
- ring channel 仍只有最小覆盖语义，latest、strict、drop-oldest、drop-newest 和 block-with-timeout 策略尚未落地。
- lease heartbeat、registry 恢复、目录扫描清理、配额和背压策略仍在后续阶段。
- 推理预览图写回 BufferRef、调试保存和更完整的指标面板仍未完成。

因此，现阶段可以使用的路径是“HTTP/base64 或 storage 输入 -> workflow runtime -> 内部 LocalBufferBroker BufferRef/FrameRef -> PublishedInferenceGateway -> deployment worker”。ZeroMQ TriggerSource 已经具备把外部图片 bytes 写入普通 BufferRef 并提交 runtime 的骨架；C# / .NET SDK 已能封装单张图片 REQ/REP 调用；06/07 双输入 workflow app 与调试文档已补齐。`image-ref -> image-base64`、本地磁盘读图和相机抓帧仍属于图内节点边界，不属于 TriggerSource。连续帧 FrameRef、其他语言 SDK 和真实 backend-service 端到端联调仍属于下一步。

## 示例与节点同步规则

- `docs/examples/workflows` 保存 template/application 源 JSON，继续保留公开输入形状，不写入机器相关的 FrameRef/BufferRef 常量。
- `docs/api/examples/workflows` 保存 HTTP 控制面请求体，继续使用 `image-base64.v1`、storage `image-ref.v1` 和 multipart 示例；后续本地 adapter 公开后再新增 `06-*` 高速输入示例。
- `docs/api/postman/workflows` 保留可直接导入和复现的 HTTP/Postman 调试路径；Postman collection 不固定 mmap path、offset、broker_epoch 或 generation。
- `backend/nodes/core_nodes` 中的推理节点应通过 PublishedInferenceGateway 访问已发布 deployment；提交、启动、停止、health 这类控制节点仍保留 deployment service / supervisor 控制语义。
- `custom_nodes` 不直接处理 mmap 文件。自定义节点应继续通过 `load_image_bytes`、`require_image_payload`、`write_image_bytes` 和 `register_image_bytes` 读写图片，catalog 中的 image-ref schema 需要同步声明 buffer/frame 支持。

## mmap 实现方式

第一阶段使用 file-backed mmap，而不是匿名 shared memory。原因是 file-backed mmap 在 Windows、Ubuntu 和 macOS 上更容易做统一实现，也便于 broker 重启后扫描 runtime buffer 目录清理旧文件。

实现约定如下：

- 每个 pool 使用固定大小 mmap 文件，例如 `runtime/buffers/image-small/pool-001.dat`。
- 每个 pool 按固定槽位分配，单次 lease 不能超过槽位大小。
- broker 持有 lease registry，记录槽位、owner、state、TTL、ref_count、broker_epoch 和 generation。
- 写入采用两阶段状态：先分配 `writing` lease，写入并 flush 后才变成 `active`，只有 active lease 才能生成对外传递的 BufferRef。
- reader 不能只相信文件路径，必须通过 broker 或本地 reader 校验 lease_id、broker_epoch、generation 和 active 状态。
- Windows 上不能在还有进程 mmap 时删除文件，因此清理策略以 release、启动扫描和延迟删除为主，避免运行中强删 pool 文件。

第 0 阶段的最小实现位于 `backend/service/infrastructure/local_buffers/mmap_buffer_pool.py`，用于验证固定容量、写入、读取、release 和旧引用拒绝。后续 broker 进程会复用这些基础设施，并补齐跨进程控制通道。

## 一致性规则

LocalBufferBroker 的一致性目标不是数据库级事务，而是保证短期大图引用不会读到未写完、已释放或被复用的数据。

必须遵守以下规则：

- 单一写入仲裁：槽位分配、lease 状态变化和 generation 增长只能由 broker 完成。
- 两阶段发布：写入期间为 `writing`，flush 完成后才切换为 `active` 并返回 BufferRef。
- 旧引用失效：broker 每次启动生成新的 `broker_epoch`；每个槽位复用时增加 `generation`。
- 读取校验：reader 必须校验 lease_id、broker_epoch、generation、path、offset、size 和 active 状态。
- 生命周期收敛：workflow run、preview run、deployment worker 和 adapter 都要声明 owner，结束或心跳丢失后由 broker 回收 lease。
- 容量背压：pool 已满时按配置拒绝、短等待或丢帧，禁止无界创建 mmap 文件。
- 长期保存分离：需要审计、下载、复现或回滚的数据必须提升为 ObjectStore 文件引用，不能依赖 BufferRef 长期有效。

## 核心对象

### BufferPool

BufferPool 表示一组固定规格的 mmap 文件池。

建议按尺寸预分配不同池：

- small：小图、结构化二进制、小中间结果
- image-1080p：常见工业相机输入
- image-4k：大图输入
- output-preview：预览图和可选渲染结果

池大小应由配置控制，不在运行中无限增长。

### BufferLease

BufferLease 表示一次临时数据占用。

建议字段：

- lease_id
- buffer_id
- owner_kind，取值如 trigger-source、preview-run、workflow-runtime、deployment-worker
- owner_id
- pool_name
- file_path
- offset
- size
- created_at
- expires_at
- ref_count
- state，取值如 writing、active、released、expired、reclaimed
- trace_id
- broker_epoch
- generation

Broker 只把 active lease 暴露给客户端。过期 lease 由 cleanup worker 回收。

### BufferRef

BufferRef 是传给 workflow 节点和 deployment worker 的数据引用。

建议字段：

```json
{
  "format_id": "amvision.buffer-ref.v1",
  "buffer_id": "buffer-1",
  "lease_id": "lease-1",
  "path": "runtime/buffers/image-1080p/pool-001.dat",
  "offset": 1048576,
  "size": 6220800,
  "shape": [1080, 1920, 3],
  "dtype": "uint8",
  "layout": "HWC",
  "pixel_format": "BGR",
  "media_type": "image/raw",
  "readonly": true,
  "broker_epoch": "epoch-1",
  "generation": 1
}
```

BufferRef 不应长期写入数据库作为正式结果。需要留存或审计的图片应异步提升为 ObjectStore 文件引用。

### RingBufferChannel

RingBufferChannel 表示一个连续帧输入源。

建议字段：

- stream_id
- channel_id
- pool_name
- frame_capacity
- frame_size
- write_sequence
- read_policy，取值如 latest、strict、drop-oldest、drop-newest
- stale_frame_ms
- dropped_frame_count

Ring buffer 适合连续检测、视频流和高节拍工位。逐件检测类场景不应默认覆盖未消费帧，应使用 strict 或 block-with-timeout 策略。

### FrameRef

FrameRef 是 ring buffer 中某一帧的引用。

建议字段：

```json
{
  "format_id": "amvision.frame-ref.v1",
  "stream_id": "line-a-camera-1",
  "sequence_id": 1024,
  "buffer_id": "ring-line-a-camera-1",
  "path": "runtime/buffers/image-1080p/pool-001.dat",
  "offset": 25165824,
  "size": 6220800,
  "shape": [1080, 1920, 3],
  "dtype": "uint8",
  "layout": "HWC",
  "pixel_format": "BGR",
  "media_type": "image/raw",
  "broker_epoch": "epoch-1",
  "generation": 1
}
```

FrameRef 的有效期通常短于普通 BufferRef。workflow 执行前应尽量把需要稳定处理的帧固定为普通 lease，避免执行期间被 ring buffer 覆盖。

## 控制面与数据面

控制面负责分配、释放、注册和查询，不传大图。

数据面通过 mmap 文件传递图片、帧和中间结果。客户端通过 BufferRef 或 FrameRef 定位 mmap 文件、offset、size 和 shape。

第一阶段控制面可以由 backend-service 托管的 LocalBufferBroker 进程提供。具体控制通道应保持可替换，优先满足跨平台和本地部署：

- Python 管理的 workflow 和 deployment 子进程可通过 broker client 使用状态事件通道。
- 外部高速输入 adapter 可通过受控 SDK 或本地 adapter 进入 broker。
- 不把大图放入控制消息，不把控制通道作为性能核心。

## 与 Workflow 的关系

workflow runtime 继续保持隔离进程执行。

需要调整的主要是公共输入和服务节点支持层：

1. 扩展 image payload 解析，支持 BufferRef 和 FrameRef。
2. 增加 PublishedInferenceGateway，workflow 推理节点只依赖 gateway，不直接依赖 deployment supervisor。
3. preview run 和 WorkflowAppRuntime 的 execution metadata 中携带 broker 客户端上下文。
4. workflow 执行结束后释放当前 run 持有的 lease。
5. 需要保留的预览图、标注图和中间图通过 ObjectStore 保存，不依赖 mmap 文件长期存在。

## 与发布推理服务的关系

DeploymentInstance 推理 worker 继续长期运行并持有模型 session。

推理 worker 需要新增 BufferRef 输入来源：

- 从 BufferRef 或 FrameRef 读取图像数据。
- 支持 raw BGR/RGB 和必要的压缩格式输入。
- 推理结果默认返回结构化 detections。
- 可选预览图输出也可返回 BufferRef，再由 workflow 或 API 层决定是否转为 ObjectStore。

现有 REST 推理接口继续保留。REST 输入可以在 backend-service 或 adapter 中转换为 BufferRef，再调用同一套 PublishedInferenceGateway。

## 与外部高速入口的关系

HTTP、ZeroMQ、gRPC、MQTT、PLC、IO 和 sensor 都属于触发或输入接入层。

其中 ZeroMQ 更适合作为上位机高速提交图片和触发 workflow 的入口。进入平台后，大图应尽快写入 LocalBufferBroker，后续 workflow 节点和推理 worker 只传 BufferRef 或 FrameRef。

```text
上位机 ZeroMQ 输入
        |
        v
ZeroMQ adapter
        |
        v
LocalBufferBroker 写入 BufferRef 或 FrameRef
        |
        v
WorkflowRun input
```

## 对现有节点的影响

影响应集中在公共层，不应让每个节点直接处理 mmap 文件。

需要修改的公共位置：

- image-ref / image-base64 解析层：增加 buffer-ref 和 frame-ref 分支。
- runtime input binding：允许图像输入携带 BufferRef 或 FrameRef。
- YOLOX detection 节点：通过 PublishedInferenceGateway 调用已发布 deployment。
- image-preview 节点：支持把 BufferRef 转为短期预览或保存到 ObjectStore。
- cleanup 机制：run 结束后释放自动创建的 buffer lease。

暂不需要修改的内容：

- 训练、验证、转换任务的队列和 worker 主链路。
- 公开 REST API 的资源管理语义。
- WorkflowGraphTemplate 的节点连接模型。
- ObjectStore 的正式文件保存规则。

## 建议代码位置

建议按下面方式拆分：

```text
backend/contracts/buffers/
  buffer_ref.py
  frame_ref.py
  buffer_lease.py

backend/service/application/local_buffers/
  local_buffer_broker_service.py
  buffer_lease_service.py
  ring_buffer_service.py

backend/service/infrastructure/local_buffers/
  mmap_buffer_pool.py
  mmap_ring_buffer.py
  buffer_registry.py
  cleanup_worker.py

backend/service/application/deployments/
  published_inference_gateway.py
  local_broker_inference_gateway.py

backend/nodes/runtime_support.py
  resolve_image_reference 支持 buffer-ref / frame-ref
```

如果后续需要把 broker 做成独立启动入口，可增加：

```text
backend/broker/
  main.py
  bootstrap.py
  settings.py
```

第一阶段也可以由 backend-service bootstrap 启动和监督本机 broker 进程，避免过早增加远程部署单元。

## 分期实现

### 第 0 阶段：规则和接口模型

- 定义 BufferRef、FrameRef 和 BufferLease 的 Pydantic 模型。
- 在 image reference 解析层保留旧输入兼容。
- 明确 mmap 文件目录、TTL、容量和清理规则。
- 文档和测试先覆盖 schema、序列化和旧输入兼容。

### 第 1 阶段：mmap 普通文件池与本地 gateway

- 实现固定容量 mmap pool。
- 实现 allocate、write、read、release、expire。
- 支持 preview run 和 workflow runtime 读取 BufferRef。
- YOLOX detection 节点通过 PublishedInferenceGateway 调用已发布推理服务。
- 保留 HTTP/base64/object_key 输入，进入内部执行前可转换为 BufferRef。

当前主干已完成上述基础能力。memory image-ref 在存在 broker writer 时会先写入 LocalBufferBroker direct mmap 数据面，再以 BufferRef 调用 PublishedInferenceGateway；storage、buffer 和 frame image-ref 会按引用传递给长期运行的 deployment worker。

### 第 2 阶段：deployment worker BufferRef 输入增强

- 推理 worker 支持从 BufferRef 读取 raw image。
- health 指标暴露当前 broker 连接状态和 buffer 输入统计。
- infer 结果支持结构化返回，预览图可选写回 BufferRef。

当前主干已经具备 deployment worker 读取 BufferRef / FrameRef 的基础路径，并会在 deployment health 中暴露 LocalBufferBroker 接入状态、buffer/frame 输入计数和最近 broker 错误；预览图写回 BufferRef 和更完整的输入统计仍在后续阶段。

### 第 3 阶段：ring buffer channel

- 为连续帧输入源创建固定 ring channel。
- 支持 latest、strict、drop-oldest、drop-newest 和 block-with-timeout 策略。
- TriggerSource 可把 ZeroMQ、相机桥接或上位机高速输入映射为 FrameRef。
- WorkflowRun 创建时可把 FrameRef 固定为 BufferRef。

当前主干已经具备最小 ring buffer channel：broker client 先创建固定容量 channel，再通过 allocate-frame、direct mmap write、commit-frame 发布 FrameRef；读取侧先 validate-frame-ref，再按 FrameRef 的 path、offset 和 size 直接读取 mmap 文件。完整 TriggerSource 接入、read policy 和 FrameRef 固定为普通 BufferRef 仍在后续阶段。

### 第 4 阶段：长期运行增强

- broker 进程独立 supervisor。
- broker registry 恢复和目录扫描清理。
- 指标、告警、配额和可视化面板。
- 按部署形态选择 mmap、shared memory 或后续 GPU IPC backend。

当前主干已经具备 broker process supervisor、基础 pool 状态指标、手动 expire_leases 触发入口、周期性 expire loop、recent_error 记录和 health API 摘要；registry 恢复、目录扫描清理和配额仍在后续阶段。

## 稳定性要求

按年运行的核心不是 mmap 本身，而是容量、租约和恢复机制。

必须具备：

- 固定容量池，禁止无界创建 mmap 文件。
- TTL 和 owner heartbeat，支持进程崩溃后的孤儿 lease 回收。
- broker epoch，客户端检测 broker 重启后重新申请或放弃旧引用。
- file generation，避免旧 BufferRef 误读复用后的区间。
- 背压策略，池满时按配置拒绝、丢帧或短等待。
- 启动扫描，清理没有 registry 的旧 mmap 文件。
- 指标暴露，覆盖容量、租约、丢帧、过期、等待和清理次数。
- 调试开关，可把特定 BufferRef 异步保存为 ObjectStore 文件。

## 性能预期

Broker + mmap 文件池主要减少三类成本：

- base64 编解码成本
- JSON 大字段序列化成本
- 进程间重复复制大图成本

第一阶段的性能目标应设为稳定降低数据搬运开销，而不是追求零拷贝。实际推理链仍可能因为图像解码、颜色转换、resize、GPU H2D 和 D2H 等步骤产生必要复制。

## 风险和约束

- mmap 引用只在本机有效，不能跨主机传递。
- 文件路径不应作为公开 API 的长期字段，跨进程 payload 应使用 BufferRef 规则。
- ring buffer 默认会带来丢帧或覆盖风险，必须由输入源明确策略。
- mmap 文件池不能替代 ObjectStore；需要审计和复现的数据仍应保存到 ObjectStore。
- broker 崩溃恢复后，旧 BufferRef 必须通过 epoch 或 generation 判定失效。

## 推荐决策

- 第一阶段采用 LocalBufferBroker + mmap 文件池。
- ring buffer 作为 mmap 文件池上的高频输入模式，不作为所有输入的默认模式。
- ZeroMQ 保持为高速外部接入和触发入口之一，不作为本机内部大图数据面的主方案。
- workflow 节点只依赖 ImageRef / BufferRef / FrameRef 和 PublishedInferenceGateway，不直接依赖 mmap 实现。
- 已发布推理服务继续作为长期稳定 worker，workflow preview 和 runtime 继续保持独立隔离。