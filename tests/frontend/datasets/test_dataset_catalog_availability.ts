import { expect, it, vi } from 'vitest'
import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import { reactive } from 'vue'
import { createI18n } from 'vue-i18n'
import DatasetCatalogPage from '../../../frontend/web-ui/src/modules/datasets/pages/DatasetCatalogPage.vue'
import SelectField from '../../../frontend/web-ui/src/shared/ui/components/Select.vue'
import Button from '../../../frontend/web-ui/src/shared/ui/components/Button.vue'
import { ApiError } from '../../../frontend/web-ui/src/shared/api/error'

const route = reactive({ query: { tab: 'versions', state: '', offset: '0' } })
const api = vi.hoisted(() => ({ listDatasetCatalog: vi.fn(), listDatasetVersionPage: vi.fn(), listDatasetRecordPage: vi.fn() }))
const deletion = vi.hoisted(() => ({ submitResourceDeletion: vi.fn() }))
vi.mock('../../../frontend/web-ui/src/shared/api/resource-deletion', () => deletion)
vi.mock('../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service', () => api)
vi.mock('../../../frontend/web-ui/src/app/stores/project.store', () => ({ useProjectStore: () => ({ selectedProjectId: 'p' }) }))
vi.mock('../../../frontend/web-ui/src/app/stores/session.store', () => ({ useSessionStore: () => ({ hasScopes: () => true }) }))
vi.mock('../../../frontend/web-ui/src/app/stores/feedback.store', () => ({ useFeedbackStore: () => ({ info: vi.fn() }) }))
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => ({
  push: vi.fn(), replace: vi.fn(({ query }) => { Object.assign(route.query, query) }),
}) }))

it('数据集为空时保留表头和导入入口，搜索无结果时允许清除筛选', async () => {
  route.query = { tab: 'datasets', state: '', offset: '0' }
  api.listDatasetCatalog.mockResolvedValue({ total: 0, items: [] })
  const wrapper = shallowMount(DatasetCatalogPage, { global: {
    plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })],
    stubs: { ResourceTable: { template: '<table><slot /></table>' }, Button: { template: '<button><slot /></button>' } },
  } })
  await flushPromises()
  expect(wrapper.text()).toContain('数据集名称')
  expect(wrapper.text()).toContain('暂无数据集')
  expect(wrapper.find('.dataset-catalog-empty').text()).toContain('导入数据集')
  await wrapper.get('input[aria-label="搜索数据集"]').setValue('missing')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.text()).toContain('未找到匹配的数据集')
  expect(wrapper.text()).toContain('请尝试调整关键词或筛选条件')
  expect(wrapper.text()).toContain('清除筛选')
  wrapper.unmount()
  route.query = { tab: 'versions', state: '', offset: '0' }
})

it('版本筛选传给后端、重置分页，未检查状态不能被显示为可用', async () => {
  api.listDatasetVersionPage.mockResolvedValue({ total: 1, items: [{
    dataset_id: 'd', dataset_version_id: 'v', version_number: 1, display_name: '数据集',
    task_type: 'detection', metadata: {}, split_counts: {}, sample_count: 0, category_count: 0,
  }] })
  const wrapper = shallowMount(DatasetCatalogPage, { global: {
    plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })],
    stubs: { ResourceTable: { template: '<table><slot /></table>' } },
  } })
  await flushPromises()
  expect(wrapper.findComponent({ name: 'StatusBadge' }).props('label')).toBe('未检查')
  const filter = wrapper.findAllComponents(SelectField).at(-1)
  expect(filter).toBeDefined()
  expect(filter!.props('options').map((item) => item.value)).toContain('missing')
  route.query.offset = '20'
  await flushPromises()
  filter!.vm.$emit('update:modelValue', 'missing')
  await flushPromises()
  expect(api.listDatasetVersionPage).toHaveBeenLastCalledWith(expect.objectContaining({ state: 'missing', offset: 0 }), expect.anything())
  wrapper.unmount()
})

