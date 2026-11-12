import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import DatasetVersionSelect from '../../../frontend/web-ui/src/modules/datasets/components/DatasetVersionSelect.vue'
import SelectField from '../../../frontend/web-ui/src/shared/ui/components/Select.vue'
import type { DatasetWorkspace } from '../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service'

const api = vi.hoisted(() => ({ listDatasetVersionPage: vi.fn() }))
vi.mock(
  '../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service',
  () => api,
)
afterEach(() => vi.clearAllMocks())
const workspace = {
  project_id: 'p',
  dataset_id: 'd',
  dataset_version_id: 'older',
  version_number: 2,
} as DatasetWorkspace
it('旧版本不在最近一页时保留选中值，并提供完整版本列表入口', async () => {
  api.listDatasetVersionPage.mockResolvedValue({
    items: [{ ...workspace, dataset_version_id: 'new', version_number: 103 }],
    total: 103,
  })
  const wrapper = shallowMount(DatasetVersionSelect, {
    props: { workspace },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })],
    },
  })
  await flushPromises()
  const select = wrapper.findComponent(SelectField)
  expect(select.props('options')).toEqual([
    { value: 'older', label: 'v2' },
    { value: 'new', label: 'v103' },
    { value: '__more__', label: '数据集版本' },
  ])
  select.vm.$emit('update:modelValue', '__more__')
  expect(wrapper.emitted('more')).toHaveLength(1)
  expect(wrapper.emitted('change')).toBeUndefined()
  select.vm.$emit('update:modelValue', 'new')
  expect(wrapper.emitted('change')).toEqual([['new']])
  await wrapper.setProps({ workspace: { ...workspace, dataset_version_id: 'new', version_number: 103 } })
  await flushPromises()
  expect(api.listDatasetVersionPage).toHaveBeenCalledTimes(1)
  expect(select.props('disabled')).toBe(false)
  wrapper.unmount()
})
it('版本切换后迟到的列表不能覆盖当前数据集', async () => {
  let finish!: (value: unknown) => void
  api.listDatasetVersionPage.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve
      }),
  )
  api.listDatasetVersionPage.mockResolvedValueOnce({
    items: [
      {
        ...workspace,
        dataset_id: 'other',
        dataset_version_id: 'other-v1',
        version_number: 1,
      },
    ],
    total: 1,
  })
  const wrapper = shallowMount(DatasetVersionSelect, {
    props: { workspace },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })],
    },
  })
  await wrapper.setProps({
    workspace: {
      ...workspace,
      dataset_id: 'other',
      dataset_version_id: 'other-v1',
      version_number: 1,
    },
  })
  await flushPromises()
  finish({
    items: [{ ...workspace, dataset_version_id: 'wrong', version_number: 99 }],
    total: 1,
  })
  await flushPromises()
  expect(wrapper.findComponent(SelectField).props('options')).toEqual([
    { value: 'other-v1', label: 'v1' },
  ])
  wrapper.unmount()
})
