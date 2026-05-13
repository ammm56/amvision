# WorkflowTriggerSource 接口

## 文档目的

本文档用于收口 workflow 外部触发入口的资源边界、第一阶段已实现接口和后续协议 adapter 开发边界。

第一阶段已经提供 TriggerSource 合同、持久化、协议中立 mapper/submitter/result dispatcher、REST 管理控制面、TriggerSourceSupervisor 与 ZeroMQ adapter 的第一版协议边界。ZeroMQ adapter 已支持 multipart envelope + content 到 BufferRef payload 的转换、REP 监听骨架、REST enable/disable 启停和 backend-service 启动时恢复 enabled trigger source。MQTT、gRPC、PLC、IO 和传感器 adapter 尚未接入。

## 当前边界

- 当前 workflow runtime 已落地的正式执行入口仍是 HTTP 控制面，TriggerSource 内部提交也复用同一套 runtime service 语义。
- 当前已经提供 `/api/v1/workflows/trigger-sources` 管理 API，用于创建、查询、启用、停用和读取 health。
- 04/05 保持为 HTTP base64 workflow app 调试示例；06/07 单独保存同 app HTTP base64 + ZeroMQ image-ref 调试示例，避免把两类入口混在同一目录中。
- TriggerSource 只提交协议原生输入，不负责把 `image-ref.v1` 主动转换成 `image-base64.v1`，也不负责补出本地图片、相机帧或其他节点级输入。
- 后续 PLC、MQTT、ZeroMQ、gRPC、IO 变化、传感器读取、schedule 和 Webhook 触发，可以继续扩展为 WorkflowTriggerSource。
- 面向设备上位机、MES、采集程序和调试脚本的外部调用方 SDK 规划见 [docs/api/trigger-source-sdks.md](trigger-source-sdks.md)。
- 传感器读数、阈值越界、状态翻转和采样结果本身就是物理世界进入 workflow 的直接触发入口，不应只被视为运行中节点的附属输入。
- 外部触发入口与节点图本身分层：触发源负责监听、过滤、去重和创建 WorkflowRun；runtime 负责执行。
- 当前草案不把“首节点轮询外部世界”作为默认触发模型。
- ZeroMQ 可作为 workstation 或 standalone 场景下的高速外部触发和图片提交入口之一，不等同于本机内部大图数据交换层。
- 该资源属于 workflow runtime 外部触发调用层；第一阶段管理 API 已进入 [docs/api/current-api.md](current-api.md) 总览。

## 资源定位

- WorkflowTriggerSource 表示一类可持续监听外部事件并创建 WorkflowRun 的受控入口。
- 触发源应绑定到 WorkflowAppRuntime 或其固定 snapshot，不直接绑定编辑态 preview。
- 触发源的职责是把外部事件转换成 run 创建请求、输入映射和执行元数据。
- 触发源不替代 custom node，也不替代运行中节点对 PLC、MQTT、传感器或其他外部系统的主动读取行为。
- 如果执行过程中需要再次读取外部状态，应使用节点；如果某个外部事件到达后才启动整条 workflow，应使用触发源。

## 为什么默认绑定 WorkflowAppRuntime

- 触发源面向生产态正式执行，应绑定已经固定 snapshot、可启动、可观测、可重启的 WorkflowAppRuntime，而不是直接追随可变的 application 保存文件。
- 如果直接绑定 application，后续继续保存同名 application 时，触发源的实际执行内容会隐式漂移，不利于现场稳定运行、回滚和审计。
- WorkflowAppRuntime 已经承接启动状态、健康状态、实例隔离和超时等运行时语义，触发源只需要负责把外部事件转成 WorkflowRun，不应再复制一套运行时管理逻辑。
- 触发源绑定 runtime 后，无论入口来自 HTTP、PLC、MQTT、传感器还是其他协议，最终都能统一落到同一套 WorkflowRun 和 runtime instance 执行链路。
- preview 或未发布 application 仍适合用于编辑态联调，不适合作为长期物理触发入口的默认绑定对象。

## 接入原则

- 外部触发优先通过 node pack、集成边界或独立桥接进程接入，不直接侵入核心 runtime。
- 触发源创建 run 后，正式执行统一落到 WorkflowRun，不为不同协议再拆另一类正式执行资源。
- 触发源与 sync invoke、async runs 是两层概念：前者描述 run 从哪里来，后者描述 run 如何提交和观察。
- 对于 PLC、IO 变化、传感器或其他强副作用场景，触发层应优先承担去抖、幂等键提取、超时和回执策略。
- 如果某个入口本质上是长期监听器，不应由 workflow 图中的首节点无限轮询或长时间 sleep 代替。

## 与 Workflow 图和应用的关系

- WorkflowGraphTemplate 定义节点图、节点参数、输入端口和输出端口，不直接关心请求来自 HTTP、ZeroMQ、PLC、IO 还是本地 adapter。
- FlowApplication 把图的输入输出端口发布成稳定 binding，例如 `request_image_base64`、`request_image_ref`、`deployment_request` 和 `http_response`。
- WorkflowAppRuntime 固定 application snapshot 和 template snapshot，是现场长期运行的宿主。
- WorkflowTriggerSource 绑定 WorkflowAppRuntime，并把外部事件映射到 application 的 `input_bindings`，不修改 workflow 图。
- 同一张图可以同时被 HTTP invoke、async run 和后续 trigger source 使用；区别只在输入从哪里来、以 sync 还是 async 提交，以及回执如何返回。
- 如果同一张图既要接 HTTP base64，又要接 ZeroMQ image-ref，应在图里显式发布多个 binding，或增加转换节点把两条入口汇到共同下游节点，而不是把转换逻辑塞进 TriggerSource。

常见图链路可以保持为：`request_image_base64` 和 `request_image_ref` 两条入口先在图里汇合，再进入 YOLOX detection 节点、OpenCV 后处理节点和 HTTP Response 输出节点。HTTP Response 输出节点的结果会出现在 `outputs["http_response"] = {"status_code": 200, "body": ...}`，由同步调用或触发源回执层决定是否直接返回给调用方。

## 触发调用层总体框架

触发调用层位于外部协议和 WorkflowAppRuntime 之间。它不是新的 workflow 执行器，也不是某个协议的专用实现，而是一组可替换的 adapter、mapper 和 result dispatcher。

```text
REST / WebSocket / ZeroMQ / gRPC / MQTT / PLC / IO / sensor
  |
  v
ProtocolAdapter
  |
  v
TriggerEventNormalizer
  |
  v
InputBindingMapper
  |
  v
WorkflowSubmitter
  |
  v
WorkflowAppRuntime / WorkflowRun
  |
  v
ResultDispatcher
  |
  v
HTTP response / ZeroMQ reply / gRPC response / MQTT publish / PLC write / WebSocket event
```

