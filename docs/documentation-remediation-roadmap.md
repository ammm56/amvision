# 文档整改路线图

## 文档目的

本文档用于把当前项目文档审查结论转换为正式整改路线，明确已完成部分、剩余缺口、优先级和完成标准，避免后续文档继续无序增长。

## 当前结论摘要

- 仓库已经具备项目约束、文档入口、系统总览、结构规划和插件系统三层骨架
- 主干方向已经清晰：前后端分离、本地优先、后端服务与 worker 分离、插件优先扩展、同目录 Python 发布运行时
- 主要问题不是方向错误，而是专题文档不完整、部分摘要层内容重复、少量主题只有目录入口没有正式内容

## 已完成文档骨架

- [AGENTS.md](../AGENTS.md)：项目级长期约束、技术基线、agent 路由和文档入口
- [docs/README.md](README.md)：文档分层和阅读顺序
- [docs/architecture/system-overview.md](architecture/system-overview.md)：平台目标、边界、流程和功能版图
- [docs/architecture/project-structure.md](architecture/project-structure.md)：目录层级、模块边界和通信关系
- [docs/architecture/plugin-system.md](architecture/plugin-system.md)：插件类型、生命周期、节点与 hook 扩展边界
- [docs/architecture/backend-service.md](architecture/backend-service.md)：后端服务职责、任务状态、调度和状态回写
- [docs/architecture/frontend-web-ui.md](architecture/frontend-web-ui.md)：浏览器前端 Web UI 的模块、路由、状态和交互边界
- [docs/api/communication-contracts.md](api/communication-contracts.md)：REST、WebSocket、ZeroMQ 的职责划分
- [docs/architecture/data-and-artifacts.md](architecture/data-and-artifacts.md)：关键对象关系和可追溯规则
- [docs/architecture/dataset-import-spec.md](architecture/dataset-import-spec.md)：数据集导入、canonical schema 与任务格式矩阵规范
- [docs/architecture/runtime-packaging.md](architecture/runtime-packaging.md)：开发运行时、发布运行时和装配层结构
- [docs/deployment/bundled-python-deployment.md](deployment/bundled-python-deployment.md)：同目录 Python 的部署与回滚流程
- [docs/plugins/manifest-capabilities.md](plugins/manifest-capabilities.md)：插件 manifest、capability 和 permission scope 规范
- [docs/plugins/triggers-hooks.md](plugins/triggers-hooks.md)：插件 trigger、hook、回调和数据上报规范
- [docs/decisions/ADR-0001-modular-monolith-with-workers.md](decisions/ADR-0001-modular-monolith-with-workers.md)：模块化单体 + worker 决策记录
- [docs/decisions/ADR-0002-bundled-python-runtime.md](decisions/ADR-0002-bundled-python-runtime.md)：同目录 Python 运行时决策记录
- [docs/decisions/ADR-0003-plugin-first-extension-model.md](decisions/ADR-0003-plugin-first-extension-model.md)：插件优先扩展决策记录

## 当前仍需补齐的主题

- API 资源清单、事件类型清单和错误语义细表
- 部署脚本、健康检查与运维排障模板
- 插件示例模板与参考实现
- 集成契约与可观测性专题文档

## 冗余与收敛建议

### 需要继续保持的文档分工

- AGENTS.md 只保留约束、边界、agent 路由和文档入口
- system-overview 只负责整体目标、模块协同和流程
- project-structure 只负责结构边界、依赖方向和通信关系
- plugin-system 只负责插件体系与扩展边界

### 需要避免的重复

- 不要在 AGENTS.md 继续膨胀系统流程和模块细节
- 不要在 system-overview 中重复写结构文档已经固定的目录层级
- 不要在 deployment 文档中重新解释架构取舍背景
- 不要让 API 文档混入内部实现细节或数据库模型说明

## 整改优先级

### P0：当前应立即完成

- backend-service
- communication-contracts
- data-and-artifacts
- runtime-packaging
- bundled-python-deployment

### P1：下一阶段应完成

- API 资源明细与事件清单
- 插件示例模板
- 集成契约与可观测性文档

### P2：随实现推进补齐

- 典型部署拓扑示意
- 运维排障手册
- 前端 UI schema 扩展规范

## 完成标准

- 每个稳定主题只有一个主文档负责定义长期边界
- 入口 README 能准确指向现有主题，不保留已经完成却仍标记为待补的条目
- 对外公开契约、插件扩展契约和运行时边界都有明确文档归属
- 关键对象、关键状态和关键通信边界能在对应文档中独立读懂

## 文档维护规则

- 架构变化先更新对应主文档，再考虑补充实现说明
- 已公开的 API、事件、插件能力和部署约束发生变化时，必须同步修改契约文档
- 发生重要取舍时优先写 ADR，再把稳定结果回写 AGENTS.md 或专题文档
- 新增文档前先判断是否已有主文档可以承载，避免同主题分裂

## 推荐阅读路径

1. [AGENTS.md](../AGENTS.md)
2. [docs/README.md](README.md)
3. [docs/architecture/system-overview.md](architecture/system-overview.md)
4. [docs/architecture/project-structure.md](architecture/project-structure.md)
5. [docs/architecture/backend-service.md](architecture/backend-service.md)
6. [docs/architecture/frontend-web-ui.md](architecture/frontend-web-ui.md)
7. [docs/api/communication-contracts.md](api/communication-contracts.md)
8. [docs/architecture/data-and-artifacts.md](architecture/data-and-artifacts.md)
9. [docs/architecture/dataset-import-spec.md](architecture/dataset-import-spec.md)
10. [docs/architecture/plugin-system.md](architecture/plugin-system.md)
11. [docs/plugins/manifest-capabilities.md](plugins/manifest-capabilities.md)
12. [docs/plugins/triggers-hooks.md](plugins/triggers-hooks.md)
13. [docs/architecture/runtime-packaging.md](architecture/runtime-packaging.md)
14. [docs/deployment/bundled-python-deployment.md](deployment/bundled-python-deployment.md)
15. [docs/decisions/ADR-0001-modular-monolith-with-workers.md](decisions/ADR-0001-modular-monolith-with-workers.md)