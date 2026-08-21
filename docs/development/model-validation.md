# 模型 full core 验收

本清单用于核对模型实现、参考语义、真实数据链、转换 artifact 和长期运行。它不保存某次测试的日期、通过数量或 `.tmp` 临时结果。

## 适用组合

- YOLOX detection
- YOLOv8/YOLO11/YOLO26：detection、classification、segmentation、pose、OBB
- RF-DETR：detection、segmentation

## 1. 结构与依赖

- [ ] 网络、loss、assigner、decode、validator、export 位于对应 `*_core`。
- [ ] 应用服务只做 Task、Repository、ObjectStore 与状态编排。
- [ ] Runtime adapter 不复制训练算法或维护第二套后处理。
- [ ] `projectsrc/` 未出现在生产 import、发行包或公开字段来源中。
- [ ] 共享模块不包含按 model name/版本分支的模型专用行为。

## 2. 权重与模型构建

- [ ] 每个公开 scale 的 checkpoint 可以按预期覆盖率加载。
- [ ] missing/unexpected/shape mismatch 有明确报告。
- [ ] strict load 没有被全局关闭。
- [ ] task、class count、keypoint shape、input size 和 head 匹配。
- [ ] RF-DETR training/export factory 的 position embedding resolution 一致。
- [ ] 非方形与 divisor 不合法输入有确定规则和测试。

## 3. 数据

- [ ] zip 安全解压、格式识别和样本数限制有效。
- [ ] DatasetImport → canonical → DatasetExport 往返保持类别和标注。
- [ ] 空 label、负样本、crowd/ignore、mask、keypoint visibility 和 rotated box 各按格式处理。
- [ ] 大数据集使用惰性索引/读取，不把全量图片载入内存。
- [ ] train/validation/test 划分可复现且不泄漏。

## 4. 训练

- [ ] forward、loss 和 backward 使用真实模型路径。
- [ ] optimizer、scheduler、AMP 和梯度累积参数真正生效。
- [ ] warm start 与 resume 分离。
- [ ] best/latest checkpoint 和 ModelVersion/ModelFile 登记完整。
- [ ] pause/cancel/failure 收敛 Task 终态并释放 GPU/文件句柄。
- [ ] 指标、CSV、TensorBoard 和事件写入频率不造成不可接受吞吐下降。

## 5. 验证与评估

- [ ] 模型 Core validator 用于训练期选择。
- [ ] 平台 dataset evaluation 使用明确的 class mapping 和 task-specific geometry。
- [ ] detection AP、mask AP、OKS AP、rotated AP 不混用。
- [ ] 与参考实现比较时固定输入、预处理、阈值、NMS 和指标口径。
- [ ] 精度差异有样本级证据，不以单个汇总数字猜测根因。

## 6. 转换

- [ ] ONNX graph 可加载、shape 正确并完成数值 smoke。
- [ ] OpenVINO IR 实际编译并推理。
- [ ] TensorRT engine 在目标版本实际构建并推理。
- [ ] conversion summary、artifact format、input/output name 和 dynamic/static shape 与实际一致。
- [ ] 失败不登记可部署 artifact。

## 7. Deployment

- [ ] PyTorch/ONNXRuntime/OpenVINO/TensorRT session 的预处理和后处理一致。
- [ ] sync/async、warmup、reset、stop 和进程恢复可用。
- [ ] 多实例资源配置基于活跃实例，不按全部已登记 Deployment 静态限制。
- [ ] 满载直接返回结构化错误，不引入隐藏排队和自动重试。
- [ ] LocalBuffer/mmap 输入不退化为 Base64 或临时图片复制。

## 8. Workflow

- [ ] 模型节点绑定明确 DeploymentInstance。
- [ ] Preview 与正式 Runtime 使用相同图片引用和模型调用语义。
- [ ] Parallel/For Each 的结果数、顺序和节点耗时正确。
- [ ] Runtime 版本切换后 Run provenance 与实际 worker epoch 一致。
- [ ] 异常、取消和超时释放 mmap 槽位与 Runtime admission。

## 9. 前端与 API

- [ ] OpenAPI 只公开已支持组合。
- [ ] 前端 capability 来自后端 registry/bootstrap，不维护第二份静态矩阵。
- [ ] 训练、转换、部署和推理页面显示 task-specific 参数与结果。
- [ ] 错误详情保留阶段、模型、artifact、device 和 request id。

## 10. 长期稳定性

真实目标机执行：

- 代表性长训练
- 三种 runtime 的 Deployment 持续推理
- Workflow Runtime + Trigger 持续负载
- 单 Worker Profile kill/recovery
- daemon/service/worker 优雅停止与异常恢复
- 跨日日志切换

记录：

- 成功率和时延分位数
- RSS、GPU memory、CPU、线程和句柄趋势
- queue depth、active Run 和恢复次数
- mmap slot generation/owner/deadline
- 日志文件切换和磁盘增长
- stop 后残留进程、端口和临时文件

## 自动化入口

```powershell
python -m tests.integration.model_task_e2e_matrix --start-processes
python -m pytest tests/integration/test_non_detection_runtime_backend_smoke_matrix.py -q
python -m pytest tests/integration/test_yolov8_detection_runtime_backend_smoke.py -q
python -m pytest tests/test_rfdetr_segmentation_task_smoke.py -q
```

完整发行进程验收：

```powershell
python -m pytest tests/integration/test_release_full_stack_acceptance.py -q
```

筛选、短链或空载测试只证明对应范围，不得写成完整模型矩阵或长期负载已通过。

## 结果存放

- 可长期复现的命令和通过标准保留在本文档或测试代码。
- 需要版本对比的稳定基线保留在专门 benchmark 文档。
- 临时 `.tmp` 输出、某次通过数量、日期流水和修复过程不进入架构正文。
- 当前支持结论统一更新 [模型支持矩阵](../reference/models/support-matrix.md)。
