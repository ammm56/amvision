import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, type Pinia } from 'pinia'
import { nextTick } from 'vue'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { i18n } from '@/platform/i18n'
import { deploymentWorkspaceMessages } from '@/platform/i18n/deployment-workspace'
import ResourceMenu from '@/shared/ui/components/ResourceMenu.vue'
import DeploymentOperationsPage from '@/modules/deployments/pages/DeploymentOperationsPage.vue'
import DeploymentCapabilitiesDrawer from '@/modules/deployments/components/DeploymentCapabilitiesDrawer.vue'
import DeploymentStatusDrawer from '@/modules/deployments/components/DeploymentStatusDrawer.vue'
import DeploymentTransferRecordsTab from '@/modules/deployments/components/DeploymentTransferRecordsTab.vue'
import {
  createTaskDeployment,
  getDeploymentRuntimeCapabilities,
  listTaskDeploymentEvents,
  listTaskDeployments,
  runTaskDeploymentHealthAction,
  runTaskDeploymentStatusAction,
  type TaskDeploymentInstance,
  type TaskDeploymentProcessStatus,
  type TaskDeploymentRuntimeHealth,
} from '@/modules/deployments/services/deployment.service'
import {
  listDeploymentReferences,
  listTransfers,
  previewDeploymentDeletion,
  type DeploymentTransfer,
} from '@/modules/deployments/services/deployment-transfer.service'
import {
  getDeploymentSourceModelDetail,
  listDeploymentSourceModels,
  listProjectModelCatalog,
} from '@/modules/models/services/model.service'

enableAutoUnmount(afterEach)

vi.mock('@/modules/deployments/services/deployment.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/modules/deployments/services/deployment.service')>()),
  createTaskDeployment: vi.fn(),
  deleteTaskDeployment: vi.fn(),
  getDeploymentRuntimeCapabilities: vi.fn(),
  listTaskDeploymentEvents: vi.fn(),
  listTaskDeployments: vi.fn(),
  runTaskDeploymentHealthAction: vi.fn(),
  runTaskDeploymentStatusAction: vi.fn(),
}))

vi.mock('@/modules/deployments/services/deployment-transfer.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/modules/deployments/services/deployment-transfer.service')>()),
  listTransfers: vi.fn(),
  listDeploymentReferences: vi.fn(),
  previewDeploymentDeletion: vi.fn(),
}))

vi.mock('@/modules/models/services/model.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/modules/models/services/model.service')>()),
  getDeploymentSourceModelDetail: vi.fn(),
  listDeploymentSourceModels: vi.fn(),
  listProjectModelCatalog: vi.fn(),
  getProjectModelCatalogDetail: vi.fn().mockRejectedValue(new Error('not needed')),
}))

const sampleDeployment: TaskDeploymentInstance = {
  deployment_instance_id: 'deploy-1',
  project_id: 'project-1',
  display_name: '连接器检测服务',
  status: 'active',
  model_id: 'model-1',
  model_version_id: 'mv-1',
  model_build_id: 'build-1',
  model_name: 'YOLO11-s',
  model_scale: 's',
  task_type: 'detection',
  source_kind: 'model-build',
  runtime_profile_id: 'rp-1',
  runtime_backend: 'openvino',
  device_name: 'CPU',
  runtime_precision: 'fp16',
  runtime_execution_mode: 'sync',
  runtime_configuration: {
    execution: {
      instance_count: 2,
      isolation_level: 'session',
      overflow_policy: 'reject',
      performance_goal: 'latency',
    },
    lifecycle: {
      warmup_dummy_inference_count: null,
      warmup_dummy_image_size: null,
      keep_warm_enabled: false,
      keep_warm_interval_seconds: 0.1,
    },
    backend_options: {
      kind: 'openvino-cpu',
      performance_hint: 'latency',
      inference_num_threads: 16,
      num_streams: 1,
      scheduling_core_type: 'auto',
      enable_hyper_threading: 'auto',
      enable_cpu_pinning: 'auto',
    },
  },
  input_size: { width: 640, height: 640 },
  labels: ['ok', 'ng'],
  created_at: '2026-11-25T10:00:00Z',
  updated_at: '2026-11-25T10:00:00Z',
  metadata: {},
}

