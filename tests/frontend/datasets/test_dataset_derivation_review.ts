import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import DatasetDerivationReview from '../../../frontend/web-ui/src/modules/datasets/components/DatasetDerivationReview.vue'

function review(result: Record<string, unknown>) {
  return mount(DatasetDerivationReview, {
    props: { sourceName: '测试', sourceNumber: 1, job: {
      task_id: 'check', operation: 'derive-check', state: 'succeeded', created_at: '', finished_at: null,
      error_message: null, progress: {}, result,
    } },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })] },
  })
}

it('样本与对象分别对照，删除类别标注不会伪装成删除样本', () => {
  const wrapper = review({ sample_count: 10, source_count: 10, object_count: 12, source_object_count: 20,
    category_count: 1, source_category_count: 2, excluded_count: 0,
    source_split_counts: { train: 10 }, split_counts: { train: 8, val: 2 },
    source_split_object_counts: { train: 20 }, split_object_counts: { train: 9, val: 3 },
    category_changes: [{ category_id: 1, before: 'nut', after: null }],
    group_integrity: 'not_configured', duplicate_check: 'passed', cross_split_duplicate_count: 0,
  })
  const train = wrapper.find('table[aria-label="划分变更"] tbody tr').text()
  expect(train).toContain('− 2')
  expect(train).toContain('− 11')
  expect(wrapper.text()).toContain('排除标注，保留样本')
  expect(wrapper.text()).not.toContain('分组完整性')
  expect(wrapper.text()).not.toContain('同组样本未跨划分。')
  wrapper.unmount()
})

it('旧报告缺少对象或重复检查数据时显示未知，不补造零值或通过', () => {
  const wrapper = review({ sample_count: 10, source_count: 10, source_split_counts: { train: 10 }, split_counts: { train: 10 } })
  expect(wrapper.text()).toContain('此历史报告未记录重复检查结果。')
  expect(wrapper.find('table[aria-label="划分变更"] tbody tr').text()).toContain('———')
  wrapper.unmount()
})

it('读取失败和重复候选显示实际结果，预检查不声称版本已创建', () => {
  const wrapper = review({ can_create: false, duplicate_check: 'incomplete', unreadable_count: 2, cross_split_duplicate_count: 3 })
  expect(wrapper.text()).toContain('预检查未通过')
  expect(wrapper.text()).toContain('2 个样本无法读取')
  expect(wrapper.text()).not.toContain('新版本创建成功')
  wrapper.unmount()
})
