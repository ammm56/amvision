<template>
  <section class="deployment-instance-panel">
    <div v-if="deployments.length === 0" class="deployment-empty-card">
      <div class="deployment-empty-card__icon" aria-hidden="true">
        <Box :size="48" :stroke-width="1.35" />
        <Rocket class="deployment-empty-card__badge" :size="18" :stroke-width="1.75" />
      </div>
      <h2>{{ t('deploymentWorkspace.empty.title') }}</h2>
      <p>{{ t('deploymentWorkspace.empty.description') }}</p>
      <div v-if="canWrite || canManageTransfers" class="deployment-empty-actions">
        <Button v-if="canWrite" variant="primary" data-deployment-action="create-wizard" :disabled="!projectId" @click="emit('create')">
          <Plus :size="15" />
          {{ t('deploymentWorkspace.actions.createDeployment') }}
        </Button>
        <Button v-if="canManageTransfers" variant="secondary" data-deployment-action="import-wizard" :disabled="!projectId" @click="emit('import')">
          <Upload :size="15" />
          {{ t('deploymentWorkspace.actions.importDeployment') }}
        </Button>
      </div>
      <div class="deployment-empty-links">
        <RouterLink to="/models">{{ t('deploymentWorkspace.actions.viewModel') }}</RouterLink>
        <span aria-hidden="true">|</span>
        <button type="button" class="deployment-link-button" data-deployment-action="capabilities" @click="emit('open-capabilities')">
          {{ t('deploymentWorkspace.actions.deviceCapabilities') }}
        </button>
      </div>
    </div>

    <template v-else>
      <div class="deployment-toolbar">
        <div class="input-with-icon deployment-search">
          <Search :size="16" aria-hidden="true" />
          <input
            v-model.trim="searchQuery"
            :placeholder="t('deploymentWorkspace.filters.searchPlaceholder')"
            :aria-label="t('deploymentWorkspace.filters.searchPlaceholder')"
          />
          <Button
            v-if="searchQuery"
            variant="ghost"
            size="sm"
            icon-only
            :aria-label="zh ? '清除搜索关键词' : 'Clear search term'"
            @click="searchQuery = ''"
          >
            <X :size="15" aria-hidden="true" />
          </Button>
        </div>
        <div class="deployment-filter-group">
          <SelectField
            fit-options
            :model-value="statusFilter"
            :options="statusFilterOptions"
            :aria-label="t('deploymentWorkspace.filters.status')"
            @update:model-value="statusFilter = String($event ?? 'all')"
          />
          <SelectField
            fit-options
            :model-value="taskFilter"
            :options="taskFilterOptions"
            :aria-label="t('deploymentWorkspace.filters.taskType')"
            @update:model-value="taskFilter = String($event ?? '')"
          />
          <div class="deployment-filter" data-deployment-filter="runtime-mode">
            <SelectField
              fit-options
              :model-value="runtimeMode"
              :options="runtimeModeOptions"
              :aria-label="t('deploymentWorkspace.filters.runtimeMode')"
              @update:model-value="emit('update:runtimeMode', $event === 'async' ? 'async' : 'sync')"
            />
          </div>
          <Button variant="secondary" :disabled="loading" :loading="loading" @click="emit('refresh')">
            <RefreshCw v-if="!loading" :size="16" aria-hidden="true" />
            {{ t('common.refresh') }}
          </Button>
        </div>
      </div>

      <div v-if="filteredDeployments.length === 0" class="resource-table deployment-table">
        <p role="status" class="deployment-no-matches">
          {{ t('deploymentWorkspace.filters.noMatches') }}
        </p>
      </div>

      <div v-else class="resource-table deployment-table" :aria-busy="loading">
        <table>
          <colgroup>
            <col class="deployment-col-name" />
            <col class="deployment-col-model" />
            <col class="deployment-col-runtime" />
            <col class="deployment-col-mode" />
            <col class="deployment-col-capacity" />
            <col class="deployment-col-status" />
            <col class="deployment-col-actions" />
          </colgroup>
          <thead>
            <tr>
              <th>{{ t('deploymentWorkspace.columns.name') }}</th>
              <th>{{ t('deploymentWorkspace.columns.modelVersion') }}</th>
              <th>{{ t('deploymentWorkspace.columns.runtimeDevice') }}</th>
              <th>{{ t('deploymentWorkspace.columns.mode') }}</th>
              <th>{{ t('deploymentWorkspace.columns.capacity') }}</th>
              <th>{{ t('deploymentWorkspace.columns.status') }}</th>
              <th>{{ t('deploymentWorkspace.columns.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in pagedDeployments"
              :key="item.deployment_instance_id"
              :data-deployment-id="item.deployment_instance_id"
            >
              <td :title="deploymentCardTitle(item)">
                <button
                  type="button"
                  class="resource-table__row-action deployment-name-link"
                  @click="emit('open-details', item.deployment_instance_id)"
                >
                  <strong>{{ deploymentCardTitle(item) }}</strong>
                </button>
              </td>
              <td :title="modelVersionSummary(item)">
                <span class="deployment-model-cell">
                  <span>{{ resolvedModelName(item) }}</span>
                  <template v-if="resolvedVersionLabel(item)">
                    <span aria-hidden="true"> · </span>
                    <span class="deployment-model-cell__version">{{ resolvedVersionLabel(item) }}</span>
                  </template>
                </span>
              </td>
              <td>
                <DeploymentRuntimeBadge
                  :backend="item.runtime_backend"
                  :device="item.device_name"
                  :precision="item.runtime_precision"
                  :build-format="typeof item.metadata?.build_format === 'string' ? item.metadata.build_format : undefined"
                />
              </td>
              <td :title="t(`deploymentOps.runtimeModes.${runtimeMode}`)">
                {{ t(`deploymentOps.runtimeModes.${runtimeMode}`) }}
              </td>
              <td :title="capacityLabel(item)">
                <span class="deployment-capacity-cell">{{ capacityLabel(item) }}</span>
              </td>
              <td>
                <div class="deployment-status-cell">
                  <span class="deployment-status-dot-label" :class="`deployment-status-dot-label--${visualState(item).tone}`">
                    <span class="deployment-status-dot" aria-hidden="true" />
                    <span>{{ t(`deploymentWorkspace.states.${visualState(item).key}`) }}</span>
                  </span>
                  <div
                    class="deployment-instance-card__states"
                    role="img"
                    :title="statusIndicatorLabel(item)"
                    :aria-label="statusIndicatorLabel(item)"
                  >
                    <span
                      v-for="indicator in statusIndicators(item)"
                      :key="indicator.channel"
                      class="deployment-status-indicator__block"
                      :class="`deployment-status-indicator__block--${indicator.tone}`"
                      :data-status-channel="indicator.channel"
                      :data-status-value="indicator.value"
                      :data-status-tone="indicator.tone"
                      aria-hidden="true"
                    />
                  </div>
                </div>
              </td>
              <td>
                <div class="deployment-row-actions">
                  <Button
                    size="sm"
                    variant="ghost"
                    class="ui-button--row-view"
                    data-deployment-action="status-details"
                    @click="emit('open-details', item.deployment_instance_id)"
                  >
                    {{ t('deploymentWorkspace.actions.details') }}
                  </Button>
                  <ResourceMenu
                    :label="t('deploymentWorkspace.actions.moreActions')"
                    :items="rowMenuItems(item)"
                    @action="runRowMenuAction(item, $event)"
                  />
                </div>
              </td>
            </tr>
          </tbody>
        </table>

        <footer class="deployment-card__footer">
          <span class="deployment-card__total">
            {{ t('deploymentWorkspace.footer.deploymentTotal', { count: filteredDeployments.length }) }}
          </span>
          <div class="deployment-card__pagination">
            <div v-if="totalPages > 1" class="deployment-page-buttons">
              <Button size="sm" variant="ghost" :disabled="currentPage <= 1" @click="currentPage -= 1">‹</Button>
              <span class="deployment-page-indicator">{{ currentPage }} / {{ totalPages }}</span>
              <Button size="sm" variant="ghost" :disabled="currentPage >= totalPages" @click="currentPage += 1">›</Button>
            </div>
            <SelectField
              fit-options
              floating
              :model-value="pageSize"
              :options="pageSizeOptions"
              @update:model-value="setPageSize"
            />
          </div>
        </footer>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, useRouter } from 'vue-router'
import { Box, Download, Play, Plus, RefreshCw, Rocket, RotateCcw, Search, Square, Trash2, Upload, X, Zap } from '@lucide/vue'
import { modelTaskLabel } from '@/modules/models/model-evaluation-types'
import Button from '@/shared/ui/components/Button.vue'
import ResourceMenu from '@/shared/ui/components/ResourceMenu.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import DeploymentRuntimeBadge from './DeploymentRuntimeBadge.vue'
import {
  computeDeploymentCapacity,
  formatDeploymentCapacityLabel,
  resolveDeploymentVisualState,
} from '../deployment-presentation'
import {
  type DeploymentRuntimeMode,
  type TaskDeploymentInstance,
  type TaskDeploymentProcessStatus,
  type TaskDeploymentRuntimeHealth,
} from '../services/deployment.service'
import { downloadTransfer, exportDeployment, type DeploymentTransfer } from '../services/deployment-transfer.service'

const props = defineProps<{
  projectId: string | null
  projectName?: string
  deployments: TaskDeploymentInstance[]
  runtimeMode: DeploymentRuntimeMode
  runtimeModeOptions: Array<{ label: string; value: string }>
  runtimeSnapshots: Record<string, { status: TaskDeploymentProcessStatus | null; health: TaskDeploymentRuntimeHealth | null }>
  runningActions: Record<string, string>
  canWrite: boolean
  canManageTransfers: boolean
  loading: boolean
  exportFor: (id: string) => DeploymentTransfer | undefined
  versionLabelsById?: Record<string, { modelName: string; versionLabel: string }>
}>()

const emit = defineEmits<{
  refresh: []
  'update:runtimeMode': [mode: DeploymentRuntimeMode]
  'open-capabilities': []
  create: []
  import: []
  'open-details': [id: string]
  start: [id: string]
  stop: [id: string]
  warmup: [id: string]
  reset: [id: string]
  delete: [id: string]
  'export-updated': [item: DeploymentTransfer]
}>()

const { t, locale } = useI18n()
const router = useRouter()
const zh = computed(() => locale.value.startsWith('zh'))

const searchQuery = ref('')
const taskFilter = ref('')
const statusFilter = ref('all')
const pageSize = ref(20)
const currentPage = ref(1)

const pageSizeOptions = computed(() => [10, 20, 50].map(size => ({
  label: t('deploymentWorkspace.footer.pageSize', { size }),
  value: size,
})))

const taskFilterOptions = computed(() => [
  { label: t('deploymentWorkspace.filters.allTasks'), value: '' },
  ...(['detection', 'classification', 'segmentation', 'pose', 'obb'] as const).map(task => ({
    label: modelTaskLabel(task, zh.value),
    value: task,
  })),
])

const statusFilterOptions = computed(() => [
  { label: t('deploymentWorkspace.filters.allStatuses'), value: 'all' },
  { label: t('deploymentWorkspace.states.running'), value: 'running' },
  { label: t('deploymentWorkspace.states.starting'), value: 'starting' },
  { label: t('deploymentWorkspace.states.stopped'), value: 'stopped' },
  { label: t('deploymentWorkspace.states.degraded'), value: 'degraded' },
  { label: t('deploymentWorkspace.states.failed'), value: 'failed' },
  { label: t('deploymentWorkspace.states.notInspected'), value: 'notInspected' },
])

function snapshot(id: string) {
  return props.runtimeSnapshots[id] ?? null
}

function capacity(item: TaskDeploymentInstance) {
  return computeDeploymentCapacity(item, snapshot(item.deployment_instance_id)?.health)
}

function visualState(item: TaskDeploymentInstance) {
  const snap = snapshot(item.deployment_instance_id)
  return resolveDeploymentVisualState(snap?.status, snap?.health)
}

function capacityLabel(item: TaskDeploymentInstance): string {
  const cap = capacity(item)
  const vis = visualState(item)
  return formatDeploymentCapacityLabel(cap, vis.key, {
    executing: t('deploymentWorkspace.capacity.executingLabel', { busy: cap.busy, total: cap.total }),
    full: t('deploymentWorkspace.capacity.fullLabel', { ready: cap.ready, total: cap.total }),
    loading: t('deploymentWorkspace.capacity.loadingLabel', { ready: cap.ready, total: cap.total }),
    ready: t('deploymentWorkspace.capacity.readyLabel', { ready: cap.ready, total: cap.total }),
    stopped: t('deploymentWorkspace.capacity.stoppedLabel'),
  })
}

function statusIndicatorTone(value: string): 'success' | 'warning' | 'danger' | 'neutral' | 'unknown' {
  const normalized = value.trim().toLowerCase()
  if (!normalized || normalized === 'unknown' || normalized === 'unloaded') return 'unknown'
  if (['fail', 'crash', 'error', 'unavailable', 'unhealthy', 'offline'].some(token => normalized.includes(token))) return 'danger'
  if (['stopped', 'inactive', 'idle', 'disabled'].some(token => normalized.includes(token))) return 'neutral'
  if (['starting', 'stopping', 'warming', 'pending', 'queued', 'created', 'degraded'].some(token => normalized.includes(token))) return 'warning'
  if (['active', 'running', 'ready', 'healthy', 'succeeded', 'success'].some(token => normalized.includes(token))) return 'success'
  return 'unknown'
}

function statusIndicators(item: TaskDeploymentInstance) {
  const runtimeStatus = snapshot(item.deployment_instance_id)?.status
  const values: Array<['deployment' | 'process' | 'desired' | 'observed', unknown]> = [
    ['deployment', item.status],
    ['process', runtimeStatus?.process_state],
    ['desired', runtimeStatus?.desired_state],
    ['observed', runtimeStatus?.observed_state],
  ]
  return values.map(([channel, rawValue]) => {
    const value = String(rawValue ?? '').trim()
    return { channel, value, tone: statusIndicatorTone(value) }
  })
}

function statusIndicatorLabel(item: TaskDeploymentInstance): string {
  const labels = {
    deployment: t('deploymentOps.columns.status'),
    process: t('deploymentOps.fields.processState'),
    desired: t('deploymentOps.fields.desiredState'),
    observed: t('deploymentOps.fields.observedState'),
  }
  return statusIndicators(item)
    .map(indicator => `${labels[indicator.channel]}：${indicator.value || '-'}`)
    .join(' · ')
}

function deploymentCardTitle(item: TaskDeploymentInstance): string {
  const displayName = item.display_name.trim()
  const generatedSourceId = item.model_build_id || item.model_version_id
  const generatedName = `${item.model_name} ${generatedSourceId}`.trim()
  if (!displayName || displayName === item.deployment_instance_id || displayName === generatedName) {
    return item.model_name || item.deployment_instance_id
  }
  return displayName
}

function resolvedModelName(item: TaskDeploymentInstance): string {
  return item.model_display_name || props.versionLabelsById?.[item.model_version_id]?.modelName || item.model_name
}

function resolvedVersionLabel(item: TaskDeploymentInstance): string {
  return item.model_version_number ? `v${item.model_version_number}` : (props.versionLabelsById?.[item.model_version_id]?.versionLabel || '')
}

function modelVersionSummary(item: TaskDeploymentInstance): string {
  return [modelTaskLabel(item.task_type, zh.value), resolvedModelName(item), resolvedVersionLabel(item)]
    .filter(Boolean)
    .join(' · ')
}

const filteredDeployments = computed(() => {
  const term = searchQuery.value.toLowerCase()
  return props.deployments.filter((item) => {
    if (taskFilter.value && item.task_type !== taskFilter.value) return false
    if (statusFilter.value !== 'all' && visualState(item).key !== statusFilter.value) return false
    if (!term) return true
    const text = `${deploymentCardTitle(item)} ${item.model_name} ${resolvedModelName(item)} ${item.deployment_instance_id}`.toLowerCase()
    return text.includes(term)
  })
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredDeployments.value.length / pageSize.value)))

const pagedDeployments = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredDeployments.value.slice(start, start + pageSize.value)
})

