import { ref, type ComputedRef, type Ref } from 'vue'

import {
  createModelConversionTask,
  type ConversionTargetKey,
  type ModelConversionTaskSubmissionResponse,
  type ModelTaskType,
} from '../services/model.service'

export function useModelConversionState(options: {
  selectedTaskType: Ref<ModelTaskType>
  selectedProjectId: ComputedRef<string>
  conversionModelType: Ref<string>
  conversionSourceModelVersionId: Ref<string>
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
    if (!options.conversionModelType.value.trim()) {
      options.setErrorMessage('model_type 不能为空')
      return
    }
    conversionSubmitting.value = true
    options.setErrorMessage(null)
    try {
      lastConversionSubmission.value = await createModelConversionTask({
        taskType: options.selectedTaskType.value,
        projectId: options.selectedProjectId.value,
        modelType: options.conversionModelType.value.trim(),
        sourceModelVersionId: options.conversionSourceModelVersionId.value.trim(),
        target: options.conversionTarget.value,
        runtimeProfileId: options.conversionRuntimeProfileId.value.trim(),
        displayName: options.conversionDisplayName.value,
      })
      await options.refreshConversionTasks()
    } catch (error) {
      options.setErrorMessage(error instanceof Error ? error.message : options.submitConversionFailedMessage())
    } finally {
      conversionSubmitting.value = false
    }
  }

  return {
    conversionSubmitting,
    lastConversionSubmission,
    submitConversion,
  }
}
