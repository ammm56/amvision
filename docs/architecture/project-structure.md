# 项目结构规划

## 文档目的

本文档用于定义仓库级目录结构、架构层级和模块关系，服务于本地优先工业视觉平台的长期演进。

本文档只描述结构方案、边界和依赖方向，不包含实现细节、接口字段或具体技术选型的低层展开。

## 适用范围

- 仓库顶层目录划分
- 后端、前端、运行时、插件和打包模块的层级边界
- 模块之间的依赖关系与禁止耦合关系
- 文档与测试如何镜像系统边界

## 设计原则

- 后端服务、worker、运行时分离
- 前端与后端严格分离，交互只通过版本化接口完成
- 本地优先实现和在线化演进兼容并存
- 先稳定契约，再扩展实现
- 重任务异步化，避免直接挤入请求处理链路
- 前端、插件、运行时和打包产物围绕同一套公开契约协作
- 浏览器前端与外部系统默认通过 REST API 和 WebSocket 接入后端服务；同机本地部署时可补充 ZeroMQ 作为进程间通信边界
- 视觉服务与外部硬件控制解耦，项目只负责协议边界，不承担硬件驱动职责
- 各类硬件桥接、协议集成、模块连接和场景特化能力优先通过插件扩展
- 插件模型与节点编辑方向向 ComfyUI 的 custom nodes 和 workflow 体验靠拢，但保留工业场景治理约束

## 最小框架视图

- frontend/web-ui：浏览器前端界面，负责页面、工作流和结果展示
- backend/service：统一后端服务入口，负责 API、状态、任务编排和治理规则
- backend/workers：后台 worker，负责训练、推理、转换和流程执行
- plugins：扩展层，负责节点、回调、后处理和协议适配能力
- runtimes + packaging：运行时和交付层，负责开发环境、发布运行时与发行结构

## 建议仓库目录结构

```text
repo/
├─ backend/
│  ├─ service/
│  │  ├─ api/
│  │  ├─ application/
│  │  │  ├─ dataset-management/
│  │  │  ├─ model-registry/
│  │  │  ├─ model-conversion/
│  │  │  ├─ inference-results/
│  │  │  └─ deployment-binding/
│  │  ├─ domain/
│  │  │  ├─ projects/
│  │  │  ├─ datasets/
│  │  │  ├─ model-registry/
│  │  │  ├─ artifacts/
│  │  │  ├─ tasks/
│  │  │  └─ deployments/
│  │  └─ infrastructure/
│  ├─ workers/
│  │  ├─ training/
│  │  ├─ inference/
│  │  ├─ conversion/
│  │  ├─ pipelines/
│  │  └─ shared/
│  ├─ shared-contracts/
│  │  ├─ api/
│  │  ├─ events/
│  │  ├─ datasets/
│  │  │  ├─ canonical/
│  │  │  ├─ imports/
│  │  │  └─ exports/
│  │  ├─ artifacts/
│  │  ├─ plugins/
│  │  └─ integrations/
│  └─ adapters/
│     ├─ database/
│     ├─ object-store/
│     │  ├─ datasets/
│     │  │  ├─ source/
│     │  │  ├─ canonical/
│     │  │  └─ exports/
│     │  ├─ models/
│     │  └─ task-runs/
│     ├─ queue/
│     ├─ cache/
│     └─ protocols/
├─ frontend/
│  └─ web-ui/
│     ├─ shells/
│     ├─ modules/
│     │  ├─ datasets/
│     │  ├─ tasks/
│     │  ├─ models/
│     │  ├─ deployments/
│     │  ├─ integrations/
│     │  ├─ pipelines/
│     │  └─ settings/
│     ├─ workflows/
│     │  ├─ training/
│     │  ├─ inference/
│     │  ├─ release/
│     │  └─ integration-triggers/
│     └─ shared/
│        ├─ ui/
│        ├─ state/
│        ├─ services/
│        ├─ composables/
│        └─ contracts/
├─ runtimes/
│  ├─ python/
│  │  ├─ dev-conda/
│  │  └─ bundled/
│  ├─ launchers/
│  │  ├─ service/
│  │  ├─ worker/
│  │  └─ maintenance/
│  └─ manifests/
│     ├─ runtime/
│     ├─ dependencies/
│     └─ compatibility/
├─ plugins/
│  ├─ pipeline-nodes/
│  ├─ postprocessors/
│  ├─ protocol-adapters/
│  ├─ hardware-bridges/
│  ├─ module-connectors/
│  └─ manifests/
├─ assets/
│  ├─ flow-templates/
│  ├─ model-profiles/
│  └─ defaults/
├─ packaging/
│  ├─ common/
│  ├─ standalone/
│  ├─ workstation/
│  └─ edge/
├─ docs/
│  ├─ architecture/
│  ├─ api/
│  ├─ deployment/
│  ├─ plugins/
│  └─ decisions/
└─ tests/
   ├─ backend/
   ├─ frontend/
   ├─ integration/
   └─ packaging/
```

