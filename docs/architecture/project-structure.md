# 项目结构规划

## 文档目的

本文档用于定义仓库级目录结构、架构层级和模块关系，服务于本地优先工业视觉平台的长期演进。

本文档只描述结构方案、边界和依赖方向，不包含实现细节、接口字段或具体技术选型的低层展开。

## 适用范围

- 仓库顶层目录划分
- 后端、前端、运行时、节点扩展和打包模块的层级边界
- 模块之间的依赖关系与禁止耦合关系
- 文档与测试如何镜像系统边界

## 设计原则

- 后端服务、worker、运行时分离
- 前端与后端严格分离，交互只通过版本化接口完成
- 本地优先实现和在线化演进兼容并存
- 先把输入输出规则定清楚，再补实现
- 重任务异步化，避免直接挤入请求处理链路
- 前端、节点扩展、运行时和打包产物围绕同一套公开接口规则协作
- 浏览器前端与外部系统默认通过 REST API 和 WebSocket 接入后端服务；同机本地部署时可补充 ZeroMQ 作为进程间通信边界
- 视觉服务与外部硬件控制解耦，项目只负责协议边界，不承担硬件驱动职责
- 各类硬件桥接、协议集成、模块连接和场景特化能力优先通过自定义节点扩展
- 自定义节点包与节点编辑方向向 ComfyUI 的 custom nodes 和 workflow 体验靠拢，但保留工业现场需要的版本、权限和回滚限制

## 源码命名约定

- backend 下的 Python 源码目录统一使用可直接导入的 snake_case 包名
- 文档中的结构路径优先与真实源码路径一致，不保留只用于规划展示的连字符目录名
- 结构优先按平台职责分层，模型增多时先在稳定层级下增加模型模块或子包，而不是为每个模型复制整套顶层目录

## 文档写法约定

- 目录名、模块名、对象名优先用简单常见词，例如 models、files、contracts、datasets
- 文档里直接写“做什么”“不做什么”“放什么”，不要写得像汇报材料
- 中文说明尽量短句，英文名也尽量短，不为了显得正式去造复杂词

## 最小框架视图

- frontend/web-ui：浏览器前端，放页面、工作流和结果查看
- backend/service：后端入口，处理 API、状态和任务安排
- backend/workers：后台 worker，跑训练、推理、转换和流程
- custom_nodes：节点扩展层，放 node pack、custom node 和相关扩展资产
- sdks：外部调用方 SDK，封装 REST、WebSocket 和 ZeroMQ TriggerSource 调用
- runtimes + packaging：运行和发布相关内容

## 建议仓库目录结构

