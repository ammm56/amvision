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

```json
{
  "format_id": "amvision.node-pack-manifest.v1",
  "id": "example.simple-nodes",
  "version": "0.1.0",
  "displayName": "Example Simple Nodes",
  "description": "提供一组简单的示例节点。",
  "category": "custom-node-pack",
  "capabilities": [
    "pipeline.node"
  ],
  "permissionScopes": [],
  "entrypoints": {
    "backend": "custom_nodes.example_simple_nodes.backend.entry:register"
  },
  "compatibility": {
    "api": ">=0.1 <1.0",
    "runtime": ">=3.12"
  },
  "timeout": {
    "defaultSeconds": 30
  },
  "enabledByDefault": true,
  "customNodeCatalogPath": "workflow/catalog.json"
}
```

上面的模板适合没有 pack 间依赖的简单节点包，后续新增简单节点时可以直接复制后改 `id`、`displayName`、`entrypoints` 和 `capabilities`。

可直接复制的示例文件：

- [docs/nodes/examples/example.simple-node-pack.manifest.json](examples/example.simple-node-pack.manifest.json)
- [custom_nodes/_scaffold/simple_node_pack/manifest.template.json](../../custom_nodes/_scaffold/simple_node_pack/manifest.template.json)
- [custom_nodes/hello_world_nodes/manifest.json](../../custom_nodes/hello_world_nodes/manifest.json)

## manifest 依赖模板

```json
{
  "format_id": "amvision.node-pack-manifest.v1",
  "id": "example.advanced-nodes",
  "version": "0.1.0",
  "displayName": "Example Advanced Nodes",
  "description": "复用其他 node pack 能力的复杂示例节点包。",
  "category": "custom-node-pack",
  "capabilities": [
    "pipeline.node",
    "result.postprocess"
  ],
  "dependencies": [
    {
      "nodePackId": "opencv.basic-nodes",
      "versionRange": ">=0.1.0 <1.0"
    }
  ],
  "permissionScopes": [
    "objectstore.read.ref",
    "objectstore.write.ref"
  ],
  "entrypoints": {
    "backend": "custom_nodes.example_advanced_nodes.backend.entry:register"
  },
  "compatibility": {
    "api": ">=0.1 <1.0",
    "runtime": ">=3.12"
  },
  "timeout": {
    "defaultSeconds": 30
  },
  "enabledByDefault": false,
  "customNodeCatalogPath": "workflow/catalog.json",
  "metadata": {
    "dependencyNotes": [
      "复用 opencv.basic-nodes 中已经稳定的复杂图像处理能力"
    ]
  }
}
```

依赖模板适合复杂节点包、组合节点包或桥接节点包。当前实现里 `dependencies` 是正式 manifest 字段，`metadata` 里的说明只是补充信息，不参与 loader 校验。

基于现有复杂示例 pack 的案例文件：

- [docs/nodes/examples/barcode.protocol-nodes.manifest.dependency-example.json](examples/barcode.protocol-nodes.manifest.dependency-example.json)
- [custom_nodes/_scaffold/dependent_node_pack/manifest.template.json](../../custom_nodes/_scaffold/dependent_node_pack/manifest.template.json)
- [custom_nodes/barcode_display_nodes/manifest.json](../../custom_nodes/barcode_display_nodes/manifest.json)

这个案例文件使用现有 `barcode.protocol-nodes` 的真实 pack id、entrypoint 和 capability 形状，演示当复杂条码节点链需要复用 `opencv.basic-nodes` 时，应如何把 pack 级依赖显式写进 manifest。它是文档案例，不直接替代当前仓库运行时使用的 `custom_nodes/barcode_protocol_nodes/manifest.json`。

当前仓库还提供了真正可复制的初始化模板目录 [custom_nodes/_scaffold](../../custom_nodes/_scaffold/README.md)，以及一个已经落地的复杂依赖 pack [custom_nodes/barcode_display_nodes/manifest.json](../../custom_nodes/barcode_display_nodes/manifest.json)。前者适合新 pack 起步，后者适合参考真实的 `dependencies` 写法和 entrypoint 组织方式。

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
- dependencies：对其他 node pack 的正式依赖声明；没有依赖时可省略
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

- `dependencies`：对其他 node pack 的正式依赖声明，字段为 `nodePackId` 和可选 `versionRange`
- `versionRange` 采用和 `compatibility` 一样的版本范围写法，例如 `>=0.1.0 <1.0` 或 `==0.1.0`
- 简单节点包没有 pack 间依赖时，不需要写 `dependencies`
- 复杂节点包复用其他 pack 的成熟能力时，应把依赖写进 `dependencies`，不要只留在顶层 import 或零散说明里
- 当前 loader 会在节点包进入启用集之前检查 `dependencies` 是否存在、是否启用、版本是否满足要求
- 系统级依赖、厂商 runtime、本地服务地址或额外资源文件，不属于 `dependencies`；这类前置条件应继续写在文档、metadata 或后续专用字段里

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
