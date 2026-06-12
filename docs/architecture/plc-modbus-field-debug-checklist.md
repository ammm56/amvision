# PLC Modbus 现场联调清单

## 文档目的

本文档用于把当前 PLC 这条线已经落地的能力、明确还没有做的能力，以及推荐现场联调顺序收成一份短清单。

本文档不替代：

- [industrial-extension-node-plan.md](industrial-extension-node-plan.md)：长期规划、协议分层和后续待办
- [current-implementation-status.md](current-implementation-status.md)：当前主干总览
- [workflow-trigger-sources.md](../api/workflow-trigger-sources.md)：TriggerSource 接口与请求形状

## 当前范围

当前 PLC 主线只收口在 `Modbus TCP` 第一阶段，不扩到 `S7 / MC / OPC UA`。

当前代码边界分为两层：

- workflow 内主动调用节点：`read-value / write-value / wait-condition`
- backend 常驻监听入口：`plc-register` TriggerSource

当前不把 PLC 常驻监听混进普通 workflow 节点，也不把 PLC 回写或业务判定塞进 TriggerSource adapter。

## 当前已实现能力

### 一、workflow 节点

- `custom.plc.modbus.read-value`
  - 读取单个 Modbus 逻辑地址
- `custom.plc.modbus.write-value`
  - 写入单个 Modbus 逻辑地址
- `custom.plc.modbus.wait-condition`
  - 轮询等待点位满足条件后继续执行

当前节点统一支持：

- 地址语义：`00001 / 10001 / 30001 / 400001`
- 数据类型：`bool / uint8 / int8 / uint16 / int16 / uint32 / int32 / uint64 / int64 / float / double / string`
- 运行时覆盖：`read-value / write-value` 支持通过 `request` 输入动态覆盖 `host / unit_id / register_address / data_type / value`
- 无限等待：`wait_timeout_seconds = null`

### 二、共享 Modbus 运行时

- 已有独立共享 transport：`backend/service/infrastructure/integrations/modbus/`
- custom node 与 TriggerSource 共用同一套项目内 Modbus TCP client
- 当前不依赖 `projectsrc/` 或额外第三方 Python 包直接运行

### 三、TriggerSource

- 已实现 `trigger_kind = plc-register`
- 已接入 `transport_config.driver = modbus-tcp`
- 当前只支持 `polling + async submit`
- 当前 `enable` 在没有可用 adapter 时会显式失败，不会停留在“已启用但未运行”的模糊状态

### 四、checked-in 样例

- workflow 样例
  - `docs/examples/workflows/plc_modbus_wait_status_word_ready_mask.*`
  - `docs/examples/workflows/plc_modbus_wait_status_word_alarm_mask.*`
  - `docs/examples/workflows/plc_modbus_wait_ready_ack_callback.*`
  - `docs/examples/workflows/plc_register_modbus_tcp_async_result_record.*`
- TriggerSource API 样例
  - `docs/api/examples/workflows/08-plc-register-modbus-tcp-async-result-record/`
- Postman collection
  - `docs/api/postman/workflows/08-plc-register-modbus-tcp-async-result-record/`

## 当前未实现能力

以下内容属于“还没做”，不是当前阶段 bug：

- `S7 / MC / OPC UA / FINS / EtherNet/IP`
- `plc-register` 的 `sync-reply`
- 多地址监听
- 更多边沿/状态模式
- 更细的 TriggerSource health 观测字段
- Modbus 的 `batch-read / batch-write` 节点
- 把 `wait-condition` 做成常驻 listener

## 当前建议不要混的边界

- 不把 PLC 轮询守护塞进 `wait-condition`
- 不把 PLC 结果回写塞进 TriggerSource 结果分发层
- 不把多个 PLC 协议混成一个大 adapter
- 不在地址语义和字节序还没确认前，直接开始调 `plc-register`

## 推荐现场联调顺序

### 第 1 步：先确认设备与点位语义

先确认以下现场参数：

- `host`
- `port`
- `unit_id`
- `register_address`
- `data_type`
- `word_order`
- `byte_position`

这一层如果没对齐，后面的等待、回写和 TriggerSource 调试都会偏。

### 第 2 步：先跑 `read-value`

目标：

- 确认地址映射正确
- 确认读到的值和 PLC 软件侧一致
- 确认 `data_type / word_order / byte_position` 设置正确

建议先从静态或容易观察变化的点位开始，不要一上来先调复杂状态字。

### 第 3 步：再跑 `wait-condition`

目标：

- 确认比较操作符正确
- 确认 `stable_match_count` 是否符合现场节拍
- 确认 `wait_timeout_seconds` 用有限等待还是无限等待

建议先用：

- `plc_modbus_wait_status_word_ready_mask.*`
- `plc_modbus_wait_status_word_alarm_mask.*`

### 第 4 步：再跑 `write-value`

目标：

- 确认写值地址可写
- 确认写入数据类型和 PLC 侧解释一致
- 确认握手位、确认位、复位位不会误写

建议随后联调：

- `plc_modbus_wait_ready_ack_callback.*`

### 第 5 步：最后再跑 `plc-register` TriggerSource

目标：

- 确认轮询周期合适
- 确认 `match_rule` 能稳定触发
- 确认 `async submit` 后 workflow run 正常创建

建议从最简单的配置开始：

- 单地址
- 单条件
- `stable_match_count = 1`
- 较保守的 `poll_interval_ms`

### 第 6 步：再接结果回传

目标：

- 确认 `result-record` 内容可用
- 确认 `http-post / json-save-local / csv-append-local` 符合现场需要

建议最后联调：

- `plc_register_modbus_tcp_async_result_record.*`
- `08-plc-register-modbus-tcp-async-result-record` Postman collection

## 现场调试建议

- 先把“读对”确认，再谈“等对”“写对”“触发对”
- 先单点位，再扩状态字，再扩业务流程
- 先 workflow 内主动节点，再调 TriggerSource 常驻监听
- 先本地结果记录，再接外部回传

## 下一步建议

如果这一轮现场联调稳定，下一批最值得补的是：

- `plc-register` 多地址监听
- 更丰富的边沿/状态模式
- 更细的 health 字段

如果现场已经明确不是 Modbus TCP，而是 `S7 / MC`，那就不应该继续往当前 pack 上堆兼容逻辑，而应单独起新的 PLC custom node pack 和 TriggerSource 分层实现。
