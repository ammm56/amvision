# 模型 full core 审计与验收清单

## 文档目的

本文档用于固定 `RF-DETR / YOLOX / YOLOv8 / YOLO11 / YOLO26` 的 full core 审计口径、残留问题分类和真实链路验收顺序。

本文档不是新的模型架构规划。长期目录边界仍以 [model-core-implementation-plan.md](model-core-implementation-plan.md) 为准。本文档只回答三个问题：

- 当前哪些模型可以认为已经进入 full core 验收阶段
- 哪些实现仍然是过渡残留、旧入口或轻量近似实现
- 第五批 custom nodes 已进入后，哪些模型链路和 custom model node 记录仍需要继续跟踪

## 当前结论

当前可以进入第五批 custom nodes 的剩余结构收口，但不能跳过模型主线和 custom model node 的持续验收记录。

`RF-DETR / YOLOX / YOLOv8 / YOLO11 / YOLO26` 的真实短链路已经形成可追溯记录，`YOLOE / SAM3` 也已按最新 core / runtime / payload / node adapter 边界完成当前阶段收口。第五批当前重点转为剩余 custom node 的结构治理：

- 已完成：`plc_modbus_tcp_nodes`、`output_local_db_nodes`、`output_mes_http_nodes` 的旧 `_runtime.py` 已拆到正式 `backend/runtime/`。
- 已完成：`camera_usb_uvc_nodes` 和 `barcode_protocol_nodes` 已删除旧 `backend/support.py`，并拆到正式 `backend/runtime/`。
- 已完成：`_opencv_shared` 已删除旧 `backend/support.py`，跨 OpenCV node pack 共享能力已拆到 `backend/runtime/`。
- 显式验收：长时间训练、更长 `release/full` 常驻 soak、更长周期资源占用和异常恢复基线仍单独跑，不放进默认 pytest，也不作为第五批结构收口的默认阻塞条件。

## 判断状态

- `完成`：代码边界清楚，核心结构与参考实现对齐，真实数据短链路、长时间 soak、资源占用和异常恢复基线都已记录，已知不支持项已经显式写明。
- `短链路已记录`：真实数据短链路、真实转换产物、deployment sync / async、workflow 调用和前端页面操作已有可追溯记录；长时间训练、更长 soak、全 scale checkpoint 或更长周期资源异常恢复仍单独跑。
- `需修复`：存在模型行为、训练、评估、导出、postprocess 或 runtime 语义差距，需要改代码。
- `过渡残留`：功能可能能跑，但仍依赖旧命名、旧入口、共享大文件或临时 smoke，容易误导后续实现。
- `不支持`：参考实现里有，但本项目当前明确不做。必须写清原因和边界，不能伪装成已实现。
- `需验收`：实现看起来完整，但还缺真实数据、真实 checkpoint、转换产物或长期 runtime 验收记录。

## 参考源码目录

以下目录只作为开发阶段参考，不作为运行时代码依赖。

- `projectsrc/rf-detr/src/rfdetr`
- `projectsrc/YOLOX_2026/yolox`
- `projectsrc/ultralytics/ultralytics`
- `projectsrc/supervision/src/supervision`

对照规则：

- `RF-DETR` 参考 `rfdetr/models`、`rfdetr/datasets`、`rfdetr/training`、`rfdetr/evaluation`、`rfdetr/export` 和 `rfdetr/utilities`。
- `YOLOX` 参考 `yolox/models`、`yolox/data`、`yolox/evaluators`、`yolox/utils` 和训练导出工具链。
- `YOLOv8 / YOLO11 / YOLO26` 参考 `ultralytics/cfg/models`、`ultralytics/nn`、`ultralytics/data`、`ultralytics/engine`、`ultralytics/models`、`ultralytics/utils/loss.py`、`tal.py`、`ops.py` 和 export 相关逻辑。
- `supervision` 只能作为结果对象、可视化和几何工具参考；不能让项目运行时代码直接依赖 `projectsrc`。

## 当前 core 目录

当前模型 core 目录已经具备基础分层，但这不等于所有 full core 行为都已验收完成。

- `backend/service/application/models/rfdetr_core`
- `backend/service/application/models/yolox_core`
- `backend/service/application/models/yolov8_core`
- `backend/service/application/models/yolo11_core`
- `backend/service/application/models/yolo26_core`
- `backend/service/application/models/yolo_core_common`

`yolo_core_common` 只允许放真正跨 `YOLOv8 / YOLO11 / YOLO26` 共用、且不包含模型代际和任务语义的底层能力。以下内容不应长期放在 `yolo_core_common`：

- 某个 `model_type` 专属 cfg、head、decode、postprocess
- 某个 `task_type` 专属 loss、assigner、target、evaluation
- 旧 `yolo_primary_*` 过渡模型构建入口
- 会让 YOLOv8、YOLO11、YOLO26 隐式混线的任务训练入口

## 图像预处理与输出坐标规则

模型预处理不按项目统一成同一种 LetterBox。每个模型必须保持和自身参考实现一致的训练、验证、导出和 runtime 预处理规则；项目层统一的是公开输出坐标和字段语义。

- `YOLOv8 / YOLO11 / YOLO26` 的 `detection / segmentation / pose / obb` 按 Ultralytics `LetterBox(center=True, scale_fill=False)` 语义处理非正方形图片。训练、验证、导出和 runtime 必须共享同一套中心 padding、gain、pad_left、pad_top 和原图坐标反算规则，禁止再回到直接拉伸到正方形后用 `scale_x / scale_y` 反算 bbox、mask、keypoint 或 rotated box。
- `YOLOX detection` 保持 YOLOX 参考实现的左上角 padding 预处理：按最小缩放比 resize 后写入输入画布左上角，其余区域填充 `114`。训练、validation、evaluation 和 runtime 必须统一使用这套 `resize_ratio` 规则，不为了项目表面一致性强行改成 center LetterBox。
- `RF-DETR detection / segmentation` 保持 RF-DETR 参考实现的固定尺寸 resize 和归一化输入规则。RF-DETR 内部可使用 normalized `cxcywh` 或固定输入尺寸坐标，runtime 和 export 后处理必须在边界处转换为任务原生结果：detection 输出原图 detection box，segmentation 输出原图 mask / polygon / instance result。
- `classification` 任务没有 bbox 坐标反算，允许按模型参考实现使用 resize / crop / normalize，但训练、验证、转换和 runtime 的输入规则必须一致。
- `mask / proto / heatmap / preview` 的 resize 是任务后处理或显示步骤，不等同于输入几何拉伸错误；它们仍必须明确输入尺寸、原图尺寸和坐标系。

对外公开结果按任务原生语义输出，不强行把所有任务压成 `xyxy`：

- detection 的主输出是原图坐标 `bbox_xyxy`。
- segmentation 的主输出是 `segments / mask / mask_area` 等实例分割结果；`bbox_xyxy` 只能作为普通显示、筛选或流程节点辅助外接框，不能替代 mask / polygon。
- pose 的主输出是原图坐标 keypoints 与置信度；`bbox_xyxy` 只能作为人体、手部或对象实例的辅助外接框。
- OBB 的主输出是 rotated box，例如 `bbox_xywhr` 或 polygon；`bbox_xyxy` 只能作为普通显示和粗筛选外接矩形，不能替代角度和旋转框语义。
- 模型内部可以使用 `xywh`、`cxcywh`、`xywhr`、normalized 坐标或 feature map 坐标，但这些表示只允许存在于 core 内部或 task 内部边界，并且必须在公开结果边界转换为对应 task 的原生输出。
- 公开字段中图片尺寸统一使用 `image_width`、`image_height`；张量形状和 `input_size` 若使用 `(height, width)`，必须在函数名、参数名或注释中写清楚，避免 `width / height` 与 `height / width` 混用。

