# 数据集导入与统一格式

## 目标

数据集导入把外部 zip 数据集转换为平台统一、版本化且可训练的数据集结构。上传、解析和校验由 backend-service 接纳，实际导入通过任务系统异步执行。

格式注册表 `backend/contracts/datasets/dataset_formats.py` 是导入、导出、训练输入和 API 能力目录的单一事实来源。

## 当前格式

| 任务 | 导入/导出格式 id |
|---|---|
| detection | `coco-detection-v1`、`voc-detection-v1`、`yolo-detection-v1` |
| segmentation | `coco-instance-seg-v1`、`voc-instance-seg-v1`、`yolo-instance-seg-v1` |
| pose | `coco-keypoints-v1`、`yolo-pose-v1` |
| classification | `imagenet-classification-v1` |
| obb | `dota-obb-v1`、`yolo-obb-v1` |

格式 id 同时固定任务类型与序列化规则，不使用只有 `coco` 或 `yolo` 的模糊公开标识。

## 处理链

```text
upload zip
  -> persist package + DatasetImport record
  -> enqueue task
  -> safe extract to staging
  -> detect/validate format
  -> parse samples, categories and splits
  -> normalize annotations
  -> write immutable DatasetVersion
  -> publish manifest/statistics
  -> clean completed staging
```

提交接口只保存上传包和待处理记录；Worker 根据 DatasetImport id 还原请求并处理。成功时 DatasetVersion 与 import 状态在受控事务内提交，失败时保留结构化 issue 和诊断日志。

## 安全解压

- 拒绝绝对路径、盘符、`..`、软链接逃逸和目标目录越界；
- 限制文件数、单文件大小和解压总量；
- staging 目录按 import id 隔离；
- 原始 zip 不作为训练目录直接读取；
- 只有完成写入并校验 manifest 的 DatasetVersion 才能被训练任务引用。

## 规范化

- 类别映射固定写入 DatasetVersion；
- 内部 bbox 使用 zero-based pixel 且右下边界 exclusive；
- segmentation 统一为可验证的 polygon/RLE 表达；
- pose 保存 keypoint schema、visibility 和顺序；
- OBB 保存四点多边形并规范点序；
- split 固定为明确的 train/val/test 归属；
- 图片尺寸、hash、媒体类型和相对对象路径进入 manifest。

导入不会修改原始标注含义来“猜测修复”错误数据。坐标越界、类别冲突、缺图、重复样本和损坏文件进入结构化问题列表，并按错误级别决定是否拒绝。

## 目录与持久化

外部 zip、staging 和最终 DatasetVersion 使用不同目录。最终版本只保存 ObjectStore 相对 key；开发机或用户上传目录的绝对路径不进入公开 manifest。

数据集版本不可原地修改。重新导入、筛选或变换会创建新版本，并记录来源版本和转换摘要。

## 导出与训练

导出器从统一 DatasetVersion 生成指定的版本化格式；训练适配器也只读取统一版本，不直接依赖原始 zip 布局。这样导入、导出、YOLOX/Ultralytics/RF-DETR 训练共享类别、split 和标注不变量。

格式细节：

- [COCO detection](coco-detection.md)
- [COCO instance segmentation](coco-segmentation.md)
- [COCO keypoints](coco-pose.md)
- [VOC detection](voc-detection.md)
- [VOC instance segmentation](voc-instance-segmentation.md)
- [YOLO detection](yolo-detection.md)
- [YOLO instance segmentation](yolo-segmentation.md)
- [YOLO pose](yolo-pose.md)
- [ImageNet classification](classification.md)
- [DOTA / YOLO OBB](dota-obb.md)

## 实现入口

- 格式注册表：`backend/contracts/datasets/dataset_formats.py`
- 导入服务：`backend/service/application/datasets/imports/service.py`
- 格式解析：`backend/service/application/datasets/imports/formats/`
- 导出服务：`backend/service/application/datasets/exports/`
- 数据集领域：`backend/service/domain/datasets/`
- API：`backend/service/api/rest/v1/routes/datasets/`

## 明确边界

- 当前核心不内置标注编辑器；标注由外部工具生成后导入。
- 不把某个模型仓库的数据目录当平台内部格式。
- 不在请求线程同步解压和解析大型数据集。
- 不允许格式探测结果覆盖调用方明确指定且通过校验的任务类型。
