<template>
  <section class="runtime-monitor">
    <header class="runtime-monitor__toolbar">
      <div><strong>{{ snapshot?.display_name || t('workflowEditor.runtimePreview.title') }}</strong>
        <small>{{ snapshot?.workflow_runtime_id }}</small></div>
      <span role="status">{{ t(`workflowEditor.runtimePreview.${status}`) }}</span>
      <span v-if="lastRun">{{ lastRun.state }} · {{ lastRun.finished_at }}<small>{{ lastRun.workflow_run_id }}</small></span>
      <div class="runtime-monitor__actions">
        <Button variant="secondary" :disabled="loading" @click="load(runtimeId)">{{ t('common.refresh') }}</Button>
        <Button variant="secondary" @click="zoom = Math.max(.2, +(zoom - .1).toFixed(1))">−</Button><span>{{ Math.round(zoom * 100) }}%</span>
        <Button variant="secondary" @click="zoom = Math.min(2, +(zoom + .1).toFixed(1))">+</Button>
        <Button v-if="snapshot" variant="secondary" @click="router.push(`/workflows/apps/${snapshot.application_id}`)">{{ t('workflowEditor.runtimePreview.back') }}</Button>
      </div>
    </header>
    <p v-if="error" role="alert" class="runtime-monitor__error">{{ error }}</p>
    <p v-if="nodeDefinitionWarning" class="runtime-monitor__warning">{{ nodeDefinitionWarning }}</p>
    <small v-if="snapshot" class="runtime-monitor__version">{{ t('workflowEditor.runtimePreview.readonly') }} · {{ snapshot.workflow_app_version_id }} · generation {{ snapshot.runtime_generation }}</small>
    <WorkflowRuntimeCanvas v-if="snapshot" :template="snapshot.template" :application="snapshot.application" :definitions="definitions" :zoom="zoom"
      :displays="displays.previewNodeDisplays.value" :invocations="invocations"
      @open-display="displays.openPreviewDisplayViewer" @open-image="displays.openImageViewer" />
    <WorkflowPreviewViewers :image="displays.activeImageViewer.value" :table="displays.activePreviewTable.value" :json="displays.activePreviewJson.value" preview-disabled
      @close-image="displays.closeImageViewer" @close-table="displays.closePreviewTableViewer" @close-json="displays.closePreviewJsonViewer" />
  </section>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTranslation } from '@/platform/i18n'
import Button from '@/shared/ui/components/Button.vue'
import WorkflowRuntimeCanvas from '../components/WorkflowRuntimeCanvas.vue'
import WorkflowPreviewViewers from '../components/WorkflowPreviewViewers.vue'
import { useRuntimePreview } from '../preview/useRuntimePreview'

const route = useRoute(), router = useRouter(), { t } = useTranslation()
const runtimeId = computed(() => String(route.params.workflowRuntimeId || ''))
const { snapshot, status, error, loading, lastRun, invocations, displays, load } = useRuntimePreview()
const definitions = computed(() => snapshot.value?.node_definitions ?? [])
const nodeDefinitionWarning = computed(() => (snapshot.value?.node_definition_warnings ?? []).length
  ? t('workflowEditor.runtimePreview.nodeDefinitionWarning')
  : '')
const zoom = ref(.8)
watch(runtimeId, (id) => load(id), { immediate: true })
</script>

<style scoped>
.runtime-monitor { --graph-node-padding-x: 12px; --graph-line: var(--am-graph-node-border); --graph-panel-soft: var(--am-graph-panel-soft); --graph-text: var(--am-graph-text); --graph-muted: var(--am-graph-text-muted); display: flex; flex-direction: column; height: calc(100dvh - 32px); min-height: 480px; gap: 8px; padding: 12px; }
.runtime-monitor__toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 18px; }
.runtime-monitor__toolbar small { display: block; font-size: 11px; color: var(--text-secondary, #69776e); overflow-wrap: anywhere; }
.runtime-monitor__toolbar > div, .runtime-monitor__toolbar > span { min-width: 0; max-width: 100%; overflow-wrap: anywhere; }
.runtime-monitor__actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-left: auto; }
.runtime-monitor__version { color: var(--text-secondary, #69776e); overflow-wrap: anywhere; }
.runtime-monitor__error { color: #b83232; margin: 0; }
.runtime-monitor__warning { color: #8a5b00; margin: 0; }
</style>
