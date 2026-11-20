# 独立模型包

独立模型包使用 `amvision.model-package.v1`，包含一个模型版本、有序类别、输入元数据及所选模型文件。ZIP 的每个文件都有大小和 SHA-256。部署实例和部署凭据不进入模型包。

所有接口使用 `/api/v1/projects/{project_id}/model-packages`，要求该项目的模型读写权限。

| 方法与路径 | 行为 |
| --- | --- |
| `GET /` | 读取项目模型包记录。 |
| `POST /exports` | 提交 `model_version_id`、`include_checkpoint`、`build_ids` 和 `file_name`，创建生成记录。 |
| `GET /{operation_id}` | 读取生成、检查或登记结果。 |
| `GET /exports/{operation_id}/download` | 下载校验完成且仍存在的 ZIP。 |
| `POST /imports` | 以 multipart `file` 上传 ZIP，提交给后台检查。 |
| `POST /imports/{operation_id}/analyze` | 以 `model_name` 新建模型，或用 `target_model_id` 追加到已有模型。可填写 `description`。 |
| `POST /imports/{operation_id}/commit` | 用最新 `analysis_revision` 和 `idempotency_key` 提交登记。相同键的重复提交回读现有结果。 |
| `DELETE /imports/{operation_id}` | 删除已结束的导入记录及上传暂存文件；保留已登记模型、版本和产物。文件占用时返回 `409`，可重试。 |
| `POST /{operation_id}/cancel` | 请求取消尚未进入登记的操作。 |

已生成的导出记录保留任务状态 `completed`。列表和详情单独提供 `file_state`：`available`（可下载）、`cleaned`（已清理）、`missing`（文件不存在）、`unavailable`（不可读或与登记大小不符）。正在生成和未生成成功的记录不返回该字段；ZIP 生成时间已知时返回 `completed_at`。读取状态不会对大文件重新计算摘要。下载仍会检查 ZIP，文件不可用时返回 `404`。

清理 ZIP 不改写任务终态，不删除源模型。旧 Worker 已标记 `expired` 且保有生成清单与摘要的记录也按完成展示。使用该记录的 `export_options` 再提交会创建新记录，Worker 会重新检查来源版本及所选产物；不会修改先前记录。

生成失败的记录可返回 `export_failure_code`（`source_invalid`、`storage_full` 或 `export_failed`）及面向用户的 `error`。系统异常和本地路径留在 Worker 日志，不通过记录返回。

后台检查清单、大小、摘要、类别顺序和必要文件。PyTorch 检查使用 `weights_only=True`。目标模型的任务、架构、规格和类别索引一致时才可追加。新版本和构建产物拥有本地 ID，源版本标识保存在来源记录中。

上传成功时记录 `uploaded_at`。首次检查未通过时，有明确检查结论的响应会提供 `import_check`（`phase`、`code`、`message`、可选的归档成员 `member`）；成员为包内相对路径，不含服务器文件路径。检查通过后的 `input_size` 用 `{width, height}` 对象表示；没有可信尺寸时省略。完成登记后的 `registered_at` 是登记时间，本地版本通过 `result.model_version_id` 获取，原包版本仍由 `source_version_id` 表示。删除记录后，列表和详情不再公开该记录；短期保留内部回执供既有提交幂等判断。

模型来源可通过 `GET /api/v1/models/catalog/{model_id}/versions/{model_version_id}/source?project_id={project_id}` 读取。训练数据集需要数据集读取权限，父版本须属于当前项目或平台基础模型。

新导出的包使用模型展示名称，并在版本来源摘要中写入 `source_version_label`。导入时目标项目按所属模型分配本地版本序号。来源包的版本标签随来源记录保留。

已提交登记但失败的导入记录会返回 `failure_stage`（`package_check`、`file_write`、`registration` 或 `unknown`）、`failure_code`（`storage_full` 或 `import_failed`）、`can_recheck` 和 `import_description`。失败记录不会返回包含本地路径的内部异常文本。暂存 ZIP 仍可用时可重新调用 `analyze`，并在复检通过后再次提交；暂存 ZIP 清理后需重新上传。登记失败会回滚本次写入的文件和登记记录。