## 层级关系

### 仓库一级层级

- backend 负责平台后端服务、worker、公共契约和协议边界接入
- frontend 负责浏览器前端界面，作为独立前端工程通过 API 与后端服务协作
- runtimes 负责开发与发布运行时的统一收敛
- plugins 负责可插拔能力扩展，不承载平台主干控制逻辑
- plugins 是场景化能力、硬件桥接、协议适配和模块连接的主扩展平面
- packaging 负责发行形态收敛，不承载业务逻辑
- docs 负责公开说明和设计文档沉淀
- tests 负责验证平台边界和交互契约

### backend 内部分层

- service 是系统主入口，负责 REST API、WebSocket、必要的本地 ZeroMQ 边界、任务编排、元数据管理和权限边界
- workers 承载训练、推理、转换和流程执行，是重任务运行主体
- shared-contracts 负责跨模块共享的 schema、事件、dataset canonical schema、artifact、插件和协议集成契约
- adapters 负责数据库、对象存储、队列、缓存和协议通信能力的实际接入
- plugins 内部按能力分层：pipeline-nodes、postprocessors、protocol-adapters、hardware-bridges、module-connectors

### backend/service 内部层级

- api 层负责 REST、WebSocket 和面向外部系统的协议接入边界
- application 层负责用例编排、任务提交、状态汇聚和事务边界
- domain 层负责核心领域对象、规则和聚合关系
- infrastructure 层负责后端服务内部对 adapters、本地 ZeroMQ 通道和外部能力的接入

### backend/service 的数据与模型主干

- domain/datasets：负责 Dataset、DatasetImport、DatasetVersion、类别体系和冻结规则
- domain/model-registry：负责 Model、ModelVersion、ModelVariant、lineage 和发布候选规则
- domain/artifacts：负责 ModelArtifact、ResultArtifact、ArtifactRef、checksum 和保留策略
- domain/tasks：负责 TrainingTask、ConversionTask、InferenceTask 与 PipelineExecutionTask 的输入输出关系
- application/dataset-management：负责格式识别、导入校验、canonical 化、切分、冻结、归档和清理
- application/model-registry：负责预训练导入、训练产物登记、标签治理和版本维护
- application/model-conversion：负责转换任务提交、变体登记、兼容性和 benchmark 写回
- application/inference-results：负责 task staging、结果提升、TTL 和清理策略
- shared-contracts/datasets：负责 canonical annotation schema、导入格式 profile 和训练导出视图契约
- adapters/object-store/datasets、models、task-runs：分别承载原始导入内容、统一数据版本内容、训练导出内容、模型产物内容和任务级暂存内容

### frontend 内部分层

- shells 负责工作台骨架、布局、导航和全局状态容器
- modules 负责数据集、任务、模型、部署、集成端点、流程等业务模块页面
- workflows 负责跨模块操作流，例如训练发布链路、推理回滚链路和外部系统触发链路
- shared 负责组件、状态封装、服务访问、组合式能力和前端契约定义

### 运行时与打包层级

