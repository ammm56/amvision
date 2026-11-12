import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { expect, it } from 'vitest'
import DatasetJobResult from '../../../frontend/web-ui/src/modules/datasets/components/DatasetJobResult.vue'
import type { DatasetJob } from '../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service'

it.each(['zh-CN', 'en'])('比较结果显示原始附件及媒体字段变化，正确定位目标版本 %s', async locale => {
  const kinds = ['cloud', 'depth', 'mask', 'calibration', 'media_metadata']
  const page = mount(DatasetJobResult, {
    props: { job: {
      task_id: 'compare', operation: 'compare', state: 'succeeded',
      created_at: '2026-11-12T00:00:00Z', finished_at: '2026-11-12T00:00:01Z',
      error_message: null, progress: { percent: 100 },
      result: { compare_version_id: 'v2', counts: Object.fromEntries(kinds.map(k => [k, 1])),
        changes: [{ sample_id: 's2', file_name: 'part.ply', kinds }] },
    } as DatasetJob },
    global: { plugins: [createI18n({ legacy: false, locale, messages: {} })] },
  })
  try {
    const row = page.get('tbody tr')
    for (const word of locale === 'en'
      ? ['Source point cloud changed', 'Source depth changed', 'Source mask changed', 'Calibration changed', 'Units, calibration parameters']
      : ['原始点云变化', '原始深度变化', '原始掩膜变化', '标定资料变化', '单位、标定参数']) expect(row.text()).toContain(word)
    expect(page.text()).not.toContain('media_metadata')
    await row.get('button').trigger('click')
    expect(page.emitted('sample')).toEqual([['s2', 'v2']])
  } finally { page.unmount() }
})
