import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import { i18n } from '@/platform/i18n'
import type { WorkflowGraphNote } from '../types'
import WorkflowGraphNoteLayer from './WorkflowGraphNoteLayer.vue'

const renderMarkdownMock = vi.hoisted(() => vi.fn((content: string) => `<p>${content}</p>`))

vi.mock('../notes/workflowNoteMarkdown', () => ({
  renderWorkflowNoteMarkdown: renderMarkdownMock,
}))

function createNote(overrides: Partial<WorkflowGraphNote> = {}): WorkflowGraphNote {
  return {
    note_id: 'note-1',
    title: '操作说明',
    content: '检查输入',
    content_format: 'markdown',
    rect: { x: 10, y: 20, width: 420, height: 260 },
    tone: 'neutral',
    collapsed: false,
    locked: false,
    metadata: {},
    ...overrides,
  }
}

describe('WorkflowGraphNoteLayer', () => {
  it('只在正文变化时重新渲染 Markdown', async () => {
    renderMarkdownMock.mockClear()
    const note = createNote()
    const wrapper = mount(WorkflowGraphNoteLayer, {
      global: { plugins: [i18n] },
      props: { notes: [note], selectedNoteId: null, editingNoteId: null },
    })

    expect(renderMarkdownMock).toHaveBeenCalledTimes(1)
    await wrapper.setProps({ notes: [{ ...note, rect: { ...note.rect, x: 200 } }] })
    expect(renderMarkdownMock).toHaveBeenCalledTimes(1)

    await wrapper.setProps({ notes: [{ ...note, content: '确认结果' }] })
    expect(renderMarkdownMock).toHaveBeenCalledTimes(2)
    expect(wrapper.get('.workflow-graph-note__markdown').html()).toContain('确认结果')
  })

  it('锁定后保留选中和解锁入口，但不提供编辑、色调或缩放操作', () => {
    const wrapper = mount(WorkflowGraphNoteLayer, {
      global: { plugins: [i18n] },
      props: {
        notes: [createNote({ locked: true })],
        selectedNoteId: 'note-1',
        editingNoteId: null,
      },
    })

    expect(wrapper.get('.workflow-graph-note').classes()).toContain('is-selected')
    expect(wrapper.get('.ui-select__button').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.workflow-graph-note__resize').exists()).toBe(false)
  })

  it('使用统一自定义下拉菜单切换说明色调', async () => {
    const note = createNote()
    const wrapper = mount(WorkflowGraphNoteLayer, {
      global: { plugins: [i18n] },
      props: { notes: [note], selectedNoteId: null, editingNoteId: null },
    })

    expect(wrapper.find('select').exists()).toBe(false)
    await wrapper.get('.ui-select__button').trigger('click')
    expect(wrapper.findAll('.ui-select__option')).toHaveLength(5)

    await wrapper.findAll('.ui-select__option')[3]!.trigger('pointerdown')
    expect(wrapper.emitted('updateTone')?.[0]).toEqual([note, 'warning'])
    expect(wrapper.find('.ui-select__menu').exists()).toBe(false)
  })
})
