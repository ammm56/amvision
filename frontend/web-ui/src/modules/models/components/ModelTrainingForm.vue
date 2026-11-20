<template>
  <form class="model-ops-form training-wizard" @submit.prevent="submitStep">
    <div class="training-wizard__heading">
      <Button type="button" variant="secondary" @click="$emit('cancel')">{{ locale.startsWith('zh') ? '返回' : 'Back' }}</Button>
      <h2>{{ t('modelOps.trainingTitle') }}</h2>
      <slot name="submission-warning" />
    </div>
    <ol class="training-wizard__steps" :aria-label="locale.startsWith('zh') ? '创建训练步骤' : 'Training steps'">
      <li v-for="(label, index) in stepLabels" :key="label" :class="{ 'is-current': step === index + 1, 'is-complete': step > index + 1 }" :aria-current="step === index + 1 ? 'step' : undefined">
        <span>{{ index + 1 }}</span><strong>{{ label }}</strong>
      </li>
    </ol>
    <div class="form-grid model-ops-form__grid">
      <section v-if="step === 1" class="training-parameter-section field field--wide">
        <h3>{{ locale.startsWith('zh') ? '任务信息' : 'Task information' }}</h3>
        <div class="form-grid training-parameter-grid">
          <label class="field"><span>{{ t('modelOps.fields.trainingDisplayName') }}</span><input :value="trainingDisplayName" maxlength="50" @input="emitString('update:trainingDisplayName', $event)" /></label>
          <label class="field"><span>{{ locale.startsWith('zh') ? '任务类型' : 'Task type' }}</span><SelectField :model-value="selectedTaskType" :options="taskTypeOptions" @update:model-value="$emit('change-task-type', normalizeSelectValue($event))" /></label>
          <label class="field field--wide"><span>{{ t('modelOps.fields.outputModelName') }}</span><input :value="outputModelName" maxlength="128" @input="emitString('update:outputModelName', $event)" /></label>
        </div>
      </section>
      <div v-if="step === 1" class="field field--wide model-picker-field training-parameter-section">
        <div class="model-picker-field__header">
          <div class="model-picker-field__title">
            <span>{{ t('modelOps.fields.trainingBaseModel') }}</span>
            <span class="model-picker-chip">{{ selectedTaskType }}</span>
          </div>
          <Button
            size="sm"
            variant="secondary"
            type="button"
            :disabled="loading || baseModelsCount === 0"
            @click="$emit('open-base-model-picker')"
          >
            {{ t('modelOps.actions.chooseBaseModel') }}
          </Button>
        </div>
        <div class="model-picker-summary" :class="{ 'is-empty': !trainingSelectedModelSummary }">
          <template v-if="trainingSelectedModelSummary">
            <div class="model-picker-summary__top">
              <div class="model-picker-summary__identity">
                <strong>{{ modelDisplayName(trainingSelectedModelSummary) }}</strong>
              </div>
              <div class="model-picker-summary__chips">
                <span class="model-picker-chip">
                  {{ t('modelOps.picker.modelScaleTitle') }} · {{ trainingSelectedModelSummary.model_scale }}
                </span>
              </div>
            </div>
          </template>
          <template v-else>
            <strong>{{ t('modelOps.baseModelEmptyTitle') }}</strong>
            <span>{{ t('modelOps.baseModelEmptyDescription') }}</span>
          </template>
        </div>
      </div>

      <div v-if="step === 2" class="field field--wide model-picker-field training-parameter-section">
        <div class="model-picker-field__header">
          <div class="model-picker-field__title">
            <span>{{ t('modelOps.fields.trainingDatasetExport') }}</span>
            <span class="model-picker-chip">{{ selectedTaskType }}</span>
          </div>
          <Button
            size="sm"
            variant="secondary"
            type="button"
            :disabled="loading || trainingDatasetExportsCount === 0"
            @click="$emit('open-training-dataset-export-picker')"
          >
            {{ selectedTrainingDatasetExport ? t('modelOps.actions.changeTrainingDatasetExport') : t('modelOps.actions.chooseTrainingDatasetExport') }}
          </Button>
        </div>
        <div class="model-picker-summary" :class="{ 'is-empty': !selectedTrainingDatasetExport }">
          <template v-if="selectedTrainingDatasetExport">
            <div class="model-picker-summary__top">
              <div class="model-picker-summary__identity">
                <strong>{{ selectedDatasetName }}<template v-if="selectedDatasetVersion"> · v{{ selectedDatasetVersion }}</template></strong>
                <span>{{ selectedTrainingDatasetExport.dataset_export_id }}</span>
              </div>
              <div class="model-picker-summary__chips">
                <span class="model-picker-chip">{{ selectedTrainingDatasetExport.task_type }}</span>
                <span class="model-picker-chip">{{ selectedTrainingDatasetExport.format_id }}</span>
              </div>
            </div>
            <div class="model-picker-summary__grid">
              <div class="model-picker-summary__item">
                <span>{{ t('datasetOps.fields.datasetId') }}</span>
                <strong>{{ selectedTrainingDatasetExport.dataset_id }}</strong>
              </div>
              <div class="model-picker-summary__item">
                <span>{{ t('datasetOps.columns.samples') }}</span>
                <strong>{{ selectedTrainingDatasetExport.sample_count }}</strong>
              </div>
              <div class="model-picker-summary__item">
                <span>{{ t('modelOps.columns.createdAt') }}</span>
                <strong>{{ formatSystemDateTime(selectedTrainingDatasetExport.created_at) }}</strong>
              </div>
              <div class="model-picker-summary__item">
                <span>{{ t('datasetOps.fields.categoryNames') }}</span>
                <strong>{{ selectedTrainingDatasetExport.category_names.join(', ') || t('common.noValue') }}</strong>
              </div>
            </div>
            <p v-if="selectedDatasetError" class="training-wizard__hint" role="status">{{ locale.startsWith('zh') ? '来源名称暂不可用，使用数据集 ID。' : 'Dataset name unavailable; showing its ID.' }} <button type="button" class="training-retry" @click="datasetSourceRetry++">{{ locale.startsWith('zh') ? '重试' : 'Retry' }}</button></p>
          </template>
          <template v-else>
            <strong>{{ t('modelOps.trainingDatasetExportEmptyTitle') }}</strong>
            <span>{{ t('modelOps.trainingDatasetExportEmptyDescription') }}</span>
          </template>
        </div>
        <template v-if="selectedTrainingDatasetExport">
          <p v-if="selectionError" role="alert" class="training-wizard__error">{{ selectionError }}</p>
          <section class="training-splits" :aria-label="locale.startsWith('zh') ? '导出数据划分' : 'Exported splits'">
            <div class="training-splits__heading"><h3>{{ locale.startsWith('zh') ? '数据集划分' : 'Dataset splits' }}</h3><span>{{ locale.startsWith('zh') ? '使用所选导出的固定划分。' : 'Uses the selected export’s fixed splits.' }}</span></div>
            <div class="training-splits__counts">
              <div v-for="split in exportSplits" :key="split.name"><span>{{ split.label }} ({{ split.name }})</span><strong>{{ split.value }}</strong></div>
            </div>
          </section>
          <h3>{{ locale.startsWith('zh') ? '类别信息' : 'Categories' }} ({{ selectedTrainingDatasetExport.category_names.length }})</h3>
          <div class="resource-table training-categories"><table><thead><tr><th>{{ locale.startsWith('zh') ? '类别 ID' : 'Category ID' }}</th><th>{{ locale.startsWith('zh') ? '类别名称' : 'Category name' }}</th></tr></thead><tbody><tr v-for="(name, index) in selectedTrainingDatasetExport.category_names" :key="index"><td>{{ index }}</td><td>{{ name }}</td></tr></tbody></table></div>
        </template>
      </div>

      <section v-if="step === 3" class="training-parameter-section field field--wide training-initialization">
        <h3>{{ locale.startsWith('zh') ? '初始化方式' : 'Initialization' }}</h3>
        <label class="training-choice"><input type="radio" name="training-initialization" :checked="!warmStartModelVersionId" @change="$emit('clear-training-warm-start')" /><span><strong>{{ locale.startsWith('zh') ? '从头训练' : 'Train from scratch' }}</strong><small>{{ locale.startsWith('zh') ? '使用随机初始化的模型权重。' : 'Start with randomly initialized weights.' }}</small></span></label>
        <div class="training-choice" :class="{ 'is-selected': !!warmStartModelVersionId }"><input type="radio" name="training-initialization" :aria-label="locale.startsWith('zh') ? '使用权重初始化' : 'Initialize from weights'" :disabled="loading || !trainingTaskSupportsWarmStart" :checked="!!warmStartModelVersionId" @click.prevent="$emit('open-training-weight-picker')" /><span><strong>{{ locale.startsWith('zh') ? '使用权重初始化' : 'Initialize from weights' }}</strong><small>{{ warmStartLabel || (locale.startsWith('zh') ? '选择可用的基础模型或项目版本。' : 'Choose available model weights.') }}</small><Button type="button" size="sm" variant="secondary" :disabled="loading || !trainingTaskSupportsWarmStart" @click="$emit('open-training-weight-picker')">{{ locale.startsWith('zh') ? '选择权重' : 'Choose weights' }}</Button></span></div>
        <p class="training-wizard__hint">{{ locale.startsWith('zh') ? '权重初始化不会恢复优化器状态或训练进度。' : 'Initializing weights does not resume optimizer state or training progress.' }}</p>
        <div class="training-choice"><span><strong>{{ locale.startsWith('zh') ? '恢复中断任务' : 'Resume an interrupted task' }}</strong><small>{{ locale.startsWith('zh') ? '暂停或失败的任务可在任务详情中检查 checkpoint 并恢复；已取消的任务不能恢复。' : 'Paused or failed tasks can be resumed from their detail page after checking the checkpoint; cancelled tasks cannot be resumed.' }}</small><Button type="button" size="sm" variant="secondary" @click="$emit('view-training-tasks')">{{ locale.startsWith('zh') ? '查看训练任务' : 'View training tasks' }}</Button></span></div>
      </section>

      <section v-if="step === 4" class="training-parameter-summary field--wide" :aria-label="locale.startsWith('zh') ? '训练配置摘要' : 'Training configuration summary'">
        <strong>{{ trainingSelectedModelSummary?.model_type && trainingSelectedModelSummary?.model_scale ? `${trainingSelectedModelSummary.model_type.toUpperCase()}-${trainingSelectedModelSummary.model_scale}` : trainingSelectedModelSummary?.model_name || '—' }}</strong>
        <span>{{ selectedTaskType }}</span>
        <span>{{ selectedDatasetName }}<template v-if="selectedDatasetVersion"> · v{{ selectedDatasetVersion }}</template></span>
        <span>{{ warmStartModelVersionId ? (locale.startsWith('zh') ? '使用权重初始化' : 'Initialize from weights') : (locale.startsWith('zh') ? '从头训练' : 'From scratch') }}</span>
      </section>
      <TrainingTaskRules v-if="step === 4 && selectedTaskType !== 'detection'" :task-type="selectedTaskType" :dataset-export="selectedTrainingDatasetExport" :workspace="selectedDatasetWorkspace">
        <template v-if="taskRuleField">
          <label class="field training-rule-parameter">
            <span>{{ localizeTrainingParameterLabel(taskRuleField) }}</span>
            <input
              :value="trainingModelParameterValues[taskRuleField.key] ?? ''"
              type="number"
              :min="taskRuleField.min"
              :max="taskRuleField.max"
              :step="taskRuleField.step"
              :disabled="taskRuleFieldDisabled"
              @input="emitModelParameterValue(taskRuleField.key, $event)"
              @blur="normalizeModelParameterNumber(taskRuleField, $event)"
            />
          </label>
          <p class="training-rule-hint" v-if="selectedTaskType === 'segmentation'">{{ locale.startsWith('zh') ? '掩码损失与边界框损失分别计算和配置。' : 'Mask and bounding-box loss are calculated and configured separately.' }}</p>
          <p class="training-rule-hint" v-else-if="!trainingAugmentationEnabled">{{ locale.startsWith('zh') ? '数据增强已关闭。可在高级参数中启用。' : 'Augmentation is off. Enable it in the advanced parameters.' }}</p>
        </template>
      </TrainingTaskRules>
      <div v-if="step === 4" class="training-standard-parameters field--wide">
        <section class="training-parameter-group">
          <h3>{{ locale.startsWith('zh') ? '基础参数' : 'Basic parameters' }}</h3>
          <div class="training-parameter-grid form-grid">
            <label class="field">
              <span>{{ t('modelOps.fields.outputModelName') }}</span>
              <input :value="outputModelName" maxlength="128" @input="emitString('update:outputModelName', $event)" />
            </label>
            <label class="field">
              <span>{{ t('modelOps.fields.maxEpochs') }}</span>
              <input :value="maxEpochs" type="number" min="1" step="1" @input="emitNumber('update:maxEpochs', $event)" />
            </label>
            <div class="field training-size">
              <span>{{ locale.startsWith('zh') ? '输入尺寸' : 'Input size' }}</span>
              <div>
                <input :aria-label="t('modelOps.fields.inputWidth')" :value="inputWidth" type="number" min="32" max="8192" step="32" @input="emitNumber('update:inputWidth', $event)" />
                <span aria-hidden="true">×</span>
                <input :aria-label="t('modelOps.fields.inputHeight')" :value="inputHeight" type="number" min="32" max="8192" step="32" @input="emitNumber('update:inputHeight', $event)" />
              </div>
            </div>
            <label class="field">
              <span>{{ t('modelOps.trainingParameters.device') }}</span>
              <SelectField
                :model-value="trainingDevice"
                :options="trainingDeviceOptions"
                @update:model-value="$emit('update:trainingDevice', normalizeSelectValue($event))"
              />
            </label>
          </div>
        </section>
        <section class="training-parameter-group">
          <h3>{{ locale.startsWith('zh') ? '批次与精度' : 'Batch and precision' }}</h3>
          <div class="training-parameter-grid form-grid">
            <label class="field">
              <span>{{ t('modelOps.fields.batchMode') }}</span>
              <SelectField
                :model-value="batchMode"
                :options="batchModeOptions"
                @update:model-value="$emit('update:batchMode', normalizeSelectValue($event) === 'fixed' ? 'fixed' : 'auto')"
              />
            </label>
            <label v-if="batchMode === 'fixed'" class="field">
              <span>{{ t('modelOps.fields.batchSize') }}</span>
              <input :value="batchSize" type="number" min="1" step="1" @input="emitNumber('update:batchSize', $event)" />
            </label>
            <label v-if="batchMode === 'auto'" class="field">
              <span>{{ t('modelOps.fields.batchTargetMemoryFraction') }}</span>
              <span class="training-percent">
                <input :value="Math.round(batchTargetMemoryFraction * 100)" type="number" min="10" max="95" step="5" @input="emitNumber('update:batchTargetMemoryFraction', $event, 0.01)" />
                <span aria-hidden="true">%</span>
              </span>
            </label>
            <label class="field">
              <span>{{ t('modelOps.fields.ampMode') }}</span>
              <SelectField
                :model-value="ampMode"
                :options="ampModeOptions"
                @update:model-value="$emit('update:ampMode', normalizeSelectValue($event))"
              />
            </label>
            <label v-if="ampMode !== 'disabled'" class="field">
              <span>{{ t('modelOps.fields.ampDtype') }}</span>
              <SelectField
                :model-value="ampDtype"
                :options="ampDtypeOptions"
                @update:model-value="$emit('update:ampDtype', normalizeSelectValue($event))"
              />
            </label>
            <label v-if="batchMode === 'auto'" class="field training-runtime-switch">
              <span>{{ t('modelOps.fields.batchRecoverOnOom') }}</span>
              <input
                type="checkbox"
                :checked="batchRecoverOnOom"
                @change="emitBoolean('update:batchRecoverOnOom', $event)"
              />
            </label>
            <label v-if="batchMode === 'auto' && batchRecoverOnOom" class="field">
              <span>{{ t('modelOps.fields.batchMaxOomRetries') }}</span>
              <input
                :value="batchMaxOomRetries"
                type="number"
                min="0"
                max="10"
                step="1"
                @input="emitNumber('update:batchMaxOomRetries', $event)"
              />
            </label>
          </div>
        </section>
        <section class="training-parameter-group">
          <h3>{{ locale.startsWith('zh') ? '保存设置' : 'Save settings' }}</h3>
          <div class="training-parameter-grid form-grid">
            <label class="field">
              <span>{{ t('modelOps.fields.evaluationInterval') }}</span>
              <input :value="evaluationInterval" type="number" min="1" step="1" @input="emitNumber('update:evaluationInterval', $event)" />
            </label>
            <label class="field">
              <span>{{ t('modelOps.fields.checkpointInterval') }}</span>
              <input :value="checkpointInterval" type="number" min="1" step="1" @input="emitNumber('update:checkpointInterval', $event)" />
            </label>
          </div>
        </section>
      </div>

      <details v-if="step === 4 && (advancedModelFields.length > 0 || trainingSupportsAugmentationToggle)" class="training-advanced field field--wide" :open="advancedOpen" @toggle="rememberAdvancedState">
      <summary>{{ locale.startsWith('zh') ? '高级参数（数据增强、优化器等）' : 'Advanced parameters' }}</summary>
      <section v-if="advancedModelFields.length > 0" class="training-parameter-section field field--wide">
        <div class="training-parameter-section__header">
          <div>
            <h3>{{ trainingModelParameterSectionTitle }}</h3>
          </div>
        </div>
        <div class="form-grid training-parameter-grid">
          <label
            v-for="field in advancedModelFields"
            :key="field.key"
            class="field"
            :class="{
              'field--wide': field.wide,
              'field--disabled': isModelFieldDisabled(field),
            }"
          >
            <span>{{ localizeTrainingParameterLabel(field) }}</span>
            <SelectField
              v-if="field.inputKind === 'select'"
              :model-value="trainingModelParameterValues[field.key] ?? ''"
              :options="localizeTrainingParameterOptions(field)"
              :disabled="isModelFieldDisabled(field)"
              @update:model-value="$emit('update:trainingModelParameterValue', field.key, normalizeSelectValue($event))"
            />
            <input
              v-else
              :value="trainingModelParameterValues[field.key] ?? ''"
              :type="field.inputKind"
              :min="field.min"
              :max="field.max"
              :step="field.step"
              :placeholder="field.placeholder"
              :disabled="isModelFieldDisabled(field)"
              @input="emitModelParameterValue(field.key, $event)"
              @blur="normalizeModelParameterNumber(field, $event)"
            />
          </label>
        </div>
      </section>

      <section
        v-if="trainingSupportsAugmentationToggle"
        class="training-parameter-section field field--wide"
      >
        <div class="training-parameter-section__header">
          <div>
            <h3>{{ t('modelOps.trainingParameters.augmentation') }}</h3>
          </div>
          <label class="training-augmentation-switch">
            <input
              type="checkbox"
              :checked="trainingAugmentationEnabled"
              @change="emitBoolean('update:trainingAugmentationEnabled', $event)"
            />
            <span>{{ trainingAugmentationEnabled ? t('modelOps.trainingParameters.augmentationEnabled') : t('modelOps.trainingParameters.augmentationDisabled') }}</span>
          </label>
        </div>
        <div
          class="form-grid training-parameter-grid"
          :class="{ 'training-parameter-grid--disabled': !trainingAugmentationEnabled }"
        >
          <label
            v-for="field in advancedAugmentationFields"
            :key="field.key"
            class="field"
            :class="{
              'field--wide': field.wide,
              'field--disabled': isAugmentationFieldDisabled(field),
            }"
          >
            <span>{{ localizeTrainingParameterLabel(field) }}</span>
            <SelectField
              v-if="field.inputKind === 'select'"
              :model-value="trainingModelParameterValues[field.key] ?? ''"
              :options="localizeTrainingParameterOptions(field)"
              :disabled="isAugmentationFieldDisabled(field)"
              @update:model-value="$emit('update:trainingModelParameterValue', field.key, normalizeSelectValue($event))"
            />
            <input
              v-else
              :value="trainingModelParameterValues[field.key] ?? ''"
              :type="field.inputKind"
              :min="field.min"
              :max="field.max"
              :step="field.step"
              :placeholder="field.placeholder"
              :disabled="isAugmentationFieldDisabled(field)"
              @input="emitModelParameterValue(field.key, $event)"
              @blur="normalizeModelParameterNumber(field, $event)"
            />
          </label>
        </div>
      </section>
      </details>
      <div v-if="step === 5" class="training-review field--wide">
        <TrainingPreflightResults
          :checks="previewChecks" :loading="previewLoading" :passed="previewPassed" :error="configurationError || previewError"
          :warm-start="!!warmStartModelVersionId" :editable="!trainingSubmitting && !trainingSubmissionUncertain && !lastTrainingSubmission"
          :zh="locale.startsWith('zh')" @retry="previewRetry++" @edit="step = $event"
        />
        <section v-for="(group, index) in reviewGroups" :key="group.step" class="training-review__card">
          <h3><component :is="group.icon" :size="18" aria-hidden="true" />{{ index + 1 }}. {{ group.title }}</h3>
          <Button v-if="!trainingSubmissionUncertain" variant="ghost" size="sm" type="button" :aria-label="`${locale.startsWith('zh') ? '编辑' : 'Edit'} ${group.title}`" :disabled="trainingSubmitting" @click="step = group.step">
            <Pencil :size="14" />{{ locale.startsWith('zh') ? '编辑' : 'Edit' }}
          </Button>
          <dl><div v-for="[label, value] in group.fields" :key="label"><dt>{{ label }}</dt><dd>{{ value }}</dd></div></dl>
          <p v-if="group.step === 1" class="training-review__initial">
            {{ locale.startsWith('zh') ? '初始化' : 'Initialization' }} · {{ warmStartModelVersionId ? (warmStartLabel || '—') : (locale.startsWith('zh') ? '从头训练' : 'From scratch') }}
          </p>
        </section>
      </div>
    </div>
    <p v-if="stepError" class="training-wizard__error" role="alert">{{ stepError }}</p>
    <slot name="submission-result" />
    <div class="training-wizard__actions">
      <Button v-if="step > 1" type="button" variant="secondary" :disabled="trainingSubmitting || trainingSubmissionUncertain" @click="step--; stepError = ''">{{ (locale.startsWith('zh') ? '上一步 · ' : 'Previous · ') + stepLabels[step - 2] }}</Button><span v-else></span>
      <div><Button type="button" variant="secondary" @click="$emit('cancel')">{{ trainingSubmissionUncertain ? (locale.startsWith('zh') ? '返回任务列表' : 'Back to tasks') : (locale.startsWith('zh') ? '取消' : 'Cancel') }}</Button>
      <Button
        variant="primary"
        type="submit"
        :disabled="!canWriteTasks || trainingSubmitting || !!lastTrainingSubmission || trainingSubmissionUncertain || (step === 2 && !!selectedTrainingDatasetExport && !!selectionError) || (step === 5 && (!!configurationError || (previewTraining && !previewPassed)))"
        :loading="trainingSubmitting"
      >
        <Play v-if="step === 5" :size="16" />
        {{ step < 5 ? (locale.startsWith('zh') ? '下一步 · ' : 'Next · ') + stepLabels[step] : trainingSubmitting ? t('modelOps.actions.submitting') : t('modelOps.actions.submitTraining') }}
      </Button></div>
    </div>
    <TaskSubmissionNotice
      v-if="lastTrainingSubmission"
      :title="t('modelOps.messages.trainingSubmitted')"
      :identifier="lastTrainingSubmission.task_id"
      :detail-to="`/models/${selectedTaskType}/training-tasks/${lastTrainingSubmission.task_id}`"
    />
  </form>
