<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">{{ t('projects.kicker') }}</p>
        <h1>{{ t('projects.title') }}</h1>
      </div>
      <div class="page-actions">
        <Button variant="secondary" @click="projectStore.loadProjects()">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
        <Button v-if="canBootstrapProject" variant="primary" @click="projectStore.bootstrapDefaultProject()">
          <Plus :size="16" />
          {{ t('projects.initDefault') }}
        </Button>
      </div>
    </header>

    <InlineError :message="projectStore.error" />

    <EmptyState
      v-if="!projectStore.loading && projectStore.projects.length === 0"
      :title="t('projects.emptyTitle')"
      :description="t('projects.emptyDescription')"
    >
      <Button v-if="canBootstrapProject" variant="primary" @click="projectStore.bootstrapDefaultProject()">
        <Plus :size="16" />
        {{ t('projects.initDefault') }}
      </Button>
    </EmptyState>

    <div v-else class="resource-table">
      <table>
        <thead>
          <tr>
            <th>{{ t('projects.columns.project') }}</th>
            <th>{{ t('projects.columns.status') }}</th>
            <th>{{ t('projects.columns.datasets') }}</th>
            <th>{{ t('projects.columns.training') }}</th>
            <th>{{ t('projects.columns.deployments') }}</th>
            <th>{{ t('projects.columns.workflows') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="project in projectStore.projects"
            :key="project.project_id"
            :class="{ 'is-selected': project.project_id === projectStore.selectedProjectId }"
            @click="projectStore.selectProject(project.project_id)"
          >
            <td>
              <strong>{{ project.display_name || project.project_id }}</strong>
              <span>{{ project.project_id }}</span>
            </td>
            <td>
              <StatusBadge :tone="project.registered_in_catalog === false ? 'warning' : 'success'">
                {{ project.registered_in_catalog === false ? t('projects.status.unregistered') : t('projects.status.available') }}
              </StatusBadge>
            </td>
            <td>{{ formatCount(project.summary?.datasets?.dataset_total) }}</td>
            <td>{{ formatCount(project.summary?.training?.total) }}</td>
            <td>{{ formatCount(project.summary?.deployments?.deployment_instance_total) }}</td>
            <td>{{ formatCount(project.summary?.workflows?.template_total) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RefreshCw, Plus } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import Button from '@/shared/ui/components/Button.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'

const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const { t } = useI18n()

const canBootstrapProject = computed(() =>
  sessionStore.hasScopes(['datasets:write']) || sessionStore.hasScopes(['workflows:write']),
)

onMounted(() => {
  if (projectStore.projects.length === 0) {
    void projectStore.loadProjects()
  }
})

function formatCount(value: unknown): string {
  return typeof value === 'number' ? String(value) : '0'
}
</script>