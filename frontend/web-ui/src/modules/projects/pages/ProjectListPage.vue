<template>
  <section class="page-stack">
    <PageHeader>
      <template #heading>
        <div class="project-page-heading">
          <h1>{{ t('common.project') }}</h1>
          <ProjectSwitcher />
        </div>
      </template>
      <template #actions>
        <Button
          :disabled="generatingSdkConfigPackage || !projectStore.selectedProjectId"
          :loading="generatingSdkConfigPackage"
          variant="secondary"
          @click="generateSdkConfigPackage"
        >
          <PackageCheck :size="16" />
          {{ t('projects.generateSdkConfigPackage') }}
        </Button>
        <Button variant="secondary" :loading="projectStore.loading" @click="loadProjectsWithSummary">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
        <Button v-if="canBootstrapProject" variant="primary" @click="showCreateProject = !showCreateProject">
          <Plus :size="16" />
          {{ t('projects.createProject') }}
        </Button>
        <Button
          v-if="canBootstrapProject && !defaultProjectExists"
          variant="secondary"
          :disabled="bootstrappingDefaultProject"
          :loading="bootstrappingDefaultProject"
          @click="bootstrapDefaultProject"
        >
          <Plus :size="16" />
          {{ t('projects.initDefault') }}
        </Button>
      </template>
    </PageHeader>

    <InlineError :message="projectStore.error" />
    <InlineError :message="formError" />
    <section v-if="sdkConfigPackagePreview" class="resource-section sdk-config-preview-panel">
      <div>
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
        <h2>{{ t('projects.createTitle') }}</h2>
      </div>
      <div class="form-grid">
        <label class="field">
          <span>{{ t('projects.fields.projectId') }}</span>
          <input v-model.trim="projectForm.projectId" autocomplete="off" placeholder="project-x" />
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
        <Button variant="primary" :disabled="creatingProject" :loading="creatingProject" @click="createProject">
          <Plus :size="16" />
          {{ t('projects.createProject') }}
        </Button>
      </div>
    </section>

    <EmptyState
      v-if="projectStore.projects.length === 0"
      :title="t('projects.emptyTitle')"
      :description="t('projects.emptyDescription')"
    >
      <Button
        v-if="canBootstrapProject && !defaultProjectExists"
        variant="primary"
        :disabled="bootstrappingDefaultProject"
        :loading="bootstrappingDefaultProject"
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
            <th>{{ t('projects.columns.source') }}</th>
            <th>{{ t('projects.columns.datasets') }}</th>
            <th>{{ t('projects.columns.training') }}</th>
            <th>{{ t('projects.columns.deployments') }}</th>
            <th>{{ t('projects.columns.workflows') }}</th>
            <th v-if="canDeleteProject" class="project-table__actions-column">{{ t('projects.columns.actions') }}</th>
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
              <strong>{{ readProjectDisplayName(project) }}</strong>
              <span>{{ project.project_id }}</span>
            </td>
            <td>{{ project.project_source === 'local_disk' ? t('projects.sources.localDisk') : t('projects.sources.configured') }}</td>
            <td>{{ formatCount(project.summary?.datasets?.dataset_total) }}</td>
            <td>{{ formatCount(project.summary?.training?.total) }}</td>
            <td>{{ formatCount(project.summary?.deployments?.deployment_instance_total) }}</td>
            <td>{{ formatCount(project.summary?.workflows?.template_total) }}</td>
            <td v-if="canDeleteProject" class="project-table__actions-column">
              <Button
                v-if="!isProjectProtected(project)"
                variant="danger"
                size="sm"
                :disabled="deletionPreviewLoading"
                :loading="deletionPreviewLoading && pendingDeletionProjectId === project.project_id"
                :title="t('projects.deletion.action')"
                @click.stop="requestProjectDeletion(project)"
              >
                <Trash2 :size="15" />
                {{ t('projects.deletion.action') }}
              </Button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <ConfirmDialog
      v-if="deletionPreview"
      :title="t('projects.deletion.title')"
      :message="t('projects.deletion.message', { projectId: deletionPreview.project_id })"
      :details="t('projects.deletion.details')"
      :confirm-label="t('projects.deletion.confirm')"
      :cancel-label="t('common.cancel')"
      :busy="deletingProject"
      :confirm-disabled="!deletionPreview.can_delete || deletionConfirmation !== deletionPreview.project_id"
      @cancel="closeDeletionDialog"
      @confirm="confirmProjectDeletion"
    >
      <div v-if="deletionPreview.blockers.length > 0" class="project-deletion-blockers">
        <strong>{{ t('projects.deletion.blockers') }}</strong>
        <ul>
          <li v-for="blocker in deletionPreview.blockers" :key="`${blocker.resource_kind}:${blocker.resource_id}`">
            {{ formatDeletionBlockerKind(blocker.resource_kind) }} · {{ blocker.resource_id }} · {{ blocker.state }}
          </li>
        </ul>
      </div>
      <dl v-if="deletionResourceEntries.length > 0" class="project-deletion-counts">
        <div v-for="[name, count] in deletionResourceEntries" :key="name">
          <dt>{{ formatDeletionResourceName(name) }}</dt>
          <dd>{{ count }}</dd>
        </div>
      </dl>
      <label class="field">
        <span>{{ t('projects.deletion.confirmationLabel') }}</span>
        <input
          v-model="deletionConfirmation"
          autocomplete="off"
          :disabled="deletingProject || !deletionPreview.can_delete"
          :placeholder="deletionPreview.project_id"
        />
      </label>
    </ConfirmDialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { RefreshCw, Plus, PackageCheck, Trash2 } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { useFeedbackStore } from '@/app/stores/feedback.store'
