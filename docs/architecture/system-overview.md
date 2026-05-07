# 平台整体方案总览

## 文档目的

本文档用于从平台视角描述整体框架、主要模块、端到端流程和所需功能，帮助建立对本地优先工业视觉平台的完整理解。

本文档聚焦整体方案和系统边界，不展开实现细节、接口字段或具体类设计。

## 适用范围

- 平台整体目标与边界
- 一级模块和职责分工
- 目录结构与模块层级的对应关系
- 关键业务流程与状态流转
- 所需功能的全局版图

## 平台目标

- 支持前后端分离部署，保持浏览器前端、后端服务和 worker 的职责清晰
- 支持数据集、训练、验证、模型转换、发布、部署、推理和回滚的完整工程链路
- 支持传统 OpenCV 机器视觉流程与深度学习模型流程并存
- 支持流程编排与插件扩展，保留向 ComfyUI 式节点语义兼容的长期演进能力
- 支持 standalone、workstation、edge 三类本地部署形态，并为后续演进为类似 Roboflow 的在线版本预留边界
- 支持通过插件补齐协议集成、硬件桥接、模块连接和场景化能力，保持核心平台精简稳定

## 边界澄清

- 本项目采用前后端分离架构，前端界面与后端服务通过版本化 REST API 和 WebSocket 交互
- 本项目是独立视觉处理后端服务，不承担相机、PLC、IO 传感器、机械臂等外部硬件的直接连接和驱动职责
- 图像、视频流、任务触发、结果回传和联动信号通过界面或外部系统经协议交互完成
- 上位机、采集系统、MES、PLC 网关、设备代理系统等属于外部系统，本项目只定义协议边界和集成接口规则
- 上位机和其他外部系统原则上与前端共用同一套公开通信规则，即 REST API、WebSocket 和版本化接口规则
- 设备集成在本文档中指“与外部系统的协议协作”，不指“项目直接接入硬件”
- 在 standalone 或 workstation 的同机本地部署中，可按需要补充 ZeroMQ 作为本地进程间通信方式，但不替代公开接口边界
- 如确有现场直连相机、PLC、传感器等需求，应通过独立插件在受控边界中实现，而不是进入核心平台主链路

## 方案总览

平台由浏览器前端、后端服务、后台 workers、运行时、插件体系、协议集成边界、基础设施适配层和打包发布层共同组成。

## 当前实现状态入口

- 当前主干已经打通以 YOLOX 为中心的训练、人工验证、数据集级评估、转换、DeploymentInstance 发布和同步 / 异步推理接口闭环。
- 当前 backend-service 除了提供 REST / WebSocket 控制面，也会按配置托管 BackgroundTaskManager 和 deployment process supervisor。
- 当前已经落地的代码模块、运行时矩阵和下一步收敛重点见 [docs/architecture/current-implementation-status.md](current-implementation-status.md)。

## 最小框架视图

- frontend/web-ui：浏览器前端，放页面、工作流和结果查看
- backend/service：后端入口，处理 API、状态和任务安排
- backend/workers：后台 worker，跑训练、推理、转换和流程
- custom_nodes：节点扩展层，放 node pack、custom node 和相关扩展资产
- runtimes + packaging：运行和发布相关内容

```text
操作人员 / 工程人员 / 外部系统 / 模型产物 / 节点包
        |              |
        |              | REST API / WebSocket / 协议调用 / 数据提交 / 结果回传
        v              v
frontend/web-ui    protocol integration boundary
        |              |
        +------ REST API / WebSocket / 状态流 ------+
                                               |
                                               v
                                      backend/service
                                               |
                                                                 任务提交 / 元数据 / 状态编排 / 规则检查
                                  +------------+-------------+
                                  |                          |
                                  v                          v
                           backend/workers           backend/adapters
                                  |                          |
                                                                                         | 调用运行时 / 节点包      | 接入数据库、对象存储、队列、缓存、协议通信
                                  v                          v
                               runtimes                 本地基础设施与外部系统协议端点
                                  |
                                                                                         | 同机本地部署时可补充 ZeroMQ 进程间通信
                                                                                         v
                                                                                 local ipc
                                                                                         |
                                  v
                         custom_nodes / assets / packaging
```

## 一级模块与职责

### frontend/web-ui

- 放浏览器前端、工作站和现场操作界面
- 提供数据集、任务、模型、部署、外部系统集成和流程编排等界面能力
- 作为独立前端工程存在，不与后端内部模块混合部署逻辑
- 通过版本化 REST API、WebSocket 和任务状态流与后端服务协作

### backend/service

- 是统一后端入口，处理元数据、任务安排和对外接口
- 管理项目、数据集、任务、模型、部署实例、集成端点、流程模板和节点包记录
- 为浏览器前端、上位机和其他外部系统提供统一的公开通信边界
- 协调 workers、适配器和公开接口规则，避免前端或外部直接耦合内部执行逻辑

