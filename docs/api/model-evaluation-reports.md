# 模型评估报告与样本

目标检测的 `GET /api/v1/models/detection/evaluation-tasks` 支持 `offset`（默认 0）和 `limit`（默认 100，最多 500）。先应用筛选，再按创建时间和任务 ID 倒序分页。列表和详情中的 `split_name` 优先使用已解析的划分，任务未开始时使用提交时指定的划分。

目标检测的 `POST /api/v1/models/detection/evaluation-tasks/preview` 检查指定的 `val` 或 `test`，返回模型运行后端、精度、设备、输入尺寸和类别顺序。对于 COCO 导出，`sample_count` 和 `annotation_count` 分别来自该划分标注文件中的图像和标注对象数组。其他格式的 `annotation_count` 为 `null`。预检不创建任务，也不逐图解码。

目标检测的 `GET /api/v1/models/detection/evaluation-tasks/{task_id}/report` 可附带 `payload.curves`。`precision_recall` 按 0.00–1.00 的 101 个召回率点记录 IoU 0.50 的插值精确率。`f1_confidence` 与 `confidence` 按下标对应，包含实际置信度工作点。mAP 和完整 PR 曲线使用从 `score_floor` 开始保留的候选，候选数量仍受推理运行时上限约束。Precision、Recall 和样本诊断使用置信度工作点。

新生成的报告通过 `payload.execution` 保存评估使用的模型名称、运行后端、精度、输入宽高及可用的模型输入契约。`device_name` 和 `runtime_artifact_file_id` 记录执行配置中的设备及权重文件标识。`batch_size` 当前为 1，对应逐图调用推理会话。`payload.nms_threshold` 为 `null` 时表示本次执行未使用 NMS。历史报告可能缺少执行字段。

目标检测的 `/samples` 支持 `q`（文件名包含匹配，不区分大小写）、`class_name`（完整类别名）及 `issue=all|errors|false_negatives|false_positives`。类别与错误类型同时设置时，只匹配该类别下的指定错误。`total` 是组合筛选后的总数；`diagnostics_available=false` 表示报告没有保存样本级诊断，不表示没有错误。

使用 `issue=localization` 可查找同时有同类别未匹配标注框和预测框、且两框满足 `0 < IoU < 0.50` 的样本。响应项的 `localization_pair` 给出 IoU 最大的匹配候选和两个原始框的索引。该诊断读取已有样本快照，原漏检、误检和 mAP 统计保持原值。

混淆矩阵以工作点通过阈值的检测框计算，按置信度排序，在同一张图内以 IoU 0.50 匹配标注框。匹配允许跨类别，用于记录错分。背景使用 `null`，分别表示未找到标注的预测和未找到预测的标注。历史报告可继续读取，生成曲线需要重新评估。

目标检测任务详情的 `progress` 可包含 `split_name`、`runtime_backend`、`runtime_precision`、`coverage` 和 `recent_samples`。覆盖量字段 `requested`、`succeeded`、`failed`、`unprocessed` 以样本为单位。最近记录最多保留三条，含零基 `image_index`、文件名 `name`、`classes`、`status` 和 `processed_at`。加载数据后保存初始覆盖量，首个样本和阶段切换立即保存，样本循环中的常规更新按秒限频。需要事件时查询 `include_events=true`。

已取消的任务保留最后一次进度快照。取消可能发生在首个进度快照之前，旧任务也可能缺少样本记录。取消任务的报告和结果包接口返回 404。

分类、实例分割、姿态估计和旋转框检测沿用各自的任务和 Worker，新增以下只读 API。`{kind}` 分别为 `classification`、`segmentation`、`pose` 和 `obb`。

| 路径（相对于 `/api/v1/models/{kind}/evaluation-tasks/{task_id}`） | 响应 |
| --- | --- |
| `/report` | `file_status` 和 Worker 保存的报告。分类报告根据保存的预测补充混淆矩阵。 |
| `/samples?offset=0&limit=2` | 样本分页。分类可使用 `errors_only=true` 查看实际错分。 |
| `/samples/{index}/image` | 任务所用数据集导出中对应的原图。 |
| `/samples/{index}/mask-overlay?layer=combined` | 实例分割的透明 PNG 图层，支持 `combined` 和 `difference`。差异展示合并实例的前景差异。 |

样本和图层依赖任务保存的文件。历史报告可以缺少几何或图层，数据集导出清理后原图也可能不可用。

姿态和旋转框通过 `/samples?issue=errors` 查看错误样本，也可使用 `missed` 和 `extra`。姿态可使用 `keypoints`，旋转框可使用 `angle` 和 `localization`。两类都先按置信度匹配同类标注，合格匹配阈值为 OKS 或 rotated IoU 0.50。剩余同类框按重叠诊断偏差，旋转框仅对齐角度后能达到阈值的记为角度偏差。响应提供按样本统计的 `issue_counts`。

## 语义分割与异常检测

独立评估接受已生成的模型输出。将独立验证或测试集的原图、真值、预测和 `manifest.json` 打包。向 `POST /api/v1/models/{kind}/evaluation-tasks` 提交 multipart 表单，`kind` 为 `semantic` 或 `anomaly`。表单字段为 `project_id`、`file`、可选的 `display_name` 和异常任务的 `threshold`。该阈值默认 0.5，仅决定样本判定。输入包限制 128 MiB，单图最多 4,194,304 像素，包内原图累计最多 160,000,000 像素。

清单字段 `format` 固定为 `amvision.dense-evaluation.v1`。必填字段包括 `kind`、`model`、`dataset`、`split` 和 `samples`。划分必须为 `val` 或 `test`。每个样本包含唯一的 `id` 和包内原图路径 `image`。

- 语义分割提供有序 `classes`、`background_index`（默认 0）以及 `ignore_index`（默认 255）。每张图的 `truth` 与 `prediction` 指向原图同尺寸的整数类别索引 PNG。忽略像素不计入指标，mIoU 排除背景和无并集类别。
- 异常检测提供 `label`（`normal` 或 `anomaly`）及 0 到 1 的 `score`。可选 `prediction` 为 8 位或 16 位灰度热图，`truth` 为同尺寸二值掩码。像素级 AUROC 仅使用热图和掩码都存在的样本。缺少任一正负类时对应 AUROC 为 `null`。

报告及样本沿用 `/report` 和 `/samples`。样本筛选使用 `sample_filter=all|normal|anomaly|errors`。预览使用 `/samples/{index}/image?layer=original|truth|prediction`，无对应图层时返回 404。报告附带输入 ZIP 的 SHA-256。