it('切换记录页时不展示旧页表格，失败后可重试', async () => {
  route.query = { tab: 'versions', state: '', offset: '0' }
  api.listDatasetVersionPage.mockResolvedValue({ total: 1, items: [{
    dataset_id: 'd', dataset_version_id: 'v', version_number: 1, display_name: '旧版本',
    task_type: 'detection', metadata: {}, split_counts: {}, sample_count: 0, category_count: 0,
  }] })
  let rejectRequest!: (reason: Error) => void
  api.listDatasetRecordPage.mockImplementationOnce(() => new Promise((_, reject) => { rejectRequest = reject }))
  const wrapper = shallowMount(DatasetCatalogPage, { global: {
    plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })],
    stubs: { ResourceTable: { template: '<table><slot /></table>' } },
  } })
  await flushPromises()
  expect(wrapper.text()).toContain('旧版本')
  await wrapper.findAll('[role="tab"]').find(item => item.text() === '导入记录')!.trigger('click')
  expect(wrapper.text()).not.toContain('旧版本')
  expect(wrapper.text()).toContain('正在加载')
  rejectRequest(new Error('offline'))
  await flushPromises()
  expect(wrapper.text()).not.toContain('旧版本')
  expect(wrapper.findComponent({ name: 'InlineError' }).exists()).toBe(true)
  api.listDatasetRecordPage.mockResolvedValue({ total: 0, items: [] })
  wrapper.findAllComponents(Button)[1].vm.$emit('click')
  await flushPromises()
  expect(wrapper.findComponent({ name: 'InlineError' }).exists()).toBe(false)
  wrapper.unmount()
})

it('删除版本确认展示选中的版本和真实数量', async () => {
  route.query = { tab: 'versions', state: '', offset: '0' }
  api.listDatasetVersionPage.mockResolvedValue({ total: 1, items: [{
    dataset_id: 'd', dataset_version_id: 'v', version_number: 2, display_name: '数据集',
    task_type: 'detection', metadata: {}, split_counts: {}, sample_count: 609, object_count: 982, category_count: 2,
  }] })
  const wrapper = shallowMount(DatasetCatalogPage, { global: {
    plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })],
    stubs: { ResourceTable: { template: '<table><slot /></table>' }, ConfirmDialog: { template: '<div><slot /></div>' } },
  } })
  await flushPromises()
  wrapper.findComponent({ name: 'ResourceMenu' }).vm.$emit('action', 'delete')
  await flushPromises()
  expect(wrapper.text()).toContain('数据集 · v2')
  expect(wrapper.text()).toContain('609')
  expect(wrapper.text()).toContain('982')
  expect(wrapper.text()).toContain('关联的导入、导出记录及其任务也将删除')
  expect(wrapper.text()).toContain('存在外部引用时将阻止删除')
  wrapper.unmount()
})

it('删除点云版本时按样本计数而不是称为图片', async () => {
  route.query = { tab: 'versions', state: '', offset: '0' }
  api.listDatasetVersionPage.mockResolvedValue({ total: 1, items: [{ dataset_id: 'd', dataset_version_id: 'v', version_number: 1, display_name: '点云', task_type: 'point-cloud', metadata: {}, split_counts: {}, sample_count: 1, object_count: 0, category_count: 0 }] })
  const wrapper = shallowMount(DatasetCatalogPage, { global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })], stubs: { ResourceTable: { template: '<table><slot /></table>' }, ConfirmDialog: { template: '<div><slot /></div>' } } } })
  await flushPromises()
  wrapper.findComponent({ name: 'ResourceMenu' }).vm.$emit('action', 'delete')
  await flushPromises()
  expect(wrapper.find('.version-delete-table').text()).toContain('样本1')
  expect(wrapper.find('.version-delete-table').text()).not.toContain('图片')
  wrapper.unmount()
})

it('删除版本被引用阻止时保留对象及原因，隐藏删除按钮', async () => {
  route.query = { tab: 'versions', state: '', offset: '0' }
  api.listDatasetVersionPage.mockResolvedValue({ total: 1, items: [{ dataset_id: 'd', project_id: 'p', dataset_version_id: 'v', version_number: 2, display_name: '数据集', task_type: 'detection', metadata: {}, split_counts: {}, sample_count: 609, object_count: 982, category_count: 2 }] })
  deletion.submitResourceDeletion.mockRejectedValueOnce(new ApiError(409, { message: '版本被训练引用', details: { blockers: [{ resource_kind: 'task', resource_id: 'train-123', state: 'completed' }] } }))
  const wrapper = shallowMount(DatasetCatalogPage, { global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })], stubs: { ResourceTable: { template: '<table><slot /></table>' }, ConfirmDialog: { name: 'ConfirmDialog', props: ['showConfirm', 'title'], template: '<div><slot /></div>' } } } })
  await flushPromises()
  wrapper.findComponent({ name: 'ResourceMenu' }).vm.$emit('action', 'delete')
  await flushPromises()
  wrapper.findComponent({ name: 'ConfirmDialog' }).vm.$emit('confirm')
  await flushPromises()
  expect(wrapper.text()).toContain('数据集 · v2')
  expect(wrapper.findComponent({ name: 'ConfirmDialog' }).props('title')).toBe('暂时无法删除版本')
  expect(wrapper.text()).toContain('train-123')
  expect(wrapper.findComponent({ name: 'ConfirmDialog' }).props('showConfirm')).toBe(false)
  wrapper.unmount()
})

