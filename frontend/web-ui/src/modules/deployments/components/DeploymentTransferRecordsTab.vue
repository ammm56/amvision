<template>
  <section class="deployment-transfer-records">
    <div v-if="allDirectionRows.length > 0" class="deployment-toolbar">
      <div class="input-with-icon deployment-records-toolbar__search">
        <Search :size="16" aria-hidden="true" />
        <input
          v-model.trim="searchQuery"
          :aria-label="direction === 'import' ? t('deploymentWorkspace.filters.importSearchPlaceholder') : t('deploymentWorkspace.filters.exportSearchPlaceholder')"
          :placeholder="direction === 'import' ? t('deploymentWorkspace.filters.importSearchPlaceholder') : t('deploymentWorkspace.filters.exportSearchPlaceholder')"
        />
        <Button
          v-if="searchQuery"
          variant="ghost"
          size="sm"
          icon-only
          :aria-label="t('deploymentWorkspace.actions.clearSearch')"
          @click="searchQuery = ''"
        >
          <X :size="15" aria-hidden="true" />
        </Button>
      </div>
      <div class="deployment-filter-group">
        <SelectField
          fit-options
          :model-value="stateFilter"
          :options="stateFilterOptions"
          @update:model-value="stateFilter = String($event ?? 'all')"
        />
        <SelectField
          v-if="direction === 'export'"
          fit-options
          :model-value="fileStateFilter"
          :options="fileStateFilterOptions"
          @update:model-value="fileStateFilter = String($event ?? 'all')"
        />
        <Button variant="secondary" :loading="refreshing" @click="emit('refresh')">
          <RefreshCw :size="15" />
          {{ t('common.refresh') }}
        </Button>
      </div>
    </div>

    <p v-if="direction === 'export' && allDirectionRows.length > 0" class="deployment-records-subhint">
      <Info :size="14" aria-hidden="true" />
      <span>{{ t('deploymentWorkspace.transfers.exportHint') }}</span>
    </p>

    <EmptyState
      v-if="allDirectionRows.length === 0"
      :title="direction === 'import' ? t('deploymentWorkspace.transfers.importsEmptyTitle') : t('deploymentWorkspace.transfers.exportsEmptyTitle')"
      :description="direction === 'import' ? t('deploymentWorkspace.transfers.importsEmptyDescription') : t('deploymentWorkspace.transfers.exportsEmptyDescription')"
    >
      <div class="deployment-empty-actions">
        <Button v-if="direction === 'import' && canWrite" variant="primary" @click="emit('begin-import')">
          <Download :size="15" />
          {{ t('deploymentWorkspace.actions.importDeployment') }}
        </Button>
        <Button variant="secondary" :loading="refreshing" @click="emit('refresh')">
          <RefreshCw :size="15" />
          {{ t('common.refresh') }}
        </Button>
      </div>
    </EmptyState>

    <div v-else-if="rows.length === 0" class="resource-table deployment-records-table">
      <p role="status" class="deployment-no-matches">
        {{ t('deploymentWorkspace.filters.noTransferMatches') }}
      </p>
    </div>

    <div v-else class="resource-table deployment-records-table">
      <table>
        <colgroup>
          <col style="width: 23%" />
          <col style="width: 20%" />
          <col style="width: 13%" />
          <col style="width: 13%" />
          <col style="width: 15%" />
          <col style="width: 16%" />
        </colgroup>
        <thead>
          <tr v-if="direction === 'import'">
            <th :title="t('deploymentWorkspace.columns.fileName')">{{ t('deploymentWorkspace.columns.fileName') }}</th>
            <th :title="t('deploymentWorkspace.columns.targetDeployment')">{{ t('deploymentWorkspace.columns.targetDeployment') }}</th>
            <th :title="t('deploymentWorkspace.columns.importResult')">{{ t('deploymentWorkspace.columns.importResult') }}</th>
            <th :title="t('deploymentWorkspace.columns.serviceStatus')">{{ t('deploymentWorkspace.columns.serviceStatus') }}</th>
            <th :title="t('deploymentWorkspace.columns.updatedAt')">{{ t('deploymentWorkspace.columns.updatedAt') }} ↓</th>
            <th :title="t('deploymentWorkspace.columns.actions')">{{ t('deploymentWorkspace.columns.actions') }}</th>
          </tr>
          <tr v-else>
            <th :title="t('deploymentWorkspace.columns.fileName')">{{ t('deploymentWorkspace.columns.fileName') }}</th>
            <th :title="t('deploymentWorkspace.columns.sourceDeployment')">{{ t('deploymentWorkspace.columns.sourceDeployment') }}</th>
            <th :title="t('deploymentWorkspace.columns.taskStatus')">{{ t('deploymentWorkspace.columns.taskStatus') }}</th>
            <th :title="t('deploymentWorkspace.columns.fileStatus')">{{ t('deploymentWorkspace.columns.fileStatus') }}</th>
            <th :title="t('deploymentWorkspace.columns.createdAt')">{{ t('deploymentWorkspace.columns.createdAt') }} ↓</th>
            <th :title="t('deploymentWorkspace.columns.actions')">{{ t('deploymentWorkspace.columns.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in pagedRows" :key="item.operation_id" :data-transfer-id="item.operation_id">
            <td :title="item.error ? `${recordTitle(item)} — ${item.error}` : recordTitle(item)">
              <strong class="transfer-cell-ellipsis">{{ recordTitle(item) }}</strong>
              <span v-if="item.error" class="transfer-record-error">{{ item.error }}</span>
            </td>
            <td :title="deploymentTitleForRecord(item)">{{ deploymentTitleForRecord(item) }}</td>
            <td :title="transferStateLabel(item.state)">
              <span class="transfer-status-indicator" :class="`transfer-status-indicator--${stateTone(item.state)}`">
                <CheckCircle2 v-if="item.state === 'completed'" :size="15" />
                <XCircle v-else-if="item.state === 'failed'" :size="15" />
                <Clock v-else-if="transferIsActive(item.state)" :size="15" />
                <MinusCircle v-else :size="15" />
                <span>{{ transferStateLabel(item.state) }}</span>
              </span>
            </td>
            <td v-if="direction === 'import'" :title="importServiceState(item).label">
              <span class="transfer-dot-label" :class="`transfer-dot-label--${importServiceState(item).tone}`">
                <span class="transfer-dot" aria-hidden="true" />
                <span>{{ importServiceState(item).label }}</span>
              </span>
            </td>
            <td v-else :title="zipStateLabel(item)">
              <span class="transfer-dot-label" :class="`transfer-dot-label--${zipStateTone(item)}`">
                <span class="transfer-dot" aria-hidden="true" />
                <span>{{ zipStateLabel(item) }}</span>
              </span>
            </td>
            <td class="transfer-time-cell" :title="(item.updated_at || item.created_at) ? formatSystemDateTime(item.updated_at || item.created_at || '') : '—'">
              {{ (item.updated_at || item.created_at) ? formatSystemDateTime(item.updated_at || item.created_at || '') : '—' }}
            </td>
            <td>
              <div class="transfer-record-actions">
                <button
                  v-if="direction === 'export' && canDownloadExport(item)"
                  type="button"
                  class="transfer-action-link"
                  data-transfer-action="download"
                  :disabled="downloadingId === item.operation_id"
                  @click="download(item)"
                >
                  {{ t('deploymentWorkspace.actions.download') }}
                </button>
                <button
                  type="button"
                  class="transfer-action-link"
                  @click="detailItem = item"
                >
                  {{ t('deploymentWorkspace.actions.details') }}
                </button>
                <Button
                  v-if="direction === 'export' && canReexport(item) && canWrite"
                  size="sm"
                  variant="secondary"
                  data-transfer-action="reexport"
                  :loading="reexportingId === item.operation_id"
                  @click="reexport(item)"
                >
                  {{ t('deploymentWorkspace.actions.reexport') }}
                </Button>
                <Button
                  v-if="direction === 'import' && ['ready', 'needs_attention', 'failed'].includes(item.state) && item.plan && canWrite"
                  size="sm"
                  variant="secondary"
                  @click="emit('open-import', item)"
                >
                  {{ t('deploymentTransfer.continue') }}
                </Button>
                <Button
                  v-if="direction === 'import' && item.state === 'failed' && canWrite"
                  size="sm"
                  variant="ghost"
                  @click="emit('dismiss', item)"
                >
                  {{ t('deploymentTransfer.clear') }}
                </Button>
                <Button
                  v-if="transferIsActive(item.state) && canWrite"
                  size="sm"
                  variant="ghost"
                  @click="emit('cancel', item)"
                >
                  {{ t('deploymentTransfer.cancel') }}
                </Button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <footer class="deployment-card__footer">
        <span class="deployment-card__total">
          {{ t('deploymentWorkspace.footer.recordTotal', { count: rows.length }) }}
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

    <SideDrawer
      :open="!!detailItem"
      :title="detailItem ? recordTitle(detailItem) : t('deploymentWorkspace.transfers.detailTitle')"
      :close-label="t('common.close')"
      panel-class="transfer-detail-drawer"
      @close="detailItem = null"
    >
      <template v-if="detailItem">
        <div class="transfer-detail">
          <div class="transfer-detail__hero">
            <span class="transfer-status-indicator" :class="`transfer-status-indicator--${stateTone(detailItem.state)}`">
              <CheckCircle2 v-if="detailItem.state === 'completed'" :size="16" />
              <XCircle v-else-if="detailItem.state === 'failed'" :size="16" />
              <Clock v-else-if="transferIsActive(detailItem.state)" :size="16" />
              <MinusCircle v-else :size="16" />
              <strong>{{ transferStateLabel(detailItem.state) }}</strong>
            </span>
            <p v-if="direction === 'export'" class="transfer-detail__hero-sub">{{ zipStateLabel(detailItem) }}</p>
          </div>

          <InlineMessage v-if="direction === 'export' && detailItem.state === 'completed' && detailItem.zip_state && detailItem.zip_state !== 'available'" tone="warning">
            {{ t('deploymentWorkspace.transfers.fileMissingHint') }}
          </InlineMessage>
          <InlineError v-if="detailItem.error" :message="detailItem.error" />

          <section class="transfer-detail__section">
            <h3>{{ t('deploymentWorkspace.transfers.basicInfoTitle') }}</h3>
            <dl class="transfer-detail__meta-grid">
              <div><dt>{{ t('deploymentWorkspace.columns.fileName') }}</dt><dd>{{ recordTitle(detailItem) }}</dd></div>
              <div><dt>{{ t('deploymentWorkspace.columns.size') }}</dt><dd>{{ sizeText(detailItem) }}</dd></div>
              <div>
                <dt>{{ direction === 'export' ? t('deploymentWorkspace.columns.sourceDeployment') : t('deploymentWorkspace.columns.targetDeployment') }}</dt>
                <dd>{{ deploymentTitleForRecord(detailItem) }}</dd>
              </div>
              <div v-if="detailVersionInfo">
                <dt>{{ t('deploymentWorkspace.columns.modelVersion') }}</dt>
                <dd class="transfer-detail__version-dd">
                  <span>{{ detailVersionInfo.modelName }}</span>
                  <template v-if="detailVersionInfo.versionLabel">
                    <span class="transfer-detail__version-sep" aria-hidden="true">·</span>
                    <span class="transfer-version-chip">{{ detailVersionInfo.versionLabel }}</span>
                  </template>
                </dd>
              </div>
              <div>
                <dt>{{ t('deploymentWorkspace.columns.runtimeDevice') }}</dt>
                <dd class="transfer-detail__runtime-dd">
                  <DeploymentRuntimeBadge
                    v-if="detailItem.summary"
                    :backend="detailItem.summary.deployment.runtime_backend"
                    :device="detailItem.summary.deployment.device_name"
                    :precision="detailItem.summary.inference.runtime_precision"
                  />
                  <span>{{ runtimeText(detailItem) }}</span>
                </dd>
              </div>
              <div><dt>{{ t('deploymentWorkspace.columns.createdAt') }}</dt><dd>{{ detailItem.created_at ? formatSystemDateTime(detailItem.created_at) : '—' }}</dd></div>
              <div><dt>{{ t('deploymentWorkspace.columns.updatedAt') }}</dt><dd>{{ detailItem.updated_at ? formatSystemDateTime(detailItem.updated_at) : '—' }}</dd></div>
              <div v-if="direction === 'export'"><dt>{{ t('deploymentWorkspace.columns.fileStatus') }}</dt><dd>{{ zipStateLabel(detailItem) }}</dd></div>
              <div v-if="detailItem.summary"><dt>{{ t('deploymentWorkspace.columns.taskType') }}</dt><dd>{{ modelTaskLabel(detailItem.summary.model.task_type, zh) }}</dd></div>
            </dl>
          </section>

          <section v-if="direction === 'export' && detailItem.state === 'completed'" class="transfer-detail__section">
            <h3>{{ t('deploymentWorkspace.transfers.fileContentsTitle') }}</h3>
            <p class="transfer-detail__desc">{{ t('deploymentWorkspace.transfers.fileContentsDesc') }}</p>
            <ul class="transfer-detail__contents">
              <li>
                <Check :size="15" aria-hidden="true" />
                <div>
                  <strong>{{ t('deploymentWorkspace.transfers.contentModel') }}</strong>
                  <span>{{ t('deploymentWorkspace.transfers.contentModelDesc') }}</span>
                </div>
              </li>
              <li>
                <Check :size="15" aria-hidden="true" />
                <div>
                  <strong>{{ t('deploymentWorkspace.transfers.contentArtifact') }}</strong>
                  <span>{{ t('deploymentWorkspace.transfers.contentArtifactDesc') }}</span>
                </div>
              </li>
              <li>
                <Check :size="15" aria-hidden="true" />
                <div>
                  <strong>{{ t('deploymentWorkspace.transfers.contentContract') }}</strong>
                  <span>{{ t('deploymentWorkspace.transfers.contentContractDesc') }}</span>
                </div>
              </li>
              <li>
                <Check :size="15" aria-hidden="true" />
                <div>
                  <strong>{{ t('deploymentWorkspace.transfers.contentConfig') }}</strong>
                  <span>{{ t('deploymentWorkspace.transfers.contentConfigDesc') }}</span>
                </div>
              </li>
            </ul>
            <p class="transfer-detail__snapshot-note">
              <Info :size="14" aria-hidden="true" />
              <span>{{ t('deploymentWorkspace.transfers.exportSnapshotHint') }}</span>
            </p>
          </section>
        </div>
      </template>

      <template v-if="detailItem" #footer>
        <div class="transfer-detail__footer">
          <Button variant="secondary" size="sm" @click="detailItem = null">{{ t('common.close') }}</Button>
          <div class="transfer-detail__footer-right">
            <Button
              v-if="direction === 'export' && detailItem.deployment_id && canWrite"
              variant="secondary"
              size="sm"
              :loading="reexportingId === detailItem.operation_id"
              @click="reexport(detailItem)"
            >
              <RefreshCw :size="14" />{{ t('deploymentWorkspace.actions.reexport') }}
            </Button>
            <Button
              v-if="direction === 'export'"
              variant="primary"
              size="sm"
              data-transfer-action="download"
              :disabled="!canDownloadExport(detailItem) || downloadingId === detailItem.operation_id"
              :loading="downloadingId === detailItem.operation_id"
              @click="download(detailItem)"
            >
              <Download :size="14" />{{ t('deploymentWorkspace.actions.download') }}
            </Button>
          </div>
        </div>
      </template>
    </SideDrawer>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, CheckCircle2, Clock, Download, Info, MinusCircle, RefreshCw, Search, X, XCircle } from '@lucide/vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import InlineMessage from '@/shared/ui/feedback/InlineMessage.vue'
import { modelTaskLabel } from '@/modules/models/model-evaluation-types'
import { formatDeploymentBackend, formatDeploymentDeviceName, resolveDeploymentVisualState } from '../deployment-presentation'
import DeploymentRuntimeBadge from './DeploymentRuntimeBadge.vue'
import type {
  TaskDeploymentInstance,
  TaskDeploymentProcessStatus,
  TaskDeploymentRuntimeHealth,
} from '../services/deployment.service'
import {
  downloadTransfer,
  exportDeployment,
  transferIsActive,
  transferStateLabel,
  type DeploymentTransfer,
} from '../services/deployment-transfer.service'

const props = defineProps<{
  projectId: string
  projectName?: string
  direction: 'import' | 'export'
  items: DeploymentTransfer[]
  deployments?: TaskDeploymentInstance[]
  runtimeSnapshots?: Record<string, { status: TaskDeploymentProcessStatus | null; health: TaskDeploymentRuntimeHealth | null }>
  versionLabelsById?: Record<string, { modelName: string; versionLabel: string }>
  canWrite?: boolean
  refreshing?: boolean
}>()

const emit = defineEmits<{
  refresh: []
  'begin-import': []
  'open-import': [item: DeploymentTransfer]
  cancel: [item: DeploymentTransfer]
  dismiss: [item: DeploymentTransfer]
  updated: [item: DeploymentTransfer]
}>()

const { t, locale } = useI18n()
const zh = computed(() => locale.value.startsWith('zh'))
const detailItem = ref<DeploymentTransfer | null>(null)
const downloadingId = ref<string | null>(null)
const reexportingId = ref<string | null>(null)
const searchQuery = ref('')
const stateFilter = ref('all')
const fileStateFilter = ref('all')
const pageSize = ref(20)
const currentPage = ref(1)

const pageSizeOptions = computed(() => [10, 20, 50].map(size => ({
  label: t('deploymentWorkspace.footer.pageSize', { size }),
  value: size,
})))

const stateFilterOptions = computed(() => [
  { label: props.direction === 'export' ? t('deploymentWorkspace.filters.generationStatus') : t('deploymentWorkspace.filters.allStatuses'), value: 'all' },
  { label: transferStateLabel('completed'), value: 'completed' },
  { label: transferStateLabel('failed'), value: 'failed' },
  { label: transferStateLabel('cancelled'), value: 'cancelled' },
])

const fileStateFilterOptions = computed(() => [
  { label: t('deploymentWorkspace.filters.fileStatus'), value: 'all' },
  { label: t('deploymentWorkspace.transfers.zipStates.available'), value: 'available' },
  { label: t('deploymentWorkspace.transfers.zipStates.missing'), value: 'missing' },
  { label: t('deploymentWorkspace.transfers.zipStates.pending'), value: 'pending' },
])

const allDirectionRows = computed(() => props.items
  .filter(item => item.direction === props.direction)
  .sort((a, b) => Date.parse(b.updated_at || b.created_at || '') - Date.parse(a.updated_at || a.created_at || '')))

const rows = computed(() => {
  const term = searchQuery.value.toLowerCase()
  return allDirectionRows.value.filter((item) => {
    if (stateFilter.value !== 'all' && item.state !== stateFilter.value) return false
    if (props.direction === 'export' && fileStateFilter.value !== 'all') {
      const zipKey = item.zip_state || (item.state === 'completed' ? 'available' : 'pending')
      if (zipKey !== fileStateFilter.value) return false
    }
    if (!term) return true
    const text = `${recordTitle(item)} ${deploymentTitleForRecord(item)} ${item.operation_id}`.toLowerCase()
    return text.includes(term)
  })
})

const totalPages = computed(() => Math.max(1, Math.ceil(rows.value.length / pageSize.value)))
const pagedRows = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return rows.value.slice(start, start + pageSize.value)
})

