import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it, vi } from 'vitest'
vi.mock('@/shared/api/resource-deletion', () => ({ previewModelVersionDeletion: vi.fn(), submitResourceDeletion: vi.fn() }))
vi.mock('../services/model.service', () => ({ listModelVersionReferences: vi.fn() }))
import { previewModelVersionDeletion, submitResourceDeletion } from '@/shared/api/resource-deletion'
import { listModelVersionReferences } from '../services/model.service'
import ModelVersionDeleteDialog from './ModelVersionDeleteDialog.vue'
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': {} } })
function mountDialog() {
  return mount(ModelVersionDeleteDialog, {
    props: { open: true, projectId: 'p1', modelId: 'm1', versionId: 'model-version-1', modelName: 'model', formats: ['PyTorch', 'ONNX'], otherVersionCount: 1 },
    global: { plugins: [i18n], stubs: {
      Teleport: true,
      RouterLink: true,
      ConfirmDialog: { props: ['showConfirm', 'confirmDisabled', 'confirmLabel'], template: '<div><slot/><slot name="leading-actions"/><button v-if="showConfirm" :disabled="confirmDisabled" @click="$emit(\'confirm\')">{{ confirmLabel }}</button><button @click="$emit(\'cancel\')">关闭</button></div>' },
    } },
  })
}
describe('model version deletion', () => {
  it('requires the actual version ID and sends the preview revision', async () => {
    vi.mocked(previewModelVersionDeletion).mockResolvedValueOnce({ blocked: false, revision: 'rev1', deleted_models: [{ kind: 'model-build', resource_id: 'b1' }] })
    vi.mocked(submitResourceDeletion).mockResolvedValueOnce({ operation_id: 'op1', project_id: 'p1', resource_kind: 'model-version', resource_id: 'model-version-1', state: 'committed', error: null })
    const wrapper = mountDialog(); await flushPromises()
    expect(wrapper.text()).toContain('保留来源数据集、任务历史及任务目录中的文件')
    expect(wrapper.text()).toContain('保留同一模型的其他 1 个版本')
    const confirm = () => wrapper.findAll('button').find(button => button.text() === '删除版本')!
    expect(confirm().attributes('disabled')).toBeDefined()
    await wrapper.get('input').setValue('model-version-1')
    await wrapper.vm.$nextTick()
    expect(confirm().attributes('disabled')).toBeUndefined()
    await confirm().trigger('click'); await flushPromises()
    expect(submitResourceDeletion).toHaveBeenCalledWith('model-version', 'model-version-1', 'p1', 'rev1')
    expect(wrapper.emitted('deleted')).toHaveLength(1)
  })
  it('does not offer deletion when a reference blocks preview', async () => {
    vi.mocked(previewModelVersionDeletion).mockResolvedValueOnce({ blocked: true, reason: '资源仍被使用' })
    vi.mocked(listModelVersionReferences).mockResolvedValueOnce({ items: [{ deployment_id: 'd1', display_name: '部署 A', model_build_id: 'b1', build_format: 'onnx', runtime_backend: 'onnxruntime', runtime_states: { sync: 'stopped' } }], total: 1 })
    const wrapper = mountDialog(); await flushPromises()
    expect(wrapper.text()).toContain('仍被 1 个部署实例引用')
    expect(wrapper.text()).toContain('已停止')
    expect(wrapper.find('input').exists()).toBe(false)
    await wrapper.findAll('button').find(button => button.text() === '查看引用')!.trigger('click')
    expect(wrapper.emitted('references')).toHaveLength(1)
  })
  it('offers a fresh check after a preflight read failure without treating it as a dependency', async () => {
    vi.mocked(previewModelVersionDeletion).mockRejectedValueOnce(new Error('无法读取'))
      .mockResolvedValueOnce({ blocked: false, revision: 'rev2', deleted_models: [] })
    const wrapper = mountDialog(); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('无法读取')
    expect(wrapper.find('input').exists()).toBe(false)
    await wrapper.findAll('button').find(button => button.text() === '重新检查')!.trigger('click')
    await flushPromises()
    expect(wrapper.find('input').exists()).toBe(true)
  })
})
