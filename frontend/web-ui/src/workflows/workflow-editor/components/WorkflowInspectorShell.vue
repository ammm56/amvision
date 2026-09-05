<template>
  <Transition name="workflow-inspector">
    <aside v-if="!collapsed" class="workflow-graph-floating-panel workflow-graph-inspector-panel" @mousedown.stop @contextmenu.stop>
    <div class="workflow-graph-panel__header">
      <div>
        <h2>{{ t('workflowEditor.editor.inspectorTitle') }}</h2>
      </div>
      <div class="workflow-graph-panel__tools">
        <button
          type="button"
          class="workflow-graph-panel__icon-button"
          :title="t('workflowEditor.editor.hideInspector')"
          :aria-label="t('workflowEditor.editor.hideInspector')"
          @click="emit('collapse')"
        >
          <PanelRightClose :size="15" />
        </button>
      </div>
    </div>

    <div class="workflow-graph-inspector-content">
      <WorkflowNewAppDraftPanel
        v-if="showNewAppDraftPanel"
        :draft="newWorkflowAppDraft"
        :save-blocker="newWorkflowAppSaveBlocker"
        @update-display-name="emit('updateNewAppDisplayName', $event)"
        @update-application-id="emit('updateNewAppApplicationId', $event)"
        @update-graph-id="emit('updateNewAppGraphId', $event)"
        @update-graph-version="emit('updateNewAppGraphVersion', $event)"
        @update-description="emit('updateNewAppDescription', $event)"
        @normalize-application-id="emit('normalizeNewAppApplicationId', $event)"
        @normalize-graph-id="emit('normalizeNewAppGraphId', $event)"
        @normalize-graph-version="emit('normalizeNewAppGraphVersion', $event)"
      />

      <WorkflowNodeDetailPanel
        v-if="inspectorDetail.kind === 'node'"
        :node="inspectorDetail.node"
        :read-title="readGraphNodeTitle"
        @update-enabled="(node, event) => emit('updateNodeEnabled', node, event)"
      />
      <WorkflowEdgeDetailPanel
        v-else-if="inspectorDetail.kind === 'edge'"
        :edge="inspectorDetail.edge"
        @delete-edge="emit('deleteSelectedEdge')"
      />
      <WorkflowNoteDetailPanel
        v-else-if="inspectorDetail.kind === 'note'"
        :note="inspectorDetail.note"
        @update-title="emit('updateNoteTitle', inspectorDetail.note, $event)"
        @update-content="emit('updateNoteContent', inspectorDetail.note, $event)"
        @update-tone="emit('updateNoteTone', inspectorDetail.note, $event)"
        @toggle-collapsed="emit('toggleNoteCollapsed', inspectorDetail.note)"
        @toggle-locked="emit('toggleNoteLocked', inspectorDetail.note)"
        @copy="emit('copyNote', inspectorDetail.note.note_id)"
        @delete="emit('deleteNote', inspectorDetail.note.note_id)"
      />
      <WorkflowPublicBindingEditorPanel
        v-else-if="inspectorDetail.kind === 'boundary'"
        :title="inspectorDetail.title"
        :bindings="inspectorDetail.bindings"
        :read-display-name="bindingDisplayName"
        :read-kind-options="bindingKindSelectOptions"
        :get-payload-type-id="getBindingPayloadTypeId"
        @update-binding-id="(binding, event) => emit('updateBindingId', binding, event)"
        @update-display-name="(binding, event) => emit('updateBindingDisplayName', binding, event)"
        @update-kind="(binding, value) => emit('updateBindingKind', binding, value)"
        @update-required="(binding, event) => emit('updateBindingRequired', binding, event)"
        @update-description="(binding, event) => emit('updateBindingDescription', binding, event)"
        @update-request-schema="(binding, event) => emit('updateBindingRequestSchema', binding, event)"
        @update-media-types="(binding, event) => emit('updateBindingMediaTypes', binding, event)"
        @update-charset="(binding, event) => emit('updateBindingCharset', binding, event)"
        @update-positive-limit="(binding, fieldName, event) => emit('updateBindingPositiveLimit', binding, fieldName, event)"
        @delete-binding="emit('deleteApplicationBinding', $event)"
      />
      <WorkflowApplicationSummaryPanel
        v-else-if="inspectorDetail.kind === 'application' && !showNewAppDraftPanel"
        :application-id="inspectorDetail.applicationId"
        :template-input-text="inspectorDetail.templateInputText"
        :template-output-text="inspectorDetail.templateOutputText"
        :empty-text="t('common.noValue')"
        :preview-run-text="inspectorDetail.previewRunText"
      />

      <WorkflowAppContractPanel
        v-if="showAppContractPanel && (showNewAppDraftPanel || inspectorDetail.kind === 'application')"
        :input-bindings="appInputBindings"
        :output-bindings="appOutputBindings"
        @add-request-json="emit('addRequestJson')"
        @add-request-value="emit('addRequestValue')"
        @add-request-text="emit('addRequestText')"
        @add-request-file="emit('addRequestFile')"
        @add-request-files="emit('addRequestFiles')"
        @add-request-image-ref="emit('addRequestImageRef')"
        @add-request-image-base64="emit('addRequestImageBase64')"
      />

      <WorkflowPreviewInputPanel
        v-if="showAppContractPanel"
        :bindings="previewInputBindings"
        :states="previewInputState"
        :blocking-messages="previewBlockingMessages"
        :image-ref-transport-kind-options="imageRefTransportKindOptions"
        :get-payload-type-id="getBindingPayloadTypeId"
        @add-value-field="emit('addPreviewValueField', $event)"
        @remove-value-field="(bindingId, fieldId) => emit('removePreviewValueField', bindingId, fieldId)"
        @set-image-ref-transport-kind="(bindingId, value) => emit('setPreviewImageRefTransportKind', bindingId, value)"
      />

      <WorkflowPreviewRunResultPanel
        v-if="lastPreviewRun"
        :preview-run="lastPreviewRun"
        :badge-tone="readPreviewRunBadgeTone(lastPreviewRun.state)"
        :status-label="formatPreviewRunStatusLabel(lastPreviewRun.state)"
        :created-at-text="formatSystemDateTime(lastPreviewRun.created_at)"
        @open-json="(title, value, statusText) => emit('openPreviewJson', title, value, statusText)"
      />
    </div>
    </aside>
  </Transition>
