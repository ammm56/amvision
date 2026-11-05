<template>
  <section class="project-workspace">
    <InlineError v-if="error" :message="error" />
    <p v-if="loading && !project" role="status">{{ text('loading') }}</p>
    <template v-if="project">
      <div class="project-overview-heading">
        <div class="project-overview-title"><Button :aria-label="text('back')" @click="backToList"><ChevronLeft :size="18" /></Button><div><h1>{{ projectName(project) }}</h1><p>{{ project.description || '—' }}</p></div></div>
        <div class="project-actions"><Button @click="dialog = 'info'"><Info :size="16" />{{ text('info') }}</Button><Button v-if="canWrite && project.revision" @click="dialog = 'edit'"><Pencil :size="16" />{{ text('edit') }}</Button><Button v-if="canSdk" @click="dialog = 'sdk'"><Package :size="16" />{{ text('sdk') }}</Button><Button :loading="loading" :aria-label="text('refresh')" @click="load"><RefreshCw :size="16" /></Button></div>
      </div>
      <p v-if="project.resource_errors?.length" class="sdk-warning">{{ text('partialResources') }}</p>
      <div v-if="metrics.length" class="project-metrics"><button type="button" v-for="metric in metrics" :key="metric.label" :disabled="!canNavigate(metric.path)" @click="navigate(metric.path)"><span>{{ text(metric.label) }}</span><strong>{{ metric.count ?? '—' }}</strong></button></div>

      <InlineError v-if="activityError && activityError !== error" :message="activityError" />
      <section v-if="expanded" class="project-panel">
        <div class="project-section-heading"><h2>{{ text('recent') }}</h2><Button @click="toggleRecent(false)">{{ text('backOverview') }}</Button></div>
        <form class="project-activity-filters" @submit.prevent="filterRecent"><input v-model="activityQuery" :placeholder="text('searchActivity')" :aria-label="text('searchActivity')" /><SelectField v-model="activityKind" :options="kindOptions" :aria-label="text('allTypes')" @update:model-value="filterRecent" /><Button type="submit">{{ text('searchAction') }}</Button><Button v-if="activityQuery || activityKind" @click="activityQuery = ''; activityKind = ''; filterRecent()">{{ text('clear') }}</Button></form>
        <ProjectActivityTable v-if="overview?.recent.length" :items="overview.recent" v-bind="tableProps" @open="openItem" />
        <p v-else class="project-empty-inline">{{ text(loading ? 'loading' : activityError ? 'failedRequest' : activityQuery || activityKind ? 'noMatchesResources' : 'noActivity') }}</p>
        <PaginationControls :offset="activityOffset" :limit="20" :item-count="overview?.recent.length || 0" :total-count="overview?.total ?? null" :has-more="activityOffset + 20 < (overview?.total || 0)" :disabled="loading" @previous="pageRecent(-20)" @next="pageRecent(20)" />
      </section>
      <template v-else>
        <div class="project-overview-panels">
          <section class="project-panel"><div class="project-section-heading"><h2>{{ text('recent') }}</h2><Button v-if="(overview?.total || 0) > 0" size="sm" variant="ghost" @click="toggleRecent(true)">{{ text('moreUpdates') }}</Button></div>
            <ProjectActivityTable v-if="overview?.recent.length" :items="overview.recent" v-bind="tableProps" @open="openItem" />
            <p v-else class="project-empty-inline">{{ text(loading ? 'loading' : activityError ? 'failedRequest' : 'noActivity') }}</p>
          </section>
          <section class="project-panel"><h2>{{ text('running') }}</h2>
            <div class="project-panel-body"><template v-for="group in activeGroups" :key="group.label">
              <div class="project-section-heading"><h3>{{ text(group.label) }}</h3></div>
              <ProjectActivityTable v-if="group.items.length" :items="group.items" mode="running" v-bind="tableProps" @open="openItem" />
              <p v-if="!group.items.length" class="project-empty-inline">{{ text(loading ? 'loading' : activityError ? 'failedRequest' : 'noServices') }}</p>
            </template></div>
          </section>
        </div>
        <section v-if="shortcuts.length" class="project-panel project-continue-panel" :aria-label="text('continue')"><div class="project-shortcuts"><button type="button" v-for="shortcut in shortcuts" :key="shortcut.path" :disabled="!!shortcut.reason" :title="shortcut.reason" @click="navigate(shortcut.path)"><component :is="shortcut.icon" :size="23" /><span>{{ text(shortcut.label) }}<small v-if="shortcut.reason">{{ shortcut.reason }}</small></span></button></div></section>
      </template>
      <ProjectResourceDrawer v-if="resourceItem" :key="resourceItem.resource_id" :project-id="project.project_id" :item="resourceItem" @close="resourceItem = null" />
      <ProjectDialogs v-if="dialog" :action="dialog" :project="project" @close="dialog = null" @changed="load" />
    </template>
    <div v-else-if="error" class="project-actions"><Button @click="backToList"><ChevronLeft :size="18" />{{ text('back') }}</Button><Button @click="load">{{ text('refresh') }}</Button></div>
  </section>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ChevronLeft, Info, Pencil, Package, RefreshCw, Database, Box, Server, Workflow } from '@lucide/vue'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { canAccessPath, canAccessPage } from '@/platform/auth/page-access'
