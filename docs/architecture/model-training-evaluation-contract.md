# 模型训练与评估契约

## 目的

本文档固定分类、检测、实例分割、姿态和 OBB 训练任务共同遵守的
checkpoint、数据 split、评估产物和恢复训练规则。模型实现可以不同，
但不能改变这些平台语义。

适用模型：

- YOLOv8、YOLO11、YOLO26
- YOLOX
- RF-DETR
- 后续接入相同任务类型的模型

## 数据 split

- `train` 只用于梯度更新。
- `val`、`valid`、`validation` 是同一类验证 split，只用于选择 best checkpoint
  和训练期调参。
- `test` 只用于训练结束后的独立评估。
- 缺少 validation 时训练必须拒绝启动，不能回退到 `test` 或其他 split。
- 缺少 test 时训练仍可完成，但 `test-metrics.json` 必须明确写
  `available: false`，不能复制 validation 指标。
- 数据家族、采集序列、托盘和批次的分组划分由数据准备过程负责。训练执行器
  只验证 split 角色，不能推断或重分配业务数据。

## Warm start、resume 和 checkpoint

三类输入不可混用：

- warm start：只加载模型权重，开始一项新的训练任务。
- resume：恢复模型、optimizer、scheduler、epoch 和已有 best 状态。
- previous best：恢复任务时延续此前已经确认的 best checkpoint。

任务执行 adapter 必须把 warm-start 和 resume 参数完整传递到模型执行层，
不能只在 API 中接受却在执行时丢失。

训练期间维护两个文件：

- `latest-checkpoint`：最近一次可恢复训练状态。
- `best-checkpoint`：validation 指标提升时立即保存的真实模型状态。

`best-checkpoint` 不能在训练结束时用 latest checkpoint 复制生成。暂停、恢复
和中断后，已有 best 指标与 best checkpoint 必须继续有效。

## 评估顺序

训练执行顺序固定为：

1. 在 train 上更新参数。
2. 按配置周期在 validation 上评估。
3. validation 指标提升时立即保存 best checkpoint。
4. 训练结束后重新加载 best checkpoint。
5. 只在独立 test split 上执行一次最终评估。
6. 写入训练指标、验证指标、测试指标和训练摘要。

test 结果不得反向影响 best checkpoint、学习率或训练轮数。

## 输出文件

训练任务至少维护：

- `train-metrics.json`
- `validation-metrics.json`
- `test-metrics.json`
- `training-summary.json`
- `best-checkpoint`
- `latest-checkpoint`

分类任务的 test 报告应包含：

- top-1、top-5
- confusion matrix
- 每类 support、预测数量、正确数量和准确率

检测类任务的 test 报告应包含：

- 任务类型
- mAP 等该任务已有的总体指标
- evaluator 能提供时的逐类指标
- `split_name: test`
- `checkpoint_role: best`

分割、姿态和 OBB 使用各自 evaluator 的指标字段，不伪装成 classification
混淆矩阵。若后续增加统一阈值下的检测混淆矩阵，必须在报告中记录阈值和匹配
规则。

## 数据与增强约束

- COCO annotations 必须按 `image_id` 聚合。同一图片的多个实例必须作为一个
  样本的多个目标，不能拆成多张重复图片。
- 未知 `category_id` 必须报错，不能静默映射到类别 0。
- 关闭分类增强时使用确定性 resize/crop，不允许保留随机裁剪。
- validation 和 test 不使用训练随机增强。

## RF-DETR 边界

RF-DETR 使用 Lightning 原生 checkpoint 回调维护 best 和 latest 文件。平台
只登记和复制已经由 trainer 写出的真实 checkpoint，不用训练结束时的当前权重
冒充 best。`trainer.test` 必须显式使用 best checkpoint，并且只绑定 test
dataloader。

## 验收

每个模型和任务类型至少覆盖：

- warm-start 参数到达模型执行层。
- validation 缺失时拒绝训练。
- test 不参与 best 选择。
- validation 改善时 best checkpoint 立即更新。
- resume 后 best 状态不丢失。
- test 报告来自 best checkpoint。
- 缺少 test 时报告明确 unavailable。
- API、任务详情页和输出文件列表可读取 `test-metrics.json`。
