<template>
  <section class="deployment-wizard-shell">
    <nav class="deployment-wizard__breadcrumb" :aria-label="t('deploymentWorkspace.wizard.title')">
      <button type="button" class="deployment-wizard__crumb-link" @click="emit('cancel')">
        {{ t('deploymentWorkspace.actions.backToList') }}
      </button>
      <ChevronRight :size="14" aria-hidden="true" />
      <span>{{ t('deploymentWorkspace.wizard.title') }}</span>
    </nav>

    <ol class="deployment-wizard__stepper" :aria-label="t('deploymentWorkspace.wizard.title')">
      <li
        v-for="(item, index) in stepLabels"
        :key="item"
        class="deployment-wizard__step"
        :class="{ 'is-current': step === index + 1, 'is-complete': step > index + 1 }"
        :aria-current="step === index + 1 ? 'step' : undefined"
      >
        <span class="deployment-wizard__step-circle">
          <Check v-if="step > index + 1" :size="14" aria-hidden="true" />
          <template v-else>{{ index + 1 }}</template>
        </span>
        <strong>{{ item }}</strong>
        <span v-if="index < stepLabels.length - 1" class="deployment-wizard__step-line" :class="{ 'is-complete': step > index + 1 }" aria-hidden="true" />
      </li>
    </ol>

    <!-- Step 1: Select Source -->
    <div v-if="step === 1" class="deployment-card deployment-wizard__card">
      <header class="deployment-wizard__card-header">
        <strong>{{ t('deploymentWorkspace.wizard.steps.source') }}</strong>
        <Button
          type="button"
          variant="secondary"
          data-deployment-action="browse-source-picker"
          :disabled="sourceModelsLoading"
          :loading="sourceModelsLoading"
          @click="emit('open-source-picker')"
        >
          {{ t('deploymentWorkspace.actions.browseByTask') }}
        </Button>
      </header>

      <div class="deployment-wizard__card-body">
        <div class="deployment-wizard__source-row">
          <label class="field">
            <span>{{ t('deploymentWorkspace.wizard.fields.deploymentName') }} <em class="req">*</em></span>
            <input
              :value="displayName"
              maxlength="128"
              :placeholder="selectedDeploymentSource?.modelName || ''"
              @input="emit('update:displayName', ($event.target as HTMLInputElement).value)"
            />
          </label>
          <div class="field">
            <span>{{ t('deploymentWorkspace.wizard.fields.model') }} <em class="req">*</em></span>
            <SelectField
              :aria-label="t('deploymentWorkspace.wizard.fields.model')"
              :model-value="wizardSelectedModelId"
              :options="modelDropdownOptions"
              :disabled="wizardModelsLoading || modelDropdownOptions.length === 0"
              @update:model-value="emit('select-wizard-model', String($event ?? ''))"
            />
          </div>
          <div class="field">
            <span>{{ t('deploymentWorkspace.wizard.fields.version') }} <em class="req">*</em></span>
            <SelectField
              :aria-label="t('deploymentWorkspace.wizard.fields.version')"
              :model-value="wizardSelectedVersionId"
              :options="versionDropdownOptions"
              :disabled="wizardDetailLoading || versionDropdownOptions.length === 0"
              @update:model-value="wizardSelectedVersionId = String($event ?? '')"
            />
          </div>
        </div>

        <section class="deployment-wizard__group">
          <h3>{{ t('deploymentWorkspace.wizard.fields.selectBuildTitle') }}</h3>
          <LoadingPanel v-if="wizardModelsLoading || wizardDetailLoading" compact :title="t('deploymentOps.sourcePicker.detailLoading')" />
          <div v-else-if="versionBuilds.length" class="wizard-build-table">
            <table>
              <colgroup>
                <col style="width: 24%" />
                <col style="width: 24%" />
                <col style="width: 26%" />
                <col style="width: 16%" />
                <col style="width: 10%" />
              </colgroup>
              <thead>
                <tr>
                  <th :title="t('deploymentWorkspace.wizard.fields.buildFormat')">{{ t('deploymentWorkspace.wizard.fields.buildFormat') }}</th>
                  <th :title="t('deploymentWorkspace.wizard.fields.precisionOrOpt')">{{ t('deploymentWorkspace.wizard.fields.precisionOrOpt') }}</th>
                  <th :title="t('deploymentWorkspace.wizard.fields.artifactFile')">{{ t('deploymentWorkspace.wizard.fields.artifactFile') }}</th>
                  <th :title="t('deploymentWorkspace.wizard.fields.checkState')">{{ t('deploymentWorkspace.wizard.fields.checkState') }}</th>
                  <th class="wizard-radio-col" :title="t('deploymentWorkspace.wizard.fields.choose')">{{ t('deploymentWorkspace.wizard.fields.choose') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="build in versionBuilds"
                  :key="build.model_build_id"
                  :class="{
                    'is-selected': selectedDeploymentSource?.modelBuildId === build.model_build_id,
                    'is-disabled': !isWizardBuildSelectable(build),
                  }"
                  @click="selectWizardBuild(build)"
                >
                  <td :title="conversionFormatName(build.build_format, zh)">
                    <span class="wizard-build-format-cell">
                      <DeploymentRuntimeBadge
                        :backend="build.runtime_backend"
                        :precision="build.runtime_precision"
                        :build-format="build.build_format"
                        backend-only
                      />
                      <strong class="wizard-ellipsis">{{ conversionFormatName(build.build_format, zh) }}</strong>
                    </span>
                  </td>
                  <td :title="`${build.runtime_precision.toUpperCase()} · ${formatDeploymentBackend(build.runtime_backend)}`">
                    {{ build.runtime_precision.toUpperCase() }} · {{ formatDeploymentBackend(build.runtime_backend) }}
                  </td>
                  <td :title="artifactFileLabel(build)"><code>{{ artifactFileLabel(build) }}</code></td>
                  <td :title="buildReason(build) || t('deploymentWorkspace.wizard.fields.buildVerified')">
                    <span v-if="buildReason(build)" class="wizard-check-dot is-warning">● {{ buildReason(build) }}</span>
                    <span v-else class="wizard-check-dot is-success">● {{ t('deploymentWorkspace.wizard.fields.buildVerified') }}</span>
                  </td>
                  <td class="wizard-radio-col">
                    <button
                      type="button"
                      class="wizard-radio"
                      :class="{ 'is-checked': selectedDeploymentSource?.modelBuildId === build.model_build_id }"
                      :disabled="!isWizardBuildSelectable(build)"
                      :aria-label="`${conversionFormatName(build.build_format, zh)} ${build.runtime_precision}`"
                      :aria-checked="selectedDeploymentSource?.modelBuildId === build.model_build_id"
                      role="radio"
                      @click.stop="selectWizardBuild(build)"
                    />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="source-empty-card">
            <strong>{{ t('deploymentOps.source.emptyTitle') }}</strong>
            <span>{{ t('deploymentOps.source.emptyDescription') }}</span>
          </div>
        </section>

        <section v-if="selectedDeploymentSource" class="deployment-wizard__group">
          <h3>{{ t('deploymentWorkspace.wizard.fields.selectedSummary') }}</h3>
          <div class="wizard-summary-strip wizard-summary-strip--review">
            <div>
              <span>{{ t('deploymentWorkspace.columns.taskType') }}</span>
              <strong>{{ selectedDeploymentSource.taskType }}（{{ modelTaskLabel(selectedDeploymentSource.taskType, zh) }}）</strong>
            </div>
            <div>
              <span>{{ t('deploymentOps.fields.runtimePrecision') }}</span>
              <strong>{{ selectedDeploymentSource.runtimePrecision ? selectedDeploymentSource.runtimePrecision.toUpperCase() : '—' }}</strong>
            </div>
            <div>
              <span>{{ t('deploymentWorkspace.wizard.fields.inputSize') }}</span>
              <strong>{{ selectedInputSize }}</strong>
            </div>
            <div>
              <span>{{ t('deploymentWorkspace.wizard.fields.classCount') }}</span>
              <strong>{{ selectedClassCount }}</strong>
            </div>
            <div>
              <span>{{ t('deploymentWorkspace.wizard.fields.outputs') }}</span>
              <strong>{{ selectedOutputSummary }}</strong>
            </div>
          </div>
        </section>

        <InlineMessage v-if="unavailableReason" tone="warning">{{ unavailableReason }}</InlineMessage>
      </div>

      <footer class="deployment-wizard__footer">
        <Button type="button" variant="secondary" @click="emit('cancel')">{{ t('common.cancel') }}</Button>
        <div class="deployment-wizard__footer-right">
          <Button type="button" variant="secondary" disabled>← {{ t('deploymentWorkspace.actions.previousStep') }}</Button>
          <Button type="button" variant="primary" :disabled="!selectedDeploymentSource" @click="step = 2">
            {{ t('deploymentWorkspace.actions.nextStep') }} →
          </Button>
        </div>
      </footer>
    </div>

    <!-- Step 2: Runtime Configuration -->
    <div v-else-if="step === 2" class="deployment-card deployment-wizard__card">
      <div class="deployment-wizard__card-body">
        <div v-if="selectedDeploymentSource" class="wizard-top-summary">
          <div class="wizard-top-summary__grid">
            <div><span>{{ t('deploymentWorkspace.wizard.fields.deploymentName') }}</span><strong>{{ displayName || selectedDeploymentSource.modelName }}</strong></div>
            <div><span>{{ t('deploymentWorkspace.wizard.fields.model') }}</span><strong>{{ selectedDeploymentSource.modelName }} ({{ modelTaskLabel(selectedDeploymentSource.taskType, zh) }})</strong></div>
            <div><span>{{ t('deploymentWorkspace.wizard.fields.version') }}</span><strong>{{ selectedSourceVersionName || '—' }}</strong></div>
            <div><span>{{ t('deploymentWorkspace.wizard.fields.runtimeBackendLabel') }}</span><strong>{{ formatDeploymentBackend(selectedDeploymentSource.runtimeBackend) }}</strong></div>
            <div><span>{{ t('deploymentWorkspace.wizard.fields.modelAccuracy') }}</span><strong>{{ selectedDeploymentSource.runtimePrecision ? selectedDeploymentSource.runtimePrecision.toUpperCase() : '—' }}</strong></div>
          </div>
        </div>

        <section class="deployment-wizard__group">
          <h3>{{ t('deploymentWorkspace.wizard.groups.execution') }}</h3>
          <div class="form-grid deployment-create-grid">
            <div class="field">
              <span>{{ t('deploymentOps.fields.deviceName') }} <em class="req">*</em></span>
              <SelectField :aria-label="t('deploymentOps.fields.deviceName')" :model-value="deviceName" :options="deploymentDeviceOptions" @update:model-value="emit('update:deviceName', String($event ?? ''))" />
            </div>
            <div class="field">
              <span>{{ t('deploymentWorkspace.filters.runtimeMode') }} <em class="req">*</em></span>
              <input :value="t('deploymentOps.runtimeModes.sync')" readonly />
            </div>
            <label class="field" :class="{ 'field--invalid': !!instanceCountError }">
              <span>{{ t('deploymentOps.fields.instanceCount') }} <em class="req">*</em></span>
              <input
                :value="instanceCount"
                type="number"
                min="1"
                max="64"
                step="1"
                @input="emit('update:instanceCount', Number(($event.target as HTMLInputElement).value))"
              />
              <span v-if="instanceCountError" class="deployment-field-error">{{ instanceCountError }}</span>
            </label>
            <div class="field deployment-wizard__checkbox-cell">
              <label class="wizard-check-row">
                <input v-model="startAfterCreate" type="checkbox" :disabled="creating || !!createdDeployment" />
                <span>{{ t('deploymentWorkspace.wizard.startAfterCreate') }}</span>
              </label>
            </div>
          </div>
        </section>

        <hr class="wizard-divider" />

        <section class="deployment-wizard__group">
          <h3>{{ t('deploymentWorkspace.wizard.groups.lifecycle') }}</h3>
          <div class="form-grid deployment-create-grid">
            <div class="field">
              <span>{{ t('deploymentOps.runtimeConfig.keepWarm') }}</span>
              <SelectField :model-value="keepWarmEnabled" :options="enabledDisabledOptions" @update:model-value="emit('update:keepWarmEnabled', $event)" />
            </div>
            <label v-if="keepWarmEnabled === 'true'" class="field" :class="{ 'field--invalid': !!keepWarmIntervalError }">
              <span>{{ t('deploymentOps.runtimeConfig.keepWarmInterval') }}</span>
              <input
                :value="keepWarmIntervalSeconds"
                type="number"
                min="0.01"
                step="0.01"
                @input="emit('update:keepWarmIntervalSeconds', Number(($event.target as HTMLInputElement).value))"
                @blur="emit('normalize:keepWarmIntervalSeconds')"
              />
              <span v-if="keepWarmIntervalError" class="deployment-field-error">{{ keepWarmIntervalError }}</span>
            </label>
          </div>
        </section>

        <hr class="wizard-divider" />

        <section class="deployment-wizard__group">
          <h3>{{ backendSectionTitle }}</h3>

          <template v-if="isOpenVinoBackend">
            <div class="form-grid deployment-create-grid">
              <div class="field">
                <span>{{ t('deploymentOps.runtimeConfig.openvinoPerformanceHint') }}</span>
                <SelectField :model-value="openvinoPerformanceHint" :options="openvinoPerformanceHintOptions" @update:model-value="emit('update:openvinoPerformanceHint', $event)" />
              </div>
              <div v-if="openvinoDeviceKind === 'cpu'" class="field">
                <span>{{ t('deploymentOps.runtimeConfig.openvinoInferenceThreads') }}</span>
                <SelectField :model-value="openvinoInferenceNumThreads" :options="openvinoInferenceThreadOptions" @update:model-value="emit('update:openvinoInferenceNumThreads', $event)" />
              </div>
              <label v-if="openvinoDeviceKind === 'cpu' || openvinoDeviceKind === 'gpu'" class="field">
                <span>{{ t('deploymentOps.runtimeConfig.openvinoStreams') }}</span>
                <input
                  :value="openvinoNumStreams"
                  type="number"
                  min="1"
                  step="1"
                  @input="emit('update:openvinoNumStreams', Number(($event.target as HTMLInputElement).value))"
                  @blur="emit('normalize:openvinoNumStreams')"
                />
              </label>
              <div v-if="openvinoDeviceKind !== 'cpu'" class="field">
                <span>{{ t('deploymentOps.runtimeConfig.openvinoInferRequests') }}</span>
                <div class="field-control-row">
                  <SelectField :model-value="openvinoNumRequestsMode" :options="openvinoNumRequestsModeOptions" @update:model-value="emit('update:openvinoNumRequestsMode', $event)" />
                  <input
                    v-if="openvinoNumRequestsMode === 'manual'"
                    :value="openvinoNumRequests"
                    type="number"
                    min="1"
                    step="1"
                    :aria-label="t('deploymentOps.runtimeConfig.openvinoInferRequests')"
                    @input="emit('update:openvinoNumRequests', Number(($event.target as HTMLInputElement).value))"
                    @blur="emit('normalize:openvinoNumRequests')"
                  />
                </div>
              </div>
              <div v-if="(openvinoDeviceKind === 'gpu' || openvinoDeviceKind === 'npu') && supportedRuntimeField('inference_precision')" class="field">
                <span>{{ t('deploymentOps.runtimeConfig.inferencePrecision') }}</span>
                <SelectField :model-value="openvinoInferencePrecision" :options="openvinoInferencePrecisionOptions" @update:model-value="emit('update:openvinoInferencePrecision', $event)" />
              </div>
              <div v-if="openvinoDeviceKind === 'npu' && supportedRuntimeField('turbo')" class="field">
                <span>{{ t('deploymentOps.runtimeConfig.npuTurbo') }}</span>
                <SelectField :model-value="openvinoNpuTurbo" :options="autoBooleanOptions" @update:model-value="emit('update:openvinoNpuTurbo', $event)" />
              </div>
              <div v-if="openvinoDeviceKind === 'npu' && supportedRuntimeField('tiles')" class="field">
                <span>{{ t('deploymentOps.runtimeConfig.npuTiles') }}</span>
                <div class="field-control-row">
                  <SelectField :model-value="openvinoNpuTilesMode" :options="autoManualOptions" @update:model-value="emit('update:openvinoNpuTilesMode', $event)" />
                  <input
                    v-if="openvinoNpuTilesMode === 'manual'"
                    :value="openvinoNpuTiles"
                    type="number"
                    min="1"
                    :max="openvinoNpuMaxTiles ?? undefined"
                    step="1"
                    :aria-label="t('deploymentOps.runtimeConfig.npuTiles')"
                    @input="emit('update:openvinoNpuTiles', Number(($event.target as HTMLInputElement).value))"
                    @blur="emit('normalize:openvinoNpuTiles')"
                  />
                </div>
              </div>
              <label v-if="openvinoDeviceKind === 'npu' && supportedRuntimeField('compilation_mode_params')" class="field">
                <span>{{ t('deploymentOps.runtimeConfig.npuCompilationModeParams') }}</span>
                <input :value="openvinoNpuCompilationModeParams" @input="emit('update:openvinoNpuCompilationModeParams', ($event.target as HTMLInputElement).value)" />
              </label>
            </div>

            <div v-if="effectiveThreadsMessage" class="wizard-info-note">
              <Info :size="15" aria-hidden="true" />
              <span>{{ effectiveThreadsMessage }}</span>
            </div>

            <details v-if="openvinoDeviceKind === 'cpu'" class="wizard-advanced">
              <summary>{{ t('deploymentWorkspace.wizard.groups.advancedOptional') }}</summary>
              <div class="form-grid deployment-create-grid wizard-advanced__body">
                <div class="field">
                  <span>{{ t('deploymentOps.runtimeConfig.cpuCoreType') }}</span>
                  <SelectField :model-value="openvinoSchedulingCoreType" :options="openvinoSchedulingCoreTypeOptions" @update:model-value="emit('update:openvinoSchedulingCoreType', $event)" />
                </div>
                <div class="field">
                  <span>{{ t('deploymentOps.runtimeConfig.hyperThreading') }}</span>
                  <SelectField :model-value="openvinoHyperThreading" :options="autoBooleanOptions" @update:model-value="emit('update:openvinoHyperThreading', $event)" />
                </div>
                <div class="field">
                  <span>{{ t('deploymentOps.runtimeConfig.cpuPinning') }}</span>
                  <SelectField :model-value="openvinoCpuPinning" :options="autoBooleanOptions" @update:model-value="emit('update:openvinoCpuPinning', $event)" />
                </div>
              </div>
            </details>
          </template>

          <template v-else-if="isTensorRtBackend">
            <div class="form-grid deployment-create-grid">
              <div v-if="showTensorRtSingleProfileRange" class="field">
                <span>{{ t('deploymentOps.runtimeConfig.tensorrtProfileRange') }}</span>
                <div class="deployment-profile-summary">
                  <span v-for="line in tensorRtSingleProfileRangeLines" :key="line">{{ line }}</span>
                </div>
              </div>
              <div v-if="showTensorRtProfileSelector" class="field">
                <span>{{ t('deploymentOps.runtimeConfig.tensorrtOptimizationProfile') }}</span>
                <SelectField :model-value="tensorrtOptimizationProfileIndex" :options="tensorRtOptimizationProfileOptions" @update:model-value="emit('update:tensorrtOptimizationProfileIndex', $event)" />
              </div>
              <div class="field">
                <span>{{ t('deploymentOps.runtimeConfig.tensorrtPinnedOutput') }}</span>
                <SelectField :model-value="tensorrtPinnedOutput" :options="serviceDefaultBooleanOptions" @update:model-value="emit('update:tensorrtPinnedOutput', $event)" />
              </div>
            </div>
          </template>

          <template v-else-if="selectedRuntimeBackend === 'onnxruntime' || selectedRuntimeBackend === 'onnx'">
            <div class="form-grid deployment-create-grid">
              <label class="field">
                <span>{{ t('deploymentWorkspace.wizard.fields.executionProvider') }}</span>
                <input :value="onnxProviderName" readonly />
              </label>
            </div>
          </template>

          <template v-else>
            <div class="wizard-info-note">
              <Lock :size="15" aria-hidden="true" />
              <span>{{ t('deploymentWorkspace.wizard.fields.pytorchEvalMode') }}</span>
            </div>
          </template>

          <InlineMessage v-if="runtimeCapabilitiesLoading" :message="t('deploymentOps.messages.capabilitiesLoading')" />
          <InlineMessage v-else-if="runtimeCapabilityWarnings.length" tone="warning">{{ runtimeCapabilityWarnings.join('；') }}</InlineMessage>
        </section>
      </div>

      <footer class="deployment-wizard__footer">
        <div class="deployment-wizard__footer-left">
          <span v-if="validationErrorCount > 0" class="wizard-error-count">
            <AlertCircle :size="15" aria-hidden="true" />
            <span>{{ t('deploymentWorkspace.wizard.fields.validationFixCount', { count: validationErrorCount }) }}</span>
          </span>
          <Button v-else type="button" variant="secondary" @click="emit('cancel')">{{ t('common.cancel') }}</Button>
        </div>
        <div class="deployment-wizard__footer-right">
          <Button v-if="validationErrorCount > 0" type="button" variant="secondary" @click="emit('cancel')">{{ t('common.cancel') }}</Button>
          <Button type="button" variant="secondary" @click="step = 1">← {{ t('deploymentWorkspace.actions.previousStep') }}</Button>
          <Button type="button" variant="primary" :disabled="hasValidationError" @click="goToReview">
            {{ t('deploymentWorkspace.actions.checkAndContinue') }} →
          </Button>
        </div>
      </footer>
    </div>

    <!-- Step 3: Check & Create -->
    <form v-else class="deployment-card deployment-wizard__card deployment-create-panel" @submit.prevent="emit('submit', { startAfterCreate })">
      <div class="deployment-wizard__card-body">
        <div v-if="selectedDeploymentSource" class="wizard-top-summary">
          <div class="wizard-top-summary__grid">
            <div><span>{{ t('deploymentWorkspace.wizard.fields.deploymentName') }}</span><strong>{{ displayName || selectedDeploymentSource.modelName }}</strong></div>
            <div><span>{{ t('deploymentWorkspace.wizard.fields.model') }}</span><strong>{{ selectedDeploymentSource.modelName }}</strong></div>
            <div><span>{{ t('deploymentWorkspace.wizard.fields.version') }}</span><strong>{{ selectedSourceVersionName || '—' }}</strong></div>
            <div><span>{{ t('deploymentWorkspace.wizard.fields.runtimeBackendLabel') }}</span><strong>{{ formatDeploymentBackend(selectedDeploymentSource.runtimeBackend) }}</strong></div>
            <div><span>{{ t('deploymentWorkspace.wizard.fields.modelAccuracy') }}</span><strong>{{ selectedDeploymentSource.runtimePrecision ? selectedDeploymentSource.runtimePrecision.toUpperCase() : '—' }}</strong></div>
          </div>
        </div>

        <section class="deployment-wizard__group">
          <h3>{{ t('deploymentWorkspace.wizard.checksTitle') }}</h3>
          <div class="wizard-checks-card">
            <div v-for="check in staticChecks" :key="check.label" class="wizard-check-item">
              <div class="wizard-check-item__title">
                <CheckCircle2 v-if="check.tone === 'success'" :size="17" class="is-success" />
                <AlertCircle v-else-if="check.tone === 'warning'" :size="17" class="is-warning" />
                <XCircle v-else :size="17" class="is-danger" />
                <strong>{{ check.label }}</strong>
              </div>
              <span class="wizard-check-item__detail">{{ check.detail }}</span>
            </div>
            <div class="wizard-checks-card__foot">
              <span>{{ t('deploymentWorkspace.wizard.checkTimeLabel') }}：{{ checkedAtLabel }}</span>
            </div>
          </div>
        </section>

        <section class="deployment-wizard__group">
          <h3>{{ t('deploymentWorkspace.wizard.summaryTitle') }}</h3>
          <div class="wizard-summary-strip wizard-summary-strip--review">
            <div>
              <span>{{ t('deploymentOps.fields.deviceName') }}</span>
              <strong>{{ formatDeploymentDeviceName(deviceName) || t('deploymentOps.options.automaticDefault') }}</strong>
            </div>
            <div>
              <span>{{ t('deploymentWorkspace.filters.runtimeMode') }}</span>
              <strong>{{ t('deploymentOps.runtimeModes.sync') }}</strong>
            </div>
            <div>
              <span>{{ t('deploymentOps.fields.instanceCount') }}</span>
              <strong>{{ instanceCount }}</strong>
            </div>
            <div>
              <span>{{ t('deploymentOps.runtimeConfig.keepWarm') }}</span>
              <strong>{{ keepWarmEnabled === 'true' ? `${t('deploymentOps.options.enabled')} (${keepWarmIntervalSeconds}s)` : t('deploymentOps.options.disabled') }}</strong>
            </div>
            <div>
              <span>{{ t('deploymentWorkspace.wizard.startAfterCreate') }}</span>
              <strong>{{ startAfterCreate ? t('deploymentOps.options.enabled') : t('deploymentOps.options.disabled') }}</strong>
            </div>
          </div>
        </section>

        <InlineMessage v-if="createdDeployment && !startFailureMessage" tone="success">
          {{ t('deploymentOps.messages.created') }} {{ createdDeployment.deployment_instance_id }}
        </InlineMessage>
        <InlineError v-if="startFailureMessage" :message="startFailureMessage" />
      </div>

      <footer class="deployment-wizard__footer">
        <Button type="button" variant="secondary" @click="emit('cancel')">{{ t('common.cancel') }}</Button>
        <div class="deployment-wizard__footer-right">
          <Button type="button" variant="secondary" :disabled="creating || !!createdDeployment" @click="step = 2">
            ← {{ t('deploymentWorkspace.actions.previousStep') }}
          </Button>
          <Button
            v-if="!createdDeployment"
            variant="primary"
            type="submit"
            :disabled="!canWriteModels || creating || !!unavailableReason || hasValidationError"
            :loading="creating"
          >
            <template v-if="creating">{{ t('deploymentOps.actions.creating') }}</template>
            <template v-else-if="startAfterCreate">{{ t('deploymentWorkspace.actions.createAndStart') }} →</template>
            <template v-else>{{ t('deploymentWorkspace.actions.createOnly') }} →</template>
          </Button>
          <Button v-else type="button" variant="primary" @click="emit('done')">
            {{ t('deploymentTransfer.done') }}
          </Button>
        </div>
      </footer>
    </form>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertCircle, Check, CheckCircle2, ChevronRight, Info, Lock, XCircle } from '@lucide/vue'