### 模型内部 box 格式契约

本项目统一的是公开输出，不强行统一模型内部 raw tensor。内部格式必须和对应参考实现一致，并在 validation、export 和 runtime 边界明确转换。

- `YOLOv8 / YOLO11` 非 end2end detection、segmentation、pose raw head 输出按 Ultralytics 默认使用 `xywh`。runtime 和 validation 必须先按 `xywh` 完成候选筛选、NMS 和 LetterBox 反算，再输出对应 task 的原生结果。COCO detection 结果文件中的 `bbox` 使用 `[x, y, width, height]` 是 COCO 文件格式要求，不是模型公开输出契约。
- `YOLOv8 / YOLO11` 训练 loss / assigner 可以在 core 内部把距离分布 decode 成 `xyxy` 参与 IoU、TAL assigner 和 bbox loss。该训练内部 `xyxy` 不改变 inference raw output 的 `xywh` 语义。
- `YOLO26` detection / segmentation / pose 默认按 end2end processed layout 使用 `xyxy` box 和 top-k 输出；export 后端、OpenVINO、TensorRT 和 deployment runtime 必须按 processed layout 解析，不能回退到普通 YOLO NMS raw 语义。该 `xyxy` 只是 detection box 或 segmentation / pose 的实例外接框来源，不替代 mask 或 keypoints。
- `YOLO26 OBB` 和 `YOLOv8 / YOLO11 OBB` 保留 rotated box 的 `xywhr` 语义。公开结果的主字段必须是 OBB 专用的 `bbox_xywhr` 或 polygon；`bbox_xyxy` 只作为普通显示和流程节点的外接矩形辅助字段。
- `YOLOX` 保持参考实现输出和左上角 padding 反算规则；平台公开 detection record 仍输出原图 `bbox_xyxy`。
- `RF-DETR` 保持参考实现的固定 resize / normalized box 处理；detection 公开原图 detection box，segmentation 公开 mask / polygon / instance result，并可附带辅助外接框。

这些转换只是在坐标系之间做线性映射或格式重排，不应引入显著精度损失；允许的误差主要来自 float32、NMS 阈值和最终 payload / 显示层的 round。若 mAP 或显示框异常，优先检查同一模型的训练、验证、导出和 runtime 是否共享同一套预处理、box format 和坐标反算规则。

## 2026-06-26 评估默认阈值复核

本轮针对训练中 `map50 / map50_95` 异常偏低的问题，重新核对了 `projectsrc/YOLOX_2026/yolox`、`projectsrc/ultralytics/ultralytics` 和本项目 evaluation / training / frontend 参数链路。结论如下：

- `YOLOX detection` 保持 YOLOX 原生默认：`score_threshold=0.01`、`nms_threshold=0.65`。
- `YOLOv8 / YOLO11 / YOLO26` 的普通 `detection / segmentation / pose` validation 默认按 Ultralytics validator：`score_threshold=0.001`、`nms_threshold=0.7`。
- `YOLOv8 / YOLO11 / YOLO26` 的 `OBB` validation 默认按 Ultralytics validator 的 OBB 分支：`score_threshold=0.01`、`nms_threshold=0.7`。
- `RF-DETR` 和通用 fallback evaluator 不能套普通 YOLO 阈值。RF-DETR 参考实现 predict 默认 `threshold=0.5`，本项目通用 evaluator 的 `0.01 / 0.65` 只作为非普通 YOLO fallback，不作为 YOLOv8 / YOLO11 / YOLO26 的 validation 默认。
- 前端训练参数、API schema、训练入口和独立 evaluation task service 必须保持同一套默认值；旧任务不会被追溯修改，需要在服务和 worker 重启后重新提交训练或 evaluation。

## 2026-06-30 普通 YOLO 训练输入流水线复核

本轮针对 YOLO11 detection 真实训练时 GPU 利用率和显存占用呈周期波动的问题，重新核对了 `projectsrc/ultralytics/ultralytics` 的 `Trainer`、`YOLODataset`、`InfiniteDataLoader`、`preprocess_batch`、`ModelEMA` 和 validator 执行边界。当前结论如下：

- 本项目不直接复制 `projectsrc/ultralytics/ultralytics` 作为运行时代码。参考仓库只作为行为核对来源，项目内仍按 `yolov8_core / yolo11_core / yolo26_core` 的分层边界重新实现，避免后续商业版本产生授权和维护风险。
- 普通 YOLO 的 `detection / classification / segmentation / pose / obb` 训练当前已经修正 CPU tensor 到 CUDA 设备的搬运方式：batch tensor 统一在 batch 维度 stack 后再搬到训练设备，CUDA 训练使用 pinned memory 和 non-blocking transfer，避免每个 sample 单独阻塞式 `.to(device)` 造成额外同步。
- 这次修复只处理数据搬运阻塞问题，不改变模型结构、loss、assigner、target、坐标格式、数据增强语义或公开输出 schema。
- `YOLOv8 / YOLO11 / YOLO26 detection` 已建立正式 PyTorch Dataset / DataLoader 入口。训练 batch、validation loss 和 COCO mAP batch 已使用各自 core 的 collate、中心 LetterBox、target 构建和主进程设备搬运规则，不再由训练 epoch loop 直接同步拼 batch。
- 三代普通 YOLO detection 的 DataLoader 已支持 `num_workers / prefetch_factor / pin_memory / persistent_workers`。当前默认仍保持 `num_workers=0`，避免突然改变所有开发机和现场环境的训练行为；真实训练确认稳定后，再决定是否提高默认 worker 数。
- 三代普通 YOLO detection 的 EMA 更新位置继续保持在 `optimizer.step()` 之后，validation 和 checkpoint 仍由当前 single-GPU trainer 执行，行为不引入 DDP 或 DataParallel。
- 当前仍需继续对齐的核心差距是 `InfiniteDataLoader` 风格的长期 iterator 复用，以及 `classification / segmentation / pose / obb` 的 task-specific DataLoader、target 同步和 validator 汇总。非 detection 任务不能直接套 detection DataLoader，必须分别处理分类标签、mask、keypoint 和 rotated box 的几何同步。

## 残留关键词分类

本轮使用下面的范围扫描了 `primary / legacy / minimal / compat / lightweight / stub / NotImplemented / 过渡 / 旧 / 兼容 / 轻量`：

```powershell
rg -n "primary|legacy|minimal|compat|lightweight|stub|TODO|NotImplemented|过渡|旧|兼容|轻量" backend/service/application/models backend/service/application/runtime backend/workers custom_nodes tests docs/architecture docs/api -g "*.py" -g "*.md"
```

扫描结果分为以下类别处理。关键词本身不是删除依据，必须先判断它属于权重/字段兼容、普通变量/文档描述，还是确实需要后续重构。

### 已完成第一批入口收口

这些入口已经从 `yolo_primary` 收成更直白的 YOLO 主线命名，后续不再使用旧文件名。

