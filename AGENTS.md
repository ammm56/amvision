# Project Context

本仓库的长期目标是构建一个独立的视觉处理后端服务，优先服务现场本地部署，长期演进方向是类似 Roboflow 的全在线版本，同时保持本地部署和外部系统协议集成能力。项目定位偏工程落地和视觉服务平台，不是直接连接硬件的控制系统，也不是通用 SaaS 平台。

## 本文件职责

- 定义项目级长期约束、技术基线、架构原则和硬性边界
- 定义 Agent Routing、Agent Color Mapping 和 agent 使用边界
- 作为项目级入口文档，指向更详细的架构、部署和插件文档
- 不展开详细目录层级、模块展开或子系统深入设计；详细结构方案见 [docs/architecture/project-structure.md](docs/architecture/project-structure.md)

## 产品范围

- 数据集管理、导入、版本化
- 训练、验证、实验追踪
- 模型转换：ONNX、OpenVINO、TensorRT、CoreML、ARM NPU
- 发布、部署、推理、回滚
- 前处理、后处理、自定义后处理插件
- 传统 OpenCV 机器视觉能力：尺寸测量、定位、规则判定
- 流程模型编排，保留后续兼容 ComfyUI 节点/流程编辑能力
- 各类协议集成、硬件桥接、模块连接和场景化能力优先通过插件扩展
- 与上位机、采集系统、MES、PLC 网关或设备代理系统的协议集成
- 通用设备部署、边缘嵌入式设备部署
- 浏览器前端界面与工作站界面：任务监控、结果可视化、流程编排、集成端点操作和配置管理

## 当前阶段边界

- 标注暂不作为核心内建系统，优先与外部或独立工具协作
- 本地部署优先，不强依赖云基础设施
- 不在项目早期拆成大量微服务，优先模块化单体 + 独立执行器
- FastAPI 处理后端服务和集成面，训练、推理、转换、流程执行通过任务系统或 worker 处理
- 数据集导入默认通过 FastAPI 接收 zip 压缩包，服务端负责解压、格式校验、统一化并落到本地磁盘的通用结构
- 预训练模型默认在开发阶段按模型目录预置到磁盘，平台只登记引用关系，不提供上传接口
- 前端优先服务于浏览器界面、工作站和现场操作界面，不按营销站或通用内容站的思路设计
- 项目不直接连接相机、PLC、IO 传感器或其他外部硬件；图像、视频流、触发信号和结果回传通过界面或外部系统经协议交互完成
- 如确有直连硬件或特殊模块连接需求，应通过独立插件在受控边界中实现，而不是写入核心平台主链路

## 默认技术基线

- Python 3.12+
- FastAPI、Pydantic 2、SQLAlchemy 2、Alembic
- SQLite 作为默认开发数据库，必须兼容 MySQL/PostgreSQL 迁移
- REST API、WebSocket、ZeroMQ
- OpenCV、supervision、PyTorch 及相关视觉模型生态
- YOLOX、YOLOv8/11/26、SAM2/3、QwenVL、RT-DETR 等模型
- ONNX Runtime、OpenVINO、TensorRT、CoreML、ARM NPU 相关转换与运行时适配
- 前端界面默认使用 Vue 3 + TypeScript + Vite，状态管理与路由优先采用 Pinia、Vue Router，并按需接入 ECharts、VueUse、Vue Flow 或等价方案

## 默认开发工具链

- Python 环境管理：开发环境使用 conda，但项目代码不得依赖系统 Python 隐式状态
- 代码质量：pytest、ruff、pre-commit
- 数据库迁移：Alembic
- 文档：Markdown 优先，后续可接 MkDocs / VitePress / Docusaurus
- 容器化：Docker 作为可选发布形态，不强制作为本地开发唯一入口

## Python 运行时与发布约定

- 开发阶段使用 conda 管理 Python 环境与依赖，环境定义必须可显式复现
- 部署和发布默认提供项目同目录 Python 运行时，启动脚本、worker、CLI 和服务进程统一从该解释器启动，整体形态与 ComfyUI 的自带 Python 分发方式保持一致
- 发行包默认不要求目标机器额外安装系统 Python、conda 或其他 Python 级运行时；无法内置的 GPU 驱动、推理厂商运行时或操作系统级通信依赖必须单独列明
- Python 依赖、前端静态资源、启动脚本和必要的本地运行时配置应能一起打包，并可在 standalone、workstation、edge 形态中复用

## 前端实现约定

- 前端不并行维护 React、Angular 等多框架实现，统一收敛到 Vue 3 生态
- 界面重点是数据集、任务、模型、流程、集成端点和结果可视化，不按通用 SaaS 仪表盘或品牌展示站套路设计
- 交互设计优先考虑工控机、工作站、大图像结果浏览、弱网和离线场景，强调信息密度、稳定性和低延迟反馈
- 前端构建产物默认本地分发，不把外网 CDN 或额外系统级 Node 运行时作为部署前提

## 架构原则

