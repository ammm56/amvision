<template>
  <section class="workflow-graph-inspector-card workflow-note-detail-panel">
    <div class="workflow-graph-inspector-card__header">
      <span class="workflow-graph-inspector-card__summary">
        <strong>{{ t('workflowEditor.editor.note') }}</strong>
        <small>{{ note.note_id }}</small>
      </span>
    </div>
    <p class="workflow-note-detail-panel__boundary">
      {{ t('workflowEditor.editor.noteExecutionBoundary') }}
    </p>
    <label>
      <span>{{ t('workflowEditor.editor.noteTitle') }}</span>
      <input
        :value="note.title"
        maxlength="128"
        :disabled="note.locked"
        @change="emit('updateTitle', readInput($event))"
      >
    </label>
    <label>
      <span>{{ t('workflowEditor.editor.noteContent') }}</span>
      <textarea
        :value="note.content"
        :disabled="note.locked"
        @change="emit('updateContent', readTextArea($event))"
      />
    </label>
    <label>
      <span>{{ t('workflowEditor.editor.noteTone') }}</span>
      <UiSelect :model-value="note.tone" :disabled="note.locked" @change="emit('updateTone', readTone($event))" :options="[...[{ value: 'neutral', label: String(t('workflowEditor.editor.noteToneNeutral')), disabled: false }], ...[{ value: 'info', label: String(t('workflowEditor.editor.noteToneInfo')), disabled: false }], ...[{ value: 'success', label: String(t('workflowEditor.editor.noteToneSuccess')), disabled: false }], ...[{ value: 'warning', label: String(t('workflowEditor.editor.noteToneWarning')), disabled: false }], ...[{ value: 'danger', label: String(t('workflowEditor.editor.noteToneDanger')), disabled: false }]]" floating />
    </label>
    <div class="workflow-note-detail-panel__actions">
      <button type="button" @click="emit('toggleCollapsed')">
        {{ t(note.collapsed ? 'workflowEditor.editor.expandNote' : 'workflowEditor.editor.collapseNote') }}
      </button>
      <button type="button" @click="emit('toggleLocked')">
        {{ t(note.locked ? 'workflowEditor.editor.unlockNote' : 'workflowEditor.editor.lockNote') }}
      </button>
      <button type="button" @click="emit('copy')">{{ t('workflowEditor.editor.copyNote') }}</button>
      <button type="button" class="is-danger" @click="emit('delete')">{{ t('workflowEditor.editor.deleteNote') }}</button>
    </div>
  </section>
</template>

<script setup lang="ts">
import UiSelect from '@/shared/ui/components/Select.vue'
import { useI18n } from 'vue-i18n'

import type { WorkflowGraphNote } from '../types'

defineProps<{ note: WorkflowGraphNote }>()
const emit = defineEmits<{
  updateTitle: [value: string]
  updateContent: [value: string]
  updateTone: [tone: WorkflowGraphNote['tone']]
  toggleCollapsed: []
  toggleLocked: []
  copy: []
  delete: []
}>()
const { t } = useI18n()

function readInput(event: Event): string {
  return event.target instanceof HTMLInputElement ? event.target.value : ''
}

function readTextArea(event: Event): string {
  return event.target instanceof HTMLTextAreaElement ? event.target.value : ''
}

function readTone(selection: string | number | boolean | null): WorkflowGraphNote['tone'] {
  const value = String(selection)
  return ['neutral', 'info', 'success', 'warning', 'danger'].includes(value)
    ? value as WorkflowGraphNote['tone']
    : 'neutral'
}
</script>