- `backend/workers/training/yolo_primary_training_queue_worker.py` 已改为 `backend/workers/training/yolo_training_queue_worker.py`
- `backend/workers/training/yolo_primary_trainer_runner.py` 已改为 `backend/workers/training/yolo_training_runner.py`
- `backend/workers/evaluation/yolo_primary_evaluation_queue_worker.py` 已改为 `backend/workers/evaluation/model_evaluation_queue_worker.py`
- classification 训练与 evaluation 已收成 `yolov8_classification_*`，YOLO11 / YOLO26 classification 使用各自专属 service。
- pose / OBB 训练已收成 `yolov8_pose_*`、`yolov8_obb_*`，YOLO11 / YOLO26 pose / OBB 使用各自专属 service。
- segmentation 训练与 evaluation 已收成中性 `segmentation_training_*` 和 `segmentation_evaluation*`，只保留 YOLOv8 与 RF-DETR 的共享任务状态、队列、对象存储和登记分发。
- 普通 YOLO non-detection 训练 worker 已收成 `backend/workers/training/yolo_training_queue_worker.py`，执行器已收成 `backend/workers/training/yolo_training_runner.py`。
- 普通 YOLO 模型构建入口已收成 `build_yolo_model` / `get_yolo_model_config`，evaluation runtime resolver 已收成 `get_yolo_evaluation_runtime_target_resolver`。
- `tests/integration/yolo_primary_full_chain_smoke.py` 已改为 `tests/integration/yolo_model_full_chain_smoke.py`
- `tests/integration/yolov8_full_chain_smoke.py` 已删除，YOLOv8 真实短链路统一通过 `tests.integration.yolo_model_full_chain_smoke --model-type yolov8` 执行

### 已清理的过渡入口

这些命名和入口曾经会让后续误以为还存在一条通用 `YOLO primary` 模型线，现在已经改成中性共享层或迁回各自 core。

- 旧共享 detection 训练入口已删除。YOLOv8 detection 训练执行已下沉到 `backend/service/application/models/yolov8_core/training/detection_execution.py`，应用层只保留 `yolov8_detection_training.py` 入口。
- YOLO11 / YOLO26 detection 已使用各自专属训练入口，不再走共享 detection 训练文件。
- 文档历史记录中仍会出现已经删除的 `yolo_primary` 旧路径，但不能作为当前实现边界或新代码模板

处理规则：

- 如果是真共享能力，改成 `yolo_*`、`model_task_*` 或更具体的任务层命名，避免再使用会被误读为过渡层的旧 task 前缀。
- 如果是 YOLOv8、YOLO11、YOLO26 某一代专属能力，迁回对应 `*_core` 或对应 service helper。
- 如果只是旧兼容入口，删除，不保留长期壳。

### 不能按关键词直接删除的兼容点

以下命名虽然包含 `legacy` 或 `compat`，但可能是读取真实权重或匹配参考实现所需，不能盲删。

- `legacy_class_head`：YOLO head 的结构行为标记，必须和参考实现及 checkpoint 形态对应。
- checkpoint 反序列化里的旧模块路径映射：用于读取真实预训练权重，不等于旧业务路径。
- RF-DETR 的 `legacy_checkpoint_format`、`legacy_ema_state_dict`：用于读取历史 RF-DETR checkpoint 和 EMA 权重，不等于旧平台入口。
- `legacy_labels_json_object_key`：训练输出文件登记时保留的旧对象键，用于已有输出文件位置兼容，不参与模型结构、训练行为或新目录规划。
- `NotImplementedError` 在抽象基类、必须由子类实现的 runtime service 中可以保留。
- `primary_sample`、`primary_metrics` 这类普通变量名不是架构残留，不需要强行改。
- node pack manifest、API 文档和 workflow 清理里的 `compatibility` 字段是公开协议字段，不属于模型 full core 残留。

处理规则：

- 只保留技术上必要的兼容点。
- 保留时必须写清楚为什么存在、对应什么 checkpoint 或参考实现行为。
- 不能把兼容点扩散成新的业务入口。

### 普通变量名或文档描述

以下残留不表示模型实现仍是轻量或旧入口，不能因为命中关键词就重构。

- 测试文件里的“轻量 fake worker”“轻量 smoke”“轻量摘要”：描述测试或业务摘要的规模，不是模型轻量实现。
- `primary_sample`、`primary_metrics`：表示主样本、主指标等局部变量语义，不是 `yolo_primary_*` 旧入口。
- `NotImplementedError`：抽象接口的强制实现边界。
- YOLO11 `PSA` 注释里的“轻量多头注意力”：描述模块设计特征，不表示项目采用轻量近似模型。

### 需要后续重构或审计的问题

以下不是本轮模型主线短链路阻塞，但进入第五批 custom nodes 前必须单独处理。

- `custom_nodes/yoloe_open_vocab_nodes/backend/runtime/prompt_free.py`、`text_prompt.py`、`visual_prompt.py`：已接收 YOLOE project-native runtime session class 和推理调用编排，nodes 层不再保存 `_project_native_runtime.py`。
- `custom_nodes/sam3_segment_nodes/backend/runtime/access.py`：已接收 SAM3 custom node 侧 runtime cache key 与 session 获取，nodes 层不再保存 `_project_native_runtime.py`。
- 训练 service 中保留的 `legacy_labels_json_object_key` 后续可考虑改成更直白的内部字段名，但前提是不破坏已有输出文件记录；它不是当前 full core 行为差距。

### YOLOE / SAM3 审计记录

以下 custom model node 不能在第五批前继续扩展功能，必须先按模型主链路稳定后的边界重新审计。当前结论是：它们不是空壳，也不是完全没实现；真正的问题是部分模型结构、runtime session、payload 解析、prompt 处理和节点 adapter 还没有完全按最新边界收口，后续会让第五批 custom nodes 继续依赖旧边界。

#### YOLOE open vocab nodes

当前主要实现位置：

- `custom_nodes/yoloe_open_vocab_nodes/backend/runtime/prompt_free.py`：包含 prompt-free runtime session 和推理调用编排。
- `custom_nodes/yoloe_open_vocab_nodes/backend/runtime/text_prompt.py`：包含 text-prompt runtime session 和推理调用编排。
- `custom_nodes/yoloe_open_vocab_nodes/backend/runtime/visual_prompt.py`：包含 visual-prompt runtime session 和推理调用编排。
- `custom_nodes/yoloe_open_vocab_nodes/backend/runtime/access.py`：包含节点侧获取 runtime session 的调用入口。
- `custom_nodes/yoloe_open_vocab_nodes/backend/core/prompts/text.py`：约 55 行，包含 text prompt 特征聚合和结果追溯文本构造。
- `custom_nodes/yoloe_open_vocab_nodes/backend/core/prompts/visual_embeddings.py`：约 59 行，包含 visual prompt embedding 提取和带 class embedding 的前向检查。
- `custom_nodes/yoloe_open_vocab_nodes/backend/core/nn/modules.py`：约 558 行，包含 YOLOE 基础 nn 模块、DFL decode、Proto、SAVPE 和文本适配模块。
- `custom_nodes/yoloe_open_vocab_nodes/backend/core/nn/models.py`：约 937 行，包含 prompt-free / text-prompt segmentation head、模型 parser 和模型构建入口。
- `custom_nodes/yoloe_open_vocab_nodes/backend/core/weights/checkpoint.py`：约 269 行，包含 prompt-free checkpoint artifact loader 和受控 checkpoint 反序列化桥。
- `custom_nodes/yoloe_open_vocab_nodes/backend/payloads/`：包含 payload 类型、图片和 prompt 解析、预训练权重定位、参数归一化、summary / result / regions payload 组装。
- 节点 adapter 分散在 `prompt_free_detect.py`、`text_prompt_detect.py`、`visual_prompt_detect.py`。

