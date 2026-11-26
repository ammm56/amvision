<template>
  <form ref="targetForm" class="form-panel model-ops-form" @submit.prevent="submitStep">
    <div class="conversion-heading">
      <Button type="button" @click="cancel">{{ zh ? '返回' : 'Back' }}</Button>
      <h2>{{ t('modelOps.conversionTitle') }}</h2>
      <slot name="submission-warning" />
    </div>
    <ol class="conversion-steps" :aria-label="zh ? '创建转换步骤' : 'Conversion steps'">
      <li v-for="(label, index) in stepLabels" :key="label" :class="{ 'is-current': step === index + 1, 'is-complete': step > index + 1 }" :aria-current="step === index + 1 ? 'step' : undefined">
        <span><Check v-if="step > index + 1" :size="16" aria-hidden="true" /><template v-else>{{ index + 1 }}</template></span><strong>{{ label }}</strong>
      </li>
    </ol>
    <div v-if="step > 1 && conversionSelectedModelSummary" class="conversion-source-summary">
      <strong>{{ modelDisplayName(conversionSelectedModelSummary) }}</strong>
      <span>{{ conversionSourceVersion ? modelVersionDisplayName(conversionSourceVersion) : '—' }}</span>
      <span>{{ modelTaskLabel(selectedTaskType, zh) }}</span>
      <span aria-hidden="true">→</span><strong>{{ unavailableTarget?.label || selectedTargetLabel }}</strong>
    </div>
    <div class="form-grid model-ops-form__grid">
      <div v-if="step === 1" class="field field--wide model-picker-field">
        <div class="model-picker-field__header">
          <div class="model-picker-field__title">
            <span>{{ t('modelOps.fields.conversionBaseModel') }}</span>
            <span class="model-picker-chip">{{ modelTaskLabel(selectedTaskType, zh) }}</span>
          </div>
          <Button
            size="sm"
            variant="secondary"
            type="button"
            :disabled="loading"
            @click="$emit('open-source-picker')"
          >
            {{ t('modelOps.actions.chooseConversionSource') }}
          </Button>
        </div>
        <div class="model-picker-summary" :class="{ 'is-empty': !conversionSelectedModelSummary }">
          <template v-if="conversionSelectedModelSummary">
            <div class="model-picker-summary__top">
              <div class="model-picker-summary__identity">
                <strong>{{ modelDisplayName(conversionSelectedModelSummary) }}</strong>
              </div>
              <div class="model-picker-summary__chips">
                <span class="model-picker-chip">{{ conversionSelectedModelSummary.model_type }}</span>
                <span class="model-picker-chip">
                  {{ zh ? '参数量' : 'Scale' }} · {{ conversionSelectedModelSummary.model_scale }}
                </span>
              </div>
            </div>
            <div class="model-picker-summary__footer">
              <span>{{ zh ? '来源版本' : 'Source version' }} · {{ conversionSourceVersion ? modelVersionDisplayName(conversionSourceVersion) : t('common.noValue') }}</span>
            </div>
          </template>
          <template v-else>
            <strong>{{ t('modelConversionSource.emptySelection') }}</strong>
          </template>
        </div>
      </div>
      <fieldset v-if="step === 2" class="field field--wide conversion-targets">
        <legend>{{ t('modelOps.fields.targetFormat') }}</legend>
        <div class="conversion-targets__grid">
          <div v-for="group in targetGroups" :key="group.key" class="conversion-target-choice" :class="{ 'is-selected': group.key === activeTargetGroup, 'is-unavailable': !group.enabled, 'conversion-target-choice--platform': group.platform }">
            <label class="conversion-target">
              <input type="radio" name="conversion-target" :aria-label="group.label" :checked="group.key === activeTargetGroup"
                :disabled="!group.enabled && !group.platform" @change="selectTargetGroup(group.key)" />
              <img v-if="group.logo" class="conversion-target__logo" :class="`is-${group.key}`" :src="group.logo" alt="" aria-hidden="true" />
              <span class="conversion-target__label"><strong>{{ group.label }}</strong><small>{{ group.description }}</small></span>
            </label>
            <Button v-if="!group.enabled && !group.platform" type="button" variant="ghost" size="sm" class="conversion-target-choice__requirements"
              :aria-label="zh ? `查看 ${group.label} 要求` : `View ${group.label} requirements`"
              :aria-expanded="unavailableTarget?.key === group.key" :aria-controls="unavailableTarget?.key === group.key ? 'conversion-target-requirements' : undefined"
              @click="unavailableTargetKey = group.key"
            >{{ zh ? '查看要求' : 'View requirements' }}</Button>
          </div>
        </div>
        <section v-if="unavailableTarget?.platform" class="conversion-target-requirements" :aria-label="zh ? '目标配置' : 'Target configuration'">
          <h3>{{ zh ? '目标配置' : 'Target configuration' }}</h3>
          <div class="conversion-platform-configuration">
            <div class="conversion-platform-configuration__target">
              <template v-if="unavailableTarget.key === 'coreml'">
                <label class="field">
                  <span>{{ zh ? '格式' : 'Format' }}</span>
                  <input readonly value="ML Program" />
                </label>
                <label class="field">
                  <span>{{ zh ? '最低系统' : 'Minimum OS' }}</span>
                  <input readonly value="macOS 12" />
                </label>
              </template>
              <label v-else class="field">
                <span>{{ zh ? '厂商适配器' : 'Vendor adapter' }}</span>
                <input readonly :value="zh ? '未登记' : 'Unregistered'" />
              </label>
            </div>
            <div class="conversion-platform-configuration__environment">
              <label class="field">
                <span>{{ zh ? '执行环境' : 'Execution environment' }}</span>
                <SelectField id="conversion-environment-select" :model-value="null" :options="unavailableEnvironments" floating
                  :aria-label="zh ? '执行环境' : 'Execution environment'"
                  :placeholder="zh ? '未选择' : 'None selected'" aria-describedby="conversion-environment-status" />
              </label>
              <div class="conversion-target-requirements__warning">
                <span id="conversion-environment-status" role="status">
                  <TriangleAlert :size="18" aria-hidden="true" />
                  {{ zh ? '没有可用于转换和校验的兼容环境。' : 'No compatible environment is available for conversion and validation.' }}
                </span>
                <div class="conversion-platform-configuration__actions">
                  <Button type="button" size="sm" @click="openEnvironmentSelector">{{ zh ? '选择环境' : 'Choose environment' }}</Button>
                  <Button type="button" size="sm" :aria-expanded="platformRequirementsOpen" aria-controls="conversion-platform-requirements"
                    @click="platformRequirementsOpen = !platformRequirementsOpen">{{ zh ? '查看要求' : 'View requirements' }}</Button>
                </div>
              </div>
            </div>
          </div>
          <p v-if="platformRequirementsOpen" id="conversion-platform-requirements" class="conversion-platform-requirement">{{ unavailableTargetRequirement }}</p>
          <details v-if="unavailableTarget.key === 'coreml'" class="conversion-platform-requirement">
            <summary>{{ zh ? 'ARM NPU 要求' : 'ARM NPU requirements' }}</summary>
            <p>{{ platformRequirement('arm-npu') }}</p>
          </details>
        </section>
        <section v-else-if="unavailableTarget" id="conversion-target-requirements" class="conversion-target-requirements" :aria-label="zh ? `${unavailableTarget.label} 要求` : `${unavailableTarget.label} requirements`">
          <div class="conversion-target-requirements__warning" role="status">
            <TriangleAlert :size="18" aria-hidden="true" />
            {{ zh ? '当前没有适用于此目标的转换和校验环境。' : 'No compatible environment is available for conversion and validation.' }}
          </div>
          <dl>
            <div><dt>{{ zh ? '目标格式' : 'Target format' }}</dt><dd>{{ unavailableTarget.label }}</dd></div>
            <div><dt>{{ zh ? '执行环境' : 'Execution environment' }}</dt><dd>{{ zh ? '不可用' : 'Unavailable' }}</dd></div>
            <div><dt>{{ zh ? '环境要求' : 'Environment requirements' }}</dt><dd>{{ unavailableTargetRequirement }}</dd></div>
          </dl>
          <Button type="button" size="sm" @click="restoreAvailableTarget">{{ zh ? '返回可用目标' : 'Return to available targets' }}</Button>
        </section>
      </fieldset>
      <section v-if="step === 3" class="field field--wide conversion-parameters">
        <h3>{{ zh ? '转换参数' : 'Conversion parameters' }}</h3>
        <div class="conversion-parameters__grid">
          <label class="field">
            <span>{{ targetOptionLabel }}</span>
            <SelectField :model-value="conversionTarget" :options="selectedTargetOptions" :aria-label="targetOptionLabel" @update:model-value="$emit('update:conversionTarget', String($event))" />
          </label>
          <label v-if="selectedTargetGroup === 'onnx'" class="field">
            <span>{{ zh ? '张量精度' : 'Tensor precision' }}</span><input value="FP32" readonly />
          </label>
          <div v-if="selectedTargetGroup === 'onnx'" class="field conversion-opset-field">
            <span>ONNX Opset</span>
            <div class="conversion-opset-field__value">
              <SelectField v-if="opsetEditable" :model-value="onnxOpsetVersion ?? 18" :options="opsetOptions" aria-label="ONNX Opset" @update:model-value="$emit('update:onnxOpsetVersion', Number($event))" />
              <input v-else value="18" aria-label="ONNX Opset" readonly />
              <details class="conversion-opset-support">
                <summary>{{ zh ? '查看支持范围' : 'View supported versions' }}</summary>
                <p>{{ supportedOpsetText }}</p>
              </details>
            </div>
          </div>
          <label v-if="openVinoInt8Enabled" class="field">
            <span>{{ zh ? '量化方法' : 'Quantization method' }}</span><input value="NNCF" readonly />
          </label>
          <label v-if="int8Enabled || openVinoInt8Enabled" class="field">
            <span>{{ zh ? '执行环境' : 'Execution environment' }}</span>
            <input :value="openVinoInt8Enabled ? (zh ? '本地 OpenVINO CPU' : 'Local OpenVINO CPU') : (zh ? '本地 NVIDIA GPU' : 'Local NVIDIA GPU')" readonly />
          </label>
          <label class="field">
            <span>{{ zh ? '输入模式' : 'Input mode' }}</span>
            <SelectField v-if="dynamicBatchAvailable" :model-value="inputShapeMode ?? 'static'" :options="inputShapeOptions" :aria-label="zh ? '输入模式' : 'Input mode'" @update:model-value="$emit('update:inputShapeMode', $event === 'dynamic-batch' ? 'dynamic-batch' : undefined)" />
            <input v-else :value="inputModeLabel" readonly />
          </label>
          <label v-if="int8Enabled && tensorRtInt8" class="field">
            <span>{{ zh ? 'Workspace 上限（GB）' : 'Workspace limit (GB)' }}</span>
            <input type="number" min="1" max="8" required :value="tensorRtInt8.workspace_gib" @input="updateWorkspace" />
          </label>
          <label v-if="!openVinoInt8Enabled" class="field"><span>{{ int8Enabled ? (zh ? '输入格式' : 'Input layout') : (zh ? '输入张量' : 'Input tensor') }}</span><input :value="inputTensorLabel" readonly /></label>
          <label v-if="selectedTargetGroup === 'onnx'" class="field">
            <span>{{ zh ? '输入名称' : 'Input name' }}</span><input :value="onnxInputName" readonly />
          </label>
          <label v-if="selectedTargetGroup === 'onnx'" class="field">
            <span>{{ zh ? '动态维度' : 'Dynamic axes' }}</span><input :value="onnxDynamicAxes" readonly />
          </label>
          <label v-if="selectedTargetGroup === 'openvino'" class="field">
            <span>{{ zh ? '输出文件' : 'Output files' }}</span><input value=".xml + .bin" readonly />
          </label>
          <label v-if="openVinoInt8Enabled" class="field">
            <span>{{ zh ? '批大小（Batch）' : 'Batch size' }}</span><input value="1" readonly />
          </label>
          <label v-if="selectedTargetGroup === 'openvino' && !openVinoInt8Enabled" class="field">
            <span>{{ zh ? '校验设备' : 'Validation device' }}</span><input value="CPU" readonly />
          </label>
          <label v-if="!int8Enabled && !openVinoInt8Enabled" class="field">
            <span>{{ t('modelOps.fields.conversionDisplayName') }}</span>
            <input :value="conversionDisplayName" @input="emitString('update:conversionDisplayName', $event)" />
          </label>
        </div>
        <TensorRtInt8Fields
          v-if="int8Enabled && tensorRtInt8"
          :model-value="tensorRtInt8"
          :zh="zh"
          :dataset-exports="datasetExports ?? []"
          @update:model-value="$emit('update:tensorRtInt8', $event)"
        />
        <Int8SampleFields
          v-else-if="openVinoInt8Enabled && openVinoInt8"
          :model-value="openVinoInt8" :dataset-exports="datasetExports ?? []" :zh="zh"
          :dataset-export-labels="datasetExportLabels"
          stacked
          @update:model-value="$emit('update:openVinoInt8', $event)"
        />
        <p v-else class="conversion-parameters__hint"><Info :size="16" aria-hidden="true" />{{ conversionParameterHint }}</p>
        <section v-if="openVinoInt8Enabled" class="conversion-parameters__advanced conversion-input-summary">
          <h4>{{ zh ? '输入与预处理' : 'Input and preprocessing' }}</h4>
          <div class="conversion-parameters__grid">
            <label class="field"><span>{{ zh ? '输入张量' : 'Input tensor' }}</span><input :value="inputTensorLabel" readonly /></label>
            <label class="field"><span>{{ zh ? '图像预处理' : 'Image preprocessing' }}</span><input value="RGB / LetterBox / 255" readonly /></label>
          </div>
          <p class="conversion-parameters__hint"><Info :size="16" aria-hidden="true" />{{ zh ? '校准与输出校验使用不同样本。数值校验通过后登记 IR，任务精度可在评估页面检查。' : 'Calibration and validation use separate images. The IR is registered after numerical validation. Use Evaluation to check task accuracy.' }}</p>
        </section>
        <details class="conversion-parameters__advanced">
          <summary>{{ zh ? '高级参数' : 'Advanced parameters' }}</summary>
          <div class="conversion-parameters__grid">
            <label v-if="selectedTargetGroup !== 'onnx'" class="field">
              <span>ONNX Opset</span>
              <SelectField v-if="opsetEditable" :model-value="onnxOpsetVersion ?? 18" :options="opsetOptions" @update:model-value="$emit('update:onnxOpsetVersion', Number($event))" />
              <input v-else value="18" readonly />
            </label>
            <label class="field">
              <span>{{ t('modelOps.fields.conversionRuntimeProfileId') }}</span>
              <input :value="conversionRuntimeProfileId" @input="emitString('update:conversionRuntimeProfileId', $event)" />
            </label>
            <label v-if="int8Enabled || openVinoInt8Enabled" class="field">
              <span>{{ t('modelOps.fields.conversionDisplayName') }}</span>
              <input :value="conversionDisplayName" @input="emitString('update:conversionDisplayName', $event)" />
            </label>
          </div>
        </details>
      </section>
      <p v-if="step === 3 && selectedTargetGroup === 'openvino'" class="field--wide conversion-parameters__hint">
        <Info :size="16" aria-hidden="true" />{{ openVinoInt8SupportText }}
      </p>
      <details v-if="step === 3 && !int8Enabled && !openVinoInt8Enabled" class="field field--wide conversion-parameters__advanced conversion-parameters__environment">
        <summary>{{ zh ? '执行环境' : 'Execution environment' }}</summary>
        <p>{{ conversionEnvironmentHint }}</p>
      </details>
      <section v-if="step === 4" class="field field--wide conversion-review">
        <h3>{{ zh ? '转换配置' : 'Conversion configuration' }}</h3>
        <dl>
          <dt>{{ zh ? '来源模型' : 'Source model' }}</dt><dd>{{ conversionSelectedModelSummary ? modelDisplayName(conversionSelectedModelSummary) : '—' }}</dd>
          <dt>{{ zh ? '来源版本' : 'Source version' }}</dt><dd>{{ conversionSourceVersion ? modelVersionDisplayName(conversionSourceVersion) : '—' }}</dd>
          <dt>{{ t('modelOps.fields.targetFormat') }}</dt><dd>{{ selectedTargetLabel }}</dd>
          <dt>ONNX Opset</dt><dd>{{ onnxOpsetVersion ?? 18 }}</dd>
          <dt>{{ zh ? '输入模式' : 'Input mode' }}</dt><dd>{{ inputModeLabel }}</dd>
          <template v-if="int8Enabled && tensorRtInt8">
            <dt>NCHW profile</dt>
            <dd class="review-profile"><span v-for="(shape, label) in tensorRtInt8.input_profile" :key="label">{{ label }} {{ shape.join(' × ') }}</span></dd>
            <dt>Workspace</dt><dd>{{ tensorRtInt8.workspace_gib }} GB</dd>
            <dt>{{ zh ? 'INT8 校准' : 'INT8 calibration' }}</dt><dd>{{ sampleSourceLabel(tensorRtInt8.int8_calibration, 'train') }}</dd>
            <dt>{{ zh ? '独立校验' : 'Independent validation' }}</dt><dd>{{ sampleSourceLabel(tensorRtInt8.int8_validation, 'val') }}</dd>
          </template>
          <template v-if="openVinoInt8Enabled && openVinoInt8">
            <dt>{{ zh ? '量化方法' : 'Quantization method' }}</dt><dd>NNCF</dd>
            <dt>{{ zh ? 'INT8 校准' : 'INT8 calibration' }}</dt><dd>{{ sampleSourceLabel(openVinoInt8.int8_calibration, 'train') }}</dd>
            <dt>{{ zh ? '独立校验' : 'Independent validation' }}</dt><dd>{{ sampleSourceLabel(openVinoInt8.int8_validation, 'val') }}</dd>
          </template>
          <dt>{{ t('modelOps.fields.conversionRuntimeProfileId') }}</dt><dd>{{ conversionRuntimeProfileId || '—' }}</dd>
        </dl>
        <div class="conversion-checks">
          <h3>{{ zh ? '检查结果' : 'Checks' }}</h3>
          <div><strong>{{ zh ? '来源文件' : 'Source file' }}</strong><span>{{ checkpointCheckText }}</span></div>
          <div><strong>{{ zh ? '来源与转换方案' : 'Source and conversion plan' }}</strong><span role="status">{{ preflightText }}</span></div>
          <div v-if="preflightStatus === 'failed'" class="conversion-check-error"><span>{{ preflightError }}</span><Button type="button" size="sm" @click="preflightRetry++">{{ zh ? '重新检查' : 'Retry' }}</Button></div>
          <div><strong>{{ zh ? '转换环境' : 'Conversion environment' }}</strong><span>{{ zh ? '提交后检查' : 'Checked after submission' }}</span></div>
        </div>
        <p>{{ zh ? '提交时服务端会再次检查来源和方案，执行时检查转换环境。' : 'The server checks the source and plan again on submission and the environment during execution.' }}</p>
      </section>
    </div>
    <slot name="submission-result" />
    <div class="form-actions conversion-actions" :class="{ 'conversion-actions--short-screen': step === 2 || step === 3 }">
      <Button v-if="step > 1" type="button" :disabled="conversionSubmitting || conversionSubmissionUncertain" @click="step--">{{ zh ? '上一步' : 'Previous' }}</Button>
      <span v-else></span>
      <div class="conversion-actions__end">
      <Button type="button" @click="cancel">{{ conversionSubmissionUncertain ? (zh ? '返回任务列表' : 'Back to tasks') : t('common.cancel') }}</Button>
      <Button
        variant="primary"
        type="submit"
        :class="{ 'conversion-action--blocked': step === 2 && !canAdvanceTarget }"
        :disabled="loading || !conversionSelectedModelSummary || !conversionSourceModelVersionId.trim() || (step === 2 && !canAdvanceTarget) || (step === 4 && (preflightStatus !== 'passed' || !canWriteTasks || conversionSubmitting || !!lastConversionSubmission || conversionSubmissionUncertain))"
        :loading="step === 4 && conversionSubmitting"
      >
        <Wand2 v-if="step === 4" :size="16" />
        {{ step < 4 ? (zh ? '下一步' : 'Next') : conversionSubmitting ? t('modelOps.actions.submitting') : t('modelOps.actions.submitConversion') }}
      </Button>
      </div>
    </div>
    <TaskSubmissionNotice
      v-if="lastConversionSubmission"
      :title="t('modelOps.messages.conversionSubmitted')"
      :identifier="lastConversionSubmission.task_id"
      :detail-to="`/models/${selectedTaskType}/conversion-tasks/${lastConversionSubmission.task_id}`"
    />
    <Button v-if="lastConversionSubmission" type="button" @click="step = 1; $emit('reset-submission')">{{ t('modelOps.actions.createAnotherConversion') }}</Button>
  </form>
