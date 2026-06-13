# 模型命名边界

## 文档目的

本文档用于固定模型平台里的命名边界，避免把公开入口统一、任务分类统一和模型实现隔离混成一层。

本文档只回答一件事：哪些文件、类、常量和 worker 名字按 `task_type` 命名，哪些必须按 `model_type` 命名，哪些可以按模型系列共享命名。

## 适用范围

- backend service 路由、application service、worker、planner、runner
- workflow service node runtime 和公开 service node
- task kind、worker consumer、queue name
- 模型平台相关架构文档和示例命名

## 当前结论

- 公开控制面按 `task_type` 命名。
- 真正执行模型差异的实现层按 `model_type` 命名。
- 只有在多个同系列模型真实共享了一层内部实现时，才允许按模型系列名命名。
- 只有和值对象或公共返回结构真的无关模型、无关任务时，才允许使用中性通用名。
- 模型 core 包先按 `model_type` 命名，core 包内部再按 `task_type` 拆分任务实现。

最重要的限制是：

- 不能把只服务某个模型系列的内部层，命名成 `detection_*` 这类看起来像全任务通用的名字。
- 不能因为公开 API 已经统一，就把内部 worker、task kind、planner、runner 也一起改成通用名。
- 不能在 `yolo_core_common` 这类共享目录里写 `if model_type == ...`，否则说明代码应该下沉到对应 `*_core`。

## 命名边界表

| 层次 | 命名方式 | 典型例子 | 不该这样命名 | 说明 |
| --- | --- | --- | --- | --- |
| 公开控制面 | 按 `task_type` 命名 | `detection_training_tasks.py`、`detection_conversion_tasks.py`、`detection-inference`、`detection-evaluation` | 把公开 detection 路由写成 `yolox_*_tasks.py` | 这一层面对的是平台调用方、前端和 workflow 公共入口，重点是任务分类一致。 |
| 模型实现层 | 按 `model_type` 命名 | `yolox_training_service.py`、`yolox_training_queue_worker.py`、`yolox_conversion_task_service.py`、`rfdetr_conversion_task_service.py` | 把仍然只服务 YOLOX 的训练/转换 worker 改成 `detection-training`、`detection-conversion` | 这一层承载的是模型结构、训练/转换流程、队列和执行器差异，必须明确隔离。 |
| 模型系列共享内部层 | 按模型系列命名 | `yolo_conversion_task_service_base.py`、`yolo_primary_conversion_task_service.py` | `detection_conversion_task_service.py` | 这一层允许多个同系列模型共用代码，但名字必须说明“共享范围只在这个系列里”，不能冒充全任务通用层。 |
| 模型 core 包 | 外层按 `model_type`，内部按 `task_type` | `yolov8_core/nn/tasks/detection.py`、`yolo26_core/losses/pose.py` | `yolo_core_common/detection_yolo26.py`、`detection_core.py` | core 外层表达模型代际，内部任务文件表达任务差异。 |
| 真正通用的值对象或小工具 | 用中性通用名 | `conversion_result_snapshot.py`、`TaskRecord`、`ModelBuild` | `yolox_conversion_result_snapshot.py` | 只有当类型本身不表达模型差异时，才允许用中性名。 |
| task kind / worker consumer / queue name | 谁执行就按谁命名 | `yolox-training`、`yolox-conversion`、`rfdetr-conversion` | 在实现未抽共享前统一改成 `detection-*` | 这些名字最终决定 worker 分发和执行归属，必须和真实实现边界一致。 |

## 模型 core 内部命名规则

模型 core 是模型内部实现层，不是公开 API 层。新增或迁移 core 代码时按下面规则命名：

- core 包按模型分类命名，例如 `yolov8_core`、`yolo11_core`、`yolo26_core`、`rfdetr_core`。
- core 包内部的任务目录或文件按任务分类命名，例如 `detection.py`、`segmentation.py`、`classification.py`、`pose.py`、`obb.py`。
- 真正跨 YOLOv8 / YOLO11 / YOLO26 共用的基础工具放入 `yolo_core_common`。
- `yolo_core_common` 只能放不关心 `model_type` 的基础函数、基础层和通用数学工具。
- 如果某段代码需要判断 `model_type`，它不应放在 `yolo_core_common`，应放入对应的 `yolov8_core`、`yolo11_core` 或 `yolo26_core`。
- 如果某段代码需要判断 `task_type`，优先拆成对应任务文件，不要在一个大函数里用多分支混写五类任务。

