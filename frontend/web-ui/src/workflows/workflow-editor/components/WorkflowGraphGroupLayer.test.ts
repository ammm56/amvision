import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { WorkflowGraphGroup } from '../types'
import WorkflowGraphGroupLayer from './WorkflowGraphGroupLayer.vue'

function createGroup(locked: boolean): WorkflowGraphGroup {
  return {
    group_id: 'group-1',
    name: '测试节点组',
    enabled: true,
    rect: { x: 10, y: 20, width: 640, height: 480 },
    member_node_ids: ['node-1'],
    membership_policy: 'full-containment',
    color: '#22b8cf',
    collapsed: false,
    locked,
    metadata: {},
  }
}

describe('WorkflowGraphGroupLayer', () => {
  it('keeps unlocked group pointer events for group dragging', async () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    let bubbledMouseDownCount = 0
    host.addEventListener('mousedown', () => { bubbledMouseDownCount += 1 })
    const group = createGroup(false)
    const wrapper = mount(WorkflowGraphGroupLayer, {
      attachTo: host,
      props: {
        groups: [group],
        selectedGroupId: null,
        draftRect: null,
        readGroupState: () => 'enabled',
      },
    })

    await wrapper.get('.workflow-graph-group').trigger('mousedown', { button: 0 })

    expect(wrapper.emitted('startGroupDrag')).toHaveLength(1)
    expect(bubbledMouseDownCount).toBe(0)
    wrapper.unmount()
    host.remove()
  })

  it('lets locked group area bubble to canvas and exposes unlock control', async () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    let bubbledMouseDownCount = 0
    host.addEventListener('mousedown', () => { bubbledMouseDownCount += 1 })
    const group = createGroup(true)
    const wrapper = mount(WorkflowGraphGroupLayer, {
      attachTo: host,
      props: {
        groups: [group],
        selectedGroupId: group.group_id,
        draftRect: null,
        readGroupState: () => 'enabled',
      },
    })

    const groupElement = wrapper.get('.workflow-graph-group')
    await groupElement.trigger('mousedown', { button: 0 })

    expect(groupElement.classes()).toContain('is-locked')
    expect(wrapper.emitted('startGroupDrag')).toBeUndefined()
    expect(bubbledMouseDownCount).toBe(1)
    expect(wrapper.find('.workflow-graph-group__resize').exists()).toBe(false)

    const lockButton = wrapper.get('.workflow-graph-group__lock')
    expect(lockButton.attributes('aria-pressed')).toBe('true')
    await lockButton.trigger('click')
    expect(wrapper.emitted('toggleGroupLocked')?.[0]).toEqual([group])
    wrapper.unmount()
    host.remove()
  })
})
