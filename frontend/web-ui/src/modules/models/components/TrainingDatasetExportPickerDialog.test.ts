import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'
import type { DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import TrainingDatasetExportPickerDialog from './TrainingDatasetExportPickerDialog.vue'

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': {} } })
const exported: DatasetExportSummary = {
  dataset_id: 'dataset-id', dataset_version_id: 'version-id', dataset_export_id: 'export-v3',
  display_name: '零件检测', version_number: 3, project_id: 'project-id', format_id: 'coco-detection-v1',
  status: 'completed', task_type: 'detection', created_at: '2026-01-01T10:00:00Z', include_test_split: false,
  split_names: ['train', 'val'], sample_count: 16, category_names: ['bolt'], manifest_object_key: 'exports/manifest.json', metadata: {},
}

describe('training dataset export picker', () => {
  it('groups readable dataset names, searches versions and applies the original export identity', async () => {
    const second = { ...exported, dataset_export_id: 'export-v1', version_number: 1 }
    const incompatible = { ...exported, dataset_export_id: 'mismatch', dataset_id: 'other-dataset', display_name: '其他数据', format_id: 'yolo-detection-v1' }
    const wrapper = mount(TrainingDatasetExportPickerDialog, {
      props: { open: true, loading: false, namesLoading: false, namesError: false,
        title: '选择导出', closeLabel: '关闭', emptyTitle: '暂无导出', applyLabel: '用于训练', searchValue: '',
        exports: [exported, second, incompatible], selectedExportId: exported.dataset_export_id, supportedFormats: ['coco-detection-v1'] },
      global: { plugins: [i18n] },
    })
    try {
      expect(wrapper.findAll('.training-export-picker__dataset')).toHaveLength(2)
      expect(wrapper.text()).toContain('零件检测')
      expect(wrapper.text()).not.toContain('dataset-id')
      const apply = () => wrapper.findAll('button').find(button => button.text() === '用于训练')!
      await wrapper.setProps({ searchValue: 'v1' })
      expect(wrapper.findAll('input[type="radio"]')).toHaveLength(1)
      expect(wrapper.get<HTMLInputElement>('input[type="radio"]').element.checked).toBe(true)
      await apply().trigger('click')
      expect(wrapper.emitted('apply-export')).toEqual([[second]])
      await wrapper.setProps({ searchValue: '其他数据' })
      expect(wrapper.text()).toContain('格式不兼容')
      expect(apply().attributes('disabled')).toBeDefined()
    } finally {
      wrapper.unmount()
    }
  })
})