```text
repo/
├─ backend/
│  ├─ alembic/
│  │  └─ versions/
│  ├─ bootstrap/
│  ├─ contracts/
│  │  ├─ buffers/
│  │  ├─ datasets/
│  │  │  └─ exports/
│  │  ├─ files/
│  │  ├─ nodes/
│  │  ├─ plugins/
│  │  └─ workflows/
│  ├─ maintenance/
│  ├─ nodes/
│  │  ├─ core_nodes/
│  │  └─ sam3_runtime_support/
│  ├─ queue/
│  ├─ service/
│  │  ├─ api/
│  │  ├─ application/
│  │  │  ├─ datasets/
│  │  │  ├─ models/
│  │  │  │  ├─ yolox_core/
│  │  │  │  ├─ yolov8_core/
│  │  │  │  ├─ yolo11_core/
│  │  │  │  ├─ yolo26_core/
│  │  │  │  ├─ rfdetr_core/
│  │  │  │  ├─ yolo_core_common/
│  │  │  │  ├─ training/
│  │  │  │  ├─ evaluation/
│  │  │  │  ├─ inference/
│  │  │  │  ├─ catalog/
│  │  │  │  └─ registry/
│  │  │  ├─ runtime/
│  │  │  │  ├─ deployment/
│  │  │  │  ├─ tasks/
│  │  │  │  ├─ predictors/
│  │  │  │  ├─ targets/
│  │  │  │  ├─ contracts/
│  │  │  │  ├─ serialization/
│  │  │  │  └─ support/
│  │  │  ├─ tasks/
│  │  │  ├─ conversions/
│  │  │  ├─ inference_results/
│  │  │  └─ deployments/
│  │  ├─ domain/
│  │  │  ├─ projects/
│  │  │  ├─ datasets/
│  │  │  ├─ models/
│  │  │  ├─ files/
│  │  │  ├─ tasks/
│  │  │  └─ deployments/
│  │  └─ infrastructure/
│  │     ├─ db/
│  │     ├─ integrations/
│  │     ├─ local_buffers/
│  │     ├─ object_store/
│  │     └─ persistence/
│  ├─ workers/
│  │  ├─ conversion/
│  │  │  └─ scripts/
│  │  ├─ datasets/
│  │  ├─ evaluation/
│  │  ├─ training/
│  │  ├─ inference/
│  │  └─ shared/
├─ frontend/
│  └─ web-ui/
│     ├─ shells/
│     ├─ modules/
│     │  ├─ datasets/
│     │  ├─ tasks/
│     │  ├─ models/
│     │  ├─ deployments/
│     │  ├─ integrations/
│     │  ├─ pipelines/
│     │  └─ settings/
│     ├─ workflows/
│     │  ├─ training/
│     │  ├─ inference/
│     │  ├─ release/
│     │  └─ integration-triggers/
│     └─ shared/
│        ├─ ui/
│        ├─ state/
│        ├─ services/
│        ├─ composables/
│        └─ contracts/
├─ sdks/
│  ├─ contracts/
│  ├─ dotnet/
│  ├─ python/
│  ├─ go/
│  ├─ c/
│  └─ examples/
├─ runtimes/
│  ├─ python/
│  │  ├─ dev-conda/
│  │  └─ bundled/
│  ├─ launchers/
│  │  ├─ service/
│  │  ├─ worker/
│  │  └─ maintenance/
│  └─ manifests/
│     ├─ runtime/
│     ├─ dependencies/
│     └─ compatibility/
├─ custom_nodes/
│  └─ <node-pack-name>/
│     ├─ manifest.json
│     ├─ workflow/
│     │  └─ catalog.json
│     ├─ backend/
│     ├─ schemas/
│     ├─ assets/
│     └─ docs/
├─ assets/
│  ├─ flow-templates/
│  ├─ model-profiles/
│  └─ defaults/
├─ packaging/
│  ├─ common/
│  ├─ standalone/
│  ├─ workstation/
│  └─ edge/
├─ docs/
│  ├─ architecture/
│  ├─ api/
│  ├─ deployment/
│  ├─ nodes/
│  └─ decisions/
└─ tests/
   ├─ backend/
   ├─ frontend/
   ├─ integration/
   └─ packaging/
```

## 层级关系

### 仓库一级层级

- backend：后端代码，包括服务、worker、共享规则和基础接入
- frontend：浏览器前端工程，通过 API 和后端协作
- sdks：外部调用方 SDK，服务设备上位机、MES、采集程序、现场桥接进程和调试脚本
- runtimes：开发和发布时要用到的运行时
- custom_nodes：可插拔节点扩展，不放平台主干逻辑
- custom_nodes 是场景化能力、硬件桥接、协议适配和模块连接的主扩展平面
- custom_nodes 允许 pack 间依赖，但简单节点优先 pack 内自给；复杂节点需要复用成熟能力时，再建立显式 pack 依赖
- packaging：发行包装配，不放业务逻辑
- docs：说明和设计文档
- tests：边界和交互验证

### backend 顶层目录

`backend/` 是服务端源码根目录。这里按平台职责分层，不按某个模型、某个任务或某次临时开发拆顶层目录。

