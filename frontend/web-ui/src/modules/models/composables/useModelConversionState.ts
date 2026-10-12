import { ref, watch, type ComputedRef, type Ref } from 'vue'

import { translate } from '@/platform/i18n'
import {
  createModelConversionTask,
  type ConversionTargetKey,
  type ModelConversionTaskSubmissionResponse,
  type ModelTaskType,
} from '../services/model.service'
import { conversionSourceIssue } from '../conversion-source-support'
import type { ModelConversionSource } from './useModelConversionSourceSelection'

export function useModelConversionState(options: {
  selectedTaskType: Ref<ModelTaskType>
  selectedProjectId: ComputedRef<string>
  selectedSource: ComputedRef<ModelConversionSource | null>
  canWriteTasks: ComputedRef<boolean>
  conversionTarget: Ref<ConversionTargetKey>
  conversionRuntimeProfileId: Ref<string>
  conversionDisplayName: Ref<string>
  refreshConversionTasks: () => Promise<void>
  setErrorMessage: (message: string | null) => void
  submitConversionFailedMessage: () => string
}) {
  const conversionSubmitting = ref(false)
  const lastConversionSubmission = ref<ModelConversionTaskSubmissionResponse | null>(null)

  async function submitConversion(): Promise<void> {
    if (conversionSubmitting.value || !options.canWriteTasks.value) return
    const source = options.selectedSource.value
    const projectId = options.selectedProjectId.value
    const taskType = options.selectedTaskType.value
    if (
      !projectId || !source || source.model.task_type !== taskType
      || (source.model.project_id !== projectId && source.model.scope_kind !== 'platform-base')
      || conversionSourceIssue(source.version) !== null
    ) {
      options.setErrorMessage(translate('modelConversionSource.required'))
      return
    }
    conversionSubmitting.value = true
    options.setErrorMessage(null)
    try {
      const submission = await createModelConversionTask({
        taskType,
        projectId,
        modelType: source.model.model_type,
        sourceModelVersionId: source.version.model_version_id,
        target: options.conversionTarget.value,
        runtimeProfileId: options.conversionRuntimeProfileId.value.trim(),
        displayName: options.conversionDisplayName.value,
      })
      if (projectId !== options.selectedProjectId.value || taskType !== options.selectedTaskType.value) return
      lastConversionSubmission.value = submission
      await options.refreshConversionTasks()
    } catch (error) {
      if (projectId === options.selectedProjectId.value && taskType === options.selectedTaskType.value) {
        options.setErrorMessage(error instanceof Error ? error.message : options.submitConversionFailedMessage())
      }
    } finally {
      conversionSubmitting.value = false
    }
  }

  watch(() => [options.selectedProjectId.value, options.selectedTaskType.value], () => { lastConversionSubmission.value = null })

  return {
    conversionSubmitting,
    lastConversionSubmission,
    submitConversion,
  }
}
