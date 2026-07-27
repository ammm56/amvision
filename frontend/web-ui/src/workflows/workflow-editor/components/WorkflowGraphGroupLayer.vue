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
        'is-locked': group.locked,
      }"
      :style="groupStyle(group)"
      @mousedown="handleGroupMouseDown($event, group)"
      @click="handleGroupClick($event, group)"
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
        <button
          type="button"
          class="workflow-graph-group__lock"
          :class="{ 'is-active': group.locked }"
          :title="readLockTitle(group)"
          :aria-label="readLockTitle(group)"
          :aria-pressed="group.locked"
          @mousedown.stop
          @click.stop="emit('toggleGroupLocked', group)"
        >
          <Lock v-if="group.locked" :size="13" />
          <LockOpen v-else :size="13" />
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
          :title="t('workflowEditor.editor.editGroupName')"
          @dblclick.stop="beginNameEdit(group)"
        >{{ group.name }}</span>
        <span class="workflow-graph-group__count">{{ group.member_node_ids.length }}</span>
        <span class="workflow-graph-group__color-picker">
          <button
            type="button"
            class="workflow-graph-group__color-button"
            :title="t('workflowEditor.editor.selectGroupColor')"
            :aria-label="t('workflowEditor.editor.selectGroupColor')"
            :style="{ '--workflow-graph-group-swatch-color': group.color || defaultGroupColor }"
            @mousedown.stop
            @click.stop="toggleColorPicker(group.group_id)"
          />
          <span v-if="colorPickerGroupId === group.group_id" class="workflow-graph-group__palette" @mousedown.stop @click.stop>
            <button
              v-for="color in groupColorOptions"
              :key="color"
              type="button"
              class="workflow-graph-group__swatch"
              :class="{ 'is-active': readGroupColor(group) === color }"
              :style="{ '--workflow-graph-group-swatch-color': color }"
              :title="t('workflowEditor.editor.setColor', { color })"
              :aria-label="t('workflowEditor.editor.setGroupColor', { color })"
              @click="selectGroupColor(group.group_id, color)"
            />
          </span>
        </span>
        <button
          type="button"
          class="workflow-graph-group__delete"
          :title="t('workflowEditor.editor.deleteGroupHint')"
          :aria-label="t('workflowEditor.editor.deleteGroup')"
          @mousedown.stop
          @click.stop="emit('deleteGroup', group.group_id)"
        >
          <Trash2 :size="13" />
        </button>
      </div>
      <button
        v-if="!group.locked"
        type="button"
        class="workflow-graph-group__resize"
        :title="t('workflowEditor.editor.resizeGroup')"
        :aria-label="t('workflowEditor.editor.resizeGroup')"
        @mousedown.stop.prevent="emit('startGroupResize', $event, group)"
      />
    </div>

    <div
      v-if="draftRect"
      class="workflow-graph-group workflow-graph-group--draft"
      :style="rectStyle(draftRect, '#22b8cf')"
    >
      <div class="workflow-graph-group__header">
        <span class="workflow-graph-group__name">{{ t('workflowEditor.editor.newGroup') }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { CheckCircle, CircleDotDashed, CircleOff, Lock, LockOpen, Trash2 } from '@lucide/vue'
import { useTranslation } from '@/platform/i18n'

import type { WorkflowGraphGroup, WorkflowGraphGroupRect } from '../types'
import type { WorkflowGraphGroupState } from '../graph/useWorkflowGraphGroups'

const { t } = useTranslation()
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
  toggleGroupLocked: [group: WorkflowGraphGroup]
  renameGroup: [groupId: string, name: string]
  deleteGroup: [groupId: string]
  updateGroupColor: [groupId: string, color: string]
}>()

const editingGroupId = ref<string | null>(null)
const nameDraft = ref('')
const nameInputs = new Map<string, HTMLInputElement>()
const colorPickerGroupId = ref<string | null>(null)
const defaultGroupColor = '#22b8cf'
const groupColorOptions = ['#22b8cf', '#4dabf7', '#40c057', '#fab005', '#ff922b', '#da77f2', '#748ffc', '#f06595']

function groupStyle(group: WorkflowGraphGroup): Record<string, string> {
  return rectStyle(group.rect, readGroupColor(group))
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
  if (state === 'enabled') return t('workflowEditor.editor.disableGroup')
  if (state === 'disabled') return t('workflowEditor.editor.enableGroup')
  return t('workflowEditor.editor.enableMixedGroup')
}

function readLockTitle(group: WorkflowGraphGroup): string {
  return group.locked ? t('workflowEditor.editor.unlockGroup') : t('workflowEditor.editor.lockGroup')
}

function handleGroupMouseDown(event: MouseEvent, group: WorkflowGraphGroup): void {
  if (group.locked) return
  event.stopPropagation()
  emit('startGroupDrag', event, group)
}

function handleGroupClick(event: MouseEvent, group: WorkflowGraphGroup): void {
  if (group.locked) return
  event.stopPropagation()
  emit('selectGroup', group.group_id)
}

function readGroupColor(group: WorkflowGraphGroup): string {
  return group.color || defaultGroupColor
}

function toggleColorPicker(groupId: string): void {
  colorPickerGroupId.value = colorPickerGroupId.value === groupId ? null : groupId
}

function selectGroupColor(groupId: string, color: string): void {
  emit('updateGroupColor', groupId, color)
  colorPickerGroupId.value = null
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
