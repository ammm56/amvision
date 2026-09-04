# Workflow 本地文件选择与读取

## 调用边界

目录 Trigger 观察变化并按现有窗口提交调用；Workflow 节点只在调用时执行，不启动 watcher/定时线程，不保存“上次文件”，不等待、重试或静默改读次新文件。Runtime、Trigger、HTTP、ZeroMQ、共享内存协议不变。

两种通用编排独立使用：

- 当前最新结果：`Directory Latest File → Load Local Image / JSON / Text`，无需 request_json。
- 变化样本：可选 `request_json → Coalesce → Extract Value Field(samples) → Filter List → For Each → Extract Value Field(path) → Load Local …`。

事件样本是有数量上限的变化通知，不是完整可靠队列。删除样本不能读取；示例显式排除 `observed_change_types` 包含 `deleted` 的样本。App Entry 的 request_json 保持可选，示例用 Coalesce 的 `fallback_value={"samples":[]}` 处理未提交输入，不在平台层强制必填。

## Directory Latest File

节点 id：`core.io.directory-latest-file`。参数为 `directory_path`、`recursive=false`、`include_hidden=false`、`glob_pattern="*"`、`extensions=[]`、`min_stable_age_seconds=0`。Path 是显式可选动态目录参数输入。

- 最新按文件修改时间 mtime 纳秒排序，不按文件名、创建时间或 Trigger 观察顺序。同时间按规范化绝对路径倒序，最后使用原路径作为平局键；Windows 路径比较不区分大小写。
- File 输出是 value.v1 包装的完整文件记录；空目录或过滤后无匹配输出 null。
- Summary 包含 `state=found/no_files`、目录和过滤设置、`raw_count/count/unstable_skipped_count/missing_skipped_count`。
- 目录不存在、不可读、配置非法时报错，不当作空目录。File=null 必须用显式条件/列表编排决定是否继续读取。
- 最小文件年龄只过滤 mtime，不保证写入已经完成；0 表示不等待。生产写入应采用原子完整发布，现有 Save 节点已使用该方式。

Directory Scan 复用同一记录与选择实现，保留 Files/Summary。普通文件名 Glob（例如 `*.json`）采用流式 scandir；`limit=K,dedupe_by=none` 的候选存储为 O(K)，Latest 固定 K=1，扫描时间仍为 O(N)。相对路径 Glob（例如 `sub/*.json`、`**/*.json`）保留 pathlib 匹配语义，其枚举内存不承诺 O(K)。未设 limit 或显式去重时仍可能保留全量结果/去重信息。

不遍历符号链接文件、链接目录和 Windows junction，避免递归环与隐含跨目录扫描。扫描中消失的文件计入 missing_skipped_count；不可读错误中止扫描。扫描循环检查已有取消/deadline；正在阻塞的操作系统文件调用不能由该检查强制中断。

## 通用文件记录

本地记录通过 value.v1 传递，List、ForEach、Extract Value Field、Object 节点可直接使用：

```json
{
  "format_id": "amvision.local-file-record.v1",
  "path": "T:/results/result.json",
  "file_name": "result.json",
  "extension": ".json",
  "size_bytes": 128,
  "modified_time_epoch_ms": 1788480000000,
  "modified_time_epoch_ns": "1788480000000000000",
  "modified_time_iso": "2026-09-04T00:00:00+00:00",
  "observed_version": {
    "device": "123", "inode": "456", "size_bytes": 128,
    "modified_time_ns": "1788480000000000000"
  }
}
```

纳秒和文件身份使用十进制字符串，避免经过浏览器 JSON 丢失整数精度。观察版本不是内容哈希、不可变快照或锁：刻意保持同身份、大小和 mtime 的原地改写不在检测保证内。Windows stat/fstat 的 ctime 含义存在差异，不参与比较。

任意本地路径不转换为 file-ref.v1；后者仍专用于 ObjectStore 不可变文件引用。File Read Text/JSON 和本地读取节点的输入边界不同。目录事件样本只携带路径，不是完整文件记录，须明确提取 path 接到 Path 输入。

## Load Local Image / JSON / Text

三个节点统一支持可选 File 记录输入和 Path 字符串参数输入，File 与 Path 连线互斥；均未连接才使用固定 local_path。连接 File 后即使为空也报错，不退回固定参数。

File 在打开后检查 observed_version；Path 表示读取执行时该路径的当前文件。从同一文件句柄限量读取后，再核对句柄/路径身份、大小和 mtime；变化、删除、超限均明确失败，不重试。Summary 保留 local_path 并附实际读取记录，业务输出继续使用 image-ref.v1、value.v1、text.v1，不增加业务结果包装。

| 节点 | 公开参数 | 默认值 |
| --- | --- | --- |
| Load Local Image | max_bytes / max_pixels | 64 MiB / 100,000,000 像素 |
| Load Local JSON | max_bytes；固定 UTF-8 | 1 MiB |
| Load Local Text | max_bytes / charset | 1 MiB / utf-8 |
| Load Local Image List | max_bytes / max_total_bytes / max_pixels | 单文件 64 MiB / 总计 64 MiB / 单图 100,000,000 像素 |

图片校验图片头和像素上限，媒体类型以已识别的实际内容为准，不让扩展名覆盖内容类型；不重复整图解码，实际像素解码由图片消费节点完成。Image List 保留输入列表顺序，完整记录执行版本检查，Summary.files 保留实际来源。大量文件优先通过 Directory Scan 的 limit 和 ForEach 分别读取。

JSON 原有 allow_missing/allow_invalid_json/default_value 保留且默认关闭。File 记录的变化/删除、大小超限不被回退开关吞掉；仅 Path 模式显式允许缺失时才回退。文本严格按 charset 解码，不猜编码或替换坏字符。

错误细节包括 `local_file_missing`、`local_file_changed`、`local_file_too_large`、`local_file_not_regular`、`local_file_read_failed`、`local_directory_scan_failed`。

## 关联、迁移与验证

独立选取最新图片和最新 JSON，不能推断二者属于同次执行。需要关联时显式使用 run_id/业务键，或先读取包含图片路径的 JSON，再沿其中路径读取图片；不得用位置排序隐式配对。

无数据库迁移。Directory Scan 新增记录字段，原路径/名称/大小/毫秒字段保留；排序精度提升、跳过链接和读取大小上限属于明确行为变化。新节点与新增可选端口从 Catalog 自动进入 Vue 编辑器，无并行前端实现或外网依赖。常驻 Runtime 按平台标准停止/启动才能加载新代码；图结构变化重新发布并显式选版本，不能改写发布快照。

```powershell
conda activate amvision
python -m pytest tests/test_workflow_local_file_reading.py tests/test_industrial_io_output_nodes.py
python -m tests.integration.local_file_reading_benchmark
python -m tests.integration.local_file_reading_live --image <已有结果图片路径> --json <已有结果JSON路径>
python -m tests.integration.local_file_reading_live_audit <validation-report.json路径> --backend-pid <当前backend工作进程PID>
```

规模测试自动创建/清理 1,000/10,000 个临时文件，真实执行图并测量时间、内存、句柄。真实链路测试在 data/validation/ 下保存生产结果副本、新建 App/发布 v1/Runtime/目录 Trigger，验证 Preview、可选空输入、同步调用、20 文件有界样本与删除通知。退出时只停用新建 Trigger/Runtime，保留小型可继续使用的验证 App/输入/报告，不改原业务资源。

短时回归和重复调用不能替代现场长期 soak，不据此宣称已满足多年连续运行认证。
