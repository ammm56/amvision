import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, type Pinia } from 'pinia'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { i18n } from '@/platform/i18n'
import {
  getDeploymentSourceModelDetail,
  listDeploymentSourceModels,
  type DeploymentSourceModelDetail,
  type DeploymentSourceModelSummary,
} from '@/modules/models/services/model.service'
import DeploymentOperationsPage from './DeploymentOperationsPage.vue'
import {
  listTaskDeploymentEvents,
  listTaskDeployments,
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
  listTaskDeploymentEvents: vi.fn(),
  listTaskDeployments: vi.fn(),
  runTaskDeploymentHealthAction: vi.fn(),
  runTaskDeploymentStatusAction: vi.fn(),
}))

vi.mock('@/modules/models/services/model.service', () => ({
  getDeploymentSourceModelDetail: vi.fn(),
  listDeploymentSourceModels: vi.fn(),
}))

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
  instance_count: 2,
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
  instance_count: 1,
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
}

const warmHealth: TaskDeploymentRuntimeHealth = {
  ...coldHealth,
  warmed_instance_count: 2,
  instances: coldHealth.instances.map((item) => ({ ...item, warmed: true })),
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

function sourceModelDetail(model: DeploymentSourceModelSummary): DeploymentSourceModelDetail {
  return { ...model, versions: [], builds: [] }
}

describe('DeploymentOperationsPage', () => {
  let pinia: Pinia

  beforeEach(() => {
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
