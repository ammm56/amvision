# 运行时与打包架构

## 文档目的

本文档用于定义开发运行时、发布运行时、启动器和发行装配之间的关系，明确“开发阶段用 conda，发布阶段用同目录 Python 运行时”的整体架构方案。

本文档回答的问题是“运行时如何组织、发布包如何构成、哪些依赖进入发布包、哪些依赖必须单独交付”。

## 适用范围

- conda 开发环境与 bundled Python 发布运行时的分工
- runtimes、launchers、packaging 三层的职责边界
- 当前 `full` 发布目录的装配关系
- 发布包中的 Python、前端静态资源、自定义节点和配置收敛方式
- 升级、回滚和兼容性管理边界

## 总体原则

- 开发环境使用 conda 管理，可复现且显式定义
- 发布与部署默认使用项目同目录 Python 运行时，不依赖目标机预装系统 Python
- 服务、worker、CLI 和维护脚本统一由 bundled Python 解释器启动
- 发布包尽量自带应用级依赖，但系统级 GPU 驱动、厂商运行时和操作系统组件单独列出
- 当前先固定一套 `full` 发布结构；后续如需推理专用目录，优先从 `full` 目录复制后手工裁剪依赖与 Python 运行时

## 三层结构

### 1. 开发运行时

- 由 conda 环境定义、锁定和复现
- 服务于本地开发、测试、类型检查和依赖迭代
- 不应直接成为最终发布包的隐式来源，而应通过显式构建流程导出发布依赖集合

### 2. 发布运行时

- 以同目录 Python 运行时为核心
- 包含 Python 解释器、应用依赖、项目代码、前端静态资源和必要的 `custom_nodes`
- 对目标机器表现为自包含应用运行时，而不是依赖系统 Python 的源码包

### 3. 装配层

- 当前只组装一个 `full` 发布目录
- 控制最终目录布局、交付形式、升级方式和验证步骤

## 运行时目录建议

```text
release/
├─ python/
├─ app/
├─ frontend/
├─ custom_nodes/
├─ config/
├─ data/
├─ logs/
├─ manifests/
└─ launchers/
   ├─ service/
   ├─ worker/
   └─ maintenance/
```

## runtimes 目录在仓库中的职责

- 当前仓库里的 runtimes 目录主要包含 launchers 和 manifests 两部分；bundled Python 本体不放在仓库里预置，release 组装阶段默认保留现有发布目录里的 `python/`。
- runtimes/launchers：统一服务、worker 和维护命令入口；当前仓库已经提供 Python 主逻辑 launcher，以及 bat/sh wrapper。
- runtimes/manifests：发布目录和 worker 职责拆分的清单；当前仓库已经提供 `full` release profile 与 worker profile。

## 当前真实状态

- 当前后端功能面已经可用，开发环境仍以 `python -m uvicorn backend.service.api.app:app --host 127.0.0.1 --port 5600` 这类直接启动方式为主。
- `backend.maintenance.main assemble-release` 当前会生成 `release/full/` 目录，复制完整 backend 代码、配置、launcher、manifest，并把仓库根目录的 `requirements.txt` 复制到发行目录。
- 当前 release 组装会保留并回迁现有发行目录里的 `python/`，也会把 `frontend/web-ui/dist/` 复制到发行目录里的 `frontend/`，补齐 `runtime-config.json`，并把 `runtimes/third_party/ffmpeg/`、`runtimes/tensorrt_bin/`、`runtimes/cudnn_dll/` 中运行需要的内容复制到发行目录里的 `tools/`。
- 只有显式提供 bundled Python 来源目录时，当前才会重建 `python/`；如果发行目录原本没有 `python/`，则会退回空目录占位模式。

## 启动器设计

### service launcher

- 负责启动 backend-service 服务进程
- 必须强制使用同目录 bundled Python
- 负责补齐 `PYTHONPATH`、加载配置、校验依赖并输出最小启动日志

### worker launcher

- 负责启动训练、推理、转换和流程 worker
- 当前通过 `config/backend-worker.json` 的 `task_manager.enabled_consumer_kinds` 或 `runtimes/manifests/worker-profiles/*.json` 派生不同 worker 组合
- 不允许隐式回退到系统 Python