建议拆成以下模块：

- ProtocolAdapter：负责协议监听、连接管理、解包、基础鉴权、超时和关闭。
- TriggerEventNormalizer：把不同协议消息转换成统一 TriggerEvent，生成 trace_id、event_id、idempotency_key 和 payload 摘要。
- InputBindingMapper：把 TriggerEvent 映射成 FlowApplication 的 input_bindings，不直接改 workflow 图。
- WorkflowSubmitter：按 submit_mode 调用 runtime invoke 或创建 WorkflowRun。
- ResultDispatcher：读取 workflow 输出绑定，按 result_mapping 转换成协议回执、发布消息或状态写回。
- TriggerSourceSupervisor：负责 trigger source 的启动、停止、健康检查、错误记录和长跑指标。

该分层使 ZeroMQ、gRPC、MQTT、PLC、IO 和传感器入口可以共用同一套 run 创建、输入映射、结果回执和审计规则。后续新增协议时，只新增 adapter 和少量 transport_config schema，不复制 runtime 执行逻辑。

## REST API 基线入口

触发调用层的 REST 执行入口应复用当前已经完成本地调试的 FastAPI workflow runtime HTTP API，不再另起一套并行 HTTP 执行接口。

当前可作为基线的入口包括：

- `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke`：同步调用已经启动的 WorkflowAppRuntime。
- `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke/upload`：multipart 同步调用，适合 HTTP 调试或低频图片上传。
- `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs`：创建异步 WorkflowRun。
- `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs/upload`：multipart 异步 WorkflowRun。
- `GET /api/v1/workflows/runs/{workflow_run_id}`：查询 WorkflowRun 结果。
- `POST /api/v1/workflows/runs/{workflow_run_id}/cancel`：取消 WorkflowRun。

因此，REST 在触发调用层里有两类职责：

- 执行基线入口：沿用现有 invoke 和 runs API，继续作为 Postman、本地调试、普通外部系统集成和低频同步调用入口。
- 触发源管理入口：后续新增 `/api/v1/workflows/trigger-sources`，只负责创建、启停、查询和观测 TriggerSource，不替代现有 invoke 和 runs API。

ZeroMQ、gRPC、MQTT、PLC、IO 和传感器 adapter 在内部提交 workflow 时，也应优先复用与现有 REST invoke/runs 相同的 `WorkflowRuntimeInvokeRequest`、`WorkflowRun` 和 `WorkflowAppRuntime` 语义。这样可以保证 HTTP 已验证路径、ZeroMQ 高速路径和后续协议路径最终落到同一套运行时行为。

## 图编排中的入口和出口

触发入口应在界面图编排中明确显示，但不应把长期协议监听器放进 workflow worker 内部执行。

推荐 UI 表达方式：

- 在 workflow app 的图边界显示入口节点，例如 `App Entry`、`ZeroMQ Frame Request`、`HTTP Invoke`、`PLC Ready Signal`。
- 入口节点对应 FlowApplication 的输入 binding，并连接到 `core.io.template-input.image`、`core.io.template-input.value` 或 `core.io.template-input.object` 这类模板输入节点。
- 协议配置、端口、topic、PLC 地址、去抖、幂等和 submit_mode 属于 WorkflowTriggerSource 资源，不写入可复用 WorkflowGraphTemplate。
- 同一张 workflow 图可以被多个入口复用，例如 HTTP 调试入口绑定 `request_image_base64`，ZeroMQ 高速入口绑定 `request_image_ref`，然后在图里通过显式转换节点汇合。
- 图中应显示输出节点，例如 `Response Envelope`、`HTTP Response`、后续的 `Workflow Result`、`PLC Write Result` 或 `MQTT Report`。

这样可以同时满足两点：操作界面能清楚看到 workflow app 从哪里开始、结果到哪里结束；运行时实现仍保持协议监听、数据面和 workflow 执行器三者隔离。

## 结果返回与回执适配

触发入口和结果返回需要成对设计。不同协议的回执能力不同，因此 workflow 输出节点不应只绑定 HTTP 语义。

推荐把结果分成两层：

- 业务结果层：由 workflow 图中的 `response-envelope`、检测结果、保存文件引用或后续 `workflow-result` 节点生成稳定输出。
- 协议回执层：由 ResultDispatcher 根据 trigger source 的 result_mapping 转换为 HTTP response、ZeroMQ reply、gRPC response、MQTT publish、PLC register write、IO output 或 WebSocket event。

当前 `core.output.http-response` 可以继续作为 HTTP invoke 的默认输出，`core.output.response-envelope` 可以作为协议中立的业务包体。后续建议补一个更通用的 `workflow-result.v1` payload 或 `core.output.workflow-result` 节点，用于表达以下内容：

- status：succeeded、failed、accepted 或 partial
- code 和 message
- data：结构化业务结果
- files：需要长期保留的 ObjectStore 文件引用
- metrics：耗时、模型版本、检测数量等摘要
- trace_id 和 event_id

回执模式建议按 trigger source 配置：

| result_mode | 说明 | 典型协议 |
| --- | --- | --- |
| sync-reply | workflow 完成后在同一连接返回结果 | HTTP、gRPC、ZeroMQ REQ/REP |
| accepted-then-query | 接收后立即返回 run id，完成后通过 REST 查询 | HTTP、Webhook、部分 PLC/MQTT 场景 |
| async-report | 完成后主动发布或写回结果 | MQTT、ZeroMQ PUB、Webhook callback、PLC write、IO output |
| event-only | 只写 WorkflowRun 和 WebSocket/事件流，不向触发方返回业务结果 | schedule、sensor、部分 IO 场景 |

同步协议如果需要即时推理结果，应显式配置 result_binding，例如 `http_response` 或 `workflow_result`。异步入口默认先确认接收和 run 创建，再由 ResultDispatcher 或后续回查接口处理完成结果。

## ZeroMQ 优先实现边界

下一阶段可以优先实现 ZeroMQ，但实现应落在通用触发调用层框架中。

ZeroMQ adapter 的第一阶段建议支持两类消息：

- 单次请求：适合同步高速推理，外部进程发送 metadata 和一张图片，adapter 写入 LocalBufferBroker 后调用 WorkflowAppRuntime，完成后返回 ZeroMQ reply。
- 连续帧：适合高节拍输入，adapter 写入 ring buffer channel，按策略创建 sync invoke 或 async WorkflowRun。

ZeroMQ 消息不应把大图继续包装成 JSON base64。推荐 multipart 结构：

