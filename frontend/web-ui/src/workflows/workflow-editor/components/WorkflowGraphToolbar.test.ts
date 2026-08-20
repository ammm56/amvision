import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'

import { i18n, setI18nLocale } from '@/platform/i18n'
import WorkflowGraphToolbar from './WorkflowGraphToolbar.vue'

function mountToolbar(inspectorCollapsed = false) {
  return mount(WorkflowGraphToolbar, {
    global: {
      plugins: [i18n],
    },
    props: {
      editorTitle: '新建应用',
      titleDraft: '新建应用',
      titleEditing: false,
      titleSaving: false,
      titleEditable: true,
      runtimeState: null,
      statusMessage: null,
      loading: false,
      previewDisabled: false,
      previewing: false,
      publishDisabled: false,
      publishing: false,
      saveDisabled: false,
      saving: false,
      groupCreateMode: false,
      inspectorCollapsed,
    },
  })
}

describe('WorkflowGraphToolbar', () => {
  beforeEach(() => {
    setI18nLocale('zh-CN')
  })

  it('uses compact Chinese labels in a canvas toolbar', () => {
    const wrapper = mountToolbar()
    const labels = wrapper.findAll('button').map((button) => button.text().trim())

    expect(wrapper.element.tagName).toBe('DIV')
    expect(wrapper.attributes('role')).toBe('toolbar')
    expect(wrapper.get('h1').text()).toBe('新建应用')
    expect(labels).toEqual(expect.arrayContaining(['节点组', '刷新', '预览', '发布', '属性面板', '保存']))
    expect(wrapper.text()).not.toContain('Preview Run')
    expect(wrapper.text()).not.toContain('保存应用')
  })

  it('toggles the inspector from the floating action group', async () => {
    const wrapper = mountToolbar(true)
    const inspectorButton = wrapper.get('.workflow-graph-toolbar__inspector-action')

    expect(inspectorButton.attributes('aria-pressed')).toBe('false')
    await inspectorButton.trigger('click')
    expect(wrapper.emitted('toggleInspector')).toHaveLength(1)
  })
})
