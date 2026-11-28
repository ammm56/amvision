import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, type Pinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { i18n } from '@/platform/i18n'
import { ApiError } from '@/shared/api/error'
import {
  listTaskDeployments,
  runTaskDeploymentStatusAction,
  type DeploymentRuntimeConfiguration,
  type TaskDeploymentInstance,
} from '@/modules/deployments/services/deployment.service'
import {
  createTaskInferenceTask,
  inferTaskDeployment,
  listDirectInferenceRecords,
  saveDirectInferenceRecord,
  type TaskInferencePayload,
} from '../services/inference.service'
import InferenceWorkspacePage from './InferenceWorkspacePage.vue'

vi.mock('@/modules/deployments/services/deployment.service', () => ({
  listTaskDeployments: vi.fn(),
  runTaskDeploymentStatusAction: vi.fn(),
}))

vi.mock('../services/inference.service', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/inference.service')>()
  return {
    ...actual,
    createTaskInferenceTask: vi.fn(),
    inferTaskDeployment: vi.fn(),
    saveDirectInferenceRecord: vi.fn(),
    listDirectInferenceRecords: vi.fn(),
    listTaskInferenceTasks: vi.fn().mockResolvedValue([]),
    listBatchInferenceTasks: vi.fn().mockResolvedValue([]),
    getDirectInferenceRecord: vi.fn(),
    deleteDirectInferenceRecord: vi.fn(),
    listProjectPublicFiles: vi.fn().mockResolvedValue([]),
  }
})