const runningStatus: TaskDeploymentProcessStatus = {
  deployment_instance_id: 'deploy-1',
  display_name: '连接器检测服务',
  runtime_mode: 'sync',
  desired_state: 'running',
  observed_state: 'running',
  generation: 2,
  process_state: 'running',
  process_id: 4321,
  auto_restart: false,
  restart_count: 0,
  restart_count_rollover_count: 0,
  last_exit_code: null,
  last_error: null,
  instance_count: 2,
}

const idleHealth: TaskDeploymentRuntimeHealth = {
  ...runningStatus,
  healthy_instance_count: 2,
  warmed_instance_count: 2,
  pinned_output_total_bytes: 0,
  instances: [
    { instance_id: 'inst-0', healthy: true, warmed: true, busy: false, inference_count: 12, error_count: 0 },
    { instance_id: 'inst-1', healthy: true, warmed: true, busy: false, inference_count: 8, error_count: 0 },
  ],
  keep_warm: { enabled: false, activated: false },
  local_buffer_broker: {},
  requested_runtime_configuration: sampleDeployment.runtime_configuration as unknown as Record<string, unknown>,
  effective_runtime_configuration: {
    execution: { instance_count: 2 },
    lifecycle: { keep_warm_enabled: false },
    backend_options: { kind: 'openvino-cpu', inference_num_threads: 8, performance_hint: 'latency' },
  },
  configuration_warnings: [],
}

