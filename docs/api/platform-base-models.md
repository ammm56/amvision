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
- 转换提交在创建 Task 和 Queue Outbox 前解析并检查来源版本、文件和输入契约。页面仅执行已登记字段的选择校验，磁盘文件存在性和内容一致性仍由后端检查。
- 本次 `/api/v1` 响应新增版本级 `labels_file_id`、`labels_storage_uri` 两个可空字段，不改变持久化结构，不需要数据库迁移。checkpoint-only 预训练引用仍可用于 warm start；损坏或冲突的类别映射不再被静默忽略。
