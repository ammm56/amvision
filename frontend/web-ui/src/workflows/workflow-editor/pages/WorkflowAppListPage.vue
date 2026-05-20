<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">{{ t('workflowEditor.applications.kicker') }}</p>
        <h1>{{ t('workflowEditor.applications.title') }}</h1>
        <p class="page-description">{{ t('workflowEditor.applications.description') }}</p>
      </div>
      <div class="page-actions">
        <RouterLink v-if="canWriteWorkflows" to="/workflows/graph/new" class="ui-button ui-button--primary ui-button--md">
          <Plus :size="16" />
          {{ t('workflowEditor.actions.newWorkflowGraph') }}
        </RouterLink>
        <Button variant="secondary" :disabled="loading" @click="loadPage">
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
          <strong>{{ workflowApps.length }}</strong>
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
                <strong>{{ workflowApp.application.display_name || workflowApp.application.application_id }}</strong>
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
                <div class="table-actions table-actions--wrap">
                  <RouterLink :to="editorPath(workflowApp.application.application_id)">{{ t('workflowEditor.actions.openGraphEditor') }}</RouterLink>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Plus, RefreshCw } from '@lucide/vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { getWorkflowNodeCatalog } from '../services/node-catalog.service'
import { listWorkflowApps, type WorkflowAppSummary } from '../services/workflow-app.service'
import type { WorkflowAppRuntime, WorkflowNodeCatalogResponse } from '../types'

const { t } = useI18n()
const projectStore = useProjectStore()
const sessionStore = useSessionStore()

const loading = ref(false)
const errorMessage = ref<string | null>(null)
const nodeCatalog = ref<WorkflowNodeCatalogResponse | null>(null)
const workflowApps = ref<WorkflowAppSummary[]>([])
const appRuntimes = ref<WorkflowAppRuntime[]>([])

const selectedProjectId = computed(() => projectStore.selectedProjectId)
const canWriteWorkflows = computed(() => sessionStore.hasScopes(['workflows:write']))
const runningRuntimeCount = computed(() => appRuntimes.value.filter((runtime) => runtime.observed_state === 'running').length)

function runtimeTone(state: string): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  if (state === 'running') return 'success'
  if (state === 'failed') return 'danger'
  if (state === 'starting' || state === 'stopping') return 'warning'
  return 'neutral'
}

function editorPath(applicationId: string): string {
  return `/workflows/graph/apps/${encodeURIComponent(applicationId)}`
}

async function loadPage(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    const [catalogResponse, workflowAppResponse] = await Promise.all([
      getWorkflowNodeCatalog(),
      listWorkflowApps(selectedProjectId.value, { limit: 100 }),
    ])
    nodeCatalog.value = catalogResponse
    workflowApps.value = workflowAppResponse.items
    appRuntimes.value = workflowAppResponse.runtimes
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('workflowEditor.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

onMounted(loadPage)
</script>
