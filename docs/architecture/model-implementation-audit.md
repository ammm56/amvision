# 模型实现与参考源码审计基线

## 参考边界

仓库内 `projectsrc/YOLOX_2026`、`projectsrc/ultralytics`、`projectsrc/rf-detr` 和 `projectsrc/supervision` 只用于开发期核对。本项目训练、转换、部署和 Workflow Runtime 不得 import 这些目录，也不得把参考仓库的 CLI、目录约定或响应对象直接暴露为平台契约。

模型与任务支持范围以 [模型支持矩阵](model-support-matrix.md) 为唯一文档事实来源。

## 审计层级

每个已声明支持的模型/任务组合按下列层级取证，不能把低层 smoke 写成高层准确率结论：

1. 数据契约：导入、统一格式、DatasetExport 和标签校验。
2. Core 行为：构建、forward/backward、loss、assigner、decode 与 postprocess。
3. 权重覆盖：project-native 模型严格加载目标 checkpoint，不忽略缺失或 shape mismatch。
4. 数值比较：固定输入与随机性，对参考实现比较 raw tensor、loss、梯度和后处理。
5. 平台短链：训练、验证、评估、转换、sync/async Deployment 和推理。
6. Runtime 比较：PyTorch、ONNX Runtime、OpenVINO 与 TensorRT 输出差异摘要。
7. 现场验收：独立 test 数据、目标硬件吞吐、内存/显存和长时间稳定性。

## 数据加载与训练稳定性

- Dataset 初始化只保存路径、尺寸和标注索引，像素在 `__getitem__` 中逐样本读取。
- DataLoader 使用有限 worker、batch 和 prefetch；禁止把全量图片像素缓存进内存。
- Windows Worker 中的 multiprocessing 配置必须避免嵌套 spawn 与不可回收 iterator。
- 暂停、终止、异常和训练结束必须关闭 iterator、子进程与文件句柄。
- validation 必须按 batch 首维逐图切分 prediction 与 target，不能跨图匹配。
- AMP overflow 不得推进 EMA 或 scheduler；几何敏感计算使用足够精度并对 NaN/Inf fail-fast。
- segmentation evaluator 使用压缩 RLE，不在完整 split 上常驻 dense mask。
- Pose 使用 keypoint OKS，OBB angle 使用弧度；显示阈值不能污染 evaluator 几何。

## 转换与部署

- 转换成功必须同时证明产物可加载和数值误差在登记阈值内。
- TensorRT/OpenVINO 系统依赖缺失时标记未执行，不能记为通过。
- RF-DETR 导出重建必须使用训练登记的 input size；position embedding shape mismatch 不能通过 `strict=False`、插值或忽略权重绕过。
- Deployment 启动后验证健康、预热、sync/async、停止和进程回收。
- 长时 soak 记录吞吐、P95/P99、RSS/VRAM、句柄、队列深度与错误率。

## 新增或升级模型的门禁

- 更新支持矩阵与输入输出契约。
- 核对参考版本、预处理、增强、head 布局、loss、evaluator 和 checkpoint key。
- 运行数据契约、Core、严格权重、转换和 Deployment 定向测试。
- 真实硬件后端未执行时明确记录环境边界。
- 参考快照升级必须重新生成数值基线；不能仅修改版本号。

可复用的完整检查项见 [模型 full core 验收](model-full-core-audit-checklist.md)。