function runtimeConfig(): DeploymentRuntimeConfiguration {
  return {
    execution: {
      instance_count: 1,
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
  deployment_instance_id: 'deploy-det-1',
  project_id: 'project-1',
  display_name: 'YOLO11 检测实例',
  status: 'active',
  model_id: 'model-1',
  model_version_id: 'mv-1',
  model_build_id: 'mb-1',
  model_name: 'yolo11-s',
  model_scale: 's',
  task_type: 'detection',
  source_kind: 'model-build',
  runtime_backend: 'openvino',
  device_name: 'cpu',
  runtime_precision: 'fp32',
  runtime_execution_mode: 'sync',
  runtime_configuration: runtimeConfig(),
  input_size: { width: 640, height: 640 },
  labels: ['bolt'],
  created_at: '2026-11-27T01:00:00Z',
  updated_at: '2026-11-27T01:00:00Z',
  metadata: {},
}

function makeResult(): TaskInferencePayload {
  return {
    request_id: 'req-001',
    deployment_instance_id: 'deploy-det-1',
    model_version_id: 'mv-1',
    input_uri: 'projects/project-1/inputs/sample.jpg',
    input_source_kind: 'input_uri',
    score_threshold: 0.3,
    save_result_image: false,
    return_preview_image_base64: false,
    image_width: 640,
    image_height: 480,
    detection_count: 1,
    latency_ms: 11.4,
    infer_ms: 8.2,
    labels: ['bolt'],
    detections: [{ bbox_xyxy: [10, 10, 80, 90], score: 0.92, class_id: 0, class_name: 'bolt' }],
    runtime_session_info: {},
  }
}

async function selectInputFieldDropdown(
  wrapper: ReturnType<typeof mount>,
  ariaLabel: string,
  label: string,
): Promise<void> {
  const selectTrigger = wrapper.find(`.inf-input-card button[aria-label="${ariaLabel}"]`)
  await selectTrigger.trigger('click')
  const option = wrapper
    .findAll('.inf-input-card .ui-select__option')
    .find((btn) => btn.text().includes(label))
  await option?.trigger('click')
}

async function selectSourceMode(wrapper: ReturnType<typeof mount>, label: string): Promise<void> {
  await selectInputFieldDropdown(wrapper, '输入来源', label)
}

describe('InferenceWorkspacePage', () => {
  let pinia: Pinia

  beforeEach(() => {
    vi.clearAllMocks()
    pinia = createPinia()
    const projectStore = useProjectStore(pinia)
    const sessionStore = useSessionStore(pinia)
    projectStore.projects = [{ project_id: 'project-1', display_name: 'Project 1', description: '' }]
    projectStore.selectedProjectId = 'project-1'
    sessionStore.currentUser = {
      principal_id: 'user-1',
      principal_type: 'user',
      project_ids: ['project-1'],
      scopes: ['models:read', 'tasks:read', 'tasks:write'],
      username: 'tester',
      display_name: 'Tester',
      auth_provider_kind: 'local',
      auth_credential_kind: 'session',
    }
    sessionStore.accessToken = 'test-token'

    vi.mocked(listTaskDeployments).mockImplementation(async (taskType) =>
      taskType === 'detection'
        ? [
            deployment,
            {
              ...deployment,
              deployment_instance_id: 'deploy-det-2',
              display_name: 'yolox-m-barcodeqrcode-very-long-deployment-name-model-build-10997bfd6559',
            },
          ]
        : [],
    )
    vi.mocked(runTaskDeploymentStatusAction).mockResolvedValue({
      deployment_instance_id: 'deploy-det-1',
      display_name: 'YOLO11 检测实例',
      runtime_mode: 'sync',
      desired_state: 'running',
      observed_state: 'running',
      generation: 1,
      process_state: 'running',
      auto_restart: true,
      restart_count: 0,
      restart_count_rollover_count: 0,
      instance_count: 1,
    })
    vi.mocked(listDirectInferenceRecords).mockResolvedValue([])
  })

  async function mountPage() {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/inference', component: InferenceWorkspacePage },
        { path: '/deployments', component: { template: '<div />' } },
      ],
    })
    await router.push('/inference')
    await router.isReady()
    const wrapper = mount(InferenceWorkspacePage, {
      global: { plugins: [pinia, i18n, router] },
    })
    await flushPromises()
    return wrapper
  }

  it('switches input source dropdown, runs sync inference, and switches all 4 non-modal inspector tabs without re-inferring', async () => {
    vi.mocked(inferTaskDeployment).mockResolvedValue(makeResult())
    const wrapper = await mountPage()

    expect(wrapper.find('.inf-project-pill').exists()).toBe(false)
    await wrapper.find('.inf-deploy-select__trigger').trigger('click')
    const searchBox = document.body.querySelector('.inf-deploy-popover__search-input') as HTMLInputElement | null
    expect(searchBox).not.toBeNull()
    if (searchBox) {
      searchBox.value = 'yolox'
      searchBox.dispatchEvent(new Event('input'))
      await flushPromises()
      const options = document.body.querySelectorAll('.inf-deploy-option')
      expect(options.length).toBe(1)
    }
    await wrapper.find('.inf-deploy-select__trigger').trigger('click')

    await selectSourceMode(wrapper, 'URI')
    const uriInput = wrapper.find('input[placeholder="projects/project-1/inputs/sample.jpg"]')
    await uriInput.setValue('projects/project-1/inputs/sample.jpg')

    await wrapper.find('[data-run-inference]').trigger('click')
    await flushPromises()

    expect(inferTaskDeployment).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-inspector-panel]').exists()).toBe(false)

    await wrapper.find('[data-toggle-inspector]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-inspector-panel]').exists()).toBe(true)
    expect(wrapper.find('[data-inspector-panel]').text()).toContain('req-001')

    const inspectorTabs = wrapper.findAll('.inf-inspector__tab')
    await inspectorTabs.find((b) => b.text() === '对象')?.trigger('click')
    expect(wrapper.find('[data-inspector-panel]').text()).toContain('对象列表 (1)')

    await inspectorTabs.find((b) => b.text() === '耗时')?.trigger('click')
    expect(wrapper.find('[data-inspector-panel]').text()).toContain('阶段耗时（服务端）')

    await inspectorTabs.find((b) => b.text() === 'JSON')?.trigger('click')
    expect(wrapper.find('.inf-json-box__code').text()).toContain('"detection_count": 1')

    await wrapper.find('.inf-inspector__close').trigger('click')
    expect(wrapper.find('[data-inspector-panel]').exists()).toBe(false)
    expect(inferTaskDeployment).toHaveBeenCalledTimes(1)
  })

  it('preserves canvas result and supports retry-save when explicit persistence fails', async () => {
    vi.mocked(inferTaskDeployment).mockResolvedValue(makeResult())
    vi.mocked(saveDirectInferenceRecord)
      .mockRejectedValueOnce(new Error('disk full'))
      .mockResolvedValueOnce({
        record_id: 'direct-record-1',
        project_id: 'project-1',
        request_id: 'req-001',
        task_type: 'detection',
        deployment_instance_id: 'deploy-det-1',
        deployment_display_name: 'YOLO11 检测实例',
        input_source_kind: 'input_uri',
        input_label: 'sample.jpg',
        has_input_image: true,
        has_preview_image: false,
        result_object_key: 'projects/project-1/results/direct-inference/direct-record-1/raw-result.json',
        item_count: 1,
        parameters: {},
        result_summary: {},
        created_at: '2026-11-27T01:00:00Z',
      })

    const wrapper = await mountPage()
    await selectSourceMode(wrapper, 'URI')
    await wrapper.find('input[placeholder="projects/project-1/inputs/sample.jpg"]').setValue('projects/project-1/inputs/sample.jpg')

    await wrapper.find('.inf-checkbox input[type="checkbox"]').setValue(true)

    await wrapper.find('[data-run-inference]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('仅重试保存')
    const retryBtn = wrapper.findAll('button').find((b) => b.text().includes('仅重试保存'))
    await retryBtn?.trigger('click')
    await flushPromises()

    expect(saveDirectInferenceRecord).toHaveBeenCalledTimes(2)
    expect(inferTaskDeployment).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.inf-saved-pill').text()).toBe('已保存')
  })

  it('shows overload alert without queuing or retrying on 503', async () => {
    vi.mocked(inferTaskDeployment).mockRejectedValueOnce(new ApiError(503, { message: 'busy' }))
    const wrapper = await mountPage()
    await selectSourceMode(wrapper, 'URI')
    await wrapper.find('input[placeholder="projects/project-1/inputs/sample.jpg"]').setValue('projects/project-1/inputs/sample.jpg')

    await wrapper.find('[data-run-inference]').trigger('click')
    await flushPromises()

    expect(inferTaskDeployment).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('推理实例已满载')
  })

  it('supports switching to async mode, blocks when async channel is stopped, and submits when running', async () => {
    vi.mocked(runTaskDeploymentStatusAction).mockImplementation(async (_tt, _id, mode) => ({
      deployment_instance_id: 'deploy-det-1',
      display_name: 'YOLO11 检测实例',
      runtime_mode: mode,
      desired_state: mode === 'sync' ? 'running' : 'stopped',
      observed_state: mode === 'sync' ? 'running' : 'stopped',
      generation: 1,
      process_state: mode === 'sync' ? 'running' : 'stopped',
      auto_restart: true,
      restart_count: 0,
      restart_count_rollover_count: 0,
      instance_count: 1,
    }))

    const wrapper = await mountPage()
    await selectSourceMode(wrapper, 'URI')
    await wrapper.find('input[placeholder="projects/project-1/inputs/sample.jpg"]').setValue('projects/project-1/inputs/sample.jpg')

    await selectInputFieldDropdown(wrapper, '调用方式', '异步任务')
    await flushPromises()
    expect(wrapper.text()).toContain('异步通道未启动')
    expect((wrapper.find('[data-run-inference]').element as HTMLButtonElement).disabled).toBe(true)

    vi.mocked(runTaskDeploymentStatusAction).mockImplementation(async (_tt, _id, mode) => ({
      deployment_instance_id: 'deploy-det-1',
      display_name: 'YOLO11 检测实例',
      runtime_mode: mode,
      desired_state: 'running',
      observed_state: 'running',
      generation: 1,
      process_state: 'running',
      auto_restart: true,
      restart_count: 0,
      restart_count_rollover_count: 0,
      instance_count: 1,
    }))
    vi.mocked(createTaskInferenceTask).mockResolvedValue({
      task_id: 'async-task-1',
      status: 'queued',
      queue_name: 'inference',
      queue_task_id: 'q-1',
      deployment_instance_id: 'deploy-det-1',
      input_uri: 'projects/project-1/inputs/sample.jpg',
      input_source_kind: 'input_uri',
    })

    const confirmBtn = wrapper.find('.inf-deploy-select__trigger')
    expect(confirmBtn.exists()).toBe(true)
    const wrapper2 = await mountPage()
    await selectSourceMode(wrapper2, 'URI')
    await wrapper2.find('input[placeholder="projects/project-1/inputs/sample.jpg"]').setValue('projects/project-1/inputs/sample.jpg')
    await selectInputFieldDropdown(wrapper2, '调用方式', '异步任务')
    await wrapper2.find('input[placeholder="可选，默认使用文件名"]').setValue('单图异步测试')
    await flushPromises()
    expect((wrapper2.find('[data-run-inference]').element as HTMLButtonElement).disabled).toBe(false)

    await wrapper2.find('[data-run-inference]').trigger('click')
    await flushPromises()
    expect(createTaskInferenceTask).toHaveBeenCalledTimes(1)
    expect(vi.mocked(createTaskInferenceTask).mock.calls[0][0].displayName).toBe('单图异步测试')
  })

  it('hides batch creation and disables async submission for read-only users without tasks:write', async () => {
    const sessionStore = useSessionStore(pinia)
    if (sessionStore.currentUser) {
      sessionStore.currentUser = {
        ...sessionStore.currentUser,
        scopes: ['models:read', 'tasks:read'],
      }
    }
    const wrapper = await mountPage()
    expect(wrapper.find('[data-readonly-banner]').exists()).toBe(true)

    await selectSourceMode(wrapper, 'URI')
    await wrapper.find('input[placeholder="projects/project-1/inputs/sample.jpg"]').setValue('projects/project-1/inputs/sample.jpg')
    await selectInputFieldDropdown(wrapper, '调用方式', '异步任务')
    await flushPromises()
    expect(wrapper.text()).toContain('当前账号为只读权限，无法提交异步任务')
    expect((wrapper.find('[data-run-inference]').element as HTMLButtonElement).disabled).toBe(true)

    const tasksTabBtn = wrapper.findAll('.tab-list button, [role="tab"]').find((b) => b.text().includes('推理任务'))
    await tasksTabBtn?.trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-create-batch-btn]').exists()).toBe(false)
  })

  it('detects deployment model version change and blocks execution until user confirms new version', async () => {
    vi.mocked(inferTaskDeployment).mockResolvedValue(makeResult())
    const wrapper = await mountPage()
    await selectSourceMode(wrapper, 'URI')
    await wrapper.find('input[placeholder="projects/project-1/inputs/sample.jpg"]').setValue('projects/project-1/inputs/sample.jpg')
    await wrapper.find('[data-run-inference]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.inf-canvas-footer__row--result').exists()).toBe(true)

    vi.mocked(listTaskDeployments).mockImplementation(async (taskType) =>
      taskType === 'detection'
        ? [{ ...deployment, model_version_id: 'mv-2', model_name: 'yolo11-s v2' }]
        : [],
    )
    const projectStore = useProjectStore(pinia)
    projectStore.selectedProjectId = 'project-2'
    await flushPromises()
    projectStore.selectedProjectId = 'project-1'
    await flushPromises()

    expect(wrapper.find('[data-version-changed-banner]').exists()).toBe(true)
    expect(wrapper.text()).toContain('部署版本已更新')
    expect((wrapper.find('[data-run-inference]').element as HTMLButtonElement).disabled).toBe(true)

    await wrapper.find('[data-confirm-version-update]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-version-changed-banner]').exists()).toBe(false)
    expect((wrapper.find('[data-run-inference]').element as HTMLButtonElement).disabled).toBe(false)
  })

  it('truncates long JSON previews above 2000 lines and distinguishes snippet copy from full download', async () => {
    const manyDetections = Array.from({ length: 400 }, (_, i) => ({
      bbox_xyxy: [i, i, i + 10, i + 10] as [number, number, number, number],
      score: 0.9,
      class_id: 0,
      class_name: 'bolt',
    }))
    vi.mocked(inferTaskDeployment).mockResolvedValue({
      ...makeResult(),
      detection_count: manyDetections.length,
      detections: manyDetections,
    })

    const wrapper = await mountPage()
    await selectSourceMode(wrapper, 'URI')
    await wrapper.find('input[placeholder="projects/project-1/inputs/sample.jpg"]').setValue('projects/project-1/inputs/sample.jpg')
    await wrapper.find('[data-run-inference]').trigger('click')
    await flushPromises()

    await wrapper.find('[data-toggle-inspector]').trigger('click')
    await flushPromises()
    const jsonTab = wrapper.findAll('.inf-inspector__tab').find((b) => b.text() === 'JSON')
    await jsonTab?.trigger('click')
    await flushPromises()

    expect(wrapper.find('.inf-json-truncation-bar').text()).toContain('仅预览前 2000 行')
    expect(wrapper.find('.inf-json-box__gutter').findAll('span').length).toBe(2000)
    expect(wrapper.text()).toContain('复制当前片段')
    expect(wrapper.text()).toContain('下载完整 JSON')
    expect(wrapper.find('.inf-json-more').exists()).toBe(true)
  })
})
