# 3D Metrology

通过项目现有 Node Pack、Workflow、CloudRuntime 和 ResourceScope 提供点云处理与测量。正式包 ID 为 `metrology3d.nodes`，只有本目录一套实现，不依赖 `projectsrc` 或测试注册器。

## 节点

- 数据：Read Cloud、Normalize Units、Filter Valid、Crop ROI、Transform Cloud、Save Cloud、Export Cloud。
- 定位与特征：Fit Plane、Build Frame、Extract Boundary、Fit Line、Fit Circle。
- 测量：Height Query、Measure Step、Measure Extents、Measure Edge Pair、Measure Hole。
- 显示：Cloud Preview。

既有严格截线与轴向跨度已可使用；R5 F 的可见投影包络、片段集合及稳健角区拟圆尚未接通，不能将该工件的 23 个有效结果称为 50 项测量完成。无效量值保持 null，并保留具体原因。

## 依赖与启动

开发环境先激活项目环境，在仓库根目录安装受控版本：

```powershell
conda activate amvision
python -m pip install --find-links runtimes/third_party/python-io --find-links runtimes/third_party/python-geometry -r custom_nodes/metrology3d_nodes/requirements.txt
python -m pip check
python -m custom_nodes.metrology3d_nodes.workflow.generate_catalog
```

manifest 锁定 NumPy 2.4.4、SciPy 1.18.0、Open3D 0.20.0、trimesh 5.1.1+amvision.2、pypcd4 1.5.1+amvision.2、python-neo-lzf 0.3.5。缺包或版本不符时包仍显示在节点管理中，但不注册可执行节点；安装不会由业务请求或节点自动触发。发行包的 bundled Python 必须安装同一组依赖及其传递依赖，不能只复制节点目录。

Windows/Ubuntu x64 为当前支持范围。Ubuntu Open3D 需要可加载的 `libusb-1.0.so.0`；验收可向临时 sysroot 解包并显式设置进程库路径，正式机器应配置系统依赖。Ubuntu 运行数据库、锁、共享内存及输出目录使用原生文件系统，不使用 `/mnt/w` 的 DrvFS。源码与输入样本可以从挂载盘只读访问。

## 显式容量

[workstation.example.json](workstation.example.json) 是 2026-10-28 确认的本机工程配置。本机已写入忽略版本控制的 `config/backend-service.local.json`，未改变所有机器的默认值。

| 配置 | 本机上限 |
| --- | --- |
| 每 Run 活跃数组 | 1 GiB |
| 算法工作预算 | 4 GiB |
| 有界显示点数 | 1,000,000 |
| 节点默认/最大超时 | 180 / 180 秒 |
| 强制停止宽限 | 2 秒 |

这些数值是安全准入边界，不是测量节拍承诺，也不是整个进程 RSS 硬上限。预算不足立即拒绝，无等待队列。示例另保留本工件验收的 400,000,000 字节解码容量、600,000,000 字节资产/导出容量、610,000,000 字节资产包容量及 500,000,000 字节 Preview 单会话文件容量。因此不能声称此配置能处理任意接近 1 GB 的文件；输入载荷上限、解码数组、资产包和运行工作集是不同限制。

未配置 `workflow_runtime.point_cloud` 时明确拒绝执行。已有后端、worker 和浏览器静态构建需要按正常更新流程重启/重建后使用新包，不靠修改在运行进程的模块状态启用。

## 验证入口

实施记录见 [R5 F 实施与验收](../../docs/development/3d-metrology-r5-f-implementation.md)。正常发布测试直接读取本目录 manifest/Catalog，不生成临时替代节点包。业务数据、旧三维资产与原始样本不迁移、不删除。