watch([filteredDeployments, pageSize], () => {
  if (currentPage.value > totalPages.value) {
    currentPage.value = totalPages.value
  }
})

function setPageSize(value: unknown): void {
  const parsed = Number(value)
  if (Number.isInteger(parsed) && parsed > 0) {
    pageSize.value = parsed
    currentPage.value = 1
  }
}

function isBusy(item: TaskDeploymentInstance): boolean {
  return Boolean(props.runningActions[item.deployment_instance_id])
}

function canStart(item: TaskDeploymentInstance): boolean {
  const state = visualState(item).key
  return !['running', 'busyFull', 'starting'].includes(state)
}

function canStop(item: TaskDeploymentInstance): boolean {
  if (isBusy(item)) return false
  const status = snapshot(item.deployment_instance_id)?.status
  if (status?.desired_state === 'running') return true
  const state = visualState(item).key
  return ['running', 'busyFull', 'starting', 'degraded'].includes(state)
}

function rowMenuItems(item: TaskDeploymentInstance) {
  const items: Array<{ id: string; label: string; icon?: Component; disabled?: boolean; danger?: boolean }> = []
  if (props.canWrite) {
    if (canStart(item)) {
      items.push({ id: 'start', label: t('deploymentOps.actions.start'), icon: Play, disabled: isBusy(item) })
    } else {
      items.push({ id: 'stop', label: t('deploymentOps.actions.stop'), icon: Square, disabled: !canStop(item) })
    }
  }
  items.push({ id: 'inference', label: t('deploymentWorkspace.actions.openInference'), icon: Zap })
  if (props.canWrite) {
    items.push(
      { id: 'warmup', label: t('deploymentOps.actions.warmup'), icon: Play, disabled: isBusy(item) },
      { id: 'reset', label: t('deploymentOps.actions.reset'), icon: RotateCcw, disabled: isBusy(item) },
    )
  }
  if (props.canManageTransfers && props.projectId) {
    items.push({ id: 'export', label: t('deploymentTransfer.export'), icon: Upload, disabled: isBusy(item) })
    const op = props.exportFor(item.deployment_instance_id)
    if (op?.state === 'completed' && op.zip_state === 'available') {
      items.push({ id: 'download', label: t('deploymentTransfer.download'), icon: Download })
    }
  }
  if (props.canWrite) {
    items.push({ id: 'delete', label: t('deploymentOps.actions.delete'), icon: Trash2, danger: true, disabled: isBusy(item) })
  }
  return items
}

