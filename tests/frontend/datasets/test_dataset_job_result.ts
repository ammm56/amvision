import { expect, it } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import DatasetJobResult from '../../../frontend/web-ui/src/modules/datasets/components/DatasetJobResult.vue'
import Button from '../../../frontend/web-ui/src/shared/ui/components/Button.vue'

it('创建成功使用完成摘要，零划分保留，查看按钮指向结果版本', () => {
  const w = shallowMount(DatasetJobResult, {
    props: { sourceName: '验收数据集', sourceNumber: 9, job: {
      operation: 'derive', state: 'succeeded', created_at: null,
      result: { created_version_id: 'new-v10', source_count: 6, sample_count: 6,
        excluded_count: 0, split_changed: 0, group_count: 6, group_key: '', split_counts: { train: 5, val: 1 } },
    } as any },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })], renderStubDefaultSlot: true },
  })
  expect(w.text()).toContain('版本已创建')
  expect(w.text()).toContain('来源版本 v9')
  expect(w.text()).toContain('train 5 / test 0 / val 1')
  expect(w.text()).not.toContain('分组数量')
  w.findComponent(Button).vm.$emit('click')
  expect(w.emitted('version')).toEqual([['new-v10']])
  w.unmount()
})
