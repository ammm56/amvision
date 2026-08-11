# 开发数据集审计

## 目的

`data/files/datasets` 是开发和真实链路验证的数据源。训练准确率验收前必须先
证明数据可解码、格式完整、标注有效、split 独立且任务所需的 validation/test
均存在。训练代码不得用静默裁剪、跳过坏图或复制 validation 指标掩盖数据问题。

## 独立命令

```powershell
python -m backend.maintenance.development_dataset_audit `
  --root data/files/datasets `
  --workers 16 `
  --output .tmp/development-dataset-audit.json
```

可用 `--task classification|detection|segmentation|pose|obb` 缩小任务范围；
`--dataset <name>` 必须和 `--task` 一同使用。命令只读数据集，发现 error 或
blocker 时返回非零退出码。图片读取使用有界线程池，所有结果在主线程按稳定
顺序汇总。

## 可重复验收数据准备

原始问题数据集不做静默原地修改。Pose 清洗版和 OBB 旋转几何 benchmark 使用
独立命令生成到新目录，然后仍由上述审计命令判定：

```powershell
python -m backend.maintenance.development_benchmark_datasets prepare-pose `
  --source-root data/files/datasets/pose/hand-keypoints `
  --output-root data/files/datasets/pose/hand-keypoints-clean-v1 `
  --train-count 2048 --val-count 256 --test-count 256 --seed 20260809

# 准确率矩阵使用完整去重/修复后的 train，并把完整来源 val 确定性拆成 val/test
python -m backend.maintenance.development_benchmark_datasets prepare-pose `
  --source-root data/files/datasets/pose/hand-keypoints `
  --output-root data/files/datasets/pose/hand-keypoints-full-v1 `
  --use-all --test-ratio 0.5 --seed 20260809

python -m backend.maintenance.development_benchmark_datasets generate-obb `
  --output-root data/files/datasets/obb/rotated-components-v1 `
  --train-count 1200 --val-count 200 --test-count 200 `
  --image-size 384 --seed 20260809
```

Pose 准备过程使用图片 SHA-256 去重，train 优先保留，validation 来源再确定性拆为
val/test；越界 bbox 裁到图内，越界可见关键点改为 `(0, 0, 0)`，并写出
`preparation-report.json`。相同图片存在冲突标签时直接失败。OBB benchmark 覆盖
多角度、多实例、两类别和背景纹理，只用于验证旋转框代码与链路，不替代现场
真实数据的业务准确率验收。

## 检查内容

- 所有图片执行真实 OpenCV 解码、尺寸检查和 SHA-256 跨 split 重复检查。
- classification 检查 train/validation/test、类别目录和各 split 类别集合。
- YOLO detection、segmentation、pose、OBB 检查 YAML、图片/标签配对、token、
  class id、有限数、归一化范围、bbox 边界、polygon 面积、关键点可见性。
- `item` 与 `no_item` 互斥类别检查同图高 IoU 冲突；`none` 等未说明否定对象的
  类别直接报错，必须改成明确的 `no_<class>`。
- VOC 同时支持平铺目录和 `VOC2007`/`VOC2012` 外壳；默认解释为常用的
  0-based、`xmax/ymax` exclusive，只有 XML 明确声明时才使用官方 PASCAL VOC
  1-based、inclusive。标准 `trainval.txt` 按 `train.txt ∪ val.txt` 聚合索引
  校验，不重复计数，也不把它误判成第三个独立 split。
- 缺独立 validation 或 test、缺任务数据集、跨 split 完全重复均作为工业验收
  阻塞项，不由训练器自动重分配数据。

## 2026-08-10 全量审计结论

报告：`.tmp/development-dataset-audit-20260810.json`。本轮共检查 17 个数据集，
9 个通过，8 个未通过。任务分布为 classification 5、detection 6、
segmentation 3、pose 2、OBB 1。

严格通过的数据集：

- classification：`computerasurfacedefect` 211 张、`mnist` 70,000 张、
  `trayemptyfullpcba1` 237 张。
- detection：`barcodeqrcode` 609 张 / 982 标注、`construction-ppe`
  1,416 张 / 11,520 标注。`construction-ppe` 的 10 个孤立标签已移除，
  明确的 PPE 正/负类别未发现 IoU≥0.9 的互斥标注冲突。
- segmentation：`crack-seg` 4,029 张 / 5,290 标注、`package-seg`
  2,197 张 / 7,643 标注。
- pose：`hand-keypoints-clean-v1` 2,560 张 / 2,560 标注，包含
  train/validation/test 和经完整校验的 21 点 `flip_idx`。
- OBB：`rotated-components-v1` 1,600 张 / 3,951 标注。该数据只用于
  旋转几何和平台链路验收，不替代现场真实 OBB 业务数据验收。

未通过的数据集及阻断原因：

- `imagenette2` 缺独立 test。
- `imagewoof2` 缺独立 test，并有 2 组跨 split 完全重复。
- `african-wildlife` 有 20 组跨 split 完全重复。
- `luoding` 缺 validation；`medical-pills` 缺 test。
- detection `voc2012` 的 11,540 张独立图片和 31,561 个标注均通过格式、
  坐标和解码检查；`trainval` 与 `train ∪ val` 一致。该数据仍因缺独立 test
  不能用于工业 test 验收。
- segmentation `voc2012` 同一根目录发现多个数据集 YAML，根结构不唯一。
- 原始 `hand-keypoints` 缺 test，有 38 组跨 split 重复、
  3,353 个 bbox 越过图片边界、83 个 bbox 字段超出归一化范围和
  1,548 个关键点坐标越界。

未通过的数据集保留为问题复现资产，不得形成“200 轮工业准确率已验收”
结论。只有严格通过且业务语义经人工确认的数据集，才能进入对应的长轮次验收。

### hand-keypoints 全量规范集

`hand-keypoints-full-v1` 已使用上述 `--use-all` 路径独立生成并完成专项全量审计：

- train 18,724、validation 3,977、test 3,976，共 26,677 张。
- 修复 3,349 个越界 bbox，将 1,548 个越界可见关键点显式改为不可见。
- 按图片 SHA-256 删除 91 个重复项，未拒绝样本。
- 图片、标签、21 点拓扑、`flip_idx`、split 独立性均通过，专项报告为
  `.tmp/development-dataset-audit-hand-keypoints-full-v1.json`。

`hand-keypoints-clean-v1` 保留为快速 smoke；准确率 A/B 和 100/200 轮矩阵必须显式
选择 `hand-keypoints-full-v1`，不得再用 smoke 子集形成全量准确率结论。
