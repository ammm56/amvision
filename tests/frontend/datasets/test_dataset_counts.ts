import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { useDatasetCounts } from '../../../frontend/web-ui/src/modules/datasets/dataset-counts'

function setup() {
  let counts!: ReturnType<typeof useDatasetCounts>
  const wrapper = mount({
    setup() { counts = useDatasetCounts(); return () => null },
  }, {
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })] },
  })
  return { counts, wrapper }
}

it('未知统计不冒充零，真实零值仍有单位与可读提示', () => {
  const { counts, wrapper } = setup()
  expect(counts.sampleCounts(undefined, null)).toEqual([])
  expect(counts.sampleCounts(0, 0).map(item => item.label)).toEqual(['样本：0 张', '类别：0 类'])
  expect(counts.sampleColumns(1174, 3).map(item => item.summary).join(' / ')).toBe('1,174 张 / 3 类')
  expect(counts.sampleColumns(undefined, 3).map(item => item.summary).join(' / ')).toBe('— / 3 类')
  expect(counts.countItems('samples', Number.NaN)).toEqual([])
  expect(counts.countItems('samples', -1)).toEqual([])
  expect(counts.sampleColumns(undefined, 3).map(({ key, count }) => ({ key, count }))).toEqual([
    { key: 'samples', count: null }, { key: 'classes', count: 3 },
  ])
  wrapper.unmount()
})

it('划分固定按训练、测试、验证顺序显示，未提供整组统计时不伪造值', () => {
  const { counts, wrapper } = setup()
  expect(counts.splitColumns({ val: 118, train: 939, test: 117 }).map(({ key, count }) => ({ key, count }))).toEqual([
    { key: 'train', count: 939 },
    { key: 'test', count: 117 },
    { key: 'val', count: 118 },
  ])
  expect(counts.splitCounts(undefined)).toEqual([])
  expect(counts.splitColumns({ val: 118, train: 939, test: 117 }).map(item => item.summary).join(' / ')).toBe('train 939 / test 117 / val 118')
  expect(counts.splitColumns(undefined).map(item => item.count)).toEqual([null, null, null])
  expect(counts.splitColumns({ train: 5 }).map(item => item.count)).toEqual([5, 0, 0])
  wrapper.unmount()
})
