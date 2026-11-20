import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'
import PlatformBaseModelPickerDialog from './PlatformBaseModelPickerDialog.vue'
import type { PlatformBaseModelDetail, PlatformBaseModelSummary } from '../services/model.service'

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': {} } })
function model(id: string, state: 'present' | 'missing'): PlatformBaseModelSummary {
  return { model_id: id, scope_kind: 'platform-base', model_name: id, model_type: id, task_type: 'detection', model_scale: 's', metadata: {}, version_count: 1, build_count: 0, available_versions: [{ model_version_id: `${id}-v1`, source_kind: 'pretrained-reference', file_ids: [], metadata: {}, checkpoint_state: state, checkpoint_storage_uri: `models/${id}.pt` }] }
}
const available = model('yolo11', 'present')
const detail: PlatformBaseModelDetail = { ...available, versions: [], builds: [] }
const props = {
  open: true, loading: false, detailLoading: false, retryLabel: '重试', title: '选择基础模型', closeLabel: '关闭',
  taskTypeOptions: [{ label: 'detection', value: 'detection' }], selectedTaskType: 'detection', modelListTitle: '', modelNameLabel: '', detailTitle: '', detailLoadingLabel: '正在加载', currentSelectionLabel: '当前选择', versionSelectionLabel: '', versionsTitle: '', extraVersionsTitle: '项目训练版本', scaleLabel: '', applyModelLabel: '', applyTrainingVersionLabel: '选择此版本', emptyTitle: '暂无模型', emptyDescription: '', detailEmptyTitle: '先选择模型', detailEmptyDescription: '', emptyVersionsTitle: '', emptyVersionsDescription: '', models: [available, model('yolox', 'missing')], selectedModelId: 'yolo11', selectedModelDetail: detail,
}
function mountDialog(overrides: Record<string, unknown> = {}) {
  return mount(PlatformBaseModelPickerDialog, { props: { ...props, ...overrides }, global: { plugins: [i18n], stubs: { SideDrawer: { template: '<div><slot/><slot name="footer"/></div>' } } } })
}
describe('PlatformBaseModelPickerDialog', () => {
  it('shows real checkpoint state and filters models', async () => {
    const wrapper = mountDialog()
    expect(wrapper.text()).toContain('文件存在')
    expect(wrapper.text()).toContain('文件缺失')
    expect(wrapper.text()).toContain('yolo11.pt')
    await wrapper.get('input[aria-label="搜索模型名称"]').setValue('yolox')
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
    expect(wrapper.find('tbody').text()).toContain('yolox')
  })
  it('does not enable missing or unchecked files', () => {
    const missing = model('yolox', 'missing')
    const wrapper = mountDialog({ selectedModelId: 'yolox', selectedModelDetail: { ...missing, versions: [], builds: [] } })
    expect(wrapper.findAll('button').find(button => button.text() === '使用所选模型')!.attributes('disabled')).toBeDefined()
  })
  it('allows choosing the architecture without a checkpoint for training from scratch', async () => {
    const missing = model('yolox', 'missing')
    const missingDetail = { ...missing, versions: [], builds: [] }
    const wrapper = mountDialog({ selectedModelId: 'yolox', selectedModelDetail: missingDetail })
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await wrapper.findAll('button').find(button => button.text() === '使用所选模型')!.trigger('click')
    expect(wrapper.emitted('apply-model')).toEqual([[missingDetail]])
  })
  it('confirms the actual checkpoint version for weight initialization', async () => {
    const wrapper = mountDialog()
    await wrapper.findAll('button').find(button => button.text() === '使用所选模型')!.trigger('click')
    expect(wrapper.emitted('apply-training-version')).toEqual([[{ model: detail, modelVersionId: 'yolo11-v1' }]])
  })
  it('distinguishes loading, list failure, and detail failure with retry', async () => {
    const wrapper = mountDialog({ models: [], selectedModelDetail: null, loading: true })
    expect(wrapper.get('[role="status"]').text()).toContain('正在加载')
    await wrapper.setProps({ loading: false, listError: '目录读取失败' })
    expect(wrapper.get('[role="alert"]').text()).toContain('目录读取失败')
    await wrapper.findAll('button').find(button => button.text() === '重试')!.trigger('click')
    expect(wrapper.emitted('retry-list')).toHaveLength(1)
    await wrapper.setProps({ models: [available], listError: null, detailError: '详情读取失败' })
    expect(wrapper.get('[role="alert"]').text()).toContain('详情读取失败')
    await wrapper.findAll('button').find(button => button.text() === '重试')!.trigger('click')
    expect(wrapper.emitted('retry-detail')).toHaveLength(1)
  })
})
