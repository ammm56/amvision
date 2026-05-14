# ADR-0003 节点扩展优先模型

## 背景

项目需要面对行业差异、客户定制、协议集成、硬件桥接、自定义后处理、外部触发与结果上报等高度变化的需求。

如果把这些能力持续写入核心平台，会快速导致 core 膨胀、边界失控、版本回滚困难和现场定制难管理。

## 决策

采用节点扩展优先模型。

- 场景化能力优先通过 `custom_nodes` 下的自定义节点和 node pack 实现，而不是直接进入核心模块
- 节点扩展体系向 ComfyUI custom nodes 与 workflow 的灵活性看齐，但保留版本、权限、超时、禁用和回滚管理
- 外部触发、结果回传、数据上报和后处理能力通过受控的节点定义、node pack manifest 和 runtime handler 接入

## 备选方案

### 主要通过核心代码内建扩展

- 优点：短期实现直接
- 缺点：长期演进和客户定制会持续侵蚀核心模块边界

### 仅支持核心节点，不提供自定义节点包

- 优点：系统更简单
- 缺点：无法覆盖大量现场实际需要的协议适配、结果回传和场景特化能力

## 影响

- 提高了扩展灵活性和客户定制承接能力
- 需要维护 `NodePackManifest`、`NodeDefinition`、runtime handler 和兼容性边界
- 需要在 backend-service 中维护 `custom_nodes` 目录扫描、node pack manifest 校验和节点目录装载规则

## 后续动作

- 持续维护 [docs/architecture/node-system.md](../architecture/node-system.md) 和 [docs/nodes/node-pack-manifest.md](../nodes/node-pack-manifest.md)
- 为自定义节点包提供示例模板、兼容性说明和审计要求