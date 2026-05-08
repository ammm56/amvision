# Workflow Runtime 第二阶段边界

## 文档目的

本文档用于收口 workflow runtime 第二阶段真正进入实现范围的控制面边界。

本文档只定义第二阶段的范围、进入条件和明确排除项，不展开详细接口字段或实现细节。

## 第二阶段目标

- 补齐第一阶段已经暴露但故意延后的 runtime 控制面缺口。
- 继续沿用 PreviewRun、WorkflowAppRuntime、WorkflowRun 三类资源，不重新引入旧 execute 语义。
- 把 restart、instances、异步 runs、execution policies 收口到可执行的最小范围。
- 避免把 AI 控制面、复杂调度和多实例伸缩一并混进第二阶段。

## Workflow Sync / Async 使用约束

- workflow 触发源不长期限制为 HTTP API。HTTP 只是当前最先落地的控制面入口。后续 PLC、ZeroMQ、MQTT、gRPC、IO 变化、传感器读取等触发方式，应优先通过 node pack 或集成边界接入，再创建 WorkflowRun，不直接写入核心 runtime 主链路。
- 一次已发布应用的正式执行统一落到 WorkflowRun。触发源、执行模式和节点图是三个独立维度，不混成同一层控制面。
- sync invoke 用于低时延、短链路、设备运行期间的高频正式调用，调用方在当前请求内直接拿到结果。
- async runs 用于长时间执行、后台提交、排队、取消和后续回查，run 可以脱离当前 HTTP 请求继续存在。
- sync invoke 与 async runs 共享同一套 workflow app、snapshot 和 node graph，不改变节点编排模型。多 WorkflowAppRuntime 实例负责吞吐、隔离和扩容；async runs 只补充脱离请求生命周期的执行能力。
- workflow runtime 负责进程隔离、稳定性、超时、重启和观测。协议接入、硬件桥接、结果上报和外部触发逻辑优先通过 custom node、node pack 或集成边界实现。

## 第二阶段包含项

### WorkflowAppRuntime restart

进入第二阶段：

- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/restart
- restart 的语义固定为 stop 当前 worker，再重新加载同一组 runtime snapshot
- restart 只作用于单个 WorkflowAppRuntime，不扩展为批量控制或多 runtime 编排

不进入第二阶段：

- restart policy 自动重启策略对外配置
- backoff、最大重试次数、崩溃熔断的公开控制面

### WorkflowAppRuntime instances

进入第二阶段：

- GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/instances
- instances 只提供观测能力，返回 instance_id、state、process_id、current_run_id、started_at、heartbeat_at、last_error 这类摘要字段
- runtime manager 内部允许为后续多实例铺路，但公开接口先收口为只读观测

不进入第二阶段：

- scale up / scale down 接口
- autoscaling 规则
- scheduler、placement、affinity、worker pool 路由策略

### WorkflowRun 异步 runs

进入第二阶段：

- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs
- GET /api/v1/workflows/runs/{workflow_run_id}
- POST /api/v1/workflows/runs/{workflow_run_id}/cancel
- WorkflowRun 状态机补齐 queued，用于异步 runs 的外部可见排队状态
- 异步 runs 仍沿用 WorkflowRun 资源，不新建另一类任务资源

不进入第二阶段：

- GET /api/v1/workflows/runs/{workflow_run_id}/events
- 节点级日志流、trace 流或单独的运行事件订阅接口
- schedule、cron、外部集成回调这类触发器

### WorkflowExecutionPolicy 最小接入

进入第二阶段：

- WorkflowPreviewRun create 支持 execution_policy_id，并在执行前固化为 snapshot
- WorkflowAppRuntime create 支持 execution_policy_id，并回写 execution_policy_snapshot_object_key
- 公开最小 execution policy 管理接口：create、list、get
- 第二阶段只纳入下列字段：
  - policy_kind
  - default_timeout_seconds
  - max_run_timeout_seconds
  - trace_level
  - retain_node_records_enabled
  - retain_trace_enabled
  - metadata

不进入第二阶段：

- persona_profile_id
- tool_policy_id
- max_agent_steps
- 任何面向 LLM、VLM、agent 的默认人格和工具权限控制

## 第二阶段明确排除项

- PersonaProfile 全部公开接口
- ToolPolicy 全部公开接口
- WorkflowTriggerSource 资源、listener bridge 和各类外部触发协议接入；这一层当前只保留草案，不进入本轮 phase2 代码实现范围
- 多实例伸缩控制接口
- 高可用、跨机器调度、负载均衡
- run 事件流、trace 下载、日志检索
- 定时触发、Webhook 触发、协议侧自动触发
- 与硬件权限、PLC、传感器控制有关的新控制面资源

## 范围矩阵

| 能力 | 第二阶段 | 说明 |
| --- | --- | --- |
| runtime restart | 进入 | 公开单 runtime restart |
| runtime instances | 进入 | 只读观测，不做伸缩控制 |
| async runs create/get/cancel | 进入 | 仍复用 WorkflowRun |
| run events | 不进入 | 保持后续专题再收口 |
| execution policy 基础字段 | 进入 | 只覆盖 timeout、trace、保留策略 |
| persona/tool 绑定 | 不进入 | 留在 AI 控制面后续阶段 |
| autoscaling / placement | 不进入 | 不在第二阶段展开 |

## 建议实现顺序

1. restart 与 instances
2. async runs create/get/cancel
3. execution policy 最小接入

这个顺序的原因是 restart 和 instances 直接延伸自第一阶段已有 worker manager，风险最小；async runs 会引入 queue 和状态机扩展；execution policy 接入最后做，避免第二阶段一开始就把控制面扩得过宽。

## 与第一阶段的关系

- 第一阶段继续保持单实例、start、stop、health、sync invoke 的稳定边界。
- 第二阶段是在第一阶段资源模型之上增量扩展，不回退到旧 execute 模式。
- 第二阶段如果需要新增字段或状态，必须先与 [docs/architecture/workflow-runtime-phase1.md](workflow-runtime-phase1.md) 的状态机和 snapshot 规则保持兼容。

## 相关文档

- [docs/architecture/workflow-runtime-phase1.md](workflow-runtime-phase1.md)
- [docs/architecture/workflow-runtime.md](workflow-runtime.md)
- [docs/api/workflow-runtime-drafts.md](../api/workflow-runtime-drafts.md)
- [docs/api/workflow-execution-policies.md](../api/workflow-execution-policies.md)