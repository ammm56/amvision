# 模型接入与工作流边界

## 文档目的

本文档用于把后续模型接入与本项目现有功能之间的边界再次收口，重点避免后续在实现训练、转换、推理、workflow 节点和触发源时把资源边界、执行边界和调用边界写乱。

本文档重点回答下面几个问题：

- 数据集导入、导出、训练、验证、评估、转换、推理、发布之间各自负责什么
- 长期稳定运行的独立推理服务与 workflow runtime 的关系是什么
- workflow 节点、图编辑、FlowApplication、WorkflowAppRuntime、WorkflowRun 和 TriggerSource 各自负责什么
- `projectsrc` 参考仓库中的优秀实现，后续应吸收到本项目哪一层

## 适用范围

- 后续所有模型分类的正式接入
- 数据集、模型、部署和 workflow 的对象边界
- backend-service、worker、deployment runtime、workflow runtime、node pack、TriggerSource 和 SDK 的调用边界
- `projectsrc` 参考代码向 amvision 正式实现迁移时的分层规则

## 核心结论

- 数据集、模型、部署和 workflow 是四条并列的正式资源链，不应混成一条大链。
- 训练、验证、评估、转换属于后台任务执行面，推理发布属于长期运行服务执行面，workflow 属于编排执行面，三者不能互相替代。
- TriggerSource 只负责创建 workflow 调用，不负责直接调用模型运行时，也不负责替 workflow 图做业务转换。
- `projectsrc` 与本项目没有任何运行时依赖关系，只能作为参考实现来源。

## 四条正式资源链

后续实现应长期保持下面四条正式资源链：

```text
Project
  -> Dataset
     -> DatasetImport
     -> DatasetVersion
     -> DatasetExport

Project
  -> Model
     -> ModelVersion
     -> ModelBuild

Project
  -> DeploymentInstance
     -> sync infer / async inference task
     -> 长期稳定运行的独立推理服务

Project
  -> WorkflowGraphTemplate
     -> FlowApplication
     -> WorkflowAppRuntime
     -> WorkflowRun
     <- TriggerSource / SDK / HTTP invoke
```

这四条链之间允许引用，但不允许越层代替。

最常见的正确引用关系是：

- TrainingTask 读取 `DatasetExport`，产出 `ModelVersion`
- EvaluationTask 读取 `DatasetExport` 和 `ModelVersion`
- ConversionTask 读取 `ModelVersion`，产出 `ModelBuild`
- DeploymentInstance 绑定 `ModelBuild` 或可部署的 `ModelVersion`
- Workflow 节点通过正式 service 或 PublishedInferenceGateway 调用上面这些资源
- TriggerSource 只创建 `WorkflowRun` 或 runtime invoke 请求

## 跨链执行关系

后续实现建议长期保持下面这条主关系：

```text
DatasetImport
  -> DatasetVersion
  -> DatasetExport
  -> TrainingTask
  -> ModelVersion
  -> ValidationSession / EvaluationTask
  -> ConversionTask
  -> ModelBuild
  -> DeploymentInstance
  -> 长期稳定运行的独立推理服务
  -> sync infer / async inference task

WorkflowGraphTemplate
  -> FlowApplication
  -> WorkflowAppRuntime
  -> WorkflowRun
  -> service node / custom node
  -> PublishedInferenceGateway
  -> 已发布 DeploymentInstance

TriggerSource / SDK / 外部协议
  -> WorkflowAppRuntime
  -> WorkflowRun
```

这里要特别注意两点：

- workflow 可以编排训练、评估、转换和已发布推理服务，但 workflow 本身不拥有这些资源的生命周期
- TriggerSource 可以触发 workflow，但 TriggerSource 本身不等于模型服务，也不等于 workflow 图

## 统一任务系统与长期运行服务的区别

TaskRecord 是统一后台任务记录，不是长期运行模型服务。

后续实现必须分清下面两类执行面：

### 后台任务执行面

适用对象：

- DatasetImport
- DatasetExport
- TrainingTask
- EvaluationTask
- ConversionTask
- batch inference task

特点：

- 有开始和结束
- 以 TaskRecord、TaskAttempt、TaskEvent 表达状态
- 默认进程隔离
- 执行完成后退出

### 长期运行服务执行面

适用对象：

- DeploymentInstance 对应的独立推理服务
- WorkflowAppRuntime 对应的 workflow app instance

特点：

- 有启动、停止、重启、健康状态和保活
- 需要固定快照和长期进程
- 需要 warmup、health、restart、keep_warm 一类能力
- 不适合用一次性 TaskRecord 表达整个生命周期

这两类执行面不能互换。

## 容易混淆的几个概念

### 数据集导入和数据集导出

