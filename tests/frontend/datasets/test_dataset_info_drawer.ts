import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia } from 'pinia'
import DatasetInfoDrawer from '../../../frontend/web-ui/src/modules/datasets/components/DatasetInfoDrawer.vue'
import { ApiError } from '../../../frontend/web-ui/src/shared/api/error'

const api = vi.hoisted(() => ({ editDatasetInfo: vi.fn(), getDatasetInfo: vi.fn(), listDatasetVersionPage: vi.fn() }))
vi.mock('../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service', () => api)
vi.mock('vue-router', () => ({ onBeforeRouteLeave: vi.fn(), onBeforeRouteUpdate: vi.fn(), useRouter: () => ({ push: vi.fn() }) }))
const wrappers: ReturnType<typeof mount>[] = []
function setup(editable = true, mode: 'info' | 'edit' = 'edit') {
  const wrapper = mount(DatasetInfoDrawer, {
    props: { info: { project_id: 'p', dataset_id: 'd', display_name: '原名称', description: '', task_type: 'detection', revision: 'rev-3', created_at: '', updated_at: '' }, mode, editable },
    global: { plugins: [createPinia(), createI18n({ legacy: false, locale: 'zh-CN', messages: {} })], stubs: {
      SideDrawer: { props: ['open'], template: '<section v-if="open"><button data-close @click="$emit(\'close\')">关闭</button><slot/><slot name="footer"/></section>' },
      ConfirmDialog: { template: '<aside data-confirm><button @click="$emit(\'cancel\')">保留</button><button @click="$emit(\'confirm\')">放弃</button></aside>' },
    } },
  })
  wrappers.push(wrapper)
  return wrapper
}
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.clearAllMocks() })
describe('数据集信息编辑保护', () => {
  it('关闭脏草稿先确认，取消后字段不丢失', async () => {
    const wrapper = setup()
    await wrapper.get('input').setValue('待保存名称')
    await wrapper.get('[data-close]').trigger('click')
    expect(wrapper.find('[data-confirm]').exists()).toBe(true)
    await wrapper.get('[data-confirm] button').trigger('click')
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('待保存名称')
    expect(api.editDatasetInfo).not.toHaveBeenCalled()
  })
  it('并发冲突保留草稿，重新读取前禁止覆盖保存', async () => {
    api.editDatasetInfo.mockRejectedValue(new ApiError(409, { message: '并发冲突' }))
    const wrapper = setup()
    await wrapper.get('input').setValue('待保存名称')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(api.editDatasetInfo.mock.calls[0][0].revision).toBe('rev-3')
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('待保存名称')
    expect(wrapper.text()).toContain('重新加载')
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
  })
  it('只读主体不能通过提交表单调用更新接口', async () => {
    const wrapper = setup(false)
    await wrapper.get('input').setValue('非法覆盖')
    await wrapper.get('form').trigger('submit')
    expect(api.editDatasetInfo).not.toHaveBeenCalled()
  })
})


it('详情展示真实最新版本统计，读取失败不得伪装成零', async () => {
  api.listDatasetVersionPage.mockResolvedValue({ items: [{ version_number: 9, sample_count: 609, category_count: 2, metadata: { source_import_id: 'import' } }], total: 4 })
  const w = setup(false, 'info'); await flushPromises()
  expect(w.find('.dataset-info-metrics').text()).toContain('v9')
  expect(w.find('.dataset-info-metrics').text()).toContain('609')
  expect(w.find('.dataset-info-metrics').text()).toContain('版本数量4')
  api.listDatasetVersionPage.mockRejectedValue(new Error('offline'))
  const unavailable = setup(false, 'info'); await flushPromises()
  expect(unavailable.find('.dataset-info-metrics').text()).not.toContain('样本0')
  expect(unavailable.find('.dataset-info-metrics').text()).toContain('样本—')
})

it('最新可用版本与所有版本数量分别读取，不把缺失版本当成可用', async () => {
  api.listDatasetVersionPage.mockImplementation(async query => query.state === 'available'
    ? { items: [{ version_number: 8, sample_count: 20, category_count: 3, metadata: { format_type: 'coco' } }], total: 2 }
    : { items: [{ version_number: 9, availability: { state: 'missing' } }], total: 4 })
  const w = setup(false, 'info'); await flushPromises()
  expect(w.text()).toContain('v8'); expect(w.text()).not.toContain('v9')
  expect(w.text()).toContain('4 个版本'); expect(w.text()).toContain('20 张'); expect(w.text()).toContain('COCO ZIP')
})
