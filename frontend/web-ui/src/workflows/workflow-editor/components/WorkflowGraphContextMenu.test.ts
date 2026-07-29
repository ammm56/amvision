import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { i18n } from '../../../platform/i18n'
import WorkflowGraphContextMenu from './WorkflowGraphContextMenu.vue'

describe('WorkflowGraphContextMenu', () => {
  it('opens the node picker only after clicking Add Node', async () => {
    const wrapper = mount(WorkflowGraphContextMenu, {
      global: {
        plugins: [i18n],
      },
      props: {
        contextMenu: {
          x: 100,
          y: 120,
          worldX: 40,
          worldY: 60,
          nodeId: null,
          edgeId: null,
          port: null,
        },
        menuStyle: {},
        minimapVisible: true,
        graphTheme: 'light',
        saveDisabled: false,
        previewDisabled: false,
        addNodeLabel: 'Add Node',
        lightLabel: 'Light',
        darkLabel: 'Dark',
        saveLabel: 'Save App',
        previewLabel: 'Preview Run',
      },
    })
    const addNodeButton = wrapper.get('.workflow-graph-context-menu__submenu-trigger')

    await addNodeButton.trigger('mouseenter')
    expect(wrapper.emitted('open-node-picker')).toBeUndefined()

    await addNodeButton.trigger('click')
    expect(wrapper.emitted('open-node-picker')).toHaveLength(1)
  })
})