import { conversionFormatName } from '@/modules/models/conversion-task-presentation'
import { modelDisplayName, modelVersionDisplayName } from '@/modules/models/model-display-name'
import { modelTaskLabel } from '@/modules/models/model-evaluation-types'
import type {
  DeploymentSourceModelBuild,
  DeploymentSourceModelDetail,
  DeploymentSourceModelSummary,
} from '@/modules/models/services/model.service'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import InlineMessage from '@/shared/ui/feedback/InlineMessage.vue'
import LoadingPanel from '@/shared/ui/feedback/LoadingPanel.vue'
import { hasCudaDevice } from '../deployment-device-support'
import { formatDeploymentBackend, formatDeploymentDeviceName } from '../deployment-presentation'
import DeploymentRuntimeBadge from './DeploymentRuntimeBadge.vue'
import type { DeploymentSourceSelection } from './deployment-source.types'
import type { DeploymentRuntimeCapabilities, TaskDeploymentInstance } from '../services/deployment.service'

const props = defineProps<{
  projectName?: string
  devices?: Record<string, unknown> | null
  wizardModels: DeploymentSourceModelSummary[]
  wizardModelsLoading: boolean
  wizardSelectedModelId: string
  wizardSelectedModelDetail: DeploymentSourceModelDetail | null
  wizardDetailLoading: boolean
  selectedDeploymentSource: DeploymentSourceSelection | null
  selectedSourceVersionName: string
  sourceModelsLoading: boolean
  unavailableReason: string
  canWriteModels: boolean
  creating: boolean
  createdDeployment: TaskDeploymentInstance | null
  startFailureMessage: string | null
  deviceName: string
  deploymentDeviceOptions: Array<{ label: string; value: string }>
  instanceCount: number
  displayName: string
  isOpenVinoBackend: boolean
  isTensorRtBackend: boolean
  openvinoDeviceKind: 'cpu' | 'gpu' | 'npu' | 'auto'
  openvinoPerformanceHint: string
  openvinoPerformanceHintOptions: Array<{ label: string; value: string }>
  openvinoInferenceNumThreads: number
  openvinoInferenceThreadOptions: Array<{ label: string; value: number }>
  openvinoNumStreams: number
  openvinoSchedulingCoreType: string
  openvinoSchedulingCoreTypeOptions: Array<{ label: string; value: string }>
  openvinoHyperThreading: string
  openvinoCpuPinning: string
  autoBooleanOptions: Array<{ label: string; value: string }>
  openvinoNumRequestsMode: string
  openvinoNumRequestsModeOptions: Array<{ label: string; value: string }>
  openvinoNumRequests: number
  openvinoInferencePrecision: string
  openvinoInferencePrecisionOptions: Array<{ label: string; value: string }>
  openvinoNpuTurbo: string
  openvinoNpuTilesMode: string
  autoManualOptions: Array<{ label: string; value: string }>
  openvinoNpuTiles: number
  openvinoNpuMaxTiles: number | null
  openvinoNpuCompilationModeParams: string
  showTensorRtSingleProfileRange: boolean
  tensorRtSingleProfileRangeLines: string[]
  showTensorRtProfileSelector: boolean
  tensorrtOptimizationProfileIndex: number
  tensorRtOptimizationProfileOptions: Array<{ label: string; value: number; description?: string }>
  tensorrtPinnedOutput: string
  serviceDefaultBooleanOptions: Array<{ label: string; value: string }>
  keepWarmEnabled: string
  enabledDisabledOptions: Array<{ label: string; value: string }>
  keepWarmIntervalSeconds: number
  runtimeCapabilities: DeploymentRuntimeCapabilities | null
  runtimeCapabilitiesLoading: boolean
  runtimeCapabilityWarnings: string[]
  supportedRuntimeField: (fieldName: string) => boolean
  initialStep?: 1 | 2 | 3
}>()