```text
frame 0: JSON envelope，包含 trigger_source_id、event_id、trace_id、input mapping key、media_type、shape、dtype、pixel_format
frame 1: image bytes 或 frame bytes
frame n: 可选附加二进制数据
```

adapter 收到二进制帧后先写入 LocalBufferBroker，随后把 BufferRef 或 FrameRef 映射到 application input_bindings。这个映射停留在协议入口层，不继续替图做 `image-ref -> image-base64`、本地磁盘读图或相机取帧。同步返回时，ResultDispatcher 读取 workflow 输出绑定，转换成 JSON reply 或 multipart reply；需要返回图片时，优先返回 ObjectStore 引用或受控 BufferRef 摘要，不把本机 mmap path 当成长期外部结果。

ZeroMQ 第一阶段不直接实现 PLC、MQTT、gRPC 等协议，但需要先落下同一套 TriggerSource 合同、adapter 接口、输入映射、结果映射、health 和审计字段，避免后续每个协议各写一套调用链。

## 调用方 SDK 边界

本地高速调用方默认通过 ZeroMQ 触发 backend-service 中已经启用的 TriggerSource。设备上位机软件、MES、采集程序和现场桥接进程不应直接拼 ZeroMQ multipart 帧、错误 reply 和 retry 规则，推荐通过外部 SDK 使用。

SDK 的标准职责是：

- 封装 ZeroMQ envelope、图片 bytes 发送和 TriggerResult 解析。
- 封装 event_id、trace_id、metadata、timeout、连接重建和统一错误码。
- 提供可选 REST control client，用于 health 检查、enable/disable 和 run 查询。
- 提供 06/07 同 app HTTP base64 + ZeroMQ image-ref 的真实图片调用示例，并说明图内节点负责转换。

SDK 不直接写 LocalBufferBroker，不直接调用 workflow worker，不访问数据库，也不把客户现场硬件驱动写进通用包。

仓库根目录建议使用 `sdks/` 保存外部 SDK，与 `backend/`、`frontend/` 和 `custom_nodes/` 分离。第一优先级是 C# / .NET SDK，兼容 .NET Framework 上位机软件和 .NET Core / .NET 应用；随后补 Python、Go 和 C。详细目录、调用流程和版本规则见 [docs/api/trigger-source-sdks.md](trigger-source-sdks.md)。

## 图片输入的两条入口路径

### HTTP JSON 同步调用

HTTP JSON invoke 是当前已公开、最容易调试的入口。调用方把图片按 `image-base64.v1` 放到 `input_bindings`，runtime 会把输入转换成 execution memory image-ref，后续推理节点在存在 LocalBufferBroker writer 时会再转换成 BufferRef 调用已发布推理服务。

```json
{
  "input_bindings": {
    "request_image": {
      "image_base64": "<base64 image bytes>",
      "media_type": "image/png"
    },
    "deployment_request": {
      "value": {
        "deployment_instance_id": "deployment-instance-1"
      }
    }
  },
  "execution_metadata": {
    "trigger_source": "sync-http-api",
    "trace_id": "trace-1"
  },
  "timeout_seconds": 5
}
```

这条路径可以完成“base64(img) 触发图片输入调用 -> 节点调用推理服务 -> 返回推理结果 -> 后续 OpenCV 处理 -> 默认 HTTP API 响应”。它适合调试、普通外部系统集成、低频同步请求和 Postman 示例，不适合作为高节拍大图热路径，因为 base64 和 JSON 都会产生额外复制和编解码成本。

### 本地 adapter / TriggerSource 高速输入

高速入口不应把大图塞进 trigger source 控制消息。推荐做法是本地 adapter 收到图像或帧后先写入 LocalBufferBroker，再把 `FrameRef` 或 `BufferRef` 填入 runtime 的 `input_bindings`。

```json
{
  "input_bindings": {
    "request_image": {
      "transport_kind": "frame",
      "frame_ref": {
        "format_id": "amvision.frame-ref.v1",
        "stream_id": "line-a-camera-1",
        "sequence_id": 1024,
        "buffer_id": "image-small:frame:line-a-camera-1:0",
        "path": "data/buffers/image-small/pool-001.dat",
        "offset": 0,
        "size": 6220800,
        "shape": [1080, 1920, 3],
        "dtype": "uint8",
        "layout": "HWC",
        "pixel_format": "BGR",
        "media_type": "image/raw",
        "broker_epoch": "epoch-1",
        "generation": 15
      }
    },
    "deployment_request": {
      "value": {
        "deployment_instance_id": "deployment-instance-1"
      }
    }
  },
  "execution_metadata": {
    "trigger_source": "zeromq-topic",
    "stream_id": "line-a-camera-1",
    "trace_id": "frame-1024"
  }
}
```

本地 adapter 可以把这份请求交给 runtime invoke 或 run 创建逻辑。sync 模式适合同机短链路、调用方需要即时结果的场景；async 模式适合长期监听、排队、断线后回查和高频事件削峰。

FrameRef 的有效期很短，适合“立即执行一条 runtime 调用”。如果执行可能排队或后续节点需要稳定读取同一帧，触发层应把 FrameRef 固定为普通 BufferRef，或把关键图片保存到 ObjectStore 后再提交 run。该转换属于受控本地 adapter 或后续 TriggerSource 的职责，不属于 workflow 图中节点的职责。

## 06/07 ZeroMQ 双输入独立调试

04/05 继续保留 HTTP base64 调试路径；06/07 单独承接同 app HTTP base64 + ZeroMQ image-ref 双入口调试路径。这样可以把“图级输入设计”和“协议触发层”分开：ZeroMQ adapter 只写 LocalBufferBroker 并提交 `image-ref.v1`，后续是否需要转成 `image-base64.v1`、是否需要从磁盘读图、是否需要通过相机节点抓一帧，都由 workflow 图和节点自己决定。

### 服务侧准备

1. 保存同时支持 HTTP base64 和 ZeroMQ image-ref 的 template 和 application：
  - 06：`docs/api/examples/workflows/06-yolox-deployment-infer-opencv-health-zeromq-image-ref/save-template.request.json` 与 `save-application.request.json`
  - 07：`docs/api/examples/workflows/07-opencv-process-save-image-zeromq-image-ref/save-template.request.json` 与 `save-application.request.json`
2. 创建并启动对应 WorkflowAppRuntime：
  - 06 runtime 创建请求体：`docs/api/examples/workflows/06-yolox-deployment-infer-opencv-health-zeromq-image-ref/app-runtime.create.request.json`
  - 07 runtime 创建请求体：`docs/api/examples/workflows/07-opencv-process-save-image-zeromq-image-ref/app-runtime.create.request.json`
  - `workflowRuntimeId` 应使用上一步创建响应里返回的 `workflow_runtime_id`，并先调用 runtime start 确认 health 为 running
