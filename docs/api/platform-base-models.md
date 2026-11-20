# 平台基础模型接口文档

## 文档目的

本文档用于说明当前已经公开的平台基础模型列表与详情接口，以及这些接口如何为 warm_start_model_version_id 提供正式查询面。

本文档只描述当前真实实现，不展开未来模型市场、权限分层或发布流程规划。

## 适用范围

- 平台基础模型列表接口
- 平台基础模型详情接口
- 平台基础模型与 Project 内模型的公开边界
- warm_start_model_version_id 的发现方式

## 接口入口

- FastAPI Swagger UI：/docs
- FastAPI OpenAPI JSON：/openapi.json
- 版本前缀：/api/v1
- 资源分组：/models

## 鉴权规则

### 最小请求头

- Authorization: Bearer <token>
- 使用当前环境实际 Bearer token

### scope 要求

- models:read

## 接口清单

### 项目模型目录

`GET /api/v1/models/catalog` 需要 `models:read` 权限和可访问的 `project_id`。可选参数为 `query`（名称包含搜索）、`task_type`、`offset`（默认 0）和 `limit`（默认 20，最大 200）。响应的 `items` 是当前页，`total` 是筛选后的总数；项目内尚无版本或产物的模型也会返回。`build_formats` 列出模型已登记的转换格式，不代表文件已通过可用性检查。平台基础模型不在此目录中。

`GET /api/v1/models/catalog/{model_id}?project_id=...` 返回当前项目模型的版本、文件及转换产物。项目外模型返回 404。版本摘要和详情均提供 `version_number`，在所属模型内从 1 递增，显示为 `v1`、`v2`。使用最大序号确定最新版本。删除后保留序号缺口。请求路径和关系仍使用 `model_version_id`。

Alembic 迁移 `1c92ab5f486e` 为历史版本补号。已有完整且唯一的版本序号优先保留，其余按可用登记时间和同模型的父版本顺序排列。迁移也为历史技术名称补充展示名称，保留已编辑的名称及模型登记名称。训练输出可使用项目内唯一且同规格的展示名称追加版本。

`GET /api/v1/models/catalog/{model_id}/versions/{model_version_id}/references` 返回当前项目中直接绑定该版本的部署。可用 `query` 按部署名称或 id 搜索，`offset` 和 `limit` 分页（默认 6，最大 100）。`total` 为筛选后的直接引用总数；`runtime_states` 分别提供已记录的 sync 和 async 观察状态，缺少模式时不推断为停止。间接 Workflow 引用不计入结果。

`GET /api/v1/models/catalog/{model_id}/versions/{model_version_id}/files/{file_id}/status` 检查该版本或其转换产物中已登记的本地文件。`state` 为 `present`、`missing` 或 `unavailable`，前者只说明检查时普通文件存在，不能替代内容完整性或设备兼容性校验；存在时 `size_bytes` 给出文件大小。无项目权限返回 403，不属于指定模型版本的文件返回 404。

同一路径将末尾 `status` 改为 `download` 可下载指定的单个登记文件。下载需要 `models:read` 和项目访问权限，传输期间持有项目读取声明，文件缺失返回 404。该接口不打包同一产物的其他文件。

展开文件摘要时可传入 `include_sha256=true`，响应中的 `sha256` 为本次读取计算所得。历史 OpenVINO 产物的 BIN 如果登记在构建元数据中，可在 XML 对应的状态或下载请求上使用 `part=weights`。服务端只接受该构建同目录、同名的 BIN。状态响应同时返回 `part: "weights"`。

### GET /api/v1/models/platform-base

列出当前可见的平台基础模型。

#### 查询参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| model_name | string \| null | 否 | 模型名筛选。 |
| model_scale | string \| null | 否 | 模型 scale 筛选。 |
| task_type | string \| null | 否 | 任务类型筛选。 |
| limit | integer | 否 | 最大返回数量，默认 100，最大 200。 |

#### 列表边界

