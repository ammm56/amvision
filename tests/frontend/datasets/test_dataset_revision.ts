import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { defineComponent } from 'vue'
import DatasetRevisionPage from '../../../frontend/web-ui/src/modules/datasets/pages/DatasetRevisionPage.vue'
const api = vi.hoisted(() => ({
  getDatasetWorkspace: vi.fn(),
  getDatasetSelectionSummary: vi.fn(),
  getDatasetJob: vi.fn(),
  submitDatasetJob: vi.fn(),
  findDatasetJob: vi.fn(),
  cancelDatasetJob: vi.fn(),
  submitDatasetImport: vi.fn(),
  push: vi.fn(),
  replace: vi.fn(),
  leave: vi.fn(),
}))
vi.mock(
  '../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service',
  () => api,
)
vi.mock(
  '../../../frontend/web-ui/src/modules/datasets/services/dataset.service',
  () => api,
)
vi.mock('../../../frontend/web-ui/src/app/stores/session.store', () => ({
  useSessionStore: () => ({ hasScopes: () => true, bootstrap: {} }),
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { datasetId: 'd', versionId: 'v' }, query: {} }),
  useRouter: () => ({ push: api.push, replace: api.replace }),
  onBeforeRouteLeave: api.leave,
  onBeforeRouteUpdate: vi.fn(),
}))
afterEach(() => {
  vi.resetAllMocks()
  history.replaceState({}, '')
})
async function create(removed = 1, revision = 'abc') {
  history.replaceState(
    {
      datasetSelection: {
        version: 'v',
        revision,
        selection: { mode: 'ids', sample_ids: ['s'] },
      },
    },
    '',
  )
  api.getDatasetWorkspace.mockResolvedValue({
    dataset_id: 'd',
    dataset_version_id: 'v',
    project_id: 'p',
    task_type: 'detection',
    dataset: { display_name: '测试' },
    sample_count: 2,
    version_number: 1,
    metadata: { content_revision: 'abc' },
  })
  api.getDatasetSelectionSummary.mockResolvedValue({ sample_count: removed })
  const wrapper = shallowMount(DatasetRevisionPage, {
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })],
      renderStubDefaultSlot: true,
      stubs: {
        Button: defineComponent({
          props: ['disabled'],
          template: '<button :disabled="disabled"><slot /></button>',
        }),
      },
    },
  })
  await flushPromises()
  return wrapper
}
it('删除选择只在确认后更新当前版本任务，草稿离开需要确认', async () => {
  const w = await create()
  expect(api.submitDatasetJob).not.toHaveBeenCalled()
  const guard = api.leave.mock.calls[0][0]
  const leaving = guard()
  await flushPromises()
  w.findComponent({ name: 'ConfirmDialog' }).vm.$emit('cancel')
  expect(await leaving).toBe(false)
  api.submitDatasetJob.mockResolvedValue({ task_id: 't' })
  api.getDatasetJob.mockResolvedValue({
    task_id: 't',
    operation: 'revise',
    state: 'succeeded',
    result: { updated_version_id: 'v' },
  })
  await w
    .findAll('button')
    .find((b) => b.text() === '保存修改')!
    .trigger('click')
  await flushPromises()
  expect(api.submitDatasetJob.mock.calls[0][2]).toMatchObject({
    operation: 'revise',
    expected_content_revision: 'abc',
    config: { exclude_selection: { mode: 'ids', sample_ids: ['s'] } },
  })
  expect(api.submitDatasetImport).not.toHaveBeenCalled()
  expect(
    w.findComponent({ name: 'DatasetJobResult' }).props('job').result
      .updated_version_id,
  ).toBe('v')
  w.unmount()
})
it('删除全部时阻止空版本，添加 ZIP 后允许一次合并发布', async () => {
  const w = await create(2)
  expect(
    w
      .findAll('button')
      .find((b) => b.text() === '保存修改')!
      .attributes('disabled'),
  ).toBeDefined()
  const zip = new File(['zip'], 'new.zip', { type: 'application/zip' })
  w.findComponent({ name: 'FilePicker' }).vm.$emit('update:modelValue', zip)
  await flushPromises()
  api.submitDatasetImport.mockResolvedValue({ dataset_import_id: 'i' })
  await w
    .findAll('button')
    .find((b) => b.text() === '保存修改')!
    .trigger('click')
  await flushPromises()
  expect(api.submitDatasetImport.mock.calls[0][0]).toMatchObject({
    baseVersionId: 'v',
    expectedContentRevision: 'abc',
    datasetId: 'd',
    packageFile: zip,
    excludeSelection: { mode: 'ids', sample_ids: ['s'] },
  })
  expect(api.push).toHaveBeenCalledWith('/datasets/imports/i')
  expect(api.submitDatasetJob).not.toHaveBeenCalled()
  w.unmount()
})
it('旧选择对应的内容已更新时，不能按过期范围保存样本修改', async () => {
  const w = await create(1, 'old-revision')
  expect(api.getDatasetSelectionSummary).not.toHaveBeenCalled()
  expect(w.findComponent({ name: 'InlineError' }).props('message')).toContain(
    '重新选择样本',
  )
  expect(
    w
      .findAll('button')
      .find((b) => b.text() === '保存修改')!
      .attributes('disabled'),
  ).toBeDefined()
  expect(api.submitDatasetJob).not.toHaveBeenCalled()
  w.unmount()
})
it('首次读取失败可原页重试，恢复删除草稿而不自动提交', async () => {
  api.getDatasetWorkspace.mockRejectedValueOnce(
    new Error('temporarily unavailable'),
  )
  const w = await create()
  await w
    .findAll('button')
    .find((b) => b.text() === '重试')!
    .trigger('click')
  await flushPromises()
  expect(w.text()).toContain('删除样本')
  expect(api.getDatasetSelectionSummary).toHaveBeenCalledTimes(1)
  expect(api.submitDatasetJob).not.toHaveBeenCalled()
  w.unmount()
})

it('删除范围未能读取时不能上传并隐式删除，重试后才显示保存', async () => {
  api.getDatasetSelectionSummary.mockRejectedValueOnce(new Error('offline'))
  const w = await create()
  expect(w.findComponent({ name: 'FilePicker' }).exists()).toBe(false)
  expect(w.findAll('button').some(b => b.text() === '保存修改')).toBe(false)
  await w.findAll('button').find(b => b.text() === '重试')!.trigger('click')
  await flushPromises()
  expect(w.text()).toContain('删除所选样本')
  expect(w.findAll('button').find(b => b.text() === '保存修改')?.attributes('disabled')).toBeUndefined()
  expect(api.submitDatasetJob).not.toHaveBeenCalled()
  w.unmount()
})