3. 使用 TriggerSource 管理 API 创建 ZeroMQ TriggerSource：
  - 06 请求体：`docs/api/examples/workflows/06-yolox-deployment-infer-opencv-health-zeromq-image-ref/trigger-source.create.request.json`
  - 07 请求体：`docs/api/examples/workflows/07-opencv-process-save-image-zeromq-image-ref/trigger-source.create.request.json`
  - 如果同名 TriggerSource 之前已经创建且需要改绑新的 WorkflowAppRuntime，可先调用 disable，再调用 `DELETE /api/v1/workflows/trigger-sources/{trigger_source_id}` 删除旧资源，然后重新 create。
4. 调用 `POST /api/v1/workflows/trigger-sources/{trigger_source_id}/enable` 启动 adapter。
5. 调用 `GET /api/v1/workflows/trigger-sources/{trigger_source_id}/health`，确认 `health_summary.adapter_running=true`。

### 图级边界

- 如果同一个 workflow app 既要接 HTTP base64，又要接 ZeroMQ image-ref，应在图里发布两个 binding，或显式增加 `image-ref -> image-base64` 节点后再接到原来的 base64 输入链路。
- 如果触发源只有 PLC 寄存器值、IO 状态或其他数值输入，后续图片从哪里来，也应由图里的本地图片加载节点、相机抓帧节点或 custom node 决定，不由 TriggerSource 补出图片。
- TriggerSource 不负责图级转换，也不替下游节点决定后续输入类型。

### C# SDK 调用

07 OpenCV 保存图片示例：

```powershell
dotnet run --project sdks/dotnet/examples/ZeroMqImageInvoke/ZeroMqImageInvoke.csproj -- tcp://127.0.0.1:5556 zeromq-trigger-source-07 <image_path> image/png
```

06 YOLOX 推理和 OpenCV 绘制示例需要已有 `deployment_instance_id`：

```powershell
dotnet run --project sdks/dotnet/examples/ZeroMqImageInvoke/ZeroMqImageInvoke.csproj -- tcp://127.0.0.1:5555 zeromq-trigger-source-06 <image_path> image/png <deployment_instance_id>
```

成功时 C# 示例输出应包含：

```text
state=succeeded
workflow_run_id=<workflow_run_id>
event_id=<event_id>
```

06 的第五个参数会写入 envelope payload 的 `deployment_request.value.deployment_instance_id`。TriggerSource 创建请求中的 `input_binding_mapping.deployment_request.source` 会读取该字段，并映射到 workflow app 的 `deployment_request` input binding。

## 高速推理调用链路

高速调用链路建议固定为以下顺序：

```text
本地输入 adapter / TriggerSource
        |
        | 写入 LocalBufferBroker ring channel 或普通 buffer pool
        v
FrameRef / BufferRef
        |
        | 映射到 FlowApplication input_bindings
        v
WorkflowAppRuntime invoke 或 WorkflowRun
        |
        v
workflow worker 子进程
        |
        | PublishedInferenceGateway
        v
backend-service 持有的长期 deployment worker
        |
        v
YOLOX detections / runtime_session_info
        |
        v
OpenCV / rule / response nodes
        |
        v
http-response 输出或 WorkflowRun outputs
```

这条链路里 workflow 图仍然只表达业务处理顺序：输入图片、调用推理、后处理、组装响应。TriggerSource 只负责把外部事件变成输入绑定和执行元数据，LocalBufferBroker 只负责本机内部大图数据面，PublishedInferenceGateway 只负责复用已启动 deployment 推理服务。

## 推荐触发类型

- plc-register：PLC 寄存器点位变化或条件满足后触发
- mqtt-topic：订阅指定 topic 并按消息内容创建 run
- zeromq-topic：ZeroMQ 主题、请求或高速图像提交触发
- grpc-method：由外部系统通过 gRPC 方法调用触发
- io-change：离散 IO 状态变化触发
- sensor-read：传感器读数达到阈值、状态翻转或采样规则命中时触发
- schedule：按固定频率或定时计划触发
- webhook：外部系统 HTTP 回调触发

这些类型是资源草案中的推荐分类，不表示当前主干已经全部实现。

## 不建议混用的模式

- 用 workflow 首节点长期轮询 PLC、MQTT 或传感器，等待外部条件成立后再继续执行整张图
- 让 runtime instance 在没有 WorkflowRun 的情况下长期承担外部协议订阅器职责
- 为不同触发协议重复创建多套 execute、task 或 run 资源语义
- 把传感器阈值判断既做成长期触发器，又在图内首节点重复做同一轮询，导致职责和去重边界混乱

## 接口入口

- 版本前缀：/api/v1
- 资源分组：/workflows
- 资源路径：/api/v1/workflows/trigger-sources
- 当前状态：第一阶段 REST 管理控制面已实现；ZeroMQ adapter 已接入 backend-service lifecycle，其他协议 adapter 尚未接入

## 鉴权草案

- list 和 get 建议使用 workflows:read
- create、delete、enable 和 disable 建议使用 workflows:write

当前阶段不单独拆 trigger-sources 专用 scope，避免过早把控制面权限做复杂。

## 资源字段草案

- trigger_source_id
- project_id
- display_name
- trigger_kind，当前合同取值为 plc-register、mqtt-topic、zeromq-topic、grpc-method、io-change、sensor-read、schedule、webhook、http-api
- workflow_runtime_id
- submit_mode，取值建议为 sync 或 async，可按触发源逐条配置
- enabled
- transport_config
- match_rule
- input_binding_mapping
- result_mapping
- default_execution_metadata
- ack_policy，可选
- result_mode，可选
- reply_timeout_seconds，可选
- debounce_window_ms，可选
- idempotency_key_path，可选
- last_triggered_at
- last_error
- metadata
- health_summary
- created_at
- updated_at
- created_by

## submit_mode 为什么默认更偏 async

- trigger source 的 submit_mode 应保持可配置，不能把所有外部触发都强行收口成 async，也不能假设它们都适合同步等待到底。
- 从默认取向上更建议 async，因为 PLC、MQTT、传感器、IO 变化、schedule 或外部回调触发，通常更接近“事件到达后创建一条正式执行记录”，而不是“当前调用方必须一直阻塞等待结果”。
- async 更适合承接物理世界和外部系统带来的长时间执行、排队、取消、断线后回查和脱离当前连接继续运行的需求。
- sync 更适合少量低时延、短链路、调用方明确需要即时结果且能稳定持有连接的触发入口，例如某些受控 gRPC 调用或同机内部快速联动。
- 即使 trigger source 支持 sync，也应作为显式选择，而不是默认行为；默认偏 async 可以避免把外部触发入口误做成新的长阻塞控制面。

