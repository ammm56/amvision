# 节点扩展 Trigger 和 Hook 说明

## 文档目的

本文档用于说明节点扩展 trigger、事件 hook、回调点和数据上报点的统一模型，明确 node pack 在哪些时机被调用、接收什么载荷、允许做什么以及如何管理。

## 适用范围

- triggerPoints 与 hookPoints 的分类
- 外部触发、内部事件 hook、完成回调和数据上报规则
- 载荷结构、幂等性、超时和失败处理
- 与 backend-service、QueueBackend、WebSocket 和外部系统回调的关系

## 总体原则

- trigger 与 hook 都属于受控节点扩展能力，必须先在 manifest 中声明
- backend-service 处理注册、鉴权、启停和事件范围管理
- 节点扩展的触发或 hook 结果若影响公开状态，必须先回写 backend-service
- 触发与 hook 不能绕开任务状态模型或节点扩展超时管理

## 术语区分

### trigger

- 指会主动创建任务、触发流程或启动回调链路的入口点
- 可来自外部系统、调度规则或内部状态变化

### hook

- 指在已有任务或流程生命周期中的固定事件点执行附加逻辑
- 不一定创建新任务，但可能补充后处理、审计、通知或结果转发

## triggerPoints 建议分类

- external.request.received：接收到外部系统触发请求
- task.accepted：任务被后端服务接收
- task.succeeded：任务成功结束
- task.failed：任务失败结束
- deployment.switched：部署切换完成
- pipeline.completed：流程执行完成

## hookPoints 建议分类

- inference.result.postprocess
- task.log.transform
- task.result.report
- deployment.health.observe
- node.status.changed
- integration.callback.before-send
- integration.callback.after-send

## 载荷结构要求

- event id
- event type
- event version
- source aggregate id
- task id or deployment id
- payload summary or payload reference
- correlation id
- occurred at

## 幂等性要求

- 外部触发和结果上报必须设计为可幂等处理
- 同一事件重复投递时，节点扩展逻辑不应产生不可控副作用
- backend-service 应提供 correlation id 或等价去重线索

## 超时与失败处理

- 所有 trigger 与 hook 执行都必须受 timeout 约束
- 节点扩展超时不能阻塞 backend-service 主链路长期悬挂
- 失败时应按能力类型决定是记录错误、重试、降级还是隔离
- 对外回调失败时应支持重试策略和失败审计

## 外部触发规则

- 外部系统请求先进入 backend-service 公开边界
- backend-service 依据 integration endpoint、manifest 和 permission scope 决定是否允许触发 node pack
- 节点扩展如需创建任务，应通过受控任务创建接口进入 QueueBackend，而不是自行绕开后端服务排队

## 完成回调与数据上报规则

- 任务完成后可触发回调节点扩展或结果上报节点扩展
- 回调发送前应以 backend-service 中的最终状态和结果引用为准
- 数据上报节点扩展应声明目标端点、数据范围和失败重试策略
- 回调结果或上报结果应保留审计记录与原始 task id 关联

## 后处理 hook 规则

- 后处理 hook 适用于推理结果、流程结果和转换结果的二次加工
- 后处理不应覆盖原始结果引用，而应产生新的结果视图、衍生文件或结构化摘要
- 若后处理失败，必须保留原始任务结果和失败原因

## 顺序与并发建议

- 同一 hookPoint 下的多个节点扩展应允许声明优先级或阶段
- 对外回调类节点扩展默认建议串行，减少重复通知和竞争问题
- 纯后处理或只读审计类节点扩展可允许受控并行

## 与 WebSocket 和 ZeroMQ 的关系

- WebSocket 只负责把已归一化事件推送给前端，不直接执行节点扩展 hook
- ZeroMQ 可作为同机本地的内部事件传递通道，但最终状态仍需回写 backend-service
- 节点扩展不能把 ZeroMQ 当作绕开公开接口与状态管理的捷径

## 推荐后续文档

- [docs/nodes/node-pack-manifest.md](node-pack-manifest.md)
- [docs/architecture/node-system.md](../architecture/node-system.md)
- [docs/api/communication-contracts.md](../api/communication-contracts.md)
