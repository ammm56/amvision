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
- 先把输入输出规则定清楚，再补实现
- 重任务异步化，避免直接挤入请求处理链路
- 前端、插件、运行时和打包产物围绕同一套公开接口规则协作
- 浏览器前端与外部系统默认通过 REST API 和 WebSocket 接入后端服务；同机本地部署时可补充 ZeroMQ 作为进程间通信边界
- 视觉服务与外部硬件控制解耦，项目只负责协议边界，不承担硬件驱动职责
- 各类硬件桥接、协议集成、模块连接和场景特化能力优先通过插件扩展
- 插件模型与节点编辑方向向 ComfyUI 的 custom nodes 和 workflow 体验靠拢，但保留工业现场需要的版本、权限和回滚限制

## 源码命名约定

- backend 下的 Python 源码目录统一使用可直接导入的 snake_case 包名
- 文档中的结构路径优先与真实源码路径一致，不保留只用于规划展示的连字符目录名
- 结构优先按平台职责分层，模型增多时先在稳定层级下增加模型模块或子包，而不是为每个模型复制整套顶层目录

## 文档写法约定

- 目录名、模块名、对象名优先用简单常见词，例如 models、files、contracts、datasets
- 文档里直接写“做什么”“不做什么”“放什么”，不要写得像汇报材料
- 中文说明尽量短句，英文名也尽量短，不为了显得正式去造复杂词

## 最小框架视图

- frontend/web-ui：浏览器前端，放页面、工作流和结果查看
- backend/service：后端入口，处理 API、状态和任务安排
- backend/workers：后台 worker，跑训练、推理、转换和流程
- plugins：扩展层，放节点、回调、后处理和协议适配
- runtimes + packaging：运行和发布相关内容

## 建议仓库目录结构