- 当前列表只返回 scope_kind=platform-base 的 Model。
- 当前列表不会混入任何 Project 内模型。
- 当前平台基础模型的 project_id 固定为空，不再使用保留 Project 占位值表达平台语义。
- 当前是否能看到某个模型族，取决于启动期 seeder 是否已从本地 `models/pretrained/yolox/detection` 或 `models/pretrained/{yolov8,yolo11,yolo26,rfdetr}` 成功登记对应 manifest；接口本身不限定只返回 YOLOX。

#### 当前列表项重点字段

- model_id：平台基础模型 id。
- model_name / model_scale / task_type：模型识别字段。
- scope_kind：当前固定为 platform-base。
- version_count：当前模型关联的 ModelVersion 数量。
- build_count：当前模型关联的 ModelBuild 数量。
- available_versions：可直接用于 warm start 选择的版本摘要列表。

#### available_versions 当前公开字段

- model_version_id：可直接填入 warm_start_model_version_id。
- source_kind：版本来源类型，当前预训练目录登记值为 pretrained-reference。
- checkpoint_file_id：checkpoint 对应的 ModelFile id。
- checkpoint_storage_uri：checkpoint 存储 URI。
- labels_file_id / labels_storage_uri：当前 ModelVersion 自己的类别映射文件；没有登记时为空。不能使用 Model 顶层或其他版本的 labels 文件替代。
- catalog_manifest_object_key：预训练目录 manifest 的 object key。

#### 成功响应示例

```json
[
  {
    "model_id": "model-5f9f3b6d66b5",
    "project_id": null,
    "scope_kind": "platform-base",
    "model_name": "yolox",
    "model_type": "yolox",
    "task_type": "detection",
    "model_scale": "nano",
    "labels_file_id": null,
    "metadata": {
      "catalog_name": "default",
      "catalog_manifest_object_key": "models/pretrained/yolox/detection/nano/default/manifest.json",
      "source_kind": "pretrained-reference"
    },
    "version_count": 1,
    "build_count": 0,
    "available_versions": [
      {
        "model_version_id": "model-version-pretrained-yolox-nano",
        "source_kind": "pretrained-reference",
        "dataset_version_id": null,
        "training_task_id": null,
        "parent_version_id": null,
        "file_ids": [
          "model-file-pretrained-yolox-nano-checkpoint"
        ],
        "metadata": {
          "catalog_name": "default",
          "catalog_manifest_object_key": "models/pretrained/yolox/detection/nano/default/manifest.json",
          "source_kind": "pretrained-reference"
        },
        "checkpoint_file_id": "model-file-pretrained-yolox-nano-checkpoint",
        "checkpoint_storage_uri": "models/pretrained/yolox/detection/nano/default/checkpoints/yolox_nano.pth",
        "catalog_manifest_object_key": "models/pretrained/yolox/detection/nano/default/manifest.json"
      }
    ]
  }
]
```

### GET /api/v1/models/platform-base/{model_id}

返回单个平台基础模型详情。

#### 当前详情重点字段

- 顶层 Model 字段：model_id、scope_kind、model_name、model_type、task_type、model_scale、metadata。
- available_versions：便于列表页或选择器直接展示的版本摘要。
- versions：当前模型下所有 ModelVersion 的完整明细。
- builds：当前模型下所有 ModelBuild 的完整明细。

#### 当前 versions 重点字段

- model_version_id：当前版本 id。
- source_kind：版本来源类型。
- checkpoint_file_id / checkpoint_storage_uri：可直接定位 warm start 权重。
- labels_file_id / labels_storage_uri：当前版本的有序类别映射文件。
- catalog_manifest_object_key：可定位到预训练目录 manifest。
- files：当前版本关联的全部文件明细。

#### 当前 builds 重点字段

- model_build_id：当前构建 id。
- source_model_version_id：来源 ModelVersion id。
- build_format：构建格式。
- files：当前构建关联的全部文件明细。

#### 错误语义

- 当 model_id 不存在时返回 404。
- 当 model_id 对应的是 Project 内模型时也返回 404，不通过这个接口暴露非平台基础模型。

## 与训练接口的关系

