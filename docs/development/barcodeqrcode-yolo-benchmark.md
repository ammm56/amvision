# barcodeqrcode YOLO detection 对照验证

## 数据入口

- 原始数据：`data/files/datasets/detection/barcodeqrcode.zip`
- 原始格式：VOC，485 个 train、35 个 val、89 个 test 图像
- 类别：`barcode`、`qrcode`
- 标注总数：982
- 坐标约定：`zero-based-exclusive`
- 审计结果：无空图、无非法框、无跨 split 图像哈希重复，单图最多 14 个框

旧版本 `dataset-version-7320cd9d424f` 曾按官方 VOC 1-based inclusive 解释，导致每个框
发生 `x/y - 1` 和 `width/height + 1` 偏移，不得用于对照训练。重新导入和导出后的
有效对象如下：

- Dataset id：`barcodeqrcode-audited-20260809`
- DatasetVersion id：`dataset-version-56389cbf90b6`
- DatasetExport id：`dataset-export-0b60c00a94f3`
- 格式：`coco-detection-v1`

已逐一比较 609 个图像和 982 个原始 XML/导出 COCO 标注，坐标不一致数量为 0。

## 训练矩阵

三项实验统一使用 M scale、COCO 预训练权重、200 epochs、batch size 16、FP32、
`cuda:0`、640×640 输入和每 5 epochs 一次验证。YOLOv8/YOLO11 使用 NMS 评估，
YOLO26 使用 end-to-end decode，不暴露 NMS 参数。

| 模型 | Task id | Warm start | 状态 |
| --- | --- | --- | --- |
| YOLOv8-M | `task-a72d54c0373e` | `mv-pretrained-yolov8-detection-m` | succeeded |
| YOLO11-M | `task-c7c1d1164e8f` | `mv-pretrained-yolo11-detection-m` | succeeded |
| YOLO26-M | `task-dc87406728d3` | `mv-pretrained-yolo26-detection-m` | succeeded |

训练完成后记录 best checkpoint、最终 validation/test AP50、AP50-95、逐类 AP、耗时、
显存峰值和收尾产物完整性。随机初始化或使用旧坐标导出的历史任务不纳入横向结论。

初始 r3 对照在运行中发现 detection 增强顺序与参考实现不一致：Mosaic 生成的
1280×1280 大画布在 RandomPerspective 裁剪前执行水平翻转，但框坐标错误地按
640 宽度变换。r3 已全部终止。r4 使用修正后的
`Mosaic/LetterBox → RandomPerspective → MixUp → HSV → Flip` 顺序，MixUp 图像权重
同时改为参考实现的 `Beta(32, 32)` 分布。

## 已完成结果

### YOLOv8-M

- 运行时间：2026-08-09 02:25:58 至 04:03:10（Asia/Shanghai），200 个 epoch 历史完整。
- 最终 validation：AP50 `0.998982`，AP50-95 `0.935104`；barcode AP50-95 `1.000000`，qrcode AP50-95 `0.870208`。
- best checkpoint test：AP50 `0.977180`，AP50-95 `0.910970`；barcode AP50-95 `0.954133`，qrcode AP50-95 `0.867807`。
- 前 10 轮到后 10 轮的训练均值：total loss `2.679219 → 1.157160`，class `1.584002 → 0.280443`，box `0.107394 → 0.030444`，DFL `0.721174 → 0.525739`。相邻 epoch 可因随机采样和增强上升，但完整窗口趋势下降。
- best/latest checkpoint、labels、training/validation/test metrics 和 summary 均已落盘；best checkpoint 已重新加载并完成独立 test split 评估，登记 ModelVersion `model-version-4018f11108d4`。

### YOLO11-M