### backend/workers

- 跑训练、验证、推理、转换和流程这些重任务
- 作为后台 worker 运行，接受后端服务调度并回写任务状态和结果
- 依赖运行时和节点扩展体系完成模型执行、OpenCV 流程和后处理扩展

### backend/contracts

- 放 API、事件、文件规则、节点规则和集成规则
- 给后端服务、workers、节点包和前端提供共用格式
- 这里的内容一旦公开，就尽量保持稳定

### backend/adapters

- 接数据库、对象存储、队列、缓存和协议通信
- 屏蔽具体 SQLite、文件系统、本地队列、ZeroMQ 和其他通信协议实现差异

### runtimes

- 放 conda 开发环境定义和发布时同目录 Python 运行时
- 管理服务、worker 和维护脚本的统一启动入口
- 管理运行时依赖、兼容性和目标平台差异边界

### custom_nodes

- 放流程节点包、结果处理节点包、协议节点包、硬件桥接节点包和模块连接节点包
- 通过 manifest、节点目录和接口规则接入平台，不直接侵入后端服务内部实现
- 在节点编辑器中与 core nodes 统一注册和展示，方向上向 ComfyUI custom nodes 看齐
- 大量自定义功能以 node pack 形式独立实现、独立加载，可作为节点或连接器接入平台
- 节点包可连接外部系统、内部模块、任务对象和数据对象，承担处理、回传和联动职责

### assets

- 放流程模板、模型配置、默认资源和运行时辅助资产
- 为训练、转换、部署和流程编排提供可复用的静态资源基础

### packaging

- 放 standalone、workstation、edge 三类发行结构的组装逻辑
- 将 backend、frontend、runtimes、assets 和必要配置收敛成可分发产物

## 目录结构与模块层级对应

- 仓库目录结构、层级关系和模块依赖方向见 [docs/architecture/project-structure.md](project-structure.md)
- 本文档主要回答“为什么要这样分模块”和“这些模块怎么一起工作”
- project-structure 讲静态结构，system-overview 讲流程和整体功能
- 任务状态、执行调度与后端服务职责详见 [docs/architecture/backend-service.md](backend-service.md)
- 检测类模型的最小共享对象与 metadata 边界详见 [docs/architecture/detection-model-rules.md](detection-model-rules.md)
- 对象关系与文件追踪详见 [docs/architecture/data-and-files.md](data-and-files.md)
- 开发运行时与发布装配详见 [docs/architecture/runtime-packaging.md](runtime-packaging.md)

## 交互关系总则

- 浏览器前端与后端服务之间是标准前后端分离关系，不共享内部模块实现
- 上位机、MES、采集系统和其他外部系统通过与前端一致的公开边界接入后端
- REST API 用来做请求响应，WebSocket 用来推送状态、日志和任务事件
- ZeroMQ 只用于同机本地部署中的进程间高频通信或低开销消息传递，不作为对外公开接口规则

## 整体流程

### 1. 数据集准备流程

1. 创建项目、数据集和数据版本
2. 导入本地图片、视频、采集结果或外部数据源清单
3. 记录元数据、样本组织方式和版本信息
4. 为训练、验证、传统视觉流程或推理任务准备输入集

### 2. 训练与验证流程

1. 从数据集版本和训练配置创建训练任务
2. 后端服务写入任务定义并提交到 worker
3. worker 在运行时环境中启动训练、验证和指标采集
4. 训练结果生成模型文件、指标记录和实验轨迹
5. 验证结论回写到后端服务，用于后续转换、发布和回滚判断

### 3. 模型转换与发布流程

1. 基于模型文件选择目标运行时和目标部署平台
2. 发起 ONNX、OpenVINO、TensorRT、CoreML 或 ARM NPU 转换任务
3. 记录转换结果、输入输出约束、精度与 benchmark 信息
4. 将可部署文件注册为可发布版本，并关联兼容平台和回滚信息

### 4. 部署与推理流程

1. 创建部署实例，绑定模型版本、运行时配置和目标运行环境
2. 通过本地运行时和启动器启动服务或 worker 进程
3. 前端或外部系统通过 REST API、WebSocket 或约定好的接口规则提交图片、视频流或推理请求，worker 完成推理和后处理
4. 后端服务回传推理结果、状态、日志和告警信息
5. 需要时执行灰度切换、回滚或重新部署

### 5. 流程编排流程

1. 选择模型节点、传统视觉节点、后处理节点、协议集成节点和自定义节点
2. 通过流程模板或节点编辑器定义执行图
3. 后端服务检查节点输入输出规则和资源依赖
4. worker 按流程图运行节点链路，并允许自定义节点连接内部模块、外部端点和相关数据对象
5. 模板与节点版本可被追踪、复用和回滚

### 6. 外部系统协议集成流程