</template>

<script setup lang="ts">
import { Box, Database, Pencil, Play, Settings } from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import { getDatasetWorkspace, type DatasetWorkspace } from '@/modules/datasets/services/dataset-workspace.service'
import { ApiError } from '@/shared/api/error'
import type {
  ModelTaskType,
  ModelTrainingPreflightCheck,
  ModelTrainingTaskSubmissionResponse,
  PlatformBaseModelSummary,
} from '../services/model.service'
import type {
  TrainingParameterField,
  TrainingParameterFieldOption,
  TrainingParameterValues,
} from '../training-parameter-support'
import {
  isTrainingAugmentationParameterDisabled,
  isTrainingModelParameterDisabled,
  normalizeTrainingParameterNumber,
} from '../training-parameter-support'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import TaskSubmissionNotice from '@/modules/tasks/components/TaskSubmissionNotice.vue'
import TrainingTaskRules from './TrainingTaskRules.vue'
import TrainingPreflightResults from './TrainingPreflightResults.vue'
import { modelDisplayName } from '../model-display-name'

type SelectValue = string | number | boolean | null
type UpdateNumberEvent =
  | 'update:maxEpochs'
  | 'update:batchSize'
  | 'update:batchTargetMemoryFraction'
  | 'update:batchMaxOomRetries'
  | 'update:evaluationInterval'
  | 'update:checkpointInterval'
  | 'update:inputWidth'
  | 'update:inputHeight'
