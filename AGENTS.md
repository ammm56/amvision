# Project Context

本仓库的长期目标是构建一个本地优先、后续可在线化的工业视觉平台后端，整体定位范围偏工程落地和设备集成，不是通用 SaaS 平台。

## 产品范围

- 数据集管理、导入、版本化
- 训练、验证、实验追踪
- 模型转换：ONNX、OpenVINO、TensorRT、CoreML、ARM NPU
- 发布、部署、推理、回滚
- 前处理、后处理、自定义后处理插件
- 传统 OpenCV 机器视觉能力：尺寸测量、定位、规则判定
- 流程模型编排，保留后续兼容 ComfyUI 节点/流程编辑能力
- 设备上位机集成、通用设备部署、边缘嵌入式设备部署

## 当前阶段边界

- 标注暂不作为核心内建系统，优先与外部或独立工具协作
- 本地部署优先，不强依赖云基础设施
- 不在项目早期拆成大量微服务，优先模块化单体 + 独立执行器
- FastAPI 负责控制面和集成面，训练、推理、转换、流程执行通过任务系统或 worker 承载

## 默认技术基线

- Python 3.12+
- FastAPI、Pydantic 2、SQLAlchemy 2、Alembic
- SQLite 作为默认开发数据库，必须兼容 MySQL/PostgreSQL 迁移
- REST API、WebSocket、ZeroMQ
- OpenCV、supervision、PyTorch 及相关视觉模型生态
- YOLOX、YOLOv8/11/26、SAM2/3、QwenVL、RT-DETR 等模型家族
- ONNX Runtime、OpenVINO、TensorRT、CoreML、ARM NPU 相关转换与运行时适配

## 默认开发工具链

- Python 环境管理：conda，但项目代码不得依赖系统 Python 隐式状态
- 代码质量：pytest、ruff、pre-commit
- 数据库迁移：Alembic
- 文档：Markdown 优先，后续可接 MkDocs / VitePress / Docusaurus
- 容器化：Docker 作为可选发布形态，不强制作为本地开发唯一入口

## 架构原则

- 控制面、执行面、运行时面分离
- 所有重任务异步化，不在请求处理器里直接跑训练、推理、转换
- 先抽象边界，再替换实现
- 本地实现优先，但从第一天起保留可切换接口
- 平台核心不是单一模型，而是模型运行时、流程节点和插件体系

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
- DeviceAdapter

## 硬性约束

- 业务层和领域层不得直接依赖数据库方言细节
- 禁止在应用层直接写原生 SQL 作为常态路径；默认通过 ORM、Repository、Unit of Work 组织数据访问
- 禁止把云对象存储、独立 Redis、独立 MQ 作为本地开发前提
- 插件必须具备 manifest、version、config schema、timeout 和禁用机制
- 模型产物、流程模板、插件版本都必须可追溯、可回滚
- API、设备接口、模型输入输出 schema 一旦公开，变更必须显式版本化
- 项目文档默认使用中性、客观文风，避免第二人称表述，除非任务明确要求面向教程式外部读者

## 本地优先实现约定

- 数据库默认 SQLite，后续可切 MySQL/PostgreSQL
- 对象存储默认本地文件系统，由服务统一管理路径和元数据
- 任务队列默认本地持久化实现，由服务或 worker 自行管理
- 缓存默认进程内或本地实现，不把独立 Redis 当作开发阶段硬依赖

## 目标部署形态

- standalone：单机本地部署
- workstation：工控机 / 上位机场景
- edge：边缘或嵌入式设备部署
- online：后续在线服务化形态

## Agent Routing

- FastAPI 开发助手：FastAPI 路由、WebSocket、请求响应模型、依赖注入、API 测试、集成边界实现
- 后端架构师：系统分层、数据库 schema、索引、缓存、队列、对象存储、设备集成、部署和平台约束
- AI 工程师：模型训练、验证、推理优化、模型转换、前后处理、视觉流程与插件化模型链路
- 技术文档工程师：README、架构说明、API 文档、部署文档、插件文档、教程和迁移指南
- 代码审查员：代码审查、设计风险、并发/性能/安全问题、测试缺口和行为回归

## 完成标准

- 行为变更必须附带最小可验证结果
- schema 或持久化结构变更必须附带迁移方案
- 模型训练、推理、转换链路变更必须说明兼容性和验证方式
- 公共接口变化必须同步更新文档或变更说明