<template>
  <section class="runtime-app-mode">
    <header class="runtime-app-mode__toolbar">
      <div>
        <strong>{{ appMode?.title || snapshot?.display_name || t('workflowEditor.appMode.title') }}</strong>
        <small>{{ snapshot?.workflow_runtime_id }}</small>
      </div>
      <span role="status">{{ t(`workflowEditor.runtimePreview.${status}`) }}</span>
      <span v-if="lastRun">
        {{ t('workflowEditor.appMode.latestRuntimeResult') }}: {{ lastRun.state }} · {{ lastRun.finished_at }}
        <small>{{ lastRun.workflow_run_id }}</small>
      </span>
      <div class="runtime-app-mode__actions">
        <Button variant="secondary" :disabled="loading" @click="load(runtimeId)">{{ t('common.refresh') }}</Button>
        <Button v-if="snapshot" variant="secondary" @click="router.push(`/workflows/runtime/${encodeURIComponent(runtimeId)}/monitor`)">{{ t('workflowEditor.appMode.monitor') }}</Button>
        <Button v-if="snapshot" variant="secondary" @click="router.push(`/workflows/apps/${snapshot.application_id}`)">{{ t('workflowEditor.runtimePreview.back') }}</Button>
      </div>
    </header>

    <p v-if="error || invokeError" role="alert" class="runtime-app-mode__error">{{ invokeError || error }}</p>
    <p v-if="snapshot && !appMode" class="runtime-app-mode__empty">{{ t('workflowEditor.appMode.notConfigured') }}</p>

    <div v-if="snapshot && appMode" class="runtime-app-mode__body">
      <WorkflowAppModeInputPanel
        :inputs="inputs"
        :states="inputStates"
        :running="invoking"
        :disabled="snapshot.observed_state !== 'running' || !snapshot.active"
        @run="invoke"
      />
      <main>
        <p v-if="manualRun" class="runtime-app-mode__manual" role="status">
          {{ t('workflowEditor.appMode.manualRequest') }}: {{ manualRun.state }} · {{ manualRun.workflow_run_id }}
        </p>
        <WorkflowAppModeDisplayGrid
          :config="appMode"
          :displays="displays.previewNodeDisplays.value"
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

import Button from '@/shared/ui/components/Button.vue'
import WorkflowAppModeDisplayGrid from '../components/WorkflowAppModeDisplayGrid.vue'
import WorkflowAppModeInputPanel from '../components/WorkflowAppModeInputPanel.vue'
import WorkflowPreviewViewers from '../components/WorkflowPreviewViewers.vue'
import { useWorkflowAppModeInputs } from '../app-mode/useWorkflowAppModeInputs'
import { useRuntimePreview } from '../preview/useRuntimePreview'
import { invokeWorkflowAppRuntime } from '../services/workflow-runtime.service'
import { orderWorkflowAppContractInputs } from '../app-mode/workflow-app-mode'
import type { WorkflowRun } from '../types'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const runtimeId = computed(() => String(route.params.workflowRuntimeId || ''))
const { snapshot, status, error, loading, lastRun, displays, load } = useRuntimePreview()
const appMode = computed(() => snapshot.value?.app_mode ?? null)
const inputs = computed(() => orderWorkflowAppContractInputs(
  snapshot.value?.application,
  snapshot.value?.contract,
))
const inputForm = useWorkflowAppModeInputs()
const inputStates = inputForm.states
const invoking = ref(false)
const invokeError = ref('')
const manualRun = ref<WorkflowRun | null>(null)

watch(runtimeId, (id) => load(id), { immediate: true })
watch(
  () => snapshot.value?.workflow_app_version_id,
  () => inputForm.initialize(inputs.value),
  { immediate: true },
)

async function invoke(): Promise<void> {
  if (!snapshot.value || !appMode.value || invoking.value) return
  invoking.value = true
  invokeError.value = ''
  manualRun.value = null
  try {
    const payload = await inputForm.build(inputs.value)
    manualRun.value = await invokeWorkflowAppRuntime(runtimeId.value, {
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
.runtime-app-mode { display: flex; flex-direction: column; min-height: calc(100dvh - 32px); gap: 12px; padding: 14px; background: var(--surface-secondary, #f4f7f5); }
.runtime-app-mode__toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 18px; padding: 12px 14px; border: 1px solid var(--border-color, #d6dfd9); border-radius: 12px; background: var(--surface-primary, #fff); }
.runtime-app-mode__toolbar small { display: block; font-size: 11px; color: var(--text-secondary, #69776e); overflow-wrap: anywhere; }
.runtime-app-mode__actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-left: auto; }
.runtime-app-mode__body { display: grid; grid-template-columns: minmax(300px, 360px) minmax(0, 1fr); gap: 14px; align-items: start; }
.runtime-app-mode__body > main { display: grid; gap: 10px; min-width: 0; }
.runtime-app-mode__manual, .runtime-app-mode__error, .runtime-app-mode__empty { margin: 0; padding: 10px 12px; border-radius: 8px; background: var(--surface-primary, #fff); }
.runtime-app-mode__error { color: #b83232; }
.runtime-app-mode__empty { color: var(--text-secondary, #69776e); }
@media (max-width: 960px) { .runtime-app-mode__body { grid-template-columns: 1fr; } }
</style>
