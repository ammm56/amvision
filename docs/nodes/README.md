# 节点扩展文档目录

## 文档目的

本目录用于存放 node pack、custom node、runtime hook 和节点扩展生命周期相关文档。

## 当前文档

- [docs/nodes/node-pack-manifest.md](node-pack-manifest.md)：node pack manifest、capability、permission scope 和兼容性规范
- [docs/nodes/runtime-hooks-callbacks.md](runtime-hooks-callbacks.md)：节点扩展 trigger、hook、完成回调和数据上报规范
- [docs/architecture/workflow-json-contracts.md](../architecture/workflow-json-contracts.md)：workflow 节点目录 JSON 合同，以及 barcode.protocol-nodes 的 catalog.json 手动生成流程

## 建议内容

- node pack manifest 规范
- version、config schema、timeout 和禁用机制说明
- capability scope、permission scope 和依赖约束说明
- 流程节点输入输出规则
- 硬件桥接节点包和协议节点包的边界说明
- 模块连接节点包和 custom nodes 扩展说明
- node pack 安装、加载、回滚和兼容性说明

## 存放规则

- 节点扩展能力说明必须围绕公开扩展边界组织，不泄漏平台内部实现细节
- 示例、模板和兼容性限制应与 manifest 规范同步维护
- 核心平台与节点扩展平台的边界应明确，硬件直连能力默认归入可选节点包而非核心模块

## 相关架构文档

- [docs/architecture/node-system.md](../architecture/node-system.md)
- [docs/architecture/system-overview.md](../architecture/system-overview.md)
- [docs/architecture/backend-service.md](../architecture/backend-service.md)
