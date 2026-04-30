# 检测类模型的最小平台规则

## 文档目的

本文档用于定义检测类模型在 amvision 中共享的最小平台规则，明确第一阶段哪些对象现在就作为正式平台对象落地，哪些信息先保留在 metadata。

本文档只覆盖 detection 任务类型，不展开具体训练参数字段、运行时实现细节或某个单一模型仓库的脚本迁移方式。

## 命名约定

- 正式名称使用“检测类模型”
- 这里的“类”表示共享 detection 输入输出主干的一组模型类型，例如 YOLOX、YOLOv8/11 detection、RT-DETR
- 不使用 family 作为正式命名
- 不使用“工厂”表达业务对象边界；工厂只保留给代码层的实例创建扩展点，例如 trainer factory、converter factory、runtime factory
- “检测类模型”是架构分组概念，不新增一个 DetectionModelCategory 表或同级持久化对象

## 适用范围

- 训练输入边界
- 模型版本与 build 产物登记边界
- 转换和推理任务的最小共享对象
- YOLOX 作为第一个真实实现时应遵守的对象落位规则

## 最小共享规则

- task_type 固定为 detection
- 平台内部通用输入是 DatasetVersion，训练与转换执行输入是 DatasetExport
- detection 训练后端不直接消费原始 COCO、VOC、YOLO 目录，而是消费平台生成的 DatasetExport
- backend-service 负责任务、元数据和对象关系，不直接持有底层训练器、推理会话或脚本参数解析入口
- worker 负责训练、转换和推理执行，但输出必须回写为正式平台对象，而不是只落到本地输出目录
- 对外 API 和任务结果只暴露平台对象 id、object key 和结构化摘要，不暴露 projectsrc 路径、脚本入口或临时目录约定

## 现在就落地的正式对象

| 对象 | 现在就稳定的正式边界 | 说明 |
| --- | --- | --- |
| TaskRecord / TaskAttempt / TaskEvent / ResourceProfile | task_kind、task_spec、worker_pool、progress、result、event payload、attempt result | detection 训练、转换、推理都继续走统一任务系统，不为单个模型单独发明任务主表 |
| DatasetExport | dataset_export_id、dataset_id、project_id、dataset_version_id、format_id、task_type、task_id、manifest_object_key、split_names、sample_count、category_names | 这是 detection 训练执行时的正式输入资源边界 |
| Model | model_id、project_id、model_name、model_type、task_type、model_scale、labels_file_id | model_type 保存具体模型类型，例如 yolox、yolov8、rtdetr；“检测类模型”不是这个字段的取值 |
| ModelVersion | model_version_id、model_id、source_kind、training_task_id、parent_version_id、file_ids | 训练产物或预置预训练模型都应登记为 ModelVersion |
| ModelBuild | model_build_id、model_id、source_model_version_id、build_format、runtime_profile_id、conversion_task_id、file_ids | 转换产物统一登记为 ModelBuild，用于部署和推理绑定 |
| ModelFile | file_id、project_id、model_id、model_version_id、model_build_id、file_type、logical_name、storage_uri | checkpoint、onnx、openvino-ir、labels、metrics 等文件统一进入文件记录链路 |

## 先放 metadata 的内容

| 承载对象 | 先放 metadata 的内容 | 现在不升格为正式字段的原因 |
| --- | --- | --- |
| TaskRecord.task_spec 与 TaskRecord.metadata | exp 模板名、增强策略、优化器细节、学习率计划、batch size、resume checkpoint、蒸馏或 teacher 配置 | 这些字段随具体训练后端差异很大，当前还不足以形成跨 YOLOX、YOLOv8/11、RT-DETR 的稳定公共 schema |
| Model.metadata | supported_export_formats、supported_build_formats、默认输入尺寸、默认阈值、后端说明标签 | 当前更多用于展示、默认值回填和能力提示，不是第一阶段的核心查询条件 |
| ModelVersion.metadata | dataset_export_id、manifest_object_key、category_names 快照、input_size、训练配置摘要、关键指标摘要 | 当前正式对象里已经有 training_task_id 和 file_ids，可以形成可追溯链路；DatasetExport 关联字段等共性还需要经过至少两个 detection 后端验证后再决定是否升格 |
| ModelBuild.metadata | onnx opset、dynamic axes、precision、device hints、benchmark 摘要、exporter 版本 | 转换链路和运行时兼容矩阵还未稳定，现在先保留弹性 |
| ModelFile.metadata | checksum、artifact role、lineage 标签、生成命令摘要 | 这些信息需要保留，但暂时没有必要为了第一阶段引入更多正式列 |

## 第一阶段不单独新增的对象

- 不新增“检测类模型分类表”或“family 表”；检测类模型只作为架构概念存在
- 不新增单独的 detection runtime registry 主对象；先通过 ModelBuild、RuntimeProfile 和 metadata 组合表达
- 不把工厂对象当作领域对象持久化；trainer factory、converter factory、runtime factory 只属于代码装配层

## 推荐落地顺序

1. 继续以 DatasetExport 作为 detection 训练唯一输入边界，优先把 YOLOX 真实 training runner 接到现有任务系统和 ModelVersion / ModelFile 登记链路上。
2. 在不扩 schema 的前提下，把 dataset_export_id、manifest_object_key、训练配置摘要先写入 TaskRecord.task_spec 和 ModelVersion.metadata。
3. 等 RT-DETR 或 YOLOv8/11 detection 接入后，再检查哪些 metadata 字段已经成为稳定共性，再决定是否升格为正式对象字段或独立规则。

## 关联文档

- [project-structure.md](project-structure.md)
- [data-and-files.md](data-and-files.md)
- [dataset-export-formats.md](dataset-export-formats.md)
- [yolox-module-design.md](yolox-module-design.md)