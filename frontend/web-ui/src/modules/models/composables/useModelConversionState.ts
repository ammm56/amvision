import { ref, watch, type ComputedRef, type Ref } from 'vue'

import { translate } from '@/platform/i18n'
import { isUncertainModelSubmission, useModelSubmissionReceipt } from './useModelSubmissionReceipt'
import {
  createModelConversionTask,
  type ConversionTargetKey,
  type ModelConversionTaskSubmissionResponse,
  type ModelTaskType,
  type TensorRtInt8Settings,
  type Int8SampleSettings,
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
  onnxOpsetVersion?: Ref<number | undefined>
  inputShapeMode?: Ref<'dynamic-batch' | undefined>
  tensorRtInt8?: Ref<TensorRtInt8Settings | undefined>
  openVinoInt8?: Ref<Int8SampleSettings | undefined>
  conversionDisplayName: Ref<string>
  principalId?: Ref<string>
  refreshConversionTasks: () => Promise<void>
  setErrorMessage: (message: string | null) => void
  submitConversionFailedMessage: () => string
}) {
  const conversionSubmitting = ref(false)
  const lastConversionSubmission = ref<ModelConversionTaskSubmissionResponse | null>(null)
  const receipt = useModelSubmissionReceipt('conversion', options.selectedProjectId, options.selectedTaskType, options.principalId)
  const conversionSubmissionUncertain = receipt.pending

  async function submitConversion(): Promise<void> {
    if (conversionSubmitting.value || lastConversionSubmission.value || conversionSubmissionUncertain.value || !options.canWriteTasks.value) return
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
    lastConversionSubmission.value = null
    options.setErrorMessage(null)
    let submitted = false
    const attempt = receipt.start()
    try {
      const submission = await createModelConversionTask({
        taskType,
        projectId,
        modelType: source.model.model_type,
        sourceModelVersionId: source.version.model_version_id,
        target: options.conversionTarget.value,
        runtimeProfileId: options.conversionRuntimeProfileId.value.trim(),
        onnxOpsetVersion: options.onnxOpsetVersion?.value,
        inputShapeMode: options.inputShapeMode?.value,
        tensorRtInt8: options.tensorRtInt8?.value,
        openVinoInt8: options.openVinoInt8?.value,
        displayName: options.conversionDisplayName.value,
      }, attempt.id)
      attempt.clear()
      submitted = true
      if (projectId !== options.selectedProjectId.value || taskType !== options.selectedTaskType.value) return
      lastConversionSubmission.value = submission
      await options.refreshConversionTasks()
    } catch (error) {
      const uncertain = !submitted && isUncertainModelSubmission(error, attempt.id)
      if (!uncertain) attempt.clear()
      if (projectId === options.selectedProjectId.value && taskType === options.selectedTaskType.value) {
        if (!uncertain) options.setErrorMessage(submitted ? translate('modelOps.messages.submittedRefreshFailed') : error instanceof Error ? error.message : options.submitConversionFailedMessage())
      }
    } finally {
      conversionSubmitting.value = false
    }
  }

  watch(() => [options.selectedProjectId.value, options.selectedTaskType.value] as const, () => {
    lastConversionSubmission.value = null
  }, { immediate: true })

  return {
    conversionSubmitting,
    lastConversionSubmission,
    conversionSubmissionUncertain,
    submitConversion,
    resetConversionSubmission: () => { lastConversionSubmission.value = null },
    conversionReceipt: receipt,
  }
}