const emit = defineEmits([
  'cancel',
  'done',
  'open-source-picker',
  'select-wizard-model',
  'select-inline-source',
  'submit',
  'update:deviceName',
  'update:instanceCount',
  'normalize:instanceCount',
  'update:displayName',
  'update:openvinoPerformanceHint',
  'update:openvinoInferenceNumThreads',
  'update:openvinoNumStreams',
  'normalize:openvinoNumStreams',
  'update:openvinoSchedulingCoreType',
  'update:openvinoHyperThreading',
  'update:openvinoCpuPinning',
  'update:openvinoNumRequestsMode',
  'update:openvinoNumRequests',
  'normalize:openvinoNumRequests',
  'update:openvinoInferencePrecision',
  'update:openvinoNpuTurbo',
  'update:openvinoNpuTilesMode',
  'update:openvinoNpuTiles',
  'normalize:openvinoNpuTiles',
  'update:openvinoNpuCompilationModeParams',
  'update:tensorrtOptimizationProfileIndex',
  'update:tensorrtPinnedOutput',
  'update:keepWarmEnabled',
  'update:keepWarmIntervalSeconds',
  'normalize:keepWarmIntervalSeconds',
])

const { t, locale } = useI18n()
const zh = computed(() => locale.value.startsWith('zh'))
const step = ref<1 | 2 | 3>(props.initialStep ?? 1)
const startAfterCreate = ref(false)
const wizardSelectedVersionId = ref('')
const checkedAt = ref(new Date().toISOString())