## submit_mode 与 trigger_kind 的推荐搭配

| trigger_kind | 推荐 submit_mode | 说明 |
| --- | --- | --- |
| plc-register | async 优先 | 更常见于设备侧条件成立后发起正式执行，适合排队、回查和断线后继续运行 |
| mqtt-topic | async 优先 | 消息订阅通常是事件驱动入口，不适合把订阅侧连接长期阻塞到执行结束 |
| zeromq-topic | async 优先；少量场景可用 sync | 可承接上位机或本地桥接进程的高速触发和图像提交；如果调用方明确要求即时结果且链路可控，可显式配置为 sync |
| grpc-method | sync 或 async 都可 | 如果调用方明确要求即时结果且链路可控，可用 sync；如果执行可能较长或需要排队，优先 async |
| io-change | async 优先 | 离散 IO 变化更接近事件触发，通常不要求当前信号发送侧同步等待完整结果 |
| sensor-read | async 优先 | 传感器阈值命中、状态翻转或采样规则命中后，通常只需要稳定触发和后续回查 |
| schedule | async | 定时任务或固定频率任务默认不应阻塞调度器线程等待执行到底 |
| webhook | async 优先 | 外部系统回调通常更适合快速确认接收，再通过 WorkflowRun 回查结果 |

补充说明：

- submit_mode 是逐条 trigger source 的配置项，不由 trigger_kind 硬编码决定。
- 表中的推荐搭配用于表达默认取向，不限制现场按具体延时、幂等、回执和上位系统要求改成 sync。
- 当某类触发入口被配置为 sync 时，应额外确认调用方连接时长、超时策略和失败回传语义都能稳定承受同步等待。

## 回执与幂等建议

- webhook、MQTT、PLC 和传感器触发都应优先把“已接收并成功创建 WorkflowRun”作为回执边界，而不是把“整条 workflow 已执行完成”作为默认 ack 边界。
- 对 webhook 和 MQTT 这类可能重投的入口，应显式提供幂等键来源，例如消息 id、事件序号、时间窗内业务键或 payload 路径。
- 对 PLC、IO 和传感器这类物理世界触发，应优先在触发层承担去抖、边沿检测、阈值去重和短时间重复抑制，避免同一物理变化被放大成多条 WorkflowRun。
- 当 trigger source 被配置为 sync 时，仍建议先完成幂等判断和 run 创建，再决定是否同步等待结果，避免把回执、去重和执行结果混成同一个边界。

## 接口清单草案

### POST /api/v1/workflows/trigger-sources

- Content-Type：application/json
- 建议需要 workflows:write
- 用途：创建一条可持续监听外部事件的 WorkflowTriggerSource

#### 请求字段

- trigger_source_id
- project_id
- display_name
- trigger_kind
- workflow_runtime_id
- submit_mode
- enabled
- transport_config
- match_rule
- input_binding_mapping
- result_mapping
- default_execution_metadata
- ack_policy，可选
- result_mode，可选
- reply_timeout_seconds，可选
- debounce_window_ms，可选
- idempotency_key_path，可选
- metadata

### GET /api/v1/workflows/trigger-sources

- 建议需要 workflows:read
- 用途：列出当前 Project 下的 WorkflowTriggerSource 摘要

#### 列表项建议字段

- trigger_source_id
- display_name
- trigger_kind
- workflow_runtime_id
- submit_mode
- enabled
- last_triggered_at
- last_error

### GET /api/v1/workflows/trigger-sources/{trigger_source_id}

- 建议需要 workflows:read
- 用途：查询单条 WorkflowTriggerSource 的完整配置和最近状态

### DELETE /api/v1/workflows/trigger-sources/{trigger_source_id}

- 建议需要 workflows:write
- 用途：删除一条 trigger source；如果 adapter 已启动，会先停止监听
- 删除后可重新使用同一个 trigger_source_id 创建新的 TriggerSource

### POST /api/v1/workflows/trigger-sources/{trigger_source_id}/enable

- 建议需要 workflows:write
- 用途：启用一条 trigger source，开始接收外部触发
- 当前要求绑定的 WorkflowAppRuntime 已经处于 running 状态
- trigger_kind 已注册 adapter 时，enable 会启动对应 adapter，并在 health_summary 中返回 adapter_configured、adapter_running 和计数信息
- trigger_kind 尚未注册 adapter 时，enable 只更新管理态，observed_state 仍可能保持 stopped

### POST /api/v1/workflows/trigger-sources/{trigger_source_id}/disable

- 建议需要 workflows:write
- 用途：停用一条 trigger source，停止接收新的外部触发
- trigger_kind 已注册 adapter 时，disable 会停止对应 adapter

### GET /api/v1/workflows/trigger-sources/{trigger_source_id}/health

- 建议需要 workflows:read
- 用途：查询 trigger source 的启用状态、期望状态、观测状态、最近错误和健康摘要

## 最小请求 JSON 草案

```json
{
  "trigger_source_id": "plc-line-a-ready",
  "project_id": "project-1",
  "display_name": "PLC Line A Ready",
  "trigger_kind": "plc-register",
  "workflow_runtime_id": "workflow-runtime-1",
  "submit_mode": "async",
  "enabled": true,
  "transport_config": {
    "driver": "modbus-tcp",
    "endpoint": "192.168.1.10:502"
  },
  "match_rule": {
    "register": "D100",
    "equals": 1
  },
  "input_binding_mapping": {
    "request_signal": {
      "source": "payload.value"
    }
  },
  "result_mapping": {
    "result_binding": "workflow_result",
    "result_mode": "accepted-then-query"
  },
  "default_execution_metadata": {
    "trigger_source": "plc-register"
  },
  "ack_policy": "ack-after-run-created",
  "debounce_window_ms": 200,
  "idempotency_key_path": "payload.sequence_id",
  "metadata": {
    "line_id": "line-a"
  }
}
```

## 推荐实现顺序

第一阶段优先收口框架，不急着铺满所有协议。