示例：

| 目标 | 推荐命名 | 不推荐命名 |
| --- | --- | --- |
| YOLO26 pose head | `yolo26_core/nn/modules/heads_pose.py` | `yolo_core_common/pose_yolo26.py` |
| YOLOv8 detection loss | `yolov8_core/losses/detection.py` | `detection_loss.py` 放在模型无关目录 |
| YOLO 通用 anchor 工具 | `yolo_core_common/utils/anchors.py` | `yolov8_core/common_anchors.py` |
| YOLO11 segmentation postprocess | `yolo11_core/postprocess/segmentation.py` | `segmentation_postprocess.py` 放在共享目录 |

## 当前已经落地的修正

- 删除了 `backend/service/application/conversions/detection_conversion_task_service.py`
- 新增了 `backend/service/application/conversions/yolo_conversion_task_service_base.py`
- 新增了 `backend/service/application/conversions/conversion_result_snapshot.py`
- classification 和 segmentation 训练路由直接改为使用 `yolo_primary_*_training_service.py`
- 删除了只做别名转发的 classification / segmentation 模型包装服务文件
- classification / segmentation evaluation 共享链改为显式使用 `SqlAlchemyYoloPrimary*EvaluationTaskService`
- evaluation runtime resolver 公共映射单独收到了 `evaluation_runtime_target_resolvers.py`
- segmentation evaluation 已补上 `rfdetr` resolver 分发；pose / obb evaluation 去掉了误写的 `yolox` 支持残留
- 保留了公开 task 路由 `backend/service/api/rest/v1/routes/detection_conversion_tasks.py`
- 保留了 YOLOX 训练和转换 worker / task kind / queue name 的模型专属命名

这次调整的核心意思是：

- `detection conversion` 作为公开入口仍然成立
- 但内部 conversion 共享层已经明确收成 `yolo conversion base`
- `yolox-conversion` 仍然是 YOLOX 自己的 task kind，不再假装已经平台化成全 detection 共用执行器

## 新增代码时的判断顺序

新增模型平台代码前，先按下面顺序判断命名：

1. 这是平台公开入口，还是内部实现？
2. 这是 `task_type` 公共规则，还是 `model_type` 差异？
3. 这层共享是不是只发生在同一个模型系列里？
4. 如果把模型名去掉，这个名字还会不会误导成“全平台已经共用”？

只有四个问题都答清楚后，再决定文件名、类名和常量名。

## 当前建议

- `detection-inference`、`detection-evaluation` 继续保留为任务分类共享名，因为实现已经是真共享。
- detection training 继续保留 `yolox-*`、`yolov8-*`、`yolo11-*`、`yolo26-*`、`rfdetr-*` 这些模型专属执行层命名。
- classification / segmentation / pose / obb 这几条非 detection 训练链，已经直接收口到 `yolo_primary_*_training_service.py` 共享实现。
- classification / segmentation evaluation 继续走 task-type 公开路由，但共享实现名明确写成 `yolo_primary_*`，避免把 YOLO 共享层误读成全平台通用层。
- deployment 这一层当前没有发现只做转发的薄壳；`detection / classification / segmentation / pose / obb deployment service` 继续保留 task-type 公共服务命名。
- `conversion` 相关层现在采用“三层分开”的写法：
  - 公开入口：`detection_conversion_tasks.py`
  - YOLO 共享层：`yolo_conversion_task_service_base.py`
  - 模型适配层：`yolox_conversion_task_service.py`、`yolov8_conversion_task_service.py`、`yolo11_conversion_task_service.py`、`yolo26_conversion_task_service.py`、`rfdetr_conversion_task_service.py`

## 后续进入条件

只有在下面条件同时满足时，才考虑把训练或转换进一步统一命名：

- 已经抽出了真实共享的基类或共享执行链
- `task kind`、worker consumer、queue name 不再绑定单一模型实现
- 至少两类不同 `model_type` 走的是同一份 service / worker / runner 主链
- 回归测试能证明不是只是“换名字”，而是真的换成共享实现
