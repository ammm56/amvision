import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { i18n, setI18nLocale } from '@/platform/i18n'
import ModelOperationsPage from '@/modules/models/pages/ModelOperationsPage.vue'
import ModelConversionSourcePickerDialog from '@/modules/models/components/ModelConversionSourcePickerDialog.vue'
import ModelConversionForm from '@/modules/models/components/ModelConversionForm.vue'
import TrainingTaskList from '@/modules/models/components/TrainingTaskList.vue'
import ModelTrainingForm from '@/modules/models/components/ModelTrainingForm.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import {
  createModelConversionTask, createModelTrainingTask, getModelConversionTaskDetail, getModelTrainingTaskDetail, listDeploymentSourceModels, listPlatformBaseModels, listTrainingParameterSchemas,
  listModelTrainingTasks, listModelConversionTasks, type DeploymentSourceModelSummary,
  listProjectModelCatalog, previewModelConversion,
} from '@/modules/models/services/model.service'
import { getDatasetExportDetail, listProjectDatasetExports, type DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import { listDetectionEvaluations } from '@/modules/models/services/model-evaluation.service'
import { conversionTask, trainingTask } from './task_lifecycle_support'

vi.mock('@/modules/models/services/model.service', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/modules/models/services/model.service')>(),
  createModelConversionTask: vi.fn(), previewModelConversion: vi.fn(), listDeploymentSourceModels: vi.fn(), listPlatformBaseModels: vi.fn(),
  listTrainingParameterSchemas: vi.fn(), listModelTrainingTasks: vi.fn(), listModelConversionTasks: vi.fn(),
  listProjectModelCatalog: vi.fn(), getModelTrainingTaskDetail: vi.fn(), createModelTrainingTask: vi.fn(), getModelConversionTaskDetail: vi.fn(),
}))
vi.mock('@/modules/datasets/services/dataset.service', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/modules/datasets/services/dataset.service')>(), listProjectDatasetExports: vi.fn(), getDatasetExportDetail: vi.fn(),
}))
vi.mock('@/modules/models/services/model-evaluation.service', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/modules/models/services/model-evaluation.service')>(),
  listDetectionEvaluations: vi.fn(),
}))
vi.mock('@/modules/models/training-parameter-support', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/modules/models/training-parameter-support')>(),
  getDefaultTrainingModelParameterValues: () => ({ learning_rate: '0.001' }),
  getModelLayerTrainingFields: () => [],
  validateTrainingModelLayerValues: () => null,
}))
enableAutoUnmount(afterEach)

const sourceModel: DeploymentSourceModelSummary = {
  model_id: 'model-trained', project_id: 'project-1', scope_kind: 'project', model_name: 'PCB classifier',
  model_type: 'yolo11', task_type: 'classification', model_scale: 's', metadata: { display_name: '托盘分类' }, version_count: 1, build_count: 0,
  available_versions: [{
    model_version_id: 'version-trained', source_kind: 'training-output', file_ids: ['checkpoint', 'labels'],
    metadata: { category_names: ['ok', 'ng', 'rework'] }, checkpoint_file_id: 'checkpoint', checkpoint_storage_uri: 'best.pt',
    labels_file_id: 'labels', labels_storage_uri: 'labels.txt',
  }],
}

function setupPage() {
  const pinia = createPinia()
  const projects = useProjectStore(pinia)
  projects.projects = [{ project_id: 'project-1', display_name: 'Project 1', description: '' }]
  projects.selectedProjectId = 'project-1'
  const session = useSessionStore(pinia)
  session.currentUser = {
    principal_id: 'user-1', principal_type: 'user', project_ids: ['project-1', 'project-2'], scopes: ['models:read', 'tasks:read', 'tasks:write'],
    username: 'tester', display_name: 'Tester', auth_provider_kind: 'local', auth_credential_kind: 'session',
  }
  vi.spyOn(session, 'ensureDeviceBootstrap').mockResolvedValue(null)
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }] })
  const mountPage = () => ({ projects, router, wrapper: mount(ModelOperationsPage, {
    global: { plugins: [pinia, i18n, router], stubs: {
      ResourceCleanupPanel: true, ImportedModelAssets: true, ModelTrainingForm: true, TrainingTaskList: true,
      ConversionTaskList: true, TrainingDatasetExportPickerDialog: true, RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
    } },
  }) })
  return { router, mountPage, session }
}