- `DatasetImport` 负责把外部 zip 或外部目录整理成平台正式 `DatasetVersion`
- `DatasetExport` 负责把 `DatasetVersion` 按目标格式导出给训练、验证或评估使用
- 导入面向外部不稳定格式，导出面向内部已经固定的数据版本

### 验证、评估和推理

- validation session：训练后单图人工验证，重点是快速看结果，不是正式在线服务
- evaluation task：基于 `DatasetExport` 的数据集级评估，重点是回归指标和报告
- infer / inference task：基于 `DeploymentInstance` 的正式推理调用，重点是发布后的线上或现场服务能力

### 模型发布和 workflow app

- `DeploymentInstance` 发布的是模型推理服务
- `WorkflowAppRuntime` 发布的是一整条 workflow 应用
- workflow app 可以调用已发布模型服务，但两者不是同一类 runtime

### 节点图和节点实现

- 图编辑器负责保存模板、连线、参数和输入输出绑定
- NodeDefinition 负责定义节点 contract
- 节点实现负责执行逻辑
- 模型训练器、转换器、运行时加载器不应直接藏在图编辑器层

### TriggerSource 和 workflow 首节点

- TriggerSource 负责把外部事件变成 WorkflowRun
- workflow 首节点负责处理一条已经开始执行的 run 的输入
- 长期监听外部世界的职责不应塞进 workflow 首节点

## 正式资源边界表

| 资源或能力 | 正式输入边界 | 正式输出边界 | 负责内容 | 不负责内容 |
| --- | --- | --- | --- | --- |
| DatasetImport | 外部 zip、外部标注格式声明 | DatasetVersion | 接收、解压、识别、校验、统一化 | 训练、评估、推理 |
| DatasetVersion | 已导入并固定的数据版本 | 供导出和复用 | 平台正式数据版本 | 直接给训练器读原始外部目录 |
| DatasetExport | DatasetVersion + format id | 训练或评估输入目录和 manifest | 面向目标模型或后端的导出格式 | 代替 DatasetVersion 成为正式主版本 |
| TrainingTask | DatasetExport + model profile | ModelVersion | 训练并登记输出文件 | 长期在线推理服务 |
| ValidationSession | ModelVersion + 单图输入 | 单图结果和预览 | 训练后人工快速验证 | 发布态推理服务 |
| EvaluationTask | DatasetExport + ModelVersion | report、metrics、结果包 | 数据集级回归评估 | 长期在线服务 |
| ConversionTask | ModelVersion | ModelBuild | 导出、优化和运行时转换 | 直接提供线上调用 |
| ModelBuild | ModelVersion + build format | 部署候选 build | 面向运行时后端的正式产物 | 调度长期进程 |
| DeploymentInstance | ModelBuild 或可部署 ModelVersion | 已发布推理服务 | 管理长期稳定运行的独立推理服务 | 训练、评估、workflow 图保存 |
| sync infer / async inference task | DeploymentInstance + 推理输入 | 结构化推理结果 | 使用已发布服务做正式推理 | 直接管理模型文件 |
| WorkflowGraphTemplate | NodeDefinition 引用、节点参数、图结构 | 模板 | 保存图结构和逻辑输入输出 | 运行长期实例 |
| FlowApplication | Template 引用 + bindings | 应用定义 | 把模板绑定到入口和输出 | 持有模型运行时会话 |
| WorkflowAppRuntime | 固定 snapshot 的 FlowApplication | 长期 workflow 运行单元 | 管理已发布 workflow 应用实例 | 代替 DeploymentInstance 发布模型 |
| WorkflowRun | WorkflowAppRuntime + 调用输入 | 运行结果 | 记录一次 workflow 正式调用 | 直接变成 TaskRecord |
| TriggerSource | 协议原生输入 + runtime 绑定 | WorkflowRun 创建请求 | 把外部事件映射到 workflow 调用 | 直接调用模型 session |

## 数据集边界

### 数据集导入

数据集导入层应长期坚持下面这些规则：

- 只接外部数据包、外部格式和导入声明
- 只生成 `DatasetVersion`
- 不直接进入训练器、转换器或部署服务
- 不把某个模型原始目录结构提升为平台内部正式格式

后续从 `projectsrc` 参考仓库吸收数据集相关能力时，只能落到：

- `application/datasets/imports`
- `application/datasets/exports`
- `contracts/datasets/imports`
- `contracts/datasets/exports`

不能直接落到：

- `backend/service/api`
- workflow 节点图保存格式
- deployment runtime

### 数据集导出

数据集导出层应长期坚持下面这些规则：

- `DatasetExport` 是训练、验证和评估的正式执行输入边界
- 训练器和评估器不应直接读取 `DatasetVersion` 的内部目录细节
- 不同模型分类共享的是 `DatasetExport` contract，不是同一个原始目录写法

