# 模型平台化规划

## 文档目的

本文档用于把当前主干从“YOLOX 已经完整实现”推进到“多模型平台可持续接入”的路线收敛成一份正式架构规划。

本文档重点回答四个问题：

- 哪些层继续保持通用
- 哪些层按任务分类拆分
- 哪些层按模型分类做适配
- 后续每个模型分类的最小接入范围和优先顺序

## 适用范围

- backend-service、worker、runtime、workflow 和发布装配的模型扩展边界
- 训练、转换、推理、部署和长期稳定运行服务的模型接入策略
- YOLOX、YOLOv8/11/26、RT-DETR、SAM2/3、QwenVL 的后续进入范围

## 当前结论

当前平台已经越过“只有 YOLOX”的阶段：YOLOX detection 仍然是第一套最完整的参考实现，但 YOLOv8/YOLO11/YOLO26 多任务链、RF-DETR detection/segmentation、统一 deployment/runtime、平台基础模型目录 seeder，以及 workflow service nodes 已经把模型执行层推进到真实的多模型平台阶段。当前更需要做的是继续收口通用接口、减少遗留 `yolox_*` 命名外壳，而不是再复制一套新实现。

### 已经比较通用的部分

- `Model`、`ModelVersion`、`ModelBuild`、`ModelFile` 已经是通用对象。
- `DatasetExport`、`TaskRecord`、`DeploymentInstance` 已经是通用对象。
- backend-service / worker / deployment 子进程 / workflow runtime / node pack / release 装配这些骨架已经是平台级能力。
- 发布态长期运行推理服务的外壳已经存在，不是只为单次脚本推理设计。

### 仍然明显绑定 YOLOX 的部分

- 历史命名上仍保留大量 `yolox_*` 模块名、队列名、runtime target 与 专用 route；这些外壳不再只服务 YOLOX，但名称仍会影响理解成本。
- `ModelRuntime`、deployment supervisor 和 async inference gateway 已经具备通用分发能力，但部分请求/结果对象和目录命名仍带早期 detection/YOLOX 色彩。
- workflow service node runtime 已经组装统一 detection / classification / segmentation / pose / obb 服务，以及 YOLOE / SAM3、PLC、目录触发、自定义输出等能力；但少数 service node id 与内部 helper 仍沿用早期 YOLOX 命名。
- worker consumer 注册表里，detection 推理和评估已经改成 `detection-inference / detection-evaluation`；当前 detection 训练仍保留 `yolox-training`，因为这层还直接对应 YOLOX 的任务服务、trainer runner 和 worker 实现边界。detection conversion 的公开入口仍然是 `detection_conversion_tasks.py`，但内部已经收成 `yolo_conversion_task_service_base.py` + `yolox / yolov8 / yolo11 / yolo26 / rfdetr` 模型适配层；task kind、queue name 和 worker consumer 仍按真实模型实现命名，不再伪装成已经完全共享。

因此，下一步不应按“再复制一套 YOLOX 目录给下一个模型”的方式继续扩张，而应先把当前主干拆成稳定的通用层、任务分类层和模型分类适配层。

## 当前进展

### YOLOv8/YOLO11/YOLO26 多任务链路

- YOLOv8/YOLO11/YOLO26 已实现 5 种任务类型（detection/classification/segmentation/pose/obb）的训练、转换、推理、部署完整链路。
- 每种非 detection 任务类型各有独立的训练路由（list/detail/save/pause/terminate/resume/delete 7 个端点）和转换路由（onnx、openvino-ir、tensorrt 三类目标）。
- OBB 训练损失已使用完整实现：probiou + 旋转框 TAL + DFL + 角度损失（`obb_loss.py`），不再使用占位 MSE。
- Pose 训练损失已使用完整实现：detection 损失 + 关键点位置损失 + 可见性 mask（`pose_loss.py`），不再使用占位 MSE。
- model_scale 命名已统一：全部 YOLO11/YOLO26 配置和默认值使用 `"nano"` 而非 `"n"`。

### RF-DETR 状态

- RF-DETR detection 已并入统一 detection 训练/转换控制面，当前正式主链已覆盖训练、转换、推理和 deployment。
- RF-DETR segmentation 已接通训练和 deployment 主链；当前 builder 已切到 `rfdetr_core/models/` 下的 upstream-aligned full-core 实现，conversion 也已走 `rfdetr_core/export/_onnx` 入口。后续重点是继续补完整 RF-DETR training/export 细节、长时间 smoke 和真实权重覆盖率验证。

