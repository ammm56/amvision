<template>
  <SideDrawer :open="true" size="compact" :title="text(mode === 'create' ? 'create' : mode === 'edit' ? 'edit' : 'info')" :close-label="text('close')" :busy="busy" @close="close">
    <InlineError v-if="error" :message="error" />
    <div v-if="unknownCreation" class="latest-values"><p>{{ text('unknownCreation') }}</p><div class="project-actions"><Button :loading="busy" @click="checkCreation">{{ text('checkResult') }}</Button><Button :disabled="busy" @click="submit">{{ text('retryCreation') }}</Button><Button :disabled="busy" @click="newDraft">{{ text('anotherProject') }}</Button></div></div>
    <div v-if="pendingEdit" class="latest-values"><p>{{ text('unknownEdit') }}</p><Button :loading="busy" @click="checkEdit">{{ text('checkResult') }}</Button></div>
    <Button v-if="conflict" :loading="busy" @click="readLatest">{{ text('reloadLatest') }}</Button>
    <div v-if="latest" class="latest-values"><strong>{{ text('latestValues') }}</strong><p>{{ latest.display_name }}</p><p>{{ latest.description || '—' }}</p><div class="project-actions"><Button :disabled="busy" @click="confirmLatest = true">{{ text('useLatest') }}</Button><Button :disabled="busy" @click="keepDraft">{{ text('keepDraft') }}</Button></div></div>
    <form v-if="mode !== 'info'" id="project-metadata" class="project-form" @submit.prevent="submit">
      <label class="field"><span>{{ text('name') }} <span class="required">*</span></span><input v-model="name" maxlength="128" required :disabled="busy || unknownCreation || !!pendingEdit" autocomplete="off" /></label>
      <label class="field"><span>{{ text('description') }}</span><textarea v-model="description" maxlength="2000" rows="5" :disabled="busy || unknownCreation || !!pendingEdit" /></label>
    </form>
    <dl v-else-if="project" class="project-info">
      <dt>{{ text('name') }}</dt><dd>{{ projectName(project) }}</dd>
      <dt>{{ text('description') }}</dt><dd>{{ project.description || '—' }}</dd>
      <dt>Project ID</dt><dd class="copy-line"><code>{{ project.project_id }}</code><Button size="sm" variant="ghost" :aria-label="`${text('copy')} Project ID`" @click="copy(project.project_id)"><Copy :size="16" /></Button></dd>
      <dt>{{ text('source') }}</dt><dd>{{ text(project.project_source === 'configured' ? 'configured' : 'local') }}</dd>
      <dt>{{ text('path') }}</dt><dd class="copy-line"><code>{{ project.storage_prefix || '—' }}</code><Button size="sm" variant="ghost" :aria-label="`${text('copy')} ${text('path')}`" @click="copy(project.storage_prefix || '')"><Copy :size="16" /></Button></dd>
      <dt>{{ text('created') }}</dt><dd>{{ projectDate(project.created_at) }}</dd>
      <dt>{{ text('updated') }}</dt><dd>{{ projectDate(project.updated_at) }}</dd>
    </dl>
    <p v-if="copied" role="status">{{ copied }} · {{ text('copied') }}</p>
    <template #footer><span /><div class="project-actions"><Button :disabled="busy" @click="close">{{ text(mode === 'info' ? 'close' : 'cancel') }}</Button><Button v-if="mode === 'info' && editable" variant="primary" @click="emit('edit')">{{ text('edit') }}</Button><Button v-if="mode !== 'info' && !unknownCreation && !pendingEdit" type="submit" form="project-metadata" variant="primary" :loading="busy" :disabled="!name.trim() || conflict || !!latest || (mode === 'edit' && !dirty)">{{ text(mode === 'create' ? 'create' : 'save') }}</Button></div></template>
  </SideDrawer>
  <ConfirmDialog v-if="confirmDiscard" :title="text('discard')" :message="text('unsaved')" :confirm-label="text('discard')" :cancel-label="text('cancel')" @confirm="finishLeave(true)" @cancel="finishLeave(false)" />
  <ConfirmDialog v-if="confirmLatest" :title="text('useLatest')" :message="text('replaceDraft')" :confirm-label="text('useLatest')" :cancel-label="text('cancel')" confirm-variant="primary" @confirm="useLatest" @cancel="confirmLatest = false" />
