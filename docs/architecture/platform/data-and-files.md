# 数据与文件

## 统一边界

平台把持久化对象、主机文件和执行期大对象分成三类：

| 类型 | 标识 | 用途 |
|---|---|---|
| ObjectStore | POSIX 风格相对 object key | 平台托管、可追溯、跨执行持久化 |
| 本机文件系统 | 当前系统可解析的绝对路径 | 本地工业现场输入输出和外部目录集成 |
| LocalBuffer | `BufferRef` / `FrameRef` | 同机进程间的大图片、视频帧高性能传输 |

三类引用不能混用。ObjectStore key 不是操作系统路径；LocalBuffer 引用不是持久化文件；绝对路径只对运行进程所在主机有效。

## ObjectStore

本地部署默认使用 `LocalDatasetStorage`，根目录由 Settings 统一配置。业务代码只保存 object key，不拼接 ObjectStore 根目录。

应用层稳定端口位于 `backend/service/application/ports/object_store.py`。当前先完成 Dataset export 的任务提交、worker 执行和 artifact 写入链路收口；该链路只使用相对 key、对象写入、对象复制和 prefix 准备能力。`LocalDatasetStorage` 在 infrastructure 层按结构实现该端口。

Dataset import 的 zip staging、解压与格式解析仍需要受控本机路径，export package delivery 仍需要返回本机绝对 `save_location`。这两部分暂不塞入通用 ObjectStore 端口，避免把本地路径能力误当成可迁移对象能力。Inference 图片的 LocalBuffer 数据面不属于本次边界。

合法 key 示例：

```text
project/files/image.jpg
workflow/roi/crop-001.png
datasets/dataset-1/versions/version-3/manifest.json
```

规则：

- 使用 `/` 分隔；
- 必须是相对路径；
- 不允许 `..`、盘符或根路径；
- 由 ObjectStore 负责解析、原子替换和目录边界检查。

## 磁盘绝对路径

`image-ref.v1` 的 `local-path` transport 显式表示当前主机绝对路径。Windows 示例：

```json
{
  "transport_kind": "local-path",
  "local_path": "W:\\images\\inspection\\image.bmp",
  "media_type": "image/bmp"
}
```

绝对路径输入不会转换成 ObjectStore key，也不会复制到平台目录。调用方必须确保运行 backend-service 或 Workflow Worker 的账户对该路径有读取权限。

## 保存位置

一般保存节点统一使用 `save_location`，页面显示名称为“保存位置”：

- 相对路径：保存到 ObjectStore；
- 当前系统可解析的绝对路径：保存到本机文件系统；
- 空值：由节点定义决定是不保存、使用内存输出，还是返回缺少输入。

```text
workflow/roi           -> ObjectStore 相对位置
T:\temp\roi           -> Windows 磁盘绝对位置
/var/lib/amvision/roi  -> Linux 磁盘绝对位置
```

节点不得再公开 `output_dir`、`output_object_key` 或仅支持 ObjectStore 的 `object_key` 作为同义保存参数。已有保存型节点通过 `backend/nodes/save_locations.py` 解析并使用原子写入。

`core.io.image-save` 是明确的单文件命名例外。该节点把目录与文件名分成三个边界清晰的参数：

- `save_directory`：只表示目录，仍遵守相对 ObjectStore、绝对本机文件系统的双路径规则；可以使用 workflow 上下文和通用日期时间块形成日期目录；
- `file_name`：只表示单级图片文件名，不允许携带目录；可以使用一个或多个通用日期时间块；
- `overwrite=true`：原子替换精确目标；`overwrite=false`：重名时在扩展名前依次追加 `_001`、`_002`，并通过原子不覆盖创建避免并发调用互相覆盖。

日期时间块由通用节点工具解析，不是 Image Save 专用实现。字段大小写敏感：`Y` 支持一至四位，`M`、`D`、`h`、`m`、`s` 支持一至两位，`S` 支持一至三位；短字段从固定宽度值右侧取对应位数。`{YYYYMMDDhh}`、`{DDMMYYYY hhmmss}`、`{YY}` 和 `saveimage-{YYYY}-{MM}-{DD}-{hh}-{mm}-{ss}-{SSS}.jpg` 都是合法模板，`{DDD}`、`{YYYYY}` 必须明确失败。节点在一次执行中只读取一次 runtime 主机本地时间。未知字段、非法文件名和图片编码与扩展名不一致都必须明确失败，不自动改格式或改写路径。完整通用规则见 [节点系统](../workflows/node-system.md#通用日期时间模板)。

## 图片引用

`image-ref.v1` 支持：

- `memory`：一次执行内的图片句柄；
- `storage`：ObjectStore object key；
- `local-path`：本机绝对路径；
- `buffer`：LocalBuffer `BufferRef`；
- `frame`：LocalBuffer `FrameRef`。

Web UI 的示例输入会按公开 binding 生成相应结构。`storage` 不能携带绝对路径；绝对路径必须使用 `local-path`，从而避免把主机路径错误交给 ObjectStore 的相对路径校验。

## 数据目录职责

- `data/files/`：本地 ObjectStore 持久化对象；
- `data/amvision.db`：默认 SQLite 元数据；
- `runtime/`：进程状态、日志、临时 staging 和运行时文件；
- `models/`：平台登记的预训练或训练输出模型资产；
- `custom_nodes/`：Node Pack 源码、manifest 和包内资产；
- `release/<profile-id>/`：由 assemble-release 生成的发布结果，不作为源码手工维护。

具体根目录允许由 Settings 修改；文档和业务记录不应写入开发机器绝对仓库路径。

## 一致性与恢复

- 权威 JSON、sidecar 和 manifest 使用临时文件加原子替换；
- Workflow App bundle 保存使用 durable journal，进程中断后先恢复文件再释放 lifecycle claim；
- App Version 先创建 publishing 记录，再写 staging，启动恢复可收敛半成品；
- Project 删除使用持久 mutation fence、删除 manifest 和 tombstone，避免删除期间产生新资源；
- 临时目录只能清理已完成、已失败或无引用的 staging，不按 TTL 回收仍可能活跃的文件写入。

## 实现入口

- ObjectStore application port：`backend/service/application/ports/object_store.py`
- Local ObjectStore：`backend/service/infrastructure/object_store/local_dataset_storage.py`
- 原子文件：`backend/service/infrastructure/filesystem/atomic_files.py`
- 保存位置：`backend/nodes/save_locations.py`
- 图片引用解析：`backend/nodes/runtime_support.py`
- LocalBuffer：`backend/service/application/local_buffers/`
- Workflow bundle journal：`backend/service/application/workflows/application_bundle_journal.py`

相关设计：[LocalBufferBroker](local-buffer-broker.md)、[高性能图片数据面](image-data-plane.md)、[运行时打包](runtime-packaging.md)。