当前混装内容：

- 模型结构已下沉到 `core/nn/modules.py` 和 `core/nn/models.py`，不再和 runtime session 混在同一文件。
- 权重读取和 checkpoint 兼容已下沉到 `core/weights/checkpoint.py`。其中 `compat` class 是真实 checkpoint 反序列化所需的受控桥接，不是旧业务入口。
- prompt 和 embedding 已拆出第一层：visual prompt mask 构建在 `core/prompts/visual.py`，text prompt grouped feature 在 `core/prompts/text.py`，visual embedding 提取在 `core/prompts/visual_embeddings.py`。
- postprocess 已下沉到 `core/postprocess/segmentation.py`，包含 bbox decode、mask decode、polygon 提取、mask PNG 编码和 regions payload 组装。
- runtime session cache 已下沉到 `runtime/sessions.py`，runtime session class 已按 prompt-free / text / visual 下沉到 `runtime/prompt_free.py`、`runtime/text_prompt.py`、`runtime/visual_prompt.py`，节点获取 session 的调用层已下沉到 `runtime/access.py`。
- payload 解析、prompt 读取、summary/result 组装已下沉到 `payloads/`，节点 adapter 不再从 `_common.py` 读取这些 helper。

第一阶段目标结构：

```text
custom_nodes/yoloe_open_vocab_nodes/backend/
├─ core/
│  ├─ nn/
│  ├─ weights/
│  ├─ prompts/
│  └─ postprocess/
├─ runtime/
│  ├─ access.py
│  ├─ prompt_free.py
│  ├─ sessions.py
│  ├─ text_prompt.py
│  ├─ types.py
│  └─ visual_prompt.py
├─ payloads/
│  ├─ inputs.py
│  ├─ pretrained.py
│  ├─ results.py
│  └─ types.py
└─ nodes/
   ├─ prompt_free_detect.py
   ├─ text_prompt_detect.py
   └─ visual_prompt_detect.py
```

处理规则：

- node_type_id 不改，workflow 示例和 Postman 不因为内部重构改变公开节点名。
- `legacy` / `compat` 命名不能按关键词盲删。YOLOE checkpoint 里的旧类名、旧 head 形态和真实权重映射如果仍需要读取现有预训练文件，应保留为 `weights` 层的受控兼容逻辑，并写清楚对应权重来源。
- `projectsrc` 不能作为运行时依赖来源；如果文档或错误信息仍提到参考目录，只能作为开发参考说明。
- 节点 adapter 只保留参数读取、调用 runtime 和返回 payload，不再新增 `_common.py` 这类混合入口。

2026-06-24 第一批收口：

- `prompt-free / text-prompt / visual-prompt` 共用的 segmentation 输出过滤、NMS、mask decode、polygon 和 mask PNG 编码已移入 `custom_nodes/yoloe_open_vocab_nodes/backend/core/postprocess/segmentation.py`。
- visual prompt mask / tensor 构建已移入 `custom_nodes/yoloe_open_vocab_nodes/backend/core/prompts/visual.py`，测试不再直接引用 `_project_native_runtime.py` 的私有函数。
- runtime session cache 已移入 `custom_nodes/yoloe_open_vocab_nodes/backend/runtime/sessions.py`，`_common.py` 不再从模型大文件直接拿 session cache。
- `_project_native_runtime.py` 从约 2813 行降到约 2406 行，仍保留模型结构、checkpoint 兼容、模型 parser、runtime session 类和 visual embedding 提取，下一批继续按 `nn / weights / runtime session class` 分层下沉。

2026-06-24 第二批收口：

- prompt-free checkpoint artifact loader、输入尺寸读取、class name 解析和 state_dict 读取已移入 `custom_nodes/yoloe_open_vocab_nodes/backend/core/weights/checkpoint.py`。
- `_CheckpointCompat*` class 和 `_temporary_checkpoint_class_aliases` 保留在 `core/weights/checkpoint.py`。这些名称服务于真实 YOLOE checkpoint 反序列化，不能按 `compat` 关键词盲删。
- `YoloeConv`、`YoloeC2f`、`YoloeC3k2`、`YoloeC2PSA`、`YoloeSPPF`、`YoloeDistributionFocalLossDecoder`、`YoloeProto`、`YoloeProto26`、`YoloeSpatialAwareVisualPromptEmbedding`、`YoloeBatchNormContrastiveHead` 和文本适配模块已移入 `core/nn/modules.py`。
- `YoloePromptFreeSegmentationHead`、`YoloeTextPromptSegmentationHead`、`YoloePromptFreeSegmentationModel`、`YoloeTextPromptSegmentationModel`、模型 parser 和模型 build 函数已移入 `core/nn/models.py`。
- `_project_native_runtime.py` 从约 2406 行降到约 740 行，当前只保留 4 个 class / 13 个 function；后续继续拆 runtime session class、text prompt feature 聚合和 visual embedding helper。

2026-06-24 第三批收口：

- `custom_nodes/yoloe_open_vocab_nodes/backend/nodes/_project_native_runtime.py` 已拆到 `custom_nodes/yoloe_open_vocab_nodes/backend/runtime/` 下的正式 session 文件，nodes 层不再保存 project-native runtime session class。
- `runtime/sessions.py` 现在直接从 `runtime/prompt_free.py`、`runtime/text_prompt.py`、`runtime/visual_prompt.py` 加载 session，断开 runtime 对 nodes 层的反向依赖。
- text prompt grouped feature 和 source prompt text 构造已移入 `core/prompts/text.py`。
- visual prompt embedding 提取和带 class embedding 的前向输出检查已移入 `core/prompts/visual_embeddings.py`。
- `runtime/project_native.py` 已删除，runtime session class 和推理调用编排已按 prompt-free / text / visual 分文件。

2026-06-24 第四批收口：

- YOLOE 的旧 `custom_nodes/yoloe_open_vocab_nodes/backend/nodes/_common.py` 已删除，不再保留 re-export 壳。
- payload 类型已进入 `payloads/types.py`，图片读取、文本提示解析、视觉提示解析和 text prompt 聚合已进入 `payloads/inputs.py`。
- 预训练 manifest 定位、模型系列 / scale / device / precision / 阈值参数归一化和 NotImplemented 错误构造已进入 `payloads/pretrained.py`。
- detection items、region items、summary、prompt-free / text / visual 输出 payload 和 workflow regions payload 已进入 `payloads/results.py`。
- 节点获取 runtime session 的调用层已进入 `runtime/access.py`；三个 node adapter 现在直接调用 `payloads/` 和 `runtime/access.py`，不再依赖 `_common.py`。

2026-06-24 第五批内部收口：

