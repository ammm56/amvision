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

训练恢复以已经成功写入的 checkpoint 为边界，不追求进程异常前最后一个 batch
或最后一轮的逐步恢复。公共 `checkpoint_interval` 默认是 5，即普通异常最多需要
重跑最近 checkpoint 之后尚未落盘的 4 轮；手动保存、暂停、终止、best 改善和
最后一轮仍会形成额外 checkpoint。resume 恢复模型、EMA、optimizer、scheduler、
AMP scaler、已完成 epoch 和已有 best 状态，但不保存或恢复 DataLoader、sampler、
Python、NumPy、PyTorch 或 CUDA RNG 的逐步状态。因此续训结果不承诺逐位一致，
但不得改变训练总轮数、学习率调度、best 选择规则和统计准确率验收标准。

`paused` 任务以及已经进入 `failed`、但仍有完整 latest checkpoint 的任务都可以
resume。没有 checkpoint、checkpoint 文件缺失或 checkpoint 校验失败时必须明确
拒绝或再次进入 failed，不能退回 warm start，也不能从损坏文件猜测状态。

`best-checkpoint` 不能在训练结束时用 latest checkpoint 复制生成。暂停、恢复
和中断后，已有 best 指标与 best checkpoint 必须继续有效。

best 指标必须是业务范围内的有限数。负数、NaN 和 Inf 不得参与比较；相同
指标不得反复覆盖历史 best checkpoint。恢复任务携带的历史 best 损坏时，
后续第一个有效 validation 指标可以重新建立 best。

## 评估顺序

训练执行顺序固定为：

1. 在 train 上更新参数。
2. 按配置周期在 validation 上评估。
3. validation 指标提升时立即保存 best checkpoint。
4. 训练结束后重新加载 best checkpoint。
5. 只在独立 test split 上执行一次最终评估。
6. 写入训练指标、验证指标、测试指标和训练摘要。

test 结果不得反向影响 best checkpoint、学习率或训练轮数。

训练、validation 和 test 的长循环必须在 batch 或 sample 边界轮询暂停、终止
状态，不能只在 epoch 结束时响应。epoch progress 在当轮 validation 和 best
判定完成后回写；有 validation 时同时更新 `validation-metrics.json`，不得先把
只包含 train loss 的中间状态伪装成完整 epoch 结果。

`evaluation_interval` 按页面展示的一基完成轮数解释。例如配置 20 时，在完成
第 20、40、60 轮后运行 validation，不得直接用零基 `epoch_index % 20` 导致
第 21、41、61 轮才评估。最后一轮始终评估一次，但没有 validation 样本时不得
伪造验证结果。

训练循环内部统一使用从 0 开始的 `epoch_index`，API、进度事件和指标文件中的
`epoch` 统一表示从 1 开始的已完成轮数。`epoch_history` 每项必须同时写出这两个
字段，不能把内部索引直接暴露为 `epoch`。因此第一轮固定记录为
`{"epoch": 1, "epoch_index": 0}`。

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

- segmentation 同时报告 bbox AP 和 mask AP；只要 validation 有实例 mask，
  best checkpoint 必须使用 mask AP，模型没有产生 mask 时按 0 处理，不能回退
  到 bbox AP。独立评估响应使用 `bbox_map50`、`bbox_map50_95`、`mask_map50`
  和 `mask_map50_95` 明确区分两类指标；v1 中的 `map50`、`map50_95` 只作为
  bbox 指标兼容别名，训练收尾与端到端验收不得依赖这个别名推断指标语义。
- pose 使用与实际关键点数量等长的 OKS sigma。COCO person 17 点使用官方
  sigma，其他拓扑使用显式配置或 `1 / num_keypoints` 等权值。训练与数据集级
  评估都使用真实 pycocotools keypoints evaluator。关键点置信度阈值只控制
  推理结果显示，不能把低置信坐标清零后再计算 OKS。
- OBB 使用旋转框 IoU，平台统一 `xywhr` 的角度单位为弧度，禁止按数值大小猜测
  角度单位，也不能用水平框 IoU 代替。数据集级评估只读取一个独立 test split；
  缺 test 时才读取 validation。没有 GT 的背景图片仍必须推理并计入误检。
- bbox、segmentation 和 keypoints 的 COCO 指标必须有真实 pycocotools 回归；
  AP50 和 AP50-95 从同一个目标 `maxDets` precision 切片读取，不直接依赖
  `COCOeval.stats` 的固定 `maxDets=100` 摘要位置。
- segmentation 训练期评估逐图生成实例 mask 后必须立即压缩为 COCO RLE。
  split 级状态只保留 bbox 和 compressed RLE，不得保留
  `image_count × maxDets × H × W` 的 dense mask。
- segmentation 的 proto mask 解码后必须按预测 bbox 裁切。训练 loss 使用
  `mask_ratio` 下采样 target；COCO AP 则必须使用 letterbox/增强完成后、下采样前的
  完整分辨率 GT mask，不能把低分辨率 loss target 最近邻放大后冒充原始 GT。
  完整 GT 在 DataLoader IPC 中使用 bit packing 传输，不能搬到 GPU；预测 mask 直接
  编码 RLE，不允许经过会丢失孔洞的 contour polygon 往返转换。
- YOLO segmentation 的 polygon 栅格化遵循参考实现的 `float -> int32` 截断规则；
  proto 和 mask coefficient 组合后的 raw logits 必须先插值、恢复原图，再按等价
  logit threshold 二值化，不能先 sigmoid 再插值改变细边界。

