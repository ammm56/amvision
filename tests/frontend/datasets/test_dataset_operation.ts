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
    query: { task: 'done' },
  }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  onBeforeRouteLeave: vi.fn(),
  onBeforeRouteUpdate: vi.fn(),
}))
afterEach(() => {
  vi.resetAllMocks()
  history.replaceState({}, '')
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