- `runtime/project_native.py` 已删除，不再作为三类 session 的混装大文件。
- `ProjectNativeYoloePrediction` 已进入 `runtime/types.py`。
- prompt-free、text-prompt、visual-prompt 三条 project-native session 已分别进入 `runtime/prompt_free.py`、`runtime/text_prompt.py`、`runtime/visual_prompt.py`。
- `runtime/sessions.py` 现在直接按 session 类型导入正式文件，不再通过 `project_native.py` 聚合。
- checkpoint / 模型加载公共逻辑已进入 `runtime/model_loading.py`，受控 checkpoint 兼容仍留在 `core/weights/checkpoint.py`。
- device / precision / CUDA fast path 准备逻辑已进入 `runtime/environment.py`，图片 decode / preprocess / tensor 构造已进入 `runtime/preprocess.py`。
- 已复跑 YOLOE 节点和 workflow 使用面：`tests/test_import_smoke.py tests/test_yoloe_prompt_free_node.py tests/test_yoloe_text_prompt_node.py tests/test_yoloe_visual_prompt_node.py tests/test_yoloe_sam3_stability.py -q` 为 `815 passed`；新增 prompt-free / visual-prompt WorkflowAppRuntime smoke 后，`tests/integration/test_yoloe_sam3_workflow_app_runtime_smoke.py -q` 为 `5 passed`。

#### SAM3 segment nodes

当前主要实现位置：

- `custom_nodes/sam3_segment_nodes/backend/core/`：SAM3 custom node 私有 core，包含 checkpoint、image preprocess、interactive model、semantic model、prompt encoding、mask postprocess、video memory tracker、vision backbone 等模型支撑文件；旧 backend shared 支撑目录已迁入这里，不再作为平台 shared support。
- `custom_nodes/sam3_segment_nodes/backend/runtime/access.py`：负责 custom node 侧 runtime cache key 与 session 获取；旧 `nodes/_project_native_runtime.py` 已删除。
- `custom_nodes/sam3_segment_nodes/backend/runtime/tracking.py`：包含 video-interactive tracking mode、参数解析、跨帧 prompt 传播、memory / attention track state 更新和 tracking summary 构造。
- `custom_nodes/sam3_segment_nodes/backend/payloads/types.py`：包含 text / interactive prompt、frame window 和预训练 variant 的 payload 类型。
- `custom_nodes/sam3_segment_nodes/backend/payloads/pretrained.py`：包含 SAM3 预训练 manifest 定位、scale / device / precision 规范化和受控未实现错误。
- `custom_nodes/sam3_segment_nodes/backend/payloads/inputs.py`：包含 text / interactive prompt 解析、frame window 读取、图片读取、polygon / mask prompt 处理。
- `custom_nodes/sam3_segment_nodes/backend/payloads/results.py`：包含 regions、tracks、summary 和 source image 摘要 payload 组装。
- 旧 `custom_nodes/sam3_segment_nodes/backend/nodes/_common.py` 已删除，不再保留 re-export 壳。
- `custom_nodes/sam3_segment_nodes/backend/nodes/video_interactive_segment.py`：只保留 frame/prompt 读取、runtime session 调用、逐帧推理和 payload 返回；tracking 细节已迁到 `runtime/tracking.py`。

当前边界判断：

- SAM3 的模型支撑已经明确为 custom node 私有 core，不进入 `backend/nodes` 平台 shared support，也不作为主模型服务 core 对外暴露。
- custom node 侧 runtime session cache 已进入 `runtime/access.py`，不再放在 nodes 目录。
- custom node 侧 payload 类型、prompt / frame window 输入读取、pretrained manifest 和 result / summary 构造已进入 `payloads/`，节点 adapter 不再依赖 `_common.py`。
- video-interactive tracking 参数解析、prompt propagation、memory / attention state 更新和 tracking summary 已进入 `runtime/tracking.py`，节点 adapter 不再直接持有这批逻辑。

第一阶段目标结构：

```text
custom_nodes/sam3_segment_nodes/backend/
├─ core/
│  ├─ checkpoint/
│  ├─ nn/
│  ├─ prompts/
│  ├─ postprocess/
│  └─ tracking/
├─ runtime/
│  ├─ access.py
│  └─ tracking.py
├─ payloads/
│  ├─ inputs.py
│  ├─ pretrained.py
│  ├─ results.py
│  └─ types.py
└─ nodes/
   ├─ interactive_segment.py
   ├─ semantic_segment.py
   ├─ video_interactive_segment.py
   └─ video_semantic_segment.py
```

处理规则：

- `custom_nodes/sam3_segment_nodes/backend/core/` 是 SAM3 custom node 私有模型支撑层；平台内建节点和其他 custom node 不直接依赖该目录。
- 如果未来平台核心需要复用 SAM3 能力，必须另立公开模型服务或显式 shared support 设计，不能反向依赖 custom node 私有 core。
- `NotImplementedError` 只允许出现在明确不支持的模型缩放、抽象接口或受控错误路径里，不能作为功能占位。
- `fallback` 只能用于后处理小区域过滤、参数默认值这类受控路径，不能作为模型结构或 checkpoint 缺失的静默降级。

#### 验证要求

YOLOE / SAM3 重构后必须至少复跑：

- YOLOE prompt-free、text prompt、visual prompt workflow 节点调用。
- SAM3 interactive、semantic、video interactive、video semantic workflow 节点调用。
- 现有 `tests/test_yoloe_*`、`tests/test_sam3_*`、workflow app runtime 相关测试。
- 如果涉及 runtime session 或 checkpoint 读取，还需要补一次真实预训练模型加载 smoke。

### 文档里的泛用兼容词

API 文档里的“向后兼容字段”“轻量详情”“旧 session 数据回退”等不全部属于模型 full core 问题。只有涉及模型训练、转换、runtime、workflow 的旧入口才纳入本清单。

## 逐模型审计表

### RF-DETR

| 项 | 当前判断 |
| --- | --- |
| 参考目录 | `projectsrc/rf-detr/src/rfdetr` |
| 当前 core | `backend/service/application/models/rfdetr_core` |
| 任务范围 | detection、segmentation |
| 状态 | `短链路已记录`，长时间训练、更长 soak、资源占用和异常恢复基线另跑 |
| 已有基础 | `models`、`datasets`、`training`、`evaluation`、`export`、`utilities` 已进入 core |
| 明确缺口 | `deploy`、`platform`、部分 CLI 能力没有完整映射；如果不纳入平台 core，必须写明不支持或迁移到 service / runtime。`supervision_compat` 是项目内替代 `supervision` 的受控子集，已覆盖当前 `datasets / export / visualize` 调用，不等同于完整 `supervision` 包。 |
| 风险点 | LoRA / PEFT 当前未启用；早期 checkpoint 转换保留 `legacy_checkpoint_format / legacy_ema_state_dict` 是读取 RF-DETR 旧训练产物所需，不属于旧平台入口；长时训练和更长 release/full 常驻 soak 仍需要单独记录 |
| 下一步 | 长时间训练、更长 release/full 常驻 soak、资源占用和异常恢复基线单独跑，不放默认测试 |

### YOLOX

| 项 | 当前判断 |
| --- | --- |
| 参考目录 | `projectsrc/YOLOX_2026/yolox` |
| 当前 core | `backend/service/application/models/yolox_core` |
| 任务范围 | detection |
| 状态 | `短链路已记录`，COCO / VOC 短链路已记录，长时间训练和更长 soak 另跑 |
| 已有基础 | `cfg`、`data`、`evaluators`、`export`、`models`、`postprocess`、`training`、`utils` 已进入 core |
| 明确缺口 | `TrainTransform / ValTransform / MosaicDetection / MixUp / random affine / HSV / EMA / yoloxwarmcos scheduler` 已进入 core；半监督 `yoloxsemiwarmcos` 不在当前平台训练范围内，需要明示为不支持。VOC DatasetExport 已接入 `voc-python` 原生 AP 评估，不再通过 COCO-style ground truth 替代 VOC evaluation。 |
| 风险点 | COCO / VOC 训练评估要各自记录真实短链路；如果现场要求 VOC 2007 11 点 AP 口径，需要通过评估参数显式开启 `use_07_metric`，不能和默认 0.5:0.95 AP 口径混用 |
| 下一步 | 长时间训练、更长 release/full 常驻 soak、资源占用和异常恢复基线单独跑 |