- `service`：系统主入口，处理 REST API、WebSocket、任务状态 API、元数据、权限、状态流、deployment supervisor 和 workflow runtime manager。
- `workers`：重任务执行进程，消费数据集导入/导出、训练、验证/评估、转换和异步推理任务。worker 可以调用模型 core 和 runtime，但不拥有公开 API。
- `contracts`：放 service、workers、nodes、custom_nodes 和外部调试样例共用的稳定 schema、payload、数据集格式、文件规则、节点规则和 workflow 规则。
- `nodes`：放平台内建节点和节点运行支持代码。它不放自定义 node pack，也不放模型训练、转换或 deployment session。
- `queue`：放 QueueBackend 抽象和本地队列实现，只处理入队、领取、确认、重试、恢复和失败隔离，不放任务业务逻辑。
- `bootstrap`：放服务启动前后的装配辅助、环境检查和默认初始化入口，不放业务规则。
- `maintenance`：放维护命令和离线工具，例如 release 装配、manifest 扫描、资产检查和一次性整理脚本，不进入在线请求路径。
- `alembic`：只放数据库迁移和迁移配置，不放应用代码。

当前不再规划 `backend/adapters` 这个顶层目录。数据库、对象存储、协议接入和本地基础设施适配统一放在 `backend/service/infrastructure`；队列基础实现放在 `backend/queue`；外部协议或硬件桥接优先通过 `custom_nodes` 扩展。

### 模型 core 与导出目录

`backend/service/application/models/*_core/` 是模型结构和模型内核能力的唯一长期落点。每个模型 core 内部按需要继续拆：

- `models` / `nn`：模型结构、backbone、neck、head、transformer、decoder、mask head 等。
- `training`：loss、assigner、matcher、target 编码、训练增强和权重保存规则。
- `evaluation`：指标计算、评估输入输出和结果汇总。
- `export`：ONNX / OpenVINO / TensorRT 前置导出边界、稳定 export forward、输出名、动态 shape、数值校验辅助和导出配置。
- `weights`：checkpoint 读取、key 归一、state_dict 加载覆盖率和跳过原因。

`projectsrc/rf-detr/src/rfdetr/export` 这类参考仓库中的导出实现，对应迁入本项目的 `backend/service/application/models/rfdetr_core/export/`，而不是塞进 `backend/workers/conversion/`。同理，`YOLOX / YOLOv8 / YOLO11 / YOLO26` 的导出能力也分别放到对应 `*_core/export/`。`backend/workers/conversion/` 只保留任务执行、对象存储读写、转换产物登记、OpenVINO / TensorRT 子进程调用和状态回写。

### custom_nodes 分层

- `custom_nodes` 以 node pack 为最小分发单元，内部可按节点、协议、桥接和结果处理能力组织。
- `custom_nodes` 内部优先把简单 helper 和节点共享逻辑收敛到当前 pack，本地解决；确需跨 pack 复用时，依赖关系要显式记录，不通过隐式顶层 import 扩散。

### backend/service 内部层级

- api 层负责 REST、WebSocket 和面向外部系统的协议接入边界
- application 层负责用例编排、任务提交、状态汇聚和事务边界
- domain 层负责核心领域对象、规则和聚合关系
- infrastructure 层负责后端服务内部对 adapters、本地 ZeroMQ 通道和外部能力的接入

### backend/service/api 建议子层级

- app.py：FastAPI 应用装配入口
- rest/router.py：REST 根路由与版本入口
- rest/v1/routes：按资源分组的版本化 REST 路由文件，例如 system、datasets、models、tasks、deployments
- ws/router.py：WebSocket 根路由与订阅入口
- deps：鉴权主体、Project scope、分页、数据库会话等依赖注入定义
- middleware：request context、访问日志、异常映射等通用中间件

### backend/service/infrastructure 建议子层级

