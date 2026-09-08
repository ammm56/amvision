# 资源删除

范围和维护方式见[当前实现与验收边界](../development/resource-deletion-implementation.md)。删除训练任务同时删除其未使用模型产物；存在依赖时整个操作被阻止。

## 同步删除

已有导入、导出、训练、转换、评估、部署 DELETE 保持 `204` 表示清理完成。新增 `DELETE /api/v1/tasks/{task_id}` 处理终态任务及其拥有资源；`DELETE /api/v1/datasets/versions/{dataset_version_id}` 删除版本，`DELETE /api/v1/datasets/{dataset_id}?project_id=...` 删除数据集。

提交前失败保留原记录和目录；提交后物理清理失败返回错误，并保留可查询、可重试的操作。尚未完成的同目标请求继续使用原操作。

## 异步受理

`POST /api/v1/resource-deletions`：

```json
{"format_id":"amvision.resource-deletion-request.v1","kind":"task","resource_id":"task-id","project_id":"project-id"}
```

kind 支持 task、dataset、dataset-version、dataset-import、dataset-export。不接受额外字段、磁盘路径或客户端清单。成功返回 `202`，包含 operation_id、project_id、resource_kind、resource_id、state、error。受理已完成依赖检查、暂存和数据库删除，队列及物理清理可以尚未完成，不能显示为“已全部删除”。

| state | 含义 |
| --- | --- |
| prepared | 清单已持久化，业务记录尚未提交删除 |
| committed | 记录已删除，清理未完成；error 说明失败原因 |
| completed | 所有清理完成，短期保留回执 |
| rolled_back | 提交前失败已恢复，短期保留回执 |

- `GET /api/v1/resource-deletions?project_id=...`：授权范围内未完成操作。
- `GET /api/v1/resource-deletions/{operation_id}`：状态；回执过期后 `404`，不能单独据此推断完成。
- `POST /api/v1/resource-deletions/{operation_id}/retry`：同步重试，完成才返回 `204`。

Task 需要 tasks:write，数据集需要 datasets:write，部署清理查询与重试需要 models:write，同时检查 Project 访问范围。鉴权与错误包沿用[通用约定](conventions.md)。依赖阻塞返回 `409`，details.blockers 包含资源类型、id、状态或引用；转换保留 protected_builds。前端显示具体依赖，解除后可重新删除。

自动清理消费者位于 dataset-export Worker profile，更新后须重启 Worker。刷新和 API 重启不丢失未完成清单。完成回执最多一天、最近 1000 项；未完成项不按时间丢弃。文件占用、权限失败、无法确认归属均不能被当作成功。
