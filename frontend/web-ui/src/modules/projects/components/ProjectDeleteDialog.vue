<template>
  <ConfirmDialog :title="text(removed ? 'removed' : awaitingResult ? 'pendingOperation' : preview && !preview.can_delete ? 'cannotRemove' : 'remove')"
    :confirm-label="text(awaitingResult ? 'check' : 'remove')" :cancel-label="text(awaitingResult ? 'close' : 'cancel')"
    :confirm-variant="awaitingResult ? 'primary' : 'danger'"
    :show-confirm="awaitingResult ? result?.state !== 'deleted' : !!preview?.can_delete"
    :confirm-disabled="loading || (!awaitingResult && confirmation !== project.project_id)" :busy="busy"
    size="medium" scroll-body @cancel="emit('close')" @confirm="awaitingResult ? check() : remove()">
    <InlineError v-if="error" :message="error" />
    <p v-if="loading" role="status">{{ text('loading') }}</p>
    <template v-if="awaitingResult">
      <div v-if="removed" class="deletion-result"><CircleCheck :size="28" class="success" /><strong>{{ text('removed') }}</strong></div>
      <p><strong>{{ projectName(project) }}</strong><small class="project-identity">{{ project.project_id }}</small></p>
      <div v-if="!result || result.state !== 'deleted'" class="cleanup-state" :class="{ 'is-error': result?.state === 'cleanup_failed' || result?.state === 'failed' }">
        <TriangleAlert v-if="result?.state === 'cleanup_failed' || result?.state === 'failed'" :size="22" /><Clock v-else :size="22" />
        <span>{{ text(!result ? 'unknownDeletion' : result.state === 'cleanup_failed' ? 'cleanupFailed' : result.state === 'cleanup_pending' ? 'cleanupPending' : result.state) }}</span>
      </div>
      <p v-else>{{ text('cleanupComplete') }}</p><Button v-if="result?.state === 'failed'" @click="awaitingResult = false; result = null; load()">{{ text('refresh') }}</Button>
      <InlineError v-if="result?.cleanup_error" :message="result.cleanup_error" />
      <p v-if="result" class="receipt">{{ text('operation') }}<code>{{ result.operation_id }}</code><Button size="sm" @click="copyOperation">{{ text(copied ? 'copied' : 'copy') }}</Button></p>
    </template>
    <Button v-else-if="error && !preview && !loading" @click="load">{{ text('refresh') }}</Button>
    <template v-else-if="preview">
      <p><strong>{{ projectName(project) }}</strong></p>
      <p v-if="preview.protected">{{ text('protected') }}</p>
      <template v-else-if="preview.blockers.length"><p>{{ text('stopFirst') }}</p><ul class="blockers"><li v-for="blocker in preview.blockers" :key="blocker.resource_id"><div><strong>{{ blocker.display_name || blocker.resource_id }}</strong><small class="project-identity">{{ blocker.resource_id }}</small></div><span>{{ stateLabel(blocker.state) }}</span><Button v-if="blockerPath(blocker)" size="sm" @click="openBlocker(blocker)">{{ text('view') }}</Button></li></ul><Button @click="load">{{ text('refresh') }}</Button></template>
      <template v-else><p>{{ text('removeImpact') }}</p><dl class="deletion-counts"><template v-for="[kind, count] in counts" :key="kind"><dt>{{ resourceLabel(kind) }}</dt><dd>{{ count }}</dd></template></dl><label class="field"><span>{{ text('confirmId') }}</span><code>{{ project.project_id }}</code><input v-model="confirmation" :placeholder="project.project_id" autocomplete="off" /></label></template>
    </template>
  </ConfirmDialog>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { canAccessPath } from '@/platform/auth/page-access'