type UpdateStringEvent =
  | 'update:outputModelName'
  | 'update:trainingDisplayName'
type UpdateBooleanEvent =
  | 'update:trainingAugmentationEnabled'
  | 'update:batchRecoverOnOom'

const props = defineProps<{
  selectedTaskType: ModelTaskType
  taskTypeOptions: Array<{ label: string; value: string }>
  loading: boolean
  baseModelsCount: number
  trainingDatasetExportsCount: number
  trainingSelectedModelSummary: PlatformBaseModelSummary | null
  selectedTrainingDatasetExport: DatasetExportSummary | null
  trainingDeviceOptions: TrainingParameterFieldOption[]
  outputModelName: string
  maxEpochs: number
  batchMode: 'auto' | 'fixed'
  batchSize: number
  batchTargetMemoryFraction: number
  batchRecoverOnOom: boolean
  batchMaxOomRetries: number
  trainingDevice: string
  evaluationInterval: number
  ampMode: 'auto' | 'enabled' | 'disabled'
  ampDtype: 'auto' | 'fp16' | 'bf16'
  checkpointInterval: number
  inputWidth: number
  inputHeight: number
  trainingDisplayName: string
  warmStartModelVersionId: string
  warmStartLabel?: string
  trainingTaskSupportsWarmStart: boolean
  trainingModelParameterFields: TrainingParameterField[]
  trainingAugmentationParameterFields: TrainingParameterField[]
  trainingAugmentationEnabled: boolean
  trainingSupportsAugmentationToggle: boolean
  trainingModelParameterValues: TrainingParameterValues
  trainingModelParameterSectionTitle: string
  batchModeOptions: Array<{ label: string; value: string }>
  ampModeOptions: Array<{ label: string; value: string }>
  ampDtypeOptions: Array<{ label: string; value: string }>
  canWriteTasks: boolean
  trainingSubmitting: boolean
  previewTraining?: (signal: AbortSignal) => Promise<unknown>
  trainingSubmissionUncertain?: boolean
  configurationError?: string | null
  selectionError?: string | null
  lastTrainingSubmission: ModelTrainingTaskSubmissionResponse | null
}>()

