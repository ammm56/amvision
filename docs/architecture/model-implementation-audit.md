# 模型实现与参考源码审计基线

## 参考版本与运行边界

当前仓库内参考快照为：

- `projectsrc/YOLOX_2026`：YOLOX 0.3.0
- `projectsrc/ultralytics`：Ultralytics 8.4.47
- `projectsrc/rf-detr`：RF-DETR 1.8.3

`projectsrc/` 只用于开发期核对。生产训练、转换和推理不得 import 这些目录，也不得依赖已安装的 Ultralytics 或 RF-DETR 官方包。

## 平台公开矩阵

| 模型 | detection | classification | segmentation | pose | OBB |
| --- | --- | --- | --- | --- | --- |
| YOLOX | 支持 | 不支持 | 不支持 | 不支持 | 不支持 |
| YOLOv8 | 支持 | 支持 | 支持 | 支持 | 支持 |
| YOLO11 | 支持 | 支持 | 支持 | 支持 | 支持 |
| YOLO26 | 支持 | 支持 | 支持 | 支持 | 支持 |
| RF-DETR | 支持 | 不支持 | 支持 | 不支持 | 不支持 |

RF-DETR 1.8.3 参考源码包含 `RFDETRKeypointPreview` 和 GroupPose 预览路径，但本项目尚未把它声明为稳定平台能力。classification 和 OBB 也不是该参考仓库的公开 RF-DETR 任务。API 和 catalog 必须明确拒绝这些组合，不能回退到其他模型实现或伪装成已支持。

## 已有证据等级

当前测试覆盖以下不同层级，层级不可混称：

1. 数据契约：导入、统一存储、导出和任务格式校验。
2. 结构行为：模型构建、forward/backward、loss/assigner/postprocess 的定点测试。
3. 平台短链：训练、验证、转换、sync/async deployment 和推理 smoke。
4. runtime 数值：PyTorch 与导出的 ONNXRuntime 输出差异摘要，部分 OpenVINO/TensorRT 真实工具链 smoke。
5. 上游 checkpoint 数值等价：相同 checkpoint、固定输入、固定随机性下，对上游与 project-native 的 raw tensor、loss、梯度和后处理逐项比较。

第 1 至 4 层已有自动化与历史真实短链证据。YOLOv8、YOLO11、YOLO26 的
classification、segmentation、pose、OBB 已使用各自 M checkpoint 完成 raw
forward、核心 loss 和 checkpoint key 100% 覆盖率的参考快照数值回归；其中
classification tuple 输出顺序、segmentation anchor/mask 坐标、YOLO26 pose
decode、OBB grid/pixel 坐标和角度质量权重均有独立回归用例。该证据仍不等于
每个 scale、每个 checkpoint 和每类真实数据均完全等价，因此不得扩大宣称范围。

非 detection 的 ONNX Runtime、OpenVINO、TensorRT 真实矩阵按 3 个 YOLO
family × 4 个 task 分别覆盖转换、独立加载和一次推理。TensorRT engine 构建
必须按资源预算分组执行，不能用覆盖全部后端的单一短超时判定失败。

## 大数据集加载结论

YOLOv8、YOLO11、YOLO26、通用 classification/segmentation/pose/OBB Dataset、YOLOX COCO Dataset 和 RF-DETR YOLO Dataset 都只在初始化阶段保存路径、尺寸和标注元数据；图片像素在 `__getitem__` 中逐样本读取。万级样本测试使用 10,000 条不存在或占位图片路径构建 Dataset，确保初始化不会调用图片解码。

DataLoader 使用有限 batch 和有限 prefetch，不会把全部图片一次载入内存：

- 通用 YOLO 任务默认 `num_workers=2`、`prefetch_factor=2`。非 detection 任务在
  同一增强阶段跨 epoch 复用 worker；Windows 不再按固定 epoch 周期重建
  `spawn` worker，只在增强阶段变化、训练结束、暂停/终止、异常退出或调用方
  显式设置复用上限时回收，避免 200 轮训练累积数十分钟启动停顿。
- 非 detection worker 只并行执行图片读取和增强，batch 以 NumPy IPC 载荷返回，
  由训练主进程显式恢复为 Tensor、pin 并传入设备；classification 不再对 NumPy
  载荷直接调用 Tensor API。IPC 数组必须拥有独立 C-contiguous 内存，禁止保留
  `Tensor.numpy()` 的 Tensor `base`；真实 `batch=79`、640×640 segmentation 两轮
  复测中，两个 worker 从旧实现的 17–18.5 GiB 线性增长收敛为 0.8–1.57 GiB
  稳定高水位。结束、暂停、终止、异常和周期 validation 路径均关闭 iterator，
  `num_workers=0` 时不会调用不存在的 multiprocessing shutdown 方法。
- spatial task 的 validation 使用最终训练 batch 做 GPU 前向，并按 batch 首维逐图
  切分 prediction、proto 和 target；切分过程保持 batch 维，连续分配全局 image id，
  首维不匹配时明确报错。COCO/OKS/rotated 关联仍按单图执行，避免跨图匹配。
- CUDA 默认启用 `pin_memory`，CPU 默认关闭。
- YOLOX 在 Windows 队列 worker 中默认 `num_workers=0`，避免嵌套 spawn 的 pickle/EOF 故障；它仍逐样本惰性读取。独立训练环境可以显式设置 worker、prefetch 和 persistent workers。
- RF-DETR 沿用训练配置中的有限 worker 数，YOLO 格式数据使用 lazy dataset。

元数据本身仍与样本数线性增长，这是索引成本，不是图片像素常驻成本。超大规模数据集如需进一步降低元数据内存，应新增磁盘索引或分片 manifest，不能用无界图片 cache 解决。