### 非 Detection 转换路由

- classification/segmentation/pose/obb 转换路由已修复，从使用缺少 planner 的基类改为使用正确的模型专属服务类（`SqlAlchemyYoloV8/11/26ConversionTaskService`）。

### Bootstrap 重构

- `build_runtime` 中 5 种 task_type 的 deployment supervisor 构建已从 ~150 行重复代码重构为参数化工厂函数。
- `start_runtime`/`stop_runtime` 已从逐字段 if-else 改为 `iter_all_deployment_supervisors()` 迭代。

## 设计目标

- 让 YOLOX 成为第一套完整参考实现，而不是唯一实现。
- 让后续模型继续复用同一套任务系统、部署系统、workflow 和发布装配。
- 让不同任务分类使用不同输入输出规则，避免把 detection、segmentation 和 multimodal-vl 混成一套结构。
- 让不同模型分类只处理自己的规格、训练、转换、推理和部署差异，不重复建设平台骨架。
- 继续保留长期稳定运行的独立推理服务形态，而不是回退到进程内临时会话模式。

## 非目标

- 第一阶段不要求所有模型都与 YOLOX 同时达到完全相同的深度。
- 第一阶段不要求同时补齐所有模型的完整训练、验证、评估和转换矩阵。
- 第一阶段不把大规模浏览器端到端测试作为主线任务。
- 第一阶段不为每个模型复制一套 service、worker、runtime 和 workflow 顶层目录。

## 分层原则

模型平台化后，建议长期维持下面四层：

1. 通用层
2. 任务分类层
3. 模型分类适配层
4. 运行时后端层

这四层的职责不能混写。

## 哪些层保持通用

下面这些层应继续保持平台通用，不按模型名复制实现。

### 1. 领域对象层

- `Model`
- `ModelVersion`
- `ModelBuild`
- `ModelFile`
- `DatasetExport`
- `TaskRecord`
- `DeploymentInstance`

这些对象描述的是平台资源，不应直接写死 YOLOX、SAM 或 QwenVL 的底层实现细节。

### 2. 基础设施层

- DatabaseBackend
- ObjectStore
- QueueBackend
- CacheBackend
- 本地文件存储
- 任务队列
- 发布装配
- 启动脚本

这些层只负责存储、调度、发布和运行，不负责具体模型算法。

### 3. 平台控制面

- REST API 路由分层
- WebSocket 资源流
- TaskService
- Project、Dataset、Model、Deployment 资源管理
- workflow runtime 管理
- node pack 生命周期管理

这部分继续作为统一控制面存在，不为单个模型单独再建一套服务框架。

### 4. 长期运行服务外壳

- DeploymentInstance 资源
- runtime target 快照持久化
- deployment process supervisor
- deployment 子进程
- runtime pool
- keep_warm / warmup / restart / health / reset / stop / start
- LocalBufferBroker 接入

长期稳定运行的独立推理服务方式应继续保留为平台通用外壳。后续不同模型分类只替换子进程内的实际会话加载和推理逻辑。

### 5. workflow 与节点外壳

- workflow template / application / execution policy / preview run / app runtime / run
- workflow service node runtime context
- node pack manifest、catalog、权限、禁用、回滚
- 发布推理服务调用边界

workflow 不应按某个模型分类重新设计执行框架，而应继续把模型能力作为节点能力挂入统一执行图。

### 6. 前端工作台外壳

- 项目、任务、数据集、模型、部署、推理、workflow、节点、设置这些主模块
- workbench shell、blank shell、auth shell
- 通用 API client、WebSocket client、runtime-config 机制

前端页面可以按任务分类和模型分类补业务页，但不应为单个模型分类复制一套新前端工程。

## 哪些层按任务分类拆分

任务分类层是后续多模型接入最重要的一层。不同模型分类只有先归到明确的任务分类，平台接口才会稳定。

当前已稳定或优先推进的任务分类：

- detection（已稳定）
- classification（已通过 YOLOv8/11/26 接入）
- segmentation（已通过 YOLOv8/11/26 接入）
- pose（已通过 YOLOv8/11/26 接入）
- obb（已通过 YOLOv8/11/26 接入）
- multimodal-vl（规划中）

### detection

适用模型分类：

- YOLOX
- YOLOv8/11/26
- RT-DETR

这一层需要稳定的内容包括：

- detection 数据集导出格式
- detection 训练输入规则
- detection 推理输入规则
- detection 结果结构
- detection 评估规则
- detection 结果图与后处理规则
- detection 部署输入输出约束