## 模型执行边界

### 训练

训练层只负责：

- 读取 `DatasetExport`
- 读取模型 profile、训练参数和资源配置
- 执行训练
- 把输出登记为 `ModelVersion` 和 `ModelFile`

训练层不负责：

- 接收外部数据集 zip
- 管理长期在线推理服务
- 保存 workflow 图
- 直接响应 TriggerSource

### 验证

validation session 只负责：

- 对 `ModelVersion` 做训练后单图人工检查
- 提供 raw-result 和 preview

validation session 不负责：

- 长期在线推理服务
- 数据集级指标回归
- workflow app 的正式生产调用

### 评估

evaluation task 只负责：

- 基于 `DatasetExport` 和 `ModelVersion` 做数据集级回归评估
- 产出 metrics、report、result package

evaluation task 不负责：

- 发布模型
- 维护长期运行进程
- 代替正式 infer 接口

### 转换

转换层只负责：

- 把 `ModelVersion` 转成 `ModelBuild`
- 处理 ONNX、OpenVINO、TensorRT 等目标格式
- 记录导出参数、摘要和文件

转换层不负责：

- 直接对外提供线上推理调用
- 保存 workflow 模板
- 接入外部协议

## 发布与长期稳定独立推理服务边界

### DeploymentInstance 的职责

DeploymentInstance 是模型发布后的正式运行单元。

模型发布的实例数量、故障隔离、OpenVINO CPU / GPU / NPU 设备参数、TensorRT engine / execution context / CUDA stream 边界和硬件迁移规则，统一见 [模型发布运行时配置](model-deployment-runtime-policy.md)。本文件只固定资源和调用边界，不重复维护后端参数清单。

它负责：

- 绑定 `ModelBuild` 或可部署 `ModelVersion`
- 固定 runtime backend、device、precision 和 deployment metadata
- 管理长期稳定运行的独立推理服务
- 提供 start、stop、warmup、health、reset、restart、keep_warm

它不负责：

- 训练
- 评估
- 数据集管理
- workflow 模板保存

`instance_count` 只表示平台期望的推理运行单元数量，不同时表示 OpenVINO stream、CPU 推理线程、TensorRT execution context、CUDA stream 或独立进程。workflow 只调用已发布服务，不负责拆分或推导这些运行资源参数。

### 推理调用的两条路径

后续实现应固定区分下面两条推理路径：

1. 公开推理调用

- `sync infer`
- `async inference task`

这条路径面向调试、外部系统调用和正式接口消费。

2. workflow 内部推理调用

- PreviewRun、WorkflowAppRuntime、WorkflowRun 中的模型推理节点
- 通过 PublishedInferenceGateway 命中已发布 DeploymentInstance

这条路径面向 workflow 内部编排，不等于公开 inference task 接口。

两条路径都应指向正式 `DeploymentInstance`，而不是让 workflow 自己再拉一套模型 session。

## workflow 边界

### WorkflowGraphTemplate

模板只负责：

- 节点图结构
- 节点参数
- 模板输入输出
- 编辑器 UI 状态

模板不负责：

- 长期运行实例
- 模型文件登记
- 训练结果持久化
- 直接对接外部协议监听

### FlowApplication

应用只负责：

- 选择模板
- 绑定输入输出
- 声明运行模式

应用不负责：

- 持有模型会话
- 直接管理 DeploymentInstance
- 替代 TriggerSource

### WorkflowAppRuntime

已发布 workflow app runtime 只负责：

- 固定 application/template snapshot
- 管理长期运行的 workflow instance
- 承接 invoke 和 runs

它不负责：

- 训练、转换和部署的资源生命周期
- 代替模型推理发布服务

### WorkflowRun

WorkflowRun 只负责：

- 记录一次正式 workflow 调用
- 持有输入、输出、trace、side effect summary

它不负责：

- 成为训练任务主记录
- 直接管理外部监听器生命周期

## 节点系统边界

### core service nodes

core service nodes 后续应继续作为“对正式服务的参数化调用”存在。

它们可以：

- 创建训练任务
- 创建评估任务
- 创建转换任务
- 创建或调用 DeploymentInstance
- 调用已发布推理服务

它们不应：

- 在节点内部长期持有模型会话
- 自己发明一套模型文件生命周期
- 绕过正式 service 直接访问数据库或 object store

### custom nodes

custom nodes 更适合承接：

- 行业前处理和后处理
- OpenCV 视觉逻辑
- 协议桥接
- 硬件桥接
- 特定结果整理
- workflow 图内的显式 payload 转换

custom nodes 不应承担：

- 平台核心模型生命周期管理
- 公开模型资源 schema 定义
- 代替 DeploymentInstance 提供长期模型服务

