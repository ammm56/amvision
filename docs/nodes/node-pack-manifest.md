# Node Pack Manifest 和 Capability 说明

## 文档目的

本文档用于细化 node pack manifest 的结构、字段含义、capability 模型和权限边界，作为节点包注册、启用、兼容性检查和管理的基本规则。

## 适用范围

- node pack manifest 必填字段与推荐字段
- capability 分类、permission scope 与依赖声明
- 版本兼容性、超时和启停管理要求
- 与 backend-service、LocalNodePackLoader、WorkflowNodeRuntimeRegistryLoader 和统一节点目录的关系

## 总体原则

- 每个 node pack 必须有唯一 manifest，且 manifest 是节点包身份和能力的正式描述
- capability 用于声明“节点包能做什么”，permission scope 用于声明“节点包能接触什么”
- backend-service 根据 manifest 决定能否注册、启用、升级或回滚 node pack
- 未在 manifest 中声明的能力、触发点和外部端点访问，不应被视为可用能力

## manifest 最小结构

```yaml
id: nodes.example.name
version: 1.0.0
displayName: Example Node Pack
category: custom-node-pack
capabilities:
  - pipeline.node
  - result.postprocess
permissionScopes:
  - task.read
  - task.result.write
entrypoints:
  backend: custom_nodes.example_nodes.backend.entry:register
compatibility:
  api: ">=1.0 <2.0"
  runtime: ">=3.12"
timeout:
  defaultSeconds: 30
enabledByDefault: false
customNodeCatalogPath: workflow/catalog.json
```

customNodeCatalogPath 指向 node pack 对外暴露的最终目录文件。对于采用碎片化维护的节点包，推荐把源文件放在 workflow/catalog_sources/ 下，再由生成步骤手动汇总成这个 catalog.json。当前 barcode.protocol-nodes 已采用这种方式，开发阶段通过以下命令手动回写目录文件：

```powershell
D:/software/anaconda3/envs/amvision/python.exe -m custom_nodes.barcode_protocol_nodes.workflow.generate_catalog
```

如果 barcode.protocol-nodes 的变更来自 specs.py 中的 decode 规格，还需要先生成 backend/nodes 下的 decode 模块和 workflow/catalog_sources/nodes 下的 decode JSON，再执行 catalog 生成：

```powershell
D:/software/anaconda3/envs/amvision/python.exe -m custom_nodes.barcode_protocol_nodes.backend.generate_decode_node_modules
D:/software/anaconda3/envs/amvision/python.exe -m custom_nodes.barcode_protocol_nodes.workflow.generate_catalog
```

## 必填字段

- id：node pack 稳定唯一标识
- version：node pack 版本
- category：节点包主类别
- capabilities：能力声明列表
- entrypoints：后端注册入口或等价注册入口
- compatibility：平台 API、运行时和依赖兼容范围
- timeout：默认超时策略
- enabledByDefault：默认启用策略

## 推荐字段

- displayName
- description
- permissionScopes
- configSchema
- inputSchema and outputSchema
- uiSchema
- triggerPoints
- hookPoints
- externalDependencies
- assetRequirements
- healthCheck

## category 建议枚举

- custom-node-pack
- result-processor
- protocol-adapter
- runtime-callback
- hardware-bridge
- module-connector
- ui-extension

## capability 模型

### capability 的职责

- 声明 node pack 可参与的后端服务或 worker 能力
- 提供前端展示、筛选和管理的基础标签
- 为启用检查、权限检查和兼容性检查提供依据

### capability 建议前缀

- pipeline.node
- pipeline.hook
- inference.postprocess
- task.callback
- integration.trigger
- integration.report
- hardware.bridge
- module.connect
- ui.panel

### capability 粒度建议

- 能力要足够细，避免出现一个大而泛的“all”能力
- 同时避免过度碎片化到无法管理或无法理解
- capability 应对齐 backend-service 能管理的资源和事件范围

## permission scope 模型

### permission scope 的职责

- 描述 node pack 允许读取、写入、触发或调用的资源范围
- 与 capability 配合定义最小权限原则

### permission scope 示例

- task.read
- task.result.write
- deployment.read
- integration.endpoint.invoke
- node.event.subscribe
- objectstore.read.ref
- objectstore.write.ref

## 兼容性声明

- 必须声明平台 API 兼容范围
- 必须声明 Python runtime 兼容范围
- 如依赖特定推理后端、厂商 SDK 或操作系统能力，也应显式声明
- 升级时若超出兼容范围，backend-service 应拒绝启用或要求人工确认

## 依赖声明

- externalDependencies：系统级依赖、厂商运行时、网络端点或本地服务依赖
- nodeDependencies：对其他节点能力或 node pack 的依赖
- assetRequirements：所需模型、字典、配置模板或前端资源

## timeout 和生命周期管理

- manifest 必须提供默认超时策略
- 对外回调、结果上报和硬件桥接能力应允许更严格的超时限制
- node pack 必须支持 enable、disable、upgrade、rollback 这些基本管理动作
- 对关键 node pack 建议提供 healthCheck 入口

## backend-service 的校验职责

- 校验 id 与 version 的唯一性
- 校验 category、capabilities、permissionScopes 是否有效
- 校验 triggerPoints、hookPoints 与平台支持的事件范围是否兼容
- 校验 compatibility 与当前平台版本、runtime profile 是否匹配
- 校验外部依赖是否满足启用前置条件
- 校验 customNodeCatalogPath 中的节点定义与 node_pack_id / node_pack_version 是否一致
- 校验 backend entrypoint 是否能完成 python-callable / worker-task handler 注册

## 推荐后续文档

- [docs/nodes/runtime-hooks-callbacks.md](runtime-hooks-callbacks.md)
- [docs/architecture/node-system.md](../architecture/node-system.md)
- [docs/architecture/backend-service.md](../architecture/backend-service.md)