</template>

<script setup lang="ts">
import { PanelRightClose } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { formatSystemDateTime } from '@/shared/formatters/date-time'
import WorkflowAppContractPanel from './WorkflowAppContractPanel.vue'
import WorkflowApplicationSummaryPanel from './WorkflowApplicationSummaryPanel.vue'
import WorkflowEdgeDetailPanel from './WorkflowEdgeDetailPanel.vue'
import WorkflowNewAppDraftPanel from './WorkflowNewAppDraftPanel.vue'
import WorkflowNodeDetailPanel from './WorkflowNodeDetailPanel.vue'
import WorkflowNoteDetailPanel from './WorkflowNoteDetailPanel.vue'
import WorkflowPreviewInputPanel from './WorkflowPreviewInputPanel.vue'
import WorkflowPreviewRunResultPanel from './WorkflowPreviewRunResultPanel.vue'
import WorkflowPublicBindingEditorPanel from './WorkflowPublicBindingEditorPanel.vue'
import { formatPreviewRunStatusLabel, readPreviewRunBadgeTone } from '../preview/useWorkflowPreviewValidation'
import type { NewWorkflowAppDraftState } from '../documents/useWorkflowNewAppDraft'
import type { WorkflowInspectorDetail } from '../panels/useWorkflowInspectorViewModel'
import type { PreviewInputState, PreviewSelectOption, PreviewSelectValue } from '../preview/useWorkflowPreviewInputs'
import type { WorkflowGraphNodeView } from '../nodes/useWorkflowGraphNodeViews'
import type {
  FlowApplicationBinding,
  WorkflowGraphNote,
  WorkflowPreviewRun,
} from '../types'