describe('Deployment workspace P6 architecture & interactions', () => {
  let pinia: Pinia
  let router: Router

  beforeEach(async () => {
    vi.clearAllMocks()
    i18n.global.locale.value = 'zh-CN'
    pinia = createPinia()
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/deployments', component: DeploymentOperationsPage },
        { path: '/inference', component: { template: '<div />' } },
        { path: '/models', component: { template: '<div />' } },
        { path: '/applications', component: { template: '<div />' } },
      ],
    })
    await router.push('/deployments')
    await router.isReady()

    const sessionStore = useSessionStore(pinia)
    sessionStore.currentUser = {
      principal_id: 'user-1',
      username: 'amvar',
      display_name: 'amvar',
      scopes: ['models:read', 'models:write'],
      project_ids: ['project-1'],
      roles: ['admin'],
      must_change_password: false,
    } as never
    sessionStore.bootstrap = {
      devices: { cpu: { available: true }, openvino: { available: true } },
    } as never

    const projectStore = useProjectStore(pinia)
    projectStore.projects = [{ project_id: 'project-1', display_name: 'Demo Project' }] as never
    projectStore.selectedProjectId = 'project-1'

    vi.mocked(listTaskDeployments).mockImplementation(async (taskType) => (
      taskType === 'detection' ? [sampleDeployment] : []
    ))
    vi.mocked(runTaskDeploymentStatusAction).mockResolvedValue(runningStatus)
    vi.mocked(runTaskDeploymentHealthAction).mockResolvedValue(idleHealth)
    vi.mocked(listTaskDeploymentEvents).mockResolvedValue([])
    vi.mocked(listTransfers).mockResolvedValue([])
    vi.mocked(listDeploymentReferences).mockResolvedValue({
      items: [{
        workflow_runtime_id: 'wf-rt-1',
        application_id: 'app-1',
        display_name: '产线主流程',
        desired_state: 'running',
        observed_state: 'running',
        relation: 'direct',
      }],
      total: 1,
    })
    vi.mocked(previewDeploymentDeletion).mockResolvedValue({
      revision: 'rev-1',
      deleted_models: [],
      retained_models: [],
    })
    vi.mocked(listProjectModelCatalog).mockResolvedValue({
      items: [],
      total: 0,
      limit: 100,
      offset: 0,
    } as never)
    vi.mocked(getDeploymentRuntimeCapabilities).mockResolvedValue({
      runtime_backend: 'openvino',
      device_name: 'CPU',
      available: true,
      hardware: { cpu_physical_core_count: 16 },
      supported_backend_fields: ['performance_hint', 'inference_num_threads', 'num_streams'],
      read_only_properties: {},
      default_runtime_configuration: sampleDeployment.runtime_configuration,
      warnings: [],
    })
  })

  it('renders 3 underline tabs, unified toolbar, icon-only runtime badge, resolved version, and device capabilities drawer', async () => {
    vi.mocked(listProjectModelCatalog).mockResolvedValue({
      items: [{
        model_id: 'model-1',
        project_id: 'project-1',
        scope_kind: 'project',
        model_name: 'YOLO11-s',
        model_type: 'yolo11',
        model_scale: 's',
        task_type: 'detection',
        version_count: 1,
        build_count: 1,
        created_at: '',
        updated_at: '',
        metadata: {},
        available_versions: [{
          model_version_id: 'mv-1',
          version_number: 1,
          source_kind: 'training',
          metadata: {},
        }],
      }],
      total: 1,
      limit: 100,
      offset: 0,
    } as never)

    const wrapper = mount(DeploymentOperationsPage, {
      global: { plugins: [pinia, i18n, router] },
    })
    await flushPromises()

    expect(wrapper.text()).not.toContain('项目：')
    const tabs = wrapper.findAll('.deployment-ops-navigation .local-tabs__tab')
    expect(tabs.map(tab => tab.text())).toEqual(['部署实例', '导入记录', '导出记录'])
    const navActions = wrapper.get('.deployment-ops-navigation__actions')
    expect(navActions.text()).toContain('设备能力')
    expect(navActions.text()).toContain('导入部署实例')
    expect(navActions.text()).toContain('新建部署')

    const searchInput = wrapper.get('.deployment-toolbar .deployment-search input')
    await searchInput.setValue('连接器')
    await nextTick()
    const clearButton = wrapper.get('.deployment-toolbar .deployment-search button[aria-label="清除搜索关键词"]')
    await clearButton.trigger('click')
    await nextTick()
    expect((searchInput.element as HTMLInputElement).value).toBe('')

    const filterGroup = wrapper.get('.deployment-toolbar .deployment-filter-group')
    expect(filterGroup.findAll('.ui-select')).toHaveLength(3)
    expect(filterGroup.text()).toContain('刷新')

    const row = wrapper.get('[data-deployment-id="deploy-1"]')
    expect(row.text()).toContain('连接器检测服务')
    const modelCell = row.get('.deployment-model-cell')
    expect(modelCell.text()).toContain('YOLO11-s · v1')
    expect(modelCell.text()).not.toContain('目标检测')
    expect(modelCell.element.closest('td')?.getAttribute('title')).toBe('目标检测 · YOLO11-s · v1')
    expect(row.text()).not.toContain('· s')
    expect(row.text()).not.toContain('mv-1')
    const runtimeBadge = row.get('.deployment-runtime-badge[role="img"]')
    expect(runtimeBadge.attributes('aria-label')).toBe('OpenVINO FP16 · CPU')
    expect(runtimeBadge.attributes('title')).toBe('OpenVINO FP16 · CPU')
    expect(runtimeBadge.text()).toBe('')
    expect(row.text()).toContain('2 / 2 就绪')

    await wrapper.get('[data-deployment-action="capabilities"]').trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('设备能力')
    expect(document.body.textContent).toContain('后端设备能力')
    expect(getDeploymentRuntimeCapabilities).toHaveBeenCalledWith('openvino', 'CPU')
  })

  it('falls back cleanly to model name without scale or raw version id when model catalog fails', async () => {
    vi.mocked(listProjectModelCatalog).mockRejectedValue(new Error('catalog unavailable'))
    const wrapper = mount(DeploymentOperationsPage, {
      global: { plugins: [pinia, i18n, router] },
    })
    await flushPromises()

    const row = wrapper.get('[data-deployment-id="deploy-1"]')
    const modelCell = row.get('.deployment-model-cell')
    expect(modelCell.text()).toBe('YOLO11-s')
    expect(modelCell.text()).not.toContain('目标检测')
    expect(modelCell.element.closest('td')?.getAttribute('title')).toBe('目标检测 · YOLO11-s')
    expect(row.text()).not.toContain('· s')
    expect(row.text()).not.toContain('mv-1')
    expect(wrapper.find('.inline-error').exists()).toBe(false)
  })

  it('supports 3-step create wizard with validation and independent create vs start feedback', async () => {
    vi.mocked(listDeploymentSourceModels).mockResolvedValue([{
      model_id: 'model-1',
      project_id: 'project-1',
      scope_kind: 'project',
      model_name: 'YOLO11-s',
      model_type: 'yolo11',
      model_scale: 's',
      task_type: 'detection',
      version_count: 1,
      build_count: 1,
      created_at: '',
      updated_at: '',
      metadata: {},
    } as never])
    vi.mocked(getDeploymentSourceModelDetail).mockResolvedValue({
      model_id: 'model-1',
      project_id: 'project-1',
      scope_kind: 'project',
      model_name: 'YOLO11-s',
      model_type: 'yolo11',
      model_scale: 's',
      task_type: 'detection',
      versions: [{
        model_version_id: 'mv-1',
        version_number: 4,
        source_kind: 'training',
        metadata: {},
      }],
      builds: [{
        model_build_id: 'build-1',
        source_model_version_id: 'mv-1',
        build_format: 'openvino-ir',
        runtime_backend: 'openvino',
        runtime_precision: 'fp16',
        metadata: {},
      }],
    } as never)
    vi.mocked(createTaskDeployment).mockResolvedValue({
      ...sampleDeployment,
      deployment_instance_id: 'deploy-new',
    })
    vi.mocked(runTaskDeploymentStatusAction).mockImplementation(async (_task, id, _mode, action) => {
      if (action === 'start' && id === 'deploy-new') throw new Error('GPU memory insufficient')
      return runningStatus
    })

    const wrapper = mount(DeploymentOperationsPage, {
      global: { plugins: [pinia, i18n, router] },
    })
    await flushPromises()

    await wrapper.get('[data-deployment-action="create-wizard"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('新建部署')

    await wrapper.get('[data-deployment-action="browse-source-picker"]').trigger('click')
    await flushPromises()
    await wrapper.get('.deployment-source-action').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find(b => b.text().includes('下一步'))!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('目标检测')
    expect(wrapper.text()).toContain('执行')

    const deviceSelect = wrapper.find('.deployment-create-grid .ui-select')
    await deviceSelect.find('.ui-select__button').trigger('click')
    await nextTick()
    const cpuOption = deviceSelect.findAll('.ui-select__option').find(opt => opt.text().includes('CPU'))!
    await cpuOption.trigger('click')
    await flushPromises()

    const instanceInput = wrapper.findAll('input[type="number"]')[0]!
    await instanceInput.setValue('0')
    await instanceInput.trigger('blur')
    expect((instanceInput.element as HTMLInputElement).value).toBe('0')
    expect(wrapper.text()).toContain('实例数必须是 1 到 64 的整数。')
    expect(wrapper.text()).toContain('请修正 1 项参数')
    const checkConfigBtn = wrapper.findAll('button').find(b => b.text().includes('检查配置'))!
    expect((checkConfigBtn.element as HTMLButtonElement).disabled).toBe(true)
    await instanceInput.setValue('2')
    expect((checkConfigBtn.element as HTMLButtonElement).disabled).toBe(false)
    expect(wrapper.text()).toContain('本机共 16 个物理核心，2 个实例；预计每实例使用 8 个线程，实际以启动后为准。')

    await wrapper.get('input[type="checkbox"]').setValue(true)
    await wrapper.findAll('button').find(b => b.text().includes('检查配置'))!.trigger('click')
    await nextTick()
    expect(wrapper.text()).toContain('检查结果')
    expect(wrapper.text()).toContain('输入输出契约完整')
    expect(wrapper.text()).toContain('部署配置摘要')

    await wrapper.get('form.deployment-create-panel').trigger('submit')
    await flushPromises()

    expect(createTaskDeployment).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('部署实例已创建（deploy-new），但启动失败：GPU memory insufficient')
  })

  it('blocks reset when requests are busy and shows confirmation impact when idle', async () => {
    vi.mocked(runTaskDeploymentHealthAction).mockResolvedValue({
      ...idleHealth,
      instances: [
        { instance_id: 'inst-0', healthy: true, warmed: true, busy: true, inference_count: 1, error_count: 0 },
        { instance_id: 'inst-1', healthy: true, warmed: true, busy: false, inference_count: 1, error_count: 0 },
      ],
    })
    const wrapper = mount(DeploymentOperationsPage, {
      global: { plugins: [pinia, i18n, router] },
    })
    await flushPromises()

    // Check stop modal first via row ResourceMenu
    wrapper.get('[data-deployment-id="deploy-1"]').findComponent(ResourceMenu).vm.$emit('action', 'stop')
    await flushPromises()
    expect(wrapper.text()).toContain('连接器检测服务')
    expect(wrapper.text()).toContain('产线主流程')
    expect(wrapper.text()).toContain('确认停止')
    await wrapper.get('[data-confirm-cancel]').trigger('click')
    await nextTick()

    // Open status drawer -> diagnostics -> reset (blocked because busy === 1)
    await wrapper.get('[data-deployment-id="deploy-1"] [data-deployment-action="status-details"]').trigger('click')
    await flushPromises()
    const diagTab = Array.from(document.body.querySelectorAll('.local-tabs__tab')).find(el => el.textContent?.trim() === '诊断') as HTMLElement
    diagTab.click()
    await nextTick()
    const resetBtn = Array.from(document.body.querySelectorAll('button')).find(el => el.textContent?.includes('重置')) as HTMLElement
    resetBtn.click()
    await flushPromises()
    expect(wrapper.text()).toContain('暂时无法重置实例')
    expect(wrapper.text()).toContain('重新检查')
  })

  it('renders 5 tabs in DeploymentStatusDrawer including requested vs effective config and references', async () => {
    const wrapper = mount(DeploymentStatusDrawer, {
      props: {
        open: true,
        deployment: sampleDeployment,
        status: runningStatus,
        health: idleHealth,
        cpuResourceSummary: { physicalCoreCount: 16, deploymentThreadCapacity: 16, threadsPerInstance: 8 },
        events: [],
        eventsLoading: false,
        displayName: '连接器检测服务',
        summaryLabel: '运行正常',
        summaryTone: 'success',
        versionLabelsById: {
          'mv-1': { modelName: 'YOLO11-s', versionLabel: 'v2' },
        },
        canWarmup: false,
        canReset: true,
      },
      global: {
        plugins: [i18n, router],
        stubs: { Teleport: true },
      },
    })
    await flushPromises()

    const drawerTabs = wrapper.findAll('.local-tabs__tab')
    expect(drawerTabs.map(el => el.text())).toEqual(['概览', '运行配置', '接口', '诊断', '引用'])
    expect(wrapper.text()).toContain('连接器检测服务')
    expect(wrapper.text()).toContain('YOLO11-s')
    expect(wrapper.text()).toContain('v2')
    expect(wrapper.text()).not.toContain('mv-1')
    expect(wrapper.text()).toContain('实例信息')
    expect(wrapper.text()).toContain('运行统计')

    await drawerTabs[1]!.trigger('click')
    const configTable = wrapper.get('.drawer-table-card')
    expect(configTable.text()).toContain('实例数')
    expect(configTable.text()).toContain('保持设备活跃')
    expect(configTable.text()).toContain('OpenVINO 性能策略')
    expect(configTable.text()).toContain('推理线程数')
    expect(configTable.text()).not.toContain('inference_num_threads')
    expect(configTable.text()).not.toContain('instance_count')
    expect(configTable.text()).not.toContain('keep_warm_enabled')
    expect(configTable.text()).toContain('16')
    expect(configTable.text()).toContain('8')

    await drawerTabs[2]!.trigger('click')
    expect(wrapper.text()).toContain('/api/v1/models/detection/deployment-instances/deploy-1/infer')

    await drawerTabs[4]!.trigger('click')
    await flushPromises()
    expect(listDeploymentReferences).toHaveBeenCalledWith('project-1', 'deploy-1')
    expect(wrapper.text()).toContain('产线主流程')
  })

  it('separates task status from missing zip_state in DeploymentTransferRecordsTab', async () => {
    const missingExport: DeploymentTransfer = {
      operation_id: 'exp-1',
      direction: 'export',
      state: 'completed',
      zip_state: 'missing',
      deployment_id: 'deploy-1',
      display_name: '连接器检测.zip',
      total_bytes: 1024 * 1024 * 12,
      updated_at: '2026-11-26T00:00:00Z',
    }
    const wrapper = mount(DeploymentTransferRecordsTab, {
      props: {
        projectId: 'project-1',
        direction: 'export',
        items: [missingExport],
        canWrite: true,
      },
      global: { plugins: [i18n] },
    })

    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).toContain('无有效文件')
    expect(wrapper.find('[data-transfer-action="download"]').exists()).toBe(false)
    expect(wrapper.get('[data-transfer-action="reexport"]').text()).toContain('重新导出')

    await wrapper.findAll('.transfer-action-link').find(b => b.text().includes('详情'))!.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('基本信息')
    expect(document.body.textContent).toContain('文件内容')
  })

  it('renders row ResourceMenu actions and shows delete dependency blocker linking to references drawer tab', async () => {
    const wrapper = mount(DeploymentOperationsPage, {
      global: { plugins: [pinia, i18n, router] },
    })
    await flushPromises()

    const menu = wrapper.get('[data-deployment-id="deploy-1"]').findComponent(ResourceMenu)
    const menuIds = ((menu.props('items') ?? []) as Array<{ id: string }>).map(item => item.id)
    expect(menuIds).toEqual(expect.arrayContaining(['stop', 'inference', 'warmup', 'reset', 'export', 'delete']))

    menu.vm.$emit('action', 'delete')
    await flushPromises()
    expect(wrapper.text()).toContain('暂时无法删除部署')
    expect(wrapper.text()).toContain('产线主流程')

    const viewRefsButton = wrapper.findAll('button').find(b => b.text().includes('查看引用'))!
    expect(viewRefsButton).toBeTruthy()
    await viewRefsButton.trigger('click')
    await flushPromises()

    const activeDrawerTab = document.body.querySelector('.local-tabs__tab.is-active')
    expect(activeDrawerTab?.textContent?.trim()).toBe('引用')
    expect(document.body.textContent).toContain('产线主流程')
  })

  it('shows automatic default device label in Step 3 when deviceName is empty', async () => {
    vi.mocked(listDeploymentSourceModels).mockResolvedValue([{
      model_id: 'model-onnx',
      project_id: 'project-1',
      scope_kind: 'project',
      model_name: 'YOLO11-s',
      model_type: 'yolo11',
      model_scale: 's',
      task_type: 'detection',
      version_count: 1,
      build_count: 1,
      created_at: '',
      updated_at: '',
      metadata: {},
    } as never])
    vi.mocked(getDeploymentSourceModelDetail).mockResolvedValue({
      model_id: 'model-onnx',
      project_id: 'project-1',
      scope_kind: 'project',
      model_name: 'YOLO11-s',
      model_type: 'yolo11',
      model_scale: 's',
      task_type: 'detection',
      versions: [{
        model_version_id: 'mv-2',
        version_number: 2,
        source_kind: 'training',
        metadata: {},
      }],
      builds: [{
        model_build_id: 'build-onnx',
        source_model_version_id: 'mv-2',
        build_format: 'onnx',
        runtime_backend: 'onnxruntime',
        runtime_precision: 'fp32',
        metadata: {},
      }],
    } as never)

    const wrapper = mount(DeploymentOperationsPage, {
      global: { plugins: [pinia, i18n, router] },
    })
    await flushPromises()

    await wrapper.get('[data-deployment-action="create-wizard"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-deployment-action="browse-source-picker"]').trigger('click')
    await flushPromises()
    await wrapper.get('.deployment-source-action').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find(b => b.text().includes('下一步'))!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find(b => b.text().includes('检查配置'))!.trigger('click')
    await nextTick()

    const checksCard = wrapper.get('.wizard-checks-card')
    expect(checksCard.text()).toContain('目标设备可访问')
    expect(checksCard.text()).toContain('自动选择（默认）')
    const reviewStrip = wrapper.get('.wizard-summary-strip--review')
    expect(reviewStrip.text()).toContain('自动选择（默认）')
    expect(reviewStrip.text()).not.toContain('—')
  })

  it('opens delete blocker ConfirmDialog on running deployment without cross-tab inline error', async () => {
    vi.mocked(listDeploymentReferences).mockResolvedValue({ items: [], total: 0 })

    const wrapper = mount(DeploymentOperationsPage, {
      global: { plugins: [pinia, i18n, router] },
    })
    await flushPromises()

    const menu = wrapper.get('[data-deployment-id="deploy-1"]').findComponent(ResourceMenu)
    menu.vm.$emit('action', 'delete')
    await flushPromises()

    expect(wrapper.text()).toContain('暂时无法删除部署')
    expect(wrapper.text()).toContain('实例尚未完全停止，请先停止服务后再删除。')
    expect(wrapper.find('.inline-error').exists()).toBe(false)

    await wrapper.get('[data-confirm-cancel]').trigger('click')
    await nextTick()
    const importTab = wrapper.findAll('.deployment-ops-navigation .local-tabs__tab').find(t => t.text() === '导入记录')!
    await importTab.trigger('click')
    await flushPromises()
    expect(wrapper.find('.inline-error').exists()).toBe(false)
  })

  it('provides matching keys across all 4 locales in deploymentWorkspaceMessages', () => {
    function collectKeys(obj: Record<string, unknown>, prefix = ''): string[] {
      return Object.entries(obj).flatMap(([key, value]) => {
        const next = prefix ? `${prefix}.${key}` : key
        return typeof value === 'object' && value !== null
          ? collectKeys(value as Record<string, unknown>, next)
          : [next]
      })
    }
    const baseKeys = collectKeys(deploymentWorkspaceMessages['zh-CN'] as Record<string, unknown>).sort()
    for (const locale of ['en-US', 'ja-JP', 'ko-KR'] as const) {
      expect(collectKeys(deploymentWorkspaceMessages[locale] as Record<string, unknown>).sort()).toEqual(baseKeys)
    }
  })

  it('renders DeploymentCapabilitiesDrawer host OS, backend-only icons, availability, and structured properties', async () => {
    vi.mocked(getDeploymentRuntimeCapabilities).mockResolvedValue({
      runtime_backend: 'openvino',
      device_name: 'CPU',
      available: true,
      hardware: { cpu_physical_core_count: 16 },
      supported_backend_fields: ['performance_hint', 'inference_num_threads'],
      read_only_properties: {
        FULL_DEVICE_NAME: 'Intel Core Ultra 9',
        CPU_DENORMALS_OPTIMIZATION: false,
        RANGE_FOR_STREAMS: [1, 8],
        OPTIMIZATION_CAPABILITIES: ['FP32', 'FP16', 'INT8'],
      },
      default_runtime_configuration: sampleDeployment.runtime_configuration,
      warnings: [],
    })

    const wrapper = mount(DeploymentCapabilitiesDrawer, {
      props: {
        open: true,
        devices: {
          host: {
            system: 'windows',
            os_name: 'Windows 11 Pro 24H2',
            os_platform: 'win32',
            hostname: 'vision-edge-01',
          },
          cpu: { physical_cores: 16, logical_cores: 32 },
          openvino: { installed: true, supports_cpu: true, available_devices: ['CPU'] },
          onnxruntime: { installed: true },
        },
      },
      global: {
        plugins: [i18n],
        stubs: { Teleport: true },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Windows 11 Pro 24H2')
    expect(wrapper.text()).toContain('Windows x64')
    expect(wrapper.text()).not.toContain('Win32')
    expect(wrapper.text()).not.toContain('win32')

    const tableRows = wrapper.findAll('.capabilities-table-wrap tbody tr')
    expect(tableRows.length).toBeGreaterThanOrEqual(2)
    for (const row of tableRows) {
      const backendTd = row.get('.capabilities-backend-td')
      const badge = backendTd.get('.deployment-runtime-badge[role="img"]')
      expect(badge.attributes('title')).toBeTruthy()
      expect(badge.text()).toBe('')
      expect(backendTd.text()).toBe('')
    }

    const openvinoCpuRow = tableRows.find(r => r.get('.deployment-runtime-badge').attributes('title') === 'OpenVINO' && r.text().includes('CPU'))!
    expect(openvinoCpuRow).toBeTruthy()
    expect(openvinoCpuRow.find('.capability-status.is-available').text()).toContain('可用')

    const propTable = wrapper.get('.capabilities-prop-table')
    expect(propTable.text()).toContain('设备型号')
    expect(propTable.text()).toContain('Intel Core Ultra 9')
    expect(propTable.text()).toContain('非正规数优化')
    expect(propTable.text()).toContain('不支持')
    expect(propTable.text()).toContain('Streams 范围')
    expect(propTable.text()).toContain('1 ~ 8')
    expect(propTable.text()).toContain('支持精度与算子能力')
    expect(propTable.findAll('.capabilities-chips li').map(li => li.text())).toEqual(['FP32', 'FP16', 'INT8'])
  })

  it('unwraps allocated_runtime_configuration and renders contract outputs and running reference state in DeploymentStatusDrawer', async () => {
    const allocatedHealth: TaskDeploymentRuntimeHealth = {
      ...idleHealth,
      effective_runtime_configuration: {
        allocated_runtime_configuration: {
          execution: {
            instance_count: 2,
            isolation_level: 'session',
            overflow_policy: 'reject',
            performance_goal: 'latency',
          },
          lifecycle: {
            warmup_dummy_inference_count: null,
            warmup_dummy_image_size: null,
            keep_warm_enabled: true,
            keep_warm_interval_seconds: 0.25,
          },
          backend_options: {
            kind: 'openvino-cpu',
            performance_hint: 'throughput',
            inference_num_threads: 6,
            num_streams: 2,
            scheduling_core_type: 'auto',
            enable_hyper_threading: 'auto',
            enable_cpu_pinning: 'auto',
          },
        },
        compile_properties: {
          PERFORMANCE_HINT: 'PerformanceMode.THROUGHPUT',
          INFERENCE_NUM_THREADS: 6,
        },
      },
    }

    const wrapper = mount(DeploymentStatusDrawer, {
      props: {
        open: true,
        deployment: sampleDeployment,
        status: runningStatus,
        health: allocatedHealth,
        cpuResourceSummary: { physicalCoreCount: 16, deploymentThreadCapacity: 12, threadsPerInstance: 6 },
        events: [],
        eventsLoading: false,
        displayName: '连接器检测服务',
        summaryLabel: '运行正常',
        summaryTone: 'success',
        versionLabelsById: {
          'mv-1': { modelName: 'YOLO11-s', versionLabel: 'v2' },
        },
        canWarmup: false,
        canReset: true,
      },
      global: {
        plugins: [i18n, router],
        stubs: { Teleport: true },
      },
    })
    await flushPromises()

    const drawerTabs = wrapper.findAll('.local-tabs__tab')

    await drawerTabs[1]!.trigger('click')
    const configRows = wrapper.findAll('.drawer-table-card tbody tr')
    const threadsRow = configRows.find(r => r.text().includes('推理线程数'))!
    expect(threadsRow.classes()).toContain('is-config-changed')
    expect(threadsRow.findAll('td')[1]!.text()).toBe('16')
    expect(threadsRow.findAll('td')[2]!.text()).toBe('6')
    const hintRow = configRows.find(r => r.text().includes('OpenVINO 性能策略'))!
    expect(hintRow.classes()).toContain('is-config-changed')
    expect(hintRow.findAll('td')[2]!.text()).toBe('最大吞吐量')
    const streamsRow = configRows.find(r => r.text().includes('Streams 数量'))!
    expect(streamsRow.findAll('td')[2]!.text()).toBe('2')

    await drawerTabs[2]!.trigger('click')
    expect(wrapper.text()).toContain('输出内容')
    expect(wrapper.text()).toContain('boxes（目标框）、classes（类别）、scores（置信度）')

    await drawerTabs[4]!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Runtime 运行中')
  })

  it('opens Step 1 import wizard dialog from DeploymentOperationsPage import-wizard button', async () => {
    const wrapper = mount(DeploymentOperationsPage, {
      global: { plugins: [pinia, i18n, router] },
    })
    await flushPromises()

    await wrapper.get('[data-deployment-action="import-wizard"]').trigger('click')
    await flushPromises()

    const bodyText = document.body.textContent ?? ''
    expect(bodyText).toContain('导入部署实例')
    expect(bodyText).toContain('选择部署实例包')
    expect(bodyText).toContain('未运行检查')
  })
})
