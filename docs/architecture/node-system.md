# 节点系统说明

## 文档目的

本文档用于说明平台节点系统的位置、边界、类型、生命周期，以及它和节点编辑器的关系。

本文档主要回答两个问题：哪些能力保留在核心平台，哪些能力通过 node pack 扩展；custom nodes 如何向 ComfyUI 的扩展体验靠拢，同时保持工业现场需要的版本、权限、超时、禁用和回滚约束。

## 设计目标

- 让核心平台保持稳定、可部署、可回滚，不把场景化需求持续堆入 core
- 让流程编排和节点编辑能够把核心节点与 custom nodes 统一纳入同一张执行图
- 让协议集成、结果处理、模块连接和硬件桥接优先通过 node pack 扩展
- 让现场定制能力通过受控 manifest、目录和 entrypoint 接入，而不是直接侵入 backend/service
- 在节点扩展自由度和工业现场可控性之间保持平衡

## 核心原则

- 核心平台处理公开接口规则、任务编排、版本管理和节点扩展生命周期管理
- 场景化能力优先通过 node pack 扩展，而不是直接扩散到核心模块
- 核心平台默认不内置相机、PLC、传感器、机械臂等硬件直连驱动
- 如确有现场直连需求，应通过受控 node pack 在独立边界中实现，并接受 manifest、权限、超时、禁用和回滚约束
- core nodes、custom nodes 和流程模板在节点编辑器中应作为统一的一等公民展示和编排
- 节点注册机制向 ComfyUI custom nodes 的灵活性看齐，但不能牺牲工业场景的稳定性和可追溯性

## 节点系统在整体架构中的位置

- backend-service：发现 node pack、读取 manifest、管理启停状态、构建统一 NodeCatalogRegistry
- workers：在运行时环境中执行 custom node 逻辑，处理节点输入输出规则
- frontend/web-ui：读取统一节点目录、参数 schema 和分类信息，在节点编辑器与配置面板里渲染节点能力
- contracts：放 node pack manifest、节点定义、payload contract 和输入输出 schema 的共用格式
- runtimes：放节点运行环境和依赖隔离边界
- packaging：处理默认 custom_nodes、可选 node pack 资产和发布装配

## node pack 类型

### 流程节点包

- 提供模型节点、传统视觉节点、控制节点、条件节点和工具节点
- 参与统一流程编排和节点执行图
- 通过输入输出 schema 和参数 schema 接入执行器与节点编辑器

### 集成节点包

- 提供与上位机、采集系统、MES、PLC 网关、设备代理系统等外部系统的协议交互能力
- 处理请求接入、状态订阅、结果回传和联动触发
- 可声明定制输入输出端点、回调格式和结果映射规则

### 结果处理节点包

- 提供检测结果过滤、规则判定、尺寸测量、缺陷归并和结果转换能力
- 与模型推理结果、传统视觉结果和外部结果处理链路组合使用
- 可在流程执行链中承担标准节点角色，而不是旁路脚本

### 现场桥接节点包

- 作为独立可选扩展实现相机、PLC、传感器、机械臂等硬件直连能力
- 不属于核心平台默认能力，必须在节点扩展边界内独立实现和管理
- 与核心平台只通过受控接口规则交互，不把硬件 SDK 和驱动逻辑渗透进 core

### Trigger Source Bridge / Listener 节点包

- 作为独立可选扩展实现 PLC 条件监听、MQTT 订阅、ZeroMQ 本地主题监听、gRPC 入口桥接、IO 变化监听和传感器阈值触发
- 这类 node pack 的职责是把外部事件转换成 WorkflowRun 创建请求，而不是把业务图执行逻辑搬进监听器本身
- trigger source 默认只创建 WorkflowRun，不直接执行图；图执行仍由 runtime instance 负责
- listener 或 bridge 可以长期运行，但应停留在受控边界中，不把协议循环、驱动状态机和厂商 SDK 直接写进 backend-service 主链路
- 当外部事件到达后，bridge 应优先创建 WorkflowRun 并交给 runtime instance 执行，而不是让 workflow 首节点长期空转轮询外部世界
- 这类扩展应声明独立 capability、timeout、外部依赖、去抖策略、幂等键来源和启停方式，保证现场长期运行时的可控性和可审计性

## node pack 目录结构建议