- 后端服务、worker、运行时分离
- 所有重任务异步化，不在请求处理器里直接跑训练、推理、转换
- 先抽象边界，再替换实现
- 本地实现优先，但从第一天起保留可切换接口
- 平台核心不是单一模型，而是模型运行时、流程节点和插件体系
- 欠缺能力、行业特化能力和特殊集成能力优先通过插件补充，而不是直接膨胀核心模块
- 插件体系和节点编辑能力向 ComfyUI 的 custom nodes 与 workflow 体验看齐，但保持版本、权限、回滚和审计约束
- 浏览器前端与后端通过版本化 REST API、WebSocket 和任务状态流协作，避免把前端交互状态散落到后端实现细节里

## 必须先稳定的接口

- DatabaseBackend
- ObjectStore
- QueueBackend
- CacheBackend
- ModelRuntime
- TrainingBackend
- ConversionBackend
- PipelineNode
- PluginLoader
- ProtocolAdapter

## 硬性约束

- 业务层和领域层不得直接依赖数据库方言细节
- 禁止在应用层直接写原生 SQL 作为常态路径；默认通过 ORM、Repository、Unit of Work 组织数据访问
- 禁止把云对象存储、独立 Redis、独立 MQ 作为本地开发前提
- 禁止把系统 Python、系统 Node 运行时或外网 CDN 作为默认部署前提
- 插件必须具备 manifest、version、capabilities、config schema、timeout 和禁用机制
- 模型产物、流程模板、插件版本都必须可追溯、可回滚
- API、协议集成接口、模型输入输出 schema 一旦公开，变更必须显式版本化
- 项目文档默认使用中性、客观文风，避免第二人称表述，除非任务明确要求面向教程式外部读者
- 文档和命名尽量使用简单、常见、直接的词，少用偏绕的说法
- Python 代码默认写中文注释，名词保持英文不变；模块、类、方法、参数、字段和属性都要说明
- 前端主栈以 Vue 3 为准，新增界面能力不得引入并行前端框架破坏维护边界
- 核心平台不内置相机、PLC、传感器等硬件驱动；如需要直连能力，必须通过插件实现并接受额外权限和隔离约束
- projectsrc/ 下的代码仅作为开发阶段参考，不得作为本项目运行时代码直接依赖、对外响应字段来源或实现边界说明；相关模型与训练能力必须按本项目长期目标、分层边界和公开接口重新实现

## 本地优先实现约定

- 数据库默认 SQLite，后续可切 MySQL/PostgreSQL
- 对象存储默认本地文件系统，由服务统一管理路径和元数据
- 任务队列默认本地持久化实现，由服务或 worker 自行管理
- 缓存默认进程内或本地实现，不把独立 Redis 当作开发阶段硬依赖
- 前端静态资源默认随服务或本地启动器一并分发，不依赖在线资源加载

## 目标部署形态

- standalone：单机本地部署
- workstation：工控机 / 上位机场景
- edge：边缘或嵌入式设备部署
- online：后续在线服务化形态

## 文档入口

- 文档总览： [docs/README.md](docs/README.md)
- 平台整体框架、整体流程和功能总览： [docs/architecture/system-overview.md](docs/architecture/system-overview.md)
- 项目结构、目录层级和模块关系总览： [docs/architecture/project-structure.md](docs/architecture/project-structure.md)
- 插件系统与节点扩展架构： [docs/architecture/plugin-system.md](docs/architecture/plugin-system.md)
- AGENTS.md 保持简明，详细架构规划统一沉淀到 docs/architecture/ 下

## Agent Routing

- FastAPI 开发助手：FastAPI 路由、WebSocket、请求响应模型、依赖注入、API 测试、集成边界实现
- 后端架构师：系统分层、数据库 schema、索引、缓存、队列、对象存储、协议集成、部署和平台约束
- AI 工程师：模型训练、验证、推理优化、模型转换、前后处理、视觉流程与插件化模型链路
- 前端开发者：Vue 3、TypeScript、Vite、Pinia、Vue Router、任务面板、可视化界面、外部系统集成面板和流程编排界面实现
- UX 架构师：工业视觉平台的信息架构、工作站布局、任务流、流程编排交互和高频操作路径设计
- UI 设计师：工业前端界面视觉系统、组件规范、状态颜色、检测结果叠加和数据可视化界面规范
- 部署与运行时工程师：conda 开发环境、同目录 Python 运行时、自带启动器、发行包结构和 standalone/workstation/edge 发布策略
- 技术文档工程师：README、架构说明、API 文档、部署文档、插件文档、教程和迁移指南
- 代码审查员：代码审查、设计风险、并发/性能/安全问题、测试缺口和行为回归

## Agent Color Mapping

- agent frontmatter 的 color 必须唯一，避免列表展示和识别冲突
- 后端架构师：blue
- FastAPI 开发助手：green
- AI 工程师：purple
- 前端开发者：cyan
- UX 架构师：yellow
- UI 设计师：orange
- 部署与运行时工程师：red
- 技术文档工程师：teal
- 代码审查员：pink

## 完成标准

- 行为变更必须附带最小可验证结果
- schema 或持久化结构变更必须附带迁移方案
- 模型训练、推理、转换链路变更必须说明兼容性和验证方式
- 公共接口变化必须同步更新文档或变更说明
- 运行时、部署或打包方式变更必须说明 conda 开发环境、同目录 Python 环境和额外系统依赖边界
- 前端栈或浏览器前端交互约束变更必须说明与 Vue 3 主栈、离线部署和长期流程编排目标的兼容性