it('Workflow 快照阻止删除时显示接口返回的快照路径', async () => {
  route.query = { tab: 'versions', state: '', offset: '0' }
  api.listDatasetVersionPage.mockResolvedValue({ total: 1, items: [{ dataset_id: 'd', project_id: 'p', dataset_version_id: 'v', version_number: 1, display_name: '数据集', task_type: 'detection', metadata: {}, split_counts: {}, sample_count: 1, object_count: 1, category_count: 1 }] })
  deletion.submitResourceDeletion.mockRejectedValueOnce(new ApiError(409, { message: 'Workflow 仍引用待删除资源', details: { blockers: [{ resource_kind: 'workflow', snapshot_object_key: 'workflows/demo/snapshot.json', references: ['v'] }] } }))
  const wrapper = shallowMount(DatasetCatalogPage, { global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })], stubs: { ResourceTable: { template: '<table><slot /></table>' }, ConfirmDialog: { name: 'ConfirmDialog', props: ['showConfirm'], template: '<div><slot /></div>' } } } })
  await flushPromises()
  wrapper.findComponent({ name: 'ResourceMenu' }).vm.$emit('action', 'delete')
  await flushPromises()
  wrapper.findComponent({ name: 'ConfirmDialog' }).vm.$emit('confirm')
  await flushPromises()
  expect(wrapper.text()).toContain('workflows/demo/snapshot.json')
  expect(wrapper.findComponent({ name: 'ConfirmDialog' }).props('showConfirm')).toBe(false)
  wrapper.unmount()
})

it('真实确认框接收依赖阻止后显示原因并移除删除操作', async () => {
  route.query = { tab: 'versions', state: '', offset: '0' }
  api.listDatasetVersionPage.mockResolvedValue({ total: 1, items: [{ dataset_id: 'd', project_id: 'p', dataset_version_id: 'v', version_number: 1, display_name: '测试版本', task_type: 'detection', metadata: {}, split_counts: {}, sample_count: 1, object_count: 1, category_count: 1 }] })
  deletion.submitResourceDeletion.mockRejectedValueOnce(new ApiError(409, { message: '资源仍被使用', details: { blockers: [{ resource_kind: 'workflow', snapshot_object_key: 'workflows/fixture.json' }] } }))
  const wrapper = mount(DatasetCatalogPage, { attachTo: document.body, global: {
    plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })],
    stubs: { ResourceMenu: { name: 'ResourceMenu', template: '<button />' }, ResourceCleanupPanel: true, PaginationControls: true, Select: true },
  } })
  await flushPromises()
  wrapper.getComponent({ name: 'ResourceMenu' }).vm.$emit('action', 'delete')
  await flushPromises()
  const dialog = document.querySelector('[role="dialog"]')!
  const remove = [...dialog.querySelectorAll('button')].find(button => button.textContent?.includes('删除版本'))!
  remove.click()
  await flushPromises()
  expect(dialog.textContent).toContain('暂时无法删除版本')
  expect(dialog.textContent).toContain('workflows/fixture.json')
  expect([...dialog.querySelectorAll('button')].some(button => button.textContent?.includes('删除版本'))).toBe(false)
  wrapper.unmount()
})

it('版本删除请求断线后不自动重试，要求先刷新确认结果', async () => {
  route.query = { tab: 'versions', state: '', offset: '0' }
  api.listDatasetVersionPage.mockResolvedValue({ total: 1, items: [{ dataset_id: 'd', project_id: 'p', dataset_version_id: 'v', version_number: 2, display_name: '数据集', task_type: 'detection', metadata: {}, split_counts: {}, sample_count: 1, object_count: 1, category_count: 1 }] })
  deletion.submitResourceDeletion.mockClear().mockRejectedValueOnce(new TypeError('网络中断'))
  const wrapper = shallowMount(DatasetCatalogPage, { global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })], stubs: { ResourceTable: { template: '<table><slot /></table>' }, ConfirmDialog: { name: 'ConfirmDialog', props: ['showConfirm'], template: '<div><slot /></div>' } } } })
  await flushPromises()
  wrapper.findComponent({ name: 'ResourceMenu' }).vm.$emit('action', 'delete')
  await flushPromises()
  const dialog = wrapper.findComponent({ name: 'ConfirmDialog' })
  dialog.vm.$emit('confirm')
  await flushPromises()
  expect(wrapper.findComponent({ name: 'InlineError' }).props('message')).toContain('结果尚未确认')
  expect(dialog.props('showConfirm')).toBe(false)
  dialog.vm.$emit('confirm')
  await flushPromises()
  expect(deletion.submitResourceDeletion).toHaveBeenCalledTimes(1)
  wrapper.unmount()
})

