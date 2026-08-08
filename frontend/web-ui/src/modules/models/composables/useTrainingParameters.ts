import { computed, reactive, ref, watch, type ComputedRef, type Ref } from 'vue'

import type {
  ModelTaskType,
  PlatformBaseModelDetail,
  TrainingParameterSchemaItem,
} from '../services/model.service'
import {
  getDefaultTrainingEvaluationInterval,
  getDefaultTrainingModelParameterValues,
  getModelLayerTrainingFields,
  isTrainingAugmentationField,
  supportsTrainingWarmStart,
  type TrainingParameterValues,
} from '../training-parameter-support'

type SelectValue = string | number | boolean | null

function selectValueToString(value: SelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}

function normalizeText(value: string | null | undefined): string {
  return String(value ?? '').trim().toLowerCase()
}

function resolveOptimizerLearningRate(optimizer: string): string {
  return ['adam', 'adamw', 'nadam', 'radam'].includes(normalizeText(optimizer))
    ? '0.001'
    : '0.01'
}

function normalizeModelNameSegment(value: string | null | undefined): string {
  return String(value ?? '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
}

function buildModelNameTimestamp(date = new Date()): string {
  const pad = (value: number) => String(value).padStart(2, '0')
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
    pad(date.getHours()),
    pad(date.getMinutes()),
    pad(date.getSeconds()),
  ].join('')
}

function alignPositiveDimension(value: number, divisor: number): number {
  const normalized = Math.max(1, Math.trunc(Number(value) || 0))
  return Math.ceil(normalized / divisor) * divisor
}

function resolveRfdetrInputDivisor(
  taskType: ModelTaskType,
  modelTypeValue: string,
  modelScaleValue: string,
): number {
  if (normalizeText(modelTypeValue) !== 'rfdetr') {
    return 1
  }
  const scale = normalizeText(modelScaleValue)
  if (taskType === 'detection') {
    return scale === 'base' ? 56 : 32
  }
  if (taskType === 'segmentation') {
    return scale === 'nano' ? 12 : 24
  }
  return 1
}