async function runRowMenuAction(item: TaskDeploymentInstance, action: string): Promise<void> {
  if (action === 'start') {
    emit('start', item.deployment_instance_id)
  } else if (action === 'stop') {
    emit('stop', item.deployment_instance_id)
  } else if (action === 'inference') {
    void router.push({ path: '/inference', query: { deployment: item.deployment_instance_id, task: item.task_type || 'detection' } })
  } else if (action === 'warmup') {
    emit('warmup', item.deployment_instance_id)
  } else if (action === 'reset') {
    emit('reset', item.deployment_instance_id)
  } else if (action === 'delete') {
    emit('delete', item.deployment_instance_id)
  } else if (action === 'export' && props.projectId) {
    const op = await exportDeployment(props.projectId, item.deployment_instance_id)
    emit('export-updated', op)
  } else if (action === 'download' && props.projectId) {
    const op = props.exportFor(item.deployment_instance_id)
    if (op) await downloadTransfer(props.projectId, op)
  }
}
</script>

<style scoped>
.deployment-instance-panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  min-width: 0;
  max-width: 100%;
}

.deployment-empty-card {
  display: grid;
  justify-items: center;
  gap: 10px;
  padding: 56px 24px 72px;
  border: 1px solid var(--am-border);
  border-radius: 10px;
  background: var(--am-surface);
  text-align: center;
}

