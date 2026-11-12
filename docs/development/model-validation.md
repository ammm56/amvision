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

### YOLOX 任务结束资源与工作集对照

设备契约回归覆盖共享 detection API 的五个模型入口，API 不预填 GPU 数量。
CPU 回退回归可在独立测试进程启动前设置 `CUDA_VISIBLE_DEVICES=-1`，不得修改
正在运行的服务环境；显式 CPU、自动 CPU、单 GPU、显式 CUDA 不可用和 GPU
占用分别检查。请求的 `gpu_count=null` 与实际执行的 `gpu_count=0/1` 不混用。

```powershell
conda activate amvision
python -m pytest tests/test_detection_training_device_contract.py tests/test_training_device_selection.py tests/test_training_device_leases.py tests/test_yolox_training_api.py -q
```

```powershell
conda activate amvision
python -m pytest tests/test_yolox_training_resource_boundary.py tests/test_yolox_augmentation_seed.py tests/test_training_engine.py -q
python -m pytest tests/integration/test_yolox_training_queue_cuda_release.py -q
python -m tests.integration.yolox_training_resource_audit --manifest-key <DatasetExport-manifest-key> --checkpoint-key <warm-start-checkpoint-key> --runs 16 --compare-working-set --output-dir .tmp/yolox-resource-audit
```

CUDA 队列用例覆盖成功、失败和取消后的真实 Tensor 释放；它与训练对照均需 GPU
独占租约，不应并行执行。最后一条命令在独立常驻进程读取现有导出数据及 checkpoint，
取得项目 GPU 独占租约，
先热身两次，再执行指定次数的 YOLOX-m/640/fp16/AutoBatch 单轮训练。增强开/关
交替，裁剪/不裁剪按四次一组交替；对照开关仅存在于验收工具，不是生产参数。
输出目录必须是尚不存在的 `.tmp` 子目录，防止覆盖已有结果。

每轮实际执行 train、validation、test，并通过正式 LocalDatasetStorage 写入 best/latest
checkpoint；写完并释放结果后核对弱引用、CUDA 活跃/保留字节、Private、RSS、句柄、
线程及子进程。工具不向现有任务数据库登记模型，也不重启生产 Worker。每轮仅删除
本工具生成的两份临时 checkpoint，源数据和模型保持不变。

评判时排除热身与其他重负载干扰，比较相同增强配置，并区分当前轮与前一轮的裁剪
策略。Private 的初次高水位增长不能直接判为泄漏；需要后续平台期证据。CUDA 活跃
字节、存活模型/EMA/optimizer/DataLoader 或子进程残留则应直接定位。成功短训循环
不替代长 epoch、多 GPU、多日 soak 和完整 API/任务登记链路验收。Windows 工作集
和 Private 的含义分别参考 [EmptyWorkingSet](https://learn.microsoft.com/en-us/windows/win32/api/psapi/nf-psapi-emptyworkingset)
与 [PROCESS_MEMORY_COUNTERS_EX](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters_ex)。

工具生成的 JSONL 可用于本轮统计；交付摘要后清理本次临时目录，不长期保留临时
checkpoint 或 `.tmp` 验收缓存。

`test_yolox_training_resource_boundary.py` 还覆盖队列记录写入失败、heartbeat 停止
异常、lease 丢失以及 Worker 致命故障的资源关闭。写入失败不得变成成功、继续
消费或隐藏重训；lease 丢失不得确认或覆盖其他 attempt。正常任务资源检查与
致命故障的进程退出检查是不同边界，不通过增加常驻线程或自动回收进程合并处理。

### 真实 HTTP 训练验收

`tests.integration.detection_training_live_audit` 使用当前服务、正式队列和训练 Worker，
按 case 文件顺序提交任务。会登记真实任务、模型和训练输出文件，均保留供页面核对；
不重启 Worker、不重试失败任务、不修改数据集。case 文件是包含 `name` 和正式训练
`request` 的 JSON 数组，最多 20 项。输出目录必须是尚不存在的 `.tmp` 子目录。

```powershell
conda activate amvision
python -m tests.integration.detection_training_live_audit --case-file .tmp/training-cases.json --output-dir .tmp/training-live-audit
```

默认读取本地开发凭据，也可通过 `AMVISION_AUDIT_TOKEN` 指定当前服务凭据；凭据
不写入报告。核对请求和实际设备、轮数、模型登记、输出文件状态、Worker 身份以及
完成后的 Private/RSS、句柄、线程、子进程。外部进程统计不能替代 CUDA 活跃字节和
对象存活检查。CPU 短训、GPU 正常轮数、增强开关与其他训练模型应分别报告。
超时只结束验收工具，不隐式取消已提交的任务；后续需检查页面中的任务状态。

跨模型单轮资源验收可显式使用固定小 batch 和 `execution.amp.mode=disabled`，
并核对实际摘要为 FP32。AutoBatch、AMP 和训练精度另用正常轮数验证；很少的
训练 step 可能全部被 GradScaler 跳过，此时必须按失败记录，不能用验证指标或
输出文件存在代替成功 optimizer step，也不能为通过验收隐式降级精度或重训。

小尺寸增强回归由 `test_yolox_multiscale_bounds.py` 覆盖：生成的多尺度高宽不小于
64 且保持 32 的倍数，避免单张批次落到 1×1 特征图。AutoBatch 使用相同上界；
关闭多尺度仍保持请求尺寸，标准 640±160 范围和随机序列不变。

## 结果存放

- 可长期复现的命令和通过标准保留在本文档或测试代码。
- 需要版本对比的稳定基线保留在专门 benchmark 文档。
- 临时 `.tmp` 输出、某次通过数量、日期流水和修复过程不进入架构正文。
- 当前支持结论统一更新 [模型支持矩阵](../reference/models/support-matrix.md)。
