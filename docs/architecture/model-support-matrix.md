# 模型真实支持清单

## 文档目的

本文档把当前主干代码中已经落地的模型支持情况收成一份正式支持清单，重点回答下面三个问题：

- 哪些 `model_type × task_type` 组合已经进入平台主链
- 这些组合在 `导入 -> 导出 -> 训练 -> 验证 -> 评估 -> 转换 -> 部署 -> 推理 -> workflow -> 前端` 各阶段做到哪里
- 哪些能力已经有显式回归，哪些只是代码已接通但还需要继续补 smoke 或工程化收口

本文档按 2026-06-15 的仓库主干代码整理，只描述本项目正式实现，不包含 `projectsrc/` 参考仓库。

## 适用范围

- `yolox / yolov8 / yolo11 / yolo26 / rfdetr`
- `detection / classification / segmentation / pose / obb`
- 数据集导入导出、训练、验证、评估、转换、部署、推理、workflow 编排和浏览器前端

本文档不覆盖 `YOLOE / SAM3` custom node 主线。两者当前走 `WorkflowAppRuntime + custom node runtime`，不属于 `DeploymentInstance` 主链。

## 状态标记

| 标记 | 含义 |
| --- | --- |
| `tested` | 公开代码路径已接通，并且仓库里已经有显式回归、checked-in Postman、checked-in workflow 或实际构建验证 |
| `implemented` | 公开代码路径已接通，但当前组合还不是仓库内主验收路径，或者显式 smoke 还偏轻 |
| `limited` | 代码已接通，但存在后端、设备、格式来源或运行条件限制，暂不适合直接当成“全收口”能力 |
| `—` | 当前不支持 |

## 使用说明

- `导入` 和 `导出` 本质上是 `task_type` 级能力，不是 `model_type` 专属能力；同一任务下不同模型行通常会保持一致。
- `部署` 和 `推理` 这里默认同时指 `sync / async` 两条控制面，且对应独立进程 deployment runtime。
- `workflow` 列表示当前已经有正式 workflow/runtime 使用面，不表示每个模型分类都单独有一份专属 workflow 图。
- `前端` 列表示 `frontend/web-ui` 已有真实页面、路由和构建入口可以管理这条资源链，不表示每个组合都有单独页面或 e2e。
- `release/full` 装配、独立 worker profile、日志和排障不放在本表里，单独归到部署与发布收口。

## 正式支持清单

| model_type | task_type | 导入 | 导出 | 训练 | 验证 | 评估 | 转换 | 部署 | 推理 | workflow | 前端 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `yolox` | `detection` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `implemented` | 当前最成熟的参考主线 |
| `yolov8` | `detection` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `implemented` | 已并入统一 detection 主链 |
| `yolo11` | `detection` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `implemented` | 已并入统一 detection 主链 |
| `yolo26` | `detection` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `implemented` | 已并入统一 detection 主链 |
| `rfdetr` | `detection` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `tested` | `implemented` | detection 主链已接通 |
| `yolov8` | `classification` | `tested` | `tested` | `tested` | `implemented` | `implemented` | `tested` | `implemented` | `implemented` | `tested` | `implemented` | 内部链与 ONNX 预测已有显式 smoke |
| `yolo11` | `classification` | `tested` | `tested` | `tested` | `implemented` | `implemented` | `implemented` | `tested` | `tested` | `tested` | `implemented` | 当前 full-chain Postman 默认分类主线 |
| `yolo26` | `classification` | `tested` | `tested` | `implemented` | `implemented` | `implemented` | `implemented` | `implemented` | `implemented` | `tested` | `implemented` | 公开主链已接通，显式回归还偏轻 |
| `yolov8` | `segmentation` | `implemented` | `implemented` | `tested` | `implemented` | `implemented` | `tested` | `implemented` | `implemented` | `tested` | `implemented` | 内部链与 ONNX 预测已有显式 smoke |
| `yolo11` | `segmentation` | `implemented` | `implemented` | `implemented` | `implemented` | `implemented` | `implemented` | `implemented` | `implemented` | `tested` | `implemented` | 当前 full-chain Postman 默认分割主线 |
| `yolo26` | `segmentation` | `implemented` | `implemented` | `tested` | `implemented` | `implemented` | `implemented` | `tested` | `tested` | `tested` | `implemented` | task-native API 主验收组合之一 |
| `rfdetr` | `segmentation` | `implemented` | `implemented` | `tested` | `implemented` | `implemented` | `tested` | `tested` | `tested` | `tested` | `implemented` | full-core conversion、OpenVINO、TensorRT 和 deployment runtime pool smoke 已接通；长时间 soak 继续放到现场验收 |
| `yolov8` | `pose` | `implemented` | `implemented` | `tested` | `implemented` | `implemented` | `implemented` | `tested` | `tested` | `tested` | `implemented` | task-native API 主验收组合之一 |
| `yolo11` | `pose` | `implemented` | `implemented` | `implemented` | `implemented` | `implemented` | `implemented` | `implemented` | `implemented` | `tested` | `implemented` | full-chain Postman 与 workflow 面已接通 |
| `yolo26` | `pose` | `implemented` | `implemented` | `implemented` | `implemented` | `implemented` | `implemented` | `implemented` | `implemented` | `tested` | `implemented` | 模型构建与公开主链已接通 |
| `yolov8` | `obb` | `tested` | `tested` | `implemented` | `implemented` | `implemented` | `implemented` | `implemented` | `implemented` | `tested` | `implemented` | 模型构建与公开主链已接通 |
| `yolo11` | `obb` | `tested` | `tested` | `implemented` | `implemented` | `implemented` | `implemented` | `implemented` | `implemented` | `tested` | `implemented` | full-chain Postman 与 workflow 面已接通 |
| `yolo26` | `obb` | `tested` | `tested` | `tested` | `implemented` | `implemented` | `implemented` | `tested` | `tested` | `tested` | `implemented` | task-native API 主验收组合之一 |

