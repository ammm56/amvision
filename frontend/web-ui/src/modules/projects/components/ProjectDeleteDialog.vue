<template>
  <ConfirmDialog :title="text(completed ? 'removed' : failed ? 'removeFailed' : preview && !preview.can_delete ? 'cannotRemove' : 'remove')"
    :confirm-label="text('remove')" :cancel-label="text(awaitingResult || (preview && !preview.can_delete) ? 'close' : 'cancel')"
    :show-confirm="!awaitingResult && !!preview?.can_delete"
    :confirm-disabled="loading || !confirmed" :busy="busy" :allow-close-while-busy="awaitingResult"
    scroll-body @cancel="emit('close')" @confirm="remove">
    <InlineError v-if="error" :message="error" />
    <p v-if="loading && !awaitingResult" role="status">{{ text('loading') }}</p>
    <template v-if="awaitingResult">
      <div class="deletion-result" role="status">
        <span v-if="completed" class="deletion-result__success"><Check :size="22" aria-hidden="true" /></span>
        <TriangleAlert v-else-if="failed || halted" class="deletion-result__error" :size="24" aria-hidden="true" />
        <LoaderCircle v-else class="deletion-result__loading" :size="24" aria-hidden="true" />
        <div><strong>{{ projectName(project) }}</strong><p v-if="!completed">{{ text(failed ? result?.state === 'cleanup_failed' ? 'cleanupFailed' : 'failed' : error ? 'unknownDeletion' : 'deleting') }}</p></div>
      </div>
      <InlineError v-if="result?.cleanup_error" :message="result.cleanup_error" />
    </template>
    <Button v-else-if="error && !preview && !loading" @click="load">{{ text('refresh') }}</Button>
    <template v-else-if="preview">
      <div class="deletion-project"><Folder :size="22" /><strong :title="project.project_id">{{ projectName(project) }}</strong></div>
      <p v-if="preview.protected" class="deletion-note">{{ text('protected') }}</p>
      <template v-else-if="preview.blockers.length">
        <p class="deletion-note">{{ text('stopFirst') }}</p>
        <ul class="blockers"><li v-for="blocker in preview.blockers" :key="`${blocker.resource_kind}:${blocker.resource_id}`"><strong :title="blocker.resource_id">{{ blocker.display_name || blocker.resource_id }}</strong><span>{{ stateLabel(blocker.state) }}</span><Button v-if="blockerPath(blocker)" size="sm" @click="openBlocker(blocker)">{{ text('view') }}</Button></li></ul>
        <Button class="deletion-refresh" @click="load">{{ text('refresh') }}</Button>
      </template>
      <template v-else-if="preview.can_delete">
        <p class="deletion-note">{{ text('removeImpact') }}</p>
        <label class="field"><span>{{ text('confirmName') }}</span><input v-model="confirmation" :placeholder="projectName(project)" autocomplete="off" :disabled="busy" /></label>
      </template>
      <p v-else class="deletion-note">{{ text('cannotRemove') }}</p>
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
import { Check, TriangleAlert, LoaderCircle, Folder } from '@lucide/vue'
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
const halted = ref(false)
const completed = computed(() => result.value?.state === 'deleted')
const failed = computed(() => result.value?.state === 'cleanup_failed' || result.value?.state === 'failed')
const confirmed = computed(() => confirmation.value === projectName(props.project))
let active = true
let timer: ReturnType<typeof setTimeout> | undefined
let controller: AbortController | undefined
onBeforeUnmount(() => { active = false; clearTimeout(timer); controller?.abort() })
function acceptResult(next: ProjectDeletionResult) {
  const previous = result.value
  result.value = next
  // 相同进度不反复刷新整个项目列表；回执只在状态变化时通知父组件。
  if (previous?.operation_id !== next.operation_id || previous?.state !== next.state || previous?.cleanup_error !== next.cleanup_error) emit('removed', next)
}
async function load() {
  loading.value = true; error.value = ''; preview.value = null; confirmation.value = ''
  try { const next = await previewProjectDeletion(props.project.project_id); if (active) preview.value = next }
  catch (e) { if (active) error.value = projectError(e) }
  finally { loading.value = false }
}
async function check() {
  if (!active || loading.value || completed.value || failed.value) return
  clearTimeout(timer)
  loading.value = true
  controller = new AbortController()
  let retry = true
  try {
    const next = await getProjectDeletionResult(props.project.project_id, result.value?.operation_id || props.operationId || 'latest', controller.signal)
    if (active) { error.value = ''; acceptResult(next) }
  } catch (e) {
    if (active) error.value = projectError(e)
    // 只自动读取结果，不重发 DELETE；失权或非法回执停止查询。
    retry = !(e instanceof ApiError && [400, 401, 403, 422].includes(e.status))
    halted.value = !retry
  } finally {
    loading.value = false
    if (active && retry && !completed.value && !failed.value) timer = setTimeout(() => void check(), error.value ? 5000 : 1000)
  }
}
async function remove() {
  if (busy.value || loading.value || awaitingResult.value || !preview.value?.can_delete || !confirmed.value) return
  busy.value = true; error.value = ''; awaitingResult.value = true; emit('started')
  // UI 核对可读名称；后端仍按精确 Project ID 校验，不改变删除 API 协议。
  try { const next = await deleteProject(props.project.project_id, props.project.project_id); if (!active) return; acceptResult(next); await check() }
  catch (e) {
    if (!active) return
    // 只有明确的请求拒绝才能解除待确认；网络/服务失败不可由旧预检推断结果。
    if (e instanceof ApiError && [400, 401, 403, 409, 422].includes(e.status)) {
      awaitingResult.value = false; emit('unaccepted'); await load(); error.value = projectError(e)
    } else { error.value = projectError(e); await check() }
  } finally { busy.value = false }
}
onMounted(() => props.operationId ? check() : load())
</script>
<style scoped>
.deletion-project { display: flex; align-items: center; gap: 10px; min-width: 0; padding-block: 4px; }
.deletion-project svg { flex: none; color: var(--am-text-muted); }
.deletion-project strong { color: var(--am-text-strong); font-size: 16px; font-weight: 600; overflow-wrap: anywhere; }
.deletion-note { margin: 0; color: var(--am-text-muted); font-size: 14px; line-height: 1.6; }
.deletion-result { display: flex; align-items: center; gap: 12px; padding-block: 8px; }
.deletion-result > svg,.deletion-result__success { flex: none; }
.deletion-result__success { display: grid; place-items: center; width: 38px; height: 38px; border-radius: 50%; background: var(--am-brand-primary); color: #fff; }
.deletion-result strong { color: var(--am-text-strong); font-size: 16px; font-weight: 600; overflow-wrap: anywhere; }
.deletion-result p { margin: 6px 0 0; color: var(--am-text-muted); font-size: 14px; }
.deletion-result__error { color: var(--am-danger-icon); }
.deletion-result__loading { color: var(--am-text-muted); animation: deletion-spin 1s linear infinite; }
@keyframes deletion-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .deletion-result__loading { animation: none; } }
.field { display: grid; gap: 8px; margin-top: 4px; font-size: 14px; }.field input { min-width: 0; width: 100%; }
.blockers { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.blockers li { display: flex; align-items: center; gap: 12px; padding: 10px; border-radius: var(--am-radius-sm); background: var(--am-hover-surface); }
.blockers strong { flex: 1; min-width: 0; overflow-wrap: anywhere; font-weight: 500; }.blockers span { flex: none; color: var(--am-text-muted); font-size: 13px; }.blockers .ui-button { flex: none; }
.deletion-refresh { justify-self: start; }
@media(max-width: 480px) { .blockers li { flex-wrap: wrap; } }
</style>
