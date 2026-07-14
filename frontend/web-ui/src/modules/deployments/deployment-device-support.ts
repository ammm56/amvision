export interface DeploymentDeviceOption {
  label: string
  value: string
}

const defaultDeploymentDeviceOption: DeploymentDeviceOption = {
  label: '自动选择（默认）',
  value: '',
}

export function buildDeploymentDeviceOptions(
  devices: Record<string, unknown> | null | undefined,
  runtimeBackend: string | null | undefined,
): DeploymentDeviceOption[] {
  const normalizedBackend = normalizeRuntimeBackend(runtimeBackend)
  if (normalizedBackend === 'openvino') {
    return buildOpenVinoDeviceOptions(devices)
  }
  if (normalizedBackend === 'tensorrt') {
    return buildTensorRtDeviceOptions(devices)
  }
  if (normalizedBackend === 'rknn') {
    return [defaultDeploymentDeviceOption, { label: 'NPU', value: 'npu' }]
  }
  if (normalizedBackend === 'onnxruntime') {
    return [defaultDeploymentDeviceOption, { label: 'cpu', value: 'cpu' }]
  }
  return buildPyTorchDeviceOptions(devices)
}

function buildPyTorchDeviceOptions(devices: Record<string, unknown> | null | undefined): DeploymentDeviceOption[] {
  return [
    defaultDeploymentDeviceOption,
    { label: 'cpu', value: 'cpu' },
    ...buildCudaDeviceOptions(devices),
  ]
}

function buildTensorRtDeviceOptions(devices: Record<string, unknown> | null | undefined): DeploymentDeviceOption[] {
  return [
    defaultDeploymentDeviceOption,
    ...buildCudaDeviceOptions(devices),
  ]
}

function buildOpenVinoDeviceOptions(devices: Record<string, unknown> | null | undefined): DeploymentDeviceOption[] {
  const openvino = readRecord(devices, 'openvino')
  const availableDevices = readStringList(openvino?.available_devices).map((value) => value.toUpperCase())
  const supportsCpu = openvino?.supports_cpu === true
    || availableDevices.length === 0
    || availableDevices.some((value) => value === 'CPU' || value.startsWith('CPU.'))
  const supportsGpu = openvino?.supports_gpu === true
    || availableDevices.some((value) => value === 'GPU' || value.startsWith('GPU.'))
  const supportsNpu = openvino?.supports_npu === true
    || availableDevices.some((value) => value === 'NPU' || value.startsWith('NPU.'))

  const options = [defaultDeploymentDeviceOption]
  options.push({ label: 'OpenVINO AUTO', value: 'auto' })
  if (supportsCpu) {
    options.push({ label: 'OpenVINO CPU', value: 'cpu' })
  }
  if (supportsGpu) {
    options.push({ label: 'OpenVINO GPU（Intel 核显 / Arc）', value: 'gpu' })
  }
  if (supportsNpu) {
    options.push({ label: 'OpenVINO NPU', value: 'npu' })
  }
  return uniqueOptions(options)
}

function buildCudaDeviceOptions(devices: Record<string, unknown> | null | undefined): DeploymentDeviceOption[] {
  const gpuCount = readGpuDeviceCount(devices)
  if (gpuCount <= 0) return []
  const options: DeploymentDeviceOption[] = [{ label: 'cuda', value: 'cuda' }]
  for (let index = 0; index < gpuCount; index += 1) {
    options.push({ label: `cuda:${index}`, value: `cuda:${index}` })
  }
  return options
}

export function hasCudaDevice(devices: Record<string, unknown> | null | undefined): boolean {
  return readGpuDeviceCount(devices) > 0
}

function normalizeRuntimeBackend(runtimeBackend: string | null | undefined): string {
  return String(runtimeBackend ?? '').trim().toLowerCase()
}

function readRecord(
  record: Record<string, unknown> | null | undefined,
  key: string,
): Record<string, unknown> | null {
  const value = record?.[key]
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function readPositiveInteger(value: unknown): number {
  const numberValue = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(numberValue) || numberValue <= 0) return 0
  return Math.floor(numberValue)
}

function readGpuDeviceCount(devices: Record<string, unknown> | null | undefined): number {
  const gpu = readRecord(devices, 'gpu')
  const rows = Array.isArray(gpu?.devices) ? gpu.devices : []
  if (rows.length > 0) return rows.length
  return Math.max(
    readPositiveInteger(gpu?.count),
    readPositiveInteger(gpu?.device_count),
    readPositiveInteger(readRecord(devices, 'cuda')?.device_count),
    readPositiveInteger(readRecord(devices, 'cuda')?.count),
  )
}

function readStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean)
}

function uniqueOptions(options: DeploymentDeviceOption[]): DeploymentDeviceOption[] {
  const seen = new Set<string>()
  return options.filter((option) => {
    if (seen.has(option.value)) return false
    seen.add(option.value)
    return true
  })
}