const stepLabels = computed(() => [
  t('deploymentWorkspace.wizard.steps.source'),
  t('deploymentWorkspace.wizard.steps.config'),
  t('deploymentWorkspace.wizard.steps.review'),
])

const modelDropdownOptions = computed(() => props.wizardModels
  .filter(item => item.scope_kind === 'project')
  .map(item => ({
    label: `${modelDisplayName(item)} (${modelTaskLabel(item.task_type, zh.value)})`,
    value: item.model_id,
  })))

const versionDropdownOptions = computed(() => (props.wizardSelectedModelDetail?.versions ?? []).map(ver => ({
  label: modelVersionDisplayName(ver),
  value: ver.model_version_id,
})))

watch(() => props.wizardSelectedModelDetail, (detail) => {
  if (!detail) {
    wizardSelectedVersionId.value = ''
    return
  }
  const sourceVer = props.selectedDeploymentSource?.modelId === detail.model_id
    ? props.selectedDeploymentSource.modelVersionId
    : ''
  if (sourceVer && detail.versions.some(v => v.model_version_id === sourceVer)) {
    wizardSelectedVersionId.value = sourceVer
  } else if (!detail.versions.some(v => v.model_version_id === wizardSelectedVersionId.value)) {
    wizardSelectedVersionId.value = detail.versions[0]?.model_version_id ?? ''
  }
}, { immediate: true })