### maintenance launcher

- 负责健康检查、版本显示、迁移检查、节点目录扫描和环境诊断
- 应作为安装后验证和升级前检查的标准入口
- 当前仓库已经提供最小 `version`、`show-config`、`validate-layout` 和 `assemble-release` 命令入口

## 发布包必须包含的内容

- bundled Python 解释器与应用依赖
- backend 服务代码与 worker 代码
- frontend 构建产物
- 默认配置模板与运行时 manifest
- 默认 custom_nodes 目录与可选节点包资产
- 启动器与维护工具
- 当前 full 发布目录已经包含 `tools/ffmpeg/`、按需包含 `tools/tensorrt/` 和 `tools/cudnn/`；如后续继续细化发布形态，再按目标平台裁剪工具目录

## 发布包不默认包含的内容

- GPU 驱动程序
- 厂商推理运行时的系统级安装器
- 操作系统级通信中间件
- 现场专有证书、密钥和客户定制配置

## 视频工具运行时约定

### 工具归属

- `ffmpeg/ffprobe` 属于应用运行时工具链，不属于模型资产目录，也不属于业务数据目录。
- 因此它们不应放在 `data/` 下，不应与 `models/`、`datasets/` 或 `maintenance` 数据目录混放。

### 仓库侧目录约定

建议在仓库中按平台维护运行时来源目录：

```text
runtimes/
└─ third_party/
   └─ ffmpeg/
      ├─ windows-x64/
      │  └─ bin/
      │     ├─ ffmpeg.exe
      │     ├─ ffprobe.exe
      │     └─ *.dll
      └─ linux-x64/
         └─ bin/
            ├─ ffmpeg
            └─ ffprobe
```

说明：

- Windows 下项目正式调用入口应是 `ffmpeg.exe` 和 `ffprobe.exe`。
- `.dll` 只是这些可执行文件的运行时依赖，应与 `exe` 放在同目录，不直接作为项目调用入口。
- Linux 下使用对应可执行文件，不单独暴露 `.so` 作为 workflow 级概念。

### 发布包目录约定

面向目标平台的发布目录建议包含：

```text
release/
└─ full/
   └─ tools/
      └─ ffmpeg/
         └─ bin/
            ├─ ffmpeg.exe / ffmpeg
            ├─ ffprobe.exe / ffprobe
            └─ 相关 dll（Windows）
```

说明：

- 当前仓库的 `assemble-release` 会先复制整个 `runtimes/third_party/ffmpeg/` 目录到 `release/full/tools/ffmpeg/`，确保开发和验收阶段可以直接闭环。
- 后续如需更严格的平台裁剪，再按目标平台只保留一套 `ffmpeg` 工具。

### 查找优先级

后续运行时代码查找 `ffmpeg/ffprobe` 时，建议按如下顺序：

1. 显式配置路径
2. 发布目录 `tools/ffmpeg/bin/`
3. 仓库 `runtimes/third_party/ffmpeg/<platform>/bin/`
4. 系统 `PATH` 中的可执行文件（仅 fallback）

系统 `PATH` 不应成为默认部署前提，只能作为诊断或临时兼容路径。

## GPU 工具运行时约定

### TensorRT 目录归属

- TensorRT 属于 GPU 厂商运行时资产，不属于模型权重目录，也不属于业务数据目录。
- 开发态默认把解压后的 TensorRT SDK 放在 `runtimes/tensorrt_bin/`，该目录不纳入 git。
- 发布态由 `assemble-release` 把运行所需内容复制到 `release/full/tools/tensorrt/`。

开发态目录：

```text
runtimes/
└─ tensorrt_bin/
   ├─ bin/
   │  ├─ trtexec.exe
   │  ├─ nvinfer_*.dll
   │  ├─ nvonnxparser_*.dll
   │  └─ 其他 TensorRT 运行时 dll
   ├─ python/
   │  └─ tensorrt-*-cp312-*.whl
   ├─ doc/
   ├─ include/
   └─ lib/
```

