# 受控 Python I/O 依赖

此目录仅保存构建材料，不加入运行时 `sys.path`，不由 backend 或节点直接导入。
当前范围是 M1 的 PLY/PCD I/O；不代表六个 3D Metrology 节点已可用。

## 来源与修改

| 包 | 原版 | 本项目版本 | 修改范围 |
| --- | --- | --- | --- |
| trimesh | 5.1.1 | 5.1.1+amvision.1 | exchange.ply 严格头部、类型化点云接口、分块读写；不修改几何算法 |
| pypcd4 | 1.5.1 | 1.5.1+amvision.2 | 头部、字段布局、记录完整性、LZF 分组、写出及版本身份；.2 修正不可压缩数据的输出容量 |

`manifest.json` 固定上游源码归档及被替换文件 SHA-256。各包目录保存完整的修改文件，
使原版未修改部分和版权声明可核对，不把它们复制进业务模块。
目录内 `.gitattributes` 固定 LF，避免 Windows 自动换行改变受控源文件哈希。
`shared/_strict_records.py` 是两个 wheel 构建时共用的 NumPy 记录检查辅助代码，
不读取 PLY/PCD 头部，不构成另一个格式解析包。两个库运行时互不依赖。

上游许可证分别为 MIT 和 BSD-3-Clause，保留在对应目录及 wheel 内。
`python-neo-lzf==0.3.5` 使用未修改的官方 CPython 3.12 x64 wheel，保留其中 BSD 声明。
本项目修改仅供本项目使用，无上游提交或等待合并步骤。

## 构建与验证

开发命令先执行 `conda activate amvision`，确认 `python` 来自该环境。
构建在独立 Python 环境进行，构建器本身不联网、不安装依赖、不改环境。
归档从 manifest 中的固定 URL 获取。示例中的目录必须尚不存在：

```powershell
python scripts/build_controlled_python.py trimesh --archive <trimesh-source.tar.gz> --work-dir .tmp/io-build-trimesh --wheel-dir <wheelhouse>
python scripts/build_controlled_python.py pypcd4 --archive <pypcd4-source.tar.gz> --work-dir .tmp/io-build-pypcd4 --wheel-dir <wheelhouse>
python -m pip install --no-index --find-links <wheelhouse> -r runtimes/python_patches/requirements-io.txt
python -m pytest tests/integration/controlled_io -q --basetemp=.tmp/io-tests
```

初次 `.1` 构建工具为 Python 3.12、build 1.3.0、setuptools 70.2.0、wheel 0.47.0、
hatchling 1.27.0、hatch-vcs 0.5.0、setuptools-scm 8.3.1、pyproject-hooks 1.2.0。
PCD `.2` 构建使用 build 1.6.1、hatchling 1.32.4、setuptools-scm 10.3.4、
pyproject-hooks 1.3.3，其余版本相同；实际源码和 wheel 身份另行固定。
构建产物是正常的 `py3-none-any.whl`，不是 editable 安装或启动时补丁。
每次构建输出 `.build.json`，记录源码、修复文件、wheel SHA-256。
构建器检查 wheel 内版本和每个修改模块，防止生成文件被打包规则漏掉。
初次产物身份见 [M1 I/O 验收记录](../../docs/development/3d-metrology-m1-io.md)，
当前 PCD `.2` 身份见[资产验证记录](../../docs/development/3d-metrology-m1-assets.md)。

集成套件显式检查安装版本和模块内容；缺依赖/装原版直接失败，不 skip。
它位于 `tests/integration/`，不使尚未启用三维依赖的常规后端测试无法收集。
同目录 Python 发行态也必须安装同一固定 wheel；本轮尚未启用 release profile，
不修改现有 `requirements.txt`/`requirements_cpu.txt` 或生产 Python 环境。

## 严格接口

- PLY：`trimesh.exchange.ply.read_ply_header`、`read_ply_data`、`write_ply_points`。
- PCD：`pypcd4.pypcd4.read_pcd_header`、`read_pcd_data`；`PointCloud.from_path/from_fileobj/save` 使用相同路径。
- PLY 头部返回冻结的 `PlyHeader/PlyElement/PlyProperty`；PCD 返回冻结的 `MetaData` 和正文偏移。
- 不经 `Trimesh` 几何对象或 `trimesh.load/export`，避免自动处理点、网格及属性。
  上游通用 mesh API 不属于本次点云严格 I/O 承诺，不能作为失败后的替代入口。
- 输入快照必须是可 seek 的二进制文件/BytesIO；网络流不是本轮接口。
- 原始标量字段、顺序、dtype 和 PCD COUNT/VIEWPOINT 保留。平台不支持的字段映射仍应整份拒绝。
- `max_header_bytes`、`max_decoded_bytes`、`chunk_rows`、`chunk_bytes` 显式提供；不在库内填写生产预算。
  `chunk_bytes` 限制读取文本/二进制块，不是 Python RSS 上限。
- PCD `max_working_bytes` 约束压缩路径的字节缓冲量。读取含目标数组、解压结果和压缩输入；
  写出含分组块、拼接及压缩输出，不含调用方已拥有的源数组。Python 对象/分配器开销仍由平台容量评估计入。
- `cancel` 在头部完成后的分配前、块边界、压缩前后调用，回调抛出的异常原样传播。
  LZF 的单次原生调用不能从 Python 内抢占；强制终止由已有执行进程管理负责。
- 调用方拥有传入 stream。writer 检查短写并 flush，路径接口负责 close；stream 的 close 由调用方验证。
  失败可留临时半文件，不能当作已提交资产。节点层仍须执行临时对象、关闭、严格读回比对、ObjectStore 提交。

PCD COUNT 和 VIEWPOINT 的省略值来自 PCD 0.7 格式规定，不是解析失败降级。
显式 compressed 压缩失败就失败，不切换编码。PLY 的 mesh/list 元素先完整报告再拒绝，不能只留下 XYZ。
浮点 NaN/Inf 是合法输入值，由后续有效点规则处理；文本数值溢出/下溢和坏 token 是格式错误。
库不能识别语义上谎报的端序，只按声明端序解码，不猜测或自动交换。

## 后续维护

修改需更新受控身份并重跑双平台格式回归。代码模块未变化的构建工具修正需单独核对 wheel 身份。
正式 wheel 放本地 `runtimes/third_party/python-io/`，不入 git；源码和验证记录入 git。
升级上游不能直接覆盖补丁，也不得把上游版本号当作受控版本。
