import { ref, type Ref } from 'vue'

import type { WorkflowGraphGroup, WorkflowGraphGroupRect } from '../types'

export type WorkflowGraphGroupState = 'enabled' | 'disabled' | 'mixed' | 'empty'

export interface WorkflowGraphGroupNodeView {
  node: {
    node_id: string
    node_type_id: string
    enabled: boolean
    ui_state: Record<string, unknown>
    metadata: Record<string, unknown>
  }
  x: number
  y: number
  width: number
}

interface PointerPosition {
  x: number
  y: number
}

interface GroupCreateState {
  start: PointerPosition
}

interface GroupDragState<NodeView extends WorkflowGraphGroupNodeView> {
  groupId: string
  start: PointerPosition
  initialRect: WorkflowGraphGroupRect
  memberNodePositions: Map<string, { x: number; y: number }>
  nodes: NodeView[]
}

interface GroupResizeState {
  groupId: string
  start: PointerPosition
  initialRect: WorkflowGraphGroupRect
}

export interface WorkflowGraphGroupsOptions<NodeView extends WorkflowGraphGroupNodeView> {
  graphGroups: Ref<WorkflowGraphGroup[]>
  graphNodes: Ref<NodeView[]>
  screenToWorld: (clientX: number, clientY: number) => PointerPosition
  readNodeHeight: (node: NodeView) => number
  setStatusMessage: (message: string | null) => void
  setErrorMessage: (message: string | null) => void
}

const minimumGroupWidth = 180
const minimumGroupHeight = 120
const defaultGroupColor = '#22b8cf'