当前 YOLOX 已经把这条线打通，因此 detection 应作为第一条平台化任务分类继续收口。

### segmentation

适用模型分类：

- SAM2/3

这一层需要稳定的内容包括：

- segmentation 输入图片规则
- prompt 输入规则，例如点、框、已有 mask
- segmentation 结果结构，例如 mask、polygon、region
- segmentation 结果预览规则
- segmentation 评估规则
- segmentation 部署输入输出约束

这一层不能硬套 detection 结果结构，否则后续 prompt、mask 和交互式调用都会变形。

### multimodal-vl

适用模型分类：

- QwenVL

这一层需要稳定的内容包括：

- 图片 + 文本联合输入规则
- 文本、JSON、grounding 结果规则
- session / context / 历史输入边界
- 多轮调用时的状态管理边界
- multimodal-vl 部署输入输出约束

这一层不应沿用 detection 的 bbox-only 结果结构，也不应沿用 segmentation 的 mask-only 结果结构。

### 后续可再增加的任务分类

当前不必立即展开，但后续可以按同一规则增加：

- ocr
- tracking

原则是：先稳定任务分类，再让具体模型分类接入，不反过来做。classification、segmentation、pose 和 obb 已通过 YOLOv8/11/26 接入。

## 哪些层按模型分类做适配

模型分类适配层只负责“这个模型分类自己的差异”，不重复建设平台通用能力。

每个模型分类至少应在下面几个位置有自己的适配实现：

- model spec
- task spec 扩展
- model service
- runtime target resolver 扩展
- deployment binding
- 训练 backend 或训练 runner
- 转换 backend 或转换 runner
- 推理 runtime session 加载与前后处理
- workflow 节点映射

下面按当前目标模型分类分别说明。

### YOLOX

任务分类：

- detection

当前状态：

- 已是最完整参考实现

后续职责：

- 不再继续作为唯一实现扩张
- 优先用于抽出 detection 通用层
- 优先用于抽出 TrainingBackend、ConversionBackend、ModelRuntime 的稳定边界

### YOLOv8/11/26

任务分类：

- detection
- classification
- segmentation
- pose
- obb

当前状态：

- 已实现 5 种任务类型的训练、转换、推理、部署完整链路
- 每种任务类型有独立的训练路由和转换路由
- OBB 和 Pose 已有真实损失函数实现（非占位）

定位：

- 第一批已接入的多任务模型分类

原因：

- 与 YOLOX 在任务类型、输入输出、部署方式和目标运行时上最接近
- 最适合验证 detection 通用层是否已经抽稳
- 多任务覆盖验证了任务分类层的拆分是否有效

### RT-DETR

任务分类：

- detection

定位：

- 第二批继续接入的检测模型分类

原因：

- 仍属于 detection，但模型结构、训练和推理细节已经明显不同
- 很适合检验平台是否真的支持“同一任务分类下的不同模型分类”

### SAM2/3

任务分类：

- segmentation

定位：

- 第一批进入 segmentation 任务分类的模型分类

原因：

- 它能验证平台是否真的从 detection 扩展到了另一种任务分类
- prompt、mask、区域输出和交互式调用都要求新的任务分类边界

### QwenVL

任务分类：

- multimodal-vl

定位：

- 第一批进入 multimodal-vl 任务分类的模型分类

原因：

- 它能验证平台是否支持图片 + 文本联合输入、文本 / JSON 联合输出和长期运行生成式服务
- 它与 detection 和 segmentation 的训练、转换、推理边界差异最大

## 当前最需要先收稳的接口

根据现有代码状态，后续多模型接入前，最需要先从 YOLOX 中抽稳下面这些接口：

- ModelRuntime
- TrainingBackend
- ConversionBackend
- RuntimeTargetResolver
- DeploymentBinding
- PredictionRequest / PredictionResult
- EvaluationRequest / EvaluationResult
- Workflow service node runtime builder

其中最关键的事实是：

- `ModelRuntime` 目前名字已经通用，但输入输出仍然带着明显 YOLOX 痕迹。
- `TrainingBackend` 与 `ConversionBackend` 已经出现通用命名，但实际请求和结果还主要围绕 YOLOX detection。
- runtime target、deployment runtime pool 和 deployment supervisor 现在也主要是 YOLOX 版本。

因此，真正的下一步不是“直接加新模型代码”，而是先把这些接口从 YOLOX 实现里拆成可复用外壳。

## 后续每个模型分类的最小接入范围

