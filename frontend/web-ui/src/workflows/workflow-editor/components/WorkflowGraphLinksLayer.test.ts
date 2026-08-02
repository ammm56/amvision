import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { WorkflowGraphLinkView } from '../geometry/useWorkflowGraphGeometry'
import WorkflowGraphLinksLayer from './WorkflowGraphLinksLayer.vue'

const link: WorkflowGraphLinkView = {
  linkKind: 'edge',
  edgeId: 'edge-1',
  edge: null,
  sourceX: 0,
  sourceY: 0,
  targetX: 100,
  targetY: 100,
}

describe('WorkflowGraphLinksLayer', () => {
  it('在命中区域 hover 时只标记对应的可见连线', async () => {
    const wrapper = mount(WorkflowGraphLinksLayer, {
      props: {
        links: [link],
        midpoints: [],
        reconnectHandles: [],
        showDraft: false,
        draftPath: '',
        linkPath: () => 'M 0 0 L 100 100',
        isLinkSelected: () => false,
      },
    })

    const hitArea = wrapper.get('.workflow-graph-link-hit-area')
    const visibleLink = wrapper.get('.workflow-graph-link')
    await hitArea.trigger('mouseenter')
    expect(visibleLink.classes()).toContain('is-hovered')

    await hitArea.trigger('mouseleave')
    expect(visibleLink.classes()).not.toContain('is-hovered')
  })

  it('将选中态传递给可见连线', () => {
    const wrapper = mount(WorkflowGraphLinksLayer, {
      props: {
        links: [link],
        midpoints: [],
        reconnectHandles: [],
        showDraft: false,
        draftPath: '',
        linkPath: () => 'M 0 0 L 100 100',
        isLinkSelected: () => true,
      },
    })

    expect(wrapper.get('.workflow-graph-link').classes()).toContain('is-selected')
  })
})
