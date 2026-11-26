import type {
  TaskDeploymentInstance,
  TaskDeploymentProcessStatus,
  TaskDeploymentRuntimeHealth,
} from './services/deployment.service'

export type DeploymentVisualStateKey =
  | 'running'
  | 'busyFull'
  | 'starting'
  | 'stopped'
  | 'degraded'
  | 'failed'
  | 'notInspected'

export type DeploymentVisualTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'

export interface DeploymentCapacitySummary {
  total: number
  ready: number
  warmed: number
  busy: number
  isFull: boolean
}

export interface DeploymentConfigComparisonRow {
  group: 'execution' | 'lifecycle' | 'backend_options'
  field: string
  requested: string
  effective: string
  changed: boolean
}

export interface HostBackendCapabilityRow {
  backend: string
  backendKey: string
  device: string
  available: boolean
  reason: string
}

/** 将内部 runtime_backend 标识格式化为标准显示名称。 */
export function formatDeploymentBackend(backend: string | null | undefined): string {
  const normalized = String(backend ?? '').trim().toLowerCase()
  const labels: Record<string, string> = {
    openvino: 'OpenVINO',
    'openvino-ir': 'OpenVINO',
    tensorrt: 'TensorRT',
    'tensorrt-engine': 'TensorRT',
    onnxruntime: 'ONNX Runtime',
    onnx: 'ONNX Runtime',
    'onnx-optimized': 'ONNX Runtime',
    pytorch: 'PyTorch',
    coreml: 'CoreML',
    rknn: 'ARM NPU',
  }
  return labels[normalized] || (backend ? backend : 'PyTorch')
}

/** 将精度标识格式化为大写，空值返回空字符串。 */
export function formatDeploymentPrecision(precision: string | null | undefined): string {
  const raw = String(precision ?? '').trim()
  return raw ? raw.toUpperCase() : ''
}

/** 将设备标识统一格式化为标准大小写形式（如 CPU、CUDA、CUDA:0、GPU、NPU、AUTO），空值返回空字符串。 */
export function formatDeploymentDeviceName(device: string | null | undefined): string {
  const raw = String(device ?? '').trim()
  if (!raw) return ''
  const lower = raw.toLowerCase()
  if (lower === 'cpu' || lower === 'npu' || lower === 'auto' || lower === 'gpu' || lower === 'cuda') return lower.toUpperCase()
  if (lower.startsWith('cuda:')) return `CUDA:${raw.slice(5)}`
  if (lower.startsWith('gpu.')) return `GPU.${raw.slice(4)}`
  if (lower.startsWith('cpu.')) return `CPU.${raw.slice(4)}`
  return raw
}

/** 拼接列表与详情共用的运行后端/精度/设备摘要。 */
export function formatDeploymentRuntimeSummary(
  deployment: Pick<TaskDeploymentInstance, 'runtime_backend' | 'runtime_precision' | 'device_name'>,
): string {
  const backend = formatDeploymentBackend(deployment.runtime_backend || 'pytorch')
  const precision = formatDeploymentPrecision(deployment.runtime_precision || 'fp32')
  const device = formatDeploymentDeviceName(deployment.device_name)
  return device ? `${backend} ${precision} · ${device}` : `${backend} ${precision}`
}

/** 从健康快照与部署配置中计算实例就绪、预热及在途执行数量。 */
export function computeDeploymentCapacity(
  deployment: Pick<TaskDeploymentInstance, 'runtime_configuration'>,
  health?: TaskDeploymentRuntimeHealth | null,
): DeploymentCapacitySummary {
  const configuredTotal = Math.max(0, Number(deployment.runtime_configuration?.execution?.instance_count ?? 1))
  const total = health ? Math.max(0, Number(health.instance_count ?? configuredTotal)) : configuredTotal
  if (!health) {
    return { total, ready: 0, warmed: 0, busy: 0, isFull: false }
  }
  const ready = Math.max(0, Number(health.healthy_instance_count ?? 0))
  const warmed = Math.max(0, Number(health.warmed_instance_count ?? 0))
  const busy = Array.isArray(health.instances)
    ? health.instances.filter(item => item.busy).length
    : 0
  return {
    total,
    ready,
    warmed,
    busy,
    isFull: total > 0 && busy >= total,
  }
}