- db：SQLAlchemy engine、session、Unit of Work 和迁移相关装配，例如 session.py、unit_of_work.py
- persistence：ORM 实体与 Repository 实现，例如 dataset_orm.py、model_orm.py、dataset_repository.py、model_repository.py
- object_store：本地文件系统或其他 ObjectStore 的适配实现
- integrations：目录、Modbus、ZeroMQ 等外部或同机集成适配，不直接写到 API、domain 或模型 core 中
- local_buffers：本地 buffer、文件暂存和工作流运行时需要的本地数据通道

QueueBackend 的基础抽象和本地实现放在 `backend/queue`。service 只通过 application 层和 QueueBackend 接口提交任务，不把队列实现细节扩散到 route、domain 或 worker 代码里。

### backend/service 的数据与模型主干

- domain/datasets：放 Dataset、DatasetImport、DatasetVersion 和版本规则
- domain/models：放 Model、ModelVersion、ModelBuild、lineage 和发布规则
- domain/files：放模型文件、结果文件、FileRef、checksum 和保留规则
- domain/tasks：放 TaskRecord、TaskAttempt、TaskEvent、ResourceProfile、task repository 协议和具体任务规格对象
- application/datasets：处理格式识别、导入检查、格式转换、切分、生成版本、归档和清理
- application/models：处理预置预训练模型登记、训练输出登记、标签管理和版本维护
- application/tasks：处理任务创建、列表筛选、事件追加、取消和任务状态快照更新
- application/conversions：处理转换任务提交、导出版本登记、兼容性和 benchmark 写回
- application/inference_results：处理 task staging、结果提升、TTL 和清理
- contracts/datasets：放通用数据格式、导入格式规则和数据集导出格式规则
- service/infrastructure/object_store：放本地文件系统 ObjectStore 适配；数据集原始包、统一版本、训练导出、模型文件和任务暂存内容都通过 ObjectStore 规则访问，不让业务层直接拼磁盘路径

### backend/service/application/models

`application/models` 当前承担模型平台的应用服务和模型 core 两类职责，后续必须用子目录隔离，不能继续把几十个 `.py` 平铺在同一层。

目标分层如下：

- `yolox_core`、`yolov8_core`、`yolo11_core`、`yolo26_core`、`rfdetr_core`：放模型结构、配置、head、loss、assigner、matcher、target 编码、postprocess、权重加载、训练/评估核心和导出 forward。
- `yolo_core_common`：只放 YOLOv8 / YOLO11 / YOLO26 真正共用且不判断 `model_type` 的基础层、anchor、bbox、DFL、tensor 工具和通用数学函数。
- `training`：放训练任务应用服务、任务提交、训练参数检查、训练输出登记和任务状态回写，不放模型 loss、matcher 或增强实现。
- `evaluation`：放验证/评估任务应用服务、评估结果登记和指标写回，不放模型 postprocess 核心实现。
- `inference`：放推理任务应用服务、payload 组装、异步推理 gateway 和结果登记，不放 deployment session。
- `catalog`：放预训练模型目录、模型类型支持范围和模型文件登记规则。
- `registry`：放模型版本、模型构建、runtime target resolver 和模型能力查询。

迁移顺序按模型纵向闭环推进，不按目录横向一次搬完：

1. 先收 `rfdetr_core`：按 `projectsrc/rf-detr/src/rfdetr` 的目录职责复制适配，完成 detection / segmentation 的 core、training、evaluation、export、外层 service、worker 和 runtime 调用边界。
2. 再收 `yolox_core`：按 `projectsrc/YOLOX_2026/yolox` 的目录职责复制适配，完成 YOLOX detection 的模型结构、训练、评估、导出和 runtime 外壳边界。
3. 最后收 `yolov8_core / yolo11_core / yolo26_core`：这三类模型复制性更高、文件更多，按普通 YOLO 主线一起规划，但仍分别落到各自 core，不能混成一个不清楚的通用实现。

