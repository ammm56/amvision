# DatasetImport 接口文档

## 文档目的

本文档用于说明当前已实现的 DatasetImport REST 接口，包括导入、详情查询和列表查询三组能力。

本文档只描述对外可见的 FastAPI 接口规则、请求参数、响应字段、错误语义和调用示例，不展开内部 service、repository 或本地文件存储实现。

## 适用范围

- Dataset zip 导入接口
- DatasetImport 详情查询接口
- Dataset 下的导入记录列表接口
- 请求头鉴权规则
- 常见错误码和 Postman 调试方式

## 接口入口

- FastAPI Swagger UI：/docs
- FastAPI OpenAPI JSON：/openapi.json
- 版本前缀：/api/v1
- 资源分组：/datasets

## 鉴权规则

当前接口通过请求头传入主体信息与 scope。

### 最小请求头

- x-amvision-principal-id：调用主体 id
- x-amvision-project-ids：当前主体可访问的 Project id 列表，多个值用逗号分隔
- x-amvision-scopes：当前主体持有的 scope 列表，多个值用逗号分隔

### scope 要求

- 导入接口需要 datasets:write
- 查询接口需要 datasets:read

## 接口清单

### POST /api/v1/datasets/imports

上传 zip 数据集压缩包，识别并导入 COCO detection 或 Pascal VOC detection，生成 DatasetImport 和 DatasetVersion。

#### Content-Type

- multipart/form-data

#### 表单字段

- project_id：必填，所属 Project id
- dataset_id：必填，所属 Dataset id
- package：必填，zip 压缩包文件
- format_type：可选，coco 或 voc；为空时自动识别
- task_type：可选，默认 detection；当前只支持 detection
- split_strategy：可选，显式指定 split 策略
- class_map_json：可选，JSON 对象字符串，例如 {"7":"bolt"}

#### 成功响应

- 状态码：201 Created

```json
{
  "dataset_import_id": "dataset-import-70395b542a6f",
  "dataset_version_id": "dataset-version-fddb0ec579b2",
  "format_type": "coco",
  "task_type": "detection",
  "status": "completed",
  "sample_count": 1,
  "category_count": 1,
  "split_names": ["train"],
  "package_path": "projects/project-1/datasets/dataset-1/imports/dataset-import-70395b542a6f/package.zip",
  "staging_path": "projects/project-1/datasets/dataset-1/imports/dataset-import-70395b542a6f/staging/extracted",
  "version_path": "projects/project-1/datasets/dataset-1/versions/dataset-version-fddb0ec579b2"
}
```

#### 失败响应

- 400：请求字段不完整、class_map_json 不是合法 JSON、zip 内容非法
- 401：缺少主体信息
- 403：主体没有 datasets:write scope，或 project_id 不在可访问范围内
- 422：当前数据格式或 task_type 不支持
- 503：持久化或数据库操作失败

### GET /api/v1/datasets/imports/{dataset_import_id}

按 DatasetImport id 查询导入记录详情，返回导入记录、校验报告、识别结果和关联 DatasetVersion 摘要。

#### 路径参数

- dataset_import_id：必填，导入记录 id

#### 成功响应

- 状态码：200 OK