</template>

<script setup lang="ts">
import { Check, Info, TriangleAlert, Wand2 } from '@lucide/vue'
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import armNpuLogo from '../assets/arm-npu.svg'
import coremlLogo from '../assets/coreml.svg'

import type {
  ConversionTargetKey,
  ModelConversionTaskSubmissionResponse,
  ModelTaskType,
  PlatformBaseModelSummary,
  PlatformBaseModelVersionSummary,
  TensorRtInt8Settings,
  Int8SampleSettings,
} from '../services/model.service'
import type { DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import TensorRtInt8Fields from './TensorRtInt8Fields.vue'
import Int8SampleFields from './Int8SampleFields.vue'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import TaskSubmissionNotice from '@/modules/tasks/components/TaskSubmissionNotice.vue'
import { modelDisplayName, modelVersionDisplayName } from '../model-display-name'
import { modelTaskLabel } from '../model-evaluation-types'
import { previewModelConversion } from '../services/model.service'

type UpdateStringEvent =
  | 'update:conversionRuntimeProfileId'
  | 'update:conversionDisplayName'

const props = defineProps<{
  projectId: string
  selectedTaskType: ModelTaskType
  loading: boolean
  conversionSelectedModelSummary: PlatformBaseModelSummary | null
  conversionModelType: string
  conversionSourceModelVersionId: string
  conversionSourceVersion: PlatformBaseModelVersionSummary | null
  conversionTarget: ConversionTargetKey
  conversionTargetOptions: Array<{ label: string; value: string }>
  conversionRuntimeProfileId: string
  onnxOpsetVersion?: number
  inputShapeMode?: 'dynamic-batch'
  tensorRtInt8?: TensorRtInt8Settings
  openVinoInt8?: Int8SampleSettings
  datasetExports?: DatasetExportSummary[]
  datasetExportLabels?: ReadonlyMap<string, string>
  conversionDisplayName: string
  canWriteTasks: boolean
  conversionSubmitting: boolean
  conversionSubmissionUncertain: boolean
  lastConversionSubmission: ModelConversionTaskSubmissionResponse | null
}>()

const emit = defineEmits<{
  submit: []
  cancel: []
  'reset-submission': []
  'open-source-picker': []
  'update:conversionTarget': [value: string]
  'update:conversionRuntimeProfileId': [value: string]
  'update:onnxOpsetVersion': [value: number]
  'update:inputShapeMode': [value: 'dynamic-batch' | undefined]
  'update:tensorRtInt8': [settings: TensorRtInt8Settings]
  'update:openVinoInt8': [settings: Int8SampleSettings]
  'update:conversionDisplayName': [value: string]
}>()

const { t, locale } = useI18n()
const zh = computed(() => locale.value.startsWith('zh'))
const step = ref(1)
const opsetEditable = computed(() => ['yolox', 'yolov8', 'yolo11', 'yolo26'].includes(props.conversionModelType.toLowerCase()))
const opsetOptions = [{ label: '18', value: 18 }, { label: '19', value: 19 }]
const supportedOpsetText = computed(() => {
  const versions = opsetEditable.value ? opsetOptions.map(item => item.label).join('、') : '18'
  return zh.value ? `此模型的转换服务支持 Opset ${versions}。目标运行环境也需支持所选版本。` : `The converter supports Opset ${versions} for this model. The target runtime must also support the selected version.`
})
const onnxInputName = computed(() => {
  if (opsetEditable.value) return 'images'
  return props.conversionModelType === 'rfdetr' ? 'image' : '—'
})
const onnxDynamicAxes = computed(() => props.inputShapeMode === 'dynamic-batch'
  ? (zh.value ? 'Batch 可变，宽高固定' : 'Dynamic batch, fixed width and height')
  : (zh.value ? '全部固定' : 'All axes fixed'))
const dynamicBatchAvailable = computed(() => props.conversionModelType === 'yolo11' && props.selectedTaskType === 'detection' && props.conversionTarget === 'onnx')
const int8Enabled = computed(() => props.conversionTarget === 'tensorrt-engine-int8')
const openVinoInt8Enabled = computed(() => props.conversionTarget === 'openvino-ir-int8')
const inputModeLabel = computed(() => {
  if (int8Enabled.value) return zh.value ? '动态输入' : 'Dynamic'
  if (openVinoInt8Enabled.value) return zh.value ? '固定输入（Batch 1）' : 'Static (batch 1)'
  if (props.inputShapeMode) return zh.value ? '动态批次' : 'Dynamic batch'
  return zh.value ? '固定' : 'Static'
})
const inputShapeOptions = computed(() => [
  { label: zh.value ? '固定' : 'Static', value: 'static' },
  { label: zh.value ? '动态批次' : 'Dynamic batch', value: 'dynamic-batch' },
])
const preflightStatus = ref<'idle' | 'loading' | 'passed' | 'failed'>('idle')
const preflightError = ref('')
const preflightRetry = ref(0)
const preflightText = computed(() => {
  if (preflightStatus.value === 'loading') return zh.value ? '检查中' : 'Checking'
  if (preflightStatus.value === 'passed') return zh.value ? '通过' : 'Passed'
  if (preflightStatus.value === 'failed') return zh.value ? '检查失败' : 'Check failed'
  return zh.value ? '待检查' : 'Not checked'
})
const stepLabels = computed(() => zh.value ? ['来源', '目标', '参数', '检查'] : ['Source', 'Target', 'Parameters', 'Review'])
const selectedTargetLabel = computed(() => props.conversionTargetOptions.find(option => option.value === props.conversionTarget)?.label || props.conversionTarget)
const inputTensorLabel = computed(() => {
  if (int8Enabled.value) return 'NCHW'
  const spec = props.conversionSourceVersion?.metadata?.model_input_spec as { tensor_shape?: unknown; tensor_layout?: string; layout?: string } | undefined
  if (!Array.isArray(spec?.tensor_shape) || !spec.tensor_shape.every(value => Number.isInteger(value))) return '—'
  const dimensions = props.inputShapeMode ? ['N', ...spec.tensor_shape.slice(1)] : spec.tensor_shape
  return [dimensions.join(openVinoInt8Enabled.value ? '×' : ' × '), spec.tensor_layout || spec.layout].filter(Boolean).join(' · ')
})
const checkpointCheckText = computed(() => {
  const status = props.conversionSourceVersion?.checkpoint_state
  if (status === 'present') return zh.value ? '文件存在，内容待校验' : 'File exists; content not yet validated'
  if (status === 'missing') return zh.value ? '文件缺失' : 'File missing'
  if (status === 'unavailable') return zh.value ? '无法检查' : 'Unable to check'
  return zh.value ? '状态未知，提交时检查' : 'Unknown; checked on submission'
})
type TargetGroup = 'onnx' | 'openvino' | 'tensorrt' | 'coreml' | 'arm-npu'
function groupForTarget(value: string): TargetGroup {
  if (value.startsWith('openvino')) return 'openvino'
  if (value.startsWith('tensorrt')) return 'tensorrt'
  return 'onnx'
}
const selectedTargetGroup = computed(() => groupForTarget(props.conversionTarget))
const openVinoInt8Supported = computed(() => props.conversionTargetOptions.some(option => option.value === 'openvino-ir-int8'))
const openVinoInt8SupportText = computed(() => {
  if (openVinoInt8Supported.value) return zh.value
    ? '所选模型与任务支持 OpenVINO INT8 量化，使用固定输入和批大小 1。'
    : 'The selected model and task support OpenVINO INT8 quantization with a fixed input shape and batch size 1.'
  return zh.value
    ? '所选模型与任务不支持 OpenVINO INT8。当前仅 YOLO11 目标检测支持 INT8 量化，使用固定输入和批大小 1。'
    : 'The selected model and task do not support OpenVINO INT8. INT8 quantization is available only for YOLO11 object detection with a fixed input shape and batch size 1.'
})
const targetOptionLabel = computed(() => {
  if (selectedTargetGroup.value === 'onnx') return zh.value ? '输出选项' : 'Output option'
  if (selectedTargetGroup.value === 'openvino') return openVinoInt8Supported.value
    ? (zh.value ? '优化方式' : 'Optimization') : (zh.value ? '权重压缩' : 'Weight compression')
  return zh.value ? '精度' : 'Precision'
})
const conversionParameterHint = computed(() => {
  if (selectedTargetGroup.value === 'onnx') return zh.value
    ? '此转换生成单个 ONNX 文件。输入宽高沿用来源模型，目标运行环境须支持所选 Opset。'
    : 'This conversion produces one ONNX file. Input width and height follow the source model. The target runtime must support the selected Opset.'
  if (selectedTargetGroup.value === 'openvino') return zh.value
    ? 'FP16 选项压缩权重。运行设备、推理精度、线程与 streams 在部署时配置。'
    : 'FP16 compresses the weights. Choose the runtime device, inference precision, threads, and streams during deployment.'
  return zh.value ? '输入宽高沿用来源模型。' : 'Input width and height follow the source model.'
})
const conversionEnvironmentHint = computed(() => selectedTargetGroup.value === 'openvino'
  ? (zh.value ? 'OpenVINO 与来源 ONNX 的输出在 Worker 的 CPU 环境执行校验。' : 'The worker validates OpenVINO against the source ONNX on CPU.')
  : (zh.value ? 'Worker 在开始转换时检查执行设备与依赖。' : 'The worker checks devices and dependencies when conversion starts.'))
const targetGroups = computed(() => ([
  { key: 'onnx' as const, label: 'ONNX', description: zh.value ? '通用模型格式' : 'Portable model format', platform: false, logo: null },
  { key: 'openvino' as const, label: 'OpenVINO', description: zh.value ? 'Intel 推理格式' : 'Intel inference format', platform: false, logo: null },
  { key: 'tensorrt' as const, label: 'TensorRT', description: zh.value ? 'NVIDIA GPU 推理格式' : 'NVIDIA GPU inference format', platform: false, logo: null },
  { key: 'coreml' as const, label: 'CoreML', description: zh.value ? 'Apple 设备机器学习推理' : 'Machine learning on Apple devices', platform: true, logo: coremlLogo },
  { key: 'arm-npu' as const, label: 'ARM NPU', description: zh.value ? '边缘设备 NPU 推理' : 'Edge NPU inference', platform: true, logo: armNpuLogo },
]).map(group => ({ ...group, enabled: props.conversionTargetOptions.some(option => groupForTarget(option.value) === group.key) })))
const unavailableTargetKey = ref<TargetGroup | null>(null)
const platformRequirementsOpen = ref(false)
// 本发行版没有登记具备这两种格式的构建与校验消费者。
const unavailableEnvironments = computed(() => [{
  value: 'unavailable', disabled: true,
  label: zh.value ? '暂无兼容环境' : 'No compatible environments',
}])
const unavailableTarget = computed(() => targetGroups.value.find(group => group.key === unavailableTargetKey.value && !group.enabled))
const activeTargetGroup = computed(() => unavailableTarget.value?.key ?? selectedTargetGroup.value)
const canAdvanceTarget = computed(() => !unavailableTarget.value && props.conversionTargetOptions.some(option => option.value === props.conversionTarget))
function platformRequirement(target: TargetGroup | undefined): string {
  switch (target) {
    case 'coreml':
      return zh.value ? 'ML Program 需要 CoreML 转换适配器，以及 macOS 12 或更新版本的 Apple 校验环境。' : 'ML Program requires a CoreML converter and an Apple validation environment running macOS 12 or later.'
    case 'arm-npu':
      return zh.value ? '需要匹配目标芯片的厂商适配器、工具链和校验环境。' : 'Requires a vendor adapter, toolchain, and validation environment for the target chip.'
    case 'tensorrt':
      return zh.value ? '需要 NVIDIA CUDA 设备及匹配的 TensorRT 转换和校验运行时。' : 'Requires an NVIDIA CUDA device and a matching TensorRT runtime for conversion and validation.'
    default:
      return '—'
  }
}
const unavailableTargetRequirement = computed(() => platformRequirement(unavailableTarget.value?.key))
const selectedTargetOptions = computed(() => props.conversionTargetOptions
  .filter(option => groupForTarget(option.value) === selectedTargetGroup.value)
  .map(option => {
    if (option.value === 'openvino-ir-fp32') return { ...option, label: zh.value ? '不压缩（FP32）' : 'Uncompressed (FP32)' }
    if (option.value === 'openvino-ir-int8') return { ...option, label: zh.value ? 'INT8 量化' : 'INT8 quantization' }
    if (option.value === 'openvino-ir-fp16') return { ...option, label: zh.value ? 'FP16 权重压缩' : 'FP16 weight compression' }
    return option
  }))
function selectTargetGroup(group: TargetGroup): void {
  platformRequirementsOpen.value = false
  const option = props.conversionTargetOptions.find(item => groupForTarget(item.value) === group)
  if (!option) {
    unavailableTargetKey.value = group
    return
  }
  unavailableTargetKey.value = null
  if (group !== selectedTargetGroup.value) emit('update:conversionTarget', option.value)
}
const targetForm = ref<HTMLFormElement | null>(null)
function openEnvironmentSelector(): void {
  const selector = targetForm.value?.querySelector<HTMLButtonElement>('#conversion-environment-select')
  selector?.focus()
  if (selector?.getAttribute('aria-expanded') === 'false') selector.click()
}
async function restoreAvailableTarget(): Promise<void> {
  unavailableTargetKey.value = null
  await nextTick()
  targetForm.value?.querySelector<HTMLInputElement>('input[name="conversion-target"]:checked')?.focus()
}
watch(() => props.conversionSourceModelVersionId, value => {
  unavailableTargetKey.value = null
  if (!value) step.value = 1
})
watch([int8Enabled, () => props.conversionSourceModelVersionId, () => props.tensorRtInt8 !== undefined], ([enabled, sourceId, configured]) => {
  if (!enabled || !sourceId || configured) return
  const shape = props.conversionSourceVersion?.metadata?.model_input_spec as { tensor_shape?: number[] } | undefined
  const supportedSize = (value: number | undefined) =>
    value !== undefined && Number.isInteger(value) && value >= 64 && value <= 1280 && value % 32 === 0 ? value : 640
  const height = supportedSize(shape?.tensor_shape?.[2])
  const width = supportedSize(shape?.tensor_shape?.[3])
  emit('update:tensorRtInt8', {
    input_profile: {
      min: [1, 3, Math.max(64, height - 64), Math.max(64, width - 64)],
      opt: [1, 3, height, width],
      max: [2, 3, Math.min(1280, height + 64), Math.min(1280, width + 64)],
    },
    workspace_gib: 4,
    int8_calibration: { dataset_export_id: '', sample_count: 1 },
    int8_validation: { dataset_export_id: '', sample_count: 1 },
  })
}, { immediate: true })
watch([openVinoInt8Enabled, () => props.conversionSourceModelVersionId, () => props.openVinoInt8 !== undefined], ([enabled, sourceId, configured]) => {
  if (!enabled || !sourceId || configured) return
  emit('update:openVinoInt8', {
    int8_calibration: { dataset_export_id: '', sample_count: 1 },
    int8_validation: { dataset_export_id: '', sample_count: 1 },
  })
}, { immediate: true })
watch(() => [step.value, props.projectId, props.selectedTaskType, props.conversionModelType, props.conversionSourceModelVersionId, props.conversionTarget, props.conversionRuntimeProfileId, props.onnxOpsetVersion, props.inputShapeMode, props.tensorRtInt8, props.openVinoInt8, preflightRetry.value] as const,
  async ([currentStep, projectId, taskType, modelType, sourceModelVersionId, target, runtimeProfileId, onnxOpsetVersion, inputShapeMode, tensorRtInt8, openVinoInt8], _previous, onCleanup) => {
    preflightStatus.value = 'idle'
    preflightError.value = ''
    if (currentStep !== 4 || !projectId || !modelType || !sourceModelVersionId) return
    const controller = new AbortController()
    onCleanup(() => controller.abort())
    preflightStatus.value = 'loading'
    try {
      const result = await previewModelConversion({ projectId, taskType, modelType, sourceModelVersionId, target, runtimeProfileId, onnxOpsetVersion, inputShapeMode, tensorRtInt8, openVinoInt8 }, controller.signal)
      if (onnxOpsetVersion !== undefined && result.onnx_opset_version !== onnxOpsetVersion) {
        throw new Error(zh.value ? '服务未确认所选 ONNX Opset，请刷新服务后重试。' : 'The service did not confirm the selected ONNX Opset. Reload the service and retry.')
      }
      const requestedMode = target === 'tensorrt-engine-int8' ? 'dynamic' : inputShapeMode
      if (requestedMode && result.input_shape_mode !== requestedMode) {
        throw new Error(zh.value ? '服务未确认动态输入配置。' : 'The service did not confirm the dynamic input settings.')
      }
      if (!controller.signal.aborted) preflightStatus.value = 'passed'
    } catch (error) {
      if (!controller.signal.aborted) {
        preflightStatus.value = 'failed'
        preflightError.value = error instanceof Error ? error.message : (zh.value ? '无法检查转换配置' : 'Unable to check conversion configuration')
      }
    }
  }, { flush: 'sync' })
function cancel(): void {
  unavailableTargetKey.value = null
  step.value = 1
  emit('cancel')
}
function updateWorkspace(event: Event): void {
  if (props.tensorRtInt8) {
    emit('update:tensorRtInt8', { ...props.tensorRtInt8, workspace_gib: (event.target as HTMLInputElement).valueAsNumber })
  }
}
function sampleSourceLabel(source: TensorRtInt8Settings['int8_calibration'], split: string): string {
  const item = props.datasetExports?.find(entry => entry.dataset_export_id === source.dataset_export_id)
  return item ? `${item.display_name || props.datasetExportLabels?.get(item.dataset_export_id) || item.dataset_export_id} · ${split} · ${source.sample_count}` : '—'
}
function submitStep(): void {
  if (!props.conversionSelectedModelSummary || !props.conversionSourceModelVersionId.trim()) return
  if (step.value === 2 && !canAdvanceTarget.value) return
  if (step.value < 4) { step.value++; return }
  if (preflightStatus.value === 'passed' && !props.loading && props.canWriteTasks && !props.conversionSubmitting && !props.lastConversionSubmission && !props.conversionSubmissionUncertain) emit('submit')
}

function getInputValue(event: Event): string {
  const input = event.target
  return input instanceof HTMLInputElement ? input.value : ''
}

function emitString(eventName: UpdateStringEvent, event: Event): void {
  const value = getInputValue(event)
  if (eventName === 'update:conversionRuntimeProfileId') {
    emit('update:conversionRuntimeProfileId', value)
    return
  }
  emit('update:conversionDisplayName', value)
}
</script>

<style scoped>
.conversion-parameters { padding:14px 16px; border:1px solid var(--am-border); border-radius:8px; }
.conversion-parameters h3 { margin:0; }
.conversion-parameters__grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px 24px; }
.conversion-parameters__grid .field { display:grid; grid-template-columns:minmax(100px,35%) minmax(0,1fr); align-items:center; }
.conversion-parameters__grid input { min-width:0; }
.conversion-parameters__grid input[readonly] { background:var(--am-surface-soft); color:var(--am-text); }
.conversion-parameters__hint { display:flex; align-items:center; gap:8px; margin:0; padding:10px 12px; border-radius:6px; background:var(--am-surface-soft); color:var(--am-text-muted); }
.conversion-parameters__advanced { border:1px solid var(--am-border); border-radius:6px; }
.conversion-parameters__advanced summary { padding:11px 12px; background:var(--am-surface-soft); cursor:pointer; font-weight:600; }
.conversion-parameters__advanced > div, .conversion-parameters__environment p { padding:10px 12px; margin:0; }
.conversion-input-summary h4 { margin:10px 12px 0; }
.conversion-input-summary .conversion-parameters__hint { margin:0 12px 12px; }
.conversion-opset-field { align-self:start; }
.conversion-opset-field > span { align-self:baseline; padding-top:10px; }
.conversion-opset-field__value { display:grid; gap:6px; min-width:0; }
.conversion-opset-support { min-width:0; color:var(--am-text-muted); }
.conversion-opset-support summary { cursor:pointer; }
.conversion-opset-support p { margin:6px 0 0; overflow-wrap:anywhere; }
@media (max-width:760px) { .conversion-parameters__grid { grid-template-columns:minmax(0,1fr); } }
.conversion-heading { display:flex; align-items:center; gap:14px; }
.conversion-heading { flex-wrap: wrap; }
.conversion-heading :deep(.submission-resolution--warning) { flex: 0 1 auto; margin: 0 0 0 auto; }
.conversion-heading h2 { margin:0; }
.conversion-steps { display:flex; align-items:center; list-style:none; padding:0; margin:20px 0; gap:12px; }
.conversion-steps li { display:flex; align-items:center; gap:10px; flex:1; color:var(--am-text-muted); }
.conversion-steps li:not(:last-child)::after { content:''; height:1px; flex:1; background:var(--am-border); }
.conversion-steps li.is-current, .conversion-steps li.is-complete { color:var(--am-text); }
.conversion-steps li span { display:grid; place-items:center; width:34px; height:34px; border:1px solid var(--am-border); border-radius:50%; flex:none; }
.conversion-steps li.is-current span { background:var(--am-brand-primary); border-color:var(--am-brand-primary); color:var(--am-brand-on-primary); }
.conversion-steps li.is-complete span { color:var(--am-brand-primary); border-color:var(--am-brand-primary); }
.conversion-steps li.is-complete::after { background:var(--am-brand-primary); }
.conversion-targets { display:grid; gap:10px; margin:0; padding:0; border:0; }
.conversion-source-summary { display:flex; align-items:center; gap:16px; flex-wrap:wrap; padding:16px; border:1px solid var(--am-border); border-radius:6px; background:var(--am-surface-soft); }
.conversion-source-summary span { color:var(--am-text-muted); overflow-wrap:anywhere; }
.conversion-targets legend { margin-bottom:10px; font-weight:600; }
.conversion-targets__grid { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:10px; }
.conversion-target-choice { grid-column:span 2; display:flex; align-items:center; justify-content:space-between; min-width:0; gap:4px; border:1px solid var(--am-border); border-radius:6px; }
.conversion-target-choice--platform { grid-column:span 3; }
.conversion-target { display:flex; flex:1; align-items:center; min-width:0; gap:10px; padding:12px 14px; cursor:pointer; }
.conversion-target svg, .conversion-target input, .conversion-target__logo { flex:none; }
.conversion-target__logo { width:22px; height:22px; object-fit:contain; }
.conversion-target__logo.is-arm-npu { width:52px; height:19px; }
html[data-theme='dark'] .conversion-target__logo:is(.is-coreml, .is-arm-npu) { filter:invert(1); }
.conversion-target__label { display:grid; min-width:0; gap:3px; }
.conversion-target__label small { color:var(--am-text-muted); }
.conversion-target-choice__requirements { flex:none; margin-inline-end:8px; }
.conversion-target-choice.is-unavailable:not(.conversion-target-choice--platform) { color:var(--am-text-muted); background:var(--am-surface-soft); }
.conversion-target-choice.is-selected { border-color:var(--am-brand-primary); background:var(--am-success-surface); }
.conversion-target input { accent-color:var(--am-brand-primary); }
.conversion-target-requirements { display:grid; gap:12px; min-width:0; padding:13px; border:1px solid var(--am-border); border-radius:6px; }
.conversion-target-requirements__warning { display:flex; align-items:center; gap:8px; padding:9px 11px; border:1px solid var(--am-warning-border); border-radius:6px; color:var(--am-warning-text); background:var(--am-warning-surface); }
.conversion-target-requirements__warning svg { flex:none; }
.conversion-target-requirements dl { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr) minmax(0,2fr); gap:8px 18px; margin:0; }
.conversion-target-requirements dt { color:var(--am-text-muted); }
.conversion-target-requirements dd { margin:4px 0 0; overflow-wrap:anywhere; }
.conversion-target-requirements > .ui-button { justify-self:start; }
.conversion-target-requirements h3 { margin:0; }
.conversion-platform-configuration { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
.conversion-platform-configuration__target, .conversion-platform-configuration__environment { display:grid; align-content:start; gap:10px; min-width:0; }
.conversion-platform-configuration .field { display:grid; grid-template-columns:minmax(76px,26%) minmax(0,1fr); align-items:center; }
.conversion-platform-configuration .field input { min-width:0; background:var(--am-surface-soft); color:var(--am-text); }
.conversion-platform-configuration__environment .conversion-target-requirements__warning { display:grid; }
.conversion-platform-configuration__environment [role=status] { display:flex; align-items:center; gap:8px; }
.conversion-platform-configuration__actions { display:flex; flex-wrap:wrap; gap:8px; }
.conversion-platform-requirement { margin:0; padding:10px 12px; border-radius:6px; background:var(--am-surface-soft); color:var(--am-text-muted); }
.conversion-platform-requirement summary { cursor:pointer; color:var(--am-text); font-weight:600; }
.conversion-platform-requirement p { margin:8px 0 0; }
@media (max-width:760px) {
  .conversion-targets__grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .conversion-target-choice { grid-column:auto; }
  .conversion-target-requirements dl, .conversion-platform-configuration { grid-template-columns:minmax(0,1fr); }
}
.conversion-actions { justify-content:space-between; }
.conversion-actions__end { display:flex; gap:10px; }
.conversion-action--blocked:disabled { background:var(--am-surface-muted); border-color:var(--am-border); color:var(--am-text-disabled); opacity:1; }
@media (max-height: 860px) {
  .conversion-actions--short-screen {
    position: sticky;
    bottom: 0;
    z-index: 1;
    padding-block: 10px;
    background: var(--am-surface-raised);
    border-top: 1px solid var(--am-border);
    box-shadow: 0 20px 0 var(--am-surface-raised);
  }
}
.conversion-review dl { display:grid; grid-template-columns:minmax(130px, 1fr) 3fr; gap:12px; margin:0; }
.conversion-review dt, .conversion-review p { color:var(--am-text-muted); }
.conversion-review dd { margin:0; overflow-wrap:anywhere; }
.review-profile { display:flex; flex-wrap:wrap; gap:6px 20px; }
.conversion-checks { display:grid; gap:10px; padding-top:12px; border-top:1px solid var(--am-border); }
.conversion-checks div { display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; }
.conversion-checks span { color:var(--am-text-muted); }
.model-ops-form,
.model-ops-form__grid {
  align-content: start;
}

.model-picker-field {
  gap: 10px;
}

.model-picker-field__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.model-picker-field__title > span:first-child {
  color: var(--am-text-muted);
  font-weight: 600;
}

.model-picker-field__title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.model-picker-summary {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface-soft);
}

.model-picker-summary.is-empty {
  min-height: 120px;
  align-content: center;
}

.model-picker-summary__top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.model-picker-summary__identity {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.model-picker-summary__identity strong,
.model-picker-summary__identity span,
.model-picker-summary.is-empty strong,
.model-picker-summary.is-empty span {
  overflow-wrap: anywhere;
}

.model-picker-summary__identity span,
.model-picker-summary.is-empty span,
.model-picker-summary__footer {
  color: var(--am-text-muted);
  font-size: 12px;
}

.model-picker-summary__chips {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.model-picker-chip {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  color: var(--am-neutral-text);
  background: var(--am-neutral-surface);
  font-size: 12px;
  font-weight: 700;
}

@media (max-width: 900px) {
  .model-picker-field__header {
    justify-content: flex-start;
  }

  .model-picker-summary__top {
    flex-direction: column;
  }
}
</style>
