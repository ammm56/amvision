import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it } from 'vitest'
import PlatformBaseModelPickerDialog from './PlatformBaseModelPickerDialog.vue'
import type { PlatformBaseModelDetail, PlatformBaseModelSummary } from '../services/model.service'

enableAutoUnmount(afterEach)
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': {} } })

function model(family: string, scale: string, state: 'present' | 'missing'): PlatformBaseModelSummary {
  const id = `${family}-${scale}`
  return {
    model_id: id, scope_kind: 'platform-base', model_name: family, model_type: family,
    task_type: 'detection', model_scale: scale, metadata: {}, version_count: 1, build_count: 0,
    available_versions: [{
      model_version_id: `${id}-v1`, version_number: 1, source_kind: 'pretrained-reference', file_ids: [],
      metadata: {}, checkpoint_state: state, checkpoint_storage_uri: `models/${id}.pt`,
    }],
  }
}

const available = model('yolo11', 's', 'present')
const medium = model('yolo11', 'm', 'present')
const missing = model('yolox', 's', 'missing')
const detail: PlatformBaseModelDetail = { ...available, versions: [], builds: [] }
const missingDetail: PlatformBaseModelDetail = { ...missing, versions: [], builds: [] }
const project = { model_version_id: 'project-v2', title: '条码检测', subtitle: 'v2', checkpoint_storage_uri: 'runs/best.pt', checkpoint_state: 'present' as const }
const props = {
  open: true, loading: false, detailLoading: false, retryLabel: '重试', title: '选择基础模型', closeLabel: '关闭',
  taskTypeLabel: '任务类型', taskTypeOptions: [{ label: '目标检测', value: 'detection' }], selectedTaskType: 'detection',
  modelListTitle: '模型选择', modelNameLabel: '模型名称', detailTitle: '版本与使用', detailLoadingLabel: '正在加载',
  extraVersionsTitle: '项目训练版本', scaleLabel: '参数量', applyModelLabel: '使用当前模型', emptyTitle: '暂无模型',
  detailEmptyTitle: '先选择模型', models: [available, medium, missing], selectedModelId: available.model_id, selectedModelDetail: detail,
}

function mountDialog(overrides: Partial<InstanceType<typeof PlatformBaseModelPickerDialog>['$props']> = {}) {
  const wrapper = mount(PlatformBaseModelPickerDialog, { props: { ...props, ...overrides }, global: { plugins: [i18n] } })
  const confirm = () => wrapper.findAll('button').find(button => button.text() === '使用当前模型')!
  return { wrapper, confirm }
}

describe('PlatformBaseModelPickerDialog', () => {
  it('groups variants by model family and supports searching a family or scale', async () => {
    const { wrapper } = mountDialog()
    expect(wrapper.findAll('.model-picker__family-button').map(button => button.text())).toEqual(['yolo11', 'yolox'])
    const scales = wrapper.findAll('[aria-label="参数量"] button')
    expect(scales.map(button => button.text())).toEqual(['s', 'm'])
    await scales[1].trigger('click')
    expect(wrapper.emitted('select-model')).toEqual([[medium.model_id]])
    await wrapper.get('input[aria-label="搜索模型名称"]').setValue('yolox-s')
    expect(wrapper.findAll('.model-picker__family-button')).toHaveLength(1)
    expect(wrapper.get('.model-picker__family-button').text()).toBe('yolox')
    await wrapper.get('.model-picker__family-button').trigger('click')
    expect(wrapper.emitted('select-model')?.at(-1)).toEqual([missing.model_id])
  })

  it('shows real file status and confirms the selected platform version', async () => {
    const { wrapper, confirm } = mountDialog()
    expect(wrapper.text()).toContain('文件存在')
    expect(wrapper.text()).toContain('yolo11-s.pt')
    await confirm().trigger('click')
    expect(wrapper.emitted('apply-training-version')).toEqual([[{ model: detail, modelVersionId: 'yolo11-s-v1' }]])
  })

  it('can select a project version despite the missing platform checkpoint', async () => {
    const { wrapper, confirm } = mountDialog({
      selectedModelId: missing.model_id, selectedModelDetail: missingDetail, weightsOnly: true,
      extraVersions: [project, { ...project, model_version_id: 'project-unknown', subtitle: 'v1', checkpoint_state: undefined }],
    })
    expect(wrapper.text()).toContain('文件缺失')
    expect(confirm().attributes('disabled')).toBeDefined()
    const projectGroup = wrapper.get('[aria-label="项目训练版本"]')
    expect(projectGroup.text()).toContain('条码检测')
    expect(projectGroup.text()).toContain('v2')
    expect(projectGroup.text()).toContain('best.pt')
    expect(projectGroup.get('[value="project-unknown"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('input[value=""]').exists()).toBe(false)
    await projectGroup.get('[value="project-v2"]').setValue(true)
    expect(wrapper.emitted('apply-training-version')).toBeUndefined()
    await confirm().trigger('click')
    expect(wrapper.emitted('apply-training-version')).toEqual([[{ model: missingDetail, modelVersionId: 'project-v2' }]])
  })

  it('restores the applied project version and discards a pending choice when reopened', async () => {
    const { wrapper } = mountDialog({ extraVersions: [project], selectedVersionId: project.model_version_id })
    const projectSelected = () => (wrapper.get<HTMLInputElement>('input[value="project-v2"]').element).checked
    expect(projectSelected()).toBe(true)
    await wrapper.get('input[value="yolo11-s-v1"]').setValue(true)
    expect(projectSelected()).toBe(false)
    await wrapper.setProps({ open: false })
    await wrapper.setProps({ open: true })
    expect(projectSelected()).toBe(true)
  })

  it('selects only the architecture for training from scratch', async () => {
    const { wrapper, confirm } = mountDialog({ selectedModelId: missing.model_id, selectedModelDetail: missingDetail })
    expect(confirm().attributes('disabled')).toBeDefined()
    await wrapper.get('input[value=""]').setValue(true)
    await confirm().trigger('click')
    expect(wrapper.emitted('apply-model')).toEqual([[missingDetail]])
  })

  it('never confirms another model while its details are changing', async () => {
    const { wrapper, confirm } = mountDialog()
    await wrapper.setProps({ selectedModelId: medium.model_id, detailLoading: true })
    expect(wrapper.get('[role="status"]').text()).toContain('正在加载')
    expect(confirm().attributes('disabled')).toBeDefined()
    await wrapper.setProps({ detailLoading: false })
    expect(confirm().attributes('disabled')).toBeDefined()
  })

  it('shows list and detail failures with retry', async () => {
    const { wrapper } = mountDialog({ models: [], selectedModelDetail: null, loading: true })
    expect(wrapper.get('[role="status"]').text()).toContain('正在加载')
    await wrapper.setProps({ loading: false, listError: '目录读取失败' })
    expect(wrapper.get('[role="alert"]').text()).toContain('目录读取失败')
    await wrapper.get('[role="alert"] button').trigger('click')
    expect(wrapper.emitted('retry-list')).toHaveLength(1)
    await wrapper.setProps({ models: [available], listError: null, detailError: '详情读取失败' })
    expect(wrapper.get('[role="alert"]').text()).toContain('详情读取失败')
    await wrapper.get('[role="alert"] button').trigger('click')
    expect(wrapper.emitted('retry-detail')).toHaveLength(1)
  })
})
