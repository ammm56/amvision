import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { i18n } from '@/platform/i18n'
import type { WorkflowGraphNote } from '../types'
import WorkflowNoteDetailPanel from './WorkflowNoteDetailPanel.vue'

function createLockedNote(): WorkflowGraphNote {
  return {
    note_id: 'note-1',
    title: '操作说明',
    content: '检查输入',
    content_format: 'markdown',
    rect: { x: 10, y: 20, width: 420, height: 260 },
    tone: 'info',
    collapsed: false,
    locked: true,
    metadata: {},
  }
}

describe('WorkflowNoteDetailPanel', () => {
  it('锁定说明后禁用属性编辑并保留解锁按钮', async () => {
    const wrapper = mount(WorkflowNoteDetailPanel, {
      global: { plugins: [i18n] },
      props: { note: createLockedNote() },
    })

    expect(wrapper.get('input').attributes('disabled')).toBeDefined()
    expect(wrapper.get('textarea').attributes('disabled')).toBeDefined()
    expect(wrapper.get('select').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.workflow-note-detail-panel__boundary').text()).toContain('不参与 Workflow 执行')

    const actionButtons = wrapper.findAll('.workflow-note-detail-panel__actions button')
    await actionButtons[1]!.trigger('click')
    expect(wrapper.emitted('toggleLocked')).toHaveLength(1)
  })
})
