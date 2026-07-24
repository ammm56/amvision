import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, type Pinia } from 'pinia'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { i18n, setI18nLocale } from '@/platform/i18n'
import {
  getDeploymentSourceModelDetail,
  listDeploymentSourceModels,
  type DeploymentSourceModelDetail,
  type DeploymentSourceModelSummary,
} from '@/modules/models/services/model.service'
import DeploymentOperationsPage from './DeploymentOperationsPage.vue'
import {
  createTaskDeployment,
  getDeploymentRuntimeCapabilities,
  listTaskDeploymentEvents,
  listTaskDeployments,
  type DeploymentRuntimeCapabilities,
  type DeploymentRuntimeConfiguration,
  runTaskDeploymentHealthAction,
  runTaskDeploymentStatusAction,
  type DeploymentHealthAction,
  type DeploymentStatusAction,
  type ModelTaskType,
  type TaskDeploymentInstance,
  type TaskDeploymentProcessEvent,
  type TaskDeploymentProcessStatus,
  type TaskDeploymentRuntimeHealth,
} from '../services/deployment.service'

vi.mock('../services/deployment.service', () => ({
  createTaskDeployment: vi.fn(),
  deleteTaskDeployment: vi.fn(),
  getDeploymentInstanceCount: (item: TaskDeploymentInstance) => item.runtime_configuration.execution.instance_count,
  getDeploymentRuntimeCapabilities: vi.fn(),
  listTaskDeploymentEvents: vi.fn(),
  listTaskDeployments: vi.fn(),
  runTaskDeploymentHealthAction: vi.fn(),
  runTaskDeploymentStatusAction: vi.fn(),
}))

vi.mock('@/modules/models/services/model.service', () => ({
  getDeploymentSourceModelDetail: vi.fn(),
  listDeploymentSourceModels: vi.fn(),
}))

function runtimeConfiguration(instanceCount: number): DeploymentRuntimeConfiguration {
  return {
    execution: {
      instance_count: instanceCount,
      isolation_level: 'session',
      overflow_policy: 'reject',
      performance_goal: 'latency',
    },
    lifecycle: {
      warmup_dummy_inference_count: null,
      warmup_dummy_image_size: null,
      keep_warm_enabled: null,
      keep_warm_interval_seconds: null,
    },
    backend_options: { kind: 'default' },
  }
}

const deployment: TaskDeploymentInstance = {
  deployment_instance_id: 'deployment-1',
  project_id: 'project-1',
  display_name: 'Barcode sync deployment',
  status: 'created',
  model_id: 'model-1',
  model_version_id: 'model-version-1',
  model_build_id: 'model-build-1',
  model_name: 'barcode-detector',
  model_scale: 'n',
  task_type: 'detection',
  source_kind: 'model-build',
  runtime_profile_id: 'runtime-profile-1',
  runtime_backend: 'tensorrt',
  device_name: 'cuda',
  runtime_precision: 'fp16',
  runtime_execution_mode: 'sync',
  runtime_configuration: runtimeConfiguration(2),
  input_size: [640, 640],
  labels: ['barcode'],
  created_at: '2026-07-10T01:00:00Z',
  updated_at: '2026-07-10T01:00:00Z',
  metadata: {},
}

const secondDeployment: TaskDeploymentInstance = {
  ...deployment,
  deployment_instance_id: 'deployment-2',
  display_name: 'Barcode cpu deployment',
  model_build_id: 'model-build-2',
  runtime_profile_id: 'runtime-profile-2',
  runtime_backend: 'openvino',
  device_name: 'cpu',
  runtime_precision: 'fp32',
  runtime_configuration: runtimeConfiguration(1),
  created_at: '2026-07-10T02:00:00Z',
  updated_at: '2026-07-10T02:00:00Z',
}

const status: TaskDeploymentProcessStatus = {
  deployment_instance_id: 'deployment-1',
  display_name: 'Barcode sync deployment',
  runtime_mode: 'sync',
  desired_state: 'running',
  process_state: 'running',
  process_id: 8123,
  auto_restart: true,
  restart_count: 1,
  restart_count_rollover_count: 0,
  last_exit_code: null,
  last_error: null,
  instance_count: 2,
}