.deployment-empty-card__icon {
  position: relative;
  display: grid;
  place-items: center;
  color: var(--am-text-muted);
  margin-bottom: 4px;
}

.deployment-empty-card__badge {
  position: absolute;
  bottom: 4px;
  left: -4px;
  color: var(--am-text-muted);
  background: var(--am-surface);
  border-radius: 999px;
}

.deployment-empty-card h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
}

.deployment-empty-card p {
  margin: 0;
  color: var(--am-text-muted);
}

.deployment-empty-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
  margin-top: 8px;
}

.deployment-empty-links {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
  font-size: 13px;
  color: var(--am-border);
}

.deployment-empty-links a,
.deployment-link-button {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--am-action-primary-strong);
  font: inherit;
  cursor: pointer;
}

.deployment-empty-links a:hover,
.deployment-link-button:hover {
  text-decoration: underline;
}

.deployment-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 16px;
  margin: 0 0 16px;
  min-width: 0;
  max-width: 100%;
}

.deployment-search {
  width: clamp(220px, 26vw, 380px);
  max-width: 100%;
  margin-inline-end: auto;
  grid-auto-flow: column;
}

.deployment-filter-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.deployment-filter {
  display: flex;
  align-items: center;
}

.deployment-no-matches {
  margin: 0;
  padding: 28px 16px;
  text-align: center;
  color: var(--am-text-muted);
}

