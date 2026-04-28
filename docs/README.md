# 文档体系总览

## 文档目的

本文档作为仓库文档总入口，用于定义文档分层、保存位置和推荐阅读路径。

本文档解决的问题不是系统实现，而是文档如何长期存放、如何被检索以及如何避免不同类型的信息混在同一份文件中。

## 文档分层

- 根目录 [AGENTS.md](../AGENTS.md) 负责项目级长期约束、技术基线、agent 路由和文档入口
- [docs/documentation-remediation-roadmap.md](documentation-remediation-roadmap.md) 负责文档整改路线、优先级和维护规则
- [docs/architecture/README.md](architecture/README.md) 负责架构与模块边界类长期参考文档
- [docs/api/README.md](api/README.md) 负责 REST API、WebSocket、ZeroMQ 和公开契约文档
- [docs/deployment/README.md](deployment/README.md) 负责开发环境、运行时、打包、安装和部署文档
- [docs/plugins/README.md](plugins/README.md) 负责插件、流程节点和扩展机制文档
- [docs/decisions/README.md](decisions/README.md) 负责架构决策记录和关键取舍沉淀

## 保存原则

- 一类信息只放在一个稳定位置，避免相同内容在多个文档重复维护
- 长期参考文档与阶段性决策记录分开存放
- 入口文档保持简明，展开内容下沉到专题文档
- 文档按主题和边界组织，不按个人或临时任务组织
- 对版本敏感的内容必须明确适用范围或迁移说明

## 推荐阅读顺序

1. [AGENTS.md](../AGENTS.md)
2. [docs/architecture/README.md](architecture/README.md)
3. [docs/documentation-remediation-roadmap.md](documentation-remediation-roadmap.md)
4. [docs/architecture/system-overview.md](architecture/system-overview.md)
5. [docs/architecture/project-structure.md](architecture/project-structure.md)
6. [docs/architecture/backend-service.md](architecture/backend-service.md)
7. [docs/architecture/frontend-web-ui.md](architecture/frontend-web-ui.md)
8. [docs/architecture/data-and-artifacts.md](architecture/data-and-artifacts.md)
9. [docs/architecture/dataset-import-spec.md](architecture/dataset-import-spec.md)
10. [docs/architecture/model-family-export-profiles.md](architecture/model-family-export-profiles.md)
11. [docs/architecture/plugin-system.md](architecture/plugin-system.md)
12. 根据任务继续进入 API、部署、插件或决策文档

## 文档维护建议

- 仓库级入口文档控制在“约束与导航”范围内，不承载详细方案展开
- 架构文档聚焦结构边界、依赖方向和模块职责，不混入实现教程
- API 文档聚焦公开契约，不混入内部实现说明
- 部署文档聚焦运行环境、目录布局、启动方式和排障，不混入架构取舍背景
- 决策文档专门记录为什么做出某个方案选择，以及被放弃的备选方案

## 当前建议补齐的文档

- API 资源与事件清单
- 典型部署拓扑说明
- 插件示例模板
- 运维排障手册