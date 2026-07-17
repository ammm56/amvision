<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">{{ t('workflowEditor.applications.kicker') }}</p>
        <h1>{{ t('workflowEditor.applications.title') }}</h1>
        <p class="page-description">{{ t('workflowEditor.applications.description') }}</p>
      </div>
      <div class="page-actions">
        <Button v-if="canWriteWorkflows" variant="primary" @click="openNewGraph">
          <Plus :size="16" />
          {{ t('workflowEditor.actions.newWorkflowGraph') }}
        </Button>
        <Button variant="secondary" :disabled="loading" @click="refreshPage">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </div>
    </header>

    <InlineError :message="errorMessage" />

    <section class="resource-section">
      <div>
        <p class="page-kicker">{{ t('workflowEditor.runtime.kicker') }}</p>
        <h2>{{ t('workflowEditor.runtime.title') }}</h2>
      </div>
      <div class="summary-grid">
        <div>
          <span>{{ t('workflowEditor.fields.applications') }}</span>
          <strong>{{ applicationCount }}</strong>
        </div>
        <div>
          <span>{{ t('workflowEditor.fields.appRuntimes') }}</span>
          <strong>{{ appRuntimes.length }}</strong>
        </div>
        <div>
          <span>{{ t('workflowEditor.fields.runningRuntimes') }}</span>
          <strong>{{ runningRuntimeCount }}</strong>
        </div>
        <div>
          <span>{{ t('workflowEditor.fields.nodeDefinitions') }}</span>
          <strong>{{ nodeCatalog?.node_definitions.length ?? 0 }}</strong>
        </div>
      </div>
    </section>

    <section class="resource-section">
      <div>
        <p class="page-kicker">{{ t('workflowEditor.applications.listKicker') }}</p>
        <h2>{{ t('workflowEditor.applications.listTitle') }}</h2>
      </div>
      <EmptyState v-if="!loading && workflowApps.length === 0" :title="t('workflowEditor.applications.emptyTitle')" :description="t('workflowEditor.applications.emptyDescription')" />
      <div v-else class="resource-table">
        <table>
          <thead>
            <tr>
              <th>{{ t('workflowEditor.columns.application') }}</th>
              <th>{{ t('workflowEditor.columns.bindings') }}</th>
              <th>{{ t('workflowEditor.columns.runtime') }}</th>
              <th>{{ t('workflowEditor.columns.updatedAt') }}</th>
              <th>{{ t('workflowEditor.columns.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="workflowApp in workflowApps" :key="workflowApp.application.application_id">
              <td>
                <RouterLink :to="detailPath(workflowApp.application.application_id)">
                  <strong>{{ workflowApp.application.display_name || workflowApp.application.application_id }}</strong>
                </RouterLink>
                <span>{{ workflowApp.application.application_id }}</span>
              </td>
              <td>{{ workflowApp.application.binding_count }}</td>
              <td>
                <StatusBadge v-if="workflowApp.primaryRuntime" :tone="runtimeTone(workflowApp.primaryRuntime.observed_state)">
                  {{ workflowApp.primaryRuntime.observed_state }}
                </StatusBadge>
                <span v-else>{{ t('common.none') }}</span>
              </td>
              <td>{{ formatSystemDateTime(workflowApp.application.updated_at) }}</td>
              <td>
                <div class="table-actions table-actions--wrap workflow-app-list__actions">
                  <Button
                    size="sm"
                    variant="secondary"
                    title="详情"
                    aria-label="详情"
                    @click="openDetail(workflowApp.application.application_id)"
                  >
                    <SquarePen :size="14" />
                    <span>详情</span>
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    :title="t('workflowEditor.actions.openGraphEditor')"
                    :aria-label="t('workflowEditor.actions.openGraphEditor')"
                    @click="openGraphEditor(workflowApp.application.application_id)"
                  >
                    <Workflow :size="14" />
                    <span>{{ t('workflowEditor.actions.openGraphEditor') }}</span>
                  </Button>
                  <Button
                    v-if="canWriteWorkflows"
                    size="sm"
                    variant="danger"
                    :disabled="deletingApplicationId === workflowApp.application.application_id || workflowApp.runtimes.length > 0"
                    :title="workflowApp.runtimes.length > 0 ? '先删除运行记录后再删除应用' : '删除应用；未被其他应用使用的图版本会一并删除'"
                    @click="deleteWorkflowApp(workflowApp)"
                  >
                    <Trash2 :size="14" />
                    删除
                  </Button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <PaginationControls
        v-if="workflowApps.length > 0"
        class="workflow-app-list__pagination"
        :offset="applicationPagination.offset"
        :limit="applicationPagination.limit"
        :item-count="workflowApps.length"
        :total-count="applicationPagination.totalCount"
        :has-more="applicationPagination.hasMore"
        :disabled="loading"
        @previous="loadPreviousPage"
        @next="loadNextPage"
      />
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Plus, RefreshCw, SquarePen, Trash2, Workflow } from '@lucide/vue'
import { RouterLink, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import type { PaginationMeta } from '@/shared/api/pagination'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { getWorkflowNodeCatalog } from '../services/node-catalog.service'
import { deleteWorkflowApplication } from '../services/workflow-application.service'
import { deleteWorkflowTemplateVersion } from '../services/workflow-template.service'
import { listWorkflowApps, type WorkflowAppSummary } from '../services/workflow-app.service'
import { refreshWorkflowAppRuntimeStatuses } from '../services/workflow-runtime.service'
import type { WorkflowAppRuntime, WorkflowNodeCatalogResponse } from '../types'

const { t } = useI18n()
const router = useRouter()
const projectStore = useProjectStore()
const sessionStore = useSessionStore()

const loading = ref(false)
const errorMessage = ref<string | null>(null)
const nodeCatalog = ref<WorkflowNodeCatalogResponse | null>(null)
const workflowApps = ref<WorkflowAppSummary[]>([])
const appRuntimes = ref<WorkflowAppRuntime[]>([])
const deletingApplicationId = ref<string | null>(null)
const applicationPagination = ref<PaginationMeta>(createPaginationState())

const selectedProjectId = computed(() => projectStore.selectedProjectId)
const canWriteWorkflows = computed(() => sessionStore.hasScopes(['workflows:write']))
const runningRuntimeCount = computed(() => appRuntimes.value.filter((runtime) => runtime.observed_state === 'running').length)
const applicationCount = computed(() => applicationPagination.value.totalCount ?? workflowApps.value.length)

function runtimeTone(state: string): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  if (state === 'running') return 'success'
  if (state === 'failed') return 'danger'
  if (state === 'starting' || state === 'stopping') return 'warning'
  return 'neutral'
}

function editorPath(applicationId: string): string {
  return `/workflows/graph/apps/${encodeURIComponent(applicationId)}`
}

function detailPath(applicationId: string): string {
  return `/workflows/apps/${encodeURIComponent(applicationId)}`
}

function openNewGraph(): void {
  void router.push('/workflows/graph/new')
}

function openDetail(applicationId: string): void {
  void router.push(detailPath(applicationId))
}

function openGraphEditor(applicationId: string): void {
  void router.push(editorPath(applicationId))
}

function refreshPage(): void {
  void loadPage()
}

async function loadPage(offset?: number): Promise<void> {
  if (!selectedProjectId.value) {
    workflowApps.value = []
    appRuntimes.value = []
    applicationPagination.value = createPaginationState()
    return
  }
  loading.value = true
  errorMessage.value = null
  const pageOffset = Number.isFinite(offset) ? Math.max(0, offset as number) : applicationPagination.value.offset
  try {
    const [catalogResponse, workflowAppResponse] = await Promise.all([
      getWorkflowNodeCatalog(),
      listWorkflowApps(selectedProjectId.value, { offset: pageOffset, limit: applicationPagination.value.limit }),
    ])
    const runtimeStatusResult = await refreshWorkflowAppRuntimeStatuses(workflowAppResponse.runtimes)
    const runtimeById = new Map(runtimeStatusResult.items.map((runtime) => [runtime.workflow_runtime_id, runtime]))
    nodeCatalog.value = catalogResponse
    workflowApps.value = workflowAppResponse.items.map((workflowApp) => {
      const runtimes = workflowApp.runtimes.map((runtime) => runtimeById.get(runtime.workflow_runtime_id) ?? runtime)
      return {
        ...workflowApp,
        runtimes,
        primaryRuntime: runtimes.find((runtime) => runtime.observed_state === 'running') ?? runtimes[0] ?? null,
      }
    })
    appRuntimes.value = runtimeStatusResult.items
    applicationPagination.value = workflowAppResponse.pagination
    if (runtimeStatusResult.failedRuntimeIds.length > 0) {
      errorMessage.value = `部分 runtime 状态刷新失败，已标记为 unknown：${runtimeStatusResult.failedRuntimeIds.join(', ')}`
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('workflowEditor.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

async function deleteWorkflowApp(workflowApp: WorkflowAppSummary): Promise<void> {
  if (!canWriteWorkflows.value || workflowApp.runtimes.length > 0) return
  const applicationId = workflowApp.application.application_id
  const shouldDeleteGraph = isGraphVersionOnlyUsedByApplication(workflowApp)
  const confirmed = window.confirm(shouldDeleteGraph ? `删除应用 ${applicationId}，并删除未被其他应用使用的图版本？` : `删除应用 ${applicationId}？`)
  if (!confirmed) return
  deletingApplicationId.value = applicationId
  errorMessage.value = null
  try {
    await deleteWorkflowApplication(selectedProjectId.value, applicationId)
    if (shouldDeleteGraph) {
      await deleteWorkflowTemplateVersion(
        selectedProjectId.value,
        workflowApp.application.template_id,
        workflowApp.application.template_version,
      )
    }
    const nextOffset = workflowApps.value.length === 1
      ? Math.max(0, applicationPagination.value.offset - applicationPagination.value.limit)
      : applicationPagination.value.offset
    await loadPage(nextOffset)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '删除应用失败'
  } finally {
    deletingApplicationId.value = null
  }
}

function isGraphVersionOnlyUsedByApplication(workflowApp: WorkflowAppSummary): boolean {
  return workflowApps.value.every((item) => {
    if (item.application.application_id === workflowApp.application.application_id) return true
    return item.application.template_id !== workflowApp.application.template_id || item.application.template_version !== workflowApp.application.template_version
  })
}

function loadPreviousPage(): void {
  void loadPage(Math.max(0, applicationPagination.value.offset - applicationPagination.value.limit))
}

function loadNextPage(): void {
  if (!applicationPagination.value.hasMore) return
  void loadPage(applicationPagination.value.nextOffset ?? applicationPagination.value.offset + applicationPagination.value.limit)
}

function createPaginationState(): PaginationMeta {
  return {
    offset: 0,
    limit: 50,
    totalCount: 0,
    hasMore: false,
    nextOffset: null,
  }
}

watch(
  () => selectedProjectId.value,
  () => {
    applicationPagination.value = createPaginationState()
    void loadPage(0)
  },
  { immediate: true },
)
</script>

<style scoped>
.workflow-app-list__actions {
  align-items: center;
  gap: 6px;
}

.workflow-app-list__pagination {
  margin-top: 16px;
}
</style>