`training`、`evaluation`、`inference`、`catalog`、`registry` 是最终整理后的应用层落点，不是第一批迁移顺序。每次迁移一个模型时，要同时检查它在 `models/`、`runtime/`、`workers/` 和 API service 中的外层调用，避免只移动 core 目录却留下散落旧逻辑。

当前已收口与后续待迁的典型文件：

- `rfdetr_model.py`、`rfdetr_segmentation_model.py` 的旧模型结构文件已删除；RF-DETR 模型结构统一放在 `rfdetr_core/models`，`detection.py`、`segmentation.py` 只保留 builder 与 postprocess adapter。`rfdetr_core/models`、`assets`、`datasets`、`evaluation`、`training`、`training/platform_runner.py`、`utilities`、`visualize`、`config.py`、`_namespace.py`、`export/_onnx`、`export/_tensorrt.py`、`export/execution.py` 和 `runtime.py` 已按 Apache-2.0 RF-DETR 参考实现职责复制适配并接入本项目导出和推理语义边界。外层 `training/rfdetr_detection.py`、`training/rfdetr_segmentation.py`、conversion runner 和 runtime predictor 只保留任务、产物、session、backend adapter、buffer 和序列化边界。
- `catalog/rfdetr.py` 负责 RF-DETR 模型文件类型、预训练模型登记和 ModelVersion / ModelBuild 通用登记服务，属于模型 catalog 层，不再平铺在 `models/` 根目录。
- `training/rfdetr_detection_task_service.py` 负责 RF-DETR detection 训练任务提交、DatasetExport 校验和队列入队，属于训练应用服务层，不再平铺在 `models/` 根目录。
- `rfdetr_conversion_planner.py` 已保留为 RF-DETR 专属转换规划器，不再继承 YOLOX planner；后续如果要抽通用转换规划，也应先建立中性 shared planner，再让 YOLOX / RF-DETR 显式接入。
- `yolo_detection_model.py` 的模型结构、head、decode、loss、postprocess 迁入 `yolo_core_common` 和对应 `yolov8_core / yolo11_core / yolo26_core`。
- `yolox_detection_training.py` 中的数据增强、loss、EMA、scheduler、checkpoint 和训练循环核心迁入 `yolox_core/training`。
- `yolo_primary_*_training.py`、`pose_loss.py`、`obb_loss.py` 中的模型核心逻辑迁入对应 core；RF-DETR matcher、criterion、training module、checkpoint、EMA、drop schedule、param groups 和 callbacks 已按上游结构位于 `rfdetr_core/models` 与 `rfdetr_core/training`，外层 RF-DETR 训练文件已经收成 `training/` 下的任务桥接。

### backend/service/application/runtime

`application/runtime` 只处理“部署后怎么加载和长期运行”，不处理“模型是什么结构”。当前这一层文件已经过多，后续也必须拆子目录，而不是继续平铺。

目标分层如下：

- `deployment`：放 `deployment_process_*`、`deployment_events`、`deployment_runtime_pool`、进程监督、事件源和长期驻留进程管理。
- `tasks`：放 detection、classification、segmentation、pose、obb 的 runtime task 编排和 `task_prediction_runtime`。
- `predictors`：放各模型/任务的 predictor 和 session 包装，例如 YOLO、YOLOX、RF-DETR 的 PyTorch / ONNXRuntime / OpenVINO / TensorRT 加载与推理调用。
- `targets`：放 `runtime_target` 和各模型 runtime target 解析。
- `contracts`：放 task runtime 输入输出 contract。
- `serialization`：放 runtime payload 序列化与反序列化。
- `support`：放 `safe_counter`、运行时小工具和 backend adapter 辅助。

不迁入 `*_core` 的内容：

