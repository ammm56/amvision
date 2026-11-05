<template>
  <ConfirmDialog :title="text(selecting ? 'selectRange' : 'sdk')" size="wide" scroll-body allow-close-while-busy :confirm-label="text(selecting ? 'applySelection' : 'download')" :cancel-label="text('close')" confirm-variant="primary" :busy="busy" :confirm-disabled="!resourcesReady || (!selecting && (!preview?.files.length || !previewIsCurrent))" @cancel="close" @confirm="selecting ? refreshPreview() : download()">
    <template v-if="selecting" #leading-actions><Button :disabled="busy || !preview" @click="returnPreview">{{ text('returnPreview') }}</Button></template>
    <InlineError v-if="error" :message="error" />
    <p v-if="busy" role="status" class="sdk-note">{{ text(generating ? 'sdkGenerating' : 'sdkReading') }}<span v-if="generating"> {{ text('sdkClosedNote') }}</span></p>
    <Button v-if="error" :disabled="busy" @click="initialize">{{ text('refresh') }}</Button>
    <div v-if="!selecting" class="sdk-heading"><div><small>{{ text('name') }}</small><strong>{{ projectName(project) }}</strong></div><div><small>{{ text('server') }}</small><span>{{ preview?.base_api_url || '—' }}</span></div></div>
    <div v-if="preview && !selecting" class="sdk-counts"><span>Workflow Runtime <strong>{{ preview.workflow_runtime_count }}</strong></span><span>Trigger <strong>{{ preview.trigger_source_count }}</strong></span><span>{{ text('models') }} <strong>{{ preview.model_deployment_count }}</strong></span></div>
    <div v-if="!selecting" class="sdk-section-heading"><h3>{{ text('range') }}</h3><Button v-if="!selecting" size="sm" @click="selecting = true">{{ text('adjust') }}</Button></div>
    <template v-if="selecting">
      <div class="sdk-range-heading"><div><small>{{ text('name') }}</small><strong>{{ projectName(project) }}</strong></div><input v-model="query" :placeholder="text('searchResources')" :aria-label="text('searchResources')" class="sdk-search" /></div>
      <div class="sdk-selection-tools"><span>{{ text('selected') }} {{ selectedCount }}</span><Button size="sm" variant="ghost" @click="toggleVisible(true)">{{ text('selectVisible') }}</Button><Button size="sm" variant="ghost" @click="toggleVisible(false)">{{ text('unselect') }}</Button></div>
      <div class="sdk-resource-list"><template v-for="group in resourceGroups" :key="group.kind"><h4 v-if="group.items.length" class="sdk-group-heading">{{ group.label }} <span>{{ group.selected }} / {{ group.total }}</span></h4><label v-for="resource in group.items" :key="resource.id" class="sdk-resource"><input type="checkbox" :checked="selected.has(resource.id) || requiredRuntimes.has(resource.id)" :disabled="requiredRuntimes.has(resource.id)" @change="toggle(resource.id, ($event.target as HTMLInputElement).checked)" /><span><strong>{{ resource.name }}</strong><small>{{ resource.id }}</small><small v-if="requiredRuntimes.has(resource.id)">{{ text('dependency') }}</small></span><span class="resource-kind">{{ resource.kind === 'runtime' ? 'Runtime' : resource.kind === 'trigger' ? 'Trigger' : text('deployments') }}</span></label></template>
      <p v-if="!visibleResources.length" class="sdk-note">{{ text(query ? 'noMatchesResources' : 'noResources') }} <Button v-if="query" size="sm" @click="query = ''">{{ text('clear') }}</Button></p></div>
      <PaginationControls v-if="visibleResources.length > 50" :offset="resourceOffset" :limit="50" :item-count="pageResources.length" :total-count="visibleResources.length" :has-more="resourceOffset + 50 < visibleResources.length" @previous="resourceOffset -= 50" @next="resourceOffset += 50" />
    </template>
    <template v-else><p v-if="resourcesReady" class="sdk-note">{{ !selectedCount ? text('noResources') : selectedCount === resources.length ? text('allResources') : `${text('selected')} ${selectedCount}` }}</p>
      <div v-if="resourcesReady && !resources.length" class="project-actions"><Button v-if="canOpenApps" @click="openResource('/workflows/apps')">{{ text('openApps') }}</Button><Button v-if="canOpenDeployments" @click="openResource('/deployments')">{{ text('openDeployments') }}</Button></div>
      <div class="sdk-options"><label><input v-model="includeDisabled" :disabled="busy" type="checkbox" @change="refreshPreview" />{{ text('disabledTriggers') }}</label><label><input v-model="includeToken" :disabled="busy" type="checkbox" @change="refreshPreview" />{{ text('token') }}</label><label>{{ text('modelMode') }}<SelectField v-model="modelMode" :disabled="busy" :options="modeOptions" @update:model-value="refreshPreview" /></label></div>
      <h3>{{ text('files') }}</h3><div v-for="file in preview?.files.slice(fileOffset, fileOffset + 50)" :key="file.path" class="sdk-file"><FileText :size="18" /><span>{{ file.path }}</span><small>{{ file.count }}</small></div>
      <PaginationControls v-if="(preview?.files.length || 0) > 50" :offset="fileOffset" :limit="50" :item-count="preview!.files.slice(fileOffset, fileOffset + 50).length" :total-count="preview!.files.length" :has-more="fileOffset + 50 < preview!.files.length" @previous="fileOffset -= 50" @next="fileOffset += 50" />
      <p v-for="note in preview?.notes" :key="note" class="sdk-note">{{ note }}</p><p v-for="warning in preview?.warnings" :key="warning" class="sdk-warning">{{ warning }}</p>
    </template>
  </ConfirmDialog>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { useFeedbackStore } from '@/app/stores/feedback.store'
