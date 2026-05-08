# WorkflowTriggerSource 接口草案

## 文档目的

本文档用于收口 workflow 外部触发入口的资源边界和最小接口草案。

本文档只定义触发源定位、接入原则和最小字段，不表示当前主干已经公开这些接口。

## 当前边界

- 当前 workflow runtime 的正式执行入口仍是 HTTP 控制面。
- 后续 PLC、MQTT、ZeroMQ、gRPC、IO 变化、传感器读取、schedule 和 Webhook 触发，可以继续扩展为 WorkflowTriggerSource。
- 传感器读数、阈值越界、状态翻转和采样结果本身就是物理世界进入 workflow 的直接触发入口，不应只被视为运行中节点的附属输入。
- 外部触发入口与节点图本身分层：触发源负责监听、过滤、去重和创建 WorkflowRun；runtime 负责执行。
- 当前草案不把“首节点轮询外部世界”作为默认触发模型。
- ZeroMQ 在当前平台中仍优先作为同机本地内部 IPC，不作为默认对外触发协议。
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

## 推荐触发类型

- plc-register：PLC 寄存器点位变化或条件满足后触发
- mqtt-topic：订阅指定 topic 并按消息内容创建 run
- zeromq-topic：同机本地 IPC 主题触发
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
- default_execution_metadata
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
| zeromq-topic | async 优先；少量场景可用 sync | 作为本地内部 IPC 时可用于快速联动，但默认仍更适合创建 run 后异步观察 |
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
- default_execution_metadata
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
  "default_execution_metadata": {
    "trigger_source": "plc-register"
  },
  "debounce_window_ms": 200,
  "idempotency_key_path": "payload.sequence_id",
  "metadata": {
    "line_id": "line-a"
  }
}
```

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