watch(() => props.selectedDeploymentSource, (source) => {
  if (source && source.modelVersionId && wizardSelectedVersionId.value !== source.modelVersionId) {
    wizardSelectedVersionId.value = source.modelVersionId
  }
})

const versionBuilds = computed(() => {
  const detail = props.wizardSelectedModelDetail
  if (!detail) return []
  if (!wizardSelectedVersionId.value) return detail.builds
  return detail.builds.filter(b => b.source_model_version_id === wizardSelectedVersionId.value)
})

function buildReason(build: DeploymentSourceModelBuild): string {
  const runtimeBackend = String(build.runtime_backend ?? '').trim().toLowerCase()
  if (runtimeBackend !== 'tensorrt') return ''
  if (!hasCudaDevice(props.devices)) return t('deploymentOps.sourcePicker.cudaUnavailable')
  const trt = props.devices?.tensorrt as Record<string, unknown> | undefined
  if (trt?.installed !== true) return t('deploymentOps.sourcePicker.tensorrtUnavailable')
  return ''
}

function isWizardBuildSelectable(build: DeploymentSourceModelBuild): boolean {
  return buildReason(build) === ''
}

function artifactFileLabel(build: DeploymentSourceModelBuild): string {
  const meta = build.metadata
  if (typeof meta?.artifact_file_name === 'string' && meta.artifact_file_name) return meta.artifact_file_name
  const format = String(build.build_format ?? '').toLowerCase()
  if (format.includes('openvino')) return 'model.xml + model.bin'
  if (format.includes('tensorrt') || format.includes('engine')) return 'model.engine'
  if (format.includes('onnx')) return 'model.onnx'
  return build.model_build_id
}