const emit = defineEmits<{
  'view-training-tasks': []
  submit: []
  cancel: []
  'change-task-type': [value: string]
  'open-base-model-picker': []
  'open-training-weight-picker': []
  'open-training-dataset-export-picker': []
  'clear-training-warm-start': []
  'update:outputModelName': [value: string]
  'dataset-name-resolved': [name: string]
  'update:maxEpochs': [value: number]
  'update:batchMode': [value: 'auto' | 'fixed']
  'update:batchSize': [value: number]
  'update:batchTargetMemoryFraction': [value: number]
  'update:batchRecoverOnOom': [value: boolean]
  'update:batchMaxOomRetries': [value: number]
  'update:trainingDevice': [value: string]
  'update:evaluationInterval': [value: number]
  'update:ampMode': [value: string]
  'update:ampDtype': [value: string]
  'update:checkpointInterval': [value: number]
  'update:inputWidth': [value: number]
  'update:inputHeight': [value: number]
  'update:trainingDisplayName': [value: string]
  'update:trainingModelParameterValue': [key: string, value: string]
  'update:trainingAugmentationEnabled': [value: boolean]
}>()

const { t, locale } = useI18n()
const taskRuleField = computed(() => {
  if (props.selectedTaskType === 'segmentation') return props.trainingModelParameterFields.find(field => field.key === 'mask_loss_weight')
  if (props.selectedTaskType === 'obb') return props.trainingAugmentationParameterFields.find(field => field.key === 'degrees')
  return undefined
})
const taskRuleFieldDisabled = computed(() => {
  const field = taskRuleField.value
  if (!field) return false
  return props.selectedTaskType === 'obb' ? isAugmentationFieldDisabled(field) : isModelFieldDisabled(field)
})
const advancedModelFields = computed(() => props.trainingModelParameterFields.filter(field => field !== taskRuleField.value))
const advancedAugmentationFields = computed(() => props.trainingAugmentationParameterFields.filter(field => field !== taskRuleField.value))
const step = ref(1)
const advancedOpen = ref(false)
function rememberAdvancedState(event: Event): void {
  advancedOpen.value = (event.currentTarget as HTMLDetailsElement).open
}
const stepError = ref('')
const previewLoading = ref(false)
const previewError = ref('')
const previewPassed = ref(false)
const previewRetry = ref(0)
const previewChecks = ref<ModelTrainingPreflightCheck[]>([])