## 当前主验收组合

下面这些组合当前已经不是“只有接口或只有路由”，而是仓库里有更明确的显式回归或正式样例：

| 组合 | 当前主证据 |
| --- | --- |
| `yolox + detection` | `tests/test_yolox_training_api.py`、`tests/test_yolox_conversion_tasks_api.py`、`tests/test_yolox_inference_tasks_api.py`、`tests/test_yolox_validation_sessions_api.py` |
| `yolov8 + classification` | `tests/test_yolo_primary_classification_chain.py` |
| `yolo11 + classification` | `tests/test_non_detection_inference_api.py`、`tests/test_non_detection_training_result_registration.py`、`docs/api/postman/classification-full-chain.postman_collection.json` |
| `yolov8 + segmentation` | `tests/test_yolo_primary_segmentation_chain.py` |
| `yolo26 + segmentation` | `tests/test_non_detection_inference_api.py`、`tests/test_non_detection_training_result_registration.py` |
| `rfdetr + segmentation` | `tests/test_rfdetr_segmentation_task_smoke.py`；2026-06-15 已用真实 segmentation nano checkpoint 跑通 ONNX 导出、ONNXRuntime 数值校验、ONNX simplify、OpenVINO IR、TensorRT 10.16 engine 构建和 deployment runtime pool sync / async smoke。 |
| `yolov8 + pose` | `tests/test_non_detection_inference_api.py`、`tests/test_non_detection_training_result_registration.py` |
| `yolo26 + obb` | `tests/test_non_detection_inference_api.py`、`tests/test_non_detection_training_result_registration.py` |
| `task-family workflow 12-15` | `docs/api/postman/workflows/12-*` 到 `15-*`、四套 non-detection root full-chain Postman collection |
| `non-detection training model_type smoke` | `tests/test_non_detection_training_model_type_matrix.py`，2026-06-12 已显式跑通 `YOLOv8 / YOLO11 / YOLO26 × classification / segmentation / pose / obb` 的训练任务提交、队列分发、结果登记、模型文件登记和 `pytorch` runtime target 解析，结果为 `12 passed`。这条是快速分发与登记回归，不代表每个组合都做过长时间真实训练。 |
| `non-detection runtime backend smoke` | `tests/integration/test_non_detection_runtime_backend_smoke_matrix.py`，2026-06-12 已显式跑通 `YOLOv8 / YOLO11 / YOLO26 × classification / segmentation / pose / obb × onnxruntime / openvino / tensorrt` 的真实 conversion -> runtime predict，结果为 `36 passed`。RF-DETR segmentation 由 `tests/test_rfdetr_segmentation_task_smoke.py` 和 2026-06-15 的真实 checkpoint conversion / deployment runtime pool smoke 单独覆盖。 |
| `RF-DETR full-core checkpoint / conversion / deployment runtime pool` | 2026-06-15 已显式跑通本地 RF-DETR detection `nano / s / m / l` 与 segmentation `nano / s / m / l / x` checkpoint 加载覆盖率，真实加载路径 coverage 均为 `1.0`；detection nano 与 segmentation nano 已完成 ONNX、OpenVINO IR、TensorRT 10.16 engine 的短时转换验收，并跑通 TensorRT engine 的 sync / async deployment runtime pool warmup、一次推理和 reset。 |
| `前端控制面` | `frontend/web-ui` 真实模块页、真实路由；models / deployments / inference 调试页已从 detection-only 改为显式 task_type 选择，相关 `Detection*` 历史类型和函数名已收成 `Model* / Task*` 命名；2026-06-12 本地 `npm run build` 已通过。 |
| `release/full 基础验收` | 2026-06-12 已执行 `assemble-release --profile-id full --force`，发布目录使用 `bundled_python_mode=preserved-existing`；`validate-layout`、发布目录 Python runtime import、`start_amvision_full.py` 一键启动、health、docs、OpenAPI 新 conversion 路由可见性和 stop 清理均已通过。当前还新增 `tests/integration/test_release_full_stack_acceptance.py`，用于显式验证 `release/full` 启动、陈旧状态文件恢复、组件日志、资源快照、短时驻留、OpenAPI 路由和 stop 回收；更长 soak 通过环境变量单独指定。stop launcher 已改为停止失败时返回非 0 并保留状态文件。 |
| `完整默认回归` | 2026-06-12 已使用开发环境 Python 跑通默认测试集 `1290 passed`，并补跑 `ruff check`、前端 `npm run build` 和若干边界定点回归。ONNX 导出当前优先使用 PyTorch 2.8 dynamo exporter；RF-DETR 对当前 PyTorch 2.8 不支持的 lowering 路径有显式 metadata 和受控 fallback，`tracer` 或 `cuda.cudart` deprecation warning 不单独记为功能失败。 |

