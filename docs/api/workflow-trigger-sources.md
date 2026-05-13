# WorkflowTriggerSource 接口草案

## 文档目的

本文档用于收口 workflow 外部触发入口的资源边界和最小接口草案。

本文档只定义触发源定位、接入原则和最小字段，不表示当前主干已经公开这些接口。

## 当前边界

- 当前 workflow runtime 已落地的正式执行入口仍是 HTTP 控制面。
- 后续 PLC、MQTT、ZeroMQ、gRPC、IO 变化、传感器读取、schedule 和 Webhook 触发，可以继续扩展为 WorkflowTriggerSource。
- 传感器读数、阈值越界、状态翻转和采样结果本身就是物理世界进入 workflow 的直接触发入口，不应只被视为运行中节点的附属输入。
- 外部触发入口与节点图本身分层：触发源负责监听、过滤、去重和创建 WorkflowRun；runtime 负责执行。
- 当前草案不把“首节点轮询外部世界”作为默认触发模型。
- ZeroMQ 可作为 workstation 或 standalone 场景下的高速外部触发和图片提交入口之一，不等同于本机内部大图数据交换层。
- 该资源属于 workflow runtime 后续控制面草案，不进入 [docs/api/current-api.md](current-api.md) 总览。

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
- FlowApplication 把图的输入输出端口发布成稳定 binding，例如 `request_image`、`deployment_request` 和 `http_response`。
- WorkflowAppRuntime 固定 application snapshot 和 template snapshot，是现场长期运行的宿主。
- WorkflowTriggerSource 绑定 WorkflowAppRuntime，并把外部事件映射到 application 的 `input_bindings`，不修改 workflow 图。
- 同一张图可以同时被 HTTP invoke、async run 和后续 trigger source 使用；区别只在输入从哪里来、以 sync 还是 async 提交，以及回执如何返回。

常见图链路可以保持为：`request_image` 输入 -> YOLOX detection 节点 -> OpenCV 后处理节点 -> HTTP Response 输出节点。HTTP Response 输出节点的结果会出现在 `outputs["http_response"] = {"status_code": 200, "body": ...}`，由同步调用或触发源回执层决定是否直接返回给调用方。

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
- 同一张 workflow 图可以被多个入口复用，例如 HTTP 调试入口和 ZeroMQ 高速入口同时绑定到 `request_image`。
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

adapter 收到二进制帧后先写入 LocalBufferBroker，随后把 BufferRef 或 FrameRef 映射到 application input_bindings。同步返回时，ResultDispatcher 读取 workflow 输出绑定，转换成 JSON reply 或 multipart reply；需要返回图片时，优先返回 ObjectStore 引用或受控 BufferRef 摘要，不把本机 mmap path 当成长期外部结果。

ZeroMQ 第一阶段不直接实现 PLC、MQTT、gRPC 等协议，但需要先落下同一套 TriggerSource 合同、adapter 接口、输入映射、结果映射、health 和审计字段，避免后续每个协议各写一套调用链。

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

## 接口入口草案

- 版本前缀：/api/v1
- 资源分组：/workflows
- 资源路径：/api/v1/workflows/trigger-sources
- 当前状态：接口草案，尚未公开

## 鉴权草案

- list 和 get 建议使用 workflows:read
- create、enable 和 disable 建议使用 workflows:write

当前阶段不单独拆 trigger-sources 专用 scope，避免过早把控制面权限做复杂。

## 资源字段草案

- trigger_source_id
- project_id
- display_name
- trigger_kind，取值建议为 plc-register、mqtt-topic、zeromq-topic、grpc-method、io-change、sensor-read、schedule、webhook
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

### POST /api/v1/workflows/trigger-sources/{trigger_source_id}/enable

- 建议需要 workflows:write
- 用途：启用一条 trigger source，开始接收外部触发

### POST /api/v1/workflows/trigger-sources/{trigger_source_id}/disable

- 建议需要 workflows:write
- 用途：停用一条 trigger source，停止接收新的外部触发

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
3. 实现 TriggerSourceService、TriggerSourceSupervisor、ProtocolAdapter 接口和 ResultDispatcher 骨架。
4. 通过 REST API 管理 trigger source 的创建、启停、health 和最近错误。
5. 实现 ZeroMQ adapter 的最小 sync-reply 链路，复用 LocalBufferBroker 写入 BufferRef，再调用已有 WorkflowAppRuntime invoke 语义。
6. 增加 ZeroMQ async 或 ring frame 链路，接入 WorkflowRun 持久化和回查。
7. 在图编排界面显示 App Entry 和 App Result 边界节点，绑定到 FlowApplication 输入输出。
8. 再按现场优先级补 MQTT、gRPC、PLC、IO 和传感器 adapter。

代码建议边界：

```text
backend/contracts/workflows/trigger_sources.py
backend/service/domain/workflows/workflow_trigger_source_records.py
backend/service/application/workflows/trigger_sources/
  trigger_source_service.py
  trigger_source_supervisor.py
  protocol_adapter.py
  input_binding_mapper.py
  result_dispatcher.py
backend/service/infrastructure/integrations/zeromq/
  zeromq_trigger_adapter.py
backend/service/api/rest/v1/routes/workflow_trigger_sources.py
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