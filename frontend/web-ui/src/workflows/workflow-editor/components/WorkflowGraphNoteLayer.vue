<template>
  <div class="workflow-graph-note-layer">
    <article
      v-for="note in notes"
      :key="note.note_id"
      class="workflow-graph-note"
      :class="[
        `workflow-graph-note--${note.tone}`,
        { 'is-selected': selectedNoteId === note.note_id, 'is-collapsed': note.collapsed, 'is-locked': note.locked },
      ]"
      :style="noteStyle(note)"
      :data-note-id="note.note_id"
      @mousedown.stop="emit('selectNote', note.note_id)"
      @contextmenu.prevent.stop="emit('openNoteContextMenu', $event, note)"
    >
      <header class="workflow-graph-note__header" @mousedown="emit('startNoteDrag', $event, note)">
        <FileText :size="15" />
        <span class="workflow-graph-note__title" @dblclick.stop="emit('beginEdit', note.note_id)">{{ note.title }}</span>
        <div class="workflow-graph-note__actions" @mousedown.stop>
          <SelectField
            class="workflow-graph-note__tone-select"
            fit-options
            :model-value="note.tone"
            :options="toneOptions"
            :aria-label="t('workflowEditor.editor.noteTone')"
            :disabled="note.locked"
            @update:model-value="emit('updateTone', note, readTone($event))"
          />
          <button type="button" :title="collapseLabel(note)" @click="emit('toggleCollapsed', note)">
            <ChevronDown v-if="note.collapsed" :size="14" />
            <ChevronUp v-else :size="14" />
          </button>
          <button type="button" :title="lockLabel(note)" @click="emit('toggleLocked', note)">
            <Lock v-if="note.locked" :size="14" />
            <LockOpen v-else :size="14" />
          </button>
        </div>
      </header>

      <div
        v-if="!note.collapsed"
        class="workflow-graph-note__body"
        @dblclick.stop="emit('beginEdit', note.note_id)"
      >
        <div
          v-if="editingNoteId !== note.note_id"
          class="workflow-graph-note__markdown"
          v-html="renderMarkdown(note)"
        />
        <div
          v-else
          class="workflow-graph-note__editor"
          @focusout="handleEditorFocusOut($event, note)"
        >
          <input
            v-model="drafts[note.note_id]!.title"
            maxlength="128"
            :aria-label="t('workflowEditor.editor.noteTitle')"
            @keydown="handleEditorKeydown($event, note)"
          />
          <textarea
            v-model="drafts[note.note_id]!.content"
            :aria-label="t('workflowEditor.editor.noteContent')"
            @keydown="handleEditorKeydown($event, note)"
          />
          <span>{{ t('workflowEditor.editor.noteEditHint') }}</span>
        </div>
      </div>

      <button
        v-if="!note.collapsed && !note.locked"
        type="button"
        class="workflow-graph-note__resize"
        :aria-label="t('workflowEditor.editor.resizeNote')"
        @mousedown="emit('startNoteResize', $event, note)"
      />
    </article>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, reactive, watch } from 'vue'
import { ChevronDown, ChevronUp, FileText, Lock, LockOpen } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import SelectField from '@/shared/ui/components/Select.vue'
import type { WorkflowGraphNote } from '../types'
import { renderWorkflowNoteMarkdown } from '../notes/workflowNoteMarkdown'

const props = defineProps<{
  notes: WorkflowGraphNote[]
  selectedNoteId: string | null
  editingNoteId: string | null
}>()

const emit = defineEmits<{
  selectNote: [noteId: string]
  beginEdit: [noteId: string]
  finishEdit: [noteId: string, title: string, content: string]
  cancelEdit: [noteId: string]
  startNoteDrag: [event: MouseEvent, note: WorkflowGraphNote]
  startNoteResize: [event: MouseEvent, note: WorkflowGraphNote]
  toggleCollapsed: [note: WorkflowGraphNote]
  toggleLocked: [note: WorkflowGraphNote]
  updateTone: [note: WorkflowGraphNote, tone: WorkflowGraphNote['tone']]
  openNoteContextMenu: [event: MouseEvent, note: WorkflowGraphNote]
}>()