function readPreviewChecks(value: unknown): ModelTrainingPreflightCheck[] {
  if (!value || typeof value !== 'object' || !('checks' in value) || !Array.isArray(value.checks)) return []
  return value.checks.filter((item): item is ModelTrainingPreflightCheck =>
    item && ['dataset_export', 'initialization', 'environment', 'output_model'].includes(item.check)
      && ['passed', 'failed', 'skipped', 'deferred'].includes(item.status)
      && (item.message === undefined || typeof item.message === 'string')
      && (item.missing_files === undefined || (Array.isArray(item.missing_files) && item.missing_files.every((name: unknown) => typeof name === 'string'))),
  )
}

watch(() => [
  step.value, props.configurationError, previewRetry.value, props.selectedTaskType,
  props.trainingSelectedModelSummary?.model_id, props.selectedTrainingDatasetExport?.dataset_export_id,
  props.selectedTrainingDatasetExport?.manifest_object_key, props.warmStartModelVersionId, props.outputModelName,
] as const, async ([currentStep, error], _previous, onCleanup) => {
  previewPassed.value = false
  previewError.value = ''
  previewChecks.value = []
  previewLoading.value = false
  if (currentStep !== 5 || error || !props.previewTraining) return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  previewLoading.value = true
  try {
    const result = await props.previewTraining(controller.signal)
    if (controller.signal.aborted) return
    previewChecks.value = readPreviewChecks(result)
    previewPassed.value = !previewChecks.value.some(check => check.status === 'failed')
    if (!previewPassed.value) previewError.value = locale.value.startsWith('zh') ? '训练检查失败' : 'Training check failed'
  } catch (cause) {
    if (controller.signal.aborted) return
    if (cause instanceof ApiError) previewChecks.value = readPreviewChecks(cause.details)
    previewError.value = cause instanceof Error ? cause.message : (locale.value.startsWith('zh') ? '训练检查失败' : 'Training check failed')
  } finally {
    if (!controller.signal.aborted) previewLoading.value = false
  }
})
const selectedDatasetWorkspace = ref<DatasetWorkspace | null>(null)
const selectedDatasetError = ref(false)
const datasetSourceRetry = ref(0)
const selectedDatasetName = computed(() => selectedDatasetWorkspace.value?.dataset?.display_name || props.selectedTrainingDatasetExport?.display_name || props.selectedTrainingDatasetExport?.dataset_id || props.selectedTrainingDatasetExport?.dataset_export_id || '—')
const selectedDatasetVersion = computed(() => selectedDatasetWorkspace.value?.version_number || props.selectedTrainingDatasetExport?.version_number || null)
watch(() => selectedDatasetWorkspace.value?.dataset?.display_name || props.selectedTrainingDatasetExport?.display_name || '', name => {
  emit('dataset-name-resolved', name)
}, { immediate: true })
watch(() => [props.selectedTrainingDatasetExport?.dataset_id, props.selectedTrainingDatasetExport?.dataset_version_id, datasetSourceRetry.value] as const,
  async ([datasetId, versionId], _previous, onCleanup) => {
    selectedDatasetWorkspace.value = null
    selectedDatasetError.value = false
    if (!datasetId || !versionId) return
    const controller = new AbortController()
    onCleanup(() => controller.abort())
    try {
      const workspace = await getDatasetWorkspace(datasetId, versionId, controller.signal)
      if (!controller.signal.aborted) {
        if (workspace.dataset_id === datasetId && workspace.dataset_version_id === versionId) selectedDatasetWorkspace.value = workspace
        else selectedDatasetError.value = true
      }
    } catch { if (!controller.signal.aborted) selectedDatasetError.value = true }
  }, { immediate: true })
