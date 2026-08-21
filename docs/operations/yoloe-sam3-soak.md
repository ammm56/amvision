# YOLOE / SAM3 soak

本文定义显式长时测试的执行方法与判定边界，不保存某台机器某一天的结果流水。性能和内存结果应随构建产物、硬件、驱动、模型资产和测试配置一起保存在外部验收报告中。

## 测试入口

```powershell
conda activate amvision

python -m pytest --basetemp .tmp/yoloe-sam3-soak tests/integration/test_yoloe_sam3_soak_benchmark.py -q -s
python -m pytest --basetemp .tmp/yoloe-sam3-extended tests/integration/test_yoloe_sam3_extended_soak_benchmark.py -q -s
python -m pytest --basetemp .tmp/sam3-video tests/integration/test_sam3_video_multiplex_benchmark.py -q -s
```

这些测试只在显式指定时执行，不属于默认快速 pytest。运行前确认 `.tmp/<name>` 没有其他进程使用；结束后只删除本次准确目录。

## 覆盖范围

- YOLOE 文本提示和视觉提示的重复推理、session 驻留与内存/显存趋势。
- SAM3 语义、交互和视频 multiplex 链路的重复执行。
- CPU 与可用 CUDA 路径。
- 异常资产、失败恢复和 session 释放。
- 更大输入、更多对象或更长视频窗口的扩展场景。

## 记录项

- 代码 commit、发行 profile、Python 和模型资产版本。
- CPU、GPU、驱动、CUDA、cuDNN 与 PyTorch 版本。
- 输入尺寸、迭代数、warmup、prompt 数量和视频窗口。
- 平均时延、P50/P95/P99、吞吐与错误率。
- RSS、allocated/reserved VRAM、线程、句柄和文件描述符趋势。
- 结束后的进程、端口、LocalBuffer 槽位和临时目录残留。

## 判定

- 内存或显存应在 warmup 后进入平台区；不能只用起止两点掩盖持续单调增长。
- allocator reserved 增长需要结合 allocated、峰值和后续稳定性判断。
- CPU/GPU、单图/视频和不同分辨率不能混成同一基线。
- 跳过 CUDA、缺少模型资产或只运行少量 smoke 必须明确记录为未覆盖，不能记为通过。
- 性能变化需在相同硬件、资产和配置下比较；跨机器数字只用于容量规划。

## 失败定位

1. 先区分模型加载、预处理、forward、后处理、LocalBuffer 和输出序列化阶段。
2. 核对 session 是否复用，避免把每次重新加载模型误判为模型推理耗时。
3. 对内存增长分别观察 Python heap、native RSS、Torch allocated/reserved 与句柄。
4. 失败后运行最小单图 smoke，确认是负载问题还是基础能力不可用。
5. 按 [YOLOE / SAM3 排障](yoloe-sam3-troubleshooting.md) 核对资产与运行环境。

阈值由测试代码和目标环境验收配置定义；调整阈值必须附带原因和相同条件下的复测证据。