.deployment-table {
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface-raised);
  overflow: auto;
}

.deployment-table table {
  width: 100%;
  min-width: 720px;
  table-layout: fixed;
  border-collapse: collapse;
}

.deployment-col-name { width: 22%; }
.deployment-col-model { width: 23%; }
.deployment-col-runtime { width: 13%; }
.deployment-col-mode { width: 7%; }
.deployment-col-capacity { width: 11%; }
.deployment-col-status { width: 12%; }
.deployment-col-actions { width: 12%; }

.deployment-table th,
.deployment-table td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--am-border);
  text-align: left;
  vertical-align: middle;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.deployment-table th {
  background: var(--am-table-header);
  color: var(--am-text-muted);
  font-size: 12px;
  font-weight: 700;
}

.deployment-table td {
  font-size: 14px;
}

.deployment-name-link {
  display: block;
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--am-text-strong, var(--am-text));
  font: inherit;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}

.deployment-name-link:hover {
  color: var(--am-action-primary-strong);
}

.deployment-model-cell {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.deployment-model-cell__version {
  color: var(--am-text-muted);
}

.deployment-capacity-cell {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.deployment-status-cell {
  display: grid;
  gap: 4px;
  justify-items: start;
}

.deployment-status-dot-label {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-weight: 500;
  white-space: nowrap;
}

.deployment-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--am-neutral-icon);
}