import { canAccessPath } from '@/platform/auth/page-access'
import { FileText } from '@lucide/vue'
import type { ProjectCatalogItem } from '@/shared/contracts'
import { downloadSdkConfigPackage, listSdkResources, previewSdkConfigPackage, type SdkResource, type SdkConfigPackagePreview } from '../services/project.service'
import { projectError, projectName, useProjectText } from '../project-workspace'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import SelectField from '@/shared/ui/components/Select.vue'
const props = defineProps<{ project: ProjectCatalogItem }>()
const emit = defineEmits<{ close: [] }>()
const text = useProjectText()
const feedback = useFeedbackStore()
const router = useRouter(), store = useProjectStore(), session = useSessionStore()
const canOpenApps = computed(() => canAccessPath(session.currentUser, '/workflows/apps') && session.hasScopes(['workflows:read']))
const canOpenDeployments = computed(() => canAccessPath(session.currentUser, '/deployments') && session.hasScopes(['models:read']))
function openResource(path: string) { if (!canAccessPath(session.currentUser, path)) return; store.selectedProjectId = props.project.project_id; store.selectedSummary = null; close(); void router.push(path) }
const resources = ref<SdkResource[]>([]), selected = ref(new Set<string>()), query = ref(''), selecting = ref(false)
const busy = ref(false), error = ref(''), preview = ref<SdkConfigPackagePreview | null>(null), includeToken = ref(true), includeDisabled = ref(true)
const generating = ref(false)
const resourcesReady = ref(false), resourceOffset = ref(0), fileOffset = ref(0)
const controller = new AbortController()
watch(query, () => { resourceOffset.value = 0 })
let appliedSelection = new Set<string>(), active = true
function close() { active = false; controller.abort(); emit('close') }
// 子视图替换会移除触发按钮，显式把键盘焦点交给新视图。
watch(selecting, value => {
  document.querySelector<HTMLElement>(value ? '.sdk-search' : '.confirm-dialog [data-confirm-cancel]')?.focus()
}, { flush: 'post' })
const modelMode = ref('sync'), previewInput = ref('')
const modeOptions = computed(() => [{ value: 'sync', label: text('sync') }, { value: 'async', label: text('async') }, { value: 'both', label: text('both') }])
const previewIsCurrent = computed(() => previewInput.value === JSON.stringify(input()))
function returnPreview() { selected.value = new Set(appliedSelection); selecting.value = false }
const requiredRuntimes = computed(() => new Set(resources.value.filter(item => item.kind === 'trigger' && selected.value.has(item.id)).map(item => item.runtime_id!)))
const effectiveSelected = computed(() => new Set([...selected.value, ...requiredRuntimes.value]))
const selectedCount = computed(() => effectiveSelected.value.size)
const visibleResources = computed(() => resources.value.filter(item => `${item.name} ${item.id}`.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase())))
const pageResources = computed(() => visibleResources.value.slice(resourceOffset.value, resourceOffset.value + 50))
const resourceGroups = computed(() => (['runtime', 'trigger', 'deployment'] as const).map(kind => ({ kind, label: kind === 'runtime' ? 'Workflow Runtime' : kind === 'trigger' ? 'Trigger' : text('deployments'), items: pageResources.value.filter(item => item.kind === kind), total: resources.value.filter(item => item.kind === kind).length, selected: resources.value.filter(item => item.kind === kind && effectiveSelected.value.has(item.id)).length })))
function toggle(id: string, checked: boolean) { const next = new Set(selected.value); checked ? next.add(id) : next.delete(id); selected.value = next }
function toggleVisible(checked: boolean) { for (const item of pageResources.value) toggle(item.id, checked) }
function input() { return { include_access_token: includeToken.value, include_disabled_trigger_sources: includeDisabled.value,
  model_runtime_modes: (modelMode.value === 'both' ? ['sync', 'async'] : [modelMode.value]) as Array<'sync' | 'async'>,
  runtime_ids: selected.value.size === resources.value.length ? undefined : resources.value.filter(item => item.kind === 'runtime' && effectiveSelected.value.has(item.id)).map(item => item.id),
  trigger_source_ids: selected.value.size === resources.value.length ? undefined : resources.value.filter(item => item.kind === 'trigger' && selected.value.has(item.id)).map(item => item.id),
  deployment_ids: selected.value.size === resources.value.length ? undefined : resources.value.filter(item => item.kind === 'deployment' && selected.value.has(item.id)).map(item => item.id) } }