import { ApiError } from '@/shared/api/error'
import type { ProjectCatalogItem } from '@/shared/contracts'
import { getProject, getProjectOverview, type ProjectOverview, type ProjectOverviewItem } from '../services/project.service'
import { projectError, projectName, useProjectText } from '../project-workspace'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import ProjectDialogs from '../components/ProjectDialogs.vue'
import ProjectResourceDrawer from '../components/ProjectResourceDrawer.vue'
import ProjectActivityTable from '../components/ProjectActivityTable.vue'
import '../project-workspace.css'
import { canExportProjectSdk } from '../project-access'
const route = useRoute(), router = useRouter(), store = useProjectStore(), session = useSessionStore(), text = useProjectText(), { t, te } = useI18n()
const project = ref<ProjectCatalogItem | null>(null), overview = ref<ProjectOverview | null>(null), loading = ref(false), error = ref(''), activityError = ref(''), dialog = ref<'info' | 'edit' | 'sdk' | null>(null)
const resourceItem = ref<ProjectOverviewItem | null>(null)
const canWrite = computed(() => session.hasScopes(['datasets:write']) || session.hasScopes(['workflows:write']))
const canSdk = computed(() => canExportProjectSdk(session))
const canNavigate = (path: string) => canAccessPath(session.currentUser, path) && (!path.startsWith('/models') || session.hasScopes(['tasks:read']))
const metrics = computed(() => ([{ label: 'datasets', path: '/datasets' }, { label: 'models', path: '/models' }, { label: 'apps', path: '/workflows/apps' }, { label: 'deployments', path: '/deployments' }] as const).filter(item => Object.hasOwn(project.value?.resource_counts || {}, item.label)).map(item => ({ ...item, count: project.value?.resource_counts?.[item.label] })))
const serviceItems = computed(() => {
  const items = overview.value?.active || [], runtimes = items.filter(item => item.kind === 'runtime'), deployments = items.filter(item => item.kind === 'deployment')
  return [...runtimes.slice(0, 2), ...deployments.slice(0, 2), ...runtimes.slice(2), ...deployments.slice(2)].slice(0, 4)
})
const activeGroups = computed(() => [
  { label: 'tasks' as const, items: overview.value?.active.filter(item => !['runtime', 'deployment'].includes(item.kind)) || [] },
  { label: 'services' as const, items: serviceItems.value },
].filter(group => group.label === 'tasks' ? overview.value?.access.tasks && group.items.length > 0 : overview.value?.access.runtimes || overview.value?.access.deployments))
const shortcuts = computed(() => [
  { label: 'import' as const, path: '/datasets', icon: Database, scope: 'datasets:write', reason: '' },
  { label: 'train' as const, path: '/models', icon: Box, scope: 'tasks:write', reason: project.value?.resource_counts?.datasets === 0 ? text('needDataset') : '' },
  { label: 'deploy' as const, path: '/deployments', icon: Server, scope: 'models:write', reason: project.value?.resource_counts?.models === 0 ? text('needModel') : '' },
  { label: 'workflow' as const, path: '/workflows/graph/new', icon: Workflow, scope: 'workflows:write', reason: '' },
].filter(item => session.hasScopes([item.scope]) && canNavigate(item.path)))
const expanded = ref(false), activityQuery = ref(''), activityKind = ref(''), activityOffset = ref(0)
const kindOptions = computed(() => [{ value: '', label: text('allTypes') }, ...(['datasets', 'models', 'apps', 'deployments', 'tasks', 'runtimes'] as const).filter(kind => lastAccess.value[kind]).map(kind => ({ value: kind, label: kind === 'runtimes' ? 'Workflow Runtime' : text(kind === 'tasks' ? 'taskList' : kind) }))])
const lastAccess = ref<Record<string, boolean>>({})
const scrollRoot = () => document.querySelector<HTMLElement>('.workbench-shell__content') || document.scrollingElement as HTMLElement
let generation = 0, controller: AbortController | undefined, timer: ReturnType<typeof setTimeout> | undefined, savedScroll = 0
function scheduleRefresh() { clearTimeout(timer); timer = setTimeout(() => { if (document.visibilityState === 'visible' && !dialog.value && !resourceItem.value && !expanded.value) void load(); else scheduleRefresh() }, 30_000) }
async function load() {
  const request = ++generation, id = String(route.params.projectId)
  controller?.abort(); controller = new AbortController()
  loading.value = true; error.value = ''; activityError.value = ''
  const [metadata, activity] = await Promise.allSettled([getProject(id, controller.signal), getProjectOverview(id, { limit: expanded.value ? 20 : 5, offset: expanded.value ? activityOffset.value : 0, q: expanded.value ? activityQuery.value : '', kind: expanded.value ? activityKind.value : '' }, controller.signal)])
  if (request !== generation) return
  if (metadata.status === 'fulfilled') {
    project.value = metadata.value
    const index = store.projects.findIndex(item => item.project_id === id)
    if (index < 0) store.projects.push(metadata.value); else store.projects[index] = metadata.value
    store.selectedProjectId = id
    store.selectedSummary = metadata.value.summary ?? null
  } else {
    error.value = projectError(metadata.reason)
    if (metadata.reason instanceof ApiError && [401, 403, 404].includes(metadata.reason.status)) { error.value = text('cannotOpen'); project.value = null; overview.value = null; loading.value = false; return }
  }
  if (activity.status === 'fulfilled') {
    if (expanded.value && activityOffset.value > 0 && activityOffset.value >= activity.value.total) {
      activityOffset.value = Math.max(0, Math.floor((activity.value.total - 1) / 20) * 20)
      return load()
    }
    overview.value = activity.value; lastAccess.value = activity.value.access
  }
  else {
    activityError.value = projectError(activity.reason)
    if (activity.reason instanceof ApiError && [401, 403].includes(activity.reason.status)) overview.value = null
  }
  loading.value = false; scheduleRefresh()
}
async function toggleRecent(value: boolean) {
  if (value) savedScroll = scrollRoot()?.scrollTop || 0
  expanded.value = value; activityOffset.value = 0; overview.value = null
  await load(); await nextTick()
  if (!value) scrollRoot()?.scrollTo({ top: savedScroll })
}
function filterRecent() { activityOffset.value = 0; overview.value = null; void load() }
function pageRecent(delta: number) { activityOffset.value = Math.max(0, activityOffset.value + delta); overview.value = null; void load() }
function stateLabel(state: string) {
  if (state === 'available' || state === 'saved' || state === 'published') return text(state)
  for (const prefix of ['tasks.status', 'startupPage.states', 'deploymentOps.states']) if (te(`${prefix}.${state}`)) return t(`${prefix}.${state}`)
  return state === 'ready' ? t('common.ready') : state
}
function kindLabel(kind: string) {
  if (kind === 'runtime') return 'Workflow Runtime'
  const fixed = { deployment: 'deployments', application: 'apps', 'app-version': 'appVersions', 'dataset-version': 'datasetVersion', 'model-version': 'modelVersion', 'dataset-import': 'import', 'dataset-export': 'exportDataset' } as const
  if (kind in fixed) return text(fixed[kind as keyof typeof fixed])
  const suffix = kind.split('-').at(-1)
  if (suffix === 'training' || suffix === 'conversion' || suffix === 'evaluation' || suffix === 'inference') return text(suffix)
  if (suffix === 'validation') return text('evaluation')
  return kind
}
function itemPath(item: ProjectOverviewItem) {
  const id = encodeURIComponent(item.target_id || item.resource_id)
  if (item.kind === 'runtime') return `/workflows/runtime/${id}/monitor`
  if (item.kind === 'deployment') return `/deployments?deployment=${id}`
  if (['application', 'app-version'].includes(item.kind)) return `/workflows/apps/${id}`
  if (item.kind === 'dataset-version') return `/datasets?version=${id}`
  if (item.kind === 'model-version') return `/models?model=${id}`
  return `/tasks/${id}`
}
const canOpen = (item: ProjectOverviewItem) => item.kind === 'dataset-version' ? canAccessPage(session.currentUser, 'datasets') : item.kind === 'model-version' ? canAccessPage(session.currentUser, 'models') : canNavigate(itemPath(item))
const tableProps = { canOpen, kindLabel, stateLabel }
function openItem(item: ProjectOverviewItem) { if (!canOpen(item)) return; if (['dataset-version', 'model-version'].includes(item.kind)) resourceItem.value = item; else void navigate(itemPath(item)) }
async function navigate(path: string) { if (!project.value || !canNavigate(path)) return; store.selectedProjectId = project.value.project_id; store.selectedSummary = project.value.summary ?? null; await router.push(path) }
function backToList() { return router.push({ path: '/projects', query: route.query }) }
function visible() { if (document.visibilityState === 'visible' && !loading.value && !dialog.value && !resourceItem.value) void load() }
document.addEventListener('visibilitychange', visible)
watch(() => [route.params.projectId, session.currentUser?.principal_id, JSON.stringify(session.currentUser?.project_ids), JSON.stringify(session.currentUser?.scopes), JSON.stringify(session.currentUser?.allowed_pages)], () => { project.value = null; overview.value = null; dialog.value = null; resourceItem.value = null; expanded.value = false; lastAccess.value = {}; void load() }, { immediate: true })
onBeforeUnmount(() => { generation++; controller?.abort(); clearTimeout(timer); document.removeEventListener('visibilitychange', visible) })
</script>