- `*_predictor.py` 不迁入 core。predictor 依赖 ONNXRuntime、OpenVINO、TensorRT、CUDA buffer、session pool、输入输出序列化和 deployment 资源管理，属于 runtime。
- `*_runtime_contracts.py` 和 `*_runtime_serialization.py` 不迁入 core。它们描述部署推理时的输入输出和传输格式，属于 runtime 边界。
- `deployment_process_*`、`deployment_runtime_pool.py`、`deployment_events.py` 不迁入 core。它们是长期进程和部署生命周期管理。
- `runtime_target.py` 不迁入 core。它负责把 ModelVersion、ModelBuild、runtime backend 和部署参数解析成运行目标。

已完成的 runtime 迁移：

- `runtime/yolox_core` 已整体迁到 `models/yolox_core`，runtime 下不再保留旧目录，后续不得恢复这个路径。
- 如果 `yolox_detection_runtime.py` 中仍有模型结构、网络层、loss、训练逻辑或权重映射，应迁入 `models/yolox_core`；保留 runtime session、加载、预处理、后处理桥接和结果序列化。

runtime 的目录整理同样按模型纵向推进。RF-DETR 已先完成第一批目录整理：`rfdetr_predictor.py`、`rfdetr_segmentation_predictor.py` 已迁到 `runtime/predictors/`，`rfdetr_runtime_target.py` 已迁到 `runtime/targets/`。后续再清 YOLOX，最后再清 YOLOv8 / YOLO11 / YOLO26。只有确认模型内部逻辑已经回到对应 core 后，才把剩余 runtime 外壳迁到 `predictors/`、`targets/`、`contracts/`、`serialization/` 等子目录。

当前 RF-DETR 已把 input size、output name、postprocess 和 segmentation mask 规整语义收进 `rfdetr_core/runtime.py`；runtime predictor 后续只做目录整理，不再新增模型语义。

### backend/workers

`backend/workers` 是独立 worker 进程的任务消费层。它可以调用 service application 用例、ObjectStore、QueueBackend 和模型 core，但自身不应该继续沉淀模型结构、loss、数据增强或 runtime session 的长期实现。

目标分层如下：

- `datasets`：消费 dataset-import、dataset-export 和数据准备任务，调用 contracts/datasets 和 application/datasets。
- `training`：消费训练任务，做任务领取、参数读取、进度回写、artifact 登记和错误回写；实际训练循环、loss、assigner、checkpoint 规则调用对应 `*_core/training`。
- `evaluation`：消费验证/评估任务，做任务状态和结果登记；真实评估前后处理调用对应 core 的 eval 或 postprocess。
- `conversion`：消费转换任务，做任务状态、目标格式、产物登记和子进程隔离；ONNX/OpenVINO/TensorRT 的稳定导出入口调用对应 `*_core/export.py`。
- `inference`：消费异步推理任务，调用 deployment runtime 或 task runtime，不直接写模型结构。
- `shared`：只放 worker 进程共用的小工具，例如任务上下文、日志、状态回写、文件登记辅助，不放模型专属逻辑。

workers 可以按模型分发任务，但不能成为模型核心实现的长期存放位置。模型相关判断应该止于“调用哪个 core 或哪个 runtime target”，不能在 worker 里重新实现 head、loss、decode 或权重加载。

### backend/contracts

`backend/contracts` 放跨层共享的稳定规则。这里的内容可以被 service、workers、nodes、custom_nodes、Postman 示例和后续 SDK 读取，但不能依赖 FastAPI route、SQLAlchemy ORM、worker 进程或模型内部实现。

当前目录职责如下：

- `buffers`：本地 buffer 和响应体传递规则。
- `datasets`：数据集导入、导出、样本、标注和格式常量。
- `datasets/exports`：训练可用的数据集导出格式和 manifest 规则。
- `files`：FileRef、文件列表和文件引用规则。
- `nodes`：节点输入输出 payload、节点 catalog 和 workflow 节点规则。
- `workflows`：workflow payload、运行时请求、触发源和结果引用规则。
- `plugins`：预留插件或扩展元数据规则。

contracts 只表达“数据长什么样、字段怎么命名、边界怎么传递”，不表达“怎么训练、怎么推理、怎么写数据库”。

