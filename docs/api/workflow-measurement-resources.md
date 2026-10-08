# Workflow 计量资源 API

基础路径：`/api/v1/workflows/projects/{project_id}/measurement-resources`。读操作要求 `workflows:read`，写操作要求 `workflows:write`，均校验项目范围。

| 方法/相对路径 | 用途 |
| --- | --- |
| GET `/` | 列出当前项目已提交的资源版本 |
| POST `/` | multipart：name、content JSON、可选 resource_id、可选 image PNG；创建资源或新版本 |
| POST `/import` | multipart：name、archive ZIP；导入为当前项目的新资源 |
| GET `/{resource_id}/versions/{version}` | 读取不可变版本及引用 |
| GET `/{resource_id}/versions/{version}/image` | 读取已授权的完整参考 PNG |
| GET `/{resource_id}/versions/{version}/export` | 生成指定版本的资源 ZIP |
| DELETE `/{resource_id}/versions/{version}` | 无草稿或发布引用时删除；有引用返回冲突，损坏引用文档时拒绝删除 |

基础路径端点不要求末尾 `/`。固定版本引用为 `project_id/resource_id/version/sha256/kind`；kind 为 `localization-template` 或 `planar-calibration`。JSON content 的 format_id 为 `amvision.measurement-resource.v1`，两种类型分别只填写 template 或 calibration；具体 Schema 由 OpenAPI 与 Pydantic 契约定义。

保存版本不会覆盖历史资源。定位模板必须包含参考图尺寸、template_roi `[x,y,width,height]`、原图坐标 anchor、reference_id 和 image_sha256。图像需为不超过 64 MiB 的 PNG；原图不超过 1600 万像素，模板区域不超过 200 万像素。平面标定不携带图像二进制；Planar Calibrate 生成的映射附带控制点和独立验证点证据。

资源包仅允许 `resource.json` 和可选 `reference.png`，校验条目、展开容量、CRC 和内容 hash，不解压任意客户端路径。跨项目导入后需重新绑定新的资源引用；已有 Workflow JSON 导出仍不包含二进制资源。

资源管理冲突直接返回，不进入推理任务队列。引用存在返回 409；文件占用、权限或空间错误返回 503 `persistence_operation_error`，包含 errno/winerror；处理外部文件问题后可重新提交删除。删除凭据保留版本身份，版本号不复用。

Runtime 准备时验证并缓存引用资源；旧工作流无这些引用时不读取资源。模板/标定更新必须保存并重新发布新版本，禁止手动修改运行中的资源目录。