function page() { return setupPage().mountPage() }

beforeEach(() => {
  vi.clearAllMocks()
  setI18nLocale('zh-CN')
  vi.mocked(listPlatformBaseModels).mockResolvedValue([])
  vi.mocked(listDeploymentSourceModels).mockImplementation(async (projectId, taskType) => projectId === 'project-1' && taskType === 'classification' ? [sourceModel] : [])
  vi.mocked(listTrainingParameterSchemas).mockResolvedValue({ protocol_version: 1, items: [] })
  vi.mocked(listProjectDatasetExports).mockResolvedValue([])
  vi.mocked(listModelTrainingTasks).mockResolvedValue([])
  vi.mocked(listModelConversionTasks).mockResolvedValue([])
  vi.mocked(listDetectionEvaluations).mockResolvedValue([])
  vi.mocked(listProjectModelCatalog).mockResolvedValue({ items: [], total: 0 })
  vi.mocked(createModelConversionTask).mockResolvedValue({ task_id: 'conversion-1' } as never)
  vi.mocked(previewModelConversion).mockResolvedValue({ task_type: 'classification', source_model_version_id: 'version-trained', target_formats: ['openvino-ir'], steps: [] })
})

describe('ModelOperationsPage copied training draft', () => {
  const baseModel = { ...sourceModel, model_id: 'model-base', model_scale: 's', scope_kind: 'platform-base' }
  const source = {
    ...trainingTask('old-training'), state: 'cancelled', model_scale: 's',
    task_spec: {
      output_model_name: 'one-tray-series', warm_start_model_version_id: 'version-trained', recipe_id: 'default',
      max_epochs: 31, batch_size: 4, input_size: { width: 224, height: 224 }, evaluation_interval: 2,
      dataset_export_id: 'old-export', dataset_export_manifest_key: 'datasets/old-export/manifest.json',
      extra_options: { batch_mode: 'fixed', amp_mode: 'disabled', requested_device: 'cpu', disable_augmentation: true, learning_rate: 0.003 },
    },
  }
  const dataset = {
    project_id: 'project-1', task_type: 'classification', status: 'completed', metadata: {}, dataset_export_id: 'old-export',
    manifest_object_key: 'datasets/old-export/manifest.json', format_id: 'imagenet',
  } as DatasetExportSummary

  async function openCopy() {
    vi.mocked(listPlatformBaseModels).mockResolvedValue([baseModel])
    vi.mocked(listTrainingParameterSchemas).mockResolvedValue({ protocol_version: 1, items: [{
      task_type: 'classification', model_type: 'yolo11', schema_name: 'classification-yolo11',
      parameter_schema: {}, default_parameters: {}, numeric_fields: [],
      capabilities: { postprocess_mode: 'classification', supports_nms_threshold: false, distribution_loss_name: null,
        augmentation_families: [], best_metric_name: 'accuracy', best_metric_direction: 'maximize' },
    }] })
    const app = setupPage()
    await app.router.push('/models?tab=training&task=classification&trainingFrom=old-training')
    const mounted = app.mountPage()
    await flushPromises()
    return mounted
  }

  it('restores exact sources and settings, then clears the copy when the draft is cancelled', async () => {
    vi.mocked(getModelTrainingTaskDetail).mockResolvedValue(source)
    vi.mocked(getDatasetExportDetail).mockResolvedValue(dataset)
    const { wrapper, router } = await openCopy()
    const form = wrapper.getComponent(ModelTrainingForm)
    expect(getDatasetExportDetail).toHaveBeenCalledWith('old-export')
    expect(form.props()).toMatchObject({
      outputModelName: 'one-tray-series', warmStartModelVersionId: 'version-trained',
      trainingSelectedModelSummary: baseModel, selectedTrainingDatasetExport: dataset,
      maxEpochs: 31, batchMode: 'fixed', batchSize: 4, inputWidth: 224, inputHeight: 224,
      evaluationInterval: 2, ampMode: 'disabled', trainingDevice: 'cpu', trainingAugmentationEnabled: false,
      trainingModelParameterValues: { learning_rate: '0.003' },
    })
    form.vm.$emit('cancel')
    await flushPromises()
    expect(router.currentRoute.value.query.trainingFrom).toBeUndefined()
    await wrapper.findAll('button').find(item => item.text() === '创建训练')!.trigger('click')
    expect(wrapper.getComponent(ModelTrainingForm).props()).toMatchObject({
      maxEpochs: 100, evaluationInterval: 5, warmStartModelVersionId: '', selectedTrainingDatasetExport: null,
    })
    expect(createModelTrainingTask).not.toHaveBeenCalled()
  })

  it('requires a new data selection after cleanup and rejects original tasks from another project', async () => {
    vi.mocked(getModelTrainingTaskDetail).mockResolvedValueOnce(source).mockResolvedValueOnce({ ...source, project_id: 'project-2' })
    vi.mocked(getDatasetExportDetail).mockResolvedValue({ ...dataset, metadata: { files_cleaned_at: '2026-11-19' } })
    const { wrapper } = await openCopy()
    expect(wrapper.getComponent(ModelTrainingForm).props('selectedTrainingDatasetExport')).toBeNull()
    expect(wrapper.text()).toContain('原数据集导出已不可用')
    vi.mocked(getDatasetExportDetail).mockClear()
    const other = await openCopy()
    expect(other.wrapper.findComponent(ModelTrainingForm).exists()).toBe(false)
    expect(other.wrapper.text()).toContain('无法在当前项目读取原训练配置')
    expect(getDatasetExportDetail).not.toHaveBeenCalled()
  })
})