### backend/nodes

`backend/nodes` 放平台内建节点和节点运行支持。它和 `custom_nodes` 的关系是：core nodes 作为平台内置基础能力随主项目发布，custom node pack 作为可选扩展独立启用、禁用和升级。

当前目录职责如下：

- `core_nodes`：放内建节点运行代码，例如图像输入、目录批处理、视频、工业规则、OpenCV 桥接、结果输出等核心可复用节点。
- `sam3_runtime_support`：放内建或自定义节点共用的 SAM3 运行辅助层。

节点层可以调用模型 deployment 或 workflow runtime，但不应该直接依赖某个训练 service 的内部文件。节点输入输出规则优先沉淀到 `backend/contracts/nodes`。

### backend/queue、bootstrap、maintenance、alembic

- `backend/queue`：QueueBackend 抽象和本地实现。它只关心任务入队、领取、确认、失败重试和 lease 恢复，不关心 YOLO、RF-DETR、数据集格式或节点业务。
- `backend/bootstrap`：服务启动装配和默认环境准备，不放模型、数据集或任务业务实现。
- `backend/maintenance`：离线维护命令和发布装配工具，例如 release/full 生成、manifest 重建、资产检查和清理脚本。在线服务和 worker 不能依赖 maintenance 里的临时实现。
- `backend/alembic`：数据库迁移目录，只保存 migration，不保存应用运行逻辑。

### frontend 内部分层

- shells 负责工作台骨架、布局、导航和全局状态容器
- modules 负责数据集、任务、模型、部署、集成端点、自定义节点和设置等业务模块页面
- workflows 负责跨模块操作流，例如训练发布链路、推理回滚链路和外部系统触发链路
- shared 放通用 UI、API client、WebSocket client、组合式能力和前端公开类型
- config 放前端运行配置、导航配置和 feature flags
- platform 放鉴权、默认本地用户自动进入、运行环境、浏览器存储和诊断适配
- plugins 放受控前端插件注册层，不作为任意 node pack 前端脚本注入入口
- lib 放第三方或底层库源码与薄封装，例如 LiteGraph
- views 只放顶层通用视图，业务页面放各模块 pages 目录
- 详细工程骨架见 [frontend-web-ui-structure.md](frontend-web-ui-structure.md)，本地启动和会话规则见 [frontend-web-ui-startup-session.md](frontend-web-ui-startup-session.md)，开发准备检查见 [frontend-web-ui-development-readiness.md](frontend-web-ui-development-readiness.md)

### 运行时与打包层级

- runtimes/python/dev-conda 服务于开发环境复现
- runtimes/python/bundled 服务于发布时同目录 Python 环境分发
- runtimes/launchers 统一服务、worker 和维护脚本的启动入口
- packaging/common 维护各发行形态共享结构
- packaging/standalone、workstation、edge 分别维护目标形态差异化装配规则

### sdks 层级

- sdks/contracts 放外部调用协议的稳定 schema、示例 payload 和错误码说明
- sdks/dotnet 放 C# / .NET SDK，优先兼容 .NET Framework 上位机和 .NET Core / .NET 应用
- sdks/python 放 Python SDK、CLI 和调试脚本能力
- sdks/go 放 Go SDK，服务边缘代理和本地桥接服务
- sdks/c 放 C ABI SDK，服务 C/C++ 上位机、厂商接口和其他需要稳定 C 接口的系统
- sdks/examples 放跨语言共享的外部调用示例，不放 backend-service 内部测试夹具

## 模块关系

### 核心依赖方向