const { t } = useI18n()
const drafts = reactive<Record<string, { title: string; content: string }>>({})
const markdownCache = new Map<string, { content: string; html: string }>()
const noteToneValues: WorkflowGraphNote['tone'][] = ['neutral', 'info', 'success', 'warning', 'danger']
const toneOptions = computed(() => [
  { value: 'neutral', label: t('workflowEditor.editor.noteToneNeutral') },
  { value: 'info', label: t('workflowEditor.editor.noteToneInfo') },
  { value: 'success', label: t('workflowEditor.editor.noteToneSuccess') },
  { value: 'warning', label: t('workflowEditor.editor.noteToneWarning') },
  { value: 'danger', label: t('workflowEditor.editor.noteToneDanger') },
])

watch(
  () => props.editingNoteId,
  async (noteId) => {
    if (!noteId) return
    const note = props.notes.find((item) => item.note_id === noteId)
    if (!note) return
    drafts[noteId] = { title: note.title, content: note.content }
    await nextTick()
    const element = document.querySelector<HTMLElement>(`[data-note-id="${CSS.escape(noteId)}"] .workflow-graph-note__editor input`)
    element?.focus()
    if (element instanceof HTMLInputElement) element.select()
  },
)

watch(
  () => props.notes.map((note) => note.note_id),
  (noteIds) => {
    const activeNoteIds = new Set(noteIds)
    for (const noteId of markdownCache.keys()) {
      if (!activeNoteIds.has(noteId)) markdownCache.delete(noteId)
    }
  },
)

function noteStyle(note: WorkflowGraphNote): Record<string, string> {
  return {
    left: `${note.rect.x}px`,
    top: `${note.rect.y}px`,
    width: `${note.rect.width}px`,
    height: note.collapsed ? '40px' : `${note.rect.height}px`,
  }
}

function renderMarkdown(note: WorkflowGraphNote): string {
  const cached = markdownCache.get(note.note_id)
  if (cached?.content === note.content) return cached.html
  const html = renderWorkflowNoteMarkdown(note.content)
  markdownCache.set(note.note_id, { content: note.content, html })
  return html
}

function readTone(value: string | number | boolean | null): WorkflowGraphNote['tone'] {
  return typeof value === 'string' && noteToneValues.includes(value as WorkflowGraphNote['tone'])
    ? value as WorkflowGraphNote['tone']
    : 'neutral'
}

function handleEditorKeydown(event: KeyboardEvent, note: WorkflowGraphNote): void {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault()
    commitDraft(note)
    return
  }
  if (event.key === 'Escape') {
    event.preventDefault()
    delete drafts[note.note_id]
    emit('cancelEdit', note.note_id)
  }
}

function handleEditorFocusOut(event: FocusEvent, note: WorkflowGraphNote): void {
  const currentTarget = event.currentTarget
  const nextTarget = event.relatedTarget
  if (currentTarget instanceof HTMLElement && nextTarget instanceof Node && currentTarget.contains(nextTarget)) return
  commitDraft(note)
}

function commitDraft(note: WorkflowGraphNote): void {
  const draft = drafts[note.note_id]
  if (!draft) return
  emit('finishEdit', note.note_id, draft.title, draft.content)
  delete drafts[note.note_id]
}

function collapseLabel(note: WorkflowGraphNote): string {
  return t(note.collapsed ? 'workflowEditor.editor.expandNote' : 'workflowEditor.editor.collapseNote')
}

function lockLabel(note: WorkflowGraphNote): string {
  return t(note.locked ? 'workflowEditor.editor.unlockNote' : 'workflowEditor.editor.lockNote')
}
</script>