.deployment-status-dot-label--success .deployment-status-dot { background: var(--am-action-primary); }
.deployment-status-dot-label--info .deployment-status-dot,
.deployment-status-dot-label--warning .deployment-status-dot { background: var(--am-warning-icon); }
.deployment-status-dot-label--danger .deployment-status-dot { background: var(--am-danger-icon); }
.deployment-status-dot-label--neutral .deployment-status-dot { background: var(--am-neutral-icon); }

.deployment-instance-card__states {
  display: flex;
  align-items: center;
  gap: 2px;
}

.deployment-status-indicator__block {
  display: block;
  width: 7px;
  height: 3px;
  border-radius: 1.5px;
  background: var(--am-neutral-icon);
}

.deployment-status-indicator__block--success { background: var(--am-action-primary); }
.deployment-status-indicator__block--warning { background: var(--am-warning-icon); }
.deployment-status-indicator__block--danger { background: var(--am-danger-icon); }
.deployment-status-indicator__block--neutral { background: var(--am-neutral-icon); }
.deployment-status-indicator__block--unknown { background: var(--am-border); }

.deployment-row-actions {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex-wrap: nowrap;
  white-space: nowrap;
}

.deployment-card__footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
}

.deployment-card__total {
  font-size: 13px;
  color: var(--am-text-muted);
}

.deployment-card__pagination {
  display: flex;
  align-items: center;
  gap: 10px;
}

.deployment-page-buttons {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.deployment-page-indicator {
  font-size: 12px;
  color: var(--am-text-muted);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 1200px) {
  .deployment-toolbar {
    gap: 12px;
  }

  .deployment-search {
    width: 220px;
  }
}

@media (max-width: 1180px) {
  .deployment-table th,
  .deployment-table td {
    padding: 11px 10px;
  }

  .deployment-col-mode,
  .deployment-table th:nth-child(4),
  .deployment-table td:nth-child(4) {
    display: none;
  }
}
</style>
