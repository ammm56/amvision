# 模型转换与 Pose 评估修复方案

状态：本轮已确认代码问题的修复与定向回归已完成。当前真实业务资产仅有 YOLO11 分类模型、相关图片和 Workflow App／Runtime／Trigger；其他任务的小样本训练、合成张量与算子执行结果均属于工程验证，不能计作真实业务精度、性能或工业长稳验收。历史矩阵状态不代表本轮正在运行，旧策略通过也不自动计为 v3 通过。原始验收记录见[用户权限与业务链路验收](user-access-acceptance.md)。稳定契约已同步到[转换](../architecture/models/conversion-runtime.md)、[训练评估](../architecture/models/training-evaluation.md)和[部署](../architecture/models/deployment-runtime.md)文档。

## 1. 问题分类与结论

| 组合 | 已确认原因 | 修复归属 |
| --- | --- | --- |
| YOLO26 detection | ONNX 与 OpenVINO 的 TopK 前候选通过原容差，TopK 后行顺序及临界候选集合不同；通用逐行比较拒绝。另有旧 ONNX 专项校验漏检框坐标 | 模型转换数值门禁，不能照搬旧 detection 例外 |
| YOLO26 segmentation / pose / obb | PyTorch 与 ONNX 的 TopK 前候选、共同选中候选的附加字段通过原容差；TopK 的临界候选集合不同 | 同一类端到端 TopK 校验缺口，必须覆盖 mask 系数、proto、关键点和角度 |
| YOLOv8 / YOLO11 pose | 训练 test 与独立评估使用不同的 scaleup、NMS 阈值及关键点裁剪坐标域；逐项对齐后，两端指标吻合 | 项目评估与推理展示策略混用，统一评估契约 |
| RF-DETR segmentation | OpenVINO AUTO 在 CPU 启动辅助阶段转入 GPU 后，结果端口访问失败；纯 OpenVINO 程序也可复现 | OpenVINO AUTO 与多输出模型的运行时集成问题；异步队列不是必要触发条件 |

没有证据把这些问题整体归因于权限、共享内存或旧 checkpoint 加载。YOLO26 存在历史校验例外，Pose 存在两条实现路径的策略漂移，RF-DETR 存在依赖运行时行为；三者不能用一次依赖升级或一项宽松容差统一解决。

## 2. 核对范围与证据边界

调查基于源码提交 `58645f96`、原失败轮次的模型及转换产物、相应隔离 SQLite。没有重新训练替代模型来掩盖原失败。诊断使用进程内观测钩子、内存中的 ONNX/OpenVINO 中间输出及相同输入，不修改原产物和正式服务；Pose 诊断关闭报告写入。

开发 conda 环境中核实的版本：PyTorch `2.12.1+cu126`、ONNX `1.21.0`、ONNX Runtime `1.26.0`、OpenVINO `2026.2.0`、NumPy `2.4.4`、pycocotools `2.0.11`。发行包解释器必须单独核对，不能由开发环境版本推断。

参考目录声明的版本为 Ultralytics `8.4.115`、RF-DETR `1.8.3`。两个目录均无独立 `.git`；不能把父仓库的 HEAD 当作参考项目的上游提交。关键参考文件的 SHA-256 如下，参考代码只用于审查，不作为项目运行依赖。

| 参考文件 | SHA-256 |
| --- | --- |
| `projectsrc/ultralytics/ultralytics/nn/modules/head.py` | `25096c28ded538d8c3b2579d7b7ae289a02b2f111b86d8a988ce8e658d33769d` |
| `projectsrc/ultralytics/ultralytics/models/yolo/pose/val.py` | `b0758a82c5fd5b46b35b01ba2e1708510ed4c87d2a6fa74aeffebef921dce8b7` |
| `projectsrc/rf-detr/src/rfdetr/models/lwdetr.py` | `a0722f953465a5a22f6c0adf1f0c27035d9a8abfbcb658f1a747c961341e7dfc` |
| `projectsrc/rf-detr/src/rfdetr/export/main.py` | `5630769885072debf8e5de88d449b14000eb74bae80805ebfa116e0ca640c795` |