1. 把现有 FastAPI invoke、runs、upload、run 查询和 cancel API 明确为 REST 执行基线入口。
2. 定义 WorkflowTriggerSource、TriggerEvent、TriggerResult、InputBindingMapping 和 ResultMapping 合同。
3. 实现 TriggerSourceService、ProtocolAdapter 接口、InputBindingMapper、WorkflowSubmitter、ResultDispatcher 和 TriggerSourceSupervisor 骨架。
4. 通过 REST API 管理 trigger source 的创建、启停、health 和最近错误。
5. 实现 ZeroMQ adapter 的最小 sync-reply 链路，复用 LocalBufferBroker 写入 BufferRef，再调用已有 WorkflowAppRuntime invoke 语义。
6. 实现外部调用方 SDK，优先交付 C# / .NET SDK，再补 Python、Go 和 C。
7. 增加 ZeroMQ async 或 ring frame 链路，接入 WorkflowRun 持久化和回查。
8. 在图编排界面显示 App Entry 和 App Result 边界节点，绑定到 FlowApplication 输入输出。
9. 再按现场优先级补 MQTT、gRPC、PLC、IO 和传感器 adapter。

## 详细开发步骤

### 第 1 步：固化 REST 执行基线

目标是确认触发调用层的执行语义完全沿用现有 FastAPI workflow runtime API。

开发内容：

- 保持现有 `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke` 作为同步执行基线。
- 保持现有 `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs` 作为异步执行基线。
- 保持 `invoke/upload` 和 `runs/upload` 作为 HTTP multipart 图片调试入口。
- 明确后续 TriggerSource 内部提交时复用 `WorkflowRuntimeInvokeRequest`、`WorkflowRuntimeService.invoke_workflow_app_runtime` 和 `WorkflowRuntimeService.create_workflow_run`，不通过本机 HTTP 回环调用自身。
- 给 00-05 workflow app 的 Postman 示例保留现有结构，作为后续 ZeroMQ adapter 的行为对照。

主要文件：

```text
backend/service/api/rest/v1/routes/workflow_runtime.py
backend/service/application/workflows/runtime_service.py
docs/api/postman/workflows/
docs/api/examples/workflows/
```

验收点：

- 已验证的 HTTP invoke、runs、upload、run 查询和 cancel 行为不变。
- TriggerSource 设计文档不引入第二套 HTTP 执行接口。
- 后续 adapter 提交 workflow 时能复用同一份 request shape 和结果 shape。

### 第 2 步：定义 TriggerSource 合同

目标是先稳定公开 JSON 形状和内部事件形状，再写协议 adapter。

开发内容：

- 新增 `WorkflowTriggerSourceContract`，描述触发源配置和状态。
- 新增 `TriggerEventContract` 或内部 `TriggerEvent`，描述协议事件进入平台后的统一格式。
- 新增 `TriggerResultContract` 或内部 `TriggerResult`，描述同步回执、异步接收和执行失败的统一结果。
- 新增 `InputBindingMappingContract`，描述外部 payload 到 FlowApplication input binding 的映射。
- 新增 `ResultMappingContract`，描述 workflow output binding 到协议回执的映射。
- 定义枚举：`trigger_kind`、`submit_mode`、`result_mode`、`ack_policy`、`desired_state`、`observed_state`。
- 合同先允许 `transport_config`、`match_rule`、`metadata` 使用对象字段，避免第一阶段为每个协议拆过细 schema。

建议字段：

```text
trigger_source_id
project_id
display_name
trigger_kind
workflow_runtime_id
submit_mode
enabled
desired_state
observed_state
transport_config
match_rule
input_binding_mapping
result_mapping
default_execution_metadata
ack_policy
result_mode
reply_timeout_seconds
debounce_window_ms
idempotency_key_path
last_triggered_at
last_error
health_summary
metadata
```

主要文件：

```text
backend/contracts/workflows/trigger_sources.py
backend/contracts/workflows/__init__.py
tests/test_workflow_trigger_source_contracts.py
```

验收点：

- 合同能序列化和反序列化 REST、ZeroMQ、PLC、MQTT 等触发源配置。
- 必填字段、空字符串、非法枚举和超时值有明确校验错误。
- `result_mapping` 可以表达 `http_response`、`workflow_result` 或其他输出 binding。

### 第 3 步：增加持久化资源

目标是让 TriggerSource 成为可管理资源，而不是临时配置文件。

开发内容：

- 新增领域对象 `WorkflowTriggerSource`。
- 新增仓储接口，支持 save、get、list、disable。
- 新增 SQLAlchemy ORM 表，保存配置、状态、最近错误和 health 摘要。
- 在 Unit of Work 中增加 `workflow_trigger_sources` 仓储属性。
- 在数据库 schema 初始化中导入新的 ORM 模块。
- 默认开发数据库继续走 SQLite create_all；正式迁移方案后续接 Alembic 时补 migration。

建议表字段：

```text
trigger_source_id TEXT PRIMARY KEY
project_id TEXT NOT NULL
display_name TEXT NOT NULL
trigger_kind TEXT NOT NULL
workflow_runtime_id TEXT NOT NULL
submit_mode TEXT NOT NULL
enabled BOOLEAN NOT NULL
desired_state TEXT NOT NULL
observed_state TEXT NOT NULL
transport_config JSON NOT NULL
match_rule JSON NOT NULL
input_binding_mapping JSON NOT NULL
result_mapping JSON NOT NULL
default_execution_metadata JSON NOT NULL
ack_policy TEXT
result_mode TEXT
reply_timeout_seconds INTEGER
debounce_window_ms INTEGER
idempotency_key_path TEXT
last_triggered_at TEXT
last_error TEXT
health_summary JSON NOT NULL
metadata JSON NOT NULL
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
created_by TEXT
```

主要文件：

```text
backend/service/domain/workflows/workflow_trigger_source_records.py
backend/service/domain/workflows/workflow_trigger_source_repository.py
backend/service/infrastructure/persistence/workflow_trigger_source_orm.py
backend/service/infrastructure/persistence/workflow_trigger_source_repository.py
backend/service/infrastructure/db/unit_of_work.py
backend/service/infrastructure/db/schema.py
```

验收点：

- 可保存、读取和按 project_id 列出 TriggerSource。
- JSON 字段在 SQLite 下可用，同时不绑定 SQLite 方言细节。
- 读取不存在资源时返回统一 ResourceNotFoundError。

### 第 4 步：实现应用服务骨架

目标是先完成协议无关的触发调用层核心，不直接进入 ZeroMQ 细节。

开发内容：

- 新增 `TriggerSourceService`，负责创建、更新、启用、停用、查询和 health 汇总。
- 新增 `ProtocolAdapter` 抽象，定义 start、stop、health 和协议接收回调的最小接口。
- 新增 `TriggerSourceSupervisor`，管理已启用触发源的 adapter 生命周期和事件提交流程。
- 新增 `InputBindingMapper`，把 TriggerEvent 映射为 `WorkflowRuntimeInvokeRequest.input_bindings`。
- 新增 `WorkflowSubmitter`，按 submit_mode 调用 `invoke_workflow_app_runtime` 或 `create_workflow_run`。
- 新增 `ResultDispatcher`，把 WorkflowRun outputs 按 result_mapping 转换成协议回执。
- 给触发源 health 加 request_count、success_count、error_count、timeout_count 和最近错误，长期累计计数使用 safe_counter。

