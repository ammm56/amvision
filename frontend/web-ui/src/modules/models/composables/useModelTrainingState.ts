import { ref, type ComputedRef, type Ref } from 'vue'

import type { DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import {
  createModelTrainingTask,
  type ModelTaskType,
  type ModelTrainingTaskSubmissionResponse,
  type PlatformBaseModelSummary,
} from '../services/model.service'
import {
  buildTrainingExtraOptions,
  validateTrainingModelLayerValues,
  type TrainingParameterValues,
} from '../training-parameter-support'

const DEFAULT_TRAINING_RECIPE_ID = 'default'

const detectionTrainingFormatByModelType: Record<string, string> = {
  yolox: 'coco-detection-v1',
  rfdetr: 'coco-detection-v1',
  yolov8: 'yolo-detection-v1',
  yolo11: 'yolo-detection-v1',
  yolo26: 'yolo-detection-v1',
}

function normalizeText(value: string | null | undefined): string {
  return String(value ?? '').trim().toLowerCase()
}

function resolveExpectedTrainingExportFormat(taskType: ModelTaskType, modelTypeValue: string): string | null {
  if (taskType !== 'detection') {
    return null
  }
  return detectionTrainingFormatByModelType[normalizeText(modelTypeValue)] ?? null
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
  warmStartModelVersionId: Ref<string>
  trainingTaskSupportsWarmStart: ComputedRef<boolean>
  trainingSupportsGpuCount: ComputedRef<boolean>
  evaluationInterval: Ref<number>
  maxEpochs: Ref<number>
  batchSize: Ref<number>
  gpuCount: Ref<number>
  precision: Ref<string>
  inputWidth: Ref<number>
  inputHeight: Ref<number>
  trainingDisplayName: Ref<string>
  trainingModelParameterValues: TrainingParameterValues
  trainingAugmentationEnabled: Ref<boolean>
  alignTrainingInputSizeForSubmit: () => { width: number; height: number }
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

    const expectedFormatId = resolveExpectedTrainingExportFormat(
      options.selectedTaskType.value,
      options.resolvedTrainingModelType.value,
    )
    if (expectedFormatId !== null && normalizeText(datasetExport.format_id) !== normalizeText(expectedFormatId)) {
      return options.messages.trainingExportFormatMismatch({
        modelType: options.resolvedTrainingModelType.value,
        formatId: expectedFormatId,
      })
    }

    return null
  }

  async function submitTraining(): Promise<void> {
    const validationError = validateTrainingSelection()
    if (validationError) {
      options.setErrorMessage(validationError)
      return
    }
    const parameterError = validateTrainingModelLayerValues(
      options.selectedTaskType.value,
      options.resolvedTrainingModelType.value,
      options.trainingModelParameterValues,
      { augmentationEnabled: options.trainingAugmentationEnabled.value },
    )
    if (parameterError) {
      options.setErrorMessage(parameterError)
      return
    }
    trainingSubmitting.value = true
    options.setErrorMessage(null)
    try {
      const alignedInputSize = options.alignTrainingInputSizeForSubmit()
      options.inputWidth.value = alignedInputSize.width
      options.inputHeight.value = alignedInputSize.height
      lastTrainingSubmission.value = await createModelTrainingTask({
        taskType: options.selectedTaskType.value,
        projectId: options.selectedProjectId.value,
        modelType: options.resolvedTrainingModelType.value,
        datasetExportId: options.trainingDatasetExportId.value.trim(),
        datasetExportManifestKey: options.resolvedTrainingManifestKey.value,
        recipeId: DEFAULT_TRAINING_RECIPE_ID,
        modelScale: options.resolvedTrainingModelScale.value,
        outputModelName: options.outputModelName.value.trim(),
        warmStartModelVersionId: options.trainingTaskSupportsWarmStart.value
          ? options.warmStartModelVersionId.value.trim()
          : '',
        evaluationInterval: options.evaluationInterval.value,
        maxEpochs: options.maxEpochs.value,
        batchSize: options.batchSize.value,
        gpuCount: options.trainingSupportsGpuCount.value ? options.gpuCount.value : undefined,
        precision: options.precision.value,
        inputWidth: alignedInputSize.width,
        inputHeight: alignedInputSize.height,
        displayName: options.trainingDisplayName.value.trim(),
        extraOptions: buildTrainingExtraOptions(
          options.selectedTaskType.value,
          options.resolvedTrainingModelType.value,
          options.trainingModelParameterValues,
          { augmentationEnabled: options.trainingAugmentationEnabled.value },
        ),
      })
      await options.refreshTrainingTasks()
    } catch (error) {
      options.setErrorMessage(error instanceof Error ? error.message : options.messages.submitTrainingFailed())
    } finally {
      trainingSubmitting.value = false
    }
  }

  return {
    trainingSubmitting,
    lastTrainingSubmission,
    submitTraining,
  }
}
