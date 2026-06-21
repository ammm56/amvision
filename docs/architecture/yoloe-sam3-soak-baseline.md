# YOLOE / SAM3 Soak 基线

## 文档目的

本文档记录 `tests/integration/test_yoloe_sam3_soak_benchmark.py` 在目标机器上的显式执行结果，作为 `YOLOE / SAM3` custom node 的本地 CPU/GPU 长时回归基线。

本文档只记录手动指定执行的真实本地资产测试结果，不作为默认快速回归的一部分。

## 执行边界

- 测试文件：`tests/integration/test_yoloe_sam3_soak_benchmark.py`
- 执行方式：显式指定文件路径执行
- 默认 `pytest` 与 `pytest tests` 不收集本文件
- 基线来源：修复 Windows 进程内存读取实现后的 3 轮完整执行结果

基础基线执行命令：

```powershell
conda activate amvision
python -m pytest --basetemp .tmp/pytest tests/integration/test_yoloe_sam3_soak_benchmark.py -q -s
```

扩展基线执行命令：

```powershell
conda activate amvision
python -m pytest --basetemp .tmp/pytest tests/integration/test_yoloe_sam3_extended_soak_benchmark.py -q -s
```

视频 memory-attention 基线执行命令：

```powershell
conda activate amvision
python -m pytest --basetemp .tmp/pytest tests/integration/test_sam3_video_memory_attention_benchmark.py -q -s
```

## 当前测试覆盖

- `YOLOE text-prompt` CPU 长时重复推理、会话驻留与内存漂移
- `SAM3 semantic-segment` CPU 长时重复推理、会话驻留与内存漂移
- `YOLOE text-prompt` CUDA 长时重复推理与显存漂移
- `SAM3 semantic-segment` CUDA 长时重复推理与显存漂移
- 异常预训练目录失败后的恢复 smoke
- `SAM3 video-interactive-segment(memory-attention-tracker)` 长窗口 + 多对象复合场景 CPU/GPU 显式 benchmark

当前测试阈值：

- CPU 内存漂移上限：`512 MB`
- GPU 显存漂移上限：`768 MB`
- CPU soak 迭代数：`6`
- GPU soak 迭代数：`4`

扩展 soak 当前使用：

- CPU soak 迭代数：`10`
- GPU soak 迭代数：`6`
- YOLOE 更大图尺寸：`640 x 448`
- SAM3 更大图尺寸：`768 x 512`

## 基线结果

### 说明

- 早期未修复版本的 CPU 内存字段为 `0`，不纳入基线。
- 以下结果仅使用修复 `GetProcessMemoryInfo` 调用后的 3 轮完整执行。
- 目标机器 CUDA 可用，因此 5 个测试均实际执行通过。

### 第 1 轮

| benchmark | 平台 | avg(ms) | min(ms) | max(ms) | 内存/显存基线 | 结束值 | 漂移 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| yoloe-text-prompt-cpu | CPU | 409.616 | 344.439 | 594.928 | 1,348,452,352 | 1,353,170,944 | 4,718,592 |
| sam3-semantic-cpu | CPU | 25,534.493 | 25,167.055 | 25,807.911 | 8,677,646,336 | 8,794,304,512 | 116,658,176 |
| yoloe-text-prompt-cuda | CUDA | 188.417 | 41.343 | 626.266 | alloc=642,708,480 / reserved=706,740,224 | alloc=642,708,480 / reserved=773,849,088 | alloc drift=0 |
| sam3-semantic-cuda | CUDA | 513.107 | 451.375 | 616.112 | alloc=2,425,950,720 / reserved=2,594,177,024 | alloc=2,425,950,720 / reserved=3,227,516,928 | alloc drift=0 |

### 第 2 轮

| benchmark | 平台 | avg(ms) | 漂移 |
| --- | --- | ---: | ---: |
| yoloe-text-prompt-cpu | CPU | 356.154 | 5,279,744 |
| sam3-semantic-cpu | CPU | 25,286.122 | 113,995,776 |
| yoloe-text-prompt-cuda | CUDA | 196.683 | alloc drift=0 |
| sam3-semantic-cuda | CUDA | 474.206 | alloc drift=0 |

### 第 3 轮

| benchmark | 平台 | avg(ms) | 漂移 |
| --- | --- | ---: | ---: |
| yoloe-text-prompt-cpu | CPU | 374.007 | 4,534,272 |
| sam3-semantic-cpu | CPU | 25,104.523 | 113,963,008 |
| yoloe-text-prompt-cuda | CUDA | 220.521 | alloc drift=0 |
| sam3-semantic-cuda | CUDA | 457.591 | alloc drift=0 |

### 结果汇总