```text
custom_nodes/
└─ <node-pack-name>/
   ├─ manifest.json
   ├─ backend/
   │  └─ entry.py
   ├─ workflow/
   │  └─ catalog.json
   ├─ schemas/
   │  ├─ config/
   │  ├─ inputs/
   │  ├─ outputs/
   │  └─ ui/
   ├─ assets/
   └─ docs/
```

## manifest 最低要求

- node_pack_id
- version
- category 和 capabilities
- entrypoints
- custom_node_catalog_path
- timeout
- permission scope
- compatibility range
- enabled_by_default

## 生命周期

### 1. 发现

- backend-service 在 custom_nodes 根目录中发现可用 node pack
- 使用 NodePackManifest 校验 manifest 完整性、版本兼容性和依赖边界

### 2. 注册

- 使用 LocalNodePackLoader 读取 manifest 与 workflow/catalog.json
- 通过 NodeCatalogRegistry 合并 core nodes 与 custom nodes
- 为前端节点编辑器和执行器生成统一节点目录

### 3. 启用

- 允许按 node pack、按版本、按节点类别启用
- 启用前进行权限校验、依赖检查和运行时兼容性校验

### 4. 执行

- workers 按节点输入输出规则、超时和权限边界执行 custom node 逻辑
- 结果和错误统一回到后端服务状态流中
- 节点扩展能力可在受控接口内连接内部模块、外部端点和相关数据对象

### 5. 升级

- 升级以 node pack 版本为单位进行，不覆盖历史版本记录
- 节点 schema 或行为变化需要显式版本化并提供迁移说明

### 6. 禁用与回滚

- node pack 可被按版本禁用或快速回滚
- 回滚后需要恢复节点目录、流程模板兼容性和运行时引用关系

## 节点编辑器对齐 ComfyUI 的方向

- 节点编辑器需要统一展示 core nodes 与 custom nodes
- custom nodes 应支持分类、搜索、图标、说明、参数 schema 和输入输出端口声明
- 流程模板应像 ComfyUI workflow 一样能保存节点图结构、参数状态和版本引用
- custom node 的注册、卸载和升级不应要求修改核心前端代码结构
- 与 ComfyUI 对齐的是“节点扩展模型”，不是照搬其无约束运行方式

## 与核心模块的关系

### backend-service

- 管理 node pack 注册、版本、启用状态和节点目录发布
- 记录 node pack 与流程模板、部署实例、任务类型之间的引用关系
- 暴露模板校验、保存、读取与后续执行所需的统一节点目录

### workers

- 提供节点执行容器、错误收敛和超时控制
- 确保 custom node 输入输出严格遵循 payload contract 与端口规则
- 负责在任务执行过程中调用对应节点逻辑

### frontend/web-ui

- 读取统一节点目录并渲染节点面板、参数表单和流程图
- 为节点包配置、状态和错误提供受控展示界面

### contracts

- 定义 NodePackManifest、NodeDefinition、WorkflowPayloadContract 和 FlowApplication 等共用格式
- 避免不同 node pack 自行发明一套不兼容协议

## 安全和管理要求

- node pack 必须声明 capability scope，避免无限制调用平台能力
- 硬件桥接节点包和协议节点包必须声明额外权限和外部依赖
- node pack 必须支持 timeout、disable 和版本回滚
- 节点扩展错误不能直接拖垮后端服务主链路，应通过任务和状态流隔离处理
- 节点日志、错误和版本必须可审计

## 哪些能力优先放进 node pack

- 行业特定协议节点
- 客户定制结果处理逻辑
- 外部触发入口和完成后的数据上报逻辑
- trigger source bridge、listener 和协议到 WorkflowRun 的映射逻辑
- 硬件直连与厂商 SDK 封装
- 特定视觉后处理逻辑
- 模块之间的特殊衔接规则
- 自定义节点、节点组和参数面板

## 哪些能力应留在核心平台

- 任务模型和状态流
- 数据集、模型、部署、流程模板的核心对象模型
- 节点扩展生命周期管理和版本管理
- 节点执行基础框架和流程模板基础格式
- 统一 API、WebSocket 和审计能力

## 推荐后续文档

- [docs/architecture/workflow-json-contracts.md](workflow-json-contracts.md)
- [docs/architecture/system-overview.md](system-overview.md)
- [docs/architecture/project-structure.md](project-structure.md)