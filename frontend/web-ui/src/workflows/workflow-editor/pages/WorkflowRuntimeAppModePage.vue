<template>
  <section class="runtime-app-mode">
    <header class="runtime-app-mode__toolbar">
      <div>
        <strong>{{ appMode?.title || snapshot?.display_name || t('workflowEditor.appMode.title') }}</strong>
      </div>
      <span v-if="lastRun" class="runtime-app-mode__result">
        <strong>{{ t('workflowEditor.appMode.runtimeResult') }}</strong>
        <span>{{ runStateLabel }}</span>
        <time :datetime="lastRun.finished_at">{{ formatSystemDateTime(lastRun.finished_at) }}</time>
      </span>
      <div class="runtime-app-mode__actions">
        <Button variant="secondary" :disabled="loading" @click="load(runtimeId)">{{ t('common.refresh') }}</Button>
        <Button v-if="snapshot" variant="secondary" @click="router.push(`/workflows/runtime/${encodeURIComponent(runtimeId)}/monitor`)">{{ t('workflowEditor.runtimePreview.title') }}</Button>
        <Button v-if="snapshot" variant="secondary" @click="router.push(`/workflows/apps/${snapshot.application_id}`)">{{ t('workflowEditor.runtimePreview.back') }}</Button>
      </div>
    </header>

    <p v-if="error || invokeError" role="alert" class="runtime-app-mode__error">{{ invokeError || error }}</p>
    <p v-if="snapshot && !appMode" class="runtime-app-mode__empty">{{ t('workflowEditor.appMode.notConfigured') }}</p>

    <div v-if="snapshot && appMode" class="runtime-app-mode__body">
      <WorkflowAppModeInputPanel
        :inputs="inputs"
        :labels="inputLabels"
        :states="inputStates"
        :running="invoking"
        :disabled="snapshot.observed_state !== 'running' || !snapshot.active"
        @run="invoke"
      />
      <main>
        <WorkflowAppModeDisplayGrid
          :config="appMode"
          :displays="displays.previewNodeDisplays.value"
          :node-titles="displayNodeTitles"
          :has-run="Boolean(lastRun)"
          @open-display="displays.openPreviewDisplayViewer"
          @open-image="displays.openImageViewer"
        />
      </main>
    </div>

    <WorkflowPreviewViewers
      :image="displays.activeImageViewer.value"
      :table="displays.activePreviewTable.value"
      :json="displays.activePreviewJson.value"
      preview-disabled
      @close-image="displays.closeImageViewer"
      @close-table="displays.closePreviewTableViewer"
      @close-json="displays.closePreviewJsonViewer"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import WorkflowAppModeDisplayGrid from '../components/WorkflowAppModeDisplayGrid.vue'
import WorkflowAppModeInputPanel from '../components/WorkflowAppModeInputPanel.vue'
import WorkflowPreviewViewers from '../components/WorkflowPreviewViewers.vue'
import { useWorkflowAppModeInputs } from '../app-mode/useWorkflowAppModeInputs'
import { useRuntimePreview } from '../preview/useRuntimePreview'
import { invokeWorkflowAppRuntime } from '../services/workflow-runtime.service'
import { orderWorkflowAppContractInputs } from '../app-mode/workflow-app-mode'
import type { WorkflowGraphNode } from '../types'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const STANDARD_INPUT_LABEL_KEYS: Record<string, string> = {
  request_image_ref: 'workflowEditor.appMode.inputImage',
  request_image_base64: 'workflowEditor.appMode.inputImageBase64',
  request_json: 'workflowEditor.appMode.inputJson',
  request_text: 'workflowEditor.appMode.inputText',
  request_file: 'workflowEditor.appMode.inputFile',
  request_files: 'workflowEditor.appMode.inputFiles',
}

const PREVIEW_NODE_LABELS: Record<string, { key: string; defaultTitle: string }> = {
  'core.io.image-preview': { key: 'workflowEditor.appMode.previewImage', defaultTitle: 'Image Preview' },
  'core.io.value-preview': { key: 'workflowEditor.appMode.previewValue', defaultTitle: 'Value Preview' },
  'core.io.table-preview': { key: 'workflowEditor.appMode.previewTable', defaultTitle: 'Table Preview' },
  'core.io.frame-window-preview': { key: 'workflowEditor.appMode.previewFrameWindow', defaultTitle: 'Frame Window Preview' },
}

const LOCALIZED_RUN_STATES = new Set(['queued', 'running', 'paused', 'succeeded', 'failed', 'timed_out', 'cancelled'])