const coldHealth: TaskDeploymentRuntimeHealth = {
  ...status,
  healthy_instance_count: 2,
  warmed_instance_count: 0,
  pinned_output_total_bytes: 2048,
  instances: [
    { instance_id: 'worker-0', healthy: true, warmed: false, busy: false },
    { instance_id: 'worker-1', healthy: true, warmed: false, busy: false },
  ],
  keep_warm: { enabled: true },
  local_buffer_broker: { pool_name: 'default' },
  requested_runtime_configuration: {},
  effective_runtime_configuration: {},
  configuration_warnings: [],
}

const warmHealth: TaskDeploymentRuntimeHealth = {
  ...coldHealth,
  warmed_instance_count: 2,
  instances: coldHealth.instances.map((item) => ({ ...item, warmed: true })),
  keep_warm: { enabled: true, activated: true },
}

const loadedButIdleHealth: TaskDeploymentRuntimeHealth = {
  ...warmHealth,
  keep_warm: { enabled: true, activated: false },
}

const event: TaskDeploymentProcessEvent = {
  deployment_instance_id: 'deployment-1',
  runtime_mode: 'sync',
  sequence: 1,
  event_type: 'runtime.started',
  created_at: '2026-07-10T01:01:00Z',
  message: 'runtime process started',
  payload: {},
}

const runtimeCapabilities: DeploymentRuntimeCapabilities = {
  runtime_backend: 'openvino',
  device_name: 'cpu',
  available: true,
  hardware: {
    cpu_physical_core_count: 8,
    cpu_logical_processor_count: 16,
  },
  supported_backend_fields: [
    'performance_hint',
    'inference_num_threads',
    'num_streams',
  ],
  read_only_properties: {},
  default_runtime_configuration: {
    ...runtimeConfiguration(1),
    backend_options: {
      kind: 'openvino-cpu',
      performance_hint: 'latency',
      inference_num_threads: 8,
      num_streams: 1,
      scheduling_core_type: 'auto',
      enable_hyper_threading: 'auto',
      enable_cpu_pinning: 'auto',
    },
  },
  warnings: [],
}

const autoRuntimeCapabilities: DeploymentRuntimeCapabilities = {
  runtime_backend: 'openvino',
  device_name: 'auto',
  available: true,
  hardware: {
    cpu_physical_core_count: 8,
    cpu_logical_processor_count: 16,
  },
  supported_backend_fields: [
    'performance_hint',
    'num_requests',
  ],
  read_only_properties: {},
  default_runtime_configuration: {
    ...runtimeConfiguration(1),
    backend_options: {
      kind: 'openvino-auto',
      performance_hint: 'latency',
      num_requests: 'auto',
    },
  },
  warnings: [],
}

const gpuRuntimeCapabilities: DeploymentRuntimeCapabilities = {
  runtime_backend: 'openvino',
  device_name: 'gpu',
  available: true,
  hardware: {
    cpu_physical_core_count: 8,
    cpu_logical_processor_count: 16,
  },
  supported_backend_fields: [
    'performance_hint',
    'num_streams',
    'num_requests',
    'inference_precision',
  ],
  read_only_properties: {},
  default_runtime_configuration: {
    ...runtimeConfiguration(1),
    backend_options: {
      kind: 'openvino-gpu',
      performance_hint: 'latency',
      num_streams: 1,
      num_requests: 'auto',
      inference_precision: 'auto',
      queue_priority: 'auto',
      queue_throttle: 'auto',
    },
  },
  warnings: [],
}

const npuRuntimeCapabilities: DeploymentRuntimeCapabilities = {
  runtime_backend: 'openvino',
  device_name: 'npu',
  available: true,
  hardware: {
    cpu_physical_core_count: 8,
    cpu_logical_processor_count: 16,
  },
  supported_backend_fields: [
    'performance_hint',
    'num_requests',
    'inference_precision',
    'turbo',
    'tiles',
    'compilation_mode_params',
  ],
  read_only_properties: {
    npu_max_tiles: 2,
  },
  default_runtime_configuration: {
    ...runtimeConfiguration(1),
    backend_options: {
      kind: 'openvino-npu',
      performance_hint: 'latency',
      num_requests: 'auto',
      inference_precision: 'auto',
      turbo: 'auto',
      tiles: 'auto',
      compilation_mode_params: null,
    },
  },
  warnings: [],
}

const latestEvent: TaskDeploymentProcessEvent = {
  ...event,
  sequence: 2,
  event_type: 'runtime.warmup.completed',
  created_at: '2026-07-10T01:02:00Z',
  message: 'runtime warmup completed',
}