- frontend/web-ui -> backend/service
- external systems -> backend/service
- external systems -> sdks -> backend/service
- backend/service -> backend/contracts
- backend/service -> backend/queue
- backend/service -> backend/service/infrastructure
- backend/workers -> backend/contracts
- backend/workers -> backend/queue
- backend/workers -> backend/service/application
- backend/workers -> backend/service/application/models/*_core
- backend/workers -> runtimes
- backend/nodes -> backend/contracts
- backend/workers -> custom_nodes
- custom_nodes -> backend/contracts
- packaging -> backend + frontend + runtimes + assets
- docs 与 tests 镜像上述公开边界，但不反向驱动业务依赖

### 关系说明

- frontend 只能依赖 backend-service 暴露的版本化 REST API、WebSocket 和任务状态流，不能直接依赖 workers、queue 或 service/infrastructure
- 上位机、MES、采集系统和其他外部系统与前端一样，统一通过 backend-service 的公开通信边界接入，而不是直接调用 workers
- SDK 是外部系统使用公开通信边界的辅助层，只封装 REST、WebSocket 和 ZeroMQ TriggerSource 协议，不成为 backend-service 的内部依赖
- ZeroMQ 只作为同机本地部署场景下的补充通信方式，用于本地进程间低开销交互，不替代公开的 REST API 和 WebSocket 规则
- backend-service 和 workers 通过 contracts 共享任务、事件、文件规则、集成规则和节点规则，避免互相侵入内部实现
- workers 使用 runtimes 提供的 Python 运行时和启动环境，使用 custom_nodes 提供可扩展节点、结果处理和协议适配扩展
- 硬件直连与模块连接逻辑如有需要，优先放入现场桥接 node pack 或模块连接 node pack，而不是扩散到 core 目录
- packaging 只负责装配和发布边界，不定义业务对象，也不持有独立领域规则
- docs/architecture 说明结构边界，docs/api 说明公开接口，docs/deployment 说明运行和发布方式，节点扩展规则收敛到架构文档

### 通信边界与交互路径

- frontend/web-ui <-> backend/service：页面请求、任务提交、配置读写和状态订阅，使用 REST API 与 WebSocket
- external systems <-> backend/service：上位机、MES、采集系统和其他业务系统的任务触发、结果回传和状态联动，默认使用 REST API 与 WebSocket
- backend/service <-> backend/workers：任务调度、状态回写和执行编排，通过内部任务与状态边界协作，不暴露给前端或外部系统
- local processes <-> local processes：在 standalone 或 workstation 的同机部署中，可通过 ZeroMQ 承担本地进程间消息分发或事件传递

## 禁止直接耦合的关系

- frontend 不直接调用 workers 或读取 runtimes 内部目录
- frontend 不与 backend 的 application、domain、infrastructure 代码直接共享运行时依赖
- sdks 不导入 backend/service 的 application、domain、infrastructure 或 worker 代码，只依赖公开协议、schema 和示例 payload
- external systems 不直接连接 workers、数据库或对象存储
- domain 不直接依赖具体数据库方言、外部消息中间件或文件系统实现
- custom_nodes 不直接依赖 backend/service 内部 application 或 domain 细节
- backend/service 和 workers 不直接持有相机、PLC、IO 传感器或机械臂的硬件驱动实现
- 核心目录不直接放客户定制模块连接逻辑，优先通过节点扩展点实现
- packaging 不反向定义 backend 和 frontend 的业务模块边界
- tests 不通过复制实现细节来建立伪结构，而应围绕公开接口规则和行为边界组织

## 文档落位建议

- [docs/README.md](../README.md) 作为整个仓库文档体系入口
- 本文档放在 docs/architecture/ 下，作为项目结构与模块边界总览
- 后续如需继续展开，可在 docs/architecture/ 下补充 backend-service、frontend-web-ui、runtime-packaging、node-system 等子文档
- 节点扩展原则和节点体系详见 [docs/architecture/node-system.md](node-system.md)
- AGENTS.md 仅保留项目约束、Agent Routing、Agent Color Mapping 和架构文档入口，不继续展开详细目录层级

## 后续可扩展文档

- docs/architecture/frontend-web-ui.md
- docs/architecture/node-system.md
- docs/architecture/integration-rules.md
- docs/architecture/execution-observability.md
