# 模型产物来源元数据

## 目标

训练和转换产生的新模型产物统一写入来源元数据，用于内部审计、产物来源判断和争议发生时的辅助材料。

这些字段不参与训练、转换、部署或推理计算。运行时代码不得依赖这些字段决定模型输入、输出、精度或执行设备。

## 统一结构

平台使用 `model_artifact_provenance` 作为数据库和任务摘要中的固定字段名，当前 schema 为 `amvision.model-artifact-provenance/v1`。

```json
{
  "schema": "amvision.model-artifact-provenance/v1",
  "producer": "amvision",
  "trademark": "amvar",
  "product_line": "vision",
  "product_name": "amvision",
  "source_names": ["amvar", "amvar vision", "amvision"],
  "origin_marker": "amvision | amvar vision | amvar",
  "copyright_notice": "Copyright (c) amvar. All rights reserved.",
  "artifact_kind": "converted-model",
  "trace": {
    "conversion_task_id": "task-...",
    "source_model_version_id": "model-version-...",
    "model_build_id": "model-build-...",
    "build_format": "openvino-ir"
  }
}
```

其中 `amvar` 是商标，`vision` 是视觉产品线，`amvision` 是视觉产品名称。平台生成固定字段，调用方传入的同名 `model_artifact_provenance` 不得覆盖平台值。`trace` 只保存已有的内部标识，不生成时间、所有人或商标注册状态等无法由产物链路验证的声明。

## 写入位置

新生成的训练产物写入：

- `ModelVersion.metadata`
- 该版本关联的 checkpoint、labels、metrics 等 `ModelFile.metadata`
- 首次创建对应 `Model` 时的 `Model.metadata`

新生成的转换产物写入：

- 转换结果与 report 中每个 build 的 `metadata`
- `ModelBuild.metadata`
- build 对应的 `ModelFile.metadata`

支持安全内嵌元数据的文件格式还写入模型文件：

- ONNX：写入 `metadata_props`。`amvision.provenance` 保存完整 JSON，同时写入 producer、trademark、product line、product name、source names 和 copyright 的可检索字段。
- OpenVINO IR：写入 `rt_info/amvision/model_artifact_provenance`，不改变计算图的输入输出。
- TensorRT engine：Python builder 设置 network 来源标识，同时在 build metadata 中保存完整结构。经 `trtexec` 生成的 engine 没有稳定的任意用户元数据容器，因此以带来源元数据的 ONNX 输入、转换报告、`ModelBuild` 和 `ModelFile` 记录组成追踪链。

训练 checkpoint 的内部结构由模型框架和训练器定义。平台不在训练完成后反序列化并重写 `.pt`、`.pth` 等文件，避免改变第三方 checkpoint schema 或破坏后续恢复训练；来源信息保存在该 checkpoint 对应的 `ModelVersion` 和 `ModelFile` 元数据中。

## 生命周期边界

- 只对新创建的训练版本和转换 build 生效，不自动修改历史模型或历史数据库记录。
- 删除模型文件或手工改写文件可能移除普通文本元数据，因此这些字段是来源标识和审计线索，不是不可篡改签名。
- 更强的证据链应在后续增加产物 SHA-256、签名 manifest、可信时间戳和受控私钥，并与源码版本、任务事件、对象存储审计记录一起保存。
- copyright 和商标权属声明必须与实际权属、注册材料和合同保持一致；代码中的固定字符串不能替代权属文件或法律意见。

## 兼容性

来源元数据不进入 runtime 配置，也不改变公开推理 schema。ONNX 和 OpenVINO 的写入发生在产物生成完成后、登记之前；TensorRT 的完整来源结构保存在平台记录中。旧模型缺少该字段时仍可部署和推理。
