# 架构文档总览

## 文档目的

本目录用于存放长期稳定的架构参考文档，覆盖目录结构、层级关系、模块边界和关键子系统职责。

本目录不承担接口实现说明、部署步骤清单或临时讨论记录。

## 当前文档

- [docs/architecture/system-overview.md](system-overview.md)：平台整体框架、一级模块、端到端流程和所需功能总览
- [docs/architecture/current-implementation-status.md](current-implementation-status.md)：当前主干已经落地的整体框架、主要代码落点、运行时矩阵和下一步收敛重点
- [docs/architecture/execution-sequences.md](execution-sequences.md)：训练、转换、部署推理和 workflow execute 四条关键调用顺序图
- [docs/architecture/project-structure.md](project-structure.md)：项目目录结构、层级关系、模块关系和禁止直接耦合关系总览
- [docs/architecture/backend-service.md](backend-service.md)：后端服务职责、任务状态、执行调度、QueueBackend 和状态回写边界
- [docs/architecture/task-system.md](task-system.md)：统一任务实体、资源调度模型、任务 schema 和 worker pool 划分
- [docs/architecture/detection-model-rules.md](detection-model-rules.md)：检测类模型的最小平台规则，以及正式对象与 metadata 的边界
- [docs/architecture/yolox-module-design.md](yolox-module-design.md)：YOLOX 在 amvision 里的模块拆分、目录位置、当前代码落点和后续收敛方向
- [docs/architecture/frontend-web-ui.md](frontend-web-ui.md)：浏览器前端 Web UI 的模块划分、路由结构、状态组织和交互边界
- [docs/architecture/plugin-system.md](plugin-system.md)：节点扩展体系、node pack 边界、custom node 模型和 ComfyUI 对齐方向
- [docs/architecture/workflow-json-contracts.md](workflow-json-contracts.md)：NodeDefinition、payload contract、图模板与流程应用 JSON 合同
- [docs/architecture/data-and-files.md](data-and-files.md)：关键对象、文件引用和版本关系
- [docs/architecture/dataset-import-spec.md](dataset-import-spec.md)：DatasetImport、通用数据格式、任务类型格式矩阵和数据集导出规范
- [docs/architecture/dataset-export-formats.md](dataset-export-formats.md)：数据集导出格式列表、格式命名和模型默认格式映射
- [docs/architecture/runtime-packaging.md](runtime-packaging.md)：开发运行时、同目录 Python 发布运行时和发行装配结构

## 建议后续文档

- integration-rules.md：集成端点、协议适配和回调规则
- logs-and-metrics.md：任务日志、指标和告警
- ui-schema-and-extension.md：前端节点 UI schema、节点面板和结果展示扩展规范

## 存放规则

- 一份文档只写一个稳定主题
- 结构总览文档优先引用专题文档，不在单文件持续膨胀
- 子系统变化如果影响长期边界，先更新这里的文档，不要只写在提交说明里
- 架构决策的取舍过程不写入本目录正文，统一下沉到 [docs/decisions/README.md](../decisions/README.md) 对应的决策记录

## 推荐阅读路径

1. [docs/architecture/system-overview.md](system-overview.md)
2. [docs/architecture/current-implementation-status.md](current-implementation-status.md)
3. [docs/architecture/execution-sequences.md](execution-sequences.md)
4. [docs/architecture/project-structure.md](project-structure.md)
5. [docs/architecture/backend-service.md](backend-service.md)
6. [docs/architecture/task-system.md](task-system.md)
7. [docs/architecture/detection-model-rules.md](detection-model-rules.md)
8. [docs/architecture/yolox-module-design.md](yolox-module-design.md)
9. [docs/architecture/frontend-web-ui.md](frontend-web-ui.md)
10. [docs/architecture/plugin-system.md](plugin-system.md)
11. [docs/architecture/workflow-json-contracts.md](workflow-json-contracts.md)
12. [docs/architecture/data-and-files.md](data-and-files.md)
13. [docs/architecture/dataset-import-spec.md](dataset-import-spec.md)
14. [docs/architecture/dataset-export-formats.md](dataset-export-formats.md)
15. [docs/architecture/runtime-packaging.md](runtime-packaging.md)
16. 按任务继续进入集成规则或日志专题文档