async function refreshPreview() {
  if (busy.value || !resourcesReady.value) return
  busy.value = true; error.value = ''
  const request = input()
  previewInput.value = ''
  try { const next = await previewSdkConfigPackage(props.project.project_id, request, controller.signal); if (!active) return; preview.value = next; fileOffset.value = 0; previewInput.value = JSON.stringify(request); appliedSelection = new Set(selected.value); selecting.value = false }
  catch (e) { error.value = projectError(e) } finally { busy.value = false }
}
async function download() {
  if (busy.value || !preview.value || !previewIsCurrent.value) return
  busy.value = true; generating.value = true; error.value = ''
  try {
    const result = await downloadSdkConfigPackage(props.project.project_id, { ...input(), expected_revision: preview.value.configuration_revision }, controller.signal)
    if (!active) return
    const url = URL.createObjectURL(result.blob), link = document.createElement('a')
    link.href = url; link.download = result.fileName || preview.value.package_name
    try {
      link.click()
      // 只能确认已交给浏览器下载，不能确认文件已保存到用户磁盘。
      feedback.info(text('downloadStarted'))
    } finally { setTimeout(() => URL.revokeObjectURL(url), 1000) }
  } catch (e) { if (active) { error.value = projectError(e); selecting.value = true } } finally { busy.value = false; generating.value = false }
}
async function initialize() {
  busy.value = true; error.value = ''; resourcesReady.value = false
  try { const next = await listSdkResources(props.project.project_id, controller.signal); if (!active) return; const available = new Set(next.map(item => item.id)); selected.value = resources.value.length ? new Set([...selected.value].filter(id => available.has(id))) : available; resources.value = next; resourcesReady.value = true; resourceOffset.value = 0; busy.value = false; await refreshPreview() }
  catch (e) { error.value = projectError(e); selecting.value = true } finally { busy.value = false }
}
onMounted(initialize)
onBeforeUnmount(() => { active = false; controller.abort() })
</script>
<style scoped>
.sdk-range-heading { display: grid; grid-template-columns: 1fr 1fr; align-items: center; gap: 20px; margin-bottom: 10px; }
.sdk-range-heading > div { display: grid; gap: 6px; overflow-wrap: anywhere; }
.sdk-range-heading small { color: var(--am-text-muted); }
@media(max-width: 600px) { .sdk-range-heading { grid-template-columns: 1fr; gap: 10px; } }
.sdk-group-heading { display: flex; justify-content: space-between; margin: 14px 0 0; font-size: 13px; font-weight: 600; color: var(--am-text-muted); }
.sdk-options .ui-select { min-width: 160px; }
.sdk-search { min-height: 38px; padding: 8px 10px; border: 1px solid var(--am-border-strong); border-radius: 6px; background: var(--am-surface); color: var(--am-text); }
:deep(.confirm-dialog__content:has(.sdk-resource-list)) { display: flex; flex-direction: column; overflow: hidden; }
:deep(.confirm-dialog__content:has(.sdk-resource-list)) > :not(.sdk-resource-list) { flex-shrink: 0; }
.sdk-resource-list { flex: 1; min-height: 80px; overflow: auto; }
.sdk-heading { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; padding-bottom: 20px; }.sdk-heading>div { display: grid; gap: 6px; overflow-wrap: anywhere; }.sdk-heading small,.sdk-note,.resource-kind,.sdk-resource small { color: var(--am-text-muted); }
.sdk-counts { display: flex; justify-content: space-between; gap: 16px; padding: 18px 0; border-block: 1px solid var(--am-border); }.sdk-counts strong { color: var(--am-brand-primary); margin-left: 8px; font-size: 22px; }
.sdk-section-heading,.sdk-selection-tools,.sdk-file { display: flex; align-items: center; gap: 12px; }.sdk-section-heading { justify-content: space-between; }.sdk-section-heading h3 { margin: 16px 0; font-size: 15px; }.sdk-search { width: 100%; }.sdk-selection-tools { flex-wrap: wrap; padding: 8px 0; }.sdk-selection-tools>span { margin-right: auto; font-size: 13px; }
.sdk-resource { display: flex; align-items: center; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--am-border); }.sdk-resource>span:first-of-type { display: grid; gap: 4px; min-width: 0; flex: 1; }.sdk-resource strong { font-size: 14px; font-weight: 500; }.sdk-resource small { font-size: 11px; overflow-wrap: anywhere; }.resource-kind { font-size: 12px; }.sdk-options { display: grid; gap: 12px; padding-bottom: 16px; border-bottom: 1px solid var(--am-border); }.sdk-options label { display: flex; align-items: center; gap: 8px; }.sdk-file { padding: 12px 0; border-bottom: 1px solid var(--am-border); }.sdk-file>span { flex: 1; overflow-wrap: anywhere; }.sdk-note,.sdk-warning { font-size: 13px; line-height: 1.6; }.sdk-warning { color: var(--am-warning-icon); }
@media(max-width: 600px) { .sdk-heading { grid-template-columns: 1fr; }.sdk-counts { flex-wrap: wrap; } }
</style>