| benchmark | 平台 | 平均耗时范围 | 漂移范围 | 当前判断 |
| --- | --- | --- | --- | --- |
| yoloe-text-prompt | CPU | `356.154 ~ 409.616 ms` | `4.53 MB ~ 5.28 MB` | 稳定，明显低于阈值 |
| sam3-semantic | CPU | `25,104.523 ~ 25,534.493 ms` | `113.96 MB ~ 116.66 MB` | 稳定，低于阈值但计算较重 |
| yoloe-text-prompt | CUDA | `188.417 ~ 220.521 ms` | `allocated drift = 0` | 稳定，reserved 增长后趋于平台化 |
| sam3-semantic | CUDA | `457.591 ~ 513.107 ms` | `allocated drift = 0` | 稳定，reserved 增长后趋于平台化 |

## 当前结论

- `YOLOE text-prompt` 在 CPU 和 CUDA 上都表现稳定，长时重复推理没有出现明显内存泄漏信号。
- `SAM3 semantic-segment` 在 CPU 上耗时明显更高，但 3 轮结果波动较小，内存漂移稳定落在 `114 MB` 左右，仍明显低于测试阈值。
- 两条 CUDA 基线都表现为 `allocated drift = 0`；`reserved` 增长后趋于固定平台，更符合 allocator cache 预热，而不是持续泄漏。
- 以当前基线看，`YOLOE / SAM3` 已经具备继续向“更接近正式可用”阶段收口的条件；pack `metadata.phase` 与默认启用策略都已经具备继续收口的基础。

## 扩展 soak 结果

### 说明

- 扩展 soak 使用更大的输入图尺寸和更长的迭代数，只执行 1 轮。
- 目标仍然是检查会话驻留、重复推理与内存/显存平台化趋势，不作为精度 benchmark。

### 扩展结果

| benchmark | 平台 | 图尺寸 | 迭代数 | avg(ms) | 漂移 | 当前判断 |
| --- | --- | --- | ---: | ---: | --- | --- |
| yoloe-text-prompt-cpu-extended | CPU | `640 x 448` | 10 | 545.326 | `6.70 MB` | 稳定，较基础基线变慢但漂移仍很小 |
| sam3-semantic-cpu-extended | CPU | `768 x 512` | 10 | 27,461.713 | `82.68 MB` | 稳定，耗时增加但漂移仍低于阈值 |
| yoloe-text-prompt-cuda-extended | CUDA | `640 x 448` | 6 | 296.693 | `allocated drift = 0` | 稳定，峰值波动可接受 |
| sam3-semantic-cuda-extended | CUDA | `768 x 512` | 6 | 555.471 | `allocated drift = 0` | 稳定，reserved 增长后趋于平台化 |

### 扩展结论

- `YOLOE text-prompt` 在更大图尺寸和更长迭代下仍保持较小 CPU 内存漂移，CUDA `allocated` 仍为 `0 drift`。
- `SAM3 semantic-segment` 在更大图尺寸下 CPU 平均耗时上升到约 `27.5 s`，但内存漂移没有放大到阈值附近；CUDA 仍表现为 `allocated drift = 0`。
- 以当前基础基线和扩展基线共同判断，`YOLOE / SAM3` 的本地会话驻留和重复推理稳定性已达到“可以继续向更接近正式可用阶段收口”的程度。

## 建议下一步

1. 在目标机器类型发生变化时，重新执行本文件并更新基线。
2. 在继续扩大默认启用范围前，优先补 workflow app 侧接入说明、排障手册和视频/多帧扩展边界说明。
3. 如果后面再扩到多帧、视频或更高分辨率资产，再单独新增对应的 integration soak 文件，而不是继续把更多场景塞进现有基础基线文件。

## `SAM3 video-interactive memory-attention` 基线

### 说明

- 本轮基线只覆盖 `memory-attention-tracker` 的复合场景：
  - 更长窗口
  - 更多对象数
- 由于 CPU 成本明显高于单图链，当前先固定为：
  - `1` 次 warm run
  - `1` 次显式测量
- 该文件仍然只在显式指定路径时执行，不进入默认回归。

### 当前执行场景

- 视频窗口：`6` 帧
- 分辨率：`192 x 144`
- 对象数：`4`
- tracking mode：`memory-attention-tracker`

### 当前结果

| benchmark | 平台 | 窗口/对象 | 迭代数 | avg(ms) | 漂移 | 当前判断 |
| --- | --- | --- | ---: | ---: | --- | --- |
| sam3-video-interactive-attention-cpu-extended | CPU | `6 frames / 4 objects` | 1 | 123,844.313 | `32.03 MB` | 稳定，CPU 明显较重，但漂移远低于阈值 |
| sam3-video-interactive-attention-cuda-extended | CUDA | `6 frames / 4 objects` | 1 | 3,245.492 | `allocated drift = 0` | 稳定，reserved 增长后趋于平台化 |

### 当前结论

- `memory-attention-tracker` 当前已经补了真实本地视频链 benchmark，不再只停留在单图或单元测试层面。
- CPU 复合场景耗时明显高于 `memory-prototype-state`，因此仍更适合复杂任务按需启用，而不是替代默认模式。
- CUDA 路径当前 `allocated drift = 0`，说明本轮补的 prompt dtype 修复后，显存驻留没有出现持续增长信号。