it('导出列表区分文件不可下载、清理待完成和已清理', async () => {
  route.query = { tab: 'exports', state: '', offset: '0' }
  api.listDatasetRecordPage.mockResolvedValue({ total: 1, items: [{ dataset_export_id: 'export-1', dataset_id: 'd', project_id: 'p', display_name: '测试', status: 'completed', format_id: 'coco', metadata: { files_cleaned_at: '2026-11-17T00:00:00Z' } }] })
  const wrapper = shallowMount(DatasetCatalogPage, { global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })], stubs: { ResourceTable: { template: '<table><slot /></table>' } } } })
  await flushPromises()
  expect(wrapper.text()).toContain('文件不可下载')
  const panel = wrapper.findComponent({ name: 'ResourceCleanupPanel' })
  panel.vm.$emit('status', [{ operation_id: 'op', project_id: 'p', resource_kind: 'dataset-export-files', resource_id: 'export-1', state: 'committed', error: '文件占用' }])
  await flushPromises()
  expect(wrapper.text()).toContain('清理待完成')
  panel.vm.$emit('status', [])
  await flushPromises()
  expect(wrapper.text()).toContain('已清理')
  wrapper.unmount()
})

it('同页筛选加载时保留旧表但暂时禁止操作', async () => {
  route.query = { tab: 'versions', state: '', offset: '0' }
  const version = { dataset_id: 'd', dataset_version_id: 'v', version_number: 1, display_name: '数据集', task_type: 'detection', metadata: {}, split_counts: {}, sample_count: 1, object_count: 1, category_count: 1 }
  api.listDatasetVersionPage.mockResolvedValueOnce({ total: 1, items: [version] })
  let finish!: (value: unknown) => void
  api.listDatasetVersionPage.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const wrapper = shallowMount(DatasetCatalogPage, { global: {
    plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })],
  } })
  await flushPromises()
  wrapper.findAllComponents(SelectField).at(-1)!.vm.$emit('update:modelValue', 'missing')
  await flushPromises()
  expect(wrapper.findComponent({ name: 'ResourceTable' }).attributes('inert')).toBeDefined()
  finish({ total: 0, items: [] })
  await flushPromises()
  wrapper.unmount()
})

it('刷新失败保留同一查询结果并提示可以重试', async () => {
  route.query = { tab: 'versions', state: '', offset: '0' }
  api.listDatasetVersionPage.mockResolvedValueOnce({ total: 1, items: [{ dataset_id: 'd', dataset_version_id: 'v', version_number: 1, display_name: '上次数据', task_type: 'detection', metadata: {}, split_counts: {}, sample_count: 1, category_count: 1 }] })
  api.listDatasetVersionPage.mockRejectedValueOnce(new Error('offline'))
  const wrapper = shallowMount(DatasetCatalogPage, { global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })], stubs: { ResourceTable: { template: '<table><slot /></table>' } } } })
  await flushPromises()
  wrapper.findAllComponents(Button)[1].vm.$emit('click')
  await flushPromises()
  expect(wrapper.text()).toContain('上次数据')
  expect(wrapper.text()).toContain('刷新失败，当前显示上次加载的数据')
  expect(wrapper.find('.dataset-stale-warning').exists()).toBe(true)
  wrapper.unmount()
})

it('筛选请求失败时不把旧查询结果显示为新筛选结果', async () => {
  route.query = { tab: 'versions', state: '', offset: '0' }
  api.listDatasetVersionPage.mockResolvedValueOnce({ total: 1, items: [{ dataset_id: 'd', dataset_version_id: 'v', version_number: 1, display_name: '旧筛选数据', task_type: 'detection', metadata: {}, split_counts: {}, sample_count: 1, category_count: 1 }] })
  api.listDatasetVersionPage.mockRejectedValueOnce(new Error('offline'))
  const wrapper = shallowMount(DatasetCatalogPage, { global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })], stubs: { ResourceTable: { template: '<table><slot /></table>' } } } })
  await flushPromises()
  wrapper.findAllComponents(SelectField).at(-1)!.vm.$emit('update:modelValue', 'missing')
  await flushPromises()
  expect(wrapper.text()).not.toContain('旧筛选数据')
  expect(wrapper.findComponent({ name: 'InlineError' }).exists()).toBe(true)
  wrapper.unmount()
})
