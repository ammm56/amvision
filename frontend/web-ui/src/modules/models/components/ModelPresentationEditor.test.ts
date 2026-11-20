import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it, vi } from 'vitest'
vi.mock('../services/model.service', () => ({ updateProjectModelPresentation: vi.fn(), getProjectModelCatalogDetail: vi.fn() }))
import { getProjectModelCatalogDetail, updateProjectModelPresentation } from '../services/model.service'
import { ApiError } from '@/shared/api/error'
import ModelPresentationEditor from './ModelPresentationEditor.vue'
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': {} } })
const model = { model_id: 'm1', scope_kind: 'project', model_name: 'original', model_type: 'yolo11', task_type: 'detection', model_scale: 's', metadata: { display_name: '名称', description: '说明', presentation_revision: 2 }, version_count: 1, build_count: 0, available_versions: [] }
function mountEditor() { return mount(ModelPresentationEditor, { props: { open: true, model, projectId: 'p1' }, global: { plugins: [i18n], stubs: { SideDrawer: { template: '<div><slot/><slot name="footer"/></div>' }, Teleport: true, ConfirmDialog: { template: '<div class="confirm"><button @click="$emit(\'confirm\')">放弃修改</button><button @click="$emit(\'cancel\')">继续编辑</button></div>' } } } }) }
describe('model presentation editor', () => {
  it('saves a trimmed display name without altering the original model identity', async () => {
    vi.mocked(updateProjectModelPresentation).mockResolvedValueOnce({ revision: 3 })
    const wrapper = mountEditor()
    await wrapper.get('input').setValue(' 新名称 ')
    await wrapper.findAll('button').find(button => button.text() === '保存')!.trigger('click')
    await flushPromises()
    expect(updateProjectModelPresentation).toHaveBeenCalledWith({ projectId: 'p1', modelId: 'm1', displayName: '新名称', description: '说明', revision: 2 })
    expect(wrapper.emitted('saved')).toHaveLength(1)
    expect(model.model_name).toBe('original')
  })
  it('preserves a dirty draft until discard is confirmed', async () => {
    const wrapper = mountEditor()
    await wrapper.get('input').setValue('草稿')
    await wrapper.findAll('button').find(button => button.text() === '取消')!.trigger('click')
    expect(wrapper.find('.confirm').exists()).toBe(true)
    await wrapper.findAll('button').find(button => button.text() === '继续编辑')!.trigger('click')
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('草稿')
    expect(wrapper.emitted('close')).toBeUndefined()
  })
  it('keeps edits visible when save fails', async () => {
    vi.mocked(updateProjectModelPresentation).mockRejectedValueOnce(new Error('模型信息已发生变化'))
    const wrapper = mountEditor()
    await wrapper.get('input').setValue('草稿')
    await wrapper.findAll('button').find(button => button.text() === '保存')!.trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('模型信息已发生变化')
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('草稿')
    expect(wrapper.emitted('saved')).toBeUndefined()
  })
  it('requires an explicit conflict choice before resubmitting the draft against the latest revision', async () => {
    vi.mocked(updateProjectModelPresentation).mockRejectedValueOnce(new ApiError(409, { message: '模型信息已发生变化' }))
      .mockResolvedValueOnce({ revision: 5 })
    vi.mocked(getProjectModelCatalogDetail).mockResolvedValueOnce({
      ...model,
      metadata: { display_name: '服务器名称', description: '其他人保存的说明', presentation_revision: 4 },
      versions: [], builds: [],
    })
    const wrapper = mountEditor()
    const button = (text: string) => wrapper.findAll('button').find(item => item.text() === text)!
    await wrapper.get('input').setValue('草稿名称')
    await button('保存').trigger('click')
    await flushPromises()
    expect(button('保存').attributes('disabled')).toBeDefined()
    await button('读取最新信息').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('服务器名称')
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('草稿名称')
    await button('保留我的草稿').trigger('click')
    await button('保存').trigger('click')
    await flushPromises()
    expect(updateProjectModelPresentation).toHaveBeenLastCalledWith({ projectId: 'p1', modelId: 'm1', displayName: '草稿名称', description: '说明', revision: 4 })
  })
})