defineProps<{
  collapsed: boolean
  showNewAppDraftPanel: boolean
  newWorkflowAppDraft: NewWorkflowAppDraftState
  newWorkflowAppSaveBlocker: string | null
  showAppContractPanel: boolean
  appInputBindings: FlowApplicationBinding[]
  appOutputBindings: FlowApplicationBinding[]
  inspectorDetail: WorkflowInspectorDetail<WorkflowGraphNodeView>
  readGraphNodeTitle: (node: WorkflowGraphNodeView) => string
  bindingDisplayName: (binding: FlowApplicationBinding) => string
  bindingKindSelectOptions: (binding: FlowApplicationBinding) => Array<{ label: string; value: string | number | boolean | null; description?: string }>
  getBindingPayloadTypeId: (binding: FlowApplicationBinding) => string
  previewInputBindings: FlowApplicationBinding[]
  previewInputState: Record<string, PreviewInputState>
  previewBlockingMessages: string[]
  imageRefTransportKindOptions: PreviewSelectOption[]
  lastPreviewRun: WorkflowPreviewRun | null
}>()

const emit = defineEmits<{
  collapse: []
  updateNewAppDisplayName: [event: Event]
  updateNewAppApplicationId: [event: Event]
  updateNewAppGraphId: [event: Event]
  updateNewAppGraphVersion: [event: Event]
  updateNewAppDescription: [event: Event]
  normalizeNewAppApplicationId: [event: Event]
  normalizeNewAppGraphId: [event: Event]
  normalizeNewAppGraphVersion: [event: Event]
  addRequestJson: []
  addRequestValue: []
  addRequestText: []
  addRequestFile: []
  addRequestFiles: []
  addRequestImageRef: []
  addRequestImageBase64: []
  updateNodeEnabled: [node: WorkflowGraphNodeView, event: Event]
  deleteSelectedEdge: []
  updateNoteTitle: [note: WorkflowGraphNote, value: string]
  updateNoteContent: [note: WorkflowGraphNote, value: string]
  updateNoteTone: [note: WorkflowGraphNote, tone: WorkflowGraphNote['tone']]
  toggleNoteCollapsed: [note: WorkflowGraphNote]
  toggleNoteLocked: [note: WorkflowGraphNote]
  copyNote: [noteId: string]
  deleteNote: [noteId: string]
  updateBindingId: [binding: FlowApplicationBinding, event: Event]
  updateBindingDisplayName: [binding: FlowApplicationBinding, event: Event]
  updateBindingKind: [binding: FlowApplicationBinding, value: string | number | boolean | null]
  updateBindingRequired: [binding: FlowApplicationBinding, event: Event]
  updateBindingDescription: [binding: FlowApplicationBinding, event: Event]
  updateBindingRequestSchema: [binding: FlowApplicationBinding, event: Event]
  updateBindingMediaTypes: [binding: FlowApplicationBinding, event: Event]
  updateBindingCharset: [binding: FlowApplicationBinding, event: Event]
  updateBindingPositiveLimit: [binding: FlowApplicationBinding, fieldName: 'max_inline_bytes' | 'max_file_bytes' | 'max_files', event: Event]
  deleteApplicationBinding: [binding: FlowApplicationBinding]
  addPreviewValueField: [bindingId: string]
  removePreviewValueField: [bindingId: string, fieldId: string]
  setPreviewImageRefTransportKind: [bindingId: string, value: PreviewSelectValue]
  openPreviewJson: [title: string, value: unknown, statusText: string | null]
}>()

const { t } = useI18n()
</script>