</template>
<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { matchedRouteKey, onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { Copy } from '@lucide/vue'
import type { ProjectCatalogItem } from '@/shared/contracts'
import { createProject, getProject, updateProject } from '../services/project.service'
import { ApiError } from '@/shared/api/error'
import { projectDate, projectError, projectName, useProjectText } from '../project-workspace'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { clearPendingCreation, readPendingEdit, savePendingCreation, savePendingEdit, type PendingCreation, type PendingEdit } from '../project-recovery'
const props = defineProps<{ mode: 'create' | 'edit' | 'info'; project?: ProjectCatalogItem; editable?: boolean; principalId?: string; creation?: PendingCreation }>()
const emit = defineEmits<{ close: []; edit: []; saved: [project: ProjectCatalogItem] }>()
const text = useProjectText()
watch(() => props.mode, mode => {
  if (mode !== 'info') document.querySelector<HTMLInputElement>('#project-metadata input')?.focus()
}, { flush: 'post' })
const principal = props.principalId || ''
const recovered = props.mode === 'create' ? props.creation : null
const pendingEdit = ref<PendingEdit | null>(props.project ? readPendingEdit(principal, props.project.project_id) : null)
const name = ref(recovered?.display_name || pendingEdit.value?.display_name || props.project?.display_name || '')
// null 表示明确清空说明，恢复待确认请求时不能退回旧项目说明。
const description = ref((recovered ? recovered.description : pendingEdit.value ? pendingEdit.value.description : props.project?.description) ?? '')
let requestId = recovered?.request_id || crypto.randomUUID()
const unknownCreation = ref(Boolean(recovered))
const expectedRevision = ref(pendingEdit.value?.expected_revision || props.project?.revision || ''), conflict = ref(false), latest = ref<ProjectCatalogItem | null>(null)
const baseline = ref({ display_name: props.project?.display_name || '', description: props.project?.description || '' })
let active = true
let copyTimer: ReturnType<typeof setTimeout> | undefined
onBeforeUnmount(() => { active = false; clearTimeout(copyTimer); leaveAnswer?.(false); window.removeEventListener('beforeunload', beforeUnload) })
const busy = ref(false), error = ref(''), copied = ref(''), confirmDiscard = ref(false), confirmLatest = ref(false)
const dirty = computed(() => name.value !== baseline.value.display_name || description.value !== baseline.value.description)
let leaveAnswer: ((answer: boolean) => void) | undefined
function needsProtection() { return props.mode !== 'info' && dirty.value && !unknownCreation.value && !pendingEdit.value }
function close() { if (busy.value) return; if (needsProtection()) confirmDiscard.value = true; else emit('close') }
function finishLeave(answer: boolean) {
  confirmDiscard.value = false
  if (leaveAnswer) { const resolve = leaveAnswer; leaveAnswer = undefined; resolve(answer) }
  else if (answer) emit('close')
}
function guardLeave() {
  if (busy.value) return false
  if (!needsProtection()) return true
  leaveAnswer?.(false)
  confirmDiscard.value = true
  return new Promise<boolean>(resolve => { leaveAnswer = resolve })
}
if (inject(matchedRouteKey, null)) { onBeforeRouteLeave(guardLeave); onBeforeRouteUpdate(guardLeave) }
function beforeUnload(event: BeforeUnloadEvent) {
  if (busy.value || needsProtection()) { event.preventDefault(); event.returnValue = '' }
}
window.addEventListener('beforeunload', beforeUnload)
async function checkCreation() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    const project = await getProject(`project-${requestId.replaceAll('-', '')}`)
    if (active) { clearPendingCreation(principal, requestId); unknownCreation.value = false; emit('saved', project) }
  } catch (e) { error.value = e instanceof ApiError && e.status === 404 ? text('creationNotFound') : projectError(e) }
  finally { busy.value = false }
}
function newDraft() {
  // 原请求仍留在列表的待确认入口，不把查询 404 当作服务端已取消。
  if (busy.value) return
  requestId = crypto.randomUUID(); name.value = ''; description.value = ''; unknownCreation.value = false; error.value = ''
}
async function copy(value: string) {
  if (!value) return
  clearTimeout(copyTimer); copied.value = ''
  try { await navigator.clipboard.writeText(value); if (active) { copied.value = value === props.project?.project_id ? 'Project ID' : text('path'); copyTimer = setTimeout(() => { copied.value = '' }, 2400) } }
  catch (e) { if (active) error.value = projectError(e) }
}
async function readLatest() {
  busy.value = true
  try { const current = await getProject(props.project!.project_id); if (!active) return; latest.value = current; conflict.value = false; error.value = '' }
  catch (e) { error.value = projectError(e) } finally { busy.value = false }
}
function keepDraft() {
  if (!latest.value?.revision) return
  expectedRevision.value = latest.value.revision
  baseline.value = { display_name: latest.value.display_name || '', description: latest.value.description || '' }
  latest.value = null; conflict.value = false; error.value = ''
}
function useLatest() {
  if (!latest.value) return
  name.value = latest.value.display_name || ''; description.value = latest.value.description || ''
  keepDraft(); confirmLatest.value = false
}
async function checkEdit() {
  if (busy.value || !pendingEdit.value) return
  busy.value = true; error.value = ''
  try { await resolveEdit() } catch (e) { if (active) error.value = projectError(e) } finally { busy.value = false }
}
async function resolveEdit() {
  const submitted = pendingEdit.value!
  const current = await getProject(props.project!.project_id)
  if (!active) return
  savePendingEdit(principal, props.project!.project_id, null); pendingEdit.value = null
  if (current.display_name === submitted.display_name && (current.description || null) === submitted.description) { emit('saved', current); return }
  if (current.revision === submitted.expected_revision) { error.value = text('editNotApplied'); return }
  latest.value = current; error.value = text('editConflict')
}
async function submit() {
  if (busy.value || !name.value.trim() || pendingEdit.value || conflict.value || latest.value) return
  busy.value = true; error.value = ''
  try {
    const body = { display_name: name.value.trim(), description: description.value.trim() || null }
    if (props.mode === 'create') savePendingCreation(principal, { ...body, request_id: requestId })
    else { pendingEdit.value = { ...body, expected_revision: expectedRevision.value }; savePendingEdit(principal, props.project!.project_id, pendingEdit.value) }
    const project = props.mode === 'create' ? await createProject({ ...body, request_id: requestId })
      : await updateProject(props.project!.project_id, { ...body, expected_revision: expectedRevision.value })
    if (props.mode === 'create') clearPendingCreation(principal, requestId)
    else { savePendingEdit(principal, props.project!.project_id, null); pendingEdit.value = null }
    if (active) { unknownCreation.value = false; emit('saved', project) }
  } catch (e) {
    error.value = projectError(e)
    conflict.value = props.mode === 'edit' && e instanceof ApiError && e.status === 409
    if (props.mode === 'create') {
      unknownCreation.value = !(e instanceof ApiError && [400, 401, 403, 422].includes(e.status))
      if (!unknownCreation.value) clearPendingCreation(principal, requestId)
    } else if (e instanceof ApiError && [400, 401, 403, 404, 409, 422].includes(e.status)) {
      savePendingEdit(principal, props.project!.project_id, null); pendingEdit.value = null
    } else {
      try { await resolveEdit() } catch { if (active) error.value = text('unknownEdit') }
    }
  } finally { busy.value = false }
}
</script>
<style scoped>
.latest-values { margin-block: 16px; padding: 12px; background: var(--am-hover-surface); border: 1px solid var(--am-border); border-radius: 6px; font-size: 13px; overflow-wrap: anywhere; }
.project-form { display: grid; gap: 24px; }
.field { display: grid; gap: 8px; }.field textarea { resize: vertical; min-height: 120px; }
.required { color: var(--am-danger-icon); }.project-actions,.copy-line { display: flex; align-items: center; gap: 10px; }
.copy-line { justify-content: space-between; }.copy-line code { font-size: 12px; overflow-wrap: anywhere; }
</style>