describe('ModelOperationsPage conversion flow', () => {
  it('copies the original source and supported conversion settings into a draft', async () => {
    const app = setupPage()
    app.session.currentUser!.scopes.push('models:write')
    vi.mocked(getModelConversionTaskDetail).mockResolvedValue({ ...conversionTask('past'), state: 'cancelled',
      target_formats: ['openvino-ir'], requested_target_formats: ['openvino-ir'], produced_formats: [],
      source_model_version_id: 'version-trained', runtime_profile_id: 'runtime-local',
      task_spec: { extra_options: { openvino_ir_precision: 'fp16', onnx_opset_version: 19 } },
    })
    await app.router.push('/models?tab=conversion&task=classification&conversionFrom=past')
    const { wrapper } = app.mountPage()
    await flushPromises()
    const form = wrapper.getComponent(ModelConversionForm)
    expect(form.props()).toMatchObject({ conversionSourceModelVersionId: 'version-trained', conversionTarget: 'openvino-ir-fp16',
      conversionRuntimeProfileId: 'runtime-local', onnxOpsetVersion: 19 })
    expect(createModelConversionTask).not.toHaveBeenCalled()
    form.vm.$emit('cancel')
    await flushPromises()
    expect(app.router.currentRoute.value.query.conversionFrom).toBeUndefined()
    expect(form.props()).toMatchObject({ conversionSourceModelVersionId: '', conversionTarget: 'onnx', conversionRuntimeProfileId: '' })
  })

  it('opens editable INT8 inputs when a failed draft has incomplete calibration settings', async () => {
    const app = setupPage()
    app.session.currentUser!.scopes.push('models:write')
    vi.mocked(getModelConversionTaskDetail).mockResolvedValue({
      ...conversionTask('past'), state: 'failed',
      target_formats: ['tensorrt-engine'], requested_target_formats: ['tensorrt-engine'], produced_formats: [],
      source_model_version_id: 'version-trained',
      task_spec: { extra_options: { tensorrt_engine_precision: 'int8' } },
    })
    await app.router.push('/models?tab=conversion&task=classification&conversionFrom=past')
    const { wrapper } = app.mountPage()
    await flushPromises()
    expect(wrapper.getComponent(ModelConversionForm).props('tensorRtInt8')).toMatchObject({
      workspace_gib: 4,
      int8_calibration: { dataset_export_id: '', sample_count: 1 },
      int8_validation: { dataset_export_id: '', sample_count: 1 },
    })
    expect(createModelConversionTask).not.toHaveBeenCalled()
  })

  it('loads project evaluations and keeps training actions out of the evaluation tab', async () => {
    const { wrapper } = page()
    await flushPromises()
    await wrapper.findAll('[role="tab"]').find(item => item.text().includes('评估'))!.trigger('click')
    await flushPromises()
    expect(listDetectionEvaluations).toHaveBeenCalledWith('project-1', expect.any(AbortSignal))
    expect(wrapper.text()).toContain('暂无目标检测评估任务')
    expect(wrapper.findAll('button').some(button => button.isVisible() && button.text().includes('创建训练'))).toBe(false)
  })

  it('keeps training inputs available when task history fails to load', async () => {
    vi.mocked(listModelTrainingTasks).mockRejectedValue(new Error('task history unavailable'))
    vi.mocked(listProjectDatasetExports).mockResolvedValue([{ dataset_export_id: 'export-1', task_type: 'detection', status: 'completed', metadata: {} }] as never)
    const { wrapper } = page()
    await flushPromises()
    await wrapper.findAll('button').find(item => item.text().includes('创建训练'))!.trigger('click')
    expect(wrapper.findComponent(ModelTrainingForm).props('trainingDatasetExportsCount')).toBe(1)
  })

  it('does not relabel old training records while a different task type is loading', async () => {
    vi.mocked(listModelTrainingTasks).mockImplementation((taskType) => taskType === 'detection'
      ? Promise.resolve([{ task_id: 'detection-task', state: 'succeeded', progress: {} }] as never)
      : new Promise(() => {}))
    vi.mocked(listProjectDatasetExports).mockImplementation((_projectId, taskType) => taskType === 'detection'
      ? Promise.resolve([{ dataset_export_id: 'export-old', metadata: {} }] as never)
      : new Promise(() => {}))
    const { wrapper } = page()
    await flushPromises()
    const tab = wrapper.findAll('[role="tab"]').find(item => item.text().includes('训练任务'))
    expect(tab).toBeDefined()
    await tab!.trigger('click')
    const list = wrapper.findComponent(TrainingTaskList)
    expect(list.props('trainingTasks')).toHaveLength(1)
    list.vm.$emit('change-task-type', 'classification')
    await wrapper.vm.$nextTick()
    expect(list.props('selectedTaskType')).toBe('classification')
    expect(list.props('trainingTasks')).toHaveLength(0)
    expect(list.props('loading')).toBe(true)
    await wrapper.findAll('button').find(item => item.text().includes('创建训练'))!.trigger('click')
    expect(wrapper.findComponent(ModelTrainingForm).props('trainingDatasetExportsCount')).toBe(0)
  })

  it('submits the real trained version without a platform catalog entry, then clears it on project change', async () => {
    const { wrapper, projects } = page()
    await flushPromises()
    wrapper.findComponent(ModelConversionForm).vm.$emit('open-source-picker')
    await flushPromises()
    wrapper.findComponent(ModelConversionSourcePickerDialog).vm.$emit('change-task-type', 'classification')
    await flushPromises()
    const picker = wrapper.findComponent(ModelConversionSourcePickerDialog)
    expect(picker.text()).toContain('托盘分类')
    expect(picker.text()).toContain('3 个类别')
    await picker.find('.conversion-source-version button').trigger('click')
    await flushPromises()
    const form = wrapper.findComponent(ModelConversionForm)
    expect(form.text()).toContain('托盘分类')
    expect(form.text()).not.toContain('尚未选择基础模型')
    expect(form.find('button[type="submit"]').attributes('disabled')).toBeUndefined()
    await form.find('form').trigger('submit')
    await form.get('input[aria-label="CoreML"]').setValue()
    const configuration = form.get('.conversion-target-requirements')
    expect(configuration.get<HTMLInputElement>('input[value="ML Program"]').element.readOnly).toBe(true)
    expect(configuration.text()).toContain('没有可用于转换和校验的兼容环境')
    await configuration.findAll('button').find(button => button.text() === '查看要求')!.trigger('click')
    expect(configuration.text()).toContain('Apple 校验环境')
    expect(form.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    await form.get('form').trigger('submit')
    expect(form.find('.conversion-parameters').exists()).toBe(false)
    expect(previewModelConversion).not.toHaveBeenCalled()
    await form.get('input[aria-label="ARM NPU"]').setValue()
    expect(form.get('.conversion-target-requirements').text()).toContain('厂商适配器')
    expect(form.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    const openvino = form.findAll('label.conversion-target').find(item => item.text().includes('OpenVINO'))
    expect(openvino).toBeDefined()
    await openvino!.find('input').setValue()
    await form.find('form').trigger('submit')
    form.findComponent(SelectField).vm.$emit('update:modelValue', 'openvino-ir-fp16')
    await form.vm.$nextTick()
    await form.find('form').trigger('submit')
    expect(createModelConversionTask).not.toHaveBeenCalled()
    await flushPromises()
    expect(previewModelConversion).toHaveBeenCalledWith(expect.objectContaining({ projectId: 'project-1', sourceModelVersionId: 'version-trained', target: 'openvino-ir-fp16' }), expect.any(AbortSignal))
    await form.find('form').trigger('submit')
    await flushPromises()
    expect(createModelConversionTask).toHaveBeenCalledWith(expect.objectContaining({
      projectId: 'project-1', modelType: 'yolo11', sourceModelVersionId: 'version-trained', taskType: 'classification', target: 'openvino-ir-fp16',
    }), expect.stringMatching(/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/))
    projects.selectedProjectId = 'project-2'
    await flushPromises()
    expect(form.find('button[type="submit"]').attributes('disabled')).toBeDefined()
    expect(form.text()).not.toContain('conversion-1')
    expect(listDeploymentSourceModels).toHaveBeenLastCalledWith('project-2', 'classification')
  })

  it('does not let an outdated preflight result authorize submission and permits retry', async () => {
    let finishFirst!: (value: Awaited<ReturnType<typeof previewModelConversion>>) => void
    vi.mocked(previewModelConversion).mockImplementationOnce(() => new Promise(resolve => { finishFirst = resolve }))
      .mockRejectedValueOnce(new Error('来源文件不可用'))
    const { wrapper } = page()
    await flushPromises()
    wrapper.findComponent(ModelConversionForm).vm.$emit('open-source-picker')
    await flushPromises()
    wrapper.findComponent(ModelConversionSourcePickerDialog).vm.$emit('change-task-type', 'classification')
    await flushPromises()
    await wrapper.findComponent(ModelConversionSourcePickerDialog).find('.conversion-source-version button').trigger('click')
    const form = wrapper.findComponent(ModelConversionForm)
    for (let i = 0; i < 3; i++) await form.find('form').trigger('submit')
    expect(form.find('button[type="submit"]').attributes('disabled')).toBeDefined()
    await form.findAll('button').find(button => button.text().includes('上一步'))!.trigger('click')
    await form.find('form').trigger('submit')
    await flushPromises()
    finishFirst({ task_type: 'classification', source_model_version_id: 'version-trained', target_formats: ['onnx'], steps: [] })
    await flushPromises()
    expect(form.text()).toContain('来源文件不可用')
    expect(form.find('button[type="submit"]').attributes('disabled')).toBeDefined()
    expect(createModelConversionTask).not.toHaveBeenCalled()
    await form.findAll('button').find(button => button.text().includes('重新检查'))!.trigger('click')
    await flushPromises()
    expect(form.find('button[type="submit"]').attributes('disabled')).toBeUndefined()
    await form.findAll('button').find(button => button.text() === '取消')!.trigger('click')
    expect(form.text()).toContain('转换来源模型')
    expect(form.text()).not.toContain('检查结果')
  })

  it('does not submit a checkpoint-only reference or stale source after a task type change', async () => {
    const warmStart = { ...sourceModel, project_id: null, scope_kind: 'platform-base', model_id: 'pretrained', available_versions: [{
      ...sourceModel.available_versions[0], metadata: {}, labels_file_id: null, labels_storage_uri: null,
    }] }
    vi.mocked(listDeploymentSourceModels).mockResolvedValue([warmStart])
    const { wrapper } = page()
    await flushPromises()
    wrapper.findComponent(ModelConversionForm).vm.$emit('open-source-picker')
    await flushPromises()
    expect(wrapper.findComponent(ModelConversionSourcePickerDialog).text()).toContain('暂无可转换')
    wrapper.findComponent(ModelConversionForm).vm.$emit('submit')
    await flushPromises()
    expect(createModelConversionTask).not.toHaveBeenCalled()
  })

  it('shows an unavailable version with its reason and prevents selecting it', async () => {
    const missing = {
      ...sourceModel, task_type: 'detection',
      available_versions: [{ ...sourceModel.available_versions[0]!, checkpoint_state: 'missing' as const }],
    }
    vi.mocked(listDeploymentSourceModels).mockResolvedValue([missing])
    const { wrapper } = page()
    await flushPromises()
    wrapper.findComponent(ModelConversionForm).vm.$emit('open-source-picker')
    await flushPromises()
    const picker = wrapper.findComponent(ModelConversionSourcePickerDialog)
    expect(picker.text()).toContain('托盘分类')
    expect(picker.text()).toContain('缺少 checkpoint')
    expect(picker.find('.conversion-source-version button').attributes('disabled')).toBeDefined()
  })
})
