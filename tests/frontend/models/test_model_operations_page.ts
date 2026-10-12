import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { i18n, setI18nLocale } from '@/platform/i18n'
import ModelOperationsPage from '@/modules/models/pages/ModelOperationsPage.vue'
import ModelConversionSourcePickerDialog from '@/modules/models/components/ModelConversionSourcePickerDialog.vue'
import ModelConversionForm from '@/modules/models/components/ModelConversionForm.vue'
import {
  createModelConversionTask, listDeploymentSourceModels, listPlatformBaseModels, listTrainingParameterSchemas,
  listModelTrainingTasks, listModelConversionTasks, type DeploymentSourceModelSummary,
} from '@/modules/models/services/model.service'
import { listProjectDatasetExports } from '@/modules/datasets/services/dataset.service'

vi.mock('@/modules/models/services/model.service', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/modules/models/services/model.service')>(),
  createModelConversionTask: vi.fn(), listDeploymentSourceModels: vi.fn(), listPlatformBaseModels: vi.fn(),
  listTrainingParameterSchemas: vi.fn(), listModelTrainingTasks: vi.fn(), listModelConversionTasks: vi.fn(),
}))
vi.mock('@/modules/datasets/services/dataset.service', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/modules/datasets/services/dataset.service')>(), listProjectDatasetExports: vi.fn(),
}))
enableAutoUnmount(afterEach)

const sourceModel: DeploymentSourceModelSummary = {
  model_id: 'model-trained', project_id: 'project-1', scope_kind: 'project', model_name: 'PCB classifier',
  model_type: 'yolo11', task_type: 'classification', model_scale: 's', metadata: {}, version_count: 1, build_count: 0,
  available_versions: [{
    model_version_id: 'version-trained', source_kind: 'training-output', file_ids: ['checkpoint', 'labels'],
    metadata: { category_names: ['ok', 'ng', 'rework'] }, checkpoint_file_id: 'checkpoint', checkpoint_storage_uri: 'best.pt',
    labels_file_id: 'labels', labels_storage_uri: 'labels.txt',
  }],
}

function page() {
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
  const wrapper = mount(ModelOperationsPage, {
    global: { plugins: [pinia, i18n], stubs: {
      ResourceCleanupPanel: true, ImportedModelAssets: true, ModelTrainingForm: true, TrainingTaskList: true,
      ConversionTaskList: true, TrainingDatasetExportPickerDialog: true, RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
    } },
  })
  return { wrapper, projects }
}

beforeEach(() => {
  vi.clearAllMocks()
  setI18nLocale('zh-CN')
  vi.mocked(listPlatformBaseModels).mockResolvedValue([])
  vi.mocked(listDeploymentSourceModels).mockImplementation(async (projectId, taskType) => projectId === 'project-1' && taskType === 'classification' ? [sourceModel] : [])
  vi.mocked(listTrainingParameterSchemas).mockResolvedValue({ protocol_version: 1, items: [] })
  vi.mocked(listProjectDatasetExports).mockResolvedValue([])
  vi.mocked(listModelTrainingTasks).mockResolvedValue([])
  vi.mocked(listModelConversionTasks).mockResolvedValue([])
  vi.mocked(createModelConversionTask).mockResolvedValue({ task_id: 'conversion-1' } as never)
})

describe('ModelOperationsPage conversion flow', () => {
  it('submits the real trained version without a platform catalog entry, then clears it on project change', async () => {
    const { wrapper, projects } = page()
    await flushPromises()
    wrapper.findComponent(ModelConversionForm).vm.$emit('open-source-picker')
    await flushPromises()
    wrapper.findComponent(ModelConversionSourcePickerDialog).vm.$emit('change-task-type', 'classification')
    await flushPromises()
    const picker = wrapper.findComponent(ModelConversionSourcePickerDialog)
    expect(picker.text()).toContain('PCB classifier')
    expect(picker.text()).toContain('3 个类别')
    await picker.find('.conversion-source-version button').trigger('click')
    await flushPromises()
    const form = wrapper.findComponent(ModelConversionForm)
    expect(form.text()).toContain('PCB classifier')
    expect(form.text()).not.toContain('尚未选择基础模型')
    expect(form.find('button[type="submit"]').attributes('disabled')).toBeUndefined()
    await form.find('form').trigger('submit')
    await flushPromises()
    expect(createModelConversionTask).toHaveBeenCalledWith(expect.objectContaining({
      projectId: 'project-1', modelType: 'yolo11', sourceModelVersionId: 'version-trained', taskType: 'classification',
    }))
    projects.selectedProjectId = 'project-2'
    await flushPromises()
    expect(form.find('button[type="submit"]').attributes('disabled')).toBeDefined()
    expect(form.text()).not.toContain('conversion-1')
    expect(listDeploymentSourceModels).toHaveBeenLastCalledWith('project-2', 'classification')
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
})
