import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import DatasetOperationPage from '../../../frontend/web-ui/src/modules/datasets/pages/DatasetOperationPage.vue'

const api = vi.hoisted(() => ({
  getDatasetWorkspace: vi.fn(),
  getDatasetSelectionSummary: vi.fn(),
  getDatasetJob: vi.fn(),
  submitDatasetJob: vi.fn(),
  findDatasetJob: vi.fn(),
  cancelDatasetJob: vi.fn(),
  listDatasetVersionPage: vi.fn(),
}))
const routeState = vi.hoisted(() => ({ query: { task: 'done' } as Record<string, string> }))
vi.mock(
  '../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service',
  () => api,
)
vi.mock('../../../frontend/web-ui/src/app/stores/session.store', () => ({
  useSessionStore: () => ({ hasScopes: () => true }),
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({
    params: { datasetId: 'd', versionId: 'v', operation: 'derive' },
    query: routeState.query,
  }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  onBeforeRouteLeave: vi.fn(),
  onBeforeRouteUpdate: vi.fn(),
}))
afterEach(() => {
  vi.resetAllMocks()
  routeState.query = { task: 'done' }
  history.replaceState({}, '')
})

it('重新划分始终按样本提交，不显示或携带分组字段', async () => {
  history.replaceState({}, '')
  routeState.query = {}
  api.getDatasetWorkspace.mockResolvedValue({ dataset: { display_name: '测试' }, metadata: {}, categories: [], version_number: 1, sample_count: 8 })
  api.submitDatasetJob.mockResolvedValue({ task_id: 'new-check' })
  api.getDatasetJob.mockResolvedValue({ task_id: 'new-check', operation: 'derive-check', state: 'succeeded', result: {} })
  const wrapper = shallowMount(DatasetOperationPage, { global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })] } })
  await flushPromises()
  await wrapper.findAll('input[name="partition"]')[1].setValue(true)
  expect(wrapper.text()).not.toContain('分组字段')
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  expect(api.submitDatasetJob).toHaveBeenCalledWith('d', 'v', expect.objectContaining({ operation: 'derive-check', config: expect.objectContaining({ group_key: '', split_ratios: [80, 20, 0] }) }))
  wrapper.unmount()
})

it('历史分组预检查不能直接作为按样本创建的凭据', async () => {
  api.getDatasetWorkspace.mockResolvedValue({ dataset: { display_name: '测试' }, metadata: {}, categories: [], version_number: 1, sample_count: 8 })
  api.getDatasetJob.mockResolvedValue({ task_id: 'done', operation: 'derive-check', state: 'succeeded', config: { group_key: 'capture_group', split_ratios: [80, 20, 0] }, result: {} })
  const wrapper = shallowMount(DatasetOperationPage, { global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })] } })
  await flushPromises()
  const create = wrapper.findAllComponents({ name: 'Button' }).find(button => button.props('variant') === 'primary')!
  create.vm.$emit('click')
  await flushPromises()
  expect(api.submitDatasetJob).not.toHaveBeenCalled()
  expect(wrapper.findComponent({ name: 'InlineError' }).props('message')).toBe('配置已修改，请重新检查。')
  wrapper.unmount()
})

it('源版本已更新且旧样本已删除，仍可查看已完成任务的原始结果', async () => {
  history.replaceState(
    {
      datasetSelection: {
        version: 'v',
        revision: 'old',
        selection: { mode: 'ids', sample_ids: ['deleted'] },
      },
    },
    '',
  )
  api.getDatasetWorkspace.mockResolvedValue({
    dataset: { display_name: '测试' },
    metadata: { content_revision: 'new' },
    categories: [],
    version_number: 1,
    sample_count: 8,
  })
  const job = {
    task_id: 'done',
    operation: 'derive',
    state: 'succeeded',
    config: { selection: { mode: 'ids', sample_ids: ['deleted'] } },
    result: { sample_count: 1, created_version_id: 'v2' },
  }
  api.getDatasetJob.mockResolvedValue(job)
  api.getDatasetSelectionSummary.mockRejectedValue(new Error('sample removed'))
  const wrapper = shallowMount(DatasetOperationPage, {
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })],
    },
  })
  await flushPromises()
  expect(api.getDatasetJob).toHaveBeenCalledWith('d', 'v', 'done')
  expect(api.getDatasetSelectionSummary).not.toHaveBeenCalled()
  expect(wrapper.findComponent({ name: 'InlineError' }).exists()).toBe(false)
  expect(
    wrapper.findComponent({ name: 'DatasetJobResult' }).props('job'),
  ).toEqual(job)
  expect(api.submitDatasetJob).not.toHaveBeenCalled()
  wrapper.unmount()
})
