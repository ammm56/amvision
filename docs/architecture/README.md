# 架构文档总览

## 文档目的

本目录用于存放长期稳定的架构参考文档，覆盖目录结构、层级关系、模块边界和关键子系统职责。

本目录不承担接口实现说明、部署步骤清单或临时讨论记录。

## 当前文档

- [docs/architecture/system-overview.md](system-overview.md)：平台整体框架、一级模块、端到端流程和所需功能总览
- [docs/architecture/project-structure.md](project-structure.md)：项目目录结构、层级关系、模块关系和禁止直接耦合关系总览
- [docs/architecture/backend-service.md](backend-service.md)：后端服务职责、任务状态、执行调度、QueueBackend 和状态回写边界
- [docs/architecture/frontend-web-ui.md](frontend-web-ui.md)：浏览器前端 Web UI 的模块划分、路由结构、状态组织和交互边界
- [docs/architecture/plugin-system.md](plugin-system.md)：插件体系、扩展边界、节点模型和 ComfyUI 对齐方向
- [docs/architecture/data-and-artifacts.md](data-and-artifacts.md)：关键对象关系、artifact 引用规则和版本追踪链路
- [docs/architecture/dataset-import-spec.md](dataset-import-spec.md)：DatasetImport、canonical annotation schema、任务族格式矩阵和训练导出视图规范
- [docs/architecture/model-family-export-profiles.md](model-family-export-profiles.md)：模型家族到 export profile 的映射、profile 命名和目录结构约定
- [docs/architecture/runtime-packaging.md](runtime-packaging.md)：开发运行时、同目录 Python 发布运行时和发行装配结构

## 建议后续文档

- integration-contracts.md：集成端点、协议适配和回调边界的专题展开
- execution-observability.md：任务执行可观测性、日志、指标和告警模型
- ui-schema-and-extension.md：前端插件 UI schema、节点面板和结果展示扩展规范

## 存放规则

- 一份文档只负责一个稳定主题
- 结构总览文档优先引用专题文档，不在单文件持续膨胀
- 子系统变化若影响长期边界，应优先更新本目录文档，而不是只留在提交说明中
- 架构决策的取舍过程不写入本目录正文，统一下沉到 [docs/decisions/README.md](../decisions/README.md) 对应的决策记录

## 推荐阅读路径

1. [docs/architecture/system-overview.md](system-overview.md)
2. [docs/architecture/project-structure.md](project-structure.md)
3. [docs/architecture/backend-service.md](backend-service.md)
4. [docs/architecture/frontend-web-ui.md](frontend-web-ui.md)
5. [docs/architecture/data-and-artifacts.md](data-and-artifacts.md)
6. [docs/architecture/dataset-import-spec.md](dataset-import-spec.md)
7. [docs/architecture/model-family-export-profiles.md](model-family-export-profiles.md)
8. [docs/architecture/plugin-system.md](plugin-system.md)
9. [docs/architecture/runtime-packaging.md](runtime-packaging.md)
10. 按任务继续进入集成契约或可观测性专题文档