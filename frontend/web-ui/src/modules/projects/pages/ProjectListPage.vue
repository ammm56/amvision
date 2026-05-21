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
        <Button v-if="canBootstrapProject" variant="primary" @click="showCreateProject = !showCreateProject">
          <Plus :size="16" />
          {{ t('projects.createProject') }}
        </Button>
        <Button
          v-if="canBootstrapProject && !defaultProjectExists"
          variant="primary"
          :disabled="bootstrappingDefaultProject"
          @click="bootstrapDefaultProject"
        >
          <Plus :size="16" />
          {{ t('projects.initDefault') }}
        </Button>
      </div>
    </header>

    <InlineError :message="projectStore.error" />
    <InlineError :message="formError" />
    <p v-if="statusMessage" class="result-note">{{ statusMessage }}</p>

    <section v-if="showCreateProject" class="resource-section">
      <div>
        <p class="page-kicker">{{ t('projects.createKicker') }}</p>
        <h2>{{ t('projects.createTitle') }}</h2>
      </div>
      <div class="form-grid">
        <label class="field">
          <span>{{ t('projects.fields.projectId') }}</span>
          <input v-model.trim="projectForm.projectId" autocomplete="off" placeholder="inspection-line-1" />
        </label>
        <label class="field">
          <span>{{ t('projects.fields.displayName') }}</span>
          <input v-model.trim="projectForm.displayName" autocomplete="off" />
        </label>
        <label class="field field--wide">
          <span>{{ t('projects.fields.description') }}</span>
          <textarea v-model.trim="projectForm.description" rows="3" />
        </label>
      </div>
      <div class="page-actions">
        <Button variant="secondary" @click="resetProjectForm">{{ t('common.cancel') }}</Button>
        <Button variant="primary" :disabled="creatingProject" @click="createProject">
          <Plus :size="16" />
          {{ t('projects.createProject') }}
        </Button>
      </div>
    </section>

    <EmptyState
      v-if="!projectStore.loading && projectStore.projects.length === 0"
      :title="t('projects.emptyTitle')"
      :description="t('projects.emptyDescription')"
    >
      <Button
        v-if="canBootstrapProject && !defaultProjectExists"
        variant="primary"
        :disabled="bootstrappingDefaultProject"
        @click="bootstrapDefaultProject"
      >
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
              <StatusPill
                :status="project.registered_in_catalog === false ? 'unregistered' : 'available'"
                :label="project.registered_in_catalog === false ? t('projects.status.unregistered') : t('projects.status.available')"
              />
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
import { computed, onMounted, reactive, ref } from 'vue'
import { RefreshCw, Plus } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { getRuntimeConfig } from '@/platform/runtime/runtime-config'
import Button from '@/shared/ui/components/Button.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import StatusPill from '@/shared/ui/data-display/StatusPill.vue'

const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const { t } = useI18n()

const showCreateProject = ref(false)
const creatingProject = ref(false)
const bootstrappingDefaultProject = ref(false)
const formError = ref<string | null>(null)
const statusMessage = ref<string | null>(null)
const projectForm = reactive({ projectId: '', displayName: '', description: '' })
const defaultProjectId = getRuntimeConfig().defaultProjectId

const canBootstrapProject = computed(() =>
  sessionStore.hasScopes(['datasets:write']) || sessionStore.hasScopes(['workflows:write']),
)
const defaultProjectExists = computed(() =>
  projectStore.projects.some((project) => project.project_id === defaultProjectId),
)

onMounted(() => {
  if (projectStore.projects.length === 0) {
    void projectStore.loadProjects()
  }
})

function formatCount(value: unknown): string {
  return typeof value === 'number' ? String(value) : '0'
}

async function createProject(): Promise<void> {
  formError.value = null
  statusMessage.value = null
  if (!projectForm.projectId) {
    formError.value = t('projects.messages.projectIdRequired')
    return
  }
  creatingProject.value = true
  try {
    await projectStore.createProject({
      project_id: projectForm.projectId,
      display_name: projectForm.displayName || undefined,
      description: projectForm.description || undefined,
    })
    statusMessage.value = t('projects.messages.created')
    resetProjectForm()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : t('projects.messages.createFailed')
  } finally {
    creatingProject.value = false
  }
}

async function bootstrapDefaultProject(): Promise<void> {
  formError.value = null
  statusMessage.value = null
  bootstrappingDefaultProject.value = true
  try {
    await projectStore.bootstrapDefaultProject()
    statusMessage.value = t('projects.messages.created')
  } catch (error) {
    formError.value = error instanceof Error ? error.message : t('projects.messages.createFailed')
  } finally {
    bootstrappingDefaultProject.value = false
  }
}

function resetProjectForm(): void {
  projectForm.projectId = ''
  projectForm.displayName = ''
  projectForm.description = ''
  showCreateProject.value = false
}
</script>