const stepLabels = computed(() => locale.value.startsWith('zh')
  ? ['任务与模型', '数据', '初始化', '参数', '检查']
  : ['Task and model', 'Data', 'Initialization', 'Parameters', 'Review'])
const exportSplits = computed(() => {
  const data = props.selectedTrainingDatasetExport
  const names = Array.isArray(data?.split_names) ? data.split_names : []
  const counts = data?.metadata?.split_counts
  const bySplit = counts && typeof counts === 'object' && !Array.isArray(counts) ? counts as Record<string, unknown> : {}
  const chinese = locale.value.startsWith('zh')
  return (['train', 'val', 'test'] as const).map((name, index) => {
    const count = bySplit[name]
    const value = typeof count === 'number' && Number.isSafeInteger(count) && count >= 0
      ? count.toLocaleString() : names.length && !names.includes(name) ? (chinese ? '未包含' : 'Not included') : '—'
    return { name, value, label: (chinese ? ['训练集', '验证集', '测试集'] : ['Training', 'Validation', 'Test'])[index] }
  })
})
const reviewGroups = computed(() => {
  const chinese = locale.value.startsWith('zh')
  const text = (zh: string, en: string) => chinese ? zh : en
  const model = props.trainingSelectedModelSummary
  const version = selectedDatasetVersion.value ? ` · v${selectedDatasetVersion.value}` : ''
  const device = props.trainingDeviceOptions.find(option => option.value === props.trainingDevice)?.label
  return [
    { step: 1, icon: Box, title: stepLabels.value[0], fields: [
      [text('训练任务名称', 'Task name'), props.trainingDisplayName || '—'],
      [text('基础模型', 'Base model'), model?.model_type ? `${model.model_type.toUpperCase()}-${model.model_scale}` : model?.model_name || '—'],
      [text('任务类型', 'Task type'), props.selectedTaskType],
      [text('输出到', 'Output model'), props.outputModelName],
    ] },
    { step: 2, icon: Database, title: stepLabels.value[1], fields: [
      [text('数据集', 'Dataset'), `${selectedDatasetName.value}${version}`],
      [text('数据划分', 'Splits'), exportSplits.value.map(split => `${split.name} ${split.value}`).join(' / ')],
      [text('类别数量', 'Classes'), props.selectedTrainingDatasetExport?.category_names?.length ?? '—'],
      [text('导出格式', 'Export format'), props.selectedTrainingDatasetExport?.format_id || '—'],
    ] },
    { step: 4, icon: Settings, title: stepLabels.value[3], fields: [
      [text('最大轮数', 'Epochs'), props.maxEpochs],
      [text('输入尺寸', 'Input size'), `${props.inputWidth} × ${props.inputHeight}`],
      [text('训练设备', 'Device'), device || props.trainingDevice || 'Auto'],
      [text('批大小策略', 'Batch size'), props.batchMode === 'auto' ? `AutoBatch · ${Math.round(props.batchTargetMemoryFraction * 100)}%` : props.batchSize],
      ['AMP', props.ampMode === 'disabled' ? text('关闭', 'Off') : props.ampDtype],
      [text('保存间隔（轮）', 'Checkpoint interval'), props.checkpointInterval],
    ] },
  ]
})

function submitStep(): void {
  stepError.value = ''
  if (step.value === 1 && (!props.outputModelName.trim() || !props.trainingSelectedModelSummary)) {
    stepError.value = locale.value.startsWith('zh') ? '请填写输出模型名称并选择模型。' : 'Enter an output model name and choose a model.'
    return
  }
  if (step.value === 2 && !props.selectedTrainingDatasetExport) {
    stepError.value = locale.value.startsWith('zh') ? '请选择用于训练的数据集导出。' : 'Choose a dataset export for training.'
    return
  }
  if (step.value === 2 && props.selectionError) {
    return
  }
  if (step.value === 4 && props.configurationError) {
    stepError.value = props.configurationError
    return
  }
  if (step.value < 5) {
    step.value += 1
  } else if (!props.previewTraining || previewPassed.value) {
    emit('submit')
  }
}

