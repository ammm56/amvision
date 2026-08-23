# 架构决策记录

ADR 记录已经接受的关键取舍及未采用方案。ADR 可以处于待实现状态；当前行为始终由对应架构文档和代码说明，ADR 只回答“为什么这样设计”。

## 当前决策

- [ADR-0001：模块化单体与独立 Worker](ADR-0001-modular-monolith-with-workers.md)
- [ADR-0002：Bundled Python Runtime](ADR-0002-bundled-python-runtime.md)
- [ADR-0003：Node Pack 扩展模型](ADR-0003-node-pack-extension-model.md)
- [ADR-0004：模型 Deployment Runtime 参数](ADR-0004-model-deployment-runtime-options.md)
- [ADR-0005：稳定 Workflow Runtime 与不可变 App Version](ADR-0005-workflow-app-versioned-runtime.md)
- [ADR-0006：任务终态、转换发布与节点超时治理](ADR-0006-task-execution-and-runtime-reliability.md)

## 规则

- ADR 包含状态、背景、决策、未采用方案和影响。
- 已接受决策不保留“后续动作”任务清单；实现结果进入架构/API/开发文档。
- 决策被替代时保留原 ADR，并标记 superseded 及替代 ADR。
- 命令、故障排查和逐步操作不写入 ADR。