## 数值稳定性

- total loss 和 FP32 gradient 出现 NaN 或 Inf 时立即失败，不能继续更新或写出
  被污染的 checkpoint。
- FP16 forward 可以使用 autocast，但 assigner、IoU/DFL/BCE、mask 和 semantic
  loss 的数值敏感计算使用 FP32。
- 原始像素坐标的 CIoU、旋转框 ProbIoU/angle quality、pose OKS 面积与 YOLO26
  RLE residual 必须先提升到 FP32。即使输入宽高不超过 FP16 上限，平方距离和
  面积仍可能溢出，不能依赖最终 `nan_to_num` 掩盖污染。
- `GradScaler` 因 overflow 跳过 optimizer step 时，所有任务都不更新 EMA；当轮
  没有任何成功 optimizer step 时不推进 epoch scheduler。训练摘要记录成功
  optimizer step 和 AMP 跳过次数。
- 任一有训练样本的 segmentation epoch 没有成功 optimizer step 时必须失败，
  不能只根据不同 batch 的 loss 波动宣称模型正在收敛。
- `optimizer=auto` 的迭代量按 `ceil(dataset_size / max(batch, nbs)) × epochs`
  计算。MuSGD 只正交化 2D/4D 参数，最终 task head 的 `cv3/one2one_cv3`
  以及指定 segmentation 参数使用三倍学习率；Muon、SGD momentum 和
  Newton–Schulz 必须按 param group 批量更新。训练进度与摘要展示基础学习率，
  不得把首个三倍学习率分组误报为全局学习率。

## 数据与增强约束

- COCO annotations 必须按 `image_id` 聚合。同一图片的多个实例必须作为一个
  样本的多个目标，不能拆成多张重复图片。
- 未知 `category_id` 必须报错，不能静默映射到类别 0。
- 关闭分类增强时使用确定性 resize/crop，不允许保留随机裁剪。
- validation 和 test 不使用训练随机增强。
- 训练期 validation 使用不放大的 letterbox（`scaleup=false`）维持稳定的 best
  checkpoint 选择；训练收尾的独立 test 必须重新加载 best checkpoint，并使用
  与生产推理一致的 letterbox（`scaleup=true`）。YOLO 检测类任务的收尾 test
  与独立评估统一使用 `score_threshold=0.001`；segmentation 的二值 mask 阈值
  固定记录为 `0.5`。这些阈值和预处理策略必须进入报告，不能由验收脚本另行覆盖。
- pose 水平翻转必须使用数据集 manifest 中与关键点数量一致的
  `keypoint_flip_indices`。映射必须是完整排列且满足对合规则。非 COCO 17 点的
  自定义拓扑缺少映射时，启用翻转必须拒绝训练，不得只记录参数却静默不执行。
- Windows `spawn` DataLoader 的增强 worker 可以跨 epoch 复用，但 batch Tensor
  不能长期累积共享内存映射。非 detection YOLO 任务使用 NumPy IPC 载荷，
  在主进程恢复和 pin Tensor；同一增强阶段不按固定 epoch 周期回收 worker，
  仅在增强阶段变化、训练正常结束、暂停、终止和异常退出时显式清理。

## RF-DETR 边界

RF-DETR 使用 Lightning 原生 checkpoint 回调维护 best 和 latest 文件。平台
只登记和复制已经由 trainer 写出的真实 checkpoint，不用训练结束时的当前权重
冒充 best。`trainer.test` 必须显式使用 best checkpoint，并且只绑定 test
dataloader。

RF-DETR grouped-query warm-start 不允许按 Tensor 第一维做模糊 flat slice。正式
预训练资产的 `manifest.json` 必须包含 checkpoint 的原始布局：

```json
{
  "checkpoint_model_config": {
    "num_queries": 300,
    "group_detr": 13
  }
}
```

加载时优先读取 checkpoint 自带的 `args.num_queries/group_detr`；缺失时只允许使用
与该 checkpoint 精确对应的 catalog manifest。需要改变 query 数量或 group 布局但
两处都缺少元数据时直接拒绝 warm-start，不猜测分组，也不保留旧 flat-slice
兼容路径。catalog 启动扫描同样会拒绝缺少上述正整数配置的 RF-DETR manifest。

## 验收

每个模型和任务类型至少覆盖：

- warm-start 参数到达模型执行层。
- validation 缺失时拒绝训练。
- test 不参与 best 选择。
- validation 改善时 best checkpoint 立即更新。
- resume 后 best 状态不丢失。
- 默认周期在第 5、10、15...轮保存，异常恢复最多重跑一个周期内未落盘的轮次。
- failed 任务只有在 latest checkpoint 完整存在时才提供 resume。
- test 报告来自 best checkpoint。
- 缺少 test 时报告明确 unavailable。
- API、任务详情页和输出文件列表可读取 `test-metrics.json`。
- 暂停和终止在 batch/validation sample 边界可响应。
- 大 validation split 的 mask 状态使用 compressed RLE，内存不随 dense mask
  总像素数无界增长。
- AMP overflow 不更新 EMA 或错误推进 scheduler。
- 端到端矩阵按任务显式配对指标：segmentation 的 bbox 指标只与 bbox 指标比较，
  mask 指标只与 mask 指标比较；在相同 checkpoint、split、score threshold 和
  生产预处理下，训练收尾 test 与独立评估的对应 AP 绝对差不得超过 `0.05`。
