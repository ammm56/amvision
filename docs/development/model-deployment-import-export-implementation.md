# 模型部署实例导入导出：实现与验收

单实例传递已接入后端、Worker 和 Vue 部署页面。公开契约、状态、磁盘路径和删除规则以 [API 说明](../api/model-deployment-transfers.md) 为准；[设计说明](model-deployment-import-export.md)保留范围和选择依据。当前不实现完整部署包、Workflow Runtime/Trigger 迁移或跨机器在线发送。

## 已实现的模块

| 步骤 | 实现 | 核对与验证 |
| --- | --- | --- |
| 包契约 | `backend/contracts/deployments/model_package.py` | 固定输入、类别顺序、版本/Build/文件引用、路径和大小限制 |
| 文件包 | `model_package_archive.py`、`package_manifest.py` | 流式 ZIP64、SHA-256、XML/BIN、ONNX external data、无 checkpoint 的 Build |
| 归属与迁移 | `model_transfer_repository.py`、迁移 e7a9b1c3d5f8 | 导入模型所有权与短期传递回执分开；旧数据不会自动转为导入来源 |
| 导入 | `package_import.py`、`transfer_service.py` | 分析、冲突副本、固定映射、配置校验、幂等提交、两个通道初始停止 |
| 后台执行 | `backend/workers/model_deployment_transfers.py` | dataset-export profile 的独立消费者；API 不执行模型打包或解压 |
| 删除 | 统一 ResourceDeletionService / ResourceDeletionPlan | 共享保留、独占回收、文件回滚、预览 revision、项目整体清理 |
| 页面 | DeploymentTransferPanel、DeploymentExportActions、ImportedModelAssets | 导入对话框、实例内导出进度与下载、刷新回读、目标配置、资源映射、导入模型管理 |

前端测试集中在 `tests/frontend/deployments/test_*.ts`，后端测试集中在根目录 `tests/test_model_deployment_*.py`。未将测试放在业务组件目录。

## 验收记录

2026-09-08 的开发环境为 conda amvision；发行验收使用实际 `release/full-windows-x64-cpu/python/python.exe` 和 `release/full-windows-x64-nvidia/python/python.exe`。

两套旧发行目录含数据，未使用 `--force` 擦除。从当前源代码通过 `assemble-release` 在专属验收目录生成对应 profile 的完整程序，通过 `--python-executable` 使用原发行目录中的实际 bundled Python。在独立数据根和 15610/15611 端口运行真实 full 启动脚本、backend-service、inference daemon，以及 dataset-export、inference 两个 Worker profile。未手改发行源码；原发行目录的业务数据和配置保持原样。

真实样例来自开发数据库已有 YOLO11 s 分类部署：OpenVINO FP32、CPU、224×224、3 类、2 个实例。源实例保持运行且只读导出；ZIP 大小 109,450,271 字节。使用同一张真实图片对比导入前后类别和概率，容差为 1e-5。

| 验收项 | 当前结果 |
| --- | --- |
| 开发页面提交真实导出 | 通过 |
| 隔离开发数据库导入、真实推理、再导出、删除记录和文件 | 通过 |
| CPU full 服务：浏览器上传、分析、导入、sync 启动/预热/推理/停止 | 通过 |
| NVIDIA full 服务：同包导入、sync 启动/预热/推理/停止 | 通过 |
| CPU/NVIDIA async 启动、预热、真实任务推理、停止 | 通过，类别及概率与源模型一致 |
| 浏览器重复上传、分析、提交及资源复用 | 通过，仍为一个实例，没有重复模型 |
| 两套完整服务停止、重启、再次 sync/async 推理及再导出 | 通过 |
| 两套服务最终删除实例、导入版本/Build/文件/归属记录 | 通过，数据库对应五类记录均为 0，导入模型目录无文件 |
| 后端组合回归 | 50 项通过，包含迁移、Worker profile、归档、导入、API、故障及资源删除 |
| 前端流程回归 | 5 项通过，包含上传取消；类型检查和生产构建通过 |
| 文档链接、git diff --check | 通过 |

真实推理验证针对上述已有样例，不把 NVIDIA 发行环境中的 OpenVINO CPU 推理写成 TensorRT/GPU 推理已通过。其他模型族、任务和硬件组合继续沿用现有运行时支持范围；包内路径/字段验证不能代替对应模型在目标硬件上的启动和预热。

中途验收曾只启动 dataset-export profile，导致异步推理任务排队；加入 inference profile 后实际任务通过。另一次 `.tmp` 隔离目录在进程运行期间丢失程序和拓扑文件，来源未确认，该次结果不计入通过。最终验收改用独立组装目录，重新执行完整导入、停止、重启、推理和删除。旧目录程序删除曾被自动审批拒绝，未以替代命令执行该操作。

## 重复验收

```powershell
conda activate amvision
python -m pytest tests/test_model_deployment_package_archive.py tests/test_model_deployment_package_import.py tests/test_model_deployment_transfer_api.py tests/test_model_deployment_transfer_faults.py
npm --prefix frontend/web-ui test -- tests/frontend/deployments/test_deployment_transfer.ts
npm --prefix frontend/web-ui run typecheck
npm --prefix frontend/web-ui run build
```

真实验收脚本为 `tests/test_model_deployment_real_acceptance.py` 和 `tests/test_model_deployment_full_acceptance.py`，后者只允许专属 15610/15611 端口。源码验收脚本的源数据库只读取已选实例，目标数据库使用不存在的新目录；full 验收通过公开 API 上传、分析、提交及现有部署调用。

开发态启用新功能前，需要使 dataset-export Worker 重新载入新消费者。异步任务推理还需启用已有 inference profile。配置上限和保留期读取同一个 `config/backend-service.json` 的 `model_deployment_transfers` 段。

本轮所有隔离服务已停止，开发环境原有 4 个部署保持运行。清理专用 `.tmp/model-deployment-final` 和 `release/model-transfer-acceptance` 目录的操作被自动审批拒绝（仅返回“被策略阻止”），目录暂留，等待明确处理；不属于长期资产。原有两个发行目录不在清理范围内。

## 实例内操作与重复导出

导出和下载集中在实例操作行，使用现有 Button loading 动效；导入成功直接刷新实例列表。未完成导入从导入入口继续，页面顶部不保留传递结果块。重复请求由跨进程登记锁合并，Worker 核对配置和文件后复用同一个 ZIP；缓存无效时原位更新，并回收旧实现的重复包。相关回归位于 `tests/test_model_deployment_export_reuse.py`、`tests/frontend/deployments/test_deployment_transfer.ts`、`tests/frontend/deployments/test_deployment_export_actions.ts`。

本轮验证：后端部署包与导出复用回归 29 项、前端交互回归 10 项通过，前端类型检查与构建通过。使用实际 YOLO11s classification / OpenVINO FP32 CPU 模型（224 × 224，3 类，约 104.4 MB ZIP），在隔离目标目录完成导入和真实推理；连续三次重新导出使用同一个操作及同一个 ZIP，文件字节和修改时间不变。浏览器核对实例按钮的等待状态及“导出 → 下载”顺序。源码开发的常驻 Worker 需要重启后载入新复用逻辑；仅前端热更新或 API 自动重载不替换 Worker 内存中的代码。
