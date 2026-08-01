import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'

import { i18n, setI18nLocale } from '@/platform/i18n'
import WorkflowGraphViewportControls from './WorkflowGraphViewportControls.vue'

describe('WorkflowGraphViewportControls', () => {
  beforeEach(() => setI18nLocale('zh-CN'))

  it('显示当前缩放比例和 Minimap 状态', () => {
    const wrapper = mount(WorkflowGraphViewportControls, {
      global: { plugins: [i18n] },
      props: { scalePercent: 85, minimapVisible: true },
    })

    expect(wrapper.attributes('role')).toBe('toolbar')
    expect(wrapper.get('.workflow-graph-viewport-controls__scale').text()).toBe('85%')
    expect(wrapper.get('.workflow-graph-viewport-controls__minimap').attributes('aria-pressed')).toBe('true')
  })

  it('发送缩放、适配和 Minimap 操作', async () => {
    const wrapper = mount(WorkflowGraphViewportControls, {
      global: { plugins: [i18n] },
      props: { scalePercent: 100, minimapVisible: false },
    })

    const buttons = wrapper.findAll('button')
    await buttons[0]?.trigger('click')
    await buttons[1]?.trigger('click')
    await buttons[2]?.trigger('click')
    await buttons[3]?.trigger('click')
    await buttons[4]?.trigger('click')

    expect(wrapper.emitted('zoomOut')).toHaveLength(1)
    expect(wrapper.emitted('resetView')).toHaveLength(1)
    expect(wrapper.emitted('zoomIn')).toHaveLength(1)
    expect(wrapper.emitted('fitView')).toHaveLength(1)
    expect(wrapper.emitted('toggleMinimap')).toHaveLength(1)
  })
})