function humanizeParameterToken(value: string): string {
  return value
    .replace(/_/g, ' ')
    .replace(/\b(hsv|nms|dfl|ema|giou|ce|cpu|gpu|rfdetr)\b/gi, (token) => token.toUpperCase())
    .replace(/^./, (character) => character.toUpperCase())
}

function localizeTrainingParameterLabel(field: TrainingParameterField): string {
  return locale.value === 'zh-CN' ? field.label : humanizeParameterToken(field.key)
}

function localizeTrainingParameterOptions(field: TrainingParameterField): TrainingParameterFieldOption[] {
  if (locale.value === 'zh-CN') return field.options ?? []
  const canonicalOptionLabels: Record<string, Record<string, string>> = {
    optimizer: {
      auto: 'Auto',
      musgd: 'MuSGD',
      sgd: 'SGD',
      adamw: 'AdamW',
      adam: 'Adam',
      nadam: 'NAdam',
      radam: 'RAdam',
      rmsprop: 'RMSProp',
    },
    lr_scheduler: {
      step: 'Step',
      cosine: 'Cosine',
    },
  }
  return (field.options ?? []).map((option) => {
    if (option.value === 'true') return { ...option, label: t('modelOps.trainingParameters.enabled') }
    if (field.key === 'crop_mode' && option.value === 'none') {
      return { ...option, label: 'Center Crop' }
    }
    if (option.value === 'false' || option.value === 'none') return { ...option, label: t('modelOps.trainingParameters.disabled') }
    const canonicalLabel = canonicalOptionLabels[field.key]?.[option.value]
    if (canonicalLabel) return { ...option, label: canonicalLabel }
    return { ...option, label: humanizeParameterToken(option.value) }
  })
}

function isAugmentationFieldDisabled(field: TrainingParameterField): boolean {
  return isTrainingAugmentationParameterDisabled(
    field,
    props.trainingModelParameterValues,
    props.trainingAugmentationEnabled,
  )
}

function isModelFieldDisabled(field: TrainingParameterField): boolean {
  return isTrainingModelParameterDisabled(field, props.trainingModelParameterValues)
}

function normalizeSelectValue(value: SelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}

function getInputValue(event: Event): string {
  const input = event.target
  return input instanceof HTMLInputElement ? input.value : ''
}

function emitString(eventName: UpdateStringEvent, event: Event): void {
  const value = getInputValue(event)
  if (eventName === 'update:outputModelName') {
    emit('update:outputModelName', value)
    return
  }
  emit('update:trainingDisplayName', value)
}

function emitNumber(eventName: UpdateNumberEvent, event: Event, multiplier = 1): void {
  const value = Number(getInputValue(event))
  const normalizedValue = Number.isFinite(value) ? value * multiplier : 0
  if (eventName === 'update:maxEpochs') {
    emit('update:maxEpochs', normalizedValue)
    return
  }
  if (eventName === 'update:batchSize') {
    emit('update:batchSize', normalizedValue)
    return
  }
  if (eventName === 'update:batchTargetMemoryFraction') {
    emit('update:batchTargetMemoryFraction', normalizedValue)
    return
  }
  if (eventName === 'update:batchMaxOomRetries') {
    emit('update:batchMaxOomRetries', normalizedValue)
    return
  }
  if (eventName === 'update:evaluationInterval') {
    emit('update:evaluationInterval', normalizedValue)
    return
  }
  if (eventName === 'update:checkpointInterval') {
    emit('update:checkpointInterval', normalizedValue)
    return
  }
  if (eventName === 'update:inputWidth') {
    emit('update:inputWidth', normalizedValue)
    return
  }
  emit('update:inputHeight', normalizedValue)
}

function emitBoolean(eventName: UpdateBooleanEvent, event: Event): void {
  const input = event.target
  const value = input instanceof HTMLInputElement && input.checked
  if (eventName === 'update:batchRecoverOnOom') {
    emit('update:batchRecoverOnOom', value)
    return
  }
  emit('update:trainingAugmentationEnabled', value)
}

function emitModelParameterValue(key: string, event: Event): void {
  emit('update:trainingModelParameterValue', key, getInputValue(event))
}

function normalizeModelParameterNumber(
  field: TrainingParameterField,
  event: Event,
): void {
  const normalizedValue = normalizeTrainingParameterNumber(
    field,
    getInputValue(event),
  )
  emit('update:trainingModelParameterValue', field.key, normalizedValue)
}
</script>

