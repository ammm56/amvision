# 三维配方携资源导入导出

## 使用范围

配方包包含当前 Workflow App、嵌入 Template、直接引用的固定点云版本和全部父点云依赖。复用现有点云资产 ZIP、App 保存事务和发布系统，不建立另一套配方或资源管理。

图编辑器空白处菜单提供“导出三维配方资源包”和“从三维资源包新建配方”。普通“导出工作流/导入工作流”仍只处理 JSON。资源包导入创建新草稿，不覆盖当前配方、不自动发布或启动；导入成功后可沿原 Preview、保存、发布和 Runtime 操作使用。当前编辑内容未保存时，打开导入结果前单独确认，取消打开不会删除已导入草稿。

仅打包固定 `point-cloud` 资源。调用时文件/数组仍由调用方提供；临时 Run/LocalBuffer 引用、对象路径、模型、部署、外部规则及二维计量资源不由该包搬运，出现未支持的固定依赖会拒绝，不静默丢弃。节点代码、依赖 wheel、凭据、发布身份、Runtime、历史结果和显示索引不在包内；目标需安装并启用相应节点，发布仍执行本机正常身份和依赖校验。源文件格式和三维契约保持 v1。

## API

共同前缀为 `/api/v1/workflows/projects/{project_id}/application-packages`，使用平台鉴权和 Project 可见性。精确字段以当前 OpenAPI 和 [Python 契约](../../backend/contracts/workflows/cloud_package.py)为准。

| 操作 | 请求 | 返回 |
| --- | --- | --- |
| `POST /export` | `workflows:read`；JSON 为 `amvision.workflow-app-document.v1`，包含 `application`、`template` | ZIP，文件名 `workflow-cloud-package.zip`；包含当前编辑文档，不隐式保存草稿 |
| `POST /import` | `workflows:write`；`Content-Type: application/zip`；原始 ZIP 请求体；必填 `Idempotency-Key` | 201；新 `application_id`、`template_id`、`resource_mapping` |

`resource_mapping` 的每项为 `{source, target}`，双方均为完整 `ResourceReference`，包含项目、资源、版本、内容摘要和类型；列表包含间接父依赖。目标资产均为新资源的 v1，不要求源/目标使用相同路径或资源 ID。

`Idempotency-Key` 为 1–128 个 ASCII 字符，首位字母或数字，其余允许字母、数字、下划线、点和连字符。相同用户、项目、请求键对应同一个导入目标；成功后重试返回 409，`error.details.application_id` 指向已导入结果，不重复创建。新键表示主动另建一份。网络中断后应先用同一键核对，不能立即换键重试。

无效归档、超限、摘要不符、缺失/额外依赖返回 400；权限不足返回 403；资源正被修改、目标已存在等冲突返回 409；缺少显式点云容量配置时拒绝。恢复失败保留事务日志与恢复准入，不伪报成功。错误使用平台 `error.code/details`，不解析中文文案。

## 格式与预算

包为 ZIP_STORED：

```text
package.json
resources/0.zip
resources/1.zip
...
```

`package.json` 的格式为 `amvision.workflow-cloud-package.v1`，字段为 `format_id`、`document`、`resources`。每项资源声明 `reference`、`name`、`byte_length`、`sha256`；路径由资源序号生成，父项必须在子项之前。内层 ZIP 继续使用既有点云资产格式，不创建新的二进制布局。

- 直接与间接依赖去重后最多 64 个版本，文档最多 16 MiB；均为明确拒绝边界。
- 整包使用现有 `workflow_runtime.point_cloud.max_archive_bytes`，不为导入另设隐式生产数值。现有 capabilities API 返回实际上限。整包上限与每次 Workflow 输入 1 GB 的限制不是同一概念。
- 包内点云逐个使用现有资产布局、单资产大小、原始行号和字段校验。禁止重复、压缩、加密、目录/链接及未知成员；固定成员集合，不按客户端路径解压。
- API 按块暂存磁盘和校验，不在请求事件循环执行几何算法；导出完成归档后才发送响应。浏览器下载使用 Blob，此次页面验收约 177 MB，不声明近 1 GB 浏览器峰值已经通过。

## 映射、取消与恢复

依赖按完整引用解析，校验同版本摘要、项目归属、父依赖与循环。导入先暂存全部资源，逐级映射父引用及 provenance 摘要，再替换 read-cloud/export-cloud 的资产来源和 save-cloud 的已有版本目标。坐标、字段 dtype、源行号、拓扑、边界特征及二进制 blob 不改变；含父引用的内容摘要会因新身份而重新计算，不能强求所有资产内容摘要原样不变。

复用 App bundle journal 和项目资源非等待锁：先登记本事务创建的确定性资源路径，再校验、移动资源，保存 Template/App，最后写持久提交标记。标记前取消或失败恢复权威文档并删除本事务新资源；标记后清理中断只继续清理，不能回滚已提交对象。进程硬退出由原启动恢复完成，恢复失败保留准入限制。并发管理写入明确冲突，不新增等待队列；普通资源列表不是跨文件可串行化快照。

前端取消、切项目/配方、卸载会中止请求并屏蔽迟到响应。取消不等于撤销已经落盘的提交；若响应丢失而服务端已提交，沿同键查重处理。导入不会携带源机器的发布版本，在目标审核后正常重新发布。

实现、双平台验证和页面证据见 [A10 实施记录](../development/3d-metrology-cloud-package.md)。