watch([rows, pageSize], () => {
  if (currentPage.value > totalPages.value) currentPage.value = totalPages.value
})

function setPageSize(value: unknown): void {
  const parsed = Number(value)
  if (Number.isInteger(parsed) && parsed > 0) {
    pageSize.value = parsed
    currentPage.value = 1
  }
}

function recordTitle(item: DeploymentTransfer): string {
  return item.file_name || item.display_name || item.summary?.deployment.display_name || item.operation_id
}

function versionInfoForRecord(item: DeploymentTransfer): { modelName: string; versionLabel: string } | null {
  const matched = item.deployment_id
    ? props.deployments?.find(d => d.deployment_instance_id === item.deployment_id)
    : undefined
  const versionId = matched?.model_version_id
    || item.mapping?.model_version_id
    || item.plan?.mapping?.model_version_id
    || item.plan?.original?.model_version_id
  if (versionId && props.versionLabelsById?.[versionId]) {
    return props.versionLabelsById[versionId]
  }
  if (matched?.model_name) {
    return { modelName: matched.model_name, versionLabel: '' }
  }
  if (item.summary?.model.model_name) {
    return { modelName: item.summary.model.model_name, versionLabel: '' }
  }
  return null
}

const detailVersionInfo = computed(() => (detailItem.value ? versionInfoForRecord(detailItem.value) : null))

