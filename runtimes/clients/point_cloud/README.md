# Python 同机点云调用工具

面向 Windows/Ubuntu 64-bit 的同机 Python 调用。模块随 amvision 源码/运行时使用，不依赖 `tests/`，不另写 mailbox 或 mmap 协议。它是平台运行时工具，不是独立 SDK，不能改变 `sdks/README.md` 的外部 SDK 边界。独立 Windows .NET 客户端继续使用 `sdks/dotnet`。

## 调用

在与服务相同的配置环境、项目工作目录中，使用同一 Python 运行时：

```python
from backend.contracts.workflows.point_cloud import CloudBufferDescriptor
from backend.service.settings import get_backend_service_settings
from runtimes.clients.point_cloud import PointCloudClient

settings = get_backend_service_settings()
client = PointCloudClient(
    buffers_root=settings.local_memory.root_dir,
    broker_settings=settings.local_buffer_broker,
)
reply = client.invoke(
    source_id=source_id,
    generation=plan_generation,
    cloud=CloudBufferDescriptor.model_validate(descriptor),
    content=memoryview(points),
    timeout_ms=timeout_ms,
)
```

`source_id` 和 `plan_generation` 来自当前已启用 Trigger 的正式配置；不写死、不自动使用过期 generation。服务在不同配置环境启动时，构造函数必须显式传入该服务的 `local_memory.root_dir` 和 `local_buffer_broker`，不能使用另一环境的默认值。

`content` 接受 bytes、bytearray、连续 memoryview，或保存紧密二进制数组的 `Path`。descriptor 中声明顺序、精度、偏移、字段、点数、单位及坐标系，长度必须完全匹配。它不是 PLY/PCD 文件解析入口。调用期间调用方不得修改原数组/文件；客户端对长度、截断和增长做检查，不为防止调用方并发写入再复制整份 1 GB 数据。

命令行同样复用服务配置：

```powershell
conda activate amvision
python -m runtimes.clients.point_cloud --descriptor cloud.json --array cloud.bin --source SOURCE_ID --generation GENERATION --timeout-ms TIMEOUT_MS
```

## 发行目录调用

`assemble-release` 将本工具、工件生成器和两份正式配方放入 `app/`，保留源码相对布局；启动器在 `launchers/client/invoke_point_cloud.py`。工具文件与摘要记录在发行 manifest 的 `point_cloud_tools` 中，`validate-layout` 检查缺失和损坏。该工具使用发行包的后端依赖，不是可单独拷走的纯 Python SDK。

Windows 在发行根目录运行，使用发行包自己的解释器：

```powershell
./python/python.exe launchers/client/invoke_point_cloud.py recipe -- data/recipes/lithium.workflow.json --input-kind array --view numeric
./python/python.exe launchers/client/invoke_point_cloud.py invoke -- --descriptor data/input/cloud.json --array data/input/cloud.bin --source SOURCE_ID --generation GENERATION --timeout-ms TIMEOUT_MS
```

入口按脚本位置识别发行根，所有工具相对路径以发行根为准，也可传绝对路径。生成器默认拒绝覆盖已有文件；覆盖必须显式传 `--overwrite`。调用不自动启动服务、创建 Trigger、发布配方、重试或排队。运行前须启用目标服务的已发布数组配方及 Trigger，并读取当前 `plan_generation`。文件配方使用 `--input-kind file`，调用仍走既有 HTTP 文件入口，不能把 PLY 文件传给 `--array`。

同机工具从目标发行根的 `config/backend-service.json` / `backend-service.local.json` 及现有 `AMVISION_` 覆盖加载配置，与服务保持一致。不得混用另一安装目录的共享内存根或开发环境覆盖。发行缺少自己的 Python 时明确失败，不回退系统 Python。源码开发仍使用 `conda activate amvision` 后的当前解释器。

同一入口代码支持 Ubuntu，解释器路径为 `python/bin/python3`；Ubuntu 完整离线包及其原生依赖仍单独验收，不能以入口测试通过替代离线发行通过。工具没有添加平台专用进程控制，沿用已有统一启动、整组停止和退出回收。

## 生命周期

- 一次调用一个 event_id，正式 PREPARE/WRITING/REQUEST/RESPONSE/ACK，无自动重试或等待准入队列。
- 总超时覆盖分配、分块写入和响应；可传 `cancelled=lambda: stop_event.is_set()`。取消后抛出 `CancelledError`，通知服务端撤销，并释放本地 writer/mmap。
- 响应解析完成即 ACK；返回普通 JSON，不暴露已经释放的共享内存视图。协议拒绝抛 `PointCloudCallError`，保留错误码及原响应。
- 调用方仍需检查 `reply.state`。执行成功不是产品合格；工件配方再检查 `reply.response_payload.results.body.data.state`，只有 `ok` 放行，`ng/invalid` 分开处理。
- 客户端只能使用自身运行用户被授权访问的同机共享目录。跨机器输入使用既有 HTTP 文件接口，不能把 mmap 路径当网络协议。

完整工件示例见 [工件配方](../../../docs/examples/workflows/lithium-workpiece.md)。
