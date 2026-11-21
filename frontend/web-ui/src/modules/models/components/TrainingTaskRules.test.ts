import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { getDatasetExportManifest, getDatasetExportText, type DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import TrainingTaskRules from './TrainingTaskRules.vue'

vi.mock('vue-i18n', () => ({ useI18n: () => ({ locale: ref('zh-CN') }) }))
vi.mock('@/modules/datasets/services/dataset.service', () => ({
  getDatasetExportManifest: vi.fn(),
  getDatasetExportText: vi.fn(),
}))

function exportRecord(id: string, format: string): DatasetExportSummary {
  return { dataset_export_id: id, dataset_version_id: id + '-version', format_id: format, split_names: ['train', 'val'] } as DatasetExportSummary
}

it('renders the exported classification class IDs and names in their original order', async () => {
  const categories = ['slot_pcb_surface_full', 'slot_empty', 'slot_back_surface_full']
  const wrapper = mount(TrainingTaskRules, {
    props: {
      taskType: 'classification',
      datasetExport: { ...exportRecord('c', 'imagenet'), category_names: categories },
      workspace: null,
    },
  })

  const list = wrapper.get('ol[aria-label="类别顺序"]')
  expect(list.attributes('start')).toBe('0')
  expect(list.findAll('li').map(item => item.findAll('span').map(part => part.text()))).toEqual(
    categories.map((name, index) => [String(index), name]),
  )
  expect(wrapper.text()).toContain('Top-1 Accuracy')

  await wrapper.setProps({ datasetExport: null })
  expect(wrapper.find('ol').exists()).toBe(false)
  expect(wrapper.get('.training-task-rules__classes').text()).toBe('—')
  wrapper.unmount()
})

describe('pose training rules', () => {
  it('ignores an outdated YOLO definition and retries only the current export', async () => {
    let finishPrevious!: (value: Awaited<ReturnType<typeof getDatasetExportManifest>>) => void
    const read = vi.mocked(getDatasetExportManifest)
    read.mockImplementationOnce(() => new Promise(resolve => { finishPrevious = resolve }))
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ dataset_version_id: 'b-version', metadata: { kpt_shape: [21, 3] } })
    const wrapper = mount(TrainingTaskRules, { props: { taskType: 'pose', datasetExport: exportRecord('a', 'yolo-pose-v1'), workspace: null } })
    await wrapper.setProps({ datasetExport: exportRecord('b', 'yolo-pose-v1') })
    await flushPromises()
    expect(read.mock.calls[0][1]?.aborted).toBe(true)
    finishPrevious({ dataset_version_id: 'a-version', metadata: { kpt_shape: [8, 2] } })
    await flushPromises()
    expect(wrapper.text()).toContain('读取失败')
    expect(wrapper.text()).not.toContain('8 点')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(read).toHaveBeenLastCalledWith('b', expect.any(AbortSignal))
    expect(wrapper.text()).toContain('21 点 · x, y, v')
    wrapper.unmount()
  })

  it('reads the exported COCO categories and skips a truncated preview', async () => {
    const read = vi.mocked(getDatasetExportText)
    read.mockResolvedValueOnce({ path: 'annotations/person_keypoints_train.json', truncated: false, content: JSON.stringify({
      categories: [{ id: 1, name: 'part', keypoints: ['left', 'right'], skeleton: [[1, 2]] }],
    }) }).mockResolvedValueOnce({ path: 'annotations/person_keypoints_train.json', truncated: true, content: '{"categories":[' })
    const wrapper = mount(TrainingTaskRules, { props: { taskType: 'pose', datasetExport: exportRecord('c', 'coco-keypoints-v1'), workspace: null } })
    await flushPromises()
    expect(read).toHaveBeenCalledWith('c', 'annotations/person_keypoints_train.json', expect.any(AbortSignal))
    expect(wrapper.text()).toContain('2 点')
    expect(wrapper.get('details').text()).toContain('left、right')
    await wrapper.setProps({ datasetExport: exportRecord('d', 'coco-keypoints-v1') })
    await flushPromises()
    expect(wrapper.find('details').exists()).toBe(false)
    expect(wrapper.text()).toContain('暂无可显示的定义')
    wrapper.unmount()
  })
})