function deploymentTitleForRecord(item: DeploymentTransfer): string {
  const id = item.deployment_id
  if (id && props.deployments?.length) {
    const matched = props.deployments.find(d => d.deployment_instance_id === id)
    if (matched) {
      const displayName = matched.display_name?.trim() || ''
      const generatedSourceId = matched.model_build_id || matched.model_version_id
      const generatedName = `${matched.model_name} ${generatedSourceId}`.trim()
      if (displayName && displayName !== matched.deployment_instance_id && displayName !== generatedName) {
        return displayName
      }
      return props.versionLabelsById?.[matched.model_version_id]?.modelName || matched.model_name || id
    }
  }
  return item.display_name || item.summary?.deployment.display_name || versionInfoForRecord(item)?.modelName || id || '—'
}

function importServiceState(item: DeploymentTransfer): { label: string; tone: 'success' | 'danger' | 'neutral' | 'warning' | 'info' } {
  if (!item.deployment_id || item.state !== 'completed') {
    return { label: t('deploymentWorkspace.states.notCreated'), tone: 'neutral' }
  }
  const snap = props.runtimeSnapshots?.[item.deployment_id]
  if (!snap) return { label: t('deploymentWorkspace.states.stopped'), tone: 'neutral' }
  const vis = resolveDeploymentVisualState(snap.status, snap.health)
  return {
    label: t(`deploymentWorkspace.states.${vis.key}`),
    tone: vis.tone,
  }
}