```json
{
  "dataset_import_id": "dataset-import-70395b542a6f",
  "dataset_id": "dataset-1",
  "project_id": "project-1",
  "format_type": "coco",
  "task_type": "detection",
  "status": "completed",
  "created_at": "2026-04-29T02:04:11.080006+00:00",
  "dataset_version_id": "dataset-version-fddb0ec579b2",
  "package_path": "projects/project-1/datasets/dataset-1/imports/dataset-import-70395b542a6f/package.zip",
  "staging_path": "projects/project-1/datasets/dataset-1/imports/dataset-import-70395b542a6f/staging/extracted",
  "version_path": "projects/project-1/datasets/dataset-1/versions/dataset-version-fddb0ec579b2",
  "image_root": "train",
  "annotation_root": "annotations",
  "manifest_file": "annotations/instances_train.json",
  "split_strategy": "manifest-name",
  "class_map": {
    "0": "bolt"
  },
  "detected_profile": {
    "detected_candidates": ["coco"],
    "format_type": "coco",
    "task_type": "detection",
    "manifest_files": ["annotations/instances_train.json"],
    "image_root": "train",
    "annotation_root": "annotations",
    "split_names": ["train"],
    "split_counts": {
      "train": 1
    }
  },
  "validation_report": {
    "status": "ok",
    "format_type": "coco",
    "task_type": "detection",
    "category_count": 1,
    "sample_count": 1,
    "split_counts": {
      "train": 1
    },
    "warnings": [],
    "errors": []
  },
  "error_message": null,
  "metadata": {
    "source_file_name": "coco-dataset.zip",
    "package_size": 552,
    "principal_id": "user-1",
    "sample_count": 1,
    "category_count": 1,
    "split_counts": {
      "train": 1
    }
  },
  "dataset_version": {
    "dataset_version_id": "dataset-version-fddb0ec579b2",
    "dataset_id": "dataset-1",
    "project_id": "project-1",
    "task_type": "detection",
    "sample_count": 1,
    "category_count": 1,
    "split_names": ["train"],
    "metadata": {
      "source_import_id": "dataset-import-70395b542a6f",
      "format_type": "coco",
      "image_root": "train",
      "annotation_root": "annotations",
      "manifest_file": "annotations/instances_train.json",
      "split_strategy": "manifest-name",
      "split_counts": {
        "train": 1
      }
    }
  }
}
```

#### 失败响应

- 401：缺少主体信息
- 403：主体没有 datasets:read scope
- 404：找不到指定的 DatasetImport，或当前主体对其所属 Project 不可见
- 503：持久化或数据库操作失败

### GET /api/v1/datasets/{dataset_id}/imports

按 Dataset id 返回当前数据集下的导入记录摘要列表。

#### 路径参数

- dataset_id：必填，Dataset id

#### 成功响应

- 状态码：200 OK

```json
[
  {
    "dataset_import_id": "dataset-import-70395b542a6f",
    "dataset_id": "dataset-1",
    "project_id": "project-1",
    "format_type": "coco",
    "task_type": "detection",
    "status": "completed",
    "created_at": "2026-04-29T02:04:11.080006+00:00",
    "dataset_version_id": "dataset-version-fddb0ec579b2",
    "package_path": "projects/project-1/datasets/dataset-1/imports/dataset-import-70395b542a6f/package.zip",
    "staging_path": "projects/project-1/datasets/dataset-1/imports/dataset-import-70395b542a6f/staging/extracted",
    "version_path": "projects/project-1/datasets/dataset-1/versions/dataset-version-fddb0ec579b2",
    "validation_status": "ok",
    "error_message": null
  }
]
```

#### 失败响应

- 401：缺少主体信息
- 403：主体没有 datasets:read scope
- 503：持久化或数据库操作失败

## 错误响应格式

接口统一返回如下错误结构：

```json
{
  "error": {
    "code": "resource_not_found",
    "message": "找不到指定的 DatasetImport",
    "details": {
      "dataset_import_id": "dataset-import-missing"
    },
    "request_id": "80d2eed6-e094-4f75-8cbf-01e32293a088"
  }
}
```

## 常见错误码

- authentication_required：缺少请求主体
- permission_denied：缺少所需 scope 或 Project 不可访问
- invalid_request：请求字段错误、zip 内容非法、class_map_json 非法
- unsupported_dataset_format：当前数据格式或 task_type 不支持
- resource_not_found：导入记录不存在或当前主体不可见
- persistence_operation_error：数据库或持久化操作失败

## 调试建议

- 本地调试时优先先调用导入接口，再把响应里的 dataset_import_id 填给详情查询接口
- 如果导入失败，先看详情接口里的 validation_report 和 error_message
- 如果需要用 Postman 直接调试，可导入 [docs/api/postman/datasets-imports.postman_collection.json](postman/datasets-imports.postman_collection.json)