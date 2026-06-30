import { describe, expect, it } from 'vitest'

import { buildDeploymentDeviceOptions } from './deployment-device-support'

describe('deployment device support', () => {
  it('builds PyTorch deployment device options from backend device diagnostics', () => {
    expect(buildDeploymentDeviceOptions(null, 'pytorch')).toEqual([
      { label: '自动选择（默认）', value: '' },
      { label: 'cpu', value: 'cpu' },
    ])
    expect(
      buildDeploymentDeviceOptions({
        gpu: {
          available: true,
          devices: [{ name: 'GPU 0' }, { name: 'GPU 1' }],
        },
        cuda: { available: true },
      }, 'pytorch'),
    ).toEqual([
      { label: '自动选择（默认）', value: '' },
      { label: 'cpu', value: 'cpu' },
      { label: 'cuda', value: 'cuda' },
      { label: 'cuda:0', value: 'cuda:0' },
      { label: 'cuda:1', value: 'cuda:1' },
    ])
  })

  it('does not expose fake indexed CUDA devices for TensorRT', () => {
    expect(buildDeploymentDeviceOptions({ cuda: { available: true } }, 'tensorrt')).toEqual([
      { label: '自动选择（默认）', value: '' },
      { label: 'cuda', value: 'cuda' },
    ])
  })

  it('keeps ONNX Runtime deployment on CPU because runtime target validation only allows CPU', () => {
    expect(
      buildDeploymentDeviceOptions({
        cuda: { available: true, device_count: 1 },
        onnxruntime: { installed: true, providers: ['CUDAExecutionProvider', 'CPUExecutionProvider'] },
      }, 'onnxruntime'),
    ).toEqual([
      { label: '自动选择（默认）', value: '' },
      { label: 'cpu', value: 'cpu' },
    ])
  })

  it('maps OpenVINO GPU device to the backend gpu value used for Intel iGPU and Arc', () => {
    expect(
      buildDeploymentDeviceOptions({
        openvino: {
          installed: true,
          available_devices: ['CPU', 'GPU.0', 'NPU'],
        },
      }, 'openvino'),
    ).toEqual([
      { label: '自动选择（默认）', value: '' },
      { label: 'OpenVINO AUTO', value: 'auto' },
      { label: 'OpenVINO CPU', value: 'cpu' },
      { label: 'OpenVINO GPU（Intel 核显 / Arc）', value: 'gpu' },
      { label: 'OpenVINO NPU', value: 'npu' },
    ])
  })
})