function runtimeText(item: DeploymentTransfer): string {
  const summary = item.summary
  if (!summary) return '—'
  const dev = formatDeploymentDeviceName(summary.deployment.device_name) || t('deploymentOps.options.automaticDefault')
  return `${formatDeploymentBackend(summary.deployment.runtime_backend)} ${summary.inference.runtime_precision.toUpperCase()} · ${dev}`
}

function sizeText(item: DeploymentTransfer): string {
  const bytes = item.total_bytes || item.upload_bytes || item.progress_bytes
  if (!bytes || bytes <= 0) return '—'
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function stateTone(state: string): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  if (state === 'completed') return 'success'
  if (state === 'failed') return 'danger'
  if (state === 'needs_attention') return 'warning'
  if (transferIsActive(state) || state === 'ready') return 'info'
  return 'neutral'
}

function zipStateLabel(item: DeploymentTransfer): string {
  if (item.zip_state) return t(`deploymentWorkspace.transfers.zipStates.${item.zip_state}`)
  if (item.state === 'completed') return t('deploymentWorkspace.transfers.zipStates.available')
  return t('deploymentWorkspace.transfers.zipStates.pending')
}

function zipStateTone(item: DeploymentTransfer): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  if (item.zip_state === 'available' || (!item.zip_state && item.state === 'completed')) return 'success'
  if (item.zip_state === 'missing' || item.zip_state === 'unavailable') return 'danger'
  return 'neutral'
}