发布态目录：

```text
release/
└─ full/
   └─ tools/
      └─ tensorrt/
         ├─ bin/
         ├─ python/
         └─ doc/
```

说明：

- 普通 TensorRT engine 构建和推理运行需要 `bin/` 中的 `trtexec.exe` 与相关 DLL。
- Python TensorRT API 需要 bundled Python 安装 `python/` 中与 Python 版本匹配的 wheel，并且 `bin/` 在 DLL 搜索路径中。
- `include/` 和 `lib/` 只用于编译 C++ 自定义 plugin 或原生扩展，不属于默认发布运行必需内容。
- `doc/` 不参与执行，但包含说明和第三方致谢，发布时保留，便于现场确认来源和许可信息。
- TensorRT Python wheel、DLL 和 `trtexec` 必须同版本，不能把不同 TensorRT 小版本的 Python 包和本地 DLL 混用。
- 目标客户机默认要求安装 NVIDIA driver 和现场指定的系统 CUDA；TensorRT SDK 的运行部分和 cuDNN DLL 随项目发布包提供。CUDA Toolkit 不整体放入 `runtimes/`，除非后续明确需要现场编译 CUDA/TensorRT plugin。

### cuDNN DLL 目录归属

- cuDNN 属于 GPU 用户态运行库，不属于模型权重目录，也不属于业务数据目录。
- 开发态默认把 cuDNN DLL 放在 `runtimes/cudnn_dll/`，该目录不纳入 git。
- 发布态由 `assemble-release` 把运行所需内容复制到 `release/full/tools/cudnn/`。
- 当前项目默认优先使用 CUDA 12.9 对应目录；如现场需要切换，可通过 `AMVISION_CUDNN_CUDA_VERSION` 或 `AMVISION_CUDNN_BIN_DIR` 显式指定。

开发态目录：

```text
runtimes/
└─ cudnn_dll/
   ├─ bin/
   │  ├─ 12.9/
   │  │  └─ x64/
   │  │     ├─ cudnn64_9.dll
   │  │     └─ cudnn_*.dll
   │  └─ 13.2/
   │     └─ x64/
   │        ├─ cudnn64_9.dll
   │        └─ cudnn_*.dll
   └─ LICENSE
```

发布态目录：

```text
release/
└─ full/
   └─ tools/
      └─ cudnn/
         ├─ bin/
         └─ LICENSE
```

说明：

- 启动器会把 `tools/cudnn/bin/12.9/x64/` 加入子进程 `PATH`。
- TensorRT runtime helper 会在当前 Python 进程和子进程里加入 cuDNN DLL 搜索路径。
- 不把系统 CUDA Toolkit 整体复制到项目中；需要 CUDA Toolkit 的现场环境按系统依赖单独安装。

### TensorRT 查找优先级

运行时代码查找 TensorRT 时按如下顺序：

1. `AMVISION_TENSORRT_BIN_DIR`
2. `AMVISION_TENSORRT_ROOT_DIR/bin`
3. 发布目录 `tools/tensorrt/bin/`
4. 仓库目录 `runtimes/tensorrt_bin/bin/`
5. 仓库目录 `runtimes/third_party/tensorrt/bin/`
6. 系统 `PATH` 中的 `trtexec` 或 TensorRT DLL

系统 `PATH` 只作为 fallback，不是默认部署前提。

## 打包流水线建议

1. 从 conda 开发环境导出可审核的依赖基线
2. 生成面向 bundled Python 的依赖集合和兼容性 manifest
3. 收敛 backend、frontend、custom_nodes 和默认配置
4. 收敛目标平台的 `ffmpeg/ffprobe`、TensorRT 等运行时工具目录
5. 生成服务、worker 和维护脚本的统一入口
6. 通过 `assemble-release` 生成目标明确的 Windows x64 CPU 或 NVIDIA 发布目录
7. 执行最小启动验证、节点目录扫描和接口健康检查

## 当前装配结果