<style scoped>
.training-retry { border:0; padding:0; background:none; color:var(--am-brand-primary); cursor:pointer; font:inherit; }
.training-splits { display:grid; gap:14px; padding:16px; border:1px solid var(--am-border); border-radius:6px; }
.training-splits__heading { display:flex; align-items:baseline; flex-wrap:wrap; gap:12px; }
.training-splits__heading h3 { margin:0; }
.training-splits__heading span, .training-splits__counts span { color:var(--am-text-muted); }
.training-splits__counts { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.training-splits__counts div { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:8px; padding-right:12px; }
.training-splits__counts div:not(:last-child) { border-right:1px solid var(--am-border); }
@media (max-width: 600px) { .training-splits__counts { grid-template-columns:1fr; } .training-splits__counts div:not(:last-child) { border-right:0; } }
.training-wizard { display: grid; gap: 18px; min-width: 0; }
.training-wizard__heading { display: flex; align-items: center; gap: 12px; }
.training-wizard__heading { flex-wrap: wrap; }
.training-wizard__heading :deep(.submission-resolution--warning) { flex: 0 1 auto; margin: 0 0 0 auto; }
.training-wizard__heading h2 { margin: 0; }
.training-wizard__steps { display: flex; align-items: center; padding: 0; margin: 0; list-style: none; }
.training-wizard__steps li { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; color: var(--am-text-muted); }
.training-wizard__steps li:not(:last-child)::after { content: ''; height: 1px; background: var(--am-border); flex: 1; margin: 0 12px; }
.training-wizard__steps li span { display: grid; place-items: center; width: 36px; height: 36px; flex: none; border: 1px solid var(--am-border); border-radius: 50%; background: var(--am-surface); }
.training-wizard__steps li strong { white-space: nowrap; font-weight: 500; }
.training-wizard__steps li.is-current, .training-wizard__steps li.is-complete { color: var(--am-text); }
.training-wizard__steps li.is-current span { color: white; background: var(--am-action-primary); border-color: var(--am-action-primary); }
.training-wizard__actions { position: sticky; bottom: 0; z-index: 1; display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 10px 0; background: var(--am-surface-page, var(--am-surface)); }
.training-wizard__actions > div { display: flex; gap: 12px; }
.training-wizard__hint { color: var(--am-text-muted); margin: 0; }
.training-wizard__error { color: var(--am-danger, #d62d2d); margin: 0; }
.training-parameter-summary { display:flex; align-items:center; flex-wrap:wrap; gap:8px 16px; min-width:0; padding:12px 16px; border:1px solid var(--am-border); border-radius:8px; background:var(--am-surface-soft); overflow-wrap:anywhere; }
.training-parameter-summary > *:not(:first-child) { padding-inline-start:16px; border-inline-start:1px solid var(--am-border); }
.training-rule-parameter.field { display:grid; grid-template-columns:minmax(104px, 36%) minmax(0, 1fr); align-items:center; gap:8px; min-width:0; width:calc((100% - 24px) / 2); }
.training-rule-parameter input { min-width:0; width:100%; }
@media (max-width: 760px) { .training-rule-parameter.field { width:100%; } }
.training-rule-hint { margin:0; color:var(--am-text-muted); }
.training-standard-parameters { min-width:0; border:1px solid var(--am-border); border-radius:8px; background:var(--am-surface); }
.training-parameter-group { padding:12px 16px; }
.training-parameter-group + .training-parameter-group { border-top:1px solid var(--am-border); }
.training-parameter-group h3 { margin:0 0 10px; font-size:15px; }
.training-parameter-group .form-grid { grid-template-columns:repeat(2, minmax(0, 1fr)); gap:8px 24px; }
.training-parameter-group .field { display:grid; grid-template-columns:minmax(124px, 39%) minmax(0, 1fr); align-items:center; gap:8px; min-width:0; }
.training-parameter-group input:not([type='checkbox']) { width:100%; min-width:0; }
.training-parameter-group .training-runtime-switch input { justify-self:start; }
.training-size > div, .training-percent { display:flex; align-items:center; gap:8px; min-width:0; }
@media (max-width: 760px) { .training-parameter-group .form-grid { grid-template-columns:minmax(0, 1fr); } }
.training-choice { display: flex; gap: 14px; align-items: flex-start; padding: 16px; border: 1px solid var(--am-border); border-radius: 8px; }
.training-choice.is-selected { border-color: var(--am-action-primary); }
.training-choice input { accent-color: var(--am-action-primary); margin-top: 4px; }
.training-choice span { display: grid; justify-items: start; gap: 8px; min-width: 0; overflow-wrap: anywhere; }
.training-choice small { color: var(--am-text-muted); }
.training-review { display:grid; gap:10px; min-width:0; }
.training-review__card { display:grid; grid-template-columns:1fr auto; align-items:center; padding:11px 14px; gap:10px; border:1px solid var(--am-border); border-radius:8px; background:var(--am-surface); min-width:0; }
.training-review__card h3 { display:flex; align-items:center; gap:8px; margin:0; font-size:15px; }
.training-review dl { grid-column:1 / -1; display:grid; grid-template-columns:repeat(auto-fit,minmax(136px,1fr)); gap:10px; margin:0; }
.training-review dl > div { min-width:0; padding:0 10px; border-inline-start:1px solid var(--am-border); }
.training-review dt { color: var(--am-text-muted); }
.training-review dd { margin: 6px 0 0; overflow-wrap: anywhere; }
.training-review__initial { grid-column:1 / -1; margin:0; }
.training-review__initial { padding:9px 10px; border-radius:5px; background:var(--am-surface-soft); overflow-wrap:anywhere; }
.training-advanced { border: 1px solid var(--am-border); border-radius: 8px; background: var(--am-surface); }
.training-advanced summary { padding: 14px; cursor: pointer; font-weight: 600; }
.training-advanced .training-parameter-section { border: 0; border-top: 1px solid var(--am-border); border-radius: 0; }
.model-ops-form,
.model-ops-form__grid {
  align-content: start;
}

.training-parameter-section {
  display: grid;
  gap: 14px;
  padding: 14px;
  border: 1px solid var(--am-border);
  border-radius: 12px;
  background: var(--am-surface);
}

.training-parameter-section__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.training-parameter-section__header h3 {
  margin: 0;
  font-size: 18px;
}

.training-parameter-section__description {
  margin: 0;
  color: var(--am-text-muted);
  font-size: 13px;
  line-height: 1.6;
}

.training-parameter-grid {
  align-content: start;
}

.training-parameter-grid--disabled {
  opacity: 0.72;
}

.field--disabled {
  opacity: 0.58;
}

.training-augmentation-switch {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid var(--am-border);
  border-radius: 999px;
  background: var(--am-surface-soft);
  color: var(--am-text);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.training-augmentation-switch input {
  width: 16px;
  height: 16px;
  accent-color: var(--am-action-primary);
}

.training-runtime-switch {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
}

.training-runtime-switch input {
  width: 18px;
  height: 18px;
  min-height: 18px;
  max-height: 18px;
  margin: 0;
  accent-color: var(--am-action-primary);
  cursor: pointer;
}

.training-inline-summary {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface-soft);
}

.training-inline-summary.is-empty {
  background: var(--am-surface);
}

.training-inline-summary strong {
  overflow-wrap: anywhere;
}

.training-inline-summary span {
  color: var(--am-text-muted);
  font-size: 12px;
}

.training-inline-summary__actions {
  display: flex;
  justify-content: flex-end;
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

.model-picker-summary__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.model-picker-summary__item {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface);
}

.model-picker-summary__item span {
  color: var(--am-text-muted);
  font-size: 12px;
  font-weight: 600;
}

.model-picker-summary__item strong {
  overflow-wrap: anywhere;
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
  .training-parameter-section__header {
    flex-direction: column;
    align-items: flex-start;
  }

  .model-picker-field__header {
    justify-content: flex-start;
  }

  .model-picker-summary__top {
    flex-direction: column;
  }

  .model-picker-summary__grid {
    grid-template-columns: 1fr;
  }
}
</style>