主要文件：

```text
backend/service/application/workflows/trigger_sources/__init__.py
backend/service/application/workflows/trigger_sources/trigger_source_service.py
backend/service/application/workflows/trigger_sources/trigger_source_supervisor.py
backend/service/application/workflows/trigger_sources/protocol_adapter.py
backend/service/application/workflows/trigger_sources/trigger_event_normalizer.py
backend/service/application/workflows/trigger_sources/input_binding_mapper.py
backend/service/application/workflows/trigger_sources/workflow_submitter.py
backend/service/application/workflows/trigger_sources/result_dispatcher.py
backend/service/application/workflows/trigger_sources/path_values.py
```

验收点：

- 不接任何外部协议时，也能用内存 TriggerEvent 验证 mapping、submit 和 result dispatch。
- sync submit 返回完整 WorkflowRun 或协议中立 TriggerResult。
- async submit 返回 run id，后续结果仍能通过现有 WorkflowRun 查询获得。

### 第 5 步：增加 TriggerSource REST 管理 API

目标是提供配置和运维控制面，不替代现有 runtime 执行 API。

开发内容：

- 新增 `workflow_trigger_sources.py` REST route。
- 在 v1 router 中挂载 trigger source 路由。
- 提供 create、list、get、enable、disable 和 health 的最小接口。
- 权限第一阶段沿用 `workflows:read` 和 `workflows:write`。
- 返回合同使用 `WorkflowTriggerSourceContract`，不直接返回内部 adapter 对象。

建议接口：

```text
POST /api/v1/workflows/trigger-sources
GET /api/v1/workflows/trigger-sources?project_id=...
GET /api/v1/workflows/trigger-sources/{trigger_source_id}
POST /api/v1/workflows/trigger-sources/{trigger_source_id}/enable
POST /api/v1/workflows/trigger-sources/{trigger_source_id}/disable
GET /api/v1/workflows/trigger-sources/{trigger_source_id}/health
```

主要文件：

```text
backend/service/api/rest/v1/routes/workflow_trigger_sources.py
backend/service/api/rest/v1/router.py
tests/test_workflow_trigger_sources_api.py
tests/test_workflow_trigger_source_components.py
```

验收点：

- REST 管理 API 可创建并启停一条 disabled 的 trigger source。
- enable 时如果绑定的 WorkflowAppRuntime 不存在或未运行，应返回明确错误。
- disable 后不再接收新触发，但不强行取消已经创建的 WorkflowRun。

### 第 6 步：补齐协议中立结果输出

目标是让结果节点不只绑定 HTTP，同时继续兼容现有 HTTP Response。

开发内容：

- 保留 `core.output.http-response` 作为 HTTP invoke 默认输出。
- 保留 `core.output.response-envelope` 作为协议中立业务包体。
- 新增 `workflow-result.v1` payload contract。
- 新增 `core.output.workflow-result` 节点，输出 status、code、message、data、files、metrics、trace_id 和 event_id。
- ResultDispatcher 支持优先读取 `result_mapping.result_binding`，例如 `workflow_result` 或 `http_response`。
- 当没有配置 result_mapping 时，sync HTTP 继续优先使用 `http_response`，其他协议默认返回 accepted 或 run id。

主要文件：

```text
backend/nodes/core_catalog.py
backend/nodes/core_nodes/workflow_result.py
tests/test_workflow_display_and_response_nodes.py
docs/examples/workflows/
```

验收点：

- 现有 HTTP Response 示例不变。
- 新的 Workflow Result 可被 HTTP、ZeroMQ、gRPC、MQTT 等 result dispatcher 共用。
- 输出中需要长期保留的图片只返回 ObjectStore 引用，不暴露本机 mmap path 作为长期结果。

### 第 7 步：实现 ZeroMQ 最小同步链路

目标是完成第一条高速入口，但仍挂在通用 TriggerSource 框架下。

开发内容：

- 在 requirements 中加入 `pyzmq`，并同步开发环境说明。
- 新增 ZeroMQ adapter，第一阶段支持受控本机 `REQ/REP` 监听骨架。
- 接收 multipart 消息：第一帧 JSON envelope，第二帧图片 bytes，后续帧暂不启用或作为扩展保留。
- adapter 读取 envelope 中的 media_type、shape、dtype、layout、pixel_format、trace_id 和 input binding 名称。
- 图片 bytes 写入 LocalBufferBroker 普通 BufferRef。
- InputBindingMapper 把 BufferRef payload 映射到 `request_image` 等 FlowApplication input binding。
- WorkflowSubmitter 使用 sync invoke 语义调用已启动 WorkflowAppRuntime。
- ResultDispatcher 把 workflow 输出转换为 ZeroMQ JSON reply。
- 对输入格式错误、runtime 未运行、超时和 workflow 失败分别返回稳定错误码。
- 当前已完成可测试的 multipart 转换、BufferRef payload 构造、reply/error reply、REP 监听骨架、REST enable/disable 启停和 backend-service 启动恢复；下一步进入 06/07 独立 image-ref workflow app 本地 ZeroMQ 联调，并继续保持图级转换与 TriggerSource 的边界分离。

主要文件：

```text
backend/service/infrastructure/integrations/zeromq/zeromq_trigger_adapter.py
backend/service/application/workflows/trigger_sources/protocol_adapter.py
backend/service/application/workflows/trigger_sources/result_dispatcher.py
requirements.txt
docs/api/examples/workflows/06-zeromq-trigger-source.md
```

验收点：

- 使用一张本地图片通过 ZeroMQ 触发 04 或 05 workflow app，同步返回业务结果。
- LocalBufferBroker health 中 allocation/released 计数匹配，run 结束后没有残留 active lease。
- ZeroMQ 输入错误不会把 WorkflowAppRuntime 或 deployment worker 打成 failed。
- 与 FastAPI invoke 同一份 input binding 时，结果语义一致。

### 第 8 步：实现外部调用方 SDK

目标是让设备上位机、MES、采集程序和调试脚本通过标准 SDK 调用 TriggerSource，而不是每个项目重复拼 ZeroMQ 消息。

开发内容：

