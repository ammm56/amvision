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

第 1 至 4 层已有自动化与历史真实短链证据。第 5 层目前只有部分公式级对齐测试和 checkpoint 加载覆盖率，不具备每个 task × scale × checkpoint 的完整 golden。因此当前不得宣称全部模型与参考源码数值完全等价。

## 大数据集加载结论

YOLOv8、YOLO11、YOLO26、通用 classification/segmentation/pose/OBB Dataset、YOLOX COCO Dataset 和 RF-DETR YOLO Dataset 都只在初始化阶段保存路径、尺寸和标注元数据；图片像素在 `__getitem__` 中逐样本读取。万级样本测试使用 10,000 条不存在或占位图片路径构建 Dataset，确保初始化不会调用图片解码。

DataLoader 使用有限 batch 和有限 prefetch，不会把全部图片一次载入内存：

- 通用 YOLO 任务默认 `num_workers=2`、`prefetch_factor=2`，有 worker 时启用 persistent workers。
- CUDA 默认启用 `pin_memory`，CPU 默认关闭。
- YOLOX 在 Windows 队列 worker 中默认 `num_workers=0`，避免嵌套 spawn 的 pickle/EOF 故障；它仍逐样本惰性读取。独立训练环境可以显式设置 worker、prefetch 和 persistent workers。
- RF-DETR 沿用训练配置中的有限 worker 数，YOLO 格式数据使用 lazy dataset。

元数据本身仍与样本数线性增长，这是索引成本，不是图片像素常驻成本。超大规模数据集如需进一步降低元数据内存，应新增磁盘索引或分片 manifest，不能用无界图片 cache 解决。

## 发布判定规则

- smoke 通过只能证明链路可执行，不能证明准确率或上游数值等价。
- 转换通过必须同时有产物合法性和 runtime 数值摘要；真实 TensorRT/OpenVINO 依赖缺失时必须标记未执行，不能记为通过。
- 新增模型 task/scale 前必须更新平台支持矩阵、数据格式、训练/验证、转换和全部 runtime backend 测试。
- 上游参考快照升级后必须重新核对预处理、head 输出布局、loss/assigner、增强、evaluator 和 checkpoint key 映射。