export function useTrainingParameters(options: {
  selectedTaskType: Ref<ModelTaskType>
  resolvedTrainingModelType: ComputedRef<string>
  resolvedTrainingModelScale: ComputedRef<string>
  trainingParameterSchema: ComputedRef<TrainingParameterSchemaItem | null>
  translate: (key: string, params?: Record<string, string>) => string
}) {
  const outputModelName = ref('')
  const lastSuggestedOutputModelName = ref('')
  const maxEpochs = ref(100)
  const batchSize = ref(1)
  const trainingDevice = ref('')
  const evaluationInterval = ref(5)
  const precision = ref('fp32')
  const inputWidth = ref(640)
  const inputHeight = ref(640)
  const trainingDisplayName = ref('')
  const trainingModelParameterValues = reactive<TrainingParameterValues>({})
  const trainingAugmentationEnabled = ref(true)

  const trainingTaskSupportsWarmStart = computed(
    () => supportsTrainingWarmStart(options.selectedTaskType.value),
  )
  const allTrainingModelParameterFields = computed(
    () => {
      if (!options.resolvedTrainingModelType.value || !options.trainingParameterSchema.value) {
        return []
      }
      return getModelLayerTrainingFields(
        options.selectedTaskType.value,
        options.resolvedTrainingModelType.value,
        options.trainingParameterSchema.value,
      )
    },
  )
  const trainingModelParameterFields = computed(
    () => allTrainingModelParameterFields.value.filter((field) => !isTrainingAugmentationField(field)),
  )
  const trainingAugmentationParameterFields = computed(
    () => allTrainingModelParameterFields.value.filter(isTrainingAugmentationField),
  )
  const trainingSupportsAugmentationToggle = computed(
    () => trainingAugmentationParameterFields.value.length > 0,
  )
  const trainingModelParameterSectionTitle = computed(() => {
    if (!options.resolvedTrainingModelType.value) {
      return options.translate('modelOps.trainingParameters.advanced')
    }
    return options.translate('modelOps.trainingParameters.advancedForModel', {
      taskType: options.selectedTaskType.value,
      modelType: options.resolvedTrainingModelType.value,
    })
  })

  function buildSuggestedOutputModelName(
    model: Pick<PlatformBaseModelDetail, 'model_name' | 'model_type' | 'model_scale'>,
  ): string {
    const modelName = normalizeModelNameSegment(model.model_name || model.model_type) || 'model'
    const modelScale = normalizeModelNameSegment(model.model_scale) || 'default'
    return `${modelName}-${modelScale}-${buildModelNameTimestamp()}`
  }

  function syncSuggestedOutputModelName(
    model: Pick<PlatformBaseModelDetail, 'model_name' | 'model_type' | 'model_scale'>,
  ): void {
    const currentValue = outputModelName.value.trim()
    if (currentValue && currentValue !== lastSuggestedOutputModelName.value) {
      return
    }
    const nextValue = buildSuggestedOutputModelName(model)
    outputModelName.value = nextValue
    lastSuggestedOutputModelName.value = nextValue
  }

  function resetSuggestedOutputModelName(): void {
    outputModelName.value = ''
    lastSuggestedOutputModelName.value = ''
  }

  function setPrecision(value: SelectValue): void {
    precision.value = selectValueToString(value) === 'fp16' ? 'fp16' : 'fp32'
  }

  function setTrainingDevice(value: SelectValue): void {
    trainingDevice.value = selectValueToString(value)
  }

  function setTrainingModelParameterValue(key: string, value: SelectValue): void {
    const nextValue = selectValueToString(value)
    if (key === 'optimizer') {
      const previousOptimizer = trainingModelParameterValues.optimizer ?? 'auto'
      const previousDefault = resolveOptimizerLearningRate(previousOptimizer)
      const currentLearningRate = trainingModelParameterValues.learning_rate ?? ''
      trainingModelParameterValues.optimizer = nextValue
      if (!currentLearningRate || currentLearningRate === previousDefault) {
        trainingModelParameterValues.learning_rate = resolveOptimizerLearningRate(nextValue)
      }
      return
    }
    trainingModelParameterValues[key] = nextValue
  }

  function alignTrainingInputSizeForSubmit(): { width: number; height: number } {
    const divisor = resolveRfdetrInputDivisor(
      options.selectedTaskType.value,
      options.resolvedTrainingModelType.value,
      options.resolvedTrainingModelScale.value,
    )
    if (divisor <= 1) {
      return {
        width: inputWidth.value,
        height: inputHeight.value,
      }
    }
    return {
      width: alignPositiveDimension(inputWidth.value, divisor),
      height: alignPositiveDimension(inputHeight.value, divisor),
    }
  }

  watch(
    [
      options.selectedTaskType,
      options.resolvedTrainingModelType,
      options.trainingParameterSchema,
    ],
    ([taskType, modelType, parameterSchema]) => {
      const defaultValues = modelType && parameterSchema
        ? getDefaultTrainingModelParameterValues(taskType, modelType, parameterSchema)
        : {}
      const visibleKeys = new Set(Object.keys(defaultValues))
      for (const key of Object.keys(trainingModelParameterValues)) {
        if (!visibleKeys.has(key)) {
          delete trainingModelParameterValues[key]
        }
      }
      for (const [key, value] of Object.entries(defaultValues)) {
        trainingModelParameterValues[key] = value
      }
      evaluationInterval.value = getDefaultTrainingEvaluationInterval(taskType, modelType)
      trainingAugmentationEnabled.value = true
    },
    { immediate: true },
  )

  return {
    outputModelName,
    maxEpochs,
    batchSize,
    trainingDevice,
    evaluationInterval,
    precision,
    inputWidth,
    inputHeight,
    trainingDisplayName,
    trainingModelParameterValues,
    trainingAugmentationEnabled,
    trainingTaskSupportsWarmStart,
    trainingModelParameterFields,
    trainingAugmentationParameterFields,
    trainingSupportsAugmentationToggle,
    trainingModelParameterSectionTitle,
    setPrecision,
    setTrainingDevice,
    setTrainingModelParameterValue,
    syncSuggestedOutputModelName,
    resetSuggestedOutputModelName,
    alignTrainingInputSizeForSubmit,
  }
}