- 平台基础模型接口本身不创建训练任务，也不修改模型内容。
- 当前推荐流程是先调用 GET /api/v1/models/platform-base 或 GET /api/v1/models/platform-base/{model_id}，拿到 available_versions[].model_version_id。
- 然后把这个 model_version_id 传给统一模型任务入口的训练入口，例如 `POST /api/v1/models/detection/training-tasks`，并在请求体里通过 `model_type` 选择具体模型实现。

## 当前能力边界

- 当前只公开读取能力，不公开平台基础模型创建、修改、删除接口。
- 当前列表和详情返回的是数据库已登记的模型，不负责扫描磁盘或触发 seeder。
- 当前平台基础模型接口不混入 Project 内模型，也不承担训练任务列表功能。
- 只有 checkpoint、没有类别映射的预训练引用用于训练初始化，不能直接转换、部署或推理。不得根据训练数据集、目录名或参考仓库补造类别名称。
- 转换页面从 `/api/v1/models/deployment-sources` 返回的实际模型版本中选择来源，不通过预训练模型的名称、参数量或父版本关系代替来源 ModelVersion。已明确登记类别映射的预训练版本也可以成为转换来源。
- 版本必须登记类别文件或非空的 `metadata.category_names` 有序列表。两者同时存在时顺序和内容必须一致；空条目、非字符串条目和重复类别均拒绝，不能过滤条目后改变输出 class id。
- 转换提交在创建 Task 和 Queue Outbox 前解析并检查来源版本、文件和输入契约。页面选择时使用版本摘要的文件状态；提交时后端仍会重新检查文件和内容一致性。
- 本次 `/api/v1` 响应新增版本级 `labels_file_id`、`labels_storage_uri` 两个可空字段，不改变持久化结构，不需要数据库迁移。checkpoint-only 预训练引用仍可用于 warm start；损坏或冲突的类别映射不再被静默忽略。
# 基础模型文件状态

`GET /api/v1/models/platform-base` 和 `GET /api/v1/models/deployment-sources` 的版本摘要包含 `checkpoint_state`：`present` 表示登记的本地文件存在，`missing` 表示文件缺失，`unavailable` 表示路径无法检查，`null` 表示未检查。该字段不代表文件完整性或设备兼容性；训练和转换执行时仍会重新读取和校验权重。

`GET /api/v1/models/{task_type}/conversion-tasks/{task_id}/report/download` 下载转换任务登记的报告，支持 detection、classification、segmentation、pose 和 obb。接口要求 `tasks:read`，检查项目可见性、任务类型和报告的受管目录归属，并在传输期间阻止所属项目资源删除。TensorRT 任务因输出数值超限而失败且保留校验明细时，此接口返回诊断 JSON（`status: failed`、`published: false` 和 `numeric_validation`）；诊断按校验输入列出超限依据，不包含引擎或本地绝对路径。其他缺少报告的任务返回 404。

`GET /api/v1/models/{task_type}/conversion-tasks/{task_id}/builds/{build_id}/{part}/download` 下载该任务登记的构建文件，`part` 为 `primary` 或 `weights`；OpenVINO 的 XML 和 BIN 分别下载。该接口使用相同的任务权限和归属检查，仅允许读取该任务的构建目录，文件缺失或未登记时返回 404。

`POST /api/v1/models/{task_type}/conversion-tasks/preview` 对 `project_id`、`model_type`、`source_model_version_id`、`target` 和可选 `runtime_profile_id` 执行与提交相同的来源及方案检查，返回目标格式和计划步骤。支持 detection、classification、segmentation、pose 和 obb，要求 `models:read` 和项目访问权限。预检不创建任务或改变模型，也不检测执行设备与工具链；实际提交时会再次检查来源和方案。

YOLOX、YOLOv8、YOLO11 和 YOLO26 支持转换选择 ONNX Opset 18 或 19。预检使用 `onnx_opset_version`，创建接口将同一值放入 `extra_options.onnx_opset_version`。不传该字段时保留原导出行为。RF-DETR 保持固定 Opset，使用此覆盖参数会被拒绝。

