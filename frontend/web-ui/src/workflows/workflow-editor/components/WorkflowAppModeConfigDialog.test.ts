import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { i18n } from '@/platform/i18n'
import WorkflowAppModeConfigDialog from './WorkflowAppModeConfigDialog.vue'

const candidates = [
  { node_id: 'preview-1', output_port: 'body', title: 'Node', size: 'medium' as const, node_title: 'Image Preview', output_title: 'Body' },
  { node_id: 'preview-2', output_port: 'body', title: 'Node', size: 'medium' as const, node_title: 'Value Preview', output_title: 'Body' },
]

describe('WorkflowAppModeConfigDialog', () => {
  it('新候选项使用 Node 作为真实默认标题', () => {
    const wrapper = mount(WorkflowAppModeConfigDialog, {
      global: { plugins: [i18n] },
      props: { applicationTitle: 'Test', config: null, candidates },
    })

    const titleInputs = wrapper.findAll('.app-mode-dialog__row input[type="text"]')
    expect(titleInputs.map((input) => (input.element as HTMLInputElement).value)).toEqual(['Node', 'Node'])
    wrapper.unmount()
  })

  it('上下移动后按显式顺序提交显示项', async () => {
    const wrapper = mount(WorkflowAppModeConfigDialog, {
      global: { plugins: [i18n] },
      props: {
        applicationTitle: 'Test',
        candidates,
        config: {
          format_id: 'amvision.workflow-app-mode.v1',
          title: '',
          displays: candidates.map(({ node_title: _nodeTitle, output_title: _outputTitle, ...display }) => display),
        },
      },
    })

    await wrapper.findAll('.app-mode-dialog__order button')[1]?.trigger('click')
    await wrapper.get('footer .ui-button--primary').trigger('click')
    const applied = wrapper.emitted('apply')?.[0]?.[0] as { displays: Array<{ node_id: string }> }
    expect(applied.displays.map((display) => display.node_id)).toEqual(['preview-2', 'preview-1'])
    wrapper.unmount()
  })
})