const detectionSourceModel: DeploymentSourceModelSummary = {
  model_id: 'detection-model',
  scope_kind: 'project',
  model_name: 'Detection model',
  model_type: 'yolo11',
  task_type: 'detection',
  model_scale: 's',
  metadata: {},
  version_count: 1,
  build_count: 0,
  available_versions: [],
}

const classificationSourceModel: DeploymentSourceModelSummary = {
  ...detectionSourceModel,
  model_id: 'classification-model',
  model_name: 'Classification model',
  task_type: 'classification',
}

const openvinoSourceModelDetail: DeploymentSourceModelDetail = {
  ...detectionSourceModel,
  build_count: 1,
  builds: [
    {
      model_build_id: 'openvino-build-1',
      source_model_version_id: 'model-version-1',
      build_format: 'openvino-ir',
      runtime_backend: 'openvino',
      runtime_precision: 'fp32',
      runtime_profile_id: null,
      conversion_task_id: 'conversion-task-1',
      file_ids: [],
      metadata: {},
      files: [],
    },
  ],
  versions: [],
}

function sourceModelDetail(model: DeploymentSourceModelSummary): DeploymentSourceModelDetail {
  return { ...model, versions: [], builds: [] }
}

describe('DeploymentOperationsPage', () => {
  let pinia: Pinia

  beforeEach(() => {
    setI18nLocale('zh-CN')
    pinia = createPinia()
    const projectStore = useProjectStore(pinia)
    const sessionStore = useSessionStore(pinia)

    projectStore.projects = [{ project_id: 'project-1', display_name: 'Project 1', description: '' }]
    projectStore.selectedProjectId = 'project-1'
    sessionStore.currentUser = {
      principal_id: 'user-1',
      principal_type: 'user',
      project_ids: ['project-1'],
      scopes: ['models:write', 'models:read'],
      username: 'tester',
      display_name: 'Tester',
      auth_provider_kind: 'local',
      auth_credential_kind: 'session',
    }
    sessionStore.accessToken = 'test-token'
    sessionStore.bootstrap = {
      auth_mode: 'local',
      bearer_auth_enabled: true,
      websocket_query_token_enabled: true,
      default_project_id: 'project-1',
      projects: [],
      features: {},
      limits: {},
      devices: {
        cuda: { available: true, device_count: 1 },
        gpu: { available: true, devices: [{ name: 'GPU 0' }] },
        openvino: {
          installed: true,
          available_devices: ['CPU', 'GPU.0', 'NPU'],
        },
      },
    } as never

    vi.mocked(listTaskDeployments).mockImplementation(async (taskType: ModelTaskType) => (
      taskType === 'detection' ? [deployment] : []
    ))
    vi.mocked(runTaskDeploymentStatusAction).mockImplementation(
      async (_taskType: ModelTaskType, _deploymentId: string, mode: string, action: DeploymentStatusAction) => ({
        ...status,
        deployment_instance_id: _deploymentId,
        display_name: _deploymentId,
        runtime_mode: mode,
        process_state: action === 'stop' ? 'stopped' : 'running',
      }),
    )
    vi.mocked(runTaskDeploymentHealthAction).mockImplementation(
      async (_taskType: ModelTaskType, _deploymentId: string, mode: string, action: DeploymentHealthAction) => ({
        ...(action === 'warmup' ? warmHealth : coldHealth),
        deployment_instance_id: _deploymentId,
        display_name: _deploymentId,
        runtime_mode: mode,
      }),
    )
    vi.mocked(listTaskDeploymentEvents).mockResolvedValue([event])
    vi.mocked(getDeploymentRuntimeCapabilities).mockImplementation(async (_backend, device) => {
      if (device === 'cpu') return runtimeCapabilities
      if (device.startsWith('gpu')) return gpuRuntimeCapabilities
      if (device === 'npu') return npuRuntimeCapabilities
      return autoRuntimeCapabilities
    })
    vi.mocked(createTaskDeployment).mockImplementation(async (input) => ({
      ...secondDeployment,
      deployment_instance_id: 'created-deployment',
      task_type: input.taskType,
      runtime_backend: input.runtimeBackend ?? 'openvino',
      runtime_precision: input.runtimePrecision ?? 'fp32',
      device_name: input.deviceName ?? '',
      runtime_configuration: input.runtimeConfiguration,
      display_name: input.displayName ?? '',
    }))
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders deployment runtime health and dispatches runtime actions', async () => {
    const wrapper = mount(DeploymentOperationsPage, {
      global: {
        plugins: [pinia, i18n],
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Barcode sync deployment')
    expect(wrapper.text()).toContain('running')
    expect(wrapper.text()).toContain('2048')
    expect(wrapper.text()).toContain('runtime.started')
    expect(runTaskDeploymentStatusAction).toHaveBeenCalledWith('detection', 'deployment-1', 'sync', 'status')
    expect(runTaskDeploymentHealthAction).toHaveBeenCalledWith('detection', 'deployment-1', 'sync', 'health')

    await clickButtonByText(wrapper, '预热')
    await flushPromises()
    expect(runTaskDeploymentHealthAction).toHaveBeenCalledWith('detection', 'deployment-1', 'sync', 'warmup')

    await clickButtonByText(wrapper, '重置')
    await flushPromises()
    expect(runTaskDeploymentHealthAction).toHaveBeenCalledWith('detection', 'deployment-1', 'sync', 'reset')

    await clickButtonByText(wrapper, '停止')
    await flushPromises()
    expect(runTaskDeploymentStatusAction).toHaveBeenCalledWith('detection', 'deployment-1', 'sync', 'stop')
  })

  it('keeps warmup available when sessions are loaded but device keep-warm is inactive', async () => {
    vi.mocked(runTaskDeploymentHealthAction).mockImplementation(
      async (_taskType: ModelTaskType, _deploymentId: string, mode: string, action: DeploymentHealthAction) => ({
        ...(action === 'warmup' ? warmHealth : loadedButIdleHealth),
        deployment_instance_id: _deploymentId,
        display_name: _deploymentId,
        runtime_mode: mode,
      }),
    )
    const wrapper = mount(DeploymentOperationsPage, {
      global: {
        plugins: [pinia, i18n],
      },
    })
    await flushPromises()

    await clickButtonByText(wrapper, '预热')
    await flushPromises()

    expect(runTaskDeploymentHealthAction).toHaveBeenCalledWith(
      'detection',
      'deployment-1',
      'sync',
      'warmup',
    )
  })

  it('renders deployment events newest first without depending on API order', async () => {
    vi.mocked(listTaskDeploymentEvents).mockResolvedValue([event, latestEvent])

    const wrapper = mount(DeploymentOperationsPage, {
      global: {
        plugins: [pinia, i18n],
      },
    })
    await flushPromises()

    const renderedEvents = wrapper.findAll('.deployment-events-panel li')
    expect(renderedEvents).toHaveLength(2)
    expect(renderedEvents[0]?.text()).toContain('runtime.warmup.completed')
    expect(renderedEvents[1]?.text()).toContain('runtime.started')
  })

  it('refreshes all runtime states and scopes busy buttons to the operated deployment', async () => {
    vi.mocked(listTaskDeployments).mockImplementation(async (taskType: ModelTaskType) => (
      taskType === 'detection' ? [deployment, secondDeployment] : []
    ))

    let resolveStop!: (value: TaskDeploymentProcessStatus) => void
    const stopPromise = new Promise<TaskDeploymentProcessStatus>((resolve) => {
      resolveStop = resolve
    })

    vi.mocked(runTaskDeploymentStatusAction).mockImplementation(
      async (_taskType: ModelTaskType, deploymentId: string, mode: string, action: DeploymentStatusAction) => {
        if (deploymentId === 'deployment-1' && action === 'stop') {
          return stopPromise
        }
        return {
          ...status,
          deployment_instance_id: deploymentId,
          display_name: deploymentId,
          runtime_mode: mode,
          process_state: action === 'stop' ? 'stopped' : 'running',
        }
      },
    )

    const wrapper = mount(DeploymentOperationsPage, {
      global: {
        plugins: [pinia, i18n],
      },
    })
    await flushPromises()

    expect(runTaskDeploymentStatusAction).toHaveBeenCalledWith('detection', 'deployment-1', 'sync', 'status')
    expect(runTaskDeploymentStatusAction).toHaveBeenCalledWith('detection', 'deployment-2', 'sync', 'status')
    expect(findDeploymentActionButton(wrapper, 'deployment-1', 'stop').attributes('disabled')).toBeUndefined()
    expect(findDeploymentActionButton(wrapper, 'deployment-2', 'stop').attributes('disabled')).toBeUndefined()

    await findDeploymentActionButton(wrapper, 'deployment-1', 'stop').trigger('click')
    await nextTick()

    expect(findDeploymentActionButton(wrapper, 'deployment-1', 'stop').attributes('disabled')).toBeDefined()
    expect(findDeploymentActionButton(wrapper, 'deployment-2', 'stop').attributes('disabled')).toBeUndefined()

    resolveStop({
      ...status,
      deployment_instance_id: 'deployment-1',
      display_name: 'deployment-1',
      runtime_mode: 'sync',
      desired_state: 'stopped',
      process_state: 'stopped',
    })
    await flushPromises()

    expect(findDeploymentActionButton(wrapper, 'deployment-2', 'stop').attributes('disabled')).toBeUndefined()
  })

  it('refreshes selected deployment runtime without flashing card state or disabling actions', async () => {
    vi.mocked(listTaskDeployments).mockImplementation(async (taskType: ModelTaskType) => (
      taskType === 'detection' ? [deployment, secondDeployment] : []
    ))

    const wrapper = mount(DeploymentOperationsPage, {
      global: {
        plugins: [pinia, i18n],
      },
    })
    await flushPromises()

    let resolveSelectedStatus!: (value: TaskDeploymentProcessStatus) => void
    const selectedStatusPromise = new Promise<TaskDeploymentProcessStatus>((resolve) => {
      resolveSelectedStatus = resolve
    })

    vi.mocked(runTaskDeploymentStatusAction).mockClear()
    vi.mocked(runTaskDeploymentHealthAction).mockClear()
    vi.mocked(runTaskDeploymentStatusAction).mockImplementation(
      async (_taskType: ModelTaskType, deploymentId: string, mode: string, action: DeploymentStatusAction) => {
        if (deploymentId === 'deployment-2' && action === 'status') {
          return selectedStatusPromise
        }
        return {
          ...status,
          deployment_instance_id: deploymentId,
          display_name: deploymentId,
          runtime_mode: mode,
          process_state: action === 'stop' ? 'stopped' : 'running',
        }
      },
    )

    const secondCard = wrapper.find('[data-deployment-id="deployment-2"]')
    expect(secondCard.exists(), 'deployment-2 card exists').toBe(true)
    await secondCard.trigger('click')
    await nextTick()

    expect(runTaskDeploymentStatusAction).toHaveBeenCalledWith('detection', 'deployment-2', 'sync', 'status')
    expect(wrapper.text()).not.toContain('刷新中')
    expect(findDeploymentActionButton(wrapper, 'deployment-2', 'stop').attributes('disabled')).toBeUndefined()
    expect(findDeploymentActionButton(wrapper, 'deployment-1', 'stop').attributes('disabled')).toBeUndefined()

    resolveSelectedStatus({
      ...status,
      deployment_instance_id: 'deployment-2',
      display_name: 'deployment-2',
      runtime_mode: 'sync',
      desired_state: 'running',
      process_state: 'running',
    })
    await flushPromises()

    expect(runTaskDeploymentHealthAction).toHaveBeenCalledWith('detection', 'deployment-2', 'sync', 'health')
    expect(findDeploymentActionButton(wrapper, 'deployment-2', 'stop').attributes('disabled')).toBeUndefined()
  })

  it('keeps picker content stable while a new task type loads and replaces it atomically', async () => {
    let resolveClassificationModels!: (models: DeploymentSourceModelSummary[]) => void
    const classificationModelsPromise = new Promise<DeploymentSourceModelSummary[]>((resolve) => {
      resolveClassificationModels = resolve
    })
    vi.mocked(listDeploymentSourceModels).mockImplementation(async (_projectId, taskType) => (
      taskType === 'classification'
        ? classificationModelsPromise
        : [detectionSourceModel]
    ))
    vi.mocked(getDeploymentSourceModelDetail).mockImplementation(async (_projectId, modelId) => (
      sourceModelDetail(modelId === classificationSourceModel.model_id ? classificationSourceModel : detectionSourceModel)
    ))

    const wrapper = mount(DeploymentOperationsPage, {
      global: { plugins: [pinia, i18n] },
    })
    await flushPromises()
    await clickButtonByText(wrapper, '选择部署来源')
    await flushPromises()

    expect(wrapper.text()).toContain('Detection model')
    await clickButtonByText(wrapper, 'classification')
    await nextTick()

    const pickerBody = wrapper.find('.model-picker-shell__body')
    expect(pickerBody.attributes('aria-busy')).toBe('true')
    expect(wrapper.text()).toContain('Detection model')

    resolveClassificationModels([classificationSourceModel])
    await flushPromises()

    expect(pickerBody.attributes('aria-busy')).toBe('false')
    expect(wrapper.text()).not.toContain('Detection model')
    expect(wrapper.text()).toContain('Classification model')
  })

  it('renders guarded OpenVINO CPU controls with shared select components', async () => {
    vi.mocked(listDeploymentSourceModels).mockResolvedValue([detectionSourceModel])
    vi.mocked(getDeploymentSourceModelDetail).mockResolvedValue(openvinoSourceModelDetail)

    const wrapper = mount(DeploymentOperationsPage, {
      global: { plugins: [pinia, i18n] },
    })
    await flushPromises()

    await clickButtonByText(wrapper, '选择部署来源')
    await flushPromises()
    await clickButtonByText(wrapper, '使用构建')
    await flushPromises()

    const initialDeviceField = findFieldByText(wrapper, 'Device')
    expect(initialDeviceField.find('.ui-select__button').text()).toContain('OpenVINO AUTO（默认）')
    expect(wrapper.text()).not.toContain('OpenVINO streams')

    const requestsField = findFieldByText(wrapper, 'OpenVINO 并发推理请求数')
    expect(requestsField.find('.ui-select__button').text()).toContain('自动（推荐）')
    await requestsField.find('.ui-select__button').trigger('click')
    await nextTick()
    const manualOption = requestsField.findAll('.ui-select__option').find((item) => item.text().includes('手动指定'))
    expect(manualOption, 'manual infer request option exists').toBeTruthy()
    await manualOption!.trigger('click')
    await nextTick()
    expect(requestsField.find('.field-control-row').exists()).toBe(true)
    expect(requestsField.find('input').attributes('type')).toBe('number')
    expect(requestsField.find('input').attributes('min')).toBe('1')

    const deviceField = findFieldByText(wrapper, 'Device')
    await deviceField.find('.ui-select__button').trigger('click')
    await nextTick()
    const cpuOption = deviceField.findAll('.ui-select__option').find((item) => item.text().includes('OpenVINO CPU'))
    expect(cpuOption, 'OpenVINO CPU option exists').toBeTruthy()
    await cpuOption!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('平台性能目标')
    expect(wrapper.text()).toContain('OpenVINO 性能策略')
    expect(wrapper.text()).toContain('OpenVINO 推理线程数')
    expect(wrapper.text()).toContain('保持设备活跃')
    expect(wrapper.findAll('select')).toHaveLength(0)
    expect(wrapper.find('.deployment-create-grid').findAll('small')).toHaveLength(0)

    const threadsField = findFieldByText(wrapper, 'OpenVINO 推理线程数')
    expect(threadsField.find('.ui-select__button').text()).toContain('8')
    await threadsField.find('.ui-select__button').trigger('click')
    await nextTick()
    expect(threadsField.findAll('.ui-select__option')).toHaveLength(8)

    const streamsInput = findFieldByText(wrapper, 'OpenVINO streams').find('input')
    expect(streamsInput.attributes('type')).toBe('number')
    expect(streamsInput.attributes('min')).toBe('1')
    expect((streamsInput.element as HTMLInputElement).value).toBe('1')
    await streamsInput.setValue('0')
    await streamsInput.trigger('blur')
    expect((streamsInput.element as HTMLInputElement).value).toBe('1')

    setI18nLocale('en-US')
    await nextTick()
    expect(wrapper.text()).toContain('OpenVINO Performance Hint')
    expect(wrapper.text()).toContain('OpenVINO Inference Threads')
    expect(wrapper.text()).toContain('Keep Device Active')
    expect(wrapper.text()).not.toContain('OpenVINO 性能策略')

    setI18nLocale('ja-JP')
    await nextTick()
    expect(wrapper.text()).toContain('OpenVINO パフォーマンス戦略')
    expect(wrapper.text()).toContain('デプロイ元モデル')
    expect(wrapper.text()).toContain('デバイスをアクティブに維持')

    setI18nLocale('ko-KR')
    await nextTick()
    expect(wrapper.text()).toContain('OpenVINO 성능 전략')
    expect(wrapper.text()).toContain('배포 소스 모델')
    expect(wrapper.text()).toContain('장치 활성 상태 유지')
  })

  it('disables device keep-warm by default and submits an explicit per-deployment override', async () => {
    vi.mocked(listDeploymentSourceModels).mockResolvedValue([detectionSourceModel])
    vi.mocked(getDeploymentSourceModelDetail).mockResolvedValue(openvinoSourceModelDetail)

    const wrapper = mount(DeploymentOperationsPage, {
      global: { plugins: [pinia, i18n] },
    })
    await flushPromises()
    await clickButtonByText(wrapper, '选择部署来源')
    await flushPromises()
    await clickButtonByText(wrapper, '使用构建')
    await flushPromises()

    const keepWarmField = findFieldByText(wrapper, '保持设备活跃')
    expect(keepWarmField.find('.ui-select__button').text()).toContain('禁用')

    await wrapper.find('.deployment-create-panel').trigger('submit')
    await flushPromises()
    expect(vi.mocked(createTaskDeployment).mock.calls.at(-1)?.[0]
      .runtimeConfiguration.lifecycle.keep_warm_enabled).toBe(false)

    await keepWarmField.find('.ui-select__button').trigger('click')
    await nextTick()
    const enabledOption = keepWarmField.findAll('.ui-select__option')
      .find((item) => item.text().includes('启用'))
    expect(enabledOption, 'keep-warm enabled option exists').toBeTruthy()
    await enabledOption!.trigger('click')
    await wrapper.find('.deployment-create-panel').trigger('submit')
    await flushPromises()

    expect(vi.mocked(createTaskDeployment).mock.calls.at(-1)?.[0]
      .runtimeConfiguration.lifecycle.keep_warm_enabled).toBe(true)
  })

  it('distinguishes FP32 model artifact precision from the OpenVINO GPU execution precision hint', async () => {
    vi.mocked(listDeploymentSourceModels).mockResolvedValue([detectionSourceModel])
    vi.mocked(getDeploymentSourceModelDetail).mockResolvedValue(openvinoSourceModelDetail)

    const wrapper = mount(DeploymentOperationsPage, {
      global: { plugins: [pinia, i18n] },
    })
    await flushPromises()
    await clickButtonByText(wrapper, '选择部署来源')
    await flushPromises()
    await clickButtonByText(wrapper, '使用构建')
    await flushPromises()

    const sourcePrecision = wrapper.findAll('.deployment-source-summary__grid > div')
      .find((item) => item.text().includes('模型文件精度'))
    expect(sourcePrecision, 'model artifact precision exists').toBeTruthy()
    expect(sourcePrecision!.text()).toContain('fp32')

    const deviceField = findFieldByText(wrapper, 'Device')
    await deviceField.find('.ui-select__button').trigger('click')
    await nextTick()
    const gpuOption = deviceField.findAll('.ui-select__option')
      .find((item) => item.text().includes('OpenVINO GPU'))
    expect(gpuOption, 'OpenVINO GPU option exists').toBeTruthy()
    await gpuOption!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('OpenVINO streams')
    const precisionField = findFieldByText(wrapper, 'OpenVINO 执行精度')
    expect(precisionField.find('.ui-select__button').text()).toContain('自动（推荐）')
    await precisionField.find('.ui-select__button').trigger('click')
    await nextTick()
    const precisionOptions = precisionField.findAll('.ui-select__option')
    expect(precisionOptions.map((item) => item.text())).toEqual([
      '自动（推荐）',
      'FP16',
      'FP32',
    ])
    await precisionOptions[1]!.trigger('click')

    setI18nLocale('en-US')
    await nextTick()
    expect(wrapper.text()).toContain('Model Artifact Precision')
    expect(wrapper.text()).toContain('OpenVINO Inference Precision')
    setI18nLocale('ja-JP')
    await nextTick()
    expect(wrapper.text()).toContain('モデルファイル精度')
    expect(wrapper.text()).toContain('OpenVINO 実行精度')
    setI18nLocale('ko-KR')
    await nextTick()
    expect(wrapper.text()).toContain('모델 파일 정밀도')
    expect(wrapper.text()).toContain('OpenVINO 실행 정밀도')

    await wrapper.find('.deployment-create-panel').trigger('submit')
    await flushPromises()

    expect(createTaskDeployment).toHaveBeenCalledTimes(1)
    const createInput = vi.mocked(createTaskDeployment).mock.calls.at(-1)?.[0]
    expect(createInput?.runtimePrecision).toBe('fp32')
    expect(createInput?.runtimeConfiguration.backend_options).toMatchObject({
      kind: 'openvino-gpu',
      inference_precision: 'f16',
    })
  })

  it('renders and submits the complete capability-driven OpenVINO NPU configuration', async () => {
    vi.mocked(listDeploymentSourceModels).mockResolvedValue([detectionSourceModel])
    vi.mocked(getDeploymentSourceModelDetail).mockResolvedValue(openvinoSourceModelDetail)

    const wrapper = mount(DeploymentOperationsPage, {
      global: { plugins: [pinia, i18n] },
    })
    await flushPromises()
    await clickButtonByText(wrapper, '选择部署来源')
    await flushPromises()
    await clickButtonByText(wrapper, '使用构建')
    await flushPromises()

    const deviceField = findFieldByText(wrapper, 'Device')
    await deviceField.find('.ui-select__button').trigger('click')
    await nextTick()
    const npuOption = deviceField.findAll('.ui-select__option').find((item) => item.text().includes('OpenVINO NPU'))
    expect(npuOption, 'OpenVINO NPU option exists').toBeTruthy()
    await npuOption!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('OpenVINO streams')
    expect(wrapper.text()).not.toContain('OpenVINO 推理线程数')
    expect(wrapper.text()).toContain('OpenVINO 执行精度')
    expect(wrapper.text()).toContain('NPU turbo')
    expect(wrapper.text()).toContain('NPU tiles')
    expect(wrapper.text()).toContain('NPU compilation mode params')

    const precisionField = findFieldByText(wrapper, 'OpenVINO 执行精度')
    await precisionField.find('.ui-select__button').trigger('click')
    await nextTick()
    expect(precisionField.findAll('.ui-select__option')).toHaveLength(2)
    expect(precisionField.text()).not.toContain('FP32')

    const tilesField = findFieldByText(wrapper, 'NPU tiles')
    await tilesField.find('.ui-select__button').trigger('click')
    await nextTick()
    const manualTilesOption = tilesField.findAll('.ui-select__option').find((item) => item.text().includes('手动指定'))
    expect(manualTilesOption, 'manual NPU tiles option exists').toBeTruthy()
    await manualTilesOption!.trigger('click')
    await nextTick()
    const tilesInput = tilesField.find('input')
    expect(tilesInput.attributes('max')).toBe('2')
    await tilesInput.setValue('3')
    await tilesInput.trigger('blur')
    expect((tilesInput.element as HTMLInputElement).value).toBe('2')

    await findFieldByText(wrapper, 'NPU compilation mode params').find('input').setValue('optimization-level=1')
    await wrapper.find('.deployment-create-panel').trigger('submit')
    await flushPromises()

    expect(createTaskDeployment).toHaveBeenCalledTimes(1)
    const createInput = vi.mocked(createTaskDeployment).mock.calls.at(-1)?.[0]
    expect(createInput?.deviceName).toBe('npu')
    expect(createInput?.runtimeConfiguration.backend_options).toEqual({
      kind: 'openvino-npu',
      performance_hint: 'latency',
      num_requests: 'auto',
      inference_precision: 'auto',
      turbo: 'auto',
      tiles: 2,
      compilation_mode_params: 'optimization-level=1',
    })
  })
})

async function clickButtonByText(wrapper: VueWrapper, text: string): Promise<void> {
  const button = wrapper.findAll('button').find((item) => item.text().includes(text))
  expect(button, `button ${text} exists`).toBeTruthy()
  await button!.trigger('click')
}

function findDeploymentActionButton(wrapper: VueWrapper, deploymentId: string, action: string) {
  const button = wrapper.find(`[data-deployment-id="${deploymentId}"] [data-deployment-action="${action}"]`)
  expect(button.exists(), `${deploymentId} ${action} button exists`).toBe(true)
  return button
}

function findFieldByText(wrapper: VueWrapper, text: string) {
  const field = wrapper.findAll('.field').find((item) => item.text().includes(text))
  expect(field, `field ${text} exists`).toBeTruthy()
  return field!
}