const runtimeId = computed(() => String(route.params.workflowRuntimeId || ''))
const { snapshot, error, loading, lastRun, displays, load } = useRuntimePreview()
const appMode = computed(() => snapshot.value?.app_mode ?? null)
const inputs = computed(() => orderWorkflowAppContractInputs(
  snapshot.value?.application,
  snapshot.value?.contract,
))
const inputLabels = computed<Record<string, string>>(() => Object.fromEntries(
  inputs.value.map((input) => [input.binding_id, resolveInputLabel(input.binding_id, input.template_port_id)]),
))
const displayNodeTitles = computed<Record<string, string>>(() => Object.fromEntries(
  (snapshot.value?.template.nodes ?? []).map((node) => [node.node_id, resolveNodeTitle(node)]),
))
const runStateLabel = computed(() => {
  const state = lastRun.value?.state ?? ''
  return LOCALIZED_RUN_STATES.has(state) ? t(`tasks.status.${state}`) : humanizeIdentifier(state)
})
const inputForm = useWorkflowAppModeInputs()
const inputStates = inputForm.states
const invoking = ref(false)
const invokeError = ref('')

watch(runtimeId, (id) => load(id), { immediate: true })
watch(
  () => snapshot.value?.workflow_app_version_id,
  () => inputForm.initialize(inputs.value),
  { immediate: true },
)

function resolveInputLabel(bindingId: string, templatePortId: string): string {
  const standardKey = STANDARD_INPUT_LABEL_KEYS[bindingId]
  if (standardKey) return t(standardKey)
  const templateInput = snapshot.value?.template.template_inputs.find((input) => input.input_id === templatePortId)
  const configuredLabel = readText(templateInput?.display_name)
  return configuredLabel && configuredLabel !== bindingId ? configuredLabel : humanizeIdentifier(bindingId)
}

function resolveNodeTitle(node: WorkflowGraphNode): string {
  const localized = PREVIEW_NODE_LABELS[node.node_type_id]
  const definitionTitle = readText(snapshot.value?.node_definitions?.find(
    (definition) => definition.node_type_id === node.node_type_id,
  )?.display_name)
  const configuredTitle = readText(node.ui_state.title) || readText(node.parameters.title)
  if (configuredTitle && configuredTitle !== localized?.defaultTitle && configuredTitle !== definitionTitle) {
    return configuredTitle
  }
  if (localized) return t(localized.key)
  return configuredTitle || definitionTitle || humanizeIdentifier(node.node_type_id)
}

function readText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function humanizeIdentifier(value: string): string {
  const leaf = value.split('.').filter(Boolean).at(-1) || value
  return leaf.replace(/[_-]+/g, ' ').replace(/\b\w/g, (character) => character.toUpperCase()).trim()
}

async function invoke(): Promise<void> {
  if (!snapshot.value || !appMode.value || invoking.value) return
  invoking.value = true
  invokeError.value = ''
  try {
    const payload = await inputForm.build(inputs.value)
    await invokeWorkflowAppRuntime(runtimeId.value, {
      ...payload,
      executionMetadata: { workflow_run_record_mode: 'none' },
    })
  } catch (cause) {
    invokeError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    invoking.value = false
  }
}
</script>

<style scoped>
.runtime-app-mode {
  --graph-node-padding-x: 0;
  --graph-line: var(--am-graph-node-border);
  --graph-panel: var(--am-graph-panel);
  --graph-panel-soft: var(--am-graph-panel-soft);
  --graph-text: var(--am-graph-text);
  --graph-text-strong: var(--am-graph-text-strong);
  --graph-muted: var(--am-graph-text-muted);
  --graph-accent: var(--am-graph-selected);

  display: flex;
  flex-direction: column;
  min-height: calc(100dvh - 32px);
  gap: var(--am-space-md);
  padding: var(--am-space-lg);
  background: var(--am-page);
  color: var(--am-text);
}

.runtime-app-mode__toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--am-space-xl);
  min-height: 58px;
  padding: var(--am-space-md) var(--am-space-lg);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  background: var(--am-surface);
}

.runtime-app-mode__toolbar > div:first-child > strong {
  color: var(--am-text-strong);
  font-size: 17px;
}

.runtime-app-mode__result {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--am-space-sm);
  color: var(--am-text-muted);
  font-size: 13px;
}

.runtime-app-mode__result strong {
  color: var(--am-text);
}

.runtime-app-mode__result span::after {
  content: '\00b7';
  margin-left: var(--am-space-sm);
  color: var(--am-text-disabled);
}

.runtime-app-mode__actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--am-space-sm);
  margin-left: auto;
}

.runtime-app-mode__body {
  display: grid;
  grid-template-columns: minmax(300px, 360px) minmax(0, 1fr);
  gap: var(--am-space-lg);
  align-items: start;
}

.runtime-app-mode__body > main {
  display: grid;
  gap: var(--am-space-md);
  min-width: 0;
}

.runtime-app-mode__error,
.runtime-app-mode__empty {
  margin: 0;
  padding: var(--am-space-md) var(--am-space-lg);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  background: var(--am-surface);
}

.runtime-app-mode__empty {
  color: var(--am-text-muted);
}

.runtime-app-mode__error {
  border-color: var(--am-danger-border);
  background: var(--am-danger-surface);
  color: var(--am-danger-text);
}

@media (max-width: 960px) {
  .runtime-app-mode__body {
    grid-template-columns: 1fr;
  }
}
</style>
