<template>
  <div class="workflow-graph-group-layer">
    <div
      v-for="group in groups"
      :key="group.group_id"
      class="workflow-graph-group"
      :class="{
        'is-selected': selectedGroupId === group.group_id,
        'is-disabled': readGroupState(group) === 'disabled',
        'is-mixed': readGroupState(group) === 'mixed',
      }"
      :style="groupStyle(group)"
      @mousedown.stop="emit('startGroupDrag', $event, group)"
      @click.stop="emit('selectGroup', group.group_id)"
    >
      <div class="workflow-graph-group__header">
        <button
          type="button"
          class="workflow-graph-group__toggle"
          :title="readToggleTitle(group)"
          :aria-label="readToggleTitle(group)"
          @mousedown.stop
          @click.stop="emit('toggleGroupEnabled', group)"
        >
          <CheckCircle v-if="readGroupState(group) === 'enabled'" :size="14" />
          <CircleOff v-else-if="readGroupState(group) === 'disabled'" :size="14" />
          <CircleDotDashed v-else :size="14" />
        </button>
        <input
          v-if="editingGroupId === group.group_id"
          :ref="(element) => bindNameInput(element, group.group_id)"
          v-model="nameDraft"
          class="workflow-graph-group__name-input"
          @mousedown.stop
          @click.stop
          @keydown.enter.prevent="commitNameEdit"
          @keydown.esc.prevent="cancelNameEdit"
          @blur="commitNameEdit"
        >
        <span
          v-else
          class="workflow-graph-group__name"
          title="双击编辑节点组名称"
          @dblclick.stop="beginNameEdit(group)"
        >{{ group.name }}</span>
        <span class="workflow-graph-group__count">{{ group.member_node_ids.length }}</span>
      </div>
      <button
        type="button"
        class="workflow-graph-group__resize"
        title="调整节点组大小"
        aria-label="调整节点组大小"
        @mousedown.stop.prevent="emit('startGroupResize', $event, group)"
      />
    </div>

    <div
      v-if="draftRect"
      class="workflow-graph-group workflow-graph-group--draft"
      :style="rectStyle(draftRect, '#22b8cf')"
    >
      <div class="workflow-graph-group__header">
        <span class="workflow-graph-group__name">新节点组</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { CheckCircle, CircleDotDashed, CircleOff } from '@lucide/vue'

import type { WorkflowGraphGroup, WorkflowGraphGroupRect } from '../types'
import type { WorkflowGraphGroupState } from '../graph/useWorkflowGraphGroups'

const props = defineProps<{
  groups: WorkflowGraphGroup[]
  selectedGroupId: string | null
  draftRect: WorkflowGraphGroupRect | null
  readGroupState: (group: WorkflowGraphGroup) => WorkflowGraphGroupState
}>()

const emit = defineEmits<{
  selectGroup: [groupId: string]
  startGroupDrag: [event: MouseEvent, group: WorkflowGraphGroup]
  startGroupResize: [event: MouseEvent, group: WorkflowGraphGroup]
  toggleGroupEnabled: [group: WorkflowGraphGroup]
  renameGroup: [groupId: string, name: string]
}>()

const editingGroupId = ref<string | null>(null)
const nameDraft = ref('')
const nameInputs = new Map<string, HTMLInputElement>()

function groupStyle(group: WorkflowGraphGroup): Record<string, string> {
  return rectStyle(group.rect, group.color || '#22b8cf')
}

function rectStyle(rect: WorkflowGraphGroupRect, color: string): Record<string, string> {
  return {
    left: `${rect.x}px`,
    top: `${rect.y}px`,
    width: `${rect.width}px`,
    height: `${rect.height}px`,
    '--workflow-graph-group-color': color,
  }
}

function readToggleTitle(group: WorkflowGraphGroup): string {
  const state = props.readGroupState(group)
  if (state === 'enabled') return '禁用节点组'
  if (state === 'disabled') return '启用节点组'
  return '统一启用节点组'
}

function bindNameInput(element: unknown, groupId: string): void {
  if (element instanceof HTMLInputElement) {
    nameInputs.set(groupId, element)
  } else {
    nameInputs.delete(groupId)
  }
}

function beginNameEdit(group: WorkflowGraphGroup): void {
  editingGroupId.value = group.group_id
  nameDraft.value = group.name
  nextTick(() => {
    const input = nameInputs.get(group.group_id)
    input?.focus()
    input?.select()
  })
}

function commitNameEdit(): void {
  if (!editingGroupId.value) return
  emit('renameGroup', editingGroupId.value, nameDraft.value)
  editingGroupId.value = null
}

function cancelNameEdit(): void {
  editingGroupId.value = null
}
</script>