import { getRuntimeConfig } from '@/platform/runtime/runtime-config'
import type { ProjectCatalogItem } from '@/shared/contracts'
import {
  deleteProject as deleteProjectRequest,
  downloadSdkConfigPackage,
  previewProjectDeletion,
  previewSdkConfigPackage,
  type ProjectDeletionPreview,
  type SdkConfigPackageGenerateInput,
  type SdkConfigPackagePreview,
} from '@/modules/projects/services/project.service'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import PageHeader from '@/shared/ui/layout/PageHeader.vue'
import ProjectSwitcher from '@/modules/projects/components/ProjectSwitcher.vue'

const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const feedbackStore = useFeedbackStore()
const { t } = useI18n()

const showCreateProject = ref(false)
const creatingProject = ref(false)
const bootstrappingDefaultProject = ref(false)
const generatingSdkConfigPackage = ref(false)
const sdkConfigPackagePreview = ref<SdkConfigPackagePreview | null>(null)
const formError = ref<string | null>(null)
const deletionPreview = ref<ProjectDeletionPreview | null>(null)
const pendingDeletionProjectId = ref<string | null>(null)
const deletionConfirmation = ref('')
const deletionPreviewLoading = ref(false)
const deletingProject = ref(false)
const projectForm = reactive({ projectId: '', displayName: '', description: '' })
const defaultProjectId = getRuntimeConfig().defaultProjectId

const canBootstrapProject = computed(() =>
  sessionStore.hasScopes(['datasets:write']) || sessionStore.hasScopes(['workflows:write']),
)
const canDeleteProject = computed(() => sessionStore.hasScopes(['projects:delete']))
const defaultProjectExists = computed(() =>
  projectStore.projects.some((project) => project.project_id === defaultProjectId),
)
const deletionResourceEntries = computed(() => Object.entries(deletionPreview.value?.resource_counts ?? {})
  .filter(([, count]) => count > 0)
  .sort(([left], [right]) => left.localeCompare(right)))
const deletionResourceLabelKeys: Record<string, string> = {
  authorization_assignments: 'projects.deletion.resources.authorizationAssignments',
  dataset_exports: 'projects.deletion.resources.datasetExports',
  dataset_imports: 'projects.deletion.resources.datasetImports',
  dataset_versions: 'projects.deletion.resources.datasetVersions',
  deployments: 'projects.deletion.resources.deployments',
  model_files: 'projects.deletion.resources.modelFiles',
  models: 'projects.deletion.resources.models',
  queue_messages: 'projects.deletion.resources.queueMessages',
  tasks: 'projects.deletion.resources.tasks',
  validation_sessions: 'projects.deletion.resources.validationSessions',
  workflow_app_runtimes: 'projects.deletion.resources.workflowAppRuntimes',
  workflow_documents: 'projects.deletion.resources.workflowDocuments',
  workflow_execution_policies: 'projects.deletion.resources.workflowExecutionPolicies',
  workflow_preview_runs: 'projects.deletion.resources.workflowPreviewRuns',
  workflow_runs: 'projects.deletion.resources.workflowRuns',
  workflow_trigger_sources: 'projects.deletion.resources.workflowTriggerSources',
}
const deletionBlockerResourceNames: Record<string, string> = {
  deployment: 'deployments',
  queue_message: 'queue_messages',
  task: 'tasks',
  trigger_source: 'workflow_trigger_sources',
  workflow_preview: 'workflow_preview_runs',
  workflow_run: 'workflow_runs',
  workflow_runtime: 'workflow_app_runtimes',
}

function readProjectDisplayName(project: ProjectCatalogItem): string {
  const displayName = project.display_name || project.project_id
  if (
    project.project_id === defaultProjectId
    && ['默认项目', 'Default Project', '既定プロジェクト', '기본 프로젝트'].includes(displayName)
  ) {
    return t('projects.defaultDisplayName')
  }
  return displayName
}

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

function formatDeletionResourceName(resourceName: string): string {
  const translationKey = deletionResourceLabelKeys[resourceName]
  return translationKey ? t(translationKey) : resourceName
}

function formatDeletionBlockerKind(resourceKind: string): string {
  return formatDeletionResourceName(deletionBlockerResourceNames[resourceKind] ?? resourceKind)
}

function isProjectProtected(project: ProjectCatalogItem): boolean {
  return project.project_source !== 'local_disk' || project.project_id === defaultProjectId
}

async function requestProjectDeletion(project: ProjectCatalogItem): Promise<void> {
  if (isProjectProtected(project) || deletionPreviewLoading.value) return
  formError.value = null
  pendingDeletionProjectId.value = project.project_id
  deletionPreviewLoading.value = true
  try {
    deletionPreview.value = await previewProjectDeletion(project.project_id)
    deletionConfirmation.value = ''
  } catch (error) {
    formError.value = error instanceof Error ? error.message : t('projects.deletion.previewFailed')
  } finally {
    deletionPreviewLoading.value = false
    pendingDeletionProjectId.value = null
  }
}

function closeDeletionDialog(): void {
  if (deletingProject.value) return
  deletionPreview.value = null
  deletionConfirmation.value = ''
}

async function confirmProjectDeletion(): Promise<void> {
  const preview = deletionPreview.value
  if (!preview || !preview.can_delete || deletionConfirmation.value !== preview.project_id) return
  deletingProject.value = true
  formError.value = null
  try {
    await deleteProjectRequest(preview.project_id, deletionConfirmation.value)
    await projectStore.refreshAfterDeletion(preview.project_id)
    feedbackStore.success(t('projects.deletion.deletedTitle'), { message: preview.project_id })
    deletionPreview.value = null
    deletionConfirmation.value = ''
  } catch (error) {
    formError.value = error instanceof Error ? error.message : t('projects.deletion.deleteFailed')
  } finally {
    deletingProject.value = false
  }
}

async function createProject(): Promise<void> {
  formError.value = null
  if (!projectForm.projectId) {
    formError.value = t('projects.messages.projectIdRequired')
    return
  }
  const projectId = projectForm.projectId
  creatingProject.value = true
  try {
    await projectStore.createProject({
      project_id: projectForm.projectId,
      display_name: projectForm.displayName || undefined,
      description: projectForm.description || undefined,
    })
    feedbackStore.success(t('projects.messages.created'), { message: projectId })
    resetProjectForm()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : t('projects.messages.createFailed')
  } finally {
    creatingProject.value = false
  }
}

async function bootstrapDefaultProject(): Promise<void> {
  formError.value = null
  bootstrappingDefaultProject.value = true
  try {
    await projectStore.bootstrapDefaultProject()
    feedbackStore.success(t('projects.messages.created'), { message: defaultProjectId })
  } catch (error) {
    formError.value = error instanceof Error ? error.message : t('projects.messages.createFailed')
  } finally {
    bootstrappingDefaultProject.value = false
  }
}

async function generateSdkConfigPackage(): Promise<void> {
  formError.value = null
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
    feedbackStore.success(t('projects.messages.sdkConfigPackageDownloaded'), { message: projectId })
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
.project-page-heading {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.sdk-config-preview-panel {
  gap: 16px;
}

.sdk-config-preview-panel__warnings {
  margin: 0;
  padding-left: 18px;
  color: var(--am-warning-text);
}

.project-table__actions-column {
  text-align: right;
  white-space: nowrap;
}

.project-deletion-blockers ul {
  margin: 8px 0 0;
  padding-left: 20px;
  color: var(--am-danger-text);
}

.project-deletion-counts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 14px;
  margin: 0;
}

.project-deletion-counts div {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}

.project-deletion-counts dt,
.project-deletion-counts dd {
  margin: 0;
}
</style>