import type { ProjectDeletionBlocker } from '../services/project.service'
import { useI18n } from 'vue-i18n'
import { CircleCheck, TriangleAlert, Clock } from '@lucide/vue'
import { ApiError } from '@/shared/api/error'
import type { ProjectCatalogItem } from '@/shared/contracts'
import { deleteProject, getProjectDeletionResult, previewProjectDeletion, type ProjectDeletionPreview, type ProjectDeletionResult } from '../services/project.service'
import { projectError, projectName, useProjectText } from '../project-workspace'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
const props = defineProps<{ project: ProjectCatalogItem; operationId?: string }>()
const emit = defineEmits<{ close: []; removed: [result: ProjectDeletionResult]; started: []; unaccepted: [] }>()
const text = useProjectText(), { t, te } = useI18n()
const router = useRouter(), store = useProjectStore(), session = useSessionStore()
function stateLabel(value: string) { return value.split('/').map(state => ['tasks.status', 'startupPage.states', 'deploymentOps.states'].map(prefix => `${prefix}.${state}`).find(key => te(key))).map((key, index) => key ? t(key) : value.split('/')[index]).join(' / ') }
function blockerPath(item: ProjectDeletionBlocker) { const id = encodeURIComponent(item.resource_id); const path = item.resource_kind === 'task' ? `/tasks/${id}` : item.resource_kind === 'deployment' ? `/deployments?deployment=${id}` : item.resource_kind === 'workflow_runtime' ? `/workflows/runtime/${id}/monitor` : item.resource_kind === 'trigger_source' ? '/integrations/trigger-sources' : ''; return path && canAccessPath(session.currentUser, path) ? path : '' }
async function openBlocker(item: ProjectDeletionBlocker) { const path = blockerPath(item); if (!path) return; store.selectedProjectId = props.project.project_id; store.selectedSummary = null; emit('close'); await router.push(path) }
const preview = ref<ProjectDeletionPreview | null>(null), result = ref<ProjectDeletionResult | null>(null), error = ref(''), confirmation = ref(''), busy = ref(false), loading = ref(false)
const awaitingResult = ref(Boolean(props.operationId))
const removed = computed(() => !!result.value && ['deleted', 'cleanup_pending', 'cleanup_failed'].includes(result.value.state))
let active = true
const copied = ref(false)
onBeforeUnmount(() => { active = false })
async function copyOperation() { try { await navigator.clipboard.writeText(result.value!.operation_id); copied.value = true } catch (e) { error.value = projectError(e) } }
const counts = computed(() => Object.entries(preview.value?.resource_counts || {}).filter(([, count]) => count > 0))
const resourceKeys: Record<string, string> = { dataset_exports: 'datasetExports', dataset_imports: 'datasetImports', dataset_versions: 'datasetVersions', deployments: 'deployments', models: 'models', model_files: 'modelFiles', tasks: 'tasks', queue_messages: 'queueMessages', validation_sessions: 'validationSessions', workflow_app_runtimes: 'workflowAppRuntimes', workflow_documents: 'workflowDocuments', workflow_execution_policies: 'workflowExecutionPolicies', workflow_runs: 'workflowRuns', workflow_trigger_sources: 'workflowTriggerSources', authorization_assignments: 'authorizationAssignments' }
function resourceLabel(kind: string) { if (kind === 'workflow_application_lifecycles') return text('operationRecords'); if (kind === 'workflow_app_versions') return text('appVersions'); return resourceKeys[kind] ? t(`projects.deletion.resources.${resourceKeys[kind]}`) : kind }
async function load() {
  loading.value = true; error.value = ''; preview.value = null
  try { const next = await previewProjectDeletion(props.project.project_id); if (active) preview.value = next }
  catch (e) { if (active) error.value = projectError(e) }
  finally { loading.value = false }
}
async function check() {
  if (loading.value) return
  loading.value = true; error.value = ''
  try {
    const next = await getProjectDeletionResult(props.project.project_id, result.value?.operation_id || props.operationId || 'latest')
    if (active) { result.value = next; emit('removed', next) }
  } catch (e) { if (active) error.value = projectError(e) }
  finally { loading.value = false }
}
async function remove() {
  if (busy.value || confirmation.value !== props.project.project_id) return
  busy.value = true; error.value = ''; awaitingResult.value = true; emit('started')
  try { result.value = await deleteProject(props.project.project_id, confirmation.value); if (!active) return; emit('removed', result.value); await check() }
  catch (e) {
    const message = projectError(e)
    // 只有明确的请求拒绝才能解除待确认；网络/服务失败不可由旧预检推断结果。
    if (e instanceof ApiError && [400, 401, 403, 409, 422].includes(e.status)) {
      awaitingResult.value = false; emit('unaccepted'); await load()
    } else await check()
    error.value = message
  } finally { busy.value = false }
}
onMounted(() => props.operationId ? check() : load())
</script>
<style scoped>
.receipt { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 12px; color: var(--am-text-muted); }.receipt code { overflow-wrap: anywhere; }.danger { color: var(--am-danger-icon); }
.project-identity { display: block; margin-top: 6px; color: var(--am-text-muted); overflow-wrap: anywhere; }
.cleanup-state { display: flex; align-items: center; gap: 12px; padding: 16px; border: 1px solid var(--am-border); border-radius: 8px; background: var(--am-hover-surface); }
.cleanup-state svg { color: var(--am-warning-icon); flex-shrink: 0; }.cleanup-state.is-error svg { color: var(--am-danger-icon); }
.field { display: grid; gap: 8px; margin-top: 24px; }.field code { font-size: 12px; overflow-wrap: anywhere; }.deletion-counts { display: grid; grid-template-columns: 1fr auto; gap: 10px; padding: 16px; border: 1px solid var(--am-border); border-radius: 8px; }.deletion-counts dd { margin: 0; }.blockers { list-style: none; margin: 0 0 16px; padding: 0; }.blockers li { display: flex; gap: 16px; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid var(--am-border); }.blockers code { overflow-wrap: anywhere; font-size: 12px; }.deletion-result { display: flex; gap: 12px; align-items: center; padding: 12px 0 20px; }.success { color: var(--am-brand-primary); }.warning { color: var(--am-warning-icon); }
</style>