- 当前 canonical manifest：`full-windows-x64-nvidia.json`、`full-windows-x64-cpu.json`
- 发布目录默认包含 backend-service、全部 worker profile、前端目录、custom_nodes 目录、配置目录、数据目录、日志目录，以及保留或占位的 `python/` 目录
- Windows 包只收敛 Windows launcher 和 Windows FFmpeg；CPU 包不携带 TensorRT/cuDNN
- Ubuntu x64 CPU/NVIDIA profile id 已预留但未实现，不能通过复制 Windows 包冒充
- bundled Python 体积较大，首次组装只创建 `python/`，由发布人员手工复制目标环境

## 长稳 soak 验收入口

`tests/integration/test_release_full_stack_acceptance.py` 是完整发布包的显式验收入口。默认只做短时启动、health、OpenAPI、组件日志、资源快照和 stop 回收检查；现场长稳验证通过环境变量放大。

常用变量：

- `AMVISION_RELEASE_FULL_ROOT`：指定待验收的 `release/full` 目录。
- `AMVISION_RELEASE_FULL_PYTHON`：指定发布目录内 Python 解释器。
- `AMVISION_RELEASE_FULL_PORT`：指定 backend-service 端口。
- `AMVISION_RELEASE_FULL_SOAK_SECONDS`：指定驻留秒数。
- `AMVISION_RELEASE_FULL_RESOURCE_SAMPLE_INTERVAL_SECONDS`：指定资源采样间隔。
- `AMVISION_RELEASE_FULL_SOAK_WORKLOAD_COMMAND_JSON`：可选负载命令，必须是 JSON 字符串数组，例如用于启动 .NET Console 循环执行 BGR24 ZeroMQ TriggerSource、WorkflowAppRuntime 和模型 DeploymentInstance 调用。
- `AMVISION_RELEASE_FULL_SOAK_WORKLOAD_CWD`：可选负载命令工作目录，默认是 `release/full`。

资源基线输出在本轮 logs 子目录的 `resource-baseline.json`，包含 backend-service、各 worker profile 的 RSS、CPU、线程变化，以及每次采样时 `/api/v1/system/health` 返回的 `local_buffer_broker` 摘要。启用 workload 后，`soak-workload.log` 会保存外部负载进程输出。

长稳场景建议把 workload 固定为“workflow trigger + deployment runtime + LocalBufferBroker”的真实调用循环：例如先由前端或配置包创建好 WorkflowAppRuntime、ZeroMQ TriggerSource 和 DeploymentInstance，再用 .NET Console 按配置 key 持续发送 BGR24 raw 图片触发，并同步调用模型 deployment sync/async 控制面和推理接口。`release/full` 验收脚本只负责拉起平台、采样和回收，不在测试里创建生产资源。

## 兼容性管理

- Python 版本、关键依赖版本和目标平台兼容性必须写入 runtime manifest
- 节点包兼容性、模型兼容性和运行时 profile 兼容性应统一记录
- 不同发布形态的差异应通过装配 manifest 管理，而不是靠人工记忆

## 升级与回滚原则

- 升级应以整个发布包或版本目录切换为单位进行
- bundled Python、节点包版本和前端资源应随版本一起切换
- 业务配置和数据目录应尽量独立于应用目录，避免升级覆盖
- 回滚应恢复到上一个完整版本目录，而不是仅回退单个 Python 包

## 验证要求

- 服务启动必须验证使用的是 bundled Python
- worker 启动必须验证队列连接、`custom_nodes` 目录和运行时依赖
- 发布包必须验证前端静态资源可访问、REST 健康检查可用、WebSocket 可订阅
- 如启用 ZeroMQ，还应验证本地 IPC 通道和端点权限

## 推荐后续文档

- [docs/deployment/bundled-python-deployment.md](../deployment/bundled-python-deployment.md)
- [docs/deployment/backend-worker-startup.md](../deployment/backend-worker-startup.md)
- [docs/deployment/backend-maintenance.md](../deployment/backend-maintenance.md)
- [docs/deployment/runtime-profiles.md](../deployment/runtime-profiles.md)
- [docs/architecture/backend-service.md](backend-service.md)
- [docs/architecture/system-overview.md](system-overview.md)