function selectWizardBuild(build: DeploymentSourceModelBuild): void {
  const detail = props.wizardSelectedModelDetail
  if (!detail || !isWizardBuildSelectable(build)) return
  emit('select-inline-source', {
    sourceKind: 'model-build',
    modelId: detail.model_id,
    modelName: modelDisplayName(detail),
    modelType: detail.model_type,
    modelScale: detail.model_scale,
    taskType: detail.task_type,
    modelVersionId: build.source_model_version_id,
    modelBuildId: build.model_build_id,
    buildFormat: build.build_format,
    runtimeProfileId: build.runtime_profile_id ?? '',
    runtimeBackend: build.runtime_backend,
    runtimePrecision: build.runtime_precision,
    buildMetadata: { ...build.metadata },
  })
}

const selectedInputSize = computed(() => {
  const meta = props.selectedDeploymentSource?.buildMetadata
  if (meta && Array.isArray(meta.input_shape) && meta.input_shape.length >= 2) {
    return `${meta.input_shape.at(-2)} × ${meta.input_shape.at(-1)}`
  }
  return '—'
})

const selectedClassCount = computed(() => {
  const meta = props.selectedDeploymentSource?.buildMetadata
  if (meta && Array.isArray(meta.labels)) return String(meta.labels.length)
  return '—'
})