当前证据来自少量单 epoch 模型，足以定位这批失败，不能证明全部权重、输入尺寸、精度及设备都等价。所有最终通过状态仍依赖后面的真实矩阵。

## 3. YOLO26：校验 TopK 语义，不能遗漏几何信息

### 3.1 代码与实测

项目的 [TopK 实现](../../backend/service/application/models/yolo26_core/postprocess/export.py)与参考 `Detect.get_topk_index` 均先按各 anchor 最大类别分数选取候选，再对候选的类别分数取 TopK；segmentation、pose、obb 使用同一组索引提取附加字段。不同类别可以对应同一 anchor，合法性不能简化为“anchor 必须唯一”。

PyTorch 明确说明同分 TopK 的索引不保证稳定，见 [torch.topk](https://docs.pytorch.org/docs/2.9/generated/torch.topk.html)。此外，接近同分的候选可能因微小数值差异跨越 K 边界，导致选中集合改变。因此仅排序输出或匹配框后比较，仍不足以证明转换正确。

对原模型的固定输入，在 fp32 下使用原 `rtol=1e-3, atol=1e-4`，观察到：

| 比较路径 | TopK 前候选形状 | 候选最大绝对差 | 候选 allclose | 共同候选的完整 processed 行 |
| --- | --- | ---: | --- | --- |
| detection ONNX → OpenVINO CPU，显式 f32 | `[1,2016,5]` | `7.6293945e-6` | 通过 | 通过，255/300 个 anchor 共同选中 |
| segmentation PyTorch CPU → ONNX | `[1,2016,37]` | `3.0517578e-5` | 通过 | 通过，含 mask 系数；proto 独立比较也通过 |
| pose PyTorch CPU → ONNX | `[1,2016,11]` | `3.0517578e-5` | 通过 | 通过，含全部关键点字段 |
| obb PyTorch CPU → ONNX | `[1,2016,6]` | `3.0517578e-5` | 通过 | 通过，含角度 |

上述 processed 输出的原始逐行比较均不通过。补充固定 float32 随机输入核对，四类任务的候选分数最大绝对差约 `5.59e-8～7.08e-8`；不同集合中的分数均接近约 `0.00311` 的 TopK 边界。这是数值近似下的候选选择差异，不能描述成“所有元素仅交换顺序”或“所有差异都是严格相等分数”。

另一个独立问题位于 已移除的旧 `yolo26_core/export/validation.py` detection 校验：`allclose` 仅由 score/class 比较决定。构造相同分数、相同类别但四个框坐标均偏移 1000 的结果，返回 `allclose=True, finite=True, raw_row_allclose=False`。旧例外由历史提交 `b1e5b36b` 引入，其描述把候选选择变化简化为行排序，实际保护不足。

修复前的 [ONNX 入口](../../backend/service/application/models/yolo26_core/export/onnx.py)仅 detection 使用该特殊摘要和 `strict_numeric_validation=False`；另外三类任务与 [OpenVINO artifact smoke](../../backend/service/application/models/model_artifact_runtime_smoke.py)仍按张量位置比较。[转换 worker](../../backend/workers/conversion/supervised_conversion_runner.py)又以摘要的 accepted/allclose 判断是否接受，形成前后不一致的门禁。

### 3.2 修复设计

在现有转换验证模块内定义统一的数值验证策略，区分固定顺序张量和端到端 processed TopK 输出，不新增常驻服务，不改变部署模型的公开输出布局。

1. **候选比较**：按固定 anchor/class 顺序验证形状、有限值、框、分数、mask 系数、关键点、角度；segmentation 的 proto 单独验证。沿用已有对应精度容差，分类 ID 必须合法，不能用浮点容差接受错误类别。
2. **选择合法性**：根据完整 processed 行重建唯一 anchor/class 对，并构造合法 stage1 集合的见证，验证每阶段数量、索引范围、排序约定、anchor/class 对应关系和选中字段来源。唯一性约束落在合法的候选标识上，不能错误排除同 anchor 的不同类别。
3. **边界差异**：每个后端先证明自己的观测结果是同次执行候选的合法 TopK，完整行必须精确来自候选；跨后端候选使用既有数值容差。近同分跨后端发生次序变化时分别检查自身选择，禁止借其他候选的误差放宽本后端的排序和 Gather 复制规则。
4. **完整字段验证**：共同候选按标识比较完整行；不同候选仍必须能映射回各自已验证的原候选，不能因为不在交集中就跳过框或附加字段。
5. **结果摘要**：保留原逐行差异作为诊断，分别记录 candidate、selection、task extra/proto 的检查结果及策略版本。只有全部必要检查成功才允许 accepted；finite、shape 失败不能被其他字段覆盖。

中间观测输出仅用于转换验收，不写入正式 ONNX/IR/engine 的公开输出。实现应由项目 exporter 明确提供验证映射，不能把本次诊断用的 `node_Split_1732` 等优化器生成名称硬编码成长期契约。若某后端无法可靠观测所需中间信息，保持未通过并明确原因；不能退化为 score/class 校验。

最终公开 artifact 还必须单独执行真实推理和任务输出验证，避免只证明增加观测输出的图正确，却遗漏优化后发布图的行为。TensorRT 需要相同语义的验证与实际 engine 执行，不能把 build 成功等同于通过。

旧 detection 漏检逻辑在替代策略完成后移除。不得全局关闭严格校验、整体增大容差、只比较高置信度框、给分数添加人为 epsilon，或切换公开模型到 raw 输出以绕过失败。

## 4. Pose：统一评估，分离指标坐标与展示裁剪

### 4.1 已定位的三项差异

| 项目 | 训练 test | 独立评估当前路径 |
| --- | --- | --- |
| 小图 LetterBox（修复前） | 数据加载 `training=False`，`scaleup=False` | 复用普通 predictor，默认 `scaleup=True` |
| NMS IoU 阈值 | 默认 `0.7` | predictor 常量 `0.65` |
| 关键点裁剪 | 在模型输入画布坐标下经过裁剪 | 反变换到原图后裁剪到原图边界 |

入口见 [Pose 数据准备](../../backend/service/application/models/yolov8_core/data/pose.py)、[训练评估](../../backend/service/application/models/yolov8_core/training/pose_execution.py)、[独立评估](../../backend/service/application/models/evaluation/pose_evaluation.py)、[坐标变换](../../backend/service/application/models/yolo_core_common/geometry.py)。YOLO11 存在对应的相同策略差异。

原样本为 `96×64`，模型输入为 `384×256`。scaleup=True 时放大 4 倍；False 时保持原尺寸并加 padding。直接改变模型所见内容，不能期待指标相同。关键点落在 padding 区域时，反变换后裁剪到原图可能把错误坐标推向 GT 边界，抬高 OKS。

使用同一 checkpoint、数据 split、CPU 设备和评估阈值，逐项对齐的 OKS AP50 如下。此处 CPU 数值不同于原 GPU 轮次，不替换原失败记录；判断依据是每个受控比较内部的两端结果。

| 诊断步骤 | YOLOv8 | YOLO11 |
| --- | ---: | ---: |
| 同设备训练评估基线 | 0.076923 | 0.111111 |
| 原独立评估 | 1.000000 | 1.000000 |
| 仅独立评估 scaleup=False | 0.250000 | 0.200000 |
| 再对齐 NMS=0.7 | 0.250000 | 0.166667 |
| 再取消独立评估反变换后的点裁剪 | 0.076923 | 0.111111 |

最后一步的 AP50:95 分别为 `0.063030999`、`0.067233560`，也与同设备训练报告的 `0.063031`、`0.067234` 在报告舍入精度内吻合。证明不能仅修改 scaleup 或 NMS 就宣布修复。

参考 Ultralytics 的验证流程也区分验证预处理与展示；其 Pose 指标还包含 bbox area×0.53 等自身约定。本项目两端使用共享 pycocotools 指标入口，没有证据表明这个参考系数是本次两端差异的原因，不能只在某一端复制参考公式。

### 4.2 修复设计

- 定义一个内部不可变的 `PoseEvaluationPolicy` 模型，统一输入大小、scaleup、score/NMS/keypoint 阈值、最大检测数、坐标策略、OKS sigma、GT area 规则和策略版本。由训练验证、训练 test、独立评估共同解析，避免在各 predictor 中散落新魔法值。
- 默认评估沿用验证预处理的 `scaleup=False` 和 NMS `0.7`，已有显式评估参数仍有效；对比测试必须使用相同策略。一般部署的 `model_input_spec.scaleup=True` 和交互推理参数不被全局改写。
- 指标使用未做显示裁剪的关键点，预测与 GT 进入同一坐标域。采用原图坐标时，两端都执行纯逆变换，GT area 与该坐标域一致；裁剪只用于结果绘制。训练端也必须检查模型画布外点，不能只修独立评估一端。
- 复用模型 core 的预处理、解码和 NMS；在现有运行时适配器中提供受控的内部评估上下文/入口，返回指标所需坐标。避免复制第二套模型实现，也不能从已经裁剪的公开预测结果逆推出原始坐标。
- 本次诊断的取消裁剪是进程内实验，不是把全局 `scale_yolo_point_from_letterbox` 改成不裁剪的生产方案；该函数还被其他几何任务复用，需要保留现有调用者默认行为。
- 新报告写明 evaluation policy 版本和实际参数，训练与独立评估比较前先检查策略、权重摘要、split 与输入规格一致。旧报告保留，不修改历史数值；缺少策略元数据的旧报告明确为历史结果，通过重新评估产生可比较的新报告。

使用现有报告 JSON 承载新增诊断信息，优先不改数据库 schema。实现若确实需要持久字段变更，先补模型和 Alembic 迁移；本轮验证 SQLite。不得破坏已有 HTTP 推理结果 schema 或把评估策略加入共享内存逐帧控制逻辑。

## 5. RF-DETR segmentation：修复 AUTO 启动阶段

### 5.1 复现证据

原 IR 有完整的 `pred_boxes [1,100,4]`、`pred_logits [1,100,2]`、`pred_masks [1,100,96,96]`。参考 RF-DETR 的 `forward_export` 返回这三类张量，本项目导出契约对应；参考仓库没有 OpenVINO runtime 实现可直接套用。

原失败部署的 device 是 **auto**，不是显式 CPU。转换 smoke 的 CPU 成功不能证明 AUTO 部署成功。只使用 OpenVINO、NumPy 和原 IR，脱离 API、异步队列、SDK、Workflow 和数据库，可得到同样错误：

```text
Cannot find tensor for port ... pred_masks/sink_port_0[0]:f32[1,100,96,96]
```

| 冷启动条件 | 本次诊断结果 |
| --- | --- |
| 显式 CPU | 连续 8 次调用成功 |
| AUTO:CPU | 连续 10 次调用成功 |
| 默认 AUTO，3 个独立进程 | 分别成功 5、4、5 次后发生相同错误 |
| AUTO + ENABLE_STARTUP_FALLBACK=False，3 个独立进程 | 每个进程连续 8 次调用成功，实际执行设备 GPU.0 |

另一次逐次观测显示 `EXECUTION_DEVICES` 先为 `(CPU)`，转为 `GPU.0` 的调用即失败。该 GPU.0 为 Intel UHD iGPU；不能因为机器有 NVIDIA 显卡就把此次 OpenVINO AUTO 描述为 TensorRT 或 NVIDIA 执行。CPU 编译端口还可能同时具有 `einsum`、`pred_masks` 别名，单凭 `get_any_name()` 不足以判定原图缺少 mask 输出。

OpenVINO AUTO 的 CPU 启动辅助和后续设备切换是官方机制，`enable_startup_fallback` 控制这一启动行为，见 [AUTO device selection](https://docs.openvino.ai/2026/openvino-workflow/running-inference/inference-devices-and-modes/auto-device-selection.html)。关闭启动辅助与关闭运行期间的故障回退不是同一项配置。

证据将问题收敛到本机 OpenVINO 2026.2.0 AUTO 切换期间的输出访问，不足以指定上游某一行源码或宣称某个旧/新版本已修复。未完成版本二分，也未证明全部 GPU 均有此问题。短次成功仅验证修复方向，不能计为长稳或完整异步链路通过。

### 5.2 修复设计

首个修复限定在 RF-DETR segmentation 的 AUTO 编译：通过 [统一 OpenVINO 编译入口](../../backend/service/application/runtime/support/openvino_execution.py)传入内部强类型编译选项，关闭启动辅助，等待 AUTO 选定设备完成编译后再宣告会话就绪。保留 AUTO 设备选择，其他模型和显式 CPU/GPU/NPU 不批量改变。

- requested/effective 诊断记录实际编译属性、OpenVINO 版本、选择设备及适配原因。该必要属性不支持时明确启动失败，不能作为普通可选属性静默忽略。
- 保持 mask 输出必需，按完整名称集合、形状及契约解析输出，不硬编码输出下标或依赖任意别名。启动 warmup 检查三类输出；失败释放 request/session 和部署状态。
- 不通过重试单次推理、重新建异步队列、把 mask 当空结果、强制全部模型 CPU 或修改共享内存容量解决。
- 不先增加用户必须理解的兼容开关。内部适配的撤销条件是替代 OpenVINO 版本通过同一套冷启动、输出和性能矩阵；依赖升级作为单独变更评估。
- 关闭启动辅助可能延长首次就绪时间。测量冷编译、热缓存启动、首帧和稳定阶段，核对现有超时与进度状态；不得无依据提高全部服务的启动时限。

## 6. 完整实施顺序

每一步先完成最小复现/失败断言，再修改对应模块，核对通过结果后进入下一步。GPU 用例串行执行。测试统一放在 `tests/`，按 `test_*.py` 命名；长链入口放在已有 `tests/integration/`，不放在生产模块旁。

| 步骤 | 工作与主要位置 | 进入下一步的门禁 |
| --- | --- | --- |
| 1. 固定复现和契约 | 扩展现有 YOLO export、Pose chain、deployment runtime、RF-DETR lifecycle 测试；冻结原失败权重/样本摘要及评估策略 | 旧检测校验能被几何反例击穿；Pose 三项差异可重复；AUTO 错误能在独立进程复现。缺硬件时明确跳过，不伪造通过 |
| 2. Pose 评估修复 | `models/evaluation`、YOLOv8/11 core 评估、Pose runtime 适配器 | 相同权重/split/policy/设备两端 AP50 和 AP50:95 满足既有 0.05 门禁；受控小样本在报告舍入精度内一致；部署公开输出及展示无回归 |
| 3. YOLO26 PyTorch→ONNX | `yolo26_core/export`、共享 export validator、转换摘要消费端 | 四类任务候选和完整输出通过新语义门禁；所有反例必须失败；移除旧 score/class 例外；正式 ONNX 仅保留原输出 |
| 4. OpenVINO/TensorRT 转换验证 | `model_artifact_runtime_smoke` 与现有转换执行器 | 相同策略覆盖 ONNX→IR/engine，正式产物真实推理通过；dense 输出仍用原严格比较。无法观测的项不得记为 accepted |
| 5. RF-DETR AUTO 适配 | 统一 OpenVINO 编译入口、RF-DETR segmentation predictor、生命周期诊断 | CPU、显式 GPU、AUTO 的输出完整；AUTO 至少 20 个冷进程各执行至少 20 帧，覆盖原切换窗口；sync/async、停止/重启、失败回收通过 |
| 6. 7 个组合串行完整复测 | 既有 `model_task_e2e_matrix` | 每组合走 DatasetImport→Export→Train→Evaluate→ONNX/OpenVINO/TensorRT→sync/async→Workflow→stop/reset，含 RF-DETR segmentation 此前未覆盖的 TensorRT |
| 7. 全矩阵与真实发行 | 全部 18 组合；CPU/NVIDIA 标准 assemble-release；各 bundled Python、正式 .NET SDK | 18 组合分别有可核验结果；发行模型导入/部署/调用通过，CPU 包不强行执行不支持的 TensorRT；NVIDIA 包补实际 TensorRT 模型调用 |
| 8. 稳定性与收尾 | 修复前后固定负载、启动生命周期、文档 | 记录首帧/p50/p95/p99、吞吐、RSS/Private、线程/句柄、会话回收；关键路径至少 30 分钟无错误、无持续资源增长；核对门禁后更新状态并清理本轮隔离临时产物 |

### 必须覆盖的反例与边界

- TopK：严格同分、近同分、分数明显分离、K 边界替换、候选数小于 K、多 batch、多类别、同 anchor 不同 class；框偏移、错误类别、缺少高分候选、错误重复项、mask 系数/关键点/角度错配、proto 错误、NaN/Inf 均拒绝。
- Pose：小于/等于/大于输入尺寸、横竖图及 padding、边界和画布外关键点、遮挡/不可见点、空图、多实例、多类别、两点与 COCO 17 点、NMS 临界重叠、自定义 OKS sigma。检查 bbox AP 与 OKS AP，不能只检查一个 AP50。
- OpenVINO：全名称集合解析、输出别名、缺少 mask 必须失败、属性不支持、异步实例冷启动、热缓存启动、停止后无残余会话。按实际设备记录结果，不把 AUTO 成功直接归类为 CPU/GPU 之一。
- 历史资产：已有 checkpoint、ONNX/IR/engine、部署导入包仍可按原公开格式读取；旧验证报告不自动变成新策略通过。需要重新转换的模型生成新 build，禁止原地覆写已发布产物。
- 性能：候选观测与完整等价性检查放在转换/评估阶段，不进入每帧推理、Broker 或 Trigger 热路径；编译兼容处理只在创建 session 时执行。

## 7. 当前实现与阶段验收

- Pose：三类模型、四种 runtime 共用评估参数解析；保持普通推理默认行为。额外修复评估小框过滤和缩放后的面积下限。原 YOLOv8/YOLO11 checkpoint 的同设备 CPU 复测中，训练与独立评估四项 AP 差值均小于 1e-6，未覆写原 GPU 报告。
- YOLO26：四类任务采用完整候选和两阶段选择验证，旧 detection 漏检路径已删除。项目 exporter 写入明确内部映射，ONNX 简化后仍可观测；正式产物不增加公开输出。
- OpenVINO/TensorRT：正式输出实际执行，候选观测仅在转换期。四类原 YOLO26 产物的 ONNX 与 OpenVINO 数值回放通过；TensorRT detection 真实 engine 的候选最大绝对差为 3.0517578e-5，新策略通过。
- RF-DETR AUTO：20 个独立冷进程、每个 20 帧，共 400 帧通过，三类张量完整且有限。实际设备为 Intel GPU.0，OpenVINO 2026.2.0。属性使用 Core 读回与显式 compile 双重配置；该版本 CompiledModel 不公开启动辅助属性，不能要求其 getter 必须支持。
- 完整链路补充发现 RF-DETR segmentation 独立评估的 mask 重建错误：显示轮廓使用 RETR_EXTERNAL，重新填充后丢失孔洞。相同权重、输入和 CPU 的隔离复测中，轮廓重建得到 mask AP50 约 0.076923，原始 mask 得到 0，与训练 test 一致。修复为内部强类型 RLE 结果，并按 COCO 规则读取标注；不改变普通推理输出和阈值门禁。15 项相关边界和评估 wrapper 测试通过。
- YOLO26 四项、YOLOv8/YOLO11 Pose 两项已分别完成真实训练、评估、三种转换、sync/async、Workflow 和 stop/reset，进程退出码均为 0。RF-DETR 首轮三种转换和所有部署链路通过，但因上述 mask 指标错误整体退出码为 1；修复后的完整重跑正在执行，不把首轮改记为通过。
- 新增 Pose/TopK/矩阵策略边界测试 62 项通过，后续又补充观测图不修改公开模型、缺映射拒绝、冻结策略常量的测试；对应 Pose/TopK 40 项通过。完整回归与实时矩阵结果在验收结束后统一填写。

以上为本轮补充修复前的历史记录，包含合成或小样本工程数据。所述“正在执行”仅描述当时状态，本轮未据此宣告完整矩阵、真实发行、SDK、性能和半小时稳定性通过。

### 2026-09-09 补充修复

本轮测试进程已退出，确认使用 `review-20260909-quality` 临时目录的进程数为 0。收尾时自动审批审核以 `blocked by policy` 拒绝递归删除，因此 `.tmp/review-20260909-quality` 尚未清理；该目录不是长期交付物。

- YOLO26 v2 有两个已复现错误放行：其他候选的 0.0005 分数误差可放行临界处漏选更高分候选；Gather 输出的框坐标偏移 0.005 可被模型级容差放行。两个反例先在旧实现失败，v3 改为同次执行精确映射和排序后通过。
- ONNX、OpenVINO、TensorRT 原路径将观测候选与另一执行的正式输出混用。现已按同次观测获取完整输出并独立验证，另外检查正式/观测完整交接；无法对应标记不可验证并停止发布，不误报成模型损坏。校验摘要新增交接证据，正式输出格式和元数据映射格式保持兼容。
- OpenVINO 通用多输出验收先核对数量，再按 ONNX 输出名称对应，覆盖普通 dense 与 TopK 模型的 IR 端口换序。普通双输出模型换序反例已先复现旧实现误判，修复后通过。
- 分割正式 proto 直接跨后端比较，防止多个观测交接阶段的容差累加放行；公开概率越界即使处在数值容差内也拒绝。
- 最终定向回归 55 项通过：TopK 38 项、实际 ONNX Runtime/OpenVINO CPU 算子与转换入口 13 项、TensorRT 编排替身 4 项。四类 TopK 算子测试核对正式 ONNX/XML/BIN 的 SHA-256 未变。TensorRT 替身测试只证明编排与失败清理，不是 GPU engine 数值验收。
- 较广模型回归 159 项通过，包含 Pose 两端评估、RF-DETR 分割任务链与生命周期、部署配置、转换 worker 和 TensorRT 支持。端口换序修复后转换相关回归 62 项通过；最后的 proto 修复由上述 55 项再次覆盖。这些批次有重叠，不相加作为独立用例总数。相关生产源码与新增测试的 Ruff 检查通过，Git diff 空白检查通过；依赖弃用和固定 shape 的 ONNX tracing 警告仍保留。
- 新增检查只在转换阶段运行，不修改 LocalBuffer、推理/Trigger 邮箱、训练事件共享内存或 Workflow 热路径，也不修改现有 YOLO11 分类业务资产。已有 Pose 评估和 RF-DETR 原始 mask／AUTO 修复随本轮模型回归复核。严格 fp32 的 TensorRT 性能成本及 AUTO 首次就绪时间仍需按实际业务环境测量，不能用单元测试推断。

## 8. 执行与状态更新规则

开发环境先执行 `conda activate amvision`，按[现有模型矩阵命令](user-access-acceptance.md#复验入口)逐项复测；完整运行至少包含 `--start-processes --run-workflow --batch-mode fixed --max-images-per-split 4 --training-precision fp32`，隔离 run-id 和空闲端口。小数据验证工程行为，不能代替真实业务模型的精度和性能验收。

每一步记录源码版本、依赖版本、权重/输入摘要、有效参数、实际设备、错误及退出码。比较报告必须匹配相同数据和策略。失败进程不能因后来补读摘要而被改写成正常退出；补验单独标注。

发行代码只能由源目录修复后执行 `assemble-release` 生成，不手工修补 `release/<profile-id>/app/`。本轮不修改权限模型、默认管理员 Token、传输协议和共享内存布局，不增加 MySQL/PostgreSQL 验证范围。

当前仍需完成真实全矩阵、发行和长期负载验收，核对 Pose 新策略对业务权重的影响，以及 AUTO 冷启动与 TensorRT 严格 fp32 构建的性能成本。算法和观测实现已有定向证据，不能把它们等同于所有设备、精度和权重均已通过。
