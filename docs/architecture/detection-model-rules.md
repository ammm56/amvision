# Detection 模型平台规则

## 边界

Detection 是任务类型，不是独立持久化的模型 family。YOLOX、YOLOv8、YOLO11、YOLO26 与 RF-DETR detection 使用同一组平台资源与任务边界，模型差异保留在对应 Core、TrainingBackend、ConversionBackend 和 ModelRuntime adapter 中。

## 稳定资源

| 资源 | 职责 |
| --- | --- |
| DatasetVersion | 平台统一数据版本 |
| DatasetExport | 训练与评估使用的不可变格式化输入 |
| TaskRecord / TaskEvent | 导入、导出、训练、评估、转换和异步推理状态 |
| Model | 项目或平台模型身份；保存 `model_type`、`task_type`、scale 等规格 |
| ModelVersion | 预训练或训练输出版本、父版本和文件集合 |
| ModelBuild | ONNX、OpenVINO、TensorRT 等转换产物与 RuntimeProfile |
| ModelFile | checkpoint、labels、metrics、IR、engine 等文件登记 |
| DeploymentInstance | 指向 ModelBuild 的长期推理服务配置 |

不新增 DetectionCategory、ModelFamily 或单模型任务主表。训练、转换与部署必须继续复用平台通用资源。

## 执行规则

- 训练与独立评估消费 DatasetExport，不直接读取上传 zip、`projectsrc` 或页面临时目录。
- backend-service 创建资源、校验引用和提交任务；模型计算由严格 Worker Profile 执行。
- 训练产物必须登记为 ModelVersion 与 ModelFile，不能只保存在任务输出目录。
- 转换产物必须登记为 ModelBuild 与 ModelFile，DeploymentInstance 只绑定已登记 build。
- 推理会话由 Inference Daemon 管理；workflow 节点通过公开 Deployment 服务调用，不直接 import predictor。
- sync 与 async 推理返回统一平台结果，模型私有 tensor 和进程句柄不进入公开 API。
- unsupported model/task 组合必须明确拒绝，不能回退到另一模型或伪装成功。

## 可扩展元数据

训练增强、优化器细节、opset、dynamic axis、后端特有 profile、benchmark 和 exporter 版本保留在任务或产物 metadata。只有跨多个模型实现稳定、需要查询或形成公开不变量的字段才升格为正式列。

## 依赖方向

```text
API / Workflow Node
        ↓
Application Service
        ↓
ModelBackend / Runtime adapter
        ↓
project-native model core
```

`projectsrc/` 只用于开发期参考核对，不能进入运行时 import、响应字段或文件定位逻辑。

## 相关文档

- [模型支持矩阵](model-support-matrix.md)
- [模型 Core 架构](model-core-architecture.md)
- [模型工作流边界](model-workflow-boundaries.md)
- [训练与评估契约](model-training-evaluation-contract.md)
- [部署运行时配置](model-deployment-runtime-policy.md)