YOLO11 detection 转换为原始 ONNX 时可在预检传 `input_shape_mode: "dynamic-batch"`，并在创建时将相同值放入 `extra_options.input_shape_mode`。ONNX 文件的批次轴是符号维度，空间宽高仍来自登记契约。报告列出数值校验覆盖的批次数。其他组合保留固定输入。动态宽高和 INT8 校准请求会在预检及提交时被拒绝。

`DELETE /api/v1/models/{task_type}/conversion-tasks/{task_id}/record` 清理终态转换任务的记录、事件和专属运行文件，保留已经登记的构建及文件，包括部署引用和原转换来源标识。要求 `models:write` 和 `tasks:write`，并校验项目可见性。成功返回 204，任务仍有运行占用或操作依赖时阻止删除。原 `DELETE /api/v1/models/{task_type}/conversion-tasks/{task_id}` 继续提供含未被引用产物在内的删除操作。删除记录后可从模型版本目录下载该版本登记的转换产物。

`POST /api/v1/models/{task_type}/training-tasks/preview` 接收与创建训练相同的请求，核对输出名称与系列、训练和验证划分及清单列出的文件和目录。指定初始化权重时检查文件可用性，存在登记的 SHA-256 时比较文件摘要。成功返回导出 ID、版本、格式、已登记划分数量及 `checks`。资源检查失败沿用 HTTP 状态与错误码，`error.details.checks` 包含独立检查结果。要求 `datasets:read` 和 `tasks:write`。

每项检查包含 `check`（`dataset_export`、`initialization`、`output_model`、`environment`）和 `status`（`passed`、`failed`、`skipped`、`deferred`）。失败项可附带 `message` 和相对导出根目录的 `missing_files`。执行设备由 Worker 在实际运行时确认。预检仅报告其执行的检查，不锁定资源。

恢复预检失败时，`error.details.resume_check` 标明已定位的原因（`task`、`checkpoint` 或 `dataset`）。预检核对状态、检查点的文件可读性和原导出可用性，实际恢复由 Worker 校验检查点中的优化器、调度器与轮次。

`GET /api/v1/models/{task_type}/training-tasks/{task_id}/resume/preview` 检查可见任务的恢复状态、原导出清单及最新检查点的文件可读性，返回检查点文件名和导出 ID。要求 `tasks:write`。实际恢复继续使用原 resume 接口，Worker 负责验证检查点格式和训练状态。

转换来源必须与请求的模型类型和任务类型一致；不一致时预检和提交均返回错误，且不会创建任务。旧任务在执行前同样会校验模型类型。

## 项目模型展示信息与版本删除

`PUT /api/v1/models/catalog/{model_id}/presentation?project_id=...` 更新项目模型的 `display_name` 和 `description`。请求需包含非负 `expected_revision`；使用旧 revision 修改返回 409。成功更新同时在已有 metadata 写入 `presentation_revision` 和 UTC 时间 `presentation_updated_at`。未曾更新的历史模型可能没有更新时间。登记名称 `model_name`、模型身份及版本归属保留。目录搜索同时匹配展示名称和登记名称。平台基础模型不能通过此接口修改。

删除项目模型版本前，使用 `GET /api/v1/resource-deletions/preview?kind=model-version&resource_id=...&project_id=...` 检查依赖和删除范围。返回的 revision 必须随 `POST /api/v1/resource-deletions` 一同提交。`has_file_cleanup` 表示删除计划中是否有需要清理的文件路径。服务端在提交时再次检查依赖与 revision，依赖未解除或范围变化时返回 409。停止部署仍保留引用，跨项目引用身份保持私有。

删除移除目标版本、所属转换产物及其文件登记。保留其他版本、训练和转换任务记录，以及归任务所有的磁盘文件。关联训练任务的 `metadata.deleted_model_version_ids` 记录本次删除的版本 ID，原始训练结果保留。专属于该版本的受管导入文件按异步清理流程处理。无法确认所有权或文件仍被其他资源引用时阻止删除。