const selectedOutputSummary = computed(() => {
  const task = props.selectedDeploymentSource?.taskType
  if (task === 'detection' || task === 'obb') return 'boxes'
  if (task === 'classification') return 'classes / scores'
  if (task === 'segmentation') return 'masks'
  if (task === 'pose') return 'keypoints'
  return '—'
})

const selectedRuntimeBackend = computed(() => props.selectedDeploymentSource?.runtimeBackend.trim().toLowerCase() ?? '')

const backendSectionTitle = computed(() => {
  const backend = formatDeploymentBackend(props.selectedDeploymentSource?.runtimeBackend)
  if (props.isOpenVinoBackend) return `${backend} (${props.openvinoDeviceKind.toUpperCase()})`
  return backend
})

const onnxProviderName = computed(() => (
  props.deviceName.toLowerCase().includes('cuda') ? 'CUDAExecutionProvider' : 'CPUExecutionProvider'
))

const instanceCountError = computed(() => {
  const value = props.instanceCount
  if (!Number.isInteger(value) || value < 1 || value > 64) {
    return t('deploymentWorkspace.wizard.invalidInstanceCount')
  }
  return ''
})

const keepWarmIntervalError = computed(() => {
  if (props.keepWarmEnabled !== 'true') return ''
  const value = props.keepWarmIntervalSeconds
  if (!Number.isFinite(value) || value < 0.01) {
    return t('deploymentWorkspace.wizard.invalidKeepWarmInterval')
  }
  return ''
})

const validationErrorCount = computed(() => (
  (instanceCountError.value ? 1 : 0) + (keepWarmIntervalError.value ? 1 : 0)
))
const hasValidationError = computed(() => validationErrorCount.value > 0)

const effectiveThreadsMessage = computed(() => {
  if (!props.isOpenVinoBackend || props.openvinoDeviceKind !== 'cpu') return ''
  const cores = Number(props.runtimeCapabilities?.hardware?.cpu_physical_core_count)
  if (!Number.isInteger(cores) || cores < 1) return ''
  const instances = Math.max(1, Math.trunc(Number(props.instanceCount) || 1))
  const requested = Math.max(1, Math.trunc(Number(props.openvinoInferenceNumThreads) || cores))
  const effective = Math.min(requested, Math.max(1, Math.floor(cores / instances)))
  return t('deploymentWorkspace.wizard.effectiveThreadsPreview', { cores, instances, effective })
})

const checkedAtLabel = computed(() => formatSystemDateTime(checkedAt.value))

function goToReview(): void {
  checkedAt.value = new Date().toISOString()
  step.value = 3
}

const staticChecks = computed(() => {
  const backend = formatDeploymentBackend(props.selectedDeploymentSource?.runtimeBackend)
  const devText = formatDeploymentDeviceName(props.deviceName) || t('deploymentOps.options.automaticDefault')
  return [
    {
      label: t('deploymentWorkspace.wizard.checks.artifact'),
      tone: (props.selectedDeploymentSource ? 'success' : 'danger') as 'success' | 'danger',
      detail: props.selectedDeploymentSource ? t('deploymentWorkspace.wizard.checks.artifactDetail') : t('deploymentOps.source.emptyTitle'),
    },
    {
      label: t('deploymentWorkspace.wizard.checks.backendCompat', { backend }),
      tone: (props.unavailableReason ? 'danger' : props.runtimeCapabilityWarnings.length ? 'warning' : 'success') as 'success' | 'warning' | 'danger',
      detail: props.unavailableReason || props.runtimeCapabilityWarnings[0] || t('deploymentWorkspace.wizard.checks.backendCompatDetail', { backend }),
    },
    {
      label: t('deploymentWorkspace.wizard.checks.device'),
      tone: (props.unavailableReason ? 'danger' : 'success') as 'success' | 'danger',
      detail: props.unavailableReason || t('deploymentWorkspace.wizard.checks.deviceDetail', { device: devText }),
    },
    {
      label: t('deploymentWorkspace.wizard.checks.contract'),
      tone: 'success' as const,
      detail: t('deploymentWorkspace.wizard.checks.contractDetail'),
    },
    {
      label: t('deploymentWorkspace.wizard.checks.configuration'),
      tone: (hasValidationError.value ? 'danger' : 'success') as 'success' | 'danger',
      detail: instanceCountError.value || keepWarmIntervalError.value || t('deploymentWorkspace.wizard.checks.configurationDetail'),
    },
  ]
})
</script>

<style scoped>
.deployment-wizard-shell {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.deployment-wizard__breadcrumb {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--am-text-muted);
}

.deployment-wizard__crumb-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--am-text);
  font: inherit;
  cursor: pointer;
}

.deployment-wizard__crumb-link:hover {
  color: var(--am-action-primary-strong);
  text-decoration: underline;
}

.deployment-wizard__stepper {
  display: flex;
  align-items: center;
  width: 100%;
  max-width: none;
  margin: 0;
  padding: 8px 4px;
  box-sizing: border-box;
  list-style: none;
}

.deployment-wizard__step {
  position: relative;
  display: flex;
  align-items: center;
  flex: 1 1 0;
  min-width: 0;
  gap: 8px;
  color: var(--am-text-muted);
  font-size: 13px;
}

.deployment-wizard__step:last-child {
  flex: 0 0 auto;
}

.deployment-wizard__step strong {
  white-space: nowrap;
}

.deployment-wizard__step-circle {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  border-radius: 999px;
  border: 1px solid var(--am-border);
  background: var(--am-surface);
  font-size: 12px;
  font-weight: 700;
}

.deployment-wizard__step.is-current {
  color: var(--am-action-primary-strong);
}