### YOLOv8

| 项 | 当前判断 |
| --- | --- |
| 参考目录 | `projectsrc/ultralytics/ultralytics` |
| 当前 core | `backend/service/application/models/yolov8_core` |
| 任务范围 | detection、classification、segmentation、pose、obb |
| 状态 | `短链路已记录`，五任务短链路已记录，指标口径和更长 soak 继续单独收 |
| 已有基础 | cfg、nn、losses、assigners、targets、data、training、evaluation、export、postprocess、inference 已成目录 |
| 明确缺口 | `yolo_core_common/primary` 已删除；`yolo_primary` 和旧 task 前缀命名的 worker、training、evaluation、catalog 和测试入口已收口；YOLOv8 detection 执行编排已进入 `yolov8_core/training/detection_execution.py` |
| 风险点 | segmentation mask AP、pose OKS、OBB rotated AP 当前是项目内 COCO-style AP 实现，不等同于 Ultralytics 完整 `SegmentationValidator / PoseValidator / OBBValidator` 及 pycocotools / 专用 rotated evaluator 的全部输出口径；全 scale checkpoint 和更长 release/full soak 仍需单独记录 |
| 2026-06-24 复核 | 已对照 Ultralytics 普通 YOLO `Detect / Segment / Pose / OBB` export 行为修正 YOLOv8 detection、segmentation、pose、OBB 的 export forward：export 使用 `[B, C, N]` channel-first 布局；runtime/postprocess 入口统一转为平台内部 `[B, N, C]` 消费。非 export PyTorch runtime 仍保留平台现有 decoded tensor 入口，不把 raw head 输出误传给部署服务。 |
| 下一步 | 继续核对 v8 loss / assigner / data augmentation；长时间训练、更长 release/full 常驻 soak、资源占用和异常恢复基线单独跑 |

### YOLO11

| 项 | 当前判断 |
| --- | --- |
| 参考目录 | `projectsrc/ultralytics/ultralytics` |
| 当前 core | `backend/service/application/models/yolo11_core` |
| 任务范围 | detection、classification、segmentation、pose、obb |
| 状态 | `短链路已记录`，五任务短链路已记录，后续补更长 soak 和全 scale checkpoint |
| 已有基础 | YOLO11 专属 cfg、nn、loss、data、training、evaluation、export、runtime backend 目录已建立 |
| 明确缺口 | non-detection service / worker / evaluation 命名已收成 YOLOv8 专属、YOLO11/YOLO26 专属或中性 segmentation 命名；`yolo_core_common/primary` 已删除；YOLOv8 / YOLO11 / YOLO26 detection 均已切到各自专属训练入口 |
| 风险点 | YOLO11 与 YOLOv8 结构相近，但不能直接复用 YOLOv8 core；只允许依赖 `yolo_core_common` 的底层能力 |
| 2026-06-24 复核 | 已对照 Ultralytics 普通 YOLO `Detect / Segment / Pose / OBB` export 行为修正 YOLO11 pose、OBB 的 export forward，并确认 detection、segmentation 已保持 `[B, C, N]` channel-first export；runtime/postprocess 入口统一转为平台内部 `[B, N, C]` 消费。 |
| 下一步 | 继续补全 scale checkpoint、更长 release/full 常驻 soak、资源占用和异常恢复基线 |

### YOLO26

| 项 | 当前判断 |
| --- | --- |
| 参考目录 | `projectsrc/ultralytics/ultralytics` |
| 当前 core | `backend/service/application/models/yolo26_core` |
| 任务范围 | detection、classification、segmentation、pose、obb |
| 状态 | `短链路已记录`，processed layout 已用真实转换产物复验，长时间 soak 另跑 |
| 已有基础 | YOLO26 专属 cfg、nn、decode、loss、data、training、evaluation、export、postprocess、runtime backend 已建立 |
| 本轮修复 | 已对照 `Detect26 / Segment26 / Pose26 / OBB26` 修正 end2end forward/export 语义：训练态保留 raw head 输出，推理非 export 返回 processed + raw，export 返回 processed；detection processed 输出为 `[x1, y1, x2, y2, score, class]`，segmentation / pose 在相同前 6 列后追加 mask coeff 或 keypoints，OBB 输出为 `[x, y, w, h, score, class, angle]`。同时修复 `Segment26` 的 `Proto26 npr` 参数传递，并为 YOLO26 PyTorch runtime 增加 detection / segmentation 输出适配。2026-06-24 又修复 segmentation 训练期 evaluation 对 `((processed, proto), raw)` nested output 的解包，避免把 processed/raw 双输出误当成普通数组。 |
| 风险点 | YOLO26 默认 end2end 行为与 YOLOv8 / YOLO11 不同；不能回落到旧 NMS 或旧 primary postprocess |
| 复验结果 | 2026-06-24 已用真实转换产物复跑 ONNX / OpenVINO / TensorRT conversion 与 deployment sync / async smoke。detection / classification 结果目录：`.tmp/yolo-model-full-chain-smoke/yolo26-processed-layout-smoke-20260624-r2/result.json`；segmentation / pose / OBB 结果目录：`.tmp/yolo-model-full-chain-smoke/yolo26-processed-layout-smoke-20260624-r3/result.json`。三种 runtime backend 均按 processed layout 正常解析。 |

## full core 核对项

每个模型、每个 task 都按下面项目逐项检查，不能只看“能训练一次”。

| 核对项 | 必须确认 |
| --- | --- |
| cfg | scale、depth、width、input size、task 默认参数和参考配置一致 |
| nn/modules | backbone、neck、block、head、stride、bias init、export mode 和参考实现一致 |
| heads | Detect / Segment / Classify / Pose / OBB 专属 head 不混用 |
| loss | box、class、DFL、mask、keypoint、angle、rotated box 等 loss 与参考实现一致或明确差异 |
| assigner | TAL、anchor、候选筛选、top-k、tiny box / rbox 过滤与参考实现一致 |
| target | bbox、mask、keypoint、OBB target 编码和数据增强同步变换正确 |
| data augmentation | HSV、flip、random affine、perspective、mosaic、mixup、multi-scale、close-mosaic/no-aug schedule 按任务实现 |
| training loop | optimizer、scheduler、EMA、AMP、resume、checkpoint、best metric、pause/resume、manual save 清晰 |
| validation | validation session 和训练期 validation 的输入、runtime backend、输出指标一致 |
| evaluation | 数据集级评估按 task 输出明确指标，过渡指标必须标明 |
| export | ONNX / OpenVINO / TensorRT 的 forward 边界、输出名、dynamic shape、processed/raw layout 明确 |
| postprocess | raw output 和 export processed output 分开，NMS / TopK / mask / pose / OBB 处理不混线 |
| weights | state_dict 覆盖率、pickle checkpoint、旧模块路径映射、shape mismatch 处理可追溯 |
| runtime | PyTorch / ONNXRuntime / OpenVINO / TensorRT session 只放 runtime，模型语义调用 core |
| deployment | sync / async / warmup / reset / stop / health / 独立进程资源释放都要验收 |
| workflow | workflow service node 调用必须使用最新 deployment / inference API，不依赖旧 predictor |