function canDownloadExport(item: DeploymentTransfer): boolean {
  if (item.state !== 'completed') return false
  return item.zip_state === undefined || item.zip_state === null || item.zip_state === 'available'
}

function canReexport(item: DeploymentTransfer): boolean {
  return !!item.deployment_id && (item.state === 'failed' || item.state === 'cancelled' || (item.state === 'completed' && item.zip_state !== 'available'))
}

async function download(item: DeploymentTransfer): Promise<void> {
  if (downloadingId.value) return
  downloadingId.value = item.operation_id
  try {
    await downloadTransfer(props.projectId, item)
  } finally {
    downloadingId.value = null
  }
}

async function reexport(item: DeploymentTransfer): Promise<void> {
  if (!item.deployment_id || reexportingId.value) return
  reexportingId.value = item.operation_id
  try {
    const updated = await exportDeployment(props.projectId, item.deployment_id)
    emit('updated', updated)
    if (detailItem.value?.operation_id === item.operation_id) {
      detailItem.value = updated
    }
  } finally {
    reexportingId.value = null
  }
}
</script>

<style scoped>
.deployment-transfer-records {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  min-width: 0;
  max-width: 100%;
}

.deployment-records-subhint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--am-text-muted);
}

.deployment-empty-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
}

.deployment-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px 16px;
  margin: 0 0 12px;
  min-width: 0;
  max-width: 100%;
}

