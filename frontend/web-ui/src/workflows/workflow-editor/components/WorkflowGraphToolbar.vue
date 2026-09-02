<template>
  <div
    class="workflow-graph-toolbar"
    role="toolbar"
    @mousedown.stop
    @wheel.stop
    @contextmenu.stop
  >
    <div class="workflow-graph-toolbar__leading">
      <div class="workflow-graph-toolbar__title">
        <div class="workflow-graph-toolbar__title-main">
          <div v-if="titleEditing" class="workflow-graph-toolbar__title-editor">
            <input
              ref="titleInputRef"
              :value="titleDraft"
              :disabled="titleSaving"
              @input="emit('updateTitleDraft', readInputValue($event))"
              @keydown.enter.prevent="emit('commitTitle')"
              @keydown.esc.prevent="emit('cancelTitle')"
            />
            <button
              type="button"
              :title="t('workflowEditor.actions.saveAppName')"
              :aria-label="t('workflowEditor.actions.saveAppName')"
              :disabled="titleSaving || !titleDraft.trim()"
              @mousedown.prevent
              @click="emit('commitTitle')"
            >
              <Check :size="14" />
            </button>
            <button
              type="button"
              :title="t('workflowEditor.actions.cancelAppNameEdit')"
              :aria-label="t('workflowEditor.actions.cancelAppNameEdit')"
              :disabled="titleSaving"
              @mousedown.prevent
              @click="emit('cancelTitle')"
            >
              <X :size="14" />
            </button>
          </div>
          <div v-else class="workflow-graph-toolbar__title-view">
            <h1
              :title="titleEditable ? t('workflowEditor.actions.renameWorkflowApp') : editorTitle"
              @dblclick="titleEditable && emit('beginTitleEdit')"
            >
              {{ editorTitle }}
            </h1>
            <button
              v-if="titleEditable"
              type="button"
              class="workflow-graph-toolbar__title-edit"
              :title="t('workflowEditor.actions.renameWorkflowApp')"
              :aria-label="t('workflowEditor.actions.renameWorkflowApp')"
              @click="emit('beginTitleEdit')"
            >
              <SquarePen :size="14" />
            </button>
          </div>
        </div>
      </div>
      <div v-if="runtimeState || statusMessage" class="workflow-graph-toolbar__meta">
        <span v-if="runtimeState">{{ runtimeState }}</span>
        <span v-if="statusMessage">{{ statusMessage }}</span>
      </div>
    </div>
    <div class="workflow-graph-toolbar__actions">
      <div class="workflow-graph-toolbar__group">
        <Button variant="secondary" :disabled="loading" @click="emit('addNote')">
          <NotebookPen :size="16" />
          {{ t('workflowEditor.editor.note') }}
        </Button>
        <Button :class="{ 'is-active': groupCreateMode }" variant="secondary" :disabled="loading" @click="emit('toggleGroupCreateMode')">
          <BoxSelect :size="16" />
          {{ t('workflowEditor.editor.nodeGroup') }}
        </Button>
        <Button variant="secondary" :disabled="loading" @click="emit('refresh')">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </div>
      <div class="workflow-graph-toolbar__group">
        <Button variant="secondary" :disabled="previewDisabled" :loading="previewing" @click="emit('preview')">
          <Play :size="16" />
          {{ t('workflowEditor.actions.previewRun') }}
        </Button>
        <Button variant="secondary" :disabled="publishDisabled" :loading="publishing" @click="emit('publish')">
          <Upload :size="16" />
          {{ t('workflowEditor.actions.publishWorkflowApp') }}
        </Button>
      </div>
      <div class="workflow-graph-toolbar__group">
        <Button
          class="workflow-graph-toolbar__inspector-action"
          :class="{ 'is-active': !inspectorCollapsed }"
          variant="secondary"
          :title="inspectorCollapsed ? t('workflowEditor.editor.showInspector') : t('workflowEditor.editor.hideInspector')"
          :aria-label="inspectorCollapsed ? t('workflowEditor.editor.showInspector') : t('workflowEditor.editor.hideInspector')"
          :aria-pressed="!inspectorCollapsed"
          @click="emit('toggleInspector')"
        >
          <PanelRightOpen v-if="inspectorCollapsed" :size="16" />
          <PanelRightClose v-else :size="16" />
          {{ t('workflowEditor.editor.inspectorTitle') }}
        </Button>
      </div>
      <Button variant="primary" :disabled="saveDisabled" :loading="saving" @click="emit('save')">
        <Save :size="16" />
        {{ t('workflowEditor.actions.saveWorkflowApp') }}
      </Button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { BoxSelect, Check, NotebookPen, PanelRightClose, PanelRightOpen, Play, RefreshCw, Save, SquarePen, Upload, X } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import Button from '@/shared/ui/components/Button.vue'

const props = defineProps<{
  editorTitle: string
  titleDraft: string
  titleEditing: boolean
  titleSaving: boolean
  titleEditable: boolean
  runtimeState: string | null
  statusMessage: string | null
  loading: boolean
  previewDisabled: boolean
  previewing: boolean
  publishDisabled: boolean
  publishing: boolean
  saveDisabled: boolean
  saving: boolean
  groupCreateMode: boolean
  inspectorCollapsed: boolean
}>()

const emit = defineEmits<{
  beginTitleEdit: []
  updateTitleDraft: [value: string]
  commitTitle: []
  cancelTitle: []
  refresh: []
  toggleGroupCreateMode: []
  addNote: []
  preview: []
  publish: []
  save: []
  toggleInspector: []
}>()

const { t } = useI18n()
const titleInputRef = ref<HTMLInputElement | null>(null)

watch(
  () => props.titleEditing,
  async (editing) => {
    if (!editing) return
    await nextTick()
    titleInputRef.value?.focus()
    titleInputRef.value?.select()
  },
)

function readInputValue(event: Event): string {
  const target = event.target
  return target instanceof HTMLInputElement ? target.value : ''
}
</script>
