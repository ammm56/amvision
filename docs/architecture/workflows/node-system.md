# 节点系统

> 当前状态：本页描述可信节点的现有执行边界。Node Pack timeout 的目标语义已由 [ADR-0006](../../decisions/ADR-0006-task-execution-and-runtime-reliability.md) 接受，但尚未完整闭环；详细步骤见 [任务执行与运行时可靠性实施基线](../../development/task-runtime-reliability-implementation.md)。Preview 将保持进程内协作式取消，正式 Runtime 将以整个 worker 作为超时后的强制终止边界，不引入每节点进程或队列。

## 定位

节点系统是 AMVision 的可组合能力边界。平台通过统一 NodeDefinition、Node Catalog、payload contract 和执行器，把 Core Node 与安装的 Custom Node 放入同一张 Workflow 图。场景化协议、硬件桥接、行业规则和大型扩展模型优先进入 Node Pack，不写入平台主链。

节点分类和一级 pack 拆分见 [节点分类](node-taxonomy.md)，manifest 字段见 [Node Pack manifest](../../nodes/node-pack-manifest.md)。

## 组成

| 组成 | 职责 |
| --- | --- |
| Core Node | 平台稳定的逻辑、集合、图片、ROI、模型调用和控制节点 |
| Custom Node | Node Pack 提供的协议、设备、算法或行业节点 |
| Node Pack | manifest、Catalog、Python handler、依赖和资产的分发单元 |
| Node Catalog | 前后端共享的节点、端口、参数和能力目录 |
| Runtime Registry | 把 `node_type_id` 映射到可信 Python handler |
| Workflow Executor | 按图、结构节点和 enabled 状态调度 handler |

## 依赖方向

```text
manifest + catalog
       ↓ load / validate
NodeCatalogRegistry + RuntimeRegistry
       ↓
Workflow Template → Executor → Node handler
       ↑                    ↓
frontend editor       payload / result
```

- 前端只消费 Catalog，不复制 Python 节点定义。
- Template 保存节点实例、参数、边、分组和 UI state，不内嵌完整 NodeDefinition。
- 执行器按 payload type 检查连线与运行输入，节点不自行修改图结构。
- Node Pack 不直接拥有 Task、ModelVersion、Deployment 或 Workflow Runtime 等平台资源。

## Core 与 Custom 边界

Core 保留：

- 通用图执行、集合、条件、结构控制和 payload bridge。
- 标准图片引用、ROI、结果类型和模型 Deployment 调用。
- Node Pack 生命周期、版本、Catalog 合并和错误映射。

Node Pack 承担：

- OpenCV 专项算法、YOLOE、SAM3 等可选能力。
- HTTP、数据库、PLC、目录、USB/UVC、厂商 SDK 和 MES 集成。
- 客户或行业特定的规则、结果变换和回调。

相机、PLC、传感器和机械臂驱动不是核心平台能力。需要直连时由明确安装和启用的 Node Pack 实现。

## Manifest 与依赖

每个 pack 至少声明：

- `id`、SemVer `version`、category 和 display metadata
- capabilities 与 pack dependencies
- workflow catalog 和 backend entrypoint
- config schema、timeout 与 `enabledByDefault`
- 平台/Python/操作系统或厂商 runtime 的兼容范围

依赖必须显式且范围窄。缺少或版本不匹配时，只让依赖该 pack 的能力失败并给出明确原因，不通过隐式顶层 import 让无关节点失效。

## 可信执行模型

本地工业视觉部署把 Node Pack 的安装与启用视为使用者已经完成的信任选择：

- Core、内置和第三方节点使用同一套进程内 handler 调用。
- Preview 在 backend-service 内直接执行可信节点。
- 正式 Workflow App 在长期 Runtime worker 内直接执行节点。
- 正常节点调用不创建 per-node 进程，不经过跨进程 RPC，也不维护 permission scope。
- 一次性安装校验可以在辅助进程检查 import 和 handler 注册，但不进入执行热路径。

Workflow Runtime worker、Deployment 常驻进程和后台 Worker 是服务生命周期与故障恢复边界，不是节点权限沙箱。未经信任的代码必须使用独立服务或操作系统级 container/sandbox，不用 manifest 字段伪装成安全隔离。

## 外部调用

HTTP、数据库、PLC、相机、ObjectStore 和模型资源由节点通过项目公开接口或对应 SDK 直接使用。节点负责：

- 明确连接、读取、执行和取消超时。
- 把外部错误映射为稳定节点错误。
- 对有副作用操作使用业务可识别的幂等键。
- 不加入隐藏排队、无限重试或吞掉错误的降级路径。

Trigger adapter 负责把外部事件转换成 Workflow Run 请求；业务图仍由稳定 Workflow Runtime 执行，监听器不复制一套图执行器。

## 参数与端口

- JSON Schema 是参数约束事实来源，UI schema 只描述控件呈现。
- `number` 应显式声明 `multipleOf` 和必要范围；未声明时前端只提供确定性 UI 步长回退，后端仍按 schema 校验。
- 输入输出端口必须声明版本化 payload type。
- 隐式类型转换禁止；需要转换时使用明确 bridge 节点。
- `node_type_id`、端口或 payload 的破坏性变化必须同步版本、示例、迁移和测试。

## Parallel、ForEach 与节点组

- Parallel 和 ForEach 是 Core 结构节点的执行语义，不由普通 Node Pack 自行实现调度器。
- `max_concurrency` 只限制显式分支或循环项，不自动并行整张 DAG。
- 画布节点组只影响布局与成员的最终 enabled 状态，不创建运行时子图或隔离进程。

详见 [Parallel 分支](parallel-branches.md) 与 [Workflow 编辑器](editor.md)。

## 生命周期

Node Pack 安装和变更遵循 staging、校验、原子激活与恢复：

1. 校验 ZIP 路径、manifest、版本、依赖和 Catalog。
2. 在 staging 中检查 Python entrypoint 与 handler 注册。
3. 原子切换活动版本并重载 Catalog/Registry。
4. 失败时恢复原版本；启动时先收敛未完成事务。
5. disable 或 rollback 后，现有 Workflow 必须在 validate/start 时得到明确缺失能力错误。

生命周期 API 与前端目录页使用同一事实，不直接手工修改已激活 manifest。

## 验收

- Core 与 Custom Node 在 Preview 和正式 Runtime 中使用同一 payload/参数语义。
- Catalog、Runtime Registry、前端端口和保存文档一致。
- 节点执行不产生 per-node 进程启动延迟或大图 Base64 复制。
- timeout、取消、异常和 Runtime 停止能释放文件、连接与 LocalBuffer 引用。
- pack 安装、禁用、升级、回滚和启动恢复保留明确版本与错误记录。
- 缺失外部依赖不会让无关 pack 或 backend-service 启动失败。

扩展开发入口见 [节点扩展](../../nodes/README.md)。