.deployment-records-toolbar__search {
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

.deployment-no-matches {
  margin: 0;
  padding: 28px 16px;
  text-align: center;
  font-size: 14px;
  color: var(--am-text-muted);
}

.deployment-records-table {
  width: 100%;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md, 8px);
  background: var(--am-surface);
  overflow: auto;
}

.deployment-records-table table {
  width: 100%;
  min-width: 720px;
  table-layout: fixed;
  border-collapse: collapse;
}

.deployment-records-table th,
.deployment-records-table td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--am-border);
  text-align: left;
  vertical-align: middle;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.deployment-records-table th:first-child,
.deployment-records-table td:first-child { padding-left: 16px; }
.deployment-records-table th:last-child,
.deployment-records-table td:last-child { padding-right: 16px; }

.deployment-records-table th {
  background: var(--am-table-header);
  color: var(--am-text-muted);
  font-size: 12px;
  font-weight: 700;
}

.deployment-records-table td {
  font-size: 14px;
}

.transfer-cell-ellipsis {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.transfer-status-indicator {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
  white-space: nowrap;
}

.transfer-status-indicator--success { color: var(--am-action-primary-strong); }
.transfer-status-indicator--warning,
.transfer-status-indicator--info { color: var(--am-warning-text); }
.transfer-status-indicator--danger { color: var(--am-danger-text); }
.transfer-status-indicator--neutral { color: var(--am-text-muted); }

.transfer-dot-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.transfer-dot {
  flex-shrink: 0;
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--am-neutral-icon);
}

