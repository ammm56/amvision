import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ModelPackageExportResult from './ModelPackageExportResult.vue'
import type { ModelPackageRecord } from '../services/model-package.service'

const sha256 = '0123456789abcdef'.repeat(4)
const record: ModelPackageRecord = {
  operation_id: 'export-1',
  direction: 'export',
  state: 'completed',
  created_at: '2026-11-21T11:35:22Z',
  updated_at: '2026-11-21T11:35:24Z',
  file_name: '检测模型-v1.zip',
  model: { model_name: '检测模型', model_type: 'yolo11', task_type: 'detection', model_scale: 's' },
  export_options: { model_version_id: 'model-version-1', include_checkpoint: true, build_ids: [], file_name: '检测模型-v1.zip' },
  files: [{ path: 'best-checkpoint.pt', owner: 'checkpoint', byte_size: 2048, sha256 }],
}

describe('ModelPackageExportResult', () => {
  it('keeps the generation status visible without a closing hint', () => {
    const wrapper = mount(ModelPackageExportResult, {
      props: { record: { ...record, state: 'running', files: [] }, zh: true, closeLabel: '关闭', busy: false },
    })
    expect(wrapper.text()).toContain('任务状态')
    expect(wrapper.text()).not.toContain('关闭面板不会取消生成')
    wrapper.unmount()
  })

  it('shows the model type and reveals and copies the full checksum', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    const clipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    const wrapper = mount(ModelPackageExportResult, {
      props: { record, zh: true, closeLabel: '关闭', busy: false },
      attachTo: document.body,
    })

    try {
      expect(wrapper.text()).toContain('模型类型YOLO11')
      const row = wrapper.get('tbody tr')
      expect(row.text()).not.toContain(sha256.slice(0, 12))
      const trigger = row.get('button[aria-label="查看 SHA256"]')
      await trigger.trigger('pointermove', { pointerType: 'mouse' })
      await vi.waitFor(() => expect(document.querySelector('.model-file-checksum code')?.textContent).toBe(sha256))
      await trigger.trigger('keydown', { key: 'Escape' })
      expect(document.querySelector('.model-file-checksum')).toBeNull()

      await row.get('button[aria-label="复制 SHA-256"]').trigger('click')
      await flushPromises()
      expect(writeText).toHaveBeenCalledWith(sha256)
      expect(wrapper.get('[role="status"]').text()).toBe('已复制 SHA-256')
    } finally {
      wrapper.unmount()
      if (clipboard) Object.defineProperty(navigator, 'clipboard', clipboard)
      else Reflect.deleteProperty(navigator, 'clipboard')
    }
  })
})