- 运行时间：2026-08-09 04:03:10 至 05:40:18（Asia/Shanghai），200 个 epoch 历史和 40 个验证点完整，best 出现在第 185 轮。
- 最终 validation：AP50 `0.999845`，AP50-95 `0.936883`；barcode AP50-95 `1.000000`，qrcode AP50-95 `0.873766`。
- best checkpoint test：AP50 `0.976914`，AP50-95 `0.925409`；barcode AP50-95 `0.960396`，qrcode AP50-95 `0.890422`。
- 前 10 轮到后 10 轮的训练均值：total loss `2.833644 → 1.210310`，class `1.671733 → 0.311494`，box `0.118404 → 0.034724`，DFL `0.739831 → 0.529424`。四项完整窗口趋势均下降。
- best/latest checkpoint、labels、training/validation/test metrics 和 summary 均已落盘；独立 test 明确记录 `checkpoint_role=best`，登记 ModelVersion `model-version-9acec37f79bd`。

### YOLO26-M

- 运行时间：2026-08-09 05:40:18 至 07:17:52（Asia/Shanghai），200 个 epoch 历史和 40 个验证点完整，best 出现在第 160 轮。
- 最终 validation：AP50 `0.996437`，AP50-95 `0.933518`；barcode AP50-95 `1.000000`，qrcode AP50-95 `0.867037`。
- best checkpoint test：AP50 `0.979813`，AP50-95 `0.921565`；barcode AP50-95 `0.957244`，qrcode AP50-95 `0.885886`。
- 前 10 轮到后 10 轮的训练均值：total loss `1.678158 → 0.356248`，class `1.615465 → 0.206843`，box `0.114886 → 0.033343`，Smooth L1 `0.005854 → 0.001834`。任务运行时的旧 worker 把第三项序列化为 `dfl_loss`；优化项实际为 `reg_max=1` 的 Smooth L1，当前源码和公开参数已经统一命名为 `l1_loss`/`l1_loss_weight`。
- best/latest checkpoint、labels、training/validation/test metrics 和 summary 均已落盘；独立 test 明确记录 `checkpoint_role=best`，登记 ModelVersion `model-version-4eaad11108db`。

## 横向结论

| 模型 | 最终 val AP50-95 | best checkpoint test AP50-95 | barcode test AP50-95 | qrcode test AP50-95 |
| --- | ---: | ---: | ---: | ---: |
| YOLOv8-M | 0.935104 | 0.910970 | 0.954133 | 0.867807 |
| YOLO11-M | 0.936883 | 0.925409 | 0.960396 | 0.890422 |
| YOLO26-M | 0.933518 | 0.921565 | 0.957244 | 0.885886 |

三项任务使用同一导出、split、输入尺寸、batch size、精度、GPU、训练轮数和验证间隔。
三代模型均完成 200 轮训练、40 次真实 pycocotools 验证、best checkpoint 重载、独立 test
和 ModelVersion 登记。结果证明旧任务约 `0.2` 的 AP50-95 不是 barcodeqrcode 数据集或
M scale 的正常上限，而是旧空间增强顺序在 Mosaic 大画布上按错误宽度翻转标注造成的
系统性坐标破坏。修复后，三代模型的独立 test AP50-95 均超过 `0.91`，相互差异处于
该小型 validation/test split 的正常统计范围。

## 最新源码运行契约复核

服务和 worker 切换到最终源码后，又从页面提交了 YOLO26-Nano 单轮真实训练任务
`task-a28861235e5a`。该任务只验证运行契约，不用于精度横向比较：

- 状态为 `succeeded`，训练、validation、best checkpoint test 和 ModelVersion 登记完整；
- 持久化执行参数包含 `l1_loss_weight=1.5`，且不存在 `dfl_loss_weight`；
- 训练、validation、test 报告均输出 `l1_loss`，不再输出伪 `dfl_loss`；
- 任务结束后的 `batch_metrics` 为空，完整 epoch 指标和 validation 指标仍保留；
- 页面刷新后继续显示完整 epoch 的 `l1_loss` 和 AP50/AP50-95，且不显示已经失效的当前批次指标；
- 浏览器控制台无 warning 或 error。