1. 注册外部系统、协议配置和回调规则
2. 由上位机、采集系统或其他业务系统提交图片、视频流、批量任务或触发请求，也可由节点扩展定义自定义触发入口
3. 后端服务根据 REST API、WebSocket 或其他版本化接口规则完成任务创建、状态跟踪和结果分发
4. 结果可经核心链路或节点扩展上报链路回传到前端、上位机、MES、PLC 网关或其他外部系统
5. 发生异常时支持禁用集成端点、切换回调策略、停用节点包或回滚模型版本

### 7. 节点扩展与节点注册流程

1. 安装或发现 node pack，读取 manifest、capability 和节点定义
2. 后端服务完成版本校验、依赖校验、权限校验和启用状态登记
3. 前端节点编辑器读取统一节点目录、参数 schema 和分类信息
4. worker 在运行时环境中按节点输入输出规则执行 custom node 逻辑，并允许节点扩展接入内部模块、外部系统和相关数据流
5. 节点扩展可实现外部触发、执行完成后的数据上报、结果后处理和跨模块衔接逻辑
6. 节点包升级、禁用、回滚后，流程模板与部署引用关系同步更新

## 所需功能版图

### 项目与数据能力

- 项目空间管理
- 数据集创建、导入、组织和版本化
- 样本元数据、标签引用和数据审计
- 数据预览、筛选和任务输入集准备

### 训练与实验能力

- 训练任务创建、排队、执行和取消
- 验证任务、指标记录和实验追踪
- 训练配置版本化与基线比对
- 训练输出文件和日志归档

### 模型与文件能力

- 模型注册与版本管理
- 文件类型管理
- 模型转换、量化和目标平台兼容性记录
- benchmark、输入输出约束和回滚信息管理

### 部署与推理能力

- 部署实例管理
- 运行时配置与资源配置管理
- 推理任务、批处理和结果回传
- 部署切换、回滚、日志和健康状态监控

### 流程与节点扩展能力

- 流程模板管理
- 节点编排、节点版本和节点依赖校验
- 结果处理节点包、协议节点包、硬件桥接节点包、模块连接节点包和 custom node 加载
- 节点包 manifest、capability、timeout、禁用和版本追踪
- 统一节点目录、节点参数 schema 和节点分类管理
- 向 ComfyUI 风格靠拢的 custom nodes 和 workflow 扩展体验
- 以节点包独立实现和加载外部触发、自定义回调、完成后数据上报和结果处理逻辑
- 以节点包连接项目、任务、部署、流程模板、集成端点和外部系统数据

### 外部系统协议集成能力

- 外部系统端点注册、协议配置和回调管理
- 图片、视频流、批量任务和推理请求的协议接入
- 结果回传、状态订阅和联动触发的协议适配
- REST API、WebSocket、ZeroMQ 或其他本地与在线协议边界支持
- 与上位机、采集系统、MES、PLC 网关或设备代理系统协同
- 允许通过节点扩展实现自定义触发入口、完成通知、数据上报和特定系统联动

### 硬件桥接与模块扩展能力

- 以独立节点包形式实现相机、PLC、传感器、机械臂等硬件桥接能力
- 以独立节点包形式实现跨模块事件连接、任务衔接和结果转发能力
- 对可选节点包施加额外权限、隔离、超时和回滚约束
- 允许节点扩展按受控接口规则连接内部模块、外部端点和数据对象，形成可编排的自定义链路

### 浏览器前端能力

- 数据集、任务、模型、部署、集成端点和流程编排页面
- 训练进度、任务状态、日志和告警面板
- 图像结果查看、检测框叠加和图表可视化
- 大图像浏览、工作站布局和触屏兼容交互

### 系统管理功能

- 任务状态流和事件审计
- 节点包和模型版本追踪
- 配置管理、兼容性声明和回滚机制
- 基础健康检查、错误记录和最小可观测性能力

## 关键对象

- Project
- Dataset
- DatasetVersion
- TrainingTask
- ValidationTask
- ModelFile
- ConversionTask
- DeploymentInstance
- InferenceTask
- PipelineTemplate
- NodePackManifest
- NodeDefinition
- IntegrationEndpoint
- RuntimeProfile

## 推荐阅读路径

1. [docs/architecture/system-overview.md](system-overview.md)
2. [docs/architecture/project-structure.md](project-structure.md)
3. [docs/architecture/backend-service.md](backend-service.md)
4. [docs/architecture/detection-model-rules.md](detection-model-rules.md)
5. [docs/architecture/frontend-web-ui.md](frontend-web-ui.md)
6. [docs/architecture/data-and-files.md](data-and-files.md)
7. [docs/architecture/plugin-system.md](plugin-system.md)
8. [docs/architecture/runtime-packaging.md](runtime-packaging.md)
9. 根据任务继续进入 deployment 专题文档

## 后续建议拆分文档

- integration-rules.md：外部协议、回调和集成端点边界
- execution-observability.md：任务执行日志、指标、告警和审计模型