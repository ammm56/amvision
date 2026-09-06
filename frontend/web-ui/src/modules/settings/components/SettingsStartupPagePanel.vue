<template>
  <section class="settings-panel settings-startup-page-panel">
    <header class="settings-panel__heading">
      <h2>{{ t('startupPage.title') }}</h2>
    </header>

    <div class="settings-preference-list settings-startup-page-form">
      <div class="settings-preference-row">
        <strong>{{ t('startupPage.openMode') }}</strong>
        <div class="settings-segmented-control" :aria-label="t('startupPage.openMode')">
          <button type="button" :class="{ 'is-active': draftMode === 'projects' }" @click="setMode('projects')">
            {{ t('startupPage.projects') }}
          </button>
          <button
            type="button"
            :class="{ 'is-active': draftMode === 'workflow-runtime-app-mode' }"
            @click="setMode('workflow-runtime-app-mode')"
          >
            {{ t('startupPage.appMode') }}
          </button>
        </div>
      </div>

      <template v-if="draftMode === 'workflow-runtime-app-mode'">
        <div class="settings-preference-row">
          <strong>{{ t('startupPage.project') }}</strong>
          <SelectField
            :model-value="selectedProjectId"
            :options="projectOptions"
            :disabled="loadingProjects || saving"
            @update:model-value="selectProject"
          />
        </div>
        <div class="settings-preference-row settings-startup-page-runtime-row">
          <strong>{{ t('startupPage.runtime') }}</strong>
          <div class="settings-startup-page-runtime-field">
            <SelectField
              :model-value="selectedRuntimeId"
              :options="runtimeOptions"
              :placeholder="runtimePlaceholder"
              :disabled="!selectedProjectId || loadingRuntimes || saving"
              @update:model-value="selectRuntime"
            />
            <StatusBadge
              v-if="validatedRuntime"
              :status="validatedRuntime.observed_state"
              :label="runtimeStateLabel(validatedRuntime.observed_state)"
              with-dot
            />
            <span v-else-if="showEmptyRuntimes" class="settings-startup-page-empty">
              {{ t('startupPage.noRuntimes') }}
            </span>
          </div>
        </div>
      </template>
    </div>

    <InlineError :message="errorMessage" />

    <footer class="settings-panel__actions settings-startup-page-actions">
      <Button variant="secondary" :disabled="saving || !canRestoreDefault" @click="restoreDefault">
        {{ t('startupPage.restoreDefault') }}
      </Button>
      <Button variant="primary" :loading="saving" :disabled="!canSave" @click="save">
        {{ t('startupPage.save') }}
      </Button>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { useFeedbackStore } from '@/app/stores/feedback.store'
import { usePreferencesStore } from '@/app/stores/preferences.store'
import { useProjectStore } from '@/app/stores/project.store'
import type { StartupPagePreference } from '@/app/startup/startup-page-preference'
import { getErrorMessage } from '@/shared/api/error'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { getWorkflowRuntimePreviewSnapshot, type RuntimePreviewSnapshot } from '@/workflows/workflow-editor/services/workflow-runtime-preview.service'
import { listWorkflowAppRuntimes } from '@/workflows/workflow-editor/services/workflow-runtime.service'
import type { WorkflowAppRuntime } from '@/workflows/workflow-editor/types'

type StartupPageMode = StartupPagePreference['mode']
type SelectValue = string | number | boolean | null

const RUNTIME_STATES = new Set(['created', 'starting', 'running', 'stopping', 'stopped', 'failed', 'unknown'])

const { t } = useI18n()
const feedbackStore = useFeedbackStore()
const preferencesStore = usePreferencesStore()
const projectStore = useProjectStore()

const draftMode = ref<StartupPageMode>(preferencesStore.startupPage.mode)
const selectedProjectId = ref(preferencesStore.startupPage.mode === 'workflow-runtime-app-mode'
  ? preferencesStore.startupPage.projectId
  : projectStore.selectedProjectId)
const selectedRuntimeId = ref(preferencesStore.startupPage.mode === 'workflow-runtime-app-mode'
  ? preferencesStore.startupPage.workflowRuntimeId
  : '')
const runtimes = ref<WorkflowAppRuntime[]>([])
const loadedRuntimeProjectId = ref('')
const validatedRuntime = ref<WorkflowAppRuntime | null>(null)
const loadingProjects = ref(false)
const loadingRuntimes = ref(false)
const validatingRuntime = ref(false)
const saving = ref(false)
const errorMessage = ref('')
let runtimeRequestGeneration = 0
let validationGeneration = 0

const projectOptions = computed(() => projectStore.projects.map((project) => ({
  label: project.display_name || project.project_id,
  value: project.project_id,
  description: project.project_id,
})))
const runtimeOptions = computed(() => [...runtimes.value]
  .sort((left, right) => runtimeOptionLabel(left).localeCompare(runtimeOptionLabel(right)))
  .map((runtime) => ({
    label: runtimeOptionLabel(runtime),
    value: runtime.workflow_runtime_id,
    description: `${runtimeStateLabel(runtime.observed_state)} · ${runtime.workflow_runtime_id}`,
  })))
const runtimePlaceholder = computed(() => loadingRuntimes.value
  ? t('startupPage.loadingRuntimes')
  : t('startupPage.selectRuntime'))
const showEmptyRuntimes = computed(() => Boolean(
  selectedProjectId.value
  && loadedRuntimeProjectId.value === selectedProjectId.value
  && runtimes.value.length === 0,
))
const canRestoreDefault = computed(() => (
  draftMode.value !== 'projects' || preferencesStore.startupPage.mode !== 'projects'
))
const isDirty = computed(() => {
  const current = preferencesStore.startupPage
  if (draftMode.value === 'projects') return current.mode !== 'projects'
  return current.mode !== 'workflow-runtime-app-mode'
    || current.projectId !== selectedProjectId.value
    || current.workflowRuntimeId !== selectedRuntimeId.value
})
const canSave = computed(() => !saving.value
  && !loadingProjects.value
  && !loadingRuntimes.value
  && !validatingRuntime.value
  && isDirty.value
  && (draftMode.value === 'projects' || Boolean(selectedProjectId.value && selectedRuntimeId.value && validatedRuntime.value)))

onMounted(() => {
  void initialize()
})

async function initialize(): Promise<void> {
  let projectsReady = true
  loadingProjects.value = true
  try {
    if (projectStore.projects.length === 0) {
      await projectStore.loadProjects({ includeSummary: false })
    }
    if (!selectedProjectId.value || !projectStore.projects.some((project) => project.project_id === selectedProjectId.value)) {
      selectedProjectId.value = projectStore.selectedProjectId || projectStore.projects[0]?.project_id || ''
      selectedRuntimeId.value = ''
    }
  } catch (error) {
    projectsReady = false
    errorMessage.value = getErrorMessage(error)
  } finally {
    loadingProjects.value = false
  }
  if (!projectsReady) return
  await loadRuntimes(selectedProjectId.value)
  if (selectedRuntimeId.value) await validateRuntime(selectedRuntimeId.value)
}

function setMode(mode: StartupPageMode): void {
  draftMode.value = mode
  errorMessage.value = ''
  if (mode === 'workflow-runtime-app-mode' && selectedProjectId.value && runtimes.value.length === 0) {
    void loadRuntimes(selectedProjectId.value)
  }
}

async function selectProject(value: SelectValue): Promise<void> {
  if (typeof value !== 'string' || value === selectedProjectId.value) return
  selectedProjectId.value = value
  selectedRuntimeId.value = ''
  validatedRuntime.value = null
  errorMessage.value = ''
  await loadRuntimes(value)
}

async function selectRuntime(value: SelectValue): Promise<void> {
  if (typeof value !== 'string') return
  selectedRuntimeId.value = value
  validatedRuntime.value = null
  errorMessage.value = ''
  await validateRuntime(value)
}

async function loadRuntimes(projectId: string): Promise<void> {
  const requestGeneration = ++runtimeRequestGeneration
  runtimes.value = []
  loadedRuntimeProjectId.value = ''
  validatedRuntime.value = null
  if (!projectId) return
  loadingRuntimes.value = true
  errorMessage.value = ''
  try {
    const items: WorkflowAppRuntime[] = []
    const visitedOffsets = new Set<number>()
    let offset = 0
    const limit = 100
    while (!visitedOffsets.has(offset)) {
      visitedOffsets.add(offset)
      const page = await listWorkflowAppRuntimes({ projectId, offset, limit })
      items.push(...page.items)
      const nextOffset = page.pagination.nextOffset
      if (!page.pagination.hasMore || nextOffset === null || visitedOffsets.has(nextOffset)) break
      offset = nextOffset
    }
    if (requestGeneration === runtimeRequestGeneration && selectedProjectId.value === projectId) {
      runtimes.value = items
      loadedRuntimeProjectId.value = projectId
    }
  } catch (error) {
    if (requestGeneration === runtimeRequestGeneration) {
      errorMessage.value = getErrorMessage(error)
    }
  } finally {
    if (requestGeneration === runtimeRequestGeneration) loadingRuntimes.value = false
  }
}

async function validateRuntime(runtimeId: string): Promise<RuntimePreviewSnapshot | null> {
  const requestGeneration = ++validationGeneration
  if (!runtimeId) return null
  validatingRuntime.value = true
  try {
    const snapshot = await getWorkflowRuntimePreviewSnapshot(runtimeId)
    if (requestGeneration !== validationGeneration || selectedRuntimeId.value !== runtimeId) return null
    const runtime = runtimes.value.find((item) => item.workflow_runtime_id === runtimeId) ?? null
    if (
      !runtime
      || snapshot.project_id !== selectedProjectId.value
      || snapshot.workflow_runtime_id !== runtimeId
      || snapshot.application_id !== runtime.application_id
    ) {
      errorMessage.value = t('startupPage.targetUnavailable')
      validatedRuntime.value = null
      return null
    }
    if (!snapshot.app_mode) {
      errorMessage.value = t('startupPage.appModeRequired')
      validatedRuntime.value = null
      return null
    }
    validatedRuntime.value = runtime
    errorMessage.value = ''
    return snapshot
  } catch (error) {
    if (requestGeneration === validationGeneration) {
      validatedRuntime.value = null
      errorMessage.value = getErrorMessage(error)
    }
    return null
  } finally {
    if (requestGeneration === validationGeneration) validatingRuntime.value = false
  }
}

async function save(): Promise<void> {
  if (!canSave.value) return
  saving.value = true
  try {
    if (draftMode.value === 'projects') {
      preferencesStore.resetStartupPage()
      feedbackStore.success(t('startupPage.saved'))
      return
    }
    const snapshot = await validateRuntime(selectedRuntimeId.value)
    if (!snapshot) return
    preferencesStore.setStartupPage({
      mode: 'workflow-runtime-app-mode',
      projectId: snapshot.project_id,
      applicationId: snapshot.application_id,
      workflowRuntimeId: snapshot.workflow_runtime_id,
    })
    feedbackStore.success(t('startupPage.saved'))
  } finally {
    saving.value = false
  }
}

function restoreDefault(): void {
  preferencesStore.resetStartupPage()
  draftMode.value = 'projects'
  errorMessage.value = ''
  feedbackStore.success(t('startupPage.restored'))
}

function runtimeOptionLabel(runtime: WorkflowAppRuntime): string {
  const applicationName = runtime.application_summary?.display_name || runtime.application_id
  const runtimeName = runtime.display_name || t('startupPage.unnamedRuntime')
  return `${applicationName} · ${runtimeName}`
}

function runtimeStateLabel(state: string): string {
  const normalized = state.trim().toLowerCase()
  return RUNTIME_STATES.has(normalized) ? t(`startupPage.states.${normalized}`) : state || t('startupPage.states.unknown')
}
</script>
