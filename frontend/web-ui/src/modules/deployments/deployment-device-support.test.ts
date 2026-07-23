import { describe, expect, it } from 'vitest'

import { buildDeploymentDeviceOptions } from './deployment-device-support'

const labels = {
  automaticDefault: 'Automatic (Default)',
  openvinoAutoDefault: 'OpenVINO AUTO (Default)',
  openvinoGpu: 'OpenVINO GPU (Intel Integrated / Arc)',
}

describe('deployment device support', () => {
  it('builds PyTorch deployment device options from backend device diagnostics', () => {
    expect(buildDeploymentDeviceOptions(null, 'pytorch', labels)).toEqual([
      { label: 'Automatic (Default)', value: '' },
      { label: 'cpu', value: 'cpu' },
    ])
    expect(
      buildDeploymentDeviceOptions({
        gpu: {
          available: true,
          devices: [{ name: 'GPU 0' }, { name: 'GPU 1' }],
        },
        cuda: { available: true },
      }, 'pytorch', labels),
    ).toEqual([
      { label: 'Automatic (Default)', value: '' },
      { label: 'cpu', value: 'cpu' },
      { label: 'cuda', value: 'cuda' },
      { label: 'cuda:0', value: 'cuda:0' },
      { label: 'cuda:1', value: 'cuda:1' },
    ])
  })

  it('does not expose fake indexed CUDA devices for TensorRT', () => {
    expect(buildDeploymentDeviceOptions({ cuda: { available: true } }, 'tensorrt', labels)).toEqual([
      { label: 'Automatic (Default)', value: '' },
    ])
  })

  it('keeps ONNX Runtime deployment on CPU because runtime target validation only allows CPU', () => {
    expect(
      buildDeploymentDeviceOptions({
        cuda: { available: true, device_count: 1 },
        onnxruntime: { installed: true, providers: ['CUDAExecutionProvider', 'CPUExecutionProvider'] },
      }, 'onnxruntime', labels),
    ).toEqual([
      { label: 'Automatic (Default)', value: '' },
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
      }, 'openvino', labels),
    ).toEqual([
      { label: 'OpenVINO AUTO (Default)', value: 'auto' },
      { label: 'OpenVINO CPU', value: 'cpu' },
      { label: 'OpenVINO GPU (Intel Integrated / Arc)', value: 'gpu' },
      { label: 'OpenVINO NPU', value: 'npu' },
    ])
  })
})