## 真实全链路验收范围

验收前不启动第五批 custom nodes。

### RF-DETR

- detection
- segmentation

### YOLOX

- detection，COCO DatasetExport
- detection，VOC DatasetExport

### YOLOv8 / YOLO11 / YOLO26

- detection
- classification
- segmentation
- pose
- obb

### 每条链必须执行

每条链固定执行以下步骤：

1. DatasetImport
2. DatasetExport
3. 短训练，默认控制在十分钟以内
4. 验证和数据集级评估
5. ONNX 转换
6. OpenVINO 转换
7. TensorRT 转换
8. deployment sync 推理
9. deployment async 推理
10. stop / reset
11. workflow 调用

### 真实全链路验收记录表

本表只记录已经能追溯到命令、结果目录、测试文件或明确待办的事实。`current-implementation-status.md` 可以保留时间线流水，本表作为模型 full core 验收的总入口。

状态说明：

- `短链路已记录`：已跑通短训练、评估、ONNX / OpenVINO / TensorRT、deployment sync / async、推理和 stop / reset，并写明结果位置；长时间训练和更长 soak 另跑。
- `部分已跑`：已经跑过 checkpoint、转换、runtime backend 或某个 task 子集，但没有覆盖完整链路。
- `待补记录`：实现和历史调试显示可用，但缺少可追踪结果目录或命令记录。
- `待跑`：还没有按本文档要求跑完整链路。
- `不适用`：该模型不支持该 task。

| 模型 | 任务 / 数据集范围 | 导入 / 导出 | 短训练 / 评估 | ONNX / OpenVINO / TensorRT | deployment sync / async / stop-reset | workflow / 前端 | 当前状态 | 记录与下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RF-DETR | detection | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 2026-06-23 已跑真实 DatasetImport / DatasetExport、短训练、评估、ONNX / OpenVINO / TensorRT、deployment sync / async / stop-reset。结果目录：`.tmp/model-full-core-validation/rfdetr-api-onnx-20260623-fix3`、`.tmp/model-full-core-validation/rfdetr-api-openvino-20260623-fix1`、`.tmp/model-full-core-validation/rfdetr-api-tensorrt-20260623`。workflow 结果目录：`.tmp/model-full-core-validation/rfdetr-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| RF-DETR | segmentation | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 2026-06-23 已跑真实 DatasetImport / DatasetExport、短训练、评估、ONNX / OpenVINO / TensorRT、deployment sync / async / stop-reset。结果目录：`.tmp/model-full-core-validation/rfdetr-api-seg-onnx-20260623-fix4`、`.tmp/model-full-core-validation/rfdetr-api-openvino-20260623-fix1`、`.tmp/model-full-core-validation/rfdetr-api-tensorrt-20260623`。workflow 结果目录：`.tmp/model-full-core-validation/rfdetr-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLOX | detection，COCO DatasetExport | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 2026-06-23 已跑真实 DatasetImport / DatasetExport、短训练、评估、ONNX / OpenVINO / TensorRT、deployment sync / async / stop-reset。结果目录：`.tmp/model-full-core-validation/yolox-api-onnx-20260623`、`.tmp/model-full-core-validation/yolox-api-openvino-20260623`、`.tmp/model-full-core-validation/yolox-api-tensorrt-20260623`。workflow 结果目录：`.tmp/model-full-core-validation/yolox-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLOX | detection，VOC DatasetExport | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 2026-06-23 已跑真实 DatasetImport / DatasetExport、短训练、VOC DatasetExport 原生评估入口、ONNX / OpenVINO / TensorRT、deployment sync / async / stop-reset。结果目录同 COCO 行；workflow 结果目录：`.tmp/model-full-core-validation/yolox-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLOv8 | detection | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 2026-06-23 已跑真实 DatasetImport / DatasetExport、短训练、评估、ONNX / OpenVINO / TensorRT、deployment sync / async / stop-reset。结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-api-full-chain-20260623`。该 run 后续因 segmentation ONNX 校验失败整体标记 failed，但 detection 子链路已完整成功；workflow 结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。2026-06-25 已补代表性真实链路复验：`tests.integration.yolo_model_full_chain_smoke --model-type yolov8 --tasks detection --target-formats onnx --max-epochs 1 --batch-size 1 --max-images-per-split 2 --start-processes --run-workflow`，结果目录：`.tmp/yolo-model-full-chain-smoke/codex-yolov8-detection-acceptance/result.json`；本轮覆盖真实 DatasetImport / DatasetExport、短训练、评估、ONNX conversion、ONNXRuntime deployment sync / async、workflow invoke 和 stop/reset。 |
| YOLOv8 | classification | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 2026-06-23 已跑真实 DatasetImport / DatasetExport、短训练、评估、ONNX / OpenVINO / TensorRT、deployment sync / async / stop-reset。结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-api-full-chain-20260623`。该 run 后续因 segmentation ONNX 校验失败整体标记 failed，但 classification 子链路已完整成功；workflow 结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLOv8 | segmentation | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 2026-06-23 修复 YOLOv8 ONNX 数值校验输入和 mean-ratio accepted 摘要后，已跑真实 DatasetImport / DatasetExport、短训练、评估、ONNX / OpenVINO / TensorRT、deployment sync / async / stop-reset。结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-segmentation-full-chain-20260623-fix1`；workflow 结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLOv8 | pose | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 2026-06-23 已跑真实 DatasetImport / DatasetExport、短训练、评估、ONNX / OpenVINO / TensorRT、deployment sync / async / stop-reset。结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-pose-obb-full-chain-20260623-fix1`；workflow 结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLOv8 | obb | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 2026-06-23 已跑真实 DatasetImport / DatasetExport、短训练、评估、ONNX / OpenVINO / TensorRT、deployment sync / async / stop-reset。结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-pose-obb-full-chain-20260623-fix1`；workflow 结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO11 | detection | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 2026-06-20 已跑 `tests.integration.yolo_model_full_chain_smoke --model-type yolo11 --tasks detection classification segmentation pose obb --target-formats onnx openvino-ir tensorrt-engine --max-epochs 1 --batch-size 1 --max-images-per-split 4 --start-processes`，结果在 `.tmp/yolo-model-full-chain-smoke/20260620110947/result.json`。workflow 结果目录：`.tmp/yolo-model-full-chain-smoke/yolo11-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO11 | classification | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 同 YOLO11 detection 记录；2026-06-23 另有 classification workflow probe 修复记录，结果使用 `yolo11-classification-workflow-probe-20260623-fix2`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO11 | segmentation | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 同 YOLO11 detection 记录；前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO11 | pose | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 2026-06-19 另有 pose / OBB ONNX 子集记录 `.tmp/yolo11-pose-obb-20260619161813`；完整三格式链路见 2026-06-20 记录，workflow 见 2026-06-23 记录。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO11 | obb | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 同 YOLO11 pose 记录；前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO26 | detection | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 2026-06-24 processed layout 和普通 YOLO export layout 修复后，已跑严格真实转换产物 smoke：真实 DatasetImport / DatasetExport、短训练、评估、ONNX / OpenVINO / TensorRT conversion、deployment sync / async、workflow 调用均成功。结果目录：`.tmp/yolo-model-full-chain-smoke/yolo26-strict-real-artifact-smoke-20260624-r1/result.json`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO26 | classification | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 同 YOLO26 detection 严格真实转换产物 smoke；结果目录：`.tmp/yolo-model-full-chain-smoke/yolo26-strict-real-artifact-smoke-20260624-r1/result.json`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO26 | segmentation | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 同 YOLO26 detection 严格真实转换产物 smoke；已覆盖 `((processed, proto), raw)` 非 export 调试输出与 export processed layout 的 runtime 解析边界。结果目录：`.tmp/yolo-model-full-chain-smoke/yolo26-strict-real-artifact-smoke-20260624-r1/result.json`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO26 | pose | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 同 YOLO26 detection 严格真实转换产物 smoke；结果目录：`.tmp/yolo-model-full-chain-smoke/yolo26-strict-real-artifact-smoke-20260624-r1/result.json`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO26 | obb | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 短链路已记录 | 同 YOLO26 detection 严格真实转换产物 smoke；结果目录：`.tmp/yolo-model-full-chain-smoke/yolo26-strict-real-artifact-smoke-20260624-r1/result.json`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |

当前最小补缺顺序：

1. 模型主线短链路已补齐记录：RF-DETR、YOLOX、YOLOv8、YOLO11、YOLO26 均已有可追溯短链路记录。
2. 如果后续继续修模型 core，必须只复跑受影响模型和 task，不把旧结论继续沿用。
3. 更长时间训练、更长 `release/full` 常驻 soak、更长周期资源占用和异常恢复基线单独跑，不放默认 pytest。
4. YOLOE / SAM3 进入第五批 custom nodes 前必须先审计和重构。

### 结果记录

结果统一记录到 `.tmp/model-full-core-validation/<timestamp>/`，每个模型和 task 保留：

- request 参数
- DatasetImport id
- DatasetExport id
- Training task id
- ModelVersion id
- Evaluation task id
- Conversion task id
- ModelBuild id
- DeploymentInstance id
- sync / async inference response 摘要
- workflow run id
- 失败原因和修复提交

前端页面操作记录：

- 2026-06-23 已跑模型页、部署页、推理页、workflow 应用列表和 workflow 应用详情页。
- 部署页和推理页已切换 detection / classification / segmentation / pose / obb 五个 `task_type`，没有 Bad Request、Internal Server Error 或 Not Found。
- 模型页当前没有全局 `task_type` 下拉，任务类型通过基础模型和数据集选择面板进入训练 / 转换表单。
- 结果目录：`.tmp/frontend-operation-record-20260623`。

release/full soak 记录：

- 2026-06-23 已跑 `tests/integration/test_release_full_stack_acceptance.py`，`AMVISION_RELEASE_FULL_SOAK_SECONDS=60`，端口 `18080`。
- 已验证 `/api/v1/system/health`、`/docs`、`/openapi.json`、full stack 组件日志、资源采样、stop 脚本回收和进程残留检查。
- 资源基线文件：`release/full/logs/release-full-short-soak-20260623/resource-baseline.json`。
- 日志目录：`release/full/logs/release-full-short-soak-20260623`。日志中未发现 `ERROR`、`Traceback`、`Exception`、`failed` 等异常关键词。
- 60 秒采样内 backend-service、dataset-import、dataset-export、training、conversion、evaluation、inference 组件 RSS 没有增长，stop 后 `runtime-state.json` 已删除，端口 `18080` 无残留监听。
- 2026-06-24 已跑更长 `release/full` 空载常驻基线：`AMVISION_RELEASE_FULL_SOAK_SECONDS=600`、`AMVISION_RELEASE_FULL_RESOURCE_SAMPLE_INTERVAL_SECONDS=30`、端口 `18240`、日志目录 `release/full/logs/model-mainline-long-soak-20260624-r1`，结果为 `1 passed`。
- 600 秒基线已验证陈旧 `runtime-state.json` 恢复、backend-service 与 6 个 worker profile 启动、health / docs / OpenAPI、30 秒间隔资源采样、stop 脚本回收和进程残留检查。
- 600 秒基线资源文件：`release/full/logs/model-mainline-long-soak-20260624-r1/resource-baseline.json`。本次 backend-service、dataset-import、dataset-export、training、conversion、evaluation、inference 的 RSS 增量为 `32768` 到 `40960` bytes，CPU 时间增量均为 `0.0`，线程数最终从 `4` 回落到 `2`。日志中未发现 `ERROR`、`Traceback`、`Exception`、`failed` 等异常关键词，stop 后 `runtime-state.json` 已删除。
- 2026-06-25 已按验收与修复主线补一轮 `release/full` 60 秒空载驻留复验：`AMVISION_RELEASE_FULL_SOAK_SECONDS=60`、`AMVISION_RELEASE_FULL_RESOURCE_SAMPLE_INTERVAL_SECONDS=10`，结果为 `1 passed`。
- 60 秒复验资源文件：`release/full/logs/integration-full-stack-1782389454/resource-baseline.json`。backend-service 与 6 个 worker profile 的 RSS 变化均为负值或无增长，CPU 时间增量均为 `0.0`，日志中未发现 `ERROR`、`Traceback`、`Exception`、`failed` 等异常关键词，stop 后 `runtime-state.json` 已删除。

上述 600 秒结果是 release/full 空载常驻和异常恢复基线，不等同于某个模型 deployment 持续推理负载 soak。真实长时间训练、代表性 deployment 长驻负载和更长时间资源基线仍按显式验收任务单独记录，不放默认 pytest。

## 下一步执行顺序

1. 如需要更强运行时基线，继续补代表性 deployment 长驻负载、真实长时间训练和更长周期资源采样；这些是显式验收任务，不进入默认 pytest。
2. YOLOE 后续只保留小范围工程整理：summary helper 已按 text / visual 局部拆分，不做跨模式大 helper；checkpoint 加载和输入预处理已下沉。
3. `SAM3` custom model node 收口已完成当前阶段：payloads、runtime access、video tracking、私有 core 迁移和 core 内部 checkpoint / models / nn / postprocess / preprocess / prompts / state / tracking 子包细化都已完成。
4. 第五批 custom nodes 已进入结构收口：`plc_modbus_tcp_nodes`、`output_local_db_nodes` 和 `output_mes_http_nodes` 的旧 `backend/nodes/_runtime.py` 均已删除，协议连接、输出 payload、参数读取、client / database / HTTP 调用和执行入口已拆到各自 `backend/runtime/`。

## 第五批进入条件

只有满足以下条件，才允许进入第五批 custom nodes：

- 本文档中 RF-DETR、YOLOX、YOLOv8、YOLO11、YOLO26 没有 `需修复` 状态。
- 旧 `yolo_primary_*` 入口已经删除或改为中性命名；旧共享 detection 训练入口也已删除或完全下沉到 `yolov8_core`。
- 每个模型的支持 task 都有真实全链路验收结果。
- deployment sync / async 和 workflow 调用已经确认不依赖旧 predictor。
- YOLOE 已完成 core / runtime / payloads / node adapter 收口，并补齐三类 workflow smoke；SAM3 已完成私有 core、runtime access、payloads、video tracking 和 core 内部子包拆分。
- 长时间训练、更长 `release/full` 常驻 soak、更长周期资源占用和异常恢复基线不作为第五批入口的默认 pytest 条件，但必须有单独计划和结果记录入口；如果执行过程中发现模型主链路 bug，必须先修复并复跑受影响链路。