.deployment-wizard__step.is-current .deployment-wizard__step-circle {
  background: var(--am-action-primary);
  border-color: var(--am-action-primary);
  color: #fff;
}

.deployment-wizard__step.is-complete {
  color: var(--am-text);
}

.deployment-wizard__step.is-complete .deployment-wizard__step-circle {
  border-color: var(--am-action-primary);
  color: var(--am-action-primary);
  background: var(--am-surface);
}

.deployment-wizard__step-line {
  flex: 1 1 auto;
  height: 1px;
  margin: 0 12px;
  background: var(--am-border);
}

.deployment-wizard__step-line.is-complete {
  background: var(--am-action-primary);
}

.deployment-wizard__card {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  border: 1px solid var(--am-border);
  border-radius: 10px;
  background: var(--am-surface);
}

.deployment-wizard__card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--am-border);
}

.deployment-wizard__card-body {
  display: grid;
  gap: 18px;
  padding: 20px;
}

.deployment-wizard__source-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.req {
  color: var(--am-danger-icon);
  font-style: normal;
}

.deployment-wizard__group {
  display: grid;
  gap: 12px;
}

.deployment-wizard__group h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
}

.wizard-build-table {
  border: 1px solid var(--am-border);
  border-radius: 8px;
  overflow-x: auto;
}

.wizard-build-table table {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
}

.wizard-build-table th,
.wizard-build-table td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--am-border);
  text-align: left;
  vertical-align: middle;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.wizard-build-table tr:last-child td {
  border-bottom: 0;
}

.wizard-build-table th {
  background: var(--am-surface);
  color: var(--am-text);
  font-size: 14px;
  font-weight: 600;
}

.wizard-build-table td {
  font-size: 14px;
}

.wizard-build-format-cell {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  min-width: 0;
  vertical-align: middle;
}

.wizard-ellipsis {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wizard-build-table tbody tr {
  cursor: pointer;
}

.wizard-build-table tbody tr.is-selected {
  background: color-mix(in srgb, var(--am-action-primary) 5%, var(--am-surface));
}

.wizard-build-table tbody tr.is-disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.wizard-radio-col {
  width: 64px;
  text-align: center !important;
}

.wizard-radio {
  position: relative;
  display: inline-grid;
  place-items: center;
  width: 18px;
  height: 18px;
  padding: 0;
  border-radius: 999px;
  border: 1.5px solid var(--am-border);
  background: var(--am-surface);
  cursor: pointer;
}

.wizard-radio.is-checked {
  border-color: var(--am-action-primary);
}

.wizard-radio.is-checked::after {
  content: '';
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--am-action-primary);
}

.wizard-check-dot {
  white-space: nowrap;
}

.wizard-check-dot.is-success {
  color: var(--am-action-primary-strong);
  font-weight: 600;
}

.wizard-check-dot.is-warning {
  color: var(--am-warning-text);
  font-weight: 600;
}

.wizard-summary-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface);
}

.wizard-summary-strip--review {
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.wizard-summary-strip > div {
  display: grid;
  gap: 3px;
}

.wizard-summary-strip span {
  font-size: 12px;
  color: var(--am-text-muted);
}

.wizard-summary-strip strong {
  font-size: 13px;
}

.wizard-info-note {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  background: var(--am-surface);
  color: var(--am-text-muted);
  font-size: 12px;
}

.wizard-top-summary {
  display: grid;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface);
}

.wizard-top-summary__project {
  font-weight: 700;
  font-size: 13px;
}

.wizard-top-summary__grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}

.wizard-top-summary__grid > div {
  display: grid;
  gap: 2px;
}

.wizard-top-summary__grid span {
  font-size: 12px;
  color: var(--am-text-muted);
}

.wizard-top-summary__grid strong {
  font-size: 13px;
}

.wizard-divider {
  border: 0;
  border-top: 1px solid var(--am-border);
  margin: 0;
}

.deployment-wizard__checkbox-cell {
  display: grid;
  gap: 4px;
  align-content: start;
  padding-top: 22px;
}

.wizard-check-row {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  cursor: pointer;
}

.deployment-field-hint {
  font-size: 12px;
  color: var(--am-text-muted);
}

.field--invalid input {
  border-color: var(--am-danger-border);
}

.deployment-field-error {
  color: var(--am-danger-text);
  font-size: 12px;
}

.wizard-advanced {
  border: 1px solid var(--am-border);
  border-radius: 8px;
  padding: 10px 12px;
}

.wizard-advanced summary {
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
}

.wizard-advanced__body {
  margin-top: 12px;
}

.wizard-checks-card {
  border: 1px solid var(--am-border);
  border-radius: 8px;
  overflow: hidden;
}

.wizard-check-item {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--am-border);
}

.wizard-check-item__title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.wizard-check-item__title .is-success { color: var(--am-action-primary); }
.wizard-check-item__title .is-warning { color: var(--am-warning-icon); }
.wizard-check-item__title .is-danger { color: var(--am-danger-icon); }

.wizard-check-item__detail {
  font-size: 13px;
  color: var(--am-text-muted);
}

.wizard-checks-card__foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 10px 16px;
  border-top: 1px solid var(--am-border);
  background: var(--am-surface);
  font-size: 12px;
  color: var(--am-text-muted);
}

.wizard-checks-card__hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.deployment-wizard__footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 20px;
  border-top: 1px solid var(--am-border);
}

.deployment-wizard__footer-left,
.deployment-wizard__footer-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.deployment-wizard__footer :deep(.ui-button:disabled) {
  opacity: 0.48;
  cursor: not-allowed;
}

.wizard-error-count {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--am-danger-text);
  font-size: 13px;
  font-weight: 600;
}

.source-empty-card {
  display: grid;
  gap: 4px;
  padding: 18px;
  border: 1px dashed var(--am-border);
  border-radius: 8px;
  color: var(--am-text-muted);
}

@media (max-width: 960px) {
  .deployment-wizard__source-row,
  .wizard-summary-strip,
  .wizard-summary-strip--review,
  .wizard-top-summary__grid,
  .wizard-check-item {
    grid-template-columns: 1fr;
  }
}
</style>