### 图编辑器

图编辑器只负责：

- 读取 NodeCatalog
- 编辑和保存 `WorkflowGraphTemplate`
- 编辑和保存 `FlowApplication`
- 发起 preview run 或 runtime invoke

图编辑器不应：

- 直接加载 Python 模型实现
- 直接读取 `custom_nodes` 文件夹
- 直接感知模型文件路径

## TriggerSource 与 SDK 边界

TriggerSource 和 SDK 只负责协议入口。

它们可以：

- 创建 runtime invoke 请求
- 创建 WorkflowRun
- 传递图片 bytes、image-ref、业务 metadata 和协议字段

它们不应：

- 直接调用模型 runtime session
- 直接拉起 DeploymentInstance 子进程
- 直接替 workflow 图做复杂业务转换
- 直接补图像抓帧、相机取图或业务回写逻辑

后续如果同一个 app 同时需要：

- HTTP `image-base64`
- ZeroMQ `image-ref`
- 其他协议输入

应通过 FlowApplication bindings 和图中的显式转换节点解决，而不是把转换逻辑塞进 TriggerSource 或 SDK。

## projectsrc 参考代码吸收边界

`projectsrc` 中的优秀实现后续应按下面方式吸收：

| 参考实现类型 | 适合吸收到本项目的位置 | 不应直接落到的位置 |
| --- | --- | --- |
| 模型结构、loss、后处理 | training runner、runtime loader、model runtime 内部适配层 | API schema、workflow JSON、TriggerSource |
| 数据集格式解析和导出 | dataset imports / exports、contracts | deployment runtime、workflow app runtime |
| exporter、backend session、runtime target | conversions、runtime target resolver、deployment runtime loader | 前端图编辑器、custom node catalog |
| 示例推理脚本、demo 服务 | docs 示例、workflow 示例、独立测试夹具 | backend-service 主链路 |
| 可视化工具、预览逻辑 | validation session、result viewer helper、custom nodes | 通用模型资源对象 |
| 协议桥接、外部调用示例 | sdks、TriggerSource adapter、node pack | 模型训练主链路 |

## 后续模型接入的固定顺序

每增加一个新的模型分类，建议长期遵守下面这个顺序：

1. 先确认任务分类和结果 contract。
2. 再确认 `DatasetExport` 默认格式和备选格式。
3. 再定义 model spec、model profile、file type 和 build format。
4. 再实现训练 backend 或明确当前阶段不做训练。
5. 再实现 validation session 和 evaluation task 的边界。
6. 再实现 conversion backend。
7. 再实现 `DeploymentInstance` 对应的长期稳定独立推理服务。
8. 再公开 sync / async infer 接口。
9. 再把能力挂到 workflow core service nodes 或已发布推理节点。
10. 最后再补前端工作台页面和 workflow app 侧的结果展示。

这个顺序的目的不是增加流程，而是强制把边界定在正式资源和正式服务上，避免一开始就把 demo 脚本、workflow 节点和模型内部逻辑混写。

## 防止层次混乱的硬规则

- 训练任务不得直接读取原始导入 zip 或 `projectsrc` 目录结构。
- 评估任务不得以 DeploymentInstance 代替 ModelVersion 或 DatasetExport。
- DeploymentInstance 不得直接读取 DatasetVersion 或 DatasetExport。
- workflow runtime 不得长期持有 deployment supervisor 之外的私有模型会话。
- TriggerSource 不得直接调用模型推理实现。
- custom node 不得替代核心模型资源管理对象。
- 图编辑器不得保存模型内部运行态。
- `projectsrc` 不得成为本项目运行时代码的 import 来源。

## 当前阶段结论

后续模型接入最需要先守住的，不是单个模型功能，而是四条链和三类执行面的分工：

- 数据集链负责把外部数据稳定变成平台输入
- 模型链负责把训练、评估、转换稳定变成平台模型产物
- 部署链负责长期稳定独立推理服务
- workflow 链负责图编排、应用发布和正式业务调用

只要这条边界持续保持清楚，后续无论继续接 `YOLOv8`、`YOLO11`、`YOLO26`、`RT-DETR`、`SAM2/3` 还是 `QwenVL`，代码层次、对象关系和模块职责都更容易保持稳定。

## 关联文档

- [model-platform-plan.md](model-platform-plan.md)
- [model-core-implementation-plan.md](model-core-implementation-plan.md)
- [workflow-runtime.md](workflow-runtime.md)
- [workflow-json-contracts.md](workflow-json-contracts.md)
- [node-system.md](node-system.md)
- [dataset-import-spec.md](dataset-import-spec.md)
- [dataset-export-formats.md](dataset-export-formats.md)
- [task-system.md](task-system.md)