“最小接入范围”指的是：达到这个范围后，就可以认为该模型分类已经正式进入平台，不再只是脚本级试验。

### 1. YOLOv8/11/26

当前状态：已完成 5 种任务类型（detection/classification/segmentation/pose/obb）的训练、转换、推理、部署全链路。

已达成：

- 预置模型登记
- detection/classification/segmentation/pose/obb 训练输入输出接入
- detection/classification/segmentation/pose/obb 转换链路（onnx、openvino-ir、tensorrt）
- DeploymentInstance 创建与查询
- sync / async 推理接口
- 独立 deployment 子进程长期运行
- warmup / keep_warm / health / reset / restart
- 完整转换矩阵
- 每种任务类型独立训练管理路由（list/detail/save/pause/terminate/resume/delete）
- OBB 和 Pose 真实损失函数实现

待补齐：

- validation session（非 detection 任务类型）
- evaluation task（非 detection 任务类型）
- workflow 推理节点接入
- 前端模型页和部署页细化展示

优先顺序：

- ~~高~~（已完成主体接入）

### 2. RT-DETR

最小接入范围：

- 预置模型登记
- detection 推理输入输出接入
- DeploymentInstance 创建与查询
- sync / async 推理接口
- 独立 deployment 子进程长期运行
- 至少一条正式转换链
- workflow 推理节点接入

第二阶段补齐：

- 正式训练任务
- evaluation task
- detection 结果与 benchmark 对齐

优先顺序：

- 中高

### 3. SAM2/3

最小接入范围：

- segmentation 输入规则
- prompt 输入规则
- mask / polygon / region 结果结构
- DeploymentInstance 创建与查询
- sync / async 推理接口
- 独立 deployment 子进程长期运行
- workflow segmentation 节点接入
- 前端最小 mask 结果预览

第二阶段补齐：

- segmentation 数据集导出
- segmentation 评估规则
- 视频或连续帧场景
- 训练或微调链路

优先顺序：

- 中

### 4. QwenVL

最小接入范围：

- 图片 + 文本输入规则
- 文本 / JSON 输出规则
- DeploymentInstance 创建与查询
- sync / async 推理接口
- 独立 deployment 子进程长期运行
- workflow multimodal-vl 节点接入
- 前端最小结果展示

第二阶段补齐：

- grounding 结果结构
- 多轮上下文
- 结构化输出模板
- 训练或微调链路

优先顺序：

- 中低

## 总体优先顺序

建议按下面顺序推进：

1. ~~先把 YOLOX 抽成 detection 参考实现~~（已完成）
2. ~~接入 YOLOv8/11/26~~（已完成 detection/classification/segmentation/pose/obb 5 种任务类型）
3. 接入 RT-DETR
4. 接入 SAM2/3，扩展 segmentation 任务分类的独立模型验证
5. 接入 QwenVL，打开 multimodal-vl 任务分类

当前进展说明：

- YOLOX 已作为 detection 参考实现稳定运行。
- YOLOv8/11/26 已完成 5 种任务类型的训练、转换、推理、部署全链路，验证了任务分类层的拆分有效性。
- 下一步重点是 RT-DETR（验证 detection 层独立于单个模型）和 SAM2/3（扩展 segmentation 独立模型）。

## 当前阶段的验证重点

当前阶段的重点应放在模型链路平台化，而不是扩大前端自动化测试面。

因此当前更适合优先验证：

- 训练链路是否可复用
- 转换链路是否可复用
- DeploymentInstance 与独立推理服务外壳是否可复用
- 推理结果结构是否已经按任务分类稳定
- workflow 节点与 service node 是否已经能挂接多模型分类

当前不建议把大规模 Playwright E2E 作为主线工作。前端后续更适合只保留少量发布验收 smoke，而不是先铺一整套浏览器回归矩阵。

## 推荐后续文档

- [docs/architecture/model-core-implementation-plan.md](model-core-implementation-plan.md)
- [docs/architecture/model-task-naming-boundaries.md](model-task-naming-boundaries.md)
- [docs/architecture/model-workflow-boundaries.md](model-workflow-boundaries.md)
- [docs/architecture/yolox-module-design.md](yolox-module-design.md)
- [docs/architecture/detection-model-rules.md](detection-model-rules.md)
- [docs/architecture/data-and-files.md](data-and-files.md)
- [docs/architecture/current-implementation-status.md](current-implementation-status.md)
- [docs/architecture/next-stage-roadmap.md](next-stage-roadmap.md)
