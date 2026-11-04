<template>
  <section class="project-workspace">
    <div class="project-toolbar"><form class="project-search" @submit.prevent="search"><Search :size="18" /><input v-model="query" :aria-label="text('search')" :placeholder="text('search')" @input="scheduleSearch" /></form><div class="project-actions"><Button v-if="canSdk" :disabled="!store.selectedProject" @click="open('sdk', store.selectedProject || undefined)"><Package :size="16" />{{ text('sdk') }}</Button><Button :loading="loading" @click="load"><RefreshCw :size="16" />{{ text('refresh') }}</Button><Button v-if="canCreate" variant="primary" @click="open('create')"><Plus :size="16" />{{ text('create') }}</Button></div></div>
    <InlineError v-if="error" :message="error" /><p v-if="error && items.length" class="project-observation">{{ text('stale') }} · {{ projectDate(checkedAt) }}</p>
    <div v-if="createdProject" class="project-notice" role="status"><span>{{ text('createdNotice') }} · {{ projectName(createdProject) }}</span><Button size="sm" @click="view(createdProject)">{{ text('view') }}</Button><Button size="sm" variant="ghost" :aria-label="text('close')" @click="createdProject = null"><X :size="16" /></Button></div>
    <div v-if="hiddenCurrent" class="project-current-location"><span>{{ text('current') }} · {{ projectName(hiddenCurrent) }}</span><Button size="sm" @click="locate(hiddenCurrent)">{{ text('locate') }}</Button></div>
    <div v-for="creation in pendingCreations" :key="creation.request_id" class="project-pending"><span>{{ text('creationPending') }} · {{ creation.display_name }}</span><Button size="sm" @click="dialog = { action: 'create', creation }">{{ text('checkResult') }}</Button></div>
    <div v-for="operation in pending" :key="operation.project.project_id" class="project-pending"><span>{{ text('pendingOperation') }} · {{ projectName(operation.project) }}</span><Button size="sm" @click="open('delete', operation.project, operation.operation_id)">{{ text('check') }}</Button></div>
    <div class="project-table-panel" :aria-busy="loading">
      <div class="project-table-scroll"><table class="project-table"><thead><tr><th>{{ text('name') }}</th><th class="project-description-column">{{ text('description') }}</th><th class="project-count-column">{{ text('datasets') }}</th><th class="project-count-column">{{ text('models') }}</th><th class="project-count-column">{{ text('apps') }}</th><th class="project-count-column">{{ text('deployments') }}</th><th class="project-date">{{ text('updated') }}</th><th>{{ text('actions') }}</th></tr></thead>
        <tbody><tr v-for="project in items" :key="project.project_id" :class="{ 'is-current': store.selectedProjectId === project.project_id }" @click="select(project)">
          <td><button class="project-name-button" :title="project.project_id" :aria-pressed="store.selectedProjectId === project.project_id" @click.stop="select(project)">{{ projectName(project) }}</button><small v-if="duplicateNames.has(projectName(project).toLocaleLowerCase())" class="project-disambiguation">{{ project.project_id }}</small><span v-if="store.selectedProjectId === project.project_id" class="project-current">{{ text('current') }}</span></td>
          <td class="project-description project-description-column">{{ project.description || '—' }}</td><td class="project-count-column">{{ project.resource_counts?.datasets ?? '—' }}</td><td class="project-count-column">{{ project.resource_counts?.models ?? '—' }}</td><td class="project-count-column">{{ project.resource_counts?.apps ?? '—' }}</td><td class="project-count-column">{{ project.resource_counts?.deployments ?? '—' }}</td><td class="project-date">{{ projectDate(project.updated_at) }}</td>
          <td @click.stop><div class="project-row-actions"><button class="project-link" @click="view(project)">{{ text('view') }}</button><ProjectMenu :exportable="canSdk" :editable="canWrite && !!project.revision" :deletable="session.hasScopes(['projects:delete'])" :protected-reason="isProtected(project) ? text('protected') : undefined" @action="open($event, project)" /></div></td>
        </tr></tbody></table></div>
      <div v-if="!items.length" class="project-empty"><Search v-if="query" :size="30" /><FolderOpen v-else :size="32" /><p>{{ loading ? text('loading') : text(error ? 'failedRequest' : query ? 'noMatches' : 'empty') }}</p><Button v-if="query" @click="query = ''; search()">{{ text('clear') }}</Button><Button v-else-if="canCreate && !loading && !error" variant="primary" @click="open('create')">{{ text('create') }}</Button></div>
      <div class="project-pagination"><PaginationControls :offset="offset" :limit="limit" :item-count="items.length" :total-count="total" :has-more="hasMore" :disabled="loading" @previous="changePage(-limit)" @next="changePage(limit)" /><SelectField :model-value="limit" :options="[20, 50, 100].map(value => ({ value, label: String(value) }))" :aria-label="text('pageSize')" @update:model-value="changeLimit" /></div>
    </div>
    <ProjectDialogs v-if="dialog" :key="`${dialog.action}-${dialog.project?.project_id || dialog.creation?.request_id || ''}`" v-bind="dialog" @close="dialog = null" @changed="changed" @created="created" />
  </section>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Search, Package, RefreshCw, Plus, FolderOpen, X } from '@lucide/vue'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import type { ProjectCatalogItem } from '@/shared/contracts'
