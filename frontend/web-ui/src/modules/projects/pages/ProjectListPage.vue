<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">{{ t('projects.kicker') }}</p>
        <h1>{{ t('projects.title') }}</h1>
      </div>
      <div class="page-actions">
        <Button :disabled="generatingSdkConfigPackage || !projectStore.selectedProjectId" variant="secondary" @click="generateSdkConfigPackage">
          <PackageCheck :size="16" />
          {{ t('projects.generateSdkConfigPackage') }}
        </Button>
        <Button variant="secondary" @click="loadProjectsWithSummary">
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
    <section v-if="sdkConfigPackagePreview" class="resource-section sdk-config-preview-panel">
      <div>
        <p class="page-kicker">{{ t('projects.sdkConfigPackage.kicker') }}</p>
        <h2>{{ t('projects.sdkConfigPackage.title') }}</h2>
      </div>
      <div class="summary-grid">
        <div>
          <span>{{ t('projects.sdkConfigPackage.workflowRuntimeCount') }}</span>
          <strong>{{ sdkConfigPackagePreview.workflow_runtime_count }}</strong>
        </div>
        <div>
          <span>{{ t('projects.sdkConfigPackage.triggerSourceCount') }}</span>
          <strong>{{ sdkConfigPackagePreview.trigger_source_count }}</strong>
        </div>
        <div>
          <span>{{ t('projects.sdkConfigPackage.modelDeploymentCount') }}</span>
          <strong>{{ sdkConfigPackagePreview.model_deployment_count }}</strong>
        </div>
        <div>
          <span>{{ t('projects.sdkConfigPackage.fileCount') }}</span>
          <strong>{{ sdkConfigPackagePreview.files.length }}</strong>
        </div>
      </div>
      <ul v-if="sdkConfigPackagePreview.warnings.length > 0" class="sdk-config-preview-panel__warnings">
        <li v-for="warning in sdkConfigPackagePreview.warnings" :key="warning">{{ warning }}</li>
      </ul>
    </section>

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
            <th>
              <span class="heading-with-hint">
                {{ t('projects.columns.source') }}
                <InfoHint :text="t('projects.sourceHint')" />
              </span>
            </th>
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
                :status="project.project_source === 'local_disk' ? 'local_disk' : 'configured'"
                :label="project.project_source === 'local_disk' ? t('projects.sources.localDisk') : t('projects.sources.configured')"
                :tone="project.project_source === 'local_disk' ? 'info' : 'success'"
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
import { RefreshCw, Plus, PackageCheck } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { getRuntimeConfig } from '@/platform/runtime/runtime-config'
import {
  downloadSdkConfigPackage,
  previewSdkConfigPackage,
  type SdkConfigPackageGenerateInput,
  type SdkConfigPackagePreview,
} from '@/modules/projects/services/project.service'
import Button from '@/shared/ui/components/Button.vue'
import InfoHint from '@/shared/ui/components/InfoHint.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import StatusPill from '@/shared/ui/data-display/StatusPill.vue'

const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const { t } = useI18n()

const showCreateProject = ref(false)
const creatingProject = ref(false)
const bootstrappingDefaultProject = ref(false)
const generatingSdkConfigPackage = ref(false)
const sdkConfigPackagePreview = ref<SdkConfigPackagePreview | null>(null)
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
  if (projectStore.projects.length === 0 || projectStore.projects.some((project) => !project.summary)) {
    void loadProjectsWithSummary()
  }
})

async function loadProjectsWithSummary(): Promise<void> {
  await projectStore.loadProjects({ includeSummary: true })
}

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

async function generateSdkConfigPackage(): Promise<void> {
  formError.value = null
  statusMessage.value = null
  sdkConfigPackagePreview.value = null
  const projectId = projectStore.selectedProjectId
  if (!projectId) {
    formError.value = t('projects.messages.selectProjectRequired')
    return
  }
  const input: SdkConfigPackageGenerateInput = {
    include_access_token: true,
    model_runtime_modes: ['sync'],
    include_disabled_trigger_sources: true,
  }
  generatingSdkConfigPackage.value = true
  try {
    const preview = await previewSdkConfigPackage(projectId, input)
    sdkConfigPackagePreview.value = preview
    if (preview.files.length === 0) {
      formError.value = preview.warnings[0] ?? t('projects.messages.sdkConfigPackageEmpty')
      return
    }
    const download = await downloadSdkConfigPackage(projectId, input)
    const objectUrl = window.URL.createObjectURL(download.blob)
    const anchor = document.createElement('a')
    anchor.href = objectUrl
    anchor.download = download.fileName ?? preview.package_name
    anchor.click()
    window.URL.revokeObjectURL(objectUrl)
    statusMessage.value = t('projects.messages.sdkConfigPackageDownloaded')
  } catch (error) {
    formError.value = error instanceof Error ? error.message : t('projects.messages.sdkConfigPackageFailed')
  } finally {
    generatingSdkConfigPackage.value = false
  }
}

function resetProjectForm(): void {
  projectForm.projectId = ''
  projectForm.displayName = ''
  projectForm.description = ''
  showCreateProject.value = false
}
</script>

<style scoped>
.sdk-config-preview-panel {
  gap: 16px;
}

.sdk-config-preview-panel__warnings {
  margin: 0;
  padding-left: 18px;
  color: var(--color-warning-text, #8a5a00);
}
</style>
