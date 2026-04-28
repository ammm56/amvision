# 插件文档目录

## 文档目的

本目录用于存放流程节点、后处理插件、协议适配插件、硬件桥接插件、模块连接插件和插件生命周期相关文档。

## 当前文档

- [docs/plugins/manifest-capabilities.md](manifest-capabilities.md)：插件 manifest、capability、permission scope 和兼容性规范
- [docs/plugins/triggers-hooks.md](triggers-hooks.md)：插件 trigger、hook、完成回调和数据上报规范

## 建议内容

- 插件 manifest 规范
- version、config schema、timeout 和禁用机制说明
- capability scope、permission scope 和依赖约束说明
- 流程节点输入输出契约
- 硬件桥接插件和协议适配插件的边界说明
- 模块连接插件和 custom nodes 扩展说明
- 插件安装、加载、回滚和兼容性说明

## 存放规则

- 插件能力说明必须围绕公开扩展边界组织，不泄漏平台内部实现细节
- 示例、模板和兼容性限制应与 manifest 规范同步维护
- 核心平台与插件平台的边界应明确，硬件直连能力默认归入可选插件而非核心模块

## 相关架构文档

- [docs/architecture/plugin-system.md](../architecture/plugin-system.md)
- [docs/architecture/system-overview.md](../architecture/system-overview.md)
- [docs/architecture/backend-service.md](../architecture/backend-service.md)