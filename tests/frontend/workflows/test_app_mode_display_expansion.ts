import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import { i18n, setI18nLocale } from '@/platform/i18n'
import WorkflowAppModeDisplayGrid from '@/workflows/workflow-editor/components/WorkflowAppModeDisplayGrid.vue'
import WorkflowPreviewTableViewer from '@/workflows/workflow-editor/components/WorkflowPreviewTableViewer.vue'
import type { PreviewNodeDisplay } from '@/workflows/workflow-editor/preview/useWorkflowPreviewDisplays'

const config = {
  format_id: 'amvision.workflow-app-mode.v1' as const,
  title: '',
  displays: [{ node_id: 'table', output_port: 'body', title: 'Measurements', size: 'large' as const }],
}

function table(prefix: string): PreviewNodeDisplay {
  return {
    nodeId: 'table', nodeTypeId: 'core.io.table-preview', outputName: 'body',
    title: 'Measurements', kind: 'table', payload: {}, statusText: '', formattedValue: '',
    image: null, galleryItems: [], columns: [{ key: 'item', label: 'Item' }],
    rows: Array.from({ length: 50 }, (_, index) => ({ item: `${prefix}-${index + 1}` })),
    rowCount: 50, emptyText: null,
  }
}

beforeEach(() => setI18nLocale('zh-CN'))

describe('App Mode display expansion', () => {
  it('opens all rows through the existing viewer, including the last measurement', async () => {
    const current = table('A')
    const wrapper = mount(WorkflowAppModeDisplayGrid, {
      props: { config, displays: { '["table","body"]': current }, nodeTitles: {}, hasRun: true },
      global: { plugins: [i18n] },
    })
    expect(wrapper.text()).not.toContain('A-50')
    const button = wrapper.get('button[aria-label="展开 Measurements"]')
    expect(button.attributes('title')).toBe('展开 Measurements')
    await button.trigger('click')
    const opened = wrapper.emitted('openDisplay')![0]![0] as PreviewNodeDisplay
    expect(opened.rows).toEqual(current.rows)
    const viewer = mount(WorkflowPreviewTableViewer, {
      props: { open: true, table: opened },
      global: { plugins: [i18n], stubs: { Teleport: true } },
    })
    expect(viewer.text()).toContain('A-50')
    expect(viewer.text()).toContain('50')
    viewer.unmount()
    wrapper.unmount()
  })

  it('opens the current result and removes the action after its output is cleared', async () => {
    const wrapper = mount(WorkflowAppModeDisplayGrid, {
      props: { config, displays: {}, nodeTitles: {}, hasRun: false },
      global: { plugins: [i18n] },
    })
    expect(wrapper.find('button').exists()).toBe(false)
    for (const prefix of ['A', 'B']) {
      await wrapper.setProps({ displays: { '["table","body"]': table(prefix) }, hasRun: true })
      await wrapper.get('button').trigger('click')
      const last = wrapper.emitted('openDisplay')!.at(-1)![0] as PreviewNodeDisplay
      expect(last.rows[49]).toEqual({ item: `${prefix}-50` })
    }
    await wrapper.setProps({ displays: {} })
    expect(wrapper.find('button').exists()).toBe(false)
    expect(wrapper.text()).toContain('本次执行没有此输出')
    expect(wrapper.emitted('openDisplay')).toHaveLength(2)
    wrapper.unmount()
  })
})
