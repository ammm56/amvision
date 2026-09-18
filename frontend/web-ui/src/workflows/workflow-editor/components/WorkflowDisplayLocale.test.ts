import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import { defaultLocale, setI18nLocale } from '@/platform/i18n'
import { workflowDisplayMessages } from '@/platform/i18n/workflow-display'
import WorkflowValueDisplay from './WorkflowValueDisplay.vue'
import WorkflowParameterRowsEditor from './WorkflowParameterRowsEditor.vue'
import WorkflowDisplayAppearance from './WorkflowDisplayAppearance.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'

afterEach(() => setI18nLocale(defaultLocale))

describe('Workflow display language switching', () => {
  it('updates existing overlays and open editors without changing data or draft', async () => {
    const payload = { fields: [{ label: '客户标签', value: 'custom-ok', format: 'status' }] }
    const display = mount(WorkflowValueDisplay, { props: { payload, overlay: true } })
    const rows = mount(WorkflowParameterRowsEditor, { props: { label: 'Reducers', schema: {}, modelValue: [] } })
    const appearance = mount(WorkflowDisplayAppearance, { props: { modelValue: { font_size: 24 } } })
    await rows.get('button').trigger('click')
    await appearance.get('.appearance-summary').trigger('click')
    try {
      for (const locale of ['en-US', 'zh-CN', 'ja-JP', 'ko-KR'] as const) {
        setI18nLocale(locale); await nextTick()
        const words = workflowDisplayMessages[locale]
        expect(display.get('button').text()).toBe(words.collapse)
        await display.get('button').trigger('click')
        expect(display.get('button').text()).toBe(words.expand)
        await display.get('button').trigger('click')
        expect(display.text()).toContain('客户标签')
        expect(display.text()).toContain('custom-ok')
        for (const editor of [rows, appearance]) {
          expect(editor.getComponent(ConfirmDialog).props('confirmLabel')).toBe(words.apply)
          expect(editor.getComponent(ConfirmDialog).props('cancelLabel')).toBe(words.cancel)
        }
        expect(appearance.getComponent(WorkflowValueDisplay).props('payload')).toMatchObject({ appearance: { font_size: 24 } })
      }
      expect(appearance.emitted('update:modelValue')).toBeUndefined()
      expect(rows.emitted('update:modelValue')).toBeUndefined()
    } finally {
      display.unmount(); rows.unmount(); appearance.unmount()
    }
  })
})
