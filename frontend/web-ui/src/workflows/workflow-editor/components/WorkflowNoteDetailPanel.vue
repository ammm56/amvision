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
      <select :value="note.tone" :disabled="note.locked" @change="emit('updateTone', readTone($event))">
        <option value="neutral">{{ t('workflowEditor.editor.noteToneNeutral') }}</option>
        <option value="info">{{ t('workflowEditor.editor.noteToneInfo') }}</option>
        <option value="success">{{ t('workflowEditor.editor.noteToneSuccess') }}</option>
        <option value="warning">{{ t('workflowEditor.editor.noteToneWarning') }}</option>
        <option value="danger">{{ t('workflowEditor.editor.noteToneDanger') }}</option>
      </select>
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

function readTone(event: Event): WorkflowGraphNote['tone'] {
  const value = event.target instanceof HTMLSelectElement ? event.target.value : 'neutral'
  return ['neutral', 'info', 'success', 'warning', 'danger'].includes(value)
    ? value as WorkflowGraphNote['tone']
    : 'neutral'
}
</script>