import { listProjects, getProject } from '../services/project.service'
import { projectDate, projectError, projectName, useProjectText } from '../project-workspace'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import ProjectMenu from '../components/ProjectMenu.vue'
import ProjectDialogs from '../components/ProjectDialogs.vue'
import { readPendingDeletions, readPendingCreations, projectRecoveryEvent, type PendingCreation } from '../project-recovery'
import { getRuntimeConfig } from '@/platform/runtime/runtime-config'
import '../project-workspace.css'
import { canExportProjectSdk } from '../project-access'
import { ApiError } from '@/shared/api/error'
const store = useProjectStore(), session = useSessionStore(), router = useRouter(), route = useRoute(), text = useProjectText()
const items = ref<ProjectCatalogItem[]>([]), query = ref(String(route.query.q || '').slice(0, 200)), offset = ref(Math.max(0, Math.trunc(Number(route.query.offset) || 0))), limit = ref([20, 50, 100].includes(Number(route.query.limit)) ? Number(route.query.limit) : 20), total = ref<number | null>(null), hasMore = ref(false), loading = ref(false), error = ref('')
const checkedAt = ref('')
const canSdk = computed(() => canExportProjectSdk(session))
const canWrite = computed(() => session.hasScopes(['datasets:write']) || session.hasScopes(['workflows:write']))
const canCreate = computed(() => canWrite.value && !session.currentUser?.project_ids?.length)
type Action = 'create' | 'info' | 'edit' | 'sdk' | 'delete'
const dialog = ref<{ action: Action; project?: ProjectCatalogItem; operationId?: string; creation?: PendingCreation } | null>(null)
const pending = ref(readPendingDeletions(session.currentUser?.principal_id || ''))
const pendingCreations = ref<PendingCreation[]>([]), createdProject = ref<ProjectCatalogItem | null>(null)
const hiddenCurrent = computed(() => store.selectedProject && !items.value.some(item => item.project_id === store.selectedProjectId) ? store.selectedProject : null)
const duplicateNames = computed(() => {
  const names = new Set<string>(), duplicates = new Set<string>()
  for (const item of items.value) { const name = projectName(item).toLocaleLowerCase(); if (names.has(name)) duplicates.add(name); names.add(name) }
  return duplicates
})
function isProtected(project: ProjectCatalogItem) { return project.project_source === 'configured' || project.project_id === getRuntimeConfig().defaultProjectId }
let generation = 0, timer: ReturnType<typeof setTimeout> | undefined, selection = 0
async function load() {
  const request = ++generation; loading.value = true; error.value = ''
  try {
    const response = await listProjects({ includeSummary: true, offset: offset.value, limit: limit.value, q: query.value })
    if (request !== generation) return
    checkedAt.value = new Date().toISOString(); items.value = response.items; total.value = response.pagination.totalCount; hasMore.value = response.pagination.hasMore
    if (offset.value > 0 && !items.value.length) { offset.value = response.pagination.totalCount == null ? Math.max(0, offset.value - limit.value) : Math.max(0, Math.floor((response.pagination.totalCount - 1) / limit.value) * limit.value); await syncQuery(true); return }
    await nextTick(); restoreScroll()
  } catch (e) { if (request === generation) { error.value = projectError(e); if (e instanceof ApiError && [401, 403, 404].includes(e.status)) items.value = [] } } finally { if (request === generation) loading.value = false }
}
function open(action: Action, project?: ProjectCatalogItem, operationId?: string) { dialog.value = { action, project, operationId } }
function search() { clearTimeout(timer); offset.value = 0; void syncQuery() }
function scheduleSearch() { clearTimeout(timer); timer = setTimeout(search, 250) }
function changeLimit(value: unknown) { if (typeof value === 'number') { limit.value = value; search() } }
function changePage(delta: number) { offset.value = Math.max(0, offset.value + delta); void syncQuery() }
async function syncQuery(replace = false) { const queryState = { q: query.value || undefined, offset: offset.value || undefined, limit: limit.value === 20 ? undefined : limit.value }; const target = router.resolve({ path: '/projects', query: queryState }); if (target.fullPath === route.fullPath) await load(); else await router[replace ? 'replace' : 'push'](target.fullPath) }
const scrollRoot = () => document.querySelector<HTMLElement>('.workbench-shell__content') || document.scrollingElement as HTMLElement
const scrollKey = () => `amvision.projects.scroll.${session.currentUser?.principal_id || ''}.${route.fullPath}`
function saveScroll() {
  try { sessionStorage.setItem(scrollKey(), String(scrollRoot()?.scrollTop || 0)) }
  catch { /* 浏览器禁用存储时不阻止进入项目。 */ }
}
function restoreScroll() {
  try { scrollRoot()?.scrollTo?.({ top: Number(sessionStorage.getItem(scrollKey()) || 0) }) }
  catch { /* 滚动位置不可恢复时保留当前视图。 */ }
}
async function select(project: ProjectCatalogItem) {
  const request = ++selection
  try { const accessible = await getProject(project.project_id); if (request !== selection) return false; const index = store.projects.findIndex(item => item.project_id === accessible.project_id); if (index < 0) store.projects.push(accessible); else store.projects[index] = accessible; store.selectedProjectId = accessible.project_id; store.selectedSummary = accessible.summary ?? null; return true }
  catch (e) { if (request === selection) error.value = projectError(e); return false }
}
async function view(project: ProjectCatalogItem) { if (await select(project)) { saveScroll(); await router.push({ path: `/projects/${encodeURIComponent(project.project_id)}`, query: route.query }) } }
async function locate(project: ProjectCatalogItem) { query.value = project.project_id; offset.value = 0; await syncQuery() }
async function created(project: ProjectCatalogItem) { store.selectedProjectId = project.project_id; store.selectedSummary = project.summary ?? null; createdProject.value = project; readPending(); await locate(project) }
function readPending() { const principal = session.currentUser?.principal_id || ''; pending.value = session.hasScopes(['projects:delete']) ? readPendingDeletions(principal) : []; pendingCreations.value = canCreate.value ? readPendingCreations(principal) : [] }
function changed() { readPending(); void load() }
watch(() => JSON.stringify([session.currentUser?.principal_id, session.currentUser?.scopes, session.currentUser?.project_ids, session.currentUser?.allowed_pages]), () => { selection++; dialog.value = null; createdProject.value = null; items.value = []; readPending(); void load() })
watch(() => route.fullPath, () => { clearTimeout(timer); query.value = String(route.query.q || '').slice(0, 200); offset.value = Math.max(0, Math.trunc(Number(route.query.offset) || 0)); limit.value = [20, 50, 100].includes(Number(route.query.limit)) ? Number(route.query.limit) : 20; items.value = []; total.value = null; hasMore.value = false; void load() }, { immediate: true })
onMounted(() => { readPending(); window.addEventListener(projectRecoveryEvent, readPending); window.addEventListener('storage', readPending) })
onBeforeUnmount(() => { generation++; selection++; clearTimeout(timer); window.removeEventListener(projectRecoveryEvent, readPending); window.removeEventListener('storage', readPending) })
</script>