## 2026-08-09 至 2026-08-10 真实训练证据

以下结果来自项目 API、queue worker、本地对象存储、project-native 模型、真实
PyTorch/ONNX/OpenVINO/TensorRT 工具链，不是 mock evaluator：

| 任务 | family / 轮数 | 数据 | 独立 evaluation 结果 |
| --- | --- | --- | --- |
| classification | YOLOv8/11/26 M，各 200 轮 | computerasurfacedefect | 三者 top-1 / top-5 均为 1.0 |
| segmentation | YOLOv8 M，200 轮 | package-seg | bbox AP50-95 0.474789，mask AP50-95 0.406950 |
| segmentation | YOLO11 M，200 轮 | package-seg | bbox AP50-95 0.495424，mask AP50-95 0.415066 |
| segmentation | YOLO26 M，200 轮 | package-seg | bbox AP50-95 0.474219，mask AP50-95 0.439617 |
| pose | YOLOv8 nano，200 轮 | hand-keypoints-clean-v1，384，最多 512/ split | OKS AP50 0.373712，AP50-95 0.209513 |
| pose | YOLO11 nano，200 轮 | hand-keypoints-clean-v1，384，最多 512/ split | OKS AP50 0.255705，AP50-95 0.132818 |

最终数值修复后的 OBB 1 轮 FP16 三家族 smoke 使用 64 张/split，validation
rotated AP50-95 为 0.164443 / 0.182726 / 0.170973；独立 test AP50-95 为
0.021443 / 0.074073 / 0.039526。三家族均完成 ONNX、OpenVINO、TensorRT 的
sync/async deployment。该结果证明旋转几何 evaluator 和完整 runtime 链路可执行，
不把 1 轮指标当作收敛准确率。

上述 nano/384/子集训练是平台长链和数值稳定性基线，不是现场工业准确率承诺。
Pose 完整源数据规模与上游常用 640 配置更大；OBB 数据为生成的旋转几何
benchmark。正式业务验收仍需现场独立 test、目标 scale/input、硬件吞吐和长时
稳定性结果。

Pose 精度矩阵现已固定使用专项审计通过的 `hand-keypoints-full-v1`（18,724 /
3,977 / 3,976），矩阵命令通过 `--dataset-dir` 显式覆盖 smoke 默认数据。训练期和
独立评估均分别输出 bbox AP 与 keypoint OKS AP，best checkpoint 只按
`val_oks_ap50_95` 选择。此前基于 `hand-keypoints-clean-v1` 的全部结果继续保留为
smoke 证据，不与全量基准合并。

`gate-runtime-summary-20260810` 进一步使用 YOLOv8m/640、128 张/split 验证实际
AutoBatch=46、FP16 AMP、batched pose validation、独立 test 和 ONNX 转换。val/test
均得到 38,400 条预测，训练摘要中的 batch、precision、device 与运行时一致。该任务
仅训练 1 轮且随机初始化，因此 AP=0 只证明链路与契约成立，不用于收敛对比。

## 发布判定规则

- smoke 通过只能证明链路可执行，不能证明准确率或上游数值等价。
- 转换通过必须同时有产物合法性和 runtime 数值摘要；真实 TensorRT/OpenVINO 依赖缺失时必须标记未执行，不能记为通过。
- 新增模型 task/scale 前必须更新平台支持矩阵、数据格式、训练/验证、转换和全部 runtime backend 测试。
- 上游参考快照升级后必须重新核对预处理、head 输出布局、loss/assigner、增强、evaluator 和 checkpoint key 映射。
- total loss 和 FP32 gradient 出现 NaN/Inf 时必须在 optimizer step 前后立即失败，不能继续更新模型或写出被污染的 checkpoint。
- CIoU、ProbIoU/OBB angle、pose OKS/area 与 YOLO26 RLE 使用 FP32 几何，避免
  FP16 对像素坐标平方后产生 Inf/NaN 并污染 assigner、box/DFL/class loss。
- AMP overflow 被 `GradScaler` 跳过时不得更新 EMA 或推进 scheduler；segmentation
  的 loss 敏感路径使用 FP32，训练摘要记录真实 optimizer step 与跳过数。
- segmentation 训练 evaluator 使用 compressed COCO RLE 和真实 pycocotools，
  不在完整 split 上保存 dense instance mask；GT mask 恢复到 COCO image 尺寸，
  prediction mask 在 bbox crop 后直接编码 RLE。
- YOLOv8/11/26 segmentation 训练 target 与 Ultralytics `polygon2mask` 保持同一
  `fillPoly -> cv2.resize(INTER_LINEAR)` 规则。禁止用固定步长切片代替 mask resize；
  在官方 crack-seg 的 640→160 量化中，旧切片与参考 target 的实例平均 IoU 只有
  0.703，且少保留约 6.1% 裂纹像素，足以使 bbox 与 mask AP 明显分离。
- 三代 YOLO segmentation loss 必须先汇总整个 batch 的 class/box/DFL 分子与
  `target_scores_sum`，mask loss 必须先汇总整个 batch 的 foreground 分子与数量，
  最后统一归一化并乘实际 batch size。禁止逐图归一化后再相加；后者会低估多实例图，
  并容易漏掉空标注图片的背景 BCE。YOLO26 semantic loss 同样按参考 criterion 乘
  batch size 后再参与 one-to-many/one-to-one 分支组合。
- pose 训练和数据集级评估分别使用真实 pycocotools bbox AP 与 keypoints AP；
  推理显示用的 keypoint confidence threshold 不参与 OKS 几何。
- OBB evaluator 的 `xywhr` angle 固定为弧度，只评估 test 或 validation 中的
  一个 split，并把无 GT 背景图片上的预测计入 false positive。