## 数据集导入导出当前事实

### 已正式实现的导入入口

- `COCO`：服务 detection / segmentation / pose
- `VOC`：服务 detection
- `ImageNet classification`：服务 classification
- `DOTA OBB`：服务 obb

### 已正式实现的导出格式

- `coco-detection-v1`
- `voc-detection-v1`
- `yolo-detection-v1`
- `coco-instance-seg-v1`
- `yolo-instance-seg-v1`
- `coco-keypoints-v1`
- `yolo-pose-v1`
- `imagenet-classification-v1`
- `dota-obb-v1`

### 已在支持列表中，但当前还没有正式实现的导出格式

- `semantic-mask-dir-v1`
- `sam-promptable-seg-v1`

这两个格式当前不能算“还能用的残缺功能”，而是明确的未实现预留项。

## 运行时后端当前状态

| 运行时后端 | 当前状态 | 说明 |
| --- | --- | --- |
| `pytorch` | `tested` | 当前训练后验证、部署和推理主线最成熟的后端 |
| `onnxruntime` | `tested` | detection 主线与多条 non-detection 内部链、task smoke 已覆盖 |
| `openvino` | `tested` | 当前已补 non-detection 正式 smoke；更依赖设备与驱动环境，但主线组合已经有显式 conversion -> runtime predict 回归 |
| `tensorrt` | `tested` | detection 与代表性 non-detection 组合当前都已有显式真实 smoke；仍需要在现场继续关注 CUDA、TensorRT 版本与显存边界 |

## 当前已经有真实前端页面的模块

当前 `frontend/web-ui` 已有真实页面和路由的主模块包括：

- 项目
- 任务
- 数据集
- 模型
- 部署
- 推理
- TriggerSource
- custom node
- workflow app
- workflow editor
- 设置与诊断

当前前端不是空壳，但“文档是否同步”和“每个组合有没有单独页面”是另一件事，不能混为一谈。

## 当前还没完全收口的点

- `semantic-mask-dir-v1`、`sam-promptable-seg-v1` 还没有正式导出实现。
- `frontend` 真实代码已经明显领先于部分旧文档，本轮已先同步 models / deployments / inference 的 task-aware 调试入口，并清掉这几页内部的 `Detection*` 历史类型命名；前端专题文档后续还需要继续细化 workflow template/version 使用面。
- `release/full` 基础装配、一键启动验收和仓库侧短时自动验收入口已经具备；worker profile 也已短时启动确认可装配。后续还需要继续补更长时间的发布目录 soak、资源占用、日志指标和现场排障样例。
- `workflow template/version` 的前端使用面已经可走主线，但还没有细化成更完整的独立使用说明。

## 建议下一步

最合适的下一步不是继续扩新模型，而是按这份支持清单继续做三件事：

1. 在 `tests/integration/test_release_full_stack_acceptance.py` 的基础上跑更长时间的发布目录 soak，并记录资源占用、日志指标和异常恢复样例。
2. 再回头补剩余导出格式和前端文档同步，不要让“代码已实现”和“文档还停在旧状态”继续分叉。
3. 后续按真实现场组合继续加更细的长期 benchmark，而不是再回到“先怀疑主链是否能跑”的阶段。
