import { ref, type ComputedRef, type Ref } from 'vue'
import { translate } from '@/platform/i18n'
import { isUncertainModelSubmission, useModelSubmissionReceipt } from './useModelSubmissionReceipt'

import type { DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import {
  createModelTrainingTask,
  previewModelTrainingTask,
  type ModelTrainingPreflight,
  type ModelTrainingTaskCreateInput,
  type ModelTaskType,
  type ModelTrainingTaskSubmissionResponse,
  type PlatformBaseModelSummary,
  type TrainingParameterSchemaItem,
} from '../services/model.service'
import {
  buildTrainingParameters,
  validateTrainingModelLayerValues,
  type TrainingParameterValues,
} from '../training-parameter-support'

const DEFAULT_TRAINING_RECIPE_ID = 'default'

function normalizeText(value: string | null | undefined): string {
  return String(value ?? '').trim().toLowerCase()
}

export function resolveSupportedTrainingExportFormats(
  taskType: ModelTaskType,
  modelTypeValue: string,
  formatsByTaskAndModelType: Record<string, Record<string, string[]>>,
): string[] {
  return formatsByTaskAndModelType[taskType]?.[normalizeText(modelTypeValue)] ?? []
}

export function useModelTrainingState(options: {
  selectedTaskType: Ref<ModelTaskType>
  selectedProjectId: ComputedRef<string>
  trainingSelectedModelSummary: ComputedRef<PlatformBaseModelSummary | null>
  selectedTrainingDatasetExport: ComputedRef<DatasetExportSummary | null>
  resolvedTrainingManifestKey: ComputedRef<string>
  resolvedTrainingModelType: ComputedRef<string>
  resolvedTrainingModelScale: ComputedRef<string>
  trainingDatasetExportId: Ref<string>
  outputModelName: Ref<string>
  trainingRecipeId?: Ref<string>
  warmStartModelVersionId: Ref<string>
  trainingTaskSupportsWarmStart: ComputedRef<boolean>
  evaluationInterval: Ref<number>
  maxEpochs: Ref<number>
  batchMode: Ref<'auto' | 'fixed'>
  batchSize: Ref<number>
  batchTargetMemoryFraction: Ref<number>
  batchMinimumSize: Ref<number>
  batchMaximumSize: Ref<number | undefined>
  batchRecoverOnOom: Ref<boolean>
  batchMaxOomRetries: Ref<number>
  trainingDevice: Ref<string>
  ampMode: Ref<'auto' | 'enabled' | 'disabled'>
  ampDtype: Ref<'auto' | 'fp16' | 'bf16'>
  checkpointInterval: Ref<number>
  checkpointKeepPeriodic: Ref<number>
  inputWidth: Ref<number>
  inputHeight: Ref<number>
  trainingDisplayName: Ref<string>
  trainingModelParameterValues: TrainingParameterValues
  trainingAugmentationEnabled: Ref<boolean>
  trainingParameterSchema: ComputedRef<TrainingParameterSchemaItem | null>
  trainingExportFormatsByTaskAndModelType: ComputedRef<Record<string, Record<string, string[]>>>
  alignTrainingInputSizeForSubmit: () => { width: number; height: number }
  principalId?: Ref<string>
  refreshTrainingTasks: () => Promise<void>
  setErrorMessage: (message: string | null) => void
  messages: {
    selectTrainingBaseModel: () => string
    selectTrainingDatasetExport: () => string
    trainingExportIncomplete: () => string
    trainingExportTaskMismatch: () => string
    trainingExportManifestMissing: () => string
    trainingExportFormatMismatch: (payload: { modelType: string; formatId: string }) => string
    submitTrainingFailed: () => string
  }
}) {
  const trainingSubmitting = ref(false)
  const lastTrainingSubmission = ref<ModelTrainingTaskSubmissionResponse | null>(null)
  const receipt = useModelSubmissionReceipt('training', options.selectedProjectId, options.selectedTaskType, options.principalId)
  const trainingSubmissionUncertain = receipt.pending

  function validateTrainingSelection(): string | null {
    if (
      options.trainingSelectedModelSummary.value === null
      || !options.resolvedTrainingModelType.value
      || !options.resolvedTrainingModelScale.value
    ) {
      return options.messages.selectTrainingBaseModel()
    }

    const datasetExport = options.selectedTrainingDatasetExport.value
    if (datasetExport === null) {
      return options.messages.selectTrainingDatasetExport()
    }
    if (normalizeText(datasetExport.status) !== 'completed') {
      return options.messages.trainingExportIncomplete()
    }
    if (normalizeText(datasetExport.task_type) !== normalizeText(options.selectedTaskType.value)) {
      return options.messages.trainingExportTaskMismatch()
    }
    if (!options.resolvedTrainingManifestKey.value) {
      return options.messages.trainingExportManifestMissing()
    }

    const supportedFormatIds = resolveSupportedTrainingExportFormats(
      options.selectedTaskType.value,
      options.resolvedTrainingModelType.value,
      options.trainingExportFormatsByTaskAndModelType.value,
    )
    if (
      supportedFormatIds.length > 0
      && !supportedFormatIds.some((formatId) => normalizeText(datasetExport.format_id) === normalizeText(formatId))
    ) {
      return options.messages.trainingExportFormatMismatch({
        modelType: options.resolvedTrainingModelType.value,
        formatId: supportedFormatIds.join(' / '),
      })
    }

    return null
  }

  function validateTrainingConfiguration(): string | null {
    const validationError = validateTrainingSelection()
    if (validationError) return validationError
    return validateTrainingModelLayerValues(
      options.selectedTaskType.value,
      options.resolvedTrainingModelType.value,
      options.trainingModelParameterValues,
      {
        maxEpochs: options.maxEpochs.value,
        augmentationEnabled: options.trainingAugmentationEnabled.value,
        parameterSchema: options.trainingParameterSchema.value,
      },
    )
  }

  function trainingInput(alignedInputSize: { width: number; height: number }): ModelTrainingTaskCreateInput {
    return {
      taskType: options.selectedTaskType.value,
      projectId: options.selectedProjectId.value,
      modelType: options.resolvedTrainingModelType.value,
      datasetExportId: options.trainingDatasetExportId.value.trim(),
      datasetExportManifestKey: options.resolvedTrainingManifestKey.value,
      recipeId: options.trainingRecipeId?.value || DEFAULT_TRAINING_RECIPE_ID,
      modelScale: options.resolvedTrainingModelScale.value,
      outputModelName: options.outputModelName.value.trim(),
      warmStartModelVersionId: options.trainingTaskSupportsWarmStart.value
        ? options.warmStartModelVersionId.value.trim()
        : '',
      maxEpochs: options.maxEpochs.value,
      batchMode: options.batchMode.value,
      batchSize: options.batchSize.value,
      batchTargetMemoryFraction: options.batchTargetMemoryFraction.value,
      batchMinimumSize: options.batchMinimumSize.value,
      batchMaximumSize: options.batchMaximumSize.value,
      batchRecoverOnOom: options.batchRecoverOnOom.value,
      batchMaxOomRetries: options.batchMaxOomRetries.value,
      ampMode: options.ampMode.value,
      ampDtype: options.ampDtype.value,
      checkpointInterval: options.checkpointInterval.value,
      checkpointKeepPeriodic: options.checkpointKeepPeriodic.value,
      evaluationInterval: options.evaluationInterval.value,
      inputWidth: alignedInputSize.width,
      inputHeight: alignedInputSize.height,
      displayName: options.trainingDisplayName.value.trim(),
      parameters: buildTrainingParameters(
        options.selectedTaskType.value,
        options.resolvedTrainingModelType.value,
        options.trainingModelParameterValues,
        {
          augmentationEnabled: options.trainingAugmentationEnabled.value,
          device: options.trainingDevice.value,
          parameterSchema: options.trainingParameterSchema.value,
        },
      ),
    }
  }

  function previewTraining(signal: AbortSignal): Promise<ModelTrainingPreflight> {
    const error = validateTrainingConfiguration()
    if (error) return Promise.reject(new Error(error))
    return previewModelTrainingTask(trainingInput(options.alignTrainingInputSizeForSubmit()), signal)
  }

  async function submitTraining(): Promise<void> {
    if (trainingSubmitting.value || lastTrainingSubmission.value || trainingSubmissionUncertain.value) return
    const validationError = validateTrainingConfiguration()
    if (validationError) {
      options.setErrorMessage(validationError)
      return
    }
    trainingSubmitting.value = true
    lastTrainingSubmission.value = null
    options.setErrorMessage(null)
    const projectId = options.selectedProjectId.value
    const taskType = options.selectedTaskType.value
    let submitted = false
    const attempt = receipt.start()
    try {
      const alignedInputSize = options.alignTrainingInputSizeForSubmit()
      options.inputWidth.value = alignedInputSize.width
      options.inputHeight.value = alignedInputSize.height
      const result = await createModelTrainingTask(trainingInput(alignedInputSize), attempt.id)
      attempt.clear()
      submitted = true
      if (projectId !== options.selectedProjectId.value || taskType !== options.selectedTaskType.value) return
      lastTrainingSubmission.value = result
      await options.refreshTrainingTasks()
    } catch (error) {
      const uncertain = !submitted && isUncertainModelSubmission(error, attempt.id)
      if (!uncertain) attempt.clear()
      if (projectId === options.selectedProjectId.value && taskType === options.selectedTaskType.value) {
        if (!uncertain) {
          options.setErrorMessage(submitted ? translate('modelOps.messages.submittedRefreshFailed') : error instanceof Error ? error.message : options.messages.submitTrainingFailed())
        }
      }
    } finally {
      trainingSubmitting.value = false
    }
  }

  return {
    trainingSubmitting,
    lastTrainingSubmission,
    trainingSubmissionUncertain,
    submitTraining,
    previewTraining,
    validateTrainingSelection,
    validateTrainingConfiguration,
    resetTrainingSubmission: () => { lastTrainingSubmission.value = null },
    trainingReceipt: receipt,
  }
}