```text
repo/
├─ backend/
│  ├─ service/
│  │  ├─ api/
│  │  ├─ application/
│  │  │  ├─ datasets/
│  │  │  ├─ models/
│  │  │  ├─ conversions/
│  │  │  ├─ inference_results/
│  │  │  └─ deployments/
│  │  ├─ domain/
│  │  │  ├─ projects/
│  │  │  ├─ datasets/
│  │  │  ├─ models/
│  │  │  ├─ files/
│  │  │  ├─ tasks/
│  │  │  └─ deployments/
│  │  └─ infrastructure/
│  ├─ workers/
│  │  ├─ training/
│  │  ├─ inference/
│  │  ├─ conversion/
│  │  ├─ pipelines/
│  │  └─ shared/
│  ├─ contracts/
│  │  ├─ api/
│  │  ├─ events/
│  │  ├─ datasets/
│  │  │  ├─ canonical/
│  │  │  ├─ imports/
│  │  │  └─ exports/
│  │  ├─ files/
│  │  ├─ plugins/
│  │  └─ integrations/
│  └─ adapters/
│     ├─ database/
│     ├─ object_store/
│     │  ├─ datasets/
│     │  │  ├─ source/
│     │  │  ├─ canonical/
│     │  │  └─ exports/
│     │  ├─ models/
│     │  └─ task_runs/
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

- backend：后端代码，包括服务、worker、共享规则和基础接入
- frontend：浏览器前端工程，通过 API 和后端协作
- runtimes：开发和发布时要用到的运行时
- plugins：可插拔扩展，不放平台主干逻辑
- plugins 是场景化能力、硬件桥接、协议适配和模块连接的主扩展平面
- packaging：发行包装配，不放业务逻辑
- docs：说明和设计文档
- tests：边界和交互验证

### backend 内部分层

- service：系统主入口，处理 REST API、WebSocket、本地 ZeroMQ、任务安排和元数据
- workers：重任务执行层，跑训练、推理、转换和流程
- contracts：放共用的 schema、事件、数据集格式、文件规则、插件和集成规则
- adapters：接数据库、对象存储、队列、缓存和协议通信
- plugins 内部按能力分层：pipeline-nodes、postprocessors、protocol-adapters、hardware-bridges、module-connectors

### backend/service 内部层级

- api 层负责 REST、WebSocket 和面向外部系统的协议接入边界
- application 层负责用例编排、任务提交、状态汇聚和事务边界
- domain 层负责核心领域对象、规则和聚合关系
- infrastructure 层负责后端服务内部对 adapters、本地 ZeroMQ 通道和外部能力的接入

### backend/service/api 建议子层级

- app.py：FastAPI 应用装配入口
- rest/router.py：REST 根路由与版本入口
- rest/v1/routes：按资源分组的版本化 REST 路由文件，例如 system、datasets、models、tasks、deployments
- ws/router.py：WebSocket 根路由与订阅入口
- deps：鉴权主体、Project scope、分页、数据库会话等依赖注入定义
- middleware：request context、访问日志、异常映射等通用中间件

### backend/service/infrastructure 建议子层级

- db：SQLAlchemy engine、session、Unit of Work 和迁移相关装配
- persistence：ORM 实体与 Repository 实现
- object_store：本地文件系统或其他 ObjectStore 的适配实现
- queue：QueueBackend 的具体实现与调度接线
- cache：可选缓存实现
- protocols：外部协议接入和内部 ZeroMQ 适配

### backend/service 的数据与模型主干

- domain/datasets：放 Dataset、DatasetImport、DatasetVersion 和冻结规则
- domain/models：放 Model、ModelVersion、ModelBuild、lineage 和发布规则
- domain/files：放模型文件、结果文件、FileRef、checksum 和保留规则
- domain/tasks：放 TrainingTask、ConversionTask、InferenceTask 与 PipelineExecutionTask 的输入输出关系
- application/datasets：处理格式识别、导入检查、canonical 化、切分、冻结、归档和清理
- application/models：处理预置预训练模型登记、训练输出登记、标签管理和版本维护
- application/conversions：处理转换任务提交、导出版本登记、兼容性和 benchmark 写回
- application/inference_results：处理 task staging、结果提升、TTL 和清理
- contracts/datasets：放 canonical annotation schema、导入格式规则和数据集导出格式规则
- adapters/object_store/datasets、models、task_runs：分别放原始导入、统一数据版本、训练导出、模型文件和任务暂存内容

### frontend 内部分层

- shells 负责工作台骨架、布局、导航和全局状态容器
- modules 负责数据集、任务、模型、部署、集成端点、流程等业务模块页面
- workflows 负责跨模块操作流，例如训练发布链路、推理回滚链路和外部系统触发链路
- shared：放组件、状态封装、服务访问、组合式能力和前端接口定义

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
- backend/service -> backend/contracts
- backend/service -> backend/adapters
- backend/service -> backend/workers
- backend/workers -> backend/contracts
- backend/workers -> runtimes
- backend/workers -> plugins
- plugins -> backend/contracts
- packaging -> backend + frontend + runtimes + assets
- docs 与 tests 镜像上述公开边界，但不反向驱动业务依赖

### 关系说明

- frontend 只能依赖 backend-service 暴露的版本化 REST API、WebSocket 和任务状态流，不能直接依赖 workers 或 adapters
- 上位机、MES、采集系统和其他外部系统与前端一样，统一通过 backend-service 的公开通信边界接入，而不是直接调用 workers
- ZeroMQ 只作为同机本地部署场景下的补充通信方式，用于本地进程间低开销交互，不替代公开的 REST API 和 WebSocket 规则
- backend-service 和 workers 通过 contracts 共享任务、事件、文件规则、集成规则和插件规则，避免互相侵入内部实现
- workers 使用 runtimes 提供的 Python 运行时和启动环境，使用 plugins 提供可扩展节点、后处理和协议适配扩展
- 硬件直连与模块连接逻辑如有需要，优先放入 hardware-bridges 或 module-connectors 插件，而不是扩散到 core 目录
- packaging 只负责装配和发布边界，不定义业务对象，也不持有独立领域规则
- docs/architecture 说明结构边界，docs/api 说明公开接口，docs/deployment 说明运行和发布方式，docs/plugins 说明扩展规则

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
- 核心目录不直接放客户定制模块连接逻辑，优先通过插件扩展点实现
- packaging 不反向定义 backend 和 frontend 的业务模块边界
- tests 不通过复制实现细节来建立伪结构，而应围绕公开接口规则和行为边界组织

## 文档落位建议

- [docs/README.md](../README.md) 作为整个仓库文档体系入口
- 本文档放在 docs/architecture/ 下，作为项目结构与模块边界总览
- 后续如需继续展开，可在 docs/architecture/ 下补充 backend-service、frontend-web-ui、runtime-packaging、plugin-system 等子文档
- 插件扩展原则和节点体系详见 [docs/architecture/plugin-system.md](plugin-system.md)
- AGENTS.md 仅保留项目约束、Agent Routing、Agent Color Mapping 和架构文档入口，不继续展开详细目录层级

## 后续可扩展文档

- docs/architecture/frontend-web-ui.md
- docs/architecture/plugin-system.md
- docs/architecture/integration-contracts.md
- docs/architecture/execution-observability.md