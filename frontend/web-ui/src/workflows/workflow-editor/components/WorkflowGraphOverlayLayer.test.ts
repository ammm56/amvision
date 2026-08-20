import { shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'

import { i18n, setI18nLocale } from '@/platform/i18n'
import WorkflowGraphOverlayLayer from './WorkflowGraphOverlayLayer.vue'

function mountOverlay() {
  return shallowMount(WorkflowGraphOverlayLayer, {
    global: { plugins: [i18n] },
    props: {
      minimapVisible: true,
      viewportScalePercent: 100,
      minimapNodes: [],
      minimapViewportStyle: {},
      isMinimapNodeSelected: () => false,
      contextMenu: null,
      contextMenuStyle: {},
      saveDisabled: false,
      previewDisabled: false,
      nodePicker: null,
      nodePickerDefinitions: [],
      nodePickerTitle: 'Node Catalog',
      nodePickerRequiredPortDirection: null,
      nodePickerRequiredPayloadTypeId: null,
      nodeCount: 1,
    },
  })
}

describe('WorkflowGraphOverlayLayer', () => {
  beforeEach(() => setI18nLocale('zh-CN'))

  it('将 Minimap 和 viewport controls 收纳到统一 Dock', () => {
    const wrapper = mountOverlay()
    const dock = wrapper.get('.workflow-graph-navigation-dock')

    expect(dock.findComponent({ name: 'WorkflowGraphMinimap' }).exists()).toBe(true)
    expect(dock.findComponent({ name: 'WorkflowGraphViewportControls' }).exists()).toBe(true)
    expect(dock.classes()).not.toContain('is-inspector-open')
  })
})