/** 将容量与状态组合为面向列表的简洁文案（与设计图一致）。 */
export function formatDeploymentCapacityLabel(
  summary: DeploymentCapacitySummary,
  visualKey: DeploymentVisualStateKey,
  labels: {
    executing: string
    full: string
    loading: string
    ready: string
    stopped: string
  },
): string {
  if (visualKey === 'stopped' || visualKey === 'notInspected') {
    return labels.stopped
  }
  if (visualKey === 'starting') {
    return labels.loading
  }
  if (visualKey === 'busyFull' || summary.isFull) {
    return labels.full
  }
  if (summary.busy > 0) {
    return labels.executing
  }
  return labels.ready
}

/** 根据进程观测状态与实时负载判定统一展示状态，区分满载与故障。 */
export function resolveDeploymentVisualState(
  status?: TaskDeploymentProcessStatus | null,
  health?: TaskDeploymentRuntimeHealth | null,
): { key: DeploymentVisualStateKey; tone: DeploymentVisualTone } {
  const processState = String(status?.process_state ?? '').trim().toLowerCase()
  const observedState = String(status?.observed_state ?? '').trim().toLowerCase()
  const desiredState = String(status?.desired_state ?? '').trim().toLowerCase()

  if (!status) {
    return { key: 'notInspected', tone: 'neutral' }
  }
  if ([processState, observedState].some(value => value.includes('fail') || value.includes('crash') || value.includes('unavailable'))) {
    return { key: 'failed', tone: 'danger' }
  }
  if (observedState === 'degraded') {
    return { key: 'degraded', tone: 'warning' }
  }
  if (processState === 'starting' || observedState === 'starting') {
    return { key: 'starting', tone: 'info' }
  }
  if (processState === 'running' || observedState === 'running') {
    if (health && health.instance_count > 0 && Array.isArray(health.instances)) {
      const busyCount = health.instances.filter(item => item.busy).length
      if (busyCount >= health.instance_count) {
        return { key: 'busyFull', tone: 'info' }
      }
    }
    return { key: 'running', tone: 'success' }
  }
  if (desiredState === 'stopped' || processState === 'stopped' || observedState === 'stopped') {
    return { key: 'stopped', tone: 'neutral' }
  }
  return { key: 'notInspected', tone: 'neutral' }
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function formatConfigValue(value: unknown): string {
  if (value === undefined || value === null || value === '') return '—'
  if (Array.isArray(value)) return value.join(' × ')
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function normalizeOpenVinoPropertyValue(field: string, value: unknown): unknown {
  if (typeof value !== 'string') return value
  const trimmed = value.trim()
  if (!trimmed) return value
  const enumToken = trimmed.includes('.') ? trimmed.slice(trimmed.lastIndexOf('.') + 1) : trimmed
  if (
    field === 'performance_hint'
    || field === 'scheduling_core_type'
    || field === 'inference_precision'
    || field === 'queue_priority'
    || field === 'queue_throttle'
  ) {
    return enumToken.toLowerCase()
  }
  if ((field === 'num_streams' || field === 'num_requests' || field === 'tiles') && enumToken.toLowerCase() === 'auto') {
    return 'auto'
  }
  return value
}

function buildEffectiveBackendOptions(
  effRoot: Record<string, unknown>,
  effAllocated: Record<string, unknown>,
  reqBackend: Record<string, unknown>,
): Record<string, unknown> {
  const merged: Record<string, unknown> = {
    ...asRecord(effAllocated.backend_options),
    ...asRecord(effRoot.backend_options),
  }

  const compileProps = asRecord(effRoot.compile_properties)
  const compilePropertyMap: Array<[string, string]> = [
    ['PERFORMANCE_HINT', 'performance_hint'],
    ['INFERENCE_NUM_THREADS', 'inference_num_threads'],
    ['NUM_STREAMS', 'num_streams'],
    ['SCHEDULING_CORE_TYPE', 'scheduling_core_type'],
    ['ENABLE_HYPER_THREADING', 'enable_hyper_threading'],
    ['ENABLE_CPU_PINNING', 'enable_cpu_pinning'],
    ['PERFORMANCE_HINT_NUM_REQUESTS', 'num_requests'],
    ['INFERENCE_PRECISION_HINT', 'inference_precision'],
    ['GPU_QUEUE_PRIORITY', 'queue_priority'],
    ['GPU_QUEUE_THROTTLE', 'queue_throttle'],
    ['NPU_TURBO', 'turbo'],
    ['NPU_TILES', 'tiles'],
    ['NPU_COMPILATION_MODE_PARAMS', 'compilation_mode_params'],
  ]

  for (const [propKey, field] of compilePropertyMap) {
    const raw = compileProps[propKey] ?? effRoot[propKey] ?? effRoot[field]
    if (raw !== undefined) {
      merged[field] = normalizeOpenVinoPropertyValue(field, raw)
    }
  }

  const topLevelBackendFields = [
    'optimization_profile_index',
    'pinned_output_buffer_enabled',
    'pinned_output_buffer_max_bytes',
  ]
  for (const field of topLevelBackendFields) {
    if (effRoot[field] !== undefined) {
      merged[field] = effRoot[field]
    }
  }

  const kind = String(merged.kind ?? reqBackend.kind ?? '').trim().toLowerCase()
  const effCpuMgr = asRecord(effRoot.cpu_device_resource_manager)
  if (kind === 'openvino-cpu' && effCpuMgr.threads_per_instance !== undefined && merged.inference_num_threads === undefined) {
    merged.inference_num_threads = effCpuMgr.threads_per_instance
  }

  return merged
}

/** 对比请求运行配置与实际生效配置，生成三组参数对比行。 */
export function buildDeploymentConfigComparisonRows(
  requested: Record<string, unknown> | null | undefined,
  effective: Record<string, unknown> | null | undefined,
): DeploymentConfigComparisonRow[] {
  const reqRoot = asRecord(requested)
  const effRoot = asRecord(effective)
  const effAllocated = asRecord(effRoot.allocated_runtime_configuration)
  const groups = ['execution', 'lifecycle', 'backend_options'] as const
  const rows: DeploymentConfigComparisonRow[] = []

  for (const group of groups) {
    const reqGroup = asRecord(reqRoot[group])
    const effGroup = group === 'backend_options'
      ? buildEffectiveBackendOptions(effRoot, effAllocated, reqGroup)
      : { ...asRecord(effAllocated[group]), ...asRecord(effRoot[group]) }
    const keys = Array.from(new Set([...Object.keys(reqGroup), ...Object.keys(effGroup)]))
    for (const field of keys) {
      const reqText = formatConfigValue(reqGroup[field])
      const effText = formatConfigValue(effGroup[field])
      rows.push({
        group,
        field,
        requested: reqText,
        effective: effText,
        changed: reqText !== effText,
      })
    }
  }
  return rows
}

/** 从 /system/bootstrap.devices 生成不虚构硬件的后端设备能力表。 */
export function buildHostCapabilityRows(
  devices: Record<string, unknown> | null | undefined,
  labels: {
    noDeviceDetected: string
    notMacOs: string
    notTargetPlatform: string
  },
): HostBackendCapabilityRow[] {
  if (!devices) return []
  const rows: HostBackendCapabilityRow[] = []
  const onnx = asRecord(devices.onnxruntime)
  const onnxAvailable = Boolean(onnx.installed ?? onnx.available ?? (devices.cpu ? true : false))
  rows.push({
    backend: 'ONNX Runtime',
    backendKey: 'onnxruntime',
    device: 'CPU',
    available: onnxAvailable,
    reason: onnxAvailable ? '—' : labels.noDeviceDetected,
  })

  const openvino = asRecord(devices.openvino)
  const openvinoList = Array.isArray(openvino.available_devices)
    ? openvino.available_devices.map(item => String(item).toUpperCase())
    : []
  const ovInstalled = Boolean(openvino.installed) || Boolean(openvino.available)
  const ovCpu = ovInstalled && (Boolean(openvino.supports_cpu) || openvinoList.length === 0 || openvinoList.some(d => d.startsWith('CPU')))
  rows.push({
    backend: 'OpenVINO',
    backendKey: 'openvino',
    device: 'CPU',
    available: ovCpu,
    reason: ovCpu ? '—' : labels.noDeviceDetected,
  })

  const ovGpu = Boolean(openvino.supports_gpu) || openvinoList.some(item => item.startsWith('GPU'))
  if (ovGpu) {
    rows.push({
      backend: 'OpenVINO',
      backendKey: 'openvino',
      device: openvinoList.find(item => item.startsWith('GPU')) || 'GPU',
      available: true,
      reason: '—',
    })
  }

  const ovNpu = Boolean(openvino.supports_npu) || openvinoList.some(item => item.startsWith('NPU'))
  rows.push({
    backend: 'OpenVINO',
    backendKey: 'openvino',
    device: openvinoList.find(item => item.startsWith('NPU')) || 'NPU',
    available: ovNpu,
    reason: ovNpu ? '—' : labels.noDeviceDetected,
  })

  const trt = asRecord(devices.tensorrt)
  const gpu = asRecord(devices.gpu)
  const gpuList = Array.isArray(gpu.devices) ? gpu.devices.map(item => asRecord(item)) : []
  const trtInstalled = Boolean(trt.installed ?? trt.available)
  const cudaAvailable = trtInstalled || gpuList.length > 0 || Boolean(asRecord(devices.cuda).available)
  const gpuLabel = gpuList[0]?.name ? `CUDA:0 (${String(gpuList[0].name)})` : cudaAvailable ? 'CUDA:0' : 'CUDA:0'
  const trtAvailable = trtInstalled && gpuList.length > 0
  rows.push({
    backend: 'TensorRT',
    backendKey: 'tensorrt',
    device: gpuLabel,
    available: trtAvailable,
    reason: trtAvailable ? '—' : labels.noDeviceDetected,
  })

  const pytorch = asRecord(devices.pytorch)
  if (Object.keys(pytorch).length > 0) {
    const ptDevice = gpuList.length > 0 ? `CUDA:0 (${String(gpuList[0]?.name || 'GPU')})` : 'CPU'
    const ptAvailable = Boolean(pytorch.installed ?? pytorch.available ?? true)
    rows.push({
      backend: 'PyTorch',
      backendKey: 'pytorch',
      device: ptDevice,
      available: ptAvailable,
      reason: ptAvailable ? '—' : labels.noDeviceDetected,
    })
  }

  const coreml = asRecord(devices.coreml)
  const isMacOs = String(asRecord(devices.host).system ?? '').trim().toLowerCase() === 'darwin'
  const coremlAvailable = Boolean(coreml.available ?? coreml.installed) || isMacOs
  rows.push({
    backend: 'CoreML',
    backendKey: 'coreml',
    device: '—',
    available: coremlAvailable,
    reason: coremlAvailable ? '—' : labels.notMacOs,
  })

  const npuRuntime = asRecord(devices.npu_runtime)
  rows.push({
    backend: 'ARM NPU',
    backendKey: 'rknn',
    device: '—',
    available: Boolean(npuRuntime.available),
    reason: Boolean(npuRuntime.available) ? '—' : labels.notTargetPlatform,
  })

  return rows
}