- runtimes/python/dev-conda 服务于开发环境复现
- runtimes/python/bundled 服务于发布时同目录 Python 环境分发
- runtimes/launchers 统一服务、worker 和维护脚本的启动入口
- packaging/common 维护各发行形态共享结构
- packaging/standalone、workstation、edge 分别维护目标形态差异化装配规则

## 模块关系

### 核心依赖方向

- frontend/web-ui -> backend/service
- external systems -> backend/service
- backend/service -> backend/shared-contracts
- backend/service -> backend/adapters
- backend/service -> backend/workers
- backend/workers -> backend/shared-contracts
- backend/workers -> runtimes
- backend/workers -> plugins
- plugins -> backend/shared-contracts
- packaging -> backend + frontend + runtimes + assets
- docs 与 tests 镜像上述公开边界，但不反向驱动业务依赖

### 关系说明

- frontend 只能依赖 backend-service 暴露的版本化 REST API、WebSocket 和任务状态流，不能直接依赖 workers 或 adapters
- 上位机、MES、采集系统和其他外部系统与前端一样，统一通过 backend-service 的公开通信边界接入，而不是直接调用 workers
- ZeroMQ 只作为同机本地部署场景下的补充通信方式，用于本地进程间低开销交互，不替代公开的 REST API 和 WebSocket 契约
- backend-service 通过 shared-contracts 统一任务、事件、artifact、协议集成和插件契约，避免后端服务与 workers 互相侵入内部实现
- workers 使用 runtimes 提供的 Python 运行时和启动环境，使用 plugins 提供可扩展节点、后处理和协议适配扩展
- 硬件直连与模块连接逻辑如有需要，优先放入 hardware-bridges 或 module-connectors 插件，而不是扩散到 core 目录
- packaging 只负责装配和发布边界，不定义业务对象，也不持有独立领域规则
- docs/architecture 描述结构边界，docs/api 描述公开接口，docs/deployment 描述运行和发布方式，docs/plugins 描述扩展约束

### 通信边界与交互路径

- frontend/web-ui <-> backend/service：页面请求、任务提交、配置读写和状态订阅，使用 REST API 与 WebSocket
- external systems <-> backend/service：上位机、MES、采集系统和其他业务系统的任务触发、结果回传和状态联动，默认使用 REST API 与 WebSocket
- backend/service <-> backend/workers：任务调度、状态回写和执行编排，通过内部任务与状态边界协作，不暴露给前端或外部系统
- local processes <-> local processes：在 standalone 或 workstation 的同机部署中，可通过 ZeroMQ 承担本地进程间消息分发或事件传递

## 禁止直接耦合的关系

- frontend 不直接调用 workers 或读取 runtimes 内部目录
- frontend 不与 backend 的 application、domain、infrastructure 代码直接共享运行时依赖
- external systems 不直接连接 workers、数据库或对象存储
- domain 不直接依赖具体数据库方言、外部消息中间件或文件系统实现
- plugins 不直接依赖 backend/service 内部 application 或 domain 细节
- backend/service 和 workers 不直接持有相机、PLC、IO 传感器或机械臂的硬件驱动实现
- 核心目录不直接承载客户定制模块连接逻辑，优先通过插件扩展点实现
- packaging 不反向定义 backend 和 frontend 的业务模块边界
- tests 不通过复制实现细节来建立伪结构，而应围绕公开契约和行为边界组织

## 文档落位建议

- [docs/README.md](../README.md) 作为整个仓库文档体系入口
- 本文档放在 docs/architecture/ 下，作为项目结构与模块边界总览
- 后续如需继续展开，可在 docs/architecture/ 下补充 backend-service、frontend-web-ui、runtime-packaging、plugin-system 等子文档
- 插件扩展原则和节点体系详见 [docs/architecture/plugin-system.md](plugin-system.md)
- AGENTS.md 仅保留项目约束、Agent Routing、Agent Color Mapping 和架构文档入口，不继续承载详细目录层级展开

## 后续可扩展文档

- docs/architecture/frontend-web-ui.md
- docs/architecture/plugin-system.md
- docs/architecture/integration-contracts.md
- docs/architecture/execution-observability.md