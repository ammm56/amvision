# 当前代码实现审计记录（2026-07-02）

## 审计范围

本记录基于当前工作区代码、项目 Markdown 文档、后端路由、worker registry、模型 core 目录、deployment runtime、workflow/custom node、前端 Vue 页面和现有测试进行核对。

重点链路：

- 数据集导入、导出
- 训练、验证、评估
- 转换：ONNX、OpenVINO、TensorRT
- deployment sync / async
- 独立子进程常驻推理
- workflow 编排与 service node
- 前端模型、部署、推理、数据集页面
- `projectsrc/` 参考源码与项目运行时代码边界

## 总体结论

当前项目实现已经不是空框架。后端控制面、独立 worker、数据集导入导出、多模型训练任务、转换任务、deployment sync / async、task-native 推理、workflow runtime、custom node 和 Vue 前端页面均有真实代码与测试覆盖。

但“完整可长期稳定运行”不能一概而论。当前主链已经具备可运行闭环，短链路和控制面测试较充分；长时间训练、代表性 deployment 长驻负载、现场资源基线、RKNN / ARM NPU runner、部分预留数据集导出格式仍未完全收口。

## 项目目标和架构匹配情况

当前代码与项目定位基本匹配：

- 本地优先：SQLite、本地对象存储、本地文件队列、同目录 Python 发布目录均已接入。
- 模块化单体：FastAPI 作为控制面，重任务通过 worker profile 消费本地队列。
- 运行时分离：deployment 使用独立子进程、请求/响应队列、runtime pool、warmup、health、reset、auto restart。
- 扩展优先：核心节点与 custom node pack 并存，`YOLOE / SAM3`、相机、Modbus、输出节点等走 custom node 边界。
- 前端主栈：`frontend/web-ui` 使用 Vue 3、TypeScript、Vite、Pinia、Vue Router。

## 主要调用链状态

### 数据集导入

已实现：

- zip 上传、落盘、DatasetImport / TaskRecord 登记。
- worker 异步处理 `dataset-imports` 队列。
- COCO、VOC、YOLO、ImageNet classification、DOTA OBB 解析。
- 成功后写 DatasetVersion、样本、类别、索引和版本目录。
- 失败时写 validation report 和任务事件。

本次修复：

- 删除已完成 DatasetImport 时改为清理整次 import 根目录，避免留下 `manifests/`、`logs/` 和空目录。
- 新增测试验证删除导入记录不会删除 DatasetVersion 文件。

### 数据集导出

已实现：

- `coco-detection-v1`
- `voc-detection-v1`
- `yolo-detection-v1`
- `coco-instance-seg-v1`
- `yolo-instance-seg-v1`
- `coco-keypoints-v1`
- `yolo-pose-v1`
- `imagenet-classification-v1`
- `dota-obb-v1`

未实现但已预留：

- `semantic-mask-dir-v1`
- `sam-promptable-seg-v1`

### 训练、验证、评估

已接入：

- `yolox`: detection
- `yolov8 / yolo11 / yolo26`: detection、classification、segmentation、pose、obb
- `rfdetr`: detection、segmentation

当前结构：

- 应用层 task service 负责任务登记、队列、对象存储输出、事件和模型版本登记。
- 模型结构、loss、target、postprocess、export、runtime helper 下沉到各模型 core。
- `backend/workers/consumer_registry.py` 已装配 dataset import/export、training、conversion、evaluation、inference consumer。

仍需优化：

- 多个 training service 文件仍超过 700 到 1400 行，个别更大，后续可继续拆分登记、输出、事件、执行适配。
- 文档已承认普通 YOLO non-detection 任务还需要继续对齐长期 DataLoader iterator、task-specific target 同步和 validator 汇总。
- 长时间真实训练不在默认 pytest 中，仍需要现场基线。

### 转换

已接入主线：

- ONNX
- optimized ONNX
- OpenVINO IR
- TensorRT engine

边界：

- detection conversion 仍保留历史目标格式子路径。
- classification、segmentation、pose、obb 使用 task-native `/models/{task_type}/conversion-tasks`。
- RKNN / ARM NPU 相关常量、文件类型、runtime target 有预留，但没有完整 conversion runner 和 runtime session，不能算当前完整实现。

### deployment 和常驻推理

已实现：

- sync / async 两套 deployment supervisor。
- 独立子进程 runtime worker。
- runtime pool、实例并发槽、warmup、health、reset、stop。
- auto restart、restart_count safe counter、keep-warm、TensorRT pinned output buffer 状态。
- task-native request / result 跨进程序列化。

仍需补强：

- 已有短时 release/full soak 和控制面测试。
- 仍缺代表性模型 deployment 长驻负载、持续推理资源曲线、异常恢复和现场 GPU/驱动组合基线。

### workflow 和 custom node

已实现：

- workflow document、template、application、preview run、app runtime、runs、execution policy、trigger source。
- service node 可调用 deployment / inference / dataset / task 等平台能力。
- custom node loader、manifest、capability、启停和 runtime registry 已接入。
- 运行时代码没有直接依赖 `projectsrc` 参考目录或官方模型包。

边界：

- `YOLOE / SAM3` 当前走 WorkflowAppRuntime + custom node runtime，不属于 DeploymentInstance 主链。
- 复杂 custom node 的长期资源和显存基线仍需要按实际现场继续记录。

### 前端

当前状态：

- 已有真实页面：项目、任务、数据集、模型、部署、推理、TriggerSource、custom node、workflow app、workflow editor、设置与诊断。
- models / deployments / inference 已按 `task_type` 显式选择，不再是单纯 detection-only 页面。
- 本次修复部署页面未完成的改动：补齐 runtime 状态缓存、按钮可用性、状态/健康刷新、lucide 图标和新布局样式。

仍需优化：

- detection conversion 前端仍接历史路径，后续可与其他 task_type 收敛成统一 API。
- workflow template/version 前端使用说明仍需继续细化。
- 前端 bundle 主 chunk 超过 500 kB，构建可通过，但后续可按页面拆包。

## 参考源码边界

`projectsrc/ultralytics/ultralytics`、`projectsrc/YOLOX_2026/yolox`、`projectsrc/rf-detr/src/rfdetr`、`projectsrc/supervision/src/supervision` 当前作为参考源码存在。

当前运行时代码没有直接 import 这些参考目录。已有测试 `tests/test_model_core_dependency_boundaries.py` 检查 backend 模型和 runtime 不 import 官方 `ultralytics` / `rfdetr` 包，也不引用 `projectsrc`。本轮额外扫描 custom_nodes，未发现直接依赖。

## 本轮修改

- 修复 DatasetImport 删除时的文件残留。
- 清理 DatasetImport service 中明显多余空行。
- 将 `YOLO_PRIMARY_*` 常量命名改为中性 `YOLO_MODEL_*`。
- 修复部署前端页面未完成改动导致的编译风险，并补齐工作台布局。
- 新增 DatasetImport 删除文件行为测试。

## 验证结果

已通过：

- `npm run build`（frontend/web-ui）
- `pytest tests/test_dataset_import_api.py::test_delete_completed_dataset_import_removes_import_files_only`
- `pytest tests/test_model_profiles.py tests/test_model_core_dependency_boundaries.py`
- `pytest tests/test_detection_deployment_instances_api.py tests/test_non_detection_conversion_tasks_api.py tests/test_non_detection_inference_api.py tests/test_yolox_deployment_process_supervisor.py`
- `ruff check` touched Python files

## 后续优先级

1. 补代表性 deployment 长驻负载 soak，记录 CPU、内存、显存、重启、异常恢复和日志。
2. 收敛 detection conversion 到 task-native API，减少前后端历史路径分叉。
3. 完成 `semantic-mask-dir-v1`、`sam-promptable-seg-v1` 导出，或从公开支持列表中保持明确隐藏。
4. 明确 RKNN / ARM NPU 的阶段边界：要么补 runner/session，要么继续作为预留能力，不在页面和 API 中误导为可用。
5. 继续拆分超大 training service 和 runtime service 文件，优先拆任务登记、输出登记、事件写入、执行适配。
6. 为 YOLOv8 / YOLO11 / YOLO26 non-detection 训练继续补 task-specific DataLoader、target 同步和 validator 长期一致性验证。