.transfer-dot-label--success .transfer-dot { background: var(--am-action-primary); }
.transfer-dot-label--warning .transfer-dot,
.transfer-dot-label--info .transfer-dot { background: var(--am-warning-icon); }
.transfer-dot-label--danger .transfer-dot { background: var(--am-danger-icon); }

.transfer-time-cell {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  font-size: 13px;
}

.transfer-record-error {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  color: var(--am-danger-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.transfer-record-actions {
  display: inline-flex;
  flex-wrap: nowrap;
  gap: 10px;
  align-items: center;
  white-space: nowrap;
}

.transfer-action-link {
  padding: 2px;
  border: 0;
  background: transparent;
  color: var(--am-action-primary-strong);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
}

.transfer-action-link:hover { text-decoration: underline; }
.transfer-action-link:disabled { opacity: 0.5; cursor: not-allowed; }

.deployment-card__footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 20px;
}

.deployment-card__total { font-size: 13px; color: var(--am-text-muted); }
.deployment-card__pagination { display: flex; align-items: center; gap: 10px; }
.deployment-page-buttons { display: inline-flex; align-items: center; gap: 4px; }
.deployment-page-indicator { font-size: 12px; color: var(--am-text-muted); }

:global(.transfer-detail-drawer.side-drawer) {
  width: min(620px, calc(100vw - 36px));
}

.transfer-detail { display: grid; gap: 18px; }
.transfer-detail__hero { display: grid; gap: 4px; }
.transfer-detail__hero-sub { margin: 0; font-size: 13px; color: var(--am-text-muted); }

.transfer-detail__section { display: grid; gap: 10px; }
.transfer-detail__section h3 { margin: 0; font-size: 14px; font-weight: 700; }
.transfer-detail__desc { margin: 0; font-size: 13px; color: var(--am-text-muted); }

.transfer-detail__meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 16px;
  margin: 0;
  font-size: 13px;
}

.transfer-detail__meta-grid > div {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
}

.transfer-detail__meta-grid dt { color: var(--am-text-muted); white-space: nowrap; }
.transfer-detail__meta-grid dd { margin: 0; font-weight: 500; overflow-wrap: anywhere; }

.transfer-detail__version-dd,
.transfer-detail__runtime-dd {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.transfer-detail__version-sep {
  color: var(--am-text-muted);
}

.transfer-version-chip {
  white-space: nowrap;
}

.transfer-detail__contents {
  margin: 0;
  padding: 0;
  list-style: none;
  border: 1px solid var(--am-border);
  border-radius: 8px;
}

.transfer-detail__contents li {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--am-border);
}

.transfer-detail__contents li:last-child { border-bottom: 0; }
.transfer-detail__contents li > div { display: grid; gap: 2px; font-size: 13px; }
.transfer-detail__contents span { font-size: 12px; color: var(--am-text-muted); }

.transfer-detail__snapshot-note {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 9px 12px;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  background: var(--am-surface-muted);
  font-size: 12px;
  color: var(--am-text-muted);
}

.transfer-detail__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.transfer-detail__footer-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

@media (max-width: 640px) {
  .transfer-detail__meta-grid { grid-template-columns: 1fr; }
}
</style>