export function useWorkflowGraphGroups<NodeView extends WorkflowGraphGroupNodeView>(
  options: WorkflowGraphGroupsOptions<NodeView>,
) {
  const selectedGroupId = ref<string | null>(null)
  const groupCreateMode = ref(false)
  const draftGroupRect = ref<WorkflowGraphGroupRect | null>(null)
  const groupCreateState = ref<GroupCreateState | null>(null)
  const groupDragState = ref<GroupDragState<NodeView> | null>(null)
  const groupResizeState = ref<GroupResizeState | null>(null)

  function toggleGroupCreateMode(): void {
    groupCreateMode.value = !groupCreateMode.value
    draftGroupRect.value = null
    options.setStatusMessage(groupCreateMode.value ? '拖拽画布区域创建节点组' : null)
  }

  function cancelTransientGroupOperations(): void {
    groupCreateMode.value = false
    draftGroupRect.value = null
    groupCreateState.value = null
    groupDragState.value = null
    groupResizeState.value = null
    removeDocumentListeners()
  }

  function startGroupCreate(event: MouseEvent): boolean {
    if (!groupCreateMode.value) return false
    const start = options.screenToWorld(event.clientX, event.clientY)
    groupCreateState.value = { start }
    draftGroupRect.value = {
      x: start.x,
      y: start.y,
      width: 1,
      height: 1,
    }
    event.preventDefault()
    document.addEventListener('mousemove', moveGroupCreate)
    document.addEventListener('mouseup', stopGroupCreate)
    return true
  }

  function moveGroupCreate(event: MouseEvent): void {
    const createState = groupCreateState.value
    if (!createState) return
    draftGroupRect.value = normalizeRectFromPoints(createState.start, options.screenToWorld(event.clientX, event.clientY))
  }

  function stopGroupCreate(): void {
    const rect = draftGroupRect.value
    groupCreateState.value = null
    draftGroupRect.value = null
    groupCreateMode.value = false
    document.removeEventListener('mousemove', moveGroupCreate)
    document.removeEventListener('mouseup', stopGroupCreate)
    if (!rect || rect.width < minimumGroupWidth || rect.height < minimumGroupHeight) {
      options.setStatusMessage('节点组区域太小，已取消创建')
      return
    }
    const group = createGraphGroup(rect)
    options.graphGroups.value = [...options.graphGroups.value, group]
    selectedGroupId.value = group.group_id
    syncGroupMemberships(group.group_id)
    options.setStatusMessage(`已创建节点组：${group.name}`)
  }

  function selectGroup(groupId: string): void {
    selectedGroupId.value = groupId
  }

  function clearGroupSelection(): void {
    selectedGroupId.value = null
  }

  function startGroupDrag(event: MouseEvent, group: WorkflowGraphGroup): void {
    if (group.locked) return
    const start = options.screenToWorld(event.clientX, event.clientY)
    const memberNodeIds = new Set(group.member_node_ids)
    const nodes = options.graphNodes.value.filter((node) => memberNodeIds.has(node.node.node_id))
    groupDragState.value = {
      groupId: group.group_id,
      start,
      initialRect: { ...group.rect },
      memberNodePositions: new Map(nodes.map((node) => [node.node.node_id, { x: node.x, y: node.y }])),
      nodes,
    }
    selectedGroupId.value = group.group_id
    event.preventDefault()
    document.addEventListener('mousemove', moveGroupDrag)
    document.addEventListener('mouseup', stopGroupDrag)
  }

  function moveGroupDrag(event: MouseEvent): void {
    const dragState = groupDragState.value
    if (!dragState) return
    const group = options.graphGroups.value.find((item) => item.group_id === dragState.groupId)
    if (!group) return
    const pointer = options.screenToWorld(event.clientX, event.clientY)
    const deltaX = Math.round(pointer.x - dragState.start.x)
    const deltaY = Math.round(pointer.y - dragState.start.y)
    group.rect = {
      ...dragState.initialRect,
      x: Math.round(dragState.initialRect.x + deltaX),
      y: Math.round(dragState.initialRect.y + deltaY),
    }
    for (const node of dragState.nodes) {
      const initialPosition = dragState.memberNodePositions.get(node.node.node_id)
      if (!initialPosition) continue
      node.x = Math.round(initialPosition.x + deltaX)
      node.y = Math.round(initialPosition.y + deltaY)
      node.node.ui_state = { ...node.node.ui_state, x: node.x, y: node.y, width: node.width }
    }
  }

  function stopGroupDrag(): void {
    const groupId = groupDragState.value?.groupId ?? null
    groupDragState.value = null
    document.removeEventListener('mousemove', moveGroupDrag)
    document.removeEventListener('mouseup', stopGroupDrag)
    if (groupId) syncGroupMemberships(groupId)
  }

  function startGroupResize(event: MouseEvent, group: WorkflowGraphGroup): void {
    if (group.locked) return
    groupResizeState.value = {
      groupId: group.group_id,
      start: options.screenToWorld(event.clientX, event.clientY),
      initialRect: { ...group.rect },
    }
    selectedGroupId.value = group.group_id
    event.preventDefault()
    document.addEventListener('mousemove', moveGroupResize)
    document.addEventListener('mouseup', stopGroupResize)
  }

  function moveGroupResize(event: MouseEvent): void {
    const resizeState = groupResizeState.value
    if (!resizeState) return
    const group = options.graphGroups.value.find((item) => item.group_id === resizeState.groupId)
    if (!group) return
    const pointer = options.screenToWorld(event.clientX, event.clientY)
    group.rect = {
      ...resizeState.initialRect,
      width: Math.max(minimumGroupWidth, Math.round(resizeState.initialRect.width + pointer.x - resizeState.start.x)),
      height: Math.max(minimumGroupHeight, Math.round(resizeState.initialRect.height + pointer.y - resizeState.start.y)),
    }
  }

  function stopGroupResize(): void {
    const groupId = groupResizeState.value?.groupId ?? null
    groupResizeState.value = null
    document.removeEventListener('mousemove', moveGroupResize)
    document.removeEventListener('mouseup', stopGroupResize)
    if (groupId) syncGroupMemberships(groupId)
  }

  function syncGroupMemberships(preferredGroupId: string | null = selectedGroupId.value): void {
    const orderedGroups = orderGroupsForMembership(preferredGroupId)
    const assignedNodeIds = new Set<string>()
    for (const group of orderedGroups) {
      const memberNodeIds = options.graphNodes.value
        .filter((node) => !assignedNodeIds.has(node.node.node_id))
        .filter((node) => isNodeFullyInsideGroup(node, group.rect))
        .map((node) => node.node.node_id)
      memberNodeIds.forEach((nodeId) => assignedNodeIds.add(nodeId))
      group.member_node_ids = memberNodeIds
    }
  }

  function syncMembershipAfterNodeDrag(): void {
    syncGroupMemberships(selectedGroupId.value)
  }

  function toggleGroupEnabled(group: WorkflowGraphGroup, forceEnabled?: boolean): void {
    const nextEnabled = typeof forceEnabled === 'boolean' ? forceEnabled : readGroupState(group) !== 'enabled'
    const memberNodeIds = new Set(group.member_node_ids)
    const skippedNodeTitles: string[] = []
    for (const node of options.graphNodes.value) {
      if (!memberNodeIds.has(node.node.node_id)) continue
      if (isGroupToggleProtectedNode(node)) {
        skippedNodeTitles.push(node.node.node_id)
        continue
      }
      node.node.enabled = nextEnabled
    }
    group.enabled = nextEnabled
    if (skippedNodeTitles.length > 0) {
      options.setStatusMessage(`节点组已更新，跳过受保护节点：${skippedNodeTitles.join('、')}`)
    } else {
      options.setStatusMessage(`${group.name} 已${nextEnabled ? '启用' : '禁用'}`)
    }
  }

  function renameGroup(groupId: string, nextName: string): void {
    const group = options.graphGroups.value.find((item) => item.group_id === groupId)
    if (!group) return
    const normalizedName = nextName.trim()
    if (!normalizedName) {
      options.setErrorMessage('节点组名称不能为空')
      return
    }
    group.name = normalizedName
    options.setStatusMessage(`已更新节点组名称：${normalizedName}`)
  }

  function deleteGroup(groupId: string): void {
    const group = options.graphGroups.value.find((item) => item.group_id === groupId)
    if (!group) return
    options.graphGroups.value = options.graphGroups.value.filter((item) => item.group_id !== groupId)
    if (selectedGroupId.value === groupId) selectedGroupId.value = null
    if (groupDragState.value?.groupId === groupId) groupDragState.value = null
    if (groupResizeState.value?.groupId === groupId) groupResizeState.value = null
    removeDocumentListeners()
    options.setStatusMessage(`已删除节点组：${group.name}，组内节点不受影响`)
  }

  function updateGroupColor(groupId: string, color: string): void {
    const group = options.graphGroups.value.find((item) => item.group_id === groupId)
    if (!group) return
    group.color = color
    options.setStatusMessage(`已更新节点组颜色：${group.name}`)
  }

  function readGroupState(group: WorkflowGraphGroup): WorkflowGraphGroupState {
    const memberNodeIds = new Set(group.member_node_ids)
    const memberNodes = options.graphNodes.value.filter((node) => memberNodeIds.has(node.node.node_id))
    if (memberNodes.length === 0) return 'empty'
    const enabledCount = memberNodes.filter((node) => node.node.enabled !== false).length
    if (enabledCount === 0) return 'disabled'
    if (enabledCount === memberNodes.length) return 'enabled'
    return 'mixed'
  }

  function removeDocumentListeners(): void {
    document.removeEventListener('mousemove', moveGroupCreate)
    document.removeEventListener('mouseup', stopGroupCreate)
    document.removeEventListener('mousemove', moveGroupDrag)
    document.removeEventListener('mouseup', stopGroupDrag)
    document.removeEventListener('mousemove', moveGroupResize)
    document.removeEventListener('mouseup', stopGroupResize)
  }

  function createGraphGroup(rect: WorkflowGraphGroupRect): WorkflowGraphGroup {
    const groupIndex = options.graphGroups.value.length + 1
    return {
      group_id: createUniqueGroupId(groupIndex),
      name: `节点组 ${groupIndex}`,
      enabled: true,
      rect: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
      member_node_ids: [],
      membership_policy: 'full-containment',
      color: defaultGroupColor,
      collapsed: false,
      locked: false,
      metadata: {},
    }
  }

  function createUniqueGroupId(index: number): string {
    const existingIds = new Set(options.graphGroups.value.map((group) => group.group_id))
    let candidate = `group-${index}`
    let suffix = index
    while (existingIds.has(candidate)) {
      suffix += 1
      candidate = `group-${suffix}`
    }
    return candidate
  }

  function orderGroupsForMembership(preferredGroupId: string | null): WorkflowGraphGroup[] {
    const groups = [...options.graphGroups.value]
    return groups.sort((left, right) => {
      if (preferredGroupId) {
        if (left.group_id === preferredGroupId) return -1
        if (right.group_id === preferredGroupId) return 1
      }
      return readGroupArea(left) - readGroupArea(right)
    })
  }

  function isNodeFullyInsideGroup(node: NodeView, rect: WorkflowGraphGroupRect): boolean {
    const nodeRight = node.x + node.width
    const nodeBottom = node.y + options.readNodeHeight(node)
    return node.x >= rect.x && node.y >= rect.y && nodeRight <= rect.x + rect.width && nodeBottom <= rect.y + rect.height
  }

  function readGroupArea(group: WorkflowGraphGroup): number {
    return Math.max(0, group.rect.width) * Math.max(0, group.rect.height)
  }

  function isGroupToggleProtectedNode(node: NodeView): boolean {
    return node.node.metadata.group_toggle_protected === true || node.node.node_type_id === 'core.io.app-entry' || node.node.node_type_id === 'core.output.app-result'
  }

  return {
    selectedGroupId,
    groupCreateMode,
    draftGroupRect,
    toggleGroupCreateMode,
    cancelTransientGroupOperations,
    startGroupCreate,
    selectGroup,
    clearGroupSelection,
    startGroupDrag,
    startGroupResize,
    syncGroupMemberships,
    syncMembershipAfterNodeDrag,
    toggleGroupEnabled,
    renameGroup,
    deleteGroup,
    updateGroupColor,
    readGroupState,
  }
}

function normalizeRectFromPoints(start: PointerPosition, end: PointerPosition): WorkflowGraphGroupRect {
  const left = Math.min(start.x, end.x)
  const top = Math.min(start.y, end.y)
  return {
    x: Math.round(left),
    y: Math.round(top),
    width: Math.round(Math.abs(end.x - start.x)),
    height: Math.round(Math.abs(end.y - start.y)),
  }
}