- 在仓库根目录增加 `sdks/`，与 backend-service 内部实现分离。
- 在 `sdks/contracts/` 固定 ZeroMQ envelope、TriggerResult 和错误 reply 的 schema 与示例。
- 优先实现 C# / .NET SDK，覆盖 .NET Framework 和 .NET Core / .NET 应用。
- 增加 Python SDK 和 CLI，服务本地联调、自动化测试和轻量桥接。
- 后续按需要补 Go SDK 和 C SDK。
- SDK 提供统一的 `InvokeImage` / `SubmitImage` 类接口，封装 event_id、trace_id、metadata、timeout 和错误码。
- SDK 提供可选 REST control client，用于检查 trigger source health、enable/disable 和 run 查询。

主要文件：

```text
sdks/README.md
sdks/contracts/
sdks/dotnet/
sdks/python/
sdks/go/
sdks/c/
docs/api/trigger-source-sdks.md
```

验收点：

- C# / .NET SDK 能用一张本地图片触发 04 或 05 workflow app，并解析 ZeroMQ reply。
- Python SDK 或 CLI 能作为本地联调工具复用同一份 schema 和示例。
- SDK 不导入 backend-service 内部代码，只依赖公开协议和 schema。
- 同一张图片通过 SDK ZeroMQ 调用和 FastAPI invoke 调用时，workflow 结果语义一致。

### 第 9 步：实现 ZeroMQ async 和 ring frame 链路

目标是支持更贴近现场高速输入的连续帧或削峰模式。

开发内容：

- 支持 trigger source submit_mode 为 async，收到消息后创建 WorkflowRun 并立即返回 run id。
- 支持 ring buffer channel 创建、FrameRef 写入和触发。
- 为 FrameRef 增加固定为普通 BufferRef 的步骤，避免排队后 frame 被覆盖。
- 支持 result_mode 为 async-report，可通过 ZeroMQ PUB 或 DEALER 回发结果摘要。
- 增加背压策略配置，例如 reject、latest、block-with-timeout。
- health 暴露 received_count、submitted_count、dropped_count、timeout_count、last_frame_sequence_id。

验收点：

- 高频连续帧输入时不会无界堆积队列。
- async 模式可以通过现有 `GET /api/v1/workflows/runs/{workflow_run_id}` 查询最终结果。
- FrameRef 覆盖不会导致运行中的 workflow 读到错误帧。

### 第 10 步：前端图编排显示入口和出口

目标是让操作人员能在 workflow app 中看到入口和结果边界，但不把协议监听器塞进图执行进程。

开发内容：

- 在图编辑器中增加 App Entry 和 App Result 边界节点显示。
- App Entry 绑定 FlowApplication input binding 和 TriggerSource 配置摘要。
- App Result 绑定 FlowApplication output binding 和 result_mapping。
- 支持同一 workflow app 显示多个入口，例如 HTTP Invoke 和 ZeroMQ Frame Request。
- 支持从入口节点跳转到 TriggerSource 配置面板。
- 支持显示 trigger source 运行状态、最近错误和最近触发时间。

验收点：

- 图里能清楚看到 workflow app 的开始入口和结果出口。
- 修改 TriggerSource 配置不改变可复用 WorkflowGraphTemplate。
- HTTP 调试入口和 ZeroMQ 高速入口可以共用同一张图。

### 第 11 步：扩展其他协议 adapter

目标是在通用框架稳定后按现场优先级增加协议，而不是一次铺满。

建议顺序：

1. gRPC method：适合同步请求响应，和 ZeroMQ sync-reply 共享 ResultDispatcher。
2. MQTT topic：适合 async trigger 和 async-report。
3. PLC register：适合边沿检测、去抖、async run 和结果写回寄存器。
4. IO change：适合状态变化触发和简单结果输出。
5. sensor-read：适合阈值、状态翻转和采样规则触发。

每新增一个协议，只新增 adapter、transport_config 校验和少量 result dispatcher 扩展，不新增 workflow 执行资源。

## 第一阶段最小可交付闭环

第一阶段建议只交付以下内容：

- TriggerSource 合同和持久化。
- TriggerSource REST 管理 API。
- 协议无关的 InputBindingMapper、WorkflowSubmitter 和 ResultDispatcher。
- TriggerSourceSupervisor 与 ZeroMQ multipart adapter 骨架。

当前代码已经完成以上内容，并已补充 ZeroMQ adapter 的 REST 启停、backend-service 启动恢复和 C# / .NET 外部调用方 SDK 首版。ZeroMQ sync-reply 真实 workflow app 联调、其他语言 SDK、ZeroMQ 调试示例和 workflow-result 输出示例进入后续阶段。

暂缓到第二阶段的内容：

- MQTT、gRPC、PLC、IO 和传感器 adapter。
- 前端完整编排面板，只先保留文档和后端合同。
- 复杂权限 scope，第一阶段继续使用 workflows:read 和 workflows:write。
- 多实例 trigger source 调度和跨主机部署。
- 长期 registry 恢复、复杂背压策略和完整指标面板。

代码建议边界：

```text
backend/contracts/workflows/trigger_sources.py
backend/service/domain/workflows/workflow_trigger_source_records.py
backend/service/application/workflows/trigger_sources/
  trigger_source_service.py
  trigger_source_supervisor.py
  protocol_adapter.py
  trigger_event_normalizer.py
  input_binding_mapper.py
  workflow_submitter.py
  result_dispatcher.py
backend/service/infrastructure/integrations/zeromq/
  zeromq_trigger_adapter.py
backend/service/api/rest/v1/routes/workflow_trigger_sources.py
sdks/
  README.md
  contracts/
  dotnet/
  python/
  go/
  c/
```

这些模块属于 workflow runtime 的外部调用触发层，不属于 LocalBufferBroker，也不属于单个 custom node。LocalBufferBroker 只承担本机数据面，workflow 图只承担业务处理和结果组织，TriggerSource 负责把二者连接到外部协议。

## 与其他资源的关系

- WorkflowTriggerSource 通常绑定 [docs/api/workflow-app-runtimes.md](workflow-app-runtimes.md) 中的 WorkflowAppRuntime。
- 触发源接收到外部事件后，应创建 [docs/api/workflow-runs.md](workflow-runs.md) 中的 WorkflowRun。
- PreviewRun 不承接长期触发器；编辑态联调应继续使用 [docs/api/workflow-preview-runs.md](workflow-preview-runs.md)。
- execution policy、persona 和 tool policy 仍属于运行时默认项，不替代触发源自己的协议配置。

## 相关文档

- [docs/api/workflow-runtime-drafts.md](workflow-runtime-drafts.md)
- [docs/api/workflow-runs.md](workflow-runs.md)
- [docs/api/communication-contracts.md](communication-contracts.md)
- [docs/architecture/workflow-runtime.md](../architecture/workflow-runtime.md)
- [docs/architecture/node-system.md](../architecture/node-system.md)