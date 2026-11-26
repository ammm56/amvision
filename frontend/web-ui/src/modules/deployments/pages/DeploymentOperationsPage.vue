<template>
  <section class="page-stack model-workspace deployment-workspace">
    <nav v-if="!createWizardOpen" class="deployment-ops-navigation" :aria-label="t('deploymentOps.title')">
      <TabList
        :tabs="pageTabs"
        :model-value="activeTab"
        variant="underline"
        :label="t('deploymentOps.title')"
        @update:model-value="setActiveTab"
      />
      <div class="deployment-ops-navigation__actions">
        <Button
          v-if="activeTab === 'instances'"
          variant="secondary"
          data-deployment-action="capabilities"
          @click="capabilitiesDrawerOpen = true"
        >
          <Cpu :size="16" aria-hidden="true" />
          {{ t('deploymentWorkspace.actions.deviceCapabilities') }}
        </Button>
        <Button
          v-if="(activeTab === 'instances' || activeTab === 'imports') && canManageTransfers"
          :variant="activeTab === 'imports' ? 'primary' : 'secondary'"
          data-deployment-action="import-wizard"
          :disabled="!selectedProjectId"
          @click="openDeploymentImportDialog"
        >
          <Upload :size="16" aria-hidden="true" />
          {{ t('deploymentWorkspace.actions.importDeployment') }}
        </Button>
        <Button
          v-if="activeTab === 'instances' && canWriteModels"
          variant="primary"
          data-deployment-action="create-wizard"
          :disabled="!selectedProjectId"
          @click="openCreateWizard"
        >
          <Plus :size="16" aria-hidden="true" />
          {{ t('deploymentWorkspace.actions.createDeployment') }}
        </Button>
      </div>
    </nav>

    <input ref="transferFileInput" type="file" accept=".zip" hidden @change="uploadDeploymentPackage" />
    <InlineError :message="errorMessage" />
    <InlineError :message="versionSourceError" />
    <ResourceCleanupPanel :project-id="selectedProjectId" @settled="refreshPage" />

    <DeploymentTransferPanel
      v-if="canManageTransfers"
      ref="transferPanel"
      :project-id="selectedProjectId"
      :devices="sessionStore.bootstrap?.devices ?? null"
      @settled="refreshPage"
      @choose-file="transferFileInput?.click()"
    />

    <DeploymentCreateWizard
      v-if="createWizardOpen"
      :project-name="selectedProjectName"
      :devices="sessionStore.bootstrap?.devices ?? null"
      :wizard-models="wizardModels"
      :wizard-models-loading="wizardModelsLoading"
      :wizard-selected-model-id="wizardSelectedModelId"
      :wizard-selected-model-detail="wizardSelectedModelDetail"
      :wizard-detail-loading="wizardDetailLoading"
      :selected-deployment-source="selectedDeploymentSource"
      :selected-source-version-name="selectedSourceVersionName"
      :source-models-loading="sourceModelsLoading"
      :unavailable-reason="selectedDeploymentSource ? deploymentSourceUnavailableReason(selectedDeploymentSource) : ''"
      :can-write-models="canWriteModels"
      :creating="creating"
      :created-deployment="wizardCreatedDeployment"
      :start-failure-message="wizardStartFailureMessage"
      :device-name="deviceName"
      :deployment-device-options="deploymentDeviceOptions"
      :instance-count="instanceCount"
      :display-name="displayName"
      :is-open-vino-backend="isOpenVinoBackend"
      :is-tensor-rt-backend="isTensorRtBackend"
      :openvino-device-kind="openvinoDeviceKind"
      :openvino-performance-hint="openvinoPerformanceHint"
      :openvino-performance-hint-options="openvinoPerformanceHintOptions"
      :openvino-inference-num-threads="openvinoInferenceNumThreads"
      :openvino-inference-thread-options="openvinoInferenceThreadOptions"
      :openvino-num-streams="openvinoNumStreams"
      :openvino-scheduling-core-type="openvinoSchedulingCoreType"
      :openvino-scheduling-core-type-options="openvinoSchedulingCoreTypeOptions"
      :openvino-hyper-threading="openvinoHyperThreading"
      :openvino-cpu-pinning="openvinoCpuPinning"
      :auto-boolean-options="autoBooleanOptions"
      :openvino-num-requests-mode="openvinoNumRequestsMode"
      :openvino-num-requests-mode-options="openvinoNumRequestsModeOptions"
      :openvino-num-requests="openvinoNumRequests"
      :openvino-inference-precision="openvinoInferencePrecision"
      :openvino-inference-precision-options="openvinoInferencePrecisionOptions"
      :openvino-npu-turbo="openvinoNpuTurbo"
      :openvino-npu-tiles-mode="openvinoNpuTilesMode"
      :auto-manual-options="autoManualOptions"
      :openvino-npu-tiles="openvinoNpuTiles"
      :openvino-npu-max-tiles="openvinoNpuMaxTiles"
      :openvino-npu-compilation-mode-params="openvinoNpuCompilationModeParams"
      :show-tensor-rt-single-profile-range="showTensorRtSingleProfileRange"
      :tensor-rt-single-profile-range-lines="tensorRtSingleProfileRangeLines"
      :show-tensor-rt-profile-selector="showTensorRtProfileSelector"
      :tensorrt-optimization-profile-index="tensorrtOptimizationProfileIndex"
      :tensor-rt-optimization-profile-options="tensorRtOptimizationProfileOptions"
      :tensorrt-pinned-output="tensorrtPinnedOutput"
      :service-default-boolean-options="serviceDefaultBooleanOptions"
      :keep-warm-enabled="keepWarmEnabled"
      :enabled-disabled-options="enabledDisabledOptions"
      :keep-warm-interval-seconds="keepWarmIntervalSeconds"
      :runtime-capabilities="runtimeCapabilities"
      :runtime-capabilities-loading="runtimeCapabilitiesLoading"
      :runtime-capability-warnings="runtimeCapabilityWarnings"
      :supported-runtime-field="supportedRuntimeField"
      @cancel="closeCreateWizard"
      @done="closeCreateWizard"
      @open-source-picker="openDeploymentSourcePicker"
      @select-wizard-model="selectWizardModel"
      @select-inline-source="applyDeploymentSource"
      @submit="handleWizardSubmit"
      @update:device-name="setDeviceName"
      @update:instance-count="instanceCount = $event"
      @normalize:instance-count="normalizeInstanceCount"
      @update:display-name="displayName = $event"
      @update:openvino-performance-hint="setOpenvinoPerformanceHint($event as SelectValue)"
      @update:openvino-inference-num-threads="setOpenvinoInferenceNumThreads($event as SelectValue)"
      @update:openvino-num-streams="openvinoNumStreams = $event"
      @normalize:openvino-num-streams="normalizeOpenvinoNumStreams"
      @update:openvino-scheduling-core-type="setOpenvinoSchedulingCoreType($event as SelectValue)"
      @update:openvino-hyper-threading="setOpenvinoHyperThreading($event as SelectValue)"
      @update:openvino-cpu-pinning="setOpenvinoCpuPinning($event as SelectValue)"
      @update:openvino-num-requests-mode="setOpenvinoNumRequestsMode($event as SelectValue)"
      @update:openvino-num-requests="openvinoNumRequests = $event"
      @normalize:openvino-num-requests="normalizeOpenvinoNumRequests"
      @update:openvino-inference-precision="setOpenvinoInferencePrecision($event as SelectValue)"
      @update:openvino-npu-turbo="setOpenvinoNpuTurbo($event as SelectValue)"
      @update:openvino-npu-tiles-mode="setOpenvinoNpuTilesMode($event as SelectValue)"
      @update:openvino-npu-tiles="openvinoNpuTiles = $event"
      @normalize:openvino-npu-tiles="normalizeOpenvinoNpuTiles"
      @update:openvino-npu-compilation-mode-params="openvinoNpuCompilationModeParams = $event"
      @update:tensorrt-optimization-profile-index="setTensorrtOptimizationProfileIndex($event as SelectValue)"
      @update:tensorrt-pinned-output="setTensorrtPinnedOutput($event as SelectValue)"
      @update:keep-warm-enabled="setKeepWarmEnabled($event as SelectValue)"
      @update:keep-warm-interval-seconds="keepWarmIntervalSeconds = $event"
      @normalize:keep-warm-interval-seconds="normalizeKeepWarmIntervalSeconds"
    />

    <DeploymentInstanceTable
      v-else-if="activeTab === 'instances'"
      :project-id="selectedProjectId"
      :project-name="selectedProjectName"
      :deployments="deployments"
      :runtime-mode="runtimeMode"
      :runtime-mode-options="runtimeModeOptions"
      :runtime-snapshots="runtimeSnapshotsByDeployment"
      :running-actions="runningActionByDeployment"
      :can-write="canWriteModels"
      :can-manage-transfers="canManageTransfers"
      :loading="loading"
      :export-for="id => transferPanel?.exportFor(id)"
      :version-labels-by-id="versionLabelsById"
      @refresh="refreshPage"
      @update:runtime-mode="setRuntimeMode"
      @open-capabilities="capabilitiesDrawerOpen = true"
      @create="openCreateWizard"
      @import="openDeploymentImportDialog"
      @open-details="openDeploymentStatusDrawer"
      @start="runStatusAction($event, runtimeMode, 'start')"
      @stop="openStopDeploymentDialog"
      @warmup="runHealthAction($event, runtimeMode, 'warmup')"
      @reset="openResetDeploymentDialog"
      @delete="openDeleteDeploymentDialog"
      @export-updated="transferPanel?.store($event)"
    />

    <DeploymentTransferRecordsTab
      v-else-if="selectedProjectId"
      :project-id="selectedProjectId"
      :project-name="selectedProjectName"
      :direction="activeTab === 'imports' ? 'import' : 'export'"
      :items="transferItems"
      :deployments="deployments"
      :runtime-snapshots="runtimeSnapshotsByDeployment"
      :version-labels-by-id="versionLabelsById"
      :can-write="canManageTransfers"
      :refreshing="false"
      @refresh="transferPanel?.refresh()"
      @begin-import="openDeploymentImportDialog"
      @open-import="transferPanel?.open($event)"
      @cancel="transferPanel?.cancel($event)"
      @dismiss="transferPanel?.dismiss($event)"
      @updated="transferPanel?.store($event)"
    />

    <DeploymentSourcePickerDialog
      :open="deploymentSourcePickerOpen"
      :loading="sourceModelsLoading"
      :detail-loading="sourceModelDetailLoading"
      :task-type="selectedTaskType"
      :task-type-options="versionSource ? taskTypeOptions.filter(option => option.value === versionSource?.taskType) : taskTypeOptions"
      :models="sourceModels"
      :selected-model-id="selectedSourceModelId"
      :selected-model-detail="selectedSourceModelDetail"
      :selected-build-id="modelBuildId"
      :version-id="versionSource?.versionId"
      :build-id="versionSource?.buildId"
      :devices="sessionStore.bootstrap?.devices ?? null"
      @close="closeDeploymentSourcePicker"
      @change-task-type="setTaskType"
      @select-model="selectDeploymentSourceModel"
      @apply-source="applyDeploymentSource"
    />

    <!-- Stop Deployment Confirmation -->
    <ConfirmDialog
      v-if="pendingStopDeployment"
      :title="t('deploymentWorkspace.dialogs.stopNamedTitle', { name: deploymentCardTitle(pendingStopDeployment) })"
      :message="stopReferences.length ? t('deploymentWorkspace.dialogs.stopNamedMessage') : t('deploymentWorkspace.dialogs.stopMessage')"
      :confirm-label="t('deploymentWorkspace.actions.confirmStop')"
      :cancel-label="t('common.cancel')"
      :busy="!!deploymentRunningAction(pendingStopDeployment.deployment_instance_id)"
      confirm-variant="danger"
      size="medium"
      panel-class="deployment-confirm-dialog"
      @cancel="pendingStopDeploymentId = null"
      @confirm="confirmStopDeployment"
    >
      <template #title-icon>
        <AlertTriangle class="dialog-title-icon is-warning" :size="20" aria-hidden="true" />
      </template>
      <div v-if="stopReferences.length" class="dialog-table-wrap">
        <table>
          <thead>
            <tr>
              <th>{{ t('deploymentWorkspace.dialogs.stopAppName') }}</th>
              <th>{{ t('deploymentWorkspace.dialogs.stopAppType') }}</th>
              <th>{{ t('deploymentWorkspace.dialogs.stopAppStatus') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="refItem in stopReferences" :key="refItem.workflow_runtime_id">
              <td><strong>{{ refItem.display_name || refItem.workflow_runtime_id }}</strong></td>
              <td>Runtime</td>
              <td>
                <span class="dialog-dot-status" :class="{ 'is-running': refItem.observed_state === 'running' }">
                  <span aria-hidden="true" />{{ refItem.observed_state }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="dialog-sub-note">
        {{ t('deploymentWorkspace.dialogs.stopNoRefsMessage', { busy: stopBusyCount }) }}
      </p>
      <div class="dialog-info-bar">
        <Info :size="15" aria-hidden="true" />
        <span>{{ t('deploymentWorkspace.dialogs.stopFooterHint') }}</span>
      </div>
    </ConfirmDialog>

    <!-- Reset Deployment Confirmation / Busy Blocker -->
    <ConfirmDialog
      v-if="pendingResetDeployment"
      :title="resetBusyCount > 0 ? t('deploymentWorkspace.dialogs.resetBlockedTitle') : t('deploymentWorkspace.dialogs.resetTitle')"
      :confirm-label="resetBusyCount > 0 ? t('deploymentWorkspace.actions.recheck') : t('deploymentWorkspace.actions.confirmReset')"
      :cancel-label="resetBusyCount > 0 ? t('common.close') : t('common.cancel')"
      :confirm-disabled="resetChecking"
      :confirm-variant="resetBusyCount > 0 ? 'primary' : 'danger'"
      :busy="resetChecking || !!deploymentRunningAction(pendingResetDeployment.deployment_instance_id)"
      size="medium"
      panel-class="deployment-confirm-dialog"
      @cancel="pendingResetDeploymentId = null"
      @confirm="resetBusyCount > 0 ? recheckResetDeployment() : confirmResetDeployment()"
    >
      <template #title-icon>
        <AlertCircle class="dialog-title-icon is-warning" :size="20" aria-hidden="true" />
      </template>
      <template v-if="resetBusyCount > 0" #leading-actions>
        <Button size="sm" variant="secondary" disabled>
          {{ t('deploymentWorkspace.actions.confirmReset') }}
        </Button>
      </template>
      <dl class="deployment-dialog-card">
        <div><dt>{{ t('deploymentWorkspace.columns.name') }}</dt><dd>{{ deploymentCardTitle(pendingResetDeployment) }}</dd></div>
        <div><dt>{{ t('deploymentWorkspace.dialogs.resetTargetArtifact') }}</dt><dd>{{ formatDeploymentBackend(pendingResetDeployment.runtime_backend) }} {{ (pendingResetDeployment.runtime_precision || 'fp32').toUpperCase() }}</dd></div>
        <div><dt>{{ t('deploymentWorkspace.dialogs.resetTargetRuntime') }}</dt><dd>{{ formatDeploymentDeviceName(pendingResetDeployment.device_name) || t('deploymentOps.options.automaticDefault') }}</dd></div>
        <div><dt>{{ t('deploymentOps.fields.instanceCount') }}</dt><dd>{{ t('deploymentWorkspace.dialogs.resetInstanceSummary', { count: pendingResetDeployment.runtime_configuration.execution.instance_count, mode: t(`deploymentOps.runtimeModes.${runtimeMode}`) }) }}</dd></div>
        <div><dt>{{ t('deploymentWorkspace.dialogs.resetBusyCount') }}</dt><dd>{{ resetBusyCount }}</dd></div>
        <div>
          <dt>{{ t('deploymentWorkspace.columns.status') }}</dt>
          <dd>
            <span class="dialog-dot-status is-running"><span aria-hidden="true" />{{ resetBusyCount > 0 ? t('deploymentWorkspace.states.running') : t('deploymentWorkspace.dialogs.resetStatusCanReset') }}</span>
          </dd>
        </div>
      </dl>

      <div class="dialog-numbered-section">
        <strong>{{ resetBusyCount > 0 ? t('deploymentWorkspace.dialogs.resetCheckTitle') : t('deploymentWorkspace.dialogs.resetImpactTitle') }}</strong>
        <ol v-if="resetBusyCount > 0" class="dialog-numbered-list">
          <li><span>{{ t('deploymentWorkspace.dialogs.resetBusyCount') }}</span><em class="is-warning">{{ t('deploymentWorkspace.dialogs.resetStepBusyCount', { busy: resetBusyCount }) }}</em></li>
          <li><span>{{ t('deploymentOps.actions.reset') }}</span><em>{{ t('deploymentWorkspace.dialogs.resetStepNotExecuted') }}</em></li>
          <li><span>{{ t('deploymentWorkspace.dialogs.resetImpactRetain') }}</span><em class="is-success">{{ t('deploymentWorkspace.dialogs.resetStepRetained') }}</em></li>
        </ol>
        <ol v-else class="dialog-numbered-list">
          <li>{{ t('deploymentWorkspace.dialogs.resetImpactRelease') }}</li>
          <li>{{ t('deploymentWorkspace.dialogs.resetImpactCounters') }}</li>
          <li>{{ t('deploymentWorkspace.dialogs.resetImpactRetain') }}</li>
        </ol>
      </div>

      <div class="dialog-warning-bar">
        <AlertCircle :size="15" aria-hidden="true" />
        <span>{{ resetBusyCount > 0 ? t('deploymentWorkspace.dialogs.resetBusyHint') : t('deploymentWorkspace.dialogs.resetIdleHint') }}</span>
      </div>
    </ConfirmDialog>

    <!-- Delete Deployment Confirmation / Dependency Blocker -->
    <ConfirmDialog
      v-if="pendingDeleteDeployment"
      :title="isDeleteBlocked ? t('deploymentWorkspace.dialogs.deleteBlockedTitle') : t('deploymentWorkspace.dialogs.deleteTitle')"
      :message="isDeleteBlocked ? t('deploymentWorkspace.dialogs.deleteBlockedMessage') : t('common.confirmDelete')"
      :confirm-label="isDeleteBlocked ? t('deploymentWorkspace.actions.viewReferences') : t('deploymentWorkspace.actions.confirmDelete')"
      :cancel-label="isDeleteBlocked ? t('common.close') : t('common.cancel')"
      :confirm-variant="isDeleteBlocked ? 'primary' : 'danger'"
      :busy="isDeleteActionBusy(pendingDeleteDeployment.deployment_instance_id)"
      size="medium"
      panel-class="deployment-confirm-dialog"
      @cancel="closeDeleteDeploymentDialog"
      @confirm="isDeleteBlocked ? openDeleteBlockedReferences() : confirmDeleteDeployment()"
    >
      <template #title-icon>
        <AlertCircle v-if="isDeleteBlocked" class="dialog-title-icon is-warning" :size="20" aria-hidden="true" />
        <Trash2 v-else class="dialog-title-icon is-danger" :size="20" aria-hidden="true" />
      </template>

      <template v-if="isDeleteBlocked">
        <div v-if="deleteReferences.length" class="dialog-table-wrap">
          <table>
            <thead>
              <tr>
                <th>{{ t('deploymentWorkspace.drawer.referenceObject') }}</th>
                <th>{{ t('deploymentWorkspace.columns.status') }}</th>
                <th>{{ t('deploymentWorkspace.columns.actions') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="refItem in deleteReferences" :key="refItem.workflow_runtime_id">
                <td><strong>{{ refItem.display_name || refItem.workflow_runtime_id }}</strong></td>
                <td>
                  <span class="dialog-dot-status" :class="{ 'is-running': refItem.observed_state === 'running' }">
                    <span aria-hidden="true" />Runtime {{ refItem.observed_state }}
                  </span>
                </td>
                <td>
                  <RouterLink class="dialog-action-link" :to="{ path: '/applications', query: { runtime: refItem.workflow_runtime_id } }" @click="closeDeleteDeploymentDialog">
                    {{ t('deploymentWorkspace.actions.view') }}
                  </RouterLink>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="dialog-warning-bar">
          <AlertCircle :size="15" aria-hidden="true" />
          <span>{{ !canDeleteDeployment(pendingDeleteDeployment) ? t('deploymentWorkspace.dialogs.deleteRunningHint') : t('deploymentWorkspace.dialogs.deleteBlockedHint') }}</span>
        </div>
        <p class="dialog-sub-note">{{ t('deploymentWorkspace.dialogs.deleteBlockedModelRetain') }}</p>
      </template>

      <template v-else>
        <dl class="deployment-dialog-card">
          <div><dt>{{ t('deploymentWorkspace.columns.name') }}</dt><dd>{{ deploymentCardTitle(pendingDeleteDeployment) }}</dd></div>
          <div>
            <dt>{{ t('deploymentWorkspace.columns.status') }}</dt>
            <dd><span class="dialog-dot-status"><span aria-hidden="true" />{{ t('deploymentWorkspace.states.stopped') }}</span></dd>
          </div>
          <div><dt>{{ t('deploymentWorkspace.dialogs.deleteActiveRefs') }}</dt><dd>{{ deleteReferences.length }}</dd></div>
          <div><dt>{{ t('deploymentWorkspace.dialogs.deleteCheckedAt') }}</dt><dd>{{ deleteCheckedAtLabel }}</dd></div>
        </dl>
        <div class="dialog-warning-bar">
          <AlertCircle :size="15" aria-hidden="true" />
          <span>{{ t('deploymentWorkspace.dialogs.deleteRetentionHint') }}</span>
        </div>
        <p class="dialog-sub-note">{{ t('deploymentWorkspace.dialogs.deleteRecheckHint') }}</p>
        <InlineError :message="errorMessage" />
      </template>
    </ConfirmDialog>

    <DeploymentStatusDrawer
      :open="statusDrawerOpen"
      :initial-tab="statusDrawerInitialTab"
      :deployment="selectedDeployment"
      :status="selectedRuntimeStatus"
      :health="selectedRuntimeHealth"
      :cpu-resource-summary="selectedCpuResourceSummary"
      :events="deploymentEvents"
      :events-loading="eventsLoading"
      :display-name="selectedDeployment ? deploymentCardTitle(selectedDeployment) : ''"
      :summary-label="selectedDeployment ? deploymentSummaryLabel(selectedDeployment) : ''"
      :summary-tone="selectedDeployment ? deploymentSummaryTone(selectedDeployment) : 'neutral'"
      :version-labels-by-id="versionLabelsById"
      :can-warmup="selectedDeployment ? canWarmupDeployment(selectedDeployment) : false"
      :can-reset="selectedDeployment ? canResetDeployment(selectedDeployment) : false"
      :can-start="selectedDeployment ? canWriteModels && !isRuntimeActionBusy(selectedDeployment) : false"
      :can-stop="selectedDeployment ? canWriteModels && !isRuntimeActionBusy(selectedDeployment) : false"
      @close="closeDeploymentStatusDrawer"
      @start="runStatusAction($event, runtimeMode, 'start')"
      @stop="openStopDeploymentDialog"
      @warmup="runHealthAction($event, runtimeMode, 'warmup')"
      @reset="openResetDeploymentDialog"
      @recheck="recheckStatusDrawerDeployment"
      @refresh-events="loadDeploymentEvents"
    />

    <DeploymentCapabilitiesDrawer
      v-if="capabilitiesDrawerOpen"
      :open="capabilitiesDrawerOpen"
      :devices="sessionStore.bootstrap?.devices ?? null"
      @close="capabilitiesDrawerOpen = false"
      @refresh-devices="refreshHostDevices"
    />
  </section>
</template>

<script setup lang="ts">
import { useCatalogVersionLabel } from '@/modules/models/composables/useCatalogVersionLabel'
import { modelDisplayName, modelVersionDisplayName } from '@/modules/models/model-display-name'
import { modelTaskLabel } from '@/modules/models/model-evaluation-types'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { AlertCircle, AlertTriangle, Cpu, Info, Plus, Trash2, Upload } from '@lucide/vue'
import { useI18n } from 'vue-i18n'
import { formatSystemDateTime } from '@/shared/formatters/date-time'

import {
  createTaskDeployment,
  deleteTaskDeployment,
  getDeploymentInstanceCount,
  getDeploymentRuntimeCapabilities,
  listTaskDeploymentEvents,
  listTaskDeployments,
  runTaskDeploymentHealthAction,
  runTaskDeploymentStatusAction,
  type DeploymentBackendOptions,
  type DeploymentRuntimeCapabilities,
  type DeploymentRuntimeConfiguration,
  type DeploymentRuntimeMode,
  type DeploymentStatusAction,
  type DeploymentHealthAction,
  type ModelTaskType,
  type TaskDeploymentInstance,
  type TaskDeploymentProcessEvent,
  type TaskDeploymentProcessStatus,
  type TaskDeploymentRuntimeHealth,
} from '../services/deployment.service'
import DeploymentCapabilitiesDrawer from '../components/DeploymentCapabilitiesDrawer.vue'
import DeploymentCreateWizard from '../components/DeploymentCreateWizard.vue'
import DeploymentInstanceTable from '../components/DeploymentInstanceTable.vue'
import DeploymentSourcePickerDialog from '../components/DeploymentSourcePickerDialog.vue'
import DeploymentStatusDrawer, { type DeploymentStatusDrawerTab } from '../components/DeploymentStatusDrawer.vue'
import DeploymentTransferPanel from '../components/DeploymentTransferPanel.vue'
import DeploymentTransferRecordsTab from '../components/DeploymentTransferRecordsTab.vue'
import type { DeploymentSourceSelection } from '../components/deployment-source.types'
import { isModelVersionTaskType, type ModelVersionAction } from '@/modules/models/model-version-action'
import { buildDeploymentDeviceOptions, hasCudaDevice } from '../deployment-device-support'
import {
  computeDeploymentCapacity,
  formatDeploymentBackend,
  formatDeploymentDeviceName,
  resolveDeploymentVisualState,
} from '../deployment-presentation'
import {
  formatTensorRtShape,
  parseTensorRtEngineCapabilities,
  type TensorRtOptimizationProfile,
} from '../tensorrt-engine-capabilities'
import {
  getDeploymentSourceModelDetail,
  listDeploymentSourceModels,
  listProjectModelCatalog,
  type DeploymentSourceModelDetail,
  type DeploymentSourceModelSummary,
} from '@/modules/models/services/model.service'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import ResourceCleanupPanel from '@/shared/ui/components/ResourceCleanupPanel.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import TabList from '@/shared/ui/navigation/TabList.vue'
import {
  listDeploymentReferences,
  previewDeploymentDeletion,
  type DeploymentDeletionPreview,
  type DeploymentReferenceItem,
} from '../services/deployment-transfer.service'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const { t, locale } = useI18n()
const zh = computed(() => locale.value.startsWith('zh'))

type PageTab = 'instances' | 'imports' | 'exports'
type SelectValue = string | number | boolean | null
const TASK_TYPES: readonly ModelTaskType[] = ['detection', 'classification', 'segmentation', 'pose', 'obb']

interface DeploymentListCandidate {
  item: TaskDeploymentInstance
  routeTaskType: ModelTaskType
}

interface DeploymentRuntimeSnapshot {
  status: TaskDeploymentProcessStatus | null
  health: TaskDeploymentRuntimeHealth | null
}

const activeTab = ref<PageTab>('instances')
const createWizardOpen = ref(false)
const capabilitiesDrawerOpen = ref(false)
const wizardCreatedDeployment = ref<TaskDeploymentInstance | null>(null)
const wizardStartFailureMessage = ref<string | null>(null)

const pageTabs = computed(() => [
  { id: 'instances', label: t('deploymentWorkspace.tabs.instances') },
  { id: 'imports', label: t('deploymentWorkspace.tabs.imports') },
  { id: 'exports', label: t('deploymentWorkspace.tabs.exports') },
])

function readRouteTab(): PageTab {
  const value = route?.query?.tab
  if (value === 'imports' || value === 'exports') return value
  return 'instances'
}

function setActiveTab(tab: string): void {
  const normalized: PageTab = tab === 'imports' || tab === 'exports' ? tab : 'instances'
  errorMessage.value = null
  activeTab.value = normalized
  void router?.replace?.({ query: { ...route?.query, tab: normalized === 'instances' ? undefined : normalized } })
}

watch(() => route?.query?.tab, () => {
  activeTab.value = readRouteTab()
}, { immediate: true })

const transferPanel = ref<InstanceType<typeof DeploymentTransferPanel> | null>(null)
const transferFileInput = ref<HTMLInputElement | null>(null)
const transferItems = computed(() => transferPanel.value?.items ?? [])
const deletionPreview = ref<DeploymentDeletionPreview | null>(null)
function openDeploymentImportDialog(): void {
  if (typeof transferPanel.value?.openImportDialog === 'function') {
    transferPanel.value.openImportDialog()
    return
  }
  transferPanel.value?.beginImport()
}
async function uploadDeploymentPackage(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) await transferPanel.value?.upload(file)
}

const versionSource = ref<ModelVersionAction | null>(null)
const versionSourceError = ref<string | null>(null)

const runtimeModeOptions = computed(() => [
  { label: t('deploymentOps.runtimeModes.sync'), value: 'sync' },
  { label: t('deploymentOps.runtimeModes.async'), value: 'async' },
])
const RUNTIME_REFRESH_CONCURRENCY = 4
const DEFAULT_KEEP_WARM_INTERVAL_SECONDS = 0.1

const taskTypeOptions = computed(() => TASK_TYPES.map((taskType) => ({
  label: modelTaskLabel(taskType, zh.value),
  value: taskType,
})))

const deployments = ref<TaskDeploymentInstance[]>([])
const deploymentEvents = ref<TaskDeploymentProcessEvent[]>([])
const loading = ref(false)
const creating = ref(false)
const eventsLoading = ref(false)
const errorMessage = ref<string | null>(null)
const lastCreatedDeployment = ref<TaskDeploymentInstance | null>(null)
const runtimeSnapshotsByDeployment = ref<Record<string, DeploymentRuntimeSnapshot>>({})
const runningActionByDeployment = ref<Record<string, string>>({})
const selectedDeploymentId = ref('')
const statusDrawerOpen = ref(false)
const statusDrawerInitialTab = ref<DeploymentStatusDrawerTab>('overview')
const selectedTaskType = ref<ModelTaskType>('detection')
const deploymentSourcePickerOpen = ref(false)
const sourceModelsLoading = ref(false)
const sourceModelDetailLoading = ref(false)
const sourceModels = ref<DeploymentSourceModelSummary[]>([])
const selectedSourceModelId = ref('')
const selectedSourceModelDetail = ref<DeploymentSourceModelDetail | null>(null)
const selectedDeploymentSource = ref<DeploymentSourceSelection | null>(null)
const wizardModels = ref<DeploymentSourceModelSummary[]>([])
const wizardModelsLoading = ref(false)
const wizardSelectedModelId = ref('')
const wizardSelectedModelDetail = ref<DeploymentSourceModelDetail | null>(null)
const wizardDetailLoading = ref(false)
const pendingDeleteDeploymentId = ref<string | null>(null)
const pendingStopDeploymentId = ref<string | null>(null)
const pendingResetDeploymentId = ref<string | null>(null)
const resetChecking = ref(false)
const stopReferences = ref<DeploymentReferenceItem[]>([])
const deleteReferences = ref<DeploymentReferenceItem[]>([])
const deleteCheckedAt = ref('')
const versionLabelsById = ref<Record<string, { modelName: string; versionLabel: string }>>({})
let versionCatalogSequence = 0

const modelType = ref('')
const modelVersionId = ref('')
const modelBuildId = ref('')
const runtimeProfileId = ref('')
const deviceName = ref('')
const instanceCount = ref(1)
const openvinoPerformanceHint = ref<'latency' | 'throughput' | 'cumulative_throughput' | 'none'>('latency')
const openvinoInferenceNumThreads = ref(1)
const openvinoNumStreams = ref(1)
const openvinoNumRequestsMode = ref<'auto' | 'manual'>('auto')
const openvinoNumRequests = ref(1)
const openvinoSchedulingCoreType = ref<'auto' | 'any_core' | 'pcore_only' | 'ecore_only'>('auto')
const openvinoHyperThreading = ref<'auto' | 'true' | 'false'>('auto')
const openvinoCpuPinning = ref<'auto' | 'true' | 'false'>('auto')
const openvinoInferencePrecision = ref<'auto' | 'f32' | 'f16'>('auto')
const openvinoNpuTurbo = ref<'auto' | 'true' | 'false'>('auto')
const openvinoNpuTilesMode = ref<'auto' | 'manual'>('auto')
const openvinoNpuTiles = ref(1)
const openvinoNpuCompilationModeParams = ref('')
const tensorrtOptimizationProfileIndex = ref(0)
const tensorrtPinnedOutput = ref<'auto' | 'true' | 'false'>('auto')
const keepWarmEnabled = ref<'true' | 'false'>('false')
const keepWarmIntervalSeconds = ref(DEFAULT_KEEP_WARM_INTERVAL_SECONDS)
const runtimeCapabilities = ref<DeploymentRuntimeCapabilities | null>(null)
const runtimeCapabilitiesLoading = ref(false)
const displayName = ref('')
const runtimeMode = ref<DeploymentRuntimeMode>('sync')

const canWriteModels = computed(() => sessionStore.hasScopes(['models:write']))
const canManageTransfers = computed(() => sessionStore.hasScopes(['models:read', 'models:write']))
const selectedProjectId = computed(() => projectStore.selectedProjectId)
const selectedProjectName = computed(() => {
  const proj = projectStore.projects.find(item => item.project_id === projectStore.selectedProjectId)
  return proj?.display_name || projectStore.selectedProjectId || ''
})
const selectedSourceVersionName = useCatalogVersionLabel(() => [
  selectedProjectId.value, selectedDeploymentSource.value?.taskType, selectedDeploymentSource.value?.modelVersionId,
])
const selectedDeployment = computed(() => deployments.value.find((item) => item.deployment_instance_id === selectedDeploymentId.value) ?? null)
const selectedRuntimeStatus = computed(() => deploymentRuntimeStatus(selectedDeploymentId.value))
const selectedRuntimeHealth = computed(() => deploymentRuntimeHealth(selectedDeploymentId.value))

const pendingStopDeployment = computed(() => {
  const id = pendingStopDeploymentId.value
  return id ? deployments.value.find(item => item.deployment_instance_id === id) ?? null : null
})
const stopBusyCount = computed(() => {
  const item = pendingStopDeployment.value
  if (!item) return 0
  return computeDeploymentCapacity(item, deploymentRuntimeHealth(item.deployment_instance_id)).busy
})

const pendingResetDeployment = computed(() => {
  const id = pendingResetDeploymentId.value
  return id ? deployments.value.find(item => item.deployment_instance_id === id) ?? null : null
})
const resetBusyCount = computed(() => {
  const item = pendingResetDeployment.value
  if (!item) return 0
  return computeDeploymentCapacity(item, deploymentRuntimeHealth(item.deployment_instance_id)).busy
})

const selectedCpuResourceSummary = computed(() => {
  const deployment = selectedDeployment.value
  if (
    deployment?.runtime_backend.trim().toLowerCase() !== 'openvino'
    || !deployment.device_name.trim().toLowerCase().startsWith('cpu')
  ) {
    return null
  }
  const manager = asRecord(
    selectedRuntimeHealth.value?.effective_runtime_configuration.cpu_device_resource_manager,
  )
  if (!manager) return null
  const physicalCoreCount = readNonNegativeInteger(manager, 'cpu_physical_core_count')
  const schedulingPolicy = manager.scheduling_policy
  const reservations = Array.isArray(manager.reservations) ? manager.reservations : []
  const reservation = reservations
    .map((item) => asRecord(item))
    .find((item) => item?.deployment_instance_id === deployment.deployment_instance_id)
  const deploymentThreadCapacity = reservation ? readNonNegativeInteger(reservation, 'allocated_thread_count') : null
  const threadsPerInstance = reservation ? readNonNegativeInteger(reservation, 'allocated_threads_per_instance') : null
  if (
    physicalCoreCount === null
    || schedulingPolicy !== 'per_deployment_shared'
    || deploymentThreadCapacity === null
    || threadsPerInstance === null
  ) {
    return null
  }
  return { physicalCoreCount, deploymentThreadCapacity, threadsPerInstance }
})

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function readNonNegativeInteger(record: Record<string, unknown>, key: string): number | null {
  const value = record[key]
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null
}

const pendingDeleteDeployment = computed(() => {
  const deploymentId = pendingDeleteDeploymentId.value
  return deploymentId ? deployments.value.find((item) => item.deployment_instance_id === deploymentId) ?? null : null
})
const isDeleteBlocked = computed(() => {
  if (!pendingDeleteDeployment.value) return false
  return !canDeleteDeployment(pendingDeleteDeployment.value) || deleteReferences.value.length > 0
})
const deleteCheckedAtLabel = computed(() => deleteCheckedAt.value ? formatSystemDateTime(deleteCheckedAt.value) : '—')

const deploymentDeviceLabels = computed(() => ({
  automaticDefault: t('deploymentOps.options.automaticDefault'),
  openvinoAutoDefault: t('deploymentOps.options.openvinoAutoDefault'),
  openvinoGpu: t('deploymentOps.options.openvinoGpu'),
}))
const deploymentDeviceOptions = computed(() => buildDeploymentDeviceOptions(
  sessionStore.bootstrap?.devices ?? null,
  selectedDeploymentSource.value?.runtimeBackend ?? '',
  deploymentDeviceLabels.value,
))
const selectedRuntimeBackend = computed(() => selectedDeploymentSource.value?.runtimeBackend.trim().toLowerCase() ?? '')
const isOpenVinoBackend = computed(() => selectedRuntimeBackend.value === 'openvino')
const isTensorRtBackend = computed(() => selectedRuntimeBackend.value === 'tensorrt')
const tensorRtEngineCapabilities = computed(() => parseTensorRtEngineCapabilities(selectedDeploymentSource.value?.buildMetadata ?? {}))
const showTensorRtSingleProfileRange = computed(() => (
  isTensorRtBackend.value
  && tensorRtEngineCapabilities.value?.inputShapeMode === 'dynamic'
  && tensorRtEngineCapabilities.value.optimizationProfiles.length === 1
))
const showTensorRtProfileSelector = computed(() => (
  isTensorRtBackend.value
  && tensorRtEngineCapabilities.value?.inputShapeMode === 'dynamic'
  && tensorRtEngineCapabilities.value.optimizationProfiles.length > 1
))
const tensorRtSingleProfileRangeLines = computed(() => {
  const profile = tensorRtEngineCapabilities.value?.optimizationProfiles[0]
  return profile ? formatTensorRtProfileRangeLines(profile) : []
})
const tensorRtOptimizationProfileOptions = computed(() => (
  tensorRtEngineCapabilities.value?.optimizationProfiles.map((profile) => ({
    label: t('deploymentOps.runtimeConfig.tensorrtProfileIndex', { index: profile.index }),
    value: profile.index,
    description: formatTensorRtProfileRangeLines(profile).join(' · '),
  })) ?? []
))
const openvinoDeviceKind = computed<'cpu' | 'gpu' | 'npu' | 'auto'>(() => {
  const device = deviceName.value.trim().toLowerCase()
  if (device.startsWith('cpu')) return 'cpu'
  if (device.startsWith('gpu')) return 'gpu'
  if (device.startsWith('npu')) return 'npu'
  return 'auto'
})
const openvinoPerformanceHintOptions = computed(() => {
  const options = [
    { label: t('deploymentOps.options.lowestLatency'), value: 'latency' },
    { label: t('deploymentOps.options.maximumThroughput'), value: 'throughput' },
  ]
  if (openvinoDeviceKind.value === 'auto') {
    options.push({ label: t('deploymentOps.options.cumulativeThroughput'), value: 'cumulative_throughput' })
  }
  options.push({ label: t('deploymentOps.options.openvinoRuntimeDefault'), value: 'none' })
  return options
})
const openvinoSchedulingCoreTypeOptions = computed(() => [
  { label: t('deploymentOps.options.automatic'), value: 'auto' },
  { label: t('deploymentOps.options.anyCore'), value: 'any_core' },
  { label: t('deploymentOps.options.pCoreOnly'), value: 'pcore_only' },
  { label: t('deploymentOps.options.eCoreOnly'), value: 'ecore_only' },
])
const autoBooleanOptions = computed(() => [
  { label: t('deploymentOps.options.automatic'), value: 'auto' },
  { label: t('deploymentOps.options.enabled'), value: 'true' },
  { label: t('deploymentOps.options.disabled'), value: 'false' },
])
const serviceDefaultBooleanOptions = computed(() => [
  { label: t('deploymentOps.options.serviceDefault'), value: 'auto' },
  { label: t('deploymentOps.options.enabled'), value: 'true' },
  { label: t('deploymentOps.options.disabled'), value: 'false' },
])
const enabledDisabledOptions = computed(() => [
  { label: t('deploymentOps.options.disabled'), value: 'false' },
  { label: t('deploymentOps.options.enabled'), value: 'true' },
])
const openvinoInferencePrecisionOptions = computed(() => [
  { label: t('deploymentOps.options.automaticRecommended'), value: 'auto' },
  { label: 'FP16', value: 'f16' },
  ...(openvinoDeviceKind.value === 'gpu' ? [{ label: 'FP32', value: 'f32' }] : []),
])
const openvinoNumRequestsModeOptions = computed(() => [
  { label: t('deploymentOps.options.automaticRecommended'), value: 'auto' },
  { label: t('deploymentOps.options.manual'), value: 'manual' },
])
const autoManualOptions = computed(() => [
  { label: t('deploymentOps.options.automatic'), value: 'auto' },
  { label: t('deploymentOps.options.manual'), value: 'manual' },
])
const openvinoMaxInferenceThreads = computed(() => normalizePositiveInteger(runtimeCapabilities.value?.hardware.cpu_physical_core_count, 1))
const openvinoInferenceThreadOptions = computed(() => Array.from(
  { length: openvinoMaxInferenceThreads.value },
  (_, index) => ({ label: String(index + 1), value: index + 1 }),
))
const openvinoNpuMaxTiles = computed(() => {
  const value = runtimeCapabilities.value?.read_only_properties.npu_max_tiles
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
})
const runtimeCapabilityWarnings = computed(() => runtimeCapabilities.value?.warnings ?? [])

let skipNextRuntimeModeRefresh = false
let runtimeRefreshSequence = 0
let sourceModelLoadSequence = 0
let sourceModelDetailSequence = 0
let runtimeCapabilityLoadSequence = 0
const runtimeRefreshTokenByDeployment = new Map<string, number>()

onMounted(async () => {
  void sessionStore.ensureDeviceBootstrap()
  if (projectStore.projects.length === 0) {
    await projectStore.loadProjects()
  }
  await refreshPage()
})

watch(runtimeMode, () => {
  if (skipNextRuntimeModeRefresh) {
    skipNextRuntimeModeRefresh = false
    return
  }
  clearRuntimeSnapshots()
  void refreshRuntimeSnapshotsAndEvents()
})

watch(selectedTaskType, () => {
  if (deploymentSourcePickerOpen.value && !versionSource.value) {
    void loadDeploymentSourceModels()
  }
})

watch([
  () => route?.query.sourceProject, () => route?.query.sourceModel,
  () => route?.query.sourceVersion, () => route?.query.sourceTask,
  () => route?.query.sourceBuild,
  selectedProjectId, canWriteModels, () => sessionStore.currentUser?.principal_id,
], ([projectId, modelId, versionId, taskType, buildId, currentProject, writable]) => {
  if (versionSource.value) closeDeploymentSourcePicker()
  versionSourceError.value = null
  if (!writable || !currentProject || projectId !== currentProject
    || typeof modelId !== 'string' || !modelId || typeof versionId !== 'string' || !versionId
    || !isModelVersionTaskType(taskType)) return
  if (buildId !== undefined && (typeof buildId !== 'string' || !buildId)) return
  openCreateWizard()
  void openVersionDeploymentSource({ projectId, modelId, versionId, taskType, buildId })
}, { immediate: true })

watch(deploymentDeviceOptions, (options) => {
  if (!options.some((option) => option.value === deviceName.value)) {
    deviceName.value = options[0]?.value ?? ''
  }
})

watch([selectedRuntimeBackend, deviceName], () => {
  void loadRuntimeCapabilities()
})

function openCreateWizard(): void {
  wizardCreatedDeployment.value = null
  wizardStartFailureMessage.value = null
  errorMessage.value = null
  createWizardOpen.value = true
  void loadWizardModels()
}

function closeCreateWizard(): void {
  createWizardOpen.value = false
  wizardCreatedDeployment.value = null
  wizardStartFailureMessage.value = null
  selectedDeploymentSource.value = null
  wizardSelectedModelId.value = ''
  wizardSelectedModelDetail.value = null
  modelType.value = ''
  modelVersionId.value = ''
  modelBuildId.value = ''
  runtimeProfileId.value = ''
  displayName.value = ''
}

async function loadWizardModels(): Promise<void> {
  if (!selectedProjectId.value) return
  wizardModelsLoading.value = true
  try {
    const groups = await Promise.all(
      TASK_TYPES.map(task => Promise.resolve(listDeploymentSourceModels(selectedProjectId.value, task)).then(
        res => (Array.isArray(res) ? res : []),
        () => [],
      )),
    )
    const seen = new Set<string>()
    const merged: DeploymentSourceModelSummary[] = []
    for (const model of groups.flat()) {
      if (model.scope_kind !== 'project' || seen.has(model.model_id)) continue
      seen.add(model.model_id)
      merged.push(model)
    }
    wizardModels.value = merged
    const targetId = selectedDeploymentSource.value?.modelId
      || (wizardSelectedModelId.value && merged.some(m => m.model_id === wizardSelectedModelId.value) ? wizardSelectedModelId.value : '')
      || merged[0]?.model_id
      || ''
    if (targetId) {
      await selectWizardModel(targetId)
    } else {
      wizardSelectedModelId.value = ''
      wizardSelectedModelDetail.value = null
    }
  } finally {
    wizardModelsLoading.value = false
  }
}

async function selectWizardModel(modelId: string): Promise<void> {
  wizardSelectedModelId.value = modelId
  if (!modelId || !selectedProjectId.value) {
    wizardSelectedModelDetail.value = null
    return
  }
  wizardDetailLoading.value = true
  try {
    const detail = await getDeploymentSourceModelDetail(selectedProjectId.value, modelId)
    if (wizardSelectedModelId.value !== modelId) return
    wizardSelectedModelDetail.value = detail
  } catch {
    if (wizardSelectedModelId.value === modelId) wizardSelectedModelDetail.value = null
  } finally {
    if (wizardSelectedModelId.value === modelId) wizardDetailLoading.value = false
  }
}

function selectValueToString(value: SelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}

function setRuntimeMode(value: SelectValue): void {
  runtimeMode.value = selectValueToString(value) === 'async' ? 'async' : 'sync'
}

function setTaskType(value: SelectValue): void {
  const normalized = selectValueToString(value)
  if (['detection', 'classification', 'segmentation', 'pose', 'obb'].includes(normalized)) {
    selectedTaskType.value = normalized as ModelTaskType
  }
}

function setDeviceName(value: SelectValue): void {
  deviceName.value = selectValueToString(value)
}

function setOpenvinoPerformanceHint(value: SelectValue): void {
  const normalized = selectValueToString(value)
  if (['latency', 'throughput', 'cumulative_throughput', 'none'].includes(normalized)) {
    openvinoPerformanceHint.value = normalized as typeof openvinoPerformanceHint.value
  }
}

function setOpenvinoInferenceNumThreads(value: SelectValue): void {
  openvinoInferenceNumThreads.value = normalizePositiveInteger(
    value,
    openvinoInferenceNumThreads.value,
    openvinoMaxInferenceThreads.value,
  )
}

function setOpenvinoSchedulingCoreType(value: SelectValue): void {
  const normalized = selectValueToString(value)
  if (['auto', 'any_core', 'pcore_only', 'ecore_only'].includes(normalized)) {
    openvinoSchedulingCoreType.value = normalized as typeof openvinoSchedulingCoreType.value
  }
}

function setAutoBoolean(value: SelectValue, assign: (normalized: 'auto' | 'true' | 'false') => void): void {
  const normalized = selectValueToString(value)
  if (normalized === 'auto' || normalized === 'true' || normalized === 'false') {
    assign(normalized)
  }
}

function setOpenvinoHyperThreading(value: SelectValue): void {
  setAutoBoolean(value, (normalized) => { openvinoHyperThreading.value = normalized })
}

function setOpenvinoCpuPinning(value: SelectValue): void {
  setAutoBoolean(value, (normalized) => { openvinoCpuPinning.value = normalized })
}

function setOpenvinoNumRequestsMode(value: SelectValue): void {
  openvinoNumRequestsMode.value = selectValueToString(value) === 'manual' ? 'manual' : 'auto'
}

function setOpenvinoInferencePrecision(value: SelectValue): void {
  const normalized = selectValueToString(value)
  if (normalized === 'auto' || normalized === 'f16' || normalized === 'f32') {
    openvinoInferencePrecision.value = normalized
  }
}

function setOpenvinoNpuTurbo(value: SelectValue): void {
  setAutoBoolean(value, (normalized) => { openvinoNpuTurbo.value = normalized })
}

function setOpenvinoNpuTilesMode(value: SelectValue): void {
  openvinoNpuTilesMode.value = selectValueToString(value) === 'manual' ? 'manual' : 'auto'
}

function setTensorrtPinnedOutput(value: SelectValue): void {
  setAutoBoolean(value, (normalized) => { tensorrtPinnedOutput.value = normalized })
}

function setTensorrtOptimizationProfileIndex(value: SelectValue): void {
  const parsed = Number(value)
  const validIndices = tensorRtEngineCapabilities.value?.optimizationProfiles.map((profile) => profile.index) ?? []
  tensorrtOptimizationProfileIndex.value = validIndices.includes(parsed) ? parsed : 0
}

function setKeepWarmEnabled(value: SelectValue): void {
  keepWarmEnabled.value = selectValueToString(value) === 'true' ? 'true' : 'false'
}

function supportedRuntimeField(fieldName: string): boolean {
  const capabilities = runtimeCapabilities.value
  return capabilities?.supported_backend_fields.includes(fieldName) ?? false
}

async function loadRuntimeCapabilities(): Promise<void> {
  const loadSequence = ++runtimeCapabilityLoadSequence
  const backend = selectedRuntimeBackend.value
  const device = deviceName.value.trim()
  runtimeCapabilities.value = null
  if (!backend || !device) return
  runtimeCapabilitiesLoading.value = true
  try {
    const capabilities = await getDeploymentRuntimeCapabilities(backend, device)
    if (loadSequence !== runtimeCapabilityLoadSequence) return
    runtimeCapabilities.value = capabilities
    applyRuntimeCapabilityDefaults(capabilities)
  } catch (error) {
    if (loadSequence !== runtimeCapabilityLoadSequence) return
    runtimeCapabilities.value = null
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.capabilitiesFailed')
  } finally {
    if (loadSequence === runtimeCapabilityLoadSequence) runtimeCapabilitiesLoading.value = false
  }
}

function applyRuntimeCapabilityDefaults(capabilities: DeploymentRuntimeCapabilities): void {
  const configuration = capabilities.default_runtime_configuration
  instanceCount.value = configuration.execution.instance_count
  keepWarmEnabled.value = configuration.lifecycle.keep_warm_enabled === true ? 'true' : 'false'
  keepWarmIntervalSeconds.value = configuration.lifecycle.keep_warm_interval_seconds ?? DEFAULT_KEEP_WARM_INTERVAL_SECONDS
  normalizeKeepWarmIntervalSeconds()
  const options = configuration.backend_options
  if (options.kind === 'openvino-cpu') {
    openvinoPerformanceHint.value = options.performance_hint
    openvinoInferenceNumThreads.value = normalizePositiveInteger(options.inference_num_threads, openvinoMaxInferenceThreads.value, openvinoMaxInferenceThreads.value)
    openvinoNumStreams.value = normalizePositiveInteger(options.num_streams, 1)
    openvinoSchedulingCoreType.value = options.scheduling_core_type
    openvinoHyperThreading.value = formatAutoBoolean(options.enable_hyper_threading)
    openvinoCpuPinning.value = formatAutoBoolean(options.enable_cpu_pinning)
  } else if (options.kind === 'openvino-gpu') {
    openvinoPerformanceHint.value = options.performance_hint
    openvinoNumStreams.value = normalizePositiveInteger(options.num_streams, 1)
    applyOpenvinoNumRequestsDefault(options.num_requests)
    openvinoInferencePrecision.value = options.inference_precision
  } else if (options.kind === 'openvino-npu') {
    openvinoPerformanceHint.value = options.performance_hint
    applyOpenvinoNumRequestsDefault(options.num_requests)
    openvinoInferencePrecision.value = options.inference_precision
    openvinoNpuTurbo.value = formatAutoBoolean(options.turbo)
    applyOpenvinoNpuTilesDefault(options.tiles)
    openvinoNpuCompilationModeParams.value = options.compilation_mode_params ?? ''
  } else if (options.kind === 'openvino-auto') {
    openvinoPerformanceHint.value = options.performance_hint
    applyOpenvinoNumRequestsDefault(options.num_requests)
  } else if (options.kind === 'tensorrt') {
    setTensorrtOptimizationProfileIndex(options.optimization_profile_index)
    tensorrtPinnedOutput.value = options.pinned_output_buffer_enabled === null ? 'auto' : options.pinned_output_buffer_enabled ? 'true' : 'false'
  }
}

function formatAutoBoolean(value: boolean | 'auto'): 'auto' | 'true' | 'false' {
  return value === 'auto' ? 'auto' : value ? 'true' : 'false'
}

function normalizePositiveInteger(value: unknown, fallback: number, maximum?: number): number {
  const parsed = Number(value)
  if (!Number.isInteger(parsed) || parsed < 1) return fallback
  return maximum === undefined ? parsed : Math.min(parsed, maximum)
}

function normalizeInstanceCount(): void {
  instanceCount.value = normalizePositiveInteger(instanceCount.value, 1, 64)
}

function normalizeOpenvinoNumStreams(): void {
  openvinoNumStreams.value = normalizePositiveInteger(openvinoNumStreams.value, 1)
}

function normalizeOpenvinoNumRequests(): void {
  openvinoNumRequests.value = normalizePositiveInteger(openvinoNumRequests.value, 1)
}

function normalizeOpenvinoNpuTiles(): void {
  openvinoNpuTiles.value = normalizePositiveInteger(openvinoNpuTiles.value, 1, openvinoNpuMaxTiles.value ?? undefined)
}

function normalizeKeepWarmIntervalSeconds(): void {
  const parsed = Number(keepWarmIntervalSeconds.value)
  keepWarmIntervalSeconds.value = Number.isFinite(parsed) && parsed >= 0.01 ? parsed : DEFAULT_KEEP_WARM_INTERVAL_SECONDS
}

function applyOpenvinoNumRequestsDefault(value: number | 'auto'): void {
  openvinoNumRequestsMode.value = value === 'auto' ? 'auto' : 'manual'
  openvinoNumRequests.value = value === 'auto' ? 1 : normalizePositiveInteger(value, 1)
}

function applyOpenvinoNpuTilesDefault(value: number | 'auto'): void {
  openvinoNpuTilesMode.value = value === 'auto' ? 'auto' : 'manual'
  openvinoNpuTiles.value = value === 'auto' ? 1 : normalizePositiveInteger(value, 1, openvinoNpuMaxTiles.value ?? undefined)
}

function parseAutoBoolean(value: 'auto' | 'true' | 'false'): boolean | 'auto' {
  return value === 'auto' ? 'auto' : value === 'true'
}

function buildBackendOptions(): DeploymentBackendOptions {
  if (isTensorRtBackend.value) {
    return {
      kind: 'tensorrt',
      optimization_profile_index: resolveTensorRtOptimizationProfileIndex(),
      pinned_output_buffer_enabled: tensorrtPinnedOutput.value === 'auto' ? null : tensorrtPinnedOutput.value === 'true',
      pinned_output_buffer_max_bytes: null,
    }
  }
  if (!isOpenVinoBackend.value) return { kind: 'default' }
  if (openvinoDeviceKind.value === 'cpu') {
    return {
      kind: 'openvino-cpu',
      performance_hint: openvinoPerformanceHint.value,
      inference_num_threads: normalizePositiveInteger(openvinoInferenceNumThreads.value, 1, openvinoMaxInferenceThreads.value),
      num_streams: normalizePositiveInteger(openvinoNumStreams.value, 1),
      scheduling_core_type: openvinoSchedulingCoreType.value,
      enable_hyper_threading: parseAutoBoolean(openvinoHyperThreading.value),
      enable_cpu_pinning: parseAutoBoolean(openvinoCpuPinning.value),
    }
  }
  if (openvinoDeviceKind.value === 'gpu') {
    return {
      kind: 'openvino-gpu',
      performance_hint: openvinoPerformanceHint.value,
      num_streams: normalizePositiveInteger(openvinoNumStreams.value, 1),
      num_requests: openvinoNumRequestsMode.value === 'auto' ? 'auto' : normalizePositiveInteger(openvinoNumRequests.value, 1),
      inference_precision: openvinoInferencePrecision.value,
      queue_priority: 'auto',
      queue_throttle: 'auto',
    }
  }
  if (openvinoDeviceKind.value === 'npu') {
    return {
      kind: 'openvino-npu',
      performance_hint: openvinoPerformanceHint.value,
      num_requests: openvinoNumRequestsMode.value === 'auto' ? 'auto' : normalizePositiveInteger(openvinoNumRequests.value, 1),
      inference_precision: openvinoInferencePrecision.value === 'f32' ? 'auto' : openvinoInferencePrecision.value,
      turbo: parseAutoBoolean(openvinoNpuTurbo.value),
      tiles: openvinoNpuTilesMode.value === 'auto' ? 'auto' : normalizePositiveInteger(openvinoNpuTiles.value, 1, openvinoNpuMaxTiles.value ?? undefined),
      compilation_mode_params: openvinoNpuCompilationModeParams.value.trim() || null,
    }
  }
  return {
    kind: 'openvino-auto',
    performance_hint: openvinoPerformanceHint.value,
    num_requests: openvinoNumRequestsMode.value === 'auto' ? 'auto' : normalizePositiveInteger(openvinoNumRequests.value, 1),
  }
}

function buildRuntimeConfiguration(): DeploymentRuntimeConfiguration {
  normalizeKeepWarmIntervalSeconds()
  return {
    execution: {
      instance_count: normalizePositiveInteger(instanceCount.value, 1, 64),
      isolation_level: 'session',
      overflow_policy: 'reject',
      performance_goal: runtimeCapabilities.value?.default_runtime_configuration.execution.performance_goal ?? 'latency',
    },
    lifecycle: {
      warmup_dummy_inference_count: null,
      warmup_dummy_image_size: null,
      keep_warm_enabled: keepWarmEnabled.value === 'true',
      keep_warm_interval_seconds: keepWarmIntervalSeconds.value,
    },
    backend_options: buildBackendOptions(),
  }
}

function clearRuntimeSnapshots(): void {
  if (Object.keys(runtimeSnapshotsByDeployment.value).length === 0) {
    runtimeRefreshTokenByDeployment.clear()
    return
  }
  runtimeSnapshotsByDeployment.value = {}
  runtimeRefreshTokenByDeployment.clear()
}

function setRuntimeModeWithoutRefresh(mode: DeploymentRuntimeMode): void {
  if (runtimeMode.value === mode) return
  skipNextRuntimeModeRefresh = true
  clearRuntimeSnapshots()
  runtimeMode.value = mode
}

async function openDeploymentSourcePicker(): Promise<void> {
  versionSourceError.value = null
  deploymentSourcePickerOpen.value = true
  await loadDeploymentSourceModels()
}

function closeDeploymentSourcePicker(): void {
  sourceModelLoadSequence += 1
  sourceModelDetailSequence += 1
  sourceModelsLoading.value = false
  sourceModelDetailLoading.value = false
  deploymentSourcePickerOpen.value = false
  versionSource.value = null
}

async function openVersionDeploymentSource(source: ModelVersionAction): Promise<void> {
  const sequence = ++sourceModelLoadSequence
  sourceModelDetailSequence += 1
  versionSource.value = source
  sourceModelsLoading.value = true
  sourceModelDetailLoading.value = false
  try {
    const model = await getDeploymentSourceModelDetail(source.projectId, source.modelId)
    if (sequence !== sourceModelLoadSequence) return
    if (model.project_id !== source.projectId || model.scope_kind !== 'project' || model.task_type !== source.taskType
      || !model.versions.some(item => item.model_version_id === source.versionId)) {
      versionSourceError.value = locale.value.startsWith('zh') ? '此模型版本已不可用。' : 'This model version is no longer available.'
      closeDeploymentSourcePicker()
      return
    }
    if (source.buildId && !model.builds.some(item => item.model_build_id === source.buildId && item.source_model_version_id === source.versionId)) {
      versionSourceError.value = locale.value.startsWith('zh') ? '此模型产物已不可用。' : 'This model artifact is no longer available.'
      closeDeploymentSourcePicker()
      return
    }
    selectedTaskType.value = source.taskType
    sourceModels.value = [model]
    selectedSourceModelId.value = model.model_id
    selectedSourceModelDetail.value = model
    deploymentSourcePickerOpen.value = true
  } catch {
    if (sequence !== sourceModelLoadSequence) return
    versionSourceError.value = t('deploymentOps.messages.sourceModelDetailFailed')
    closeDeploymentSourcePicker()
  } finally {
    if (sequence === sourceModelLoadSequence) sourceModelsLoading.value = false
  }
}

async function loadDeploymentSourceModels(): Promise<void> {
  const loadSequence = ++sourceModelLoadSequence
  sourceModelDetailSequence += 1
  const taskType = selectedTaskType.value
  sourceModelsLoading.value = true
  sourceModelDetailLoading.value = false
  errorMessage.value = null
  try {
    const models = await listDeploymentSourceModels(selectedProjectId.value, taskType)
    if (loadSequence !== sourceModelLoadSequence) return
    const projectModels = models.filter((model) => model.scope_kind === 'project')
    const candidateModelIds = [
      selectedSourceModelId.value,
      selectedDeploymentSource.value?.taskType === taskType ? selectedDeploymentSource.value.modelId : '',
      projectModels[0]?.model_id ?? '',
    ]
    const preferredModelId = candidateModelIds.find(
      (modelId) => projectModels.some((model) => model.model_id === modelId),
    ) ?? ''
    const modelDetail = preferredModelId
      ? await getDeploymentSourceModelDetail(selectedProjectId.value, preferredModelId)
      : null
    if (loadSequence !== sourceModelLoadSequence) return
    sourceModels.value = models
    selectedSourceModelId.value = preferredModelId
    selectedSourceModelDetail.value = modelDetail
  } catch (error) {
    if (loadSequence !== sourceModelLoadSequence) return
    sourceModels.value = []
    selectedSourceModelId.value = ''
    selectedSourceModelDetail.value = null
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.sourceModelsFailed')
  } finally {
    if (loadSequence === sourceModelLoadSequence) sourceModelsLoading.value = false
  }
}

async function selectDeploymentSourceModel(modelId: string): Promise<void> {
  if (versionSource.value) return
  const detailSequence = ++sourceModelDetailSequence
  selectedSourceModelId.value = modelId
  sourceModelDetailLoading.value = true
  errorMessage.value = null
  try {
    const modelDetail = await getDeploymentSourceModelDetail(selectedProjectId.value, modelId)
    if (detailSequence !== sourceModelDetailSequence || selectedSourceModelId.value !== modelId) return
    selectedSourceModelDetail.value = modelDetail
  } catch (error) {
    if (detailSequence !== sourceModelDetailSequence || selectedSourceModelId.value !== modelId) return
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.sourceModelDetailFailed')
  } finally {
    if (detailSequence === sourceModelDetailSequence && selectedSourceModelId.value === modelId) sourceModelDetailLoading.value = false
  }
}

watch([pendingStopDeployment, pendingResetDeployment, pendingDeleteDeployment, locale], () => {
  void nextTick(() => {
    const cancelText = t('common.cancel')
    const closeText = t('common.close')
    for (const closeBtn of document.querySelectorAll<HTMLButtonElement>('.deployment-confirm-dialog .confirm-dialog__close')) {
      if (closeBtn.getAttribute('aria-label') === cancelText) {
        closeBtn.setAttribute('aria-label', closeText)
      }
    }
  })
}, { flush: 'post' })

watch(selectedProjectId, (projectId) => {
  versionLabelsById.value = {}
  if (projectId) void refreshVersionLabels(projectId)
})

function resolveSourceVersionLabel(selection: DeploymentSourceSelection): string {
  const explicit = (selection as { modelVersionName?: string }).modelVersionName?.trim()
  if (explicit) return explicit
  const cached = versionLabelsById.value[selection.modelVersionId]?.versionLabel?.trim()
  if (cached) return cached
  for (const detail of [wizardSelectedModelDetail.value, selectedSourceModelDetail.value]) {
    const version = detail?.versions.find((item) => item.model_version_id === selection.modelVersionId)
    if (version) {
      const formatted = modelVersionDisplayName(version, false)
      if (formatted && formatted !== '—') return formatted
    }
  }
  return ''
}

function applyDeploymentSource(selection: DeploymentSourceSelection): void {
  if (versionSource.value && (selection.modelId !== versionSource.value.modelId
    || selection.modelVersionId !== versionSource.value.versionId
    || (versionSource.value.buildId && selection.modelBuildId !== versionSource.value.buildId))) return
  selectedDeploymentSource.value = selection
  tensorrtOptimizationProfileIndex.value = 0
  selectedSourceModelId.value = selection.modelId
  modelType.value = selection.modelType
  modelVersionId.value = selection.modelVersionId
  modelBuildId.value = selection.modelBuildId
  runtimeProfileId.value = selection.runtimeProfileId
  selectedTaskType.value = selection.taskType
  const deviceOptions = buildDeploymentDeviceOptions(sessionStore.bootstrap?.devices ?? null, selection.runtimeBackend, deploymentDeviceLabels.value)
  if (!deviceOptions.some((option) => option.value === deviceName.value)) deviceName.value = deviceOptions[0]?.value ?? ''
  if (!displayName.value.trim()) {
    const versionLabel = resolveSourceVersionLabel(selection)
    displayName.value = `${selection.modelName} ${versionLabel}`.trim()
  }
  closeDeploymentSourcePicker()
}

function resolveTensorRtOptimizationProfileIndex(): number {
  if (!showTensorRtProfileSelector.value) return 0
  const validIndices = tensorRtEngineCapabilities.value?.optimizationProfiles.map((profile) => profile.index) ?? []
  return validIndices.includes(tensorrtOptimizationProfileIndex.value) ? tensorrtOptimizationProfileIndex.value : 0
}

function formatTensorRtProfileRangeLines(profile: TensorRtOptimizationProfile): string[] {
  return profile.inputs.map((input) => t('deploymentOps.runtimeConfig.tensorrtProfileInputRange', {
    input: input.inputName,
    min: formatTensorRtShape(input.minShape),
    opt: formatTensorRtShape(input.optShape),
    max: formatTensorRtShape(input.maxShape),
  }))
}

function deploymentSourceUnavailableReason(selection: DeploymentSourceSelection): string {
  const runtimeBackend = selection.runtimeBackend.trim().toLowerCase()
  if (runtimeBackend !== 'tensorrt') return ''
  const devices = sessionStore.bootstrap?.devices ?? null
  if (!hasCudaDevice(devices)) return t('deploymentOps.messages.tensorrtCudaUnavailable')
  const tensorrt = readDeviceRecord(devices, 'tensorrt')
  if (tensorrt?.installed !== true) return t('deploymentOps.messages.tensorrtRuntimeUnavailable')
  return ''
}

function readDeviceRecord(record: Record<string, unknown> | null | undefined, key: string): Record<string, unknown> | null {
  const value = record?.[key]
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function deploymentCardTitle(item: TaskDeploymentInstance): string {
  const name = item.display_name.trim()
  const generatedSourceId = item.model_build_id || item.model_version_id
  const generatedName = `${item.model_name} ${generatedSourceId}`.trim()
  if (!name || name === item.deployment_instance_id || name === generatedName) {
    return item.model_name || item.deployment_instance_id
  }
  return name
}

function deploymentSummaryLabel(item: TaskDeploymentInstance): string {
  const snap = deploymentRuntimeSnapshot(item.deployment_instance_id)
  return t(`deploymentWorkspace.states.${resolveDeploymentVisualState(snap?.status, snap?.health).key}`)
}

function deploymentSummaryTone(item: TaskDeploymentInstance): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  const snap = deploymentRuntimeSnapshot(item.deployment_instance_id)
  return resolveDeploymentVisualState(snap?.status, snap?.health).tone
}

function createEmptyRuntimeSnapshot(): DeploymentRuntimeSnapshot {
  return { status: null, health: null }
}

function deploymentRuntimeSnapshot(deploymentId: string): DeploymentRuntimeSnapshot | null {
  return deploymentId ? runtimeSnapshotsByDeployment.value[deploymentId] ?? null : null
}

function deploymentRuntimeStatus(deploymentId: string): TaskDeploymentProcessStatus | null {
  return deploymentRuntimeSnapshot(deploymentId)?.status ?? null
}

function deploymentRuntimeHealth(deploymentId: string): TaskDeploymentRuntimeHealth | null {
  return deploymentRuntimeSnapshot(deploymentId)?.health ?? null
}

function runtimeSnapshotValueEquals(left: unknown, right: unknown): boolean {
  return JSON.stringify(left ?? null) === JSON.stringify(right ?? null)
}

function setDeploymentRuntimeSnapshot(deploymentId: string, patch: Partial<DeploymentRuntimeSnapshot>): void {
  if (!deploymentId) return
  const current = runtimeSnapshotsByDeployment.value[deploymentId] ?? createEmptyRuntimeSnapshot()
  const next: DeploymentRuntimeSnapshot = {
    status: patch.status === undefined ? current.status : patch.status,
    health: patch.health === undefined ? current.health : patch.health,
  }
  if (runtimeSnapshotValueEquals(current.status, next.status) && runtimeSnapshotValueEquals(current.health, next.health)) return
  runtimeSnapshotsByDeployment.value = { ...runtimeSnapshotsByDeployment.value, [deploymentId]: next }
}

function commitDeploymentRuntimeStatus(deploymentId: string, status: TaskDeploymentProcessStatus | null): void {
  setDeploymentRuntimeSnapshot(deploymentId, { status })
}

function commitDeploymentRuntimeHealth(deploymentId: string, health: TaskDeploymentRuntimeHealth | null): void {
  setDeploymentRuntimeSnapshot(deploymentId, { status: health, health })
}

function commitDeploymentRuntimeResult(deploymentId: string, status: TaskDeploymentProcessStatus | null, health: TaskDeploymentRuntimeHealth | null): void {
  setDeploymentRuntimeSnapshot(deploymentId, { status: health ?? status, health })
}

function deleteDeploymentRuntimeSnapshot(deploymentId: string): void {
  if (!runtimeSnapshotsByDeployment.value[deploymentId]) return
  const nextSnapshots = { ...runtimeSnapshotsByDeployment.value }
  delete nextSnapshots[deploymentId]
  runtimeSnapshotsByDeployment.value = nextSnapshots
  runtimeRefreshTokenByDeployment.delete(deploymentId)
}

function beginDeploymentRuntimeRefresh(deploymentId: string): number {
  const token = ++runtimeRefreshSequence
  runtimeRefreshTokenByDeployment.set(deploymentId, token)
  return token
}

function isCurrentDeploymentRuntimeRefresh(deploymentId: string, token: number): boolean {
  return runtimeRefreshTokenByDeployment.get(deploymentId) === token
}

function finishDeploymentRuntimeRefresh(deploymentId: string, token: number): void {
  if (isCurrentDeploymentRuntimeRefresh(deploymentId, token)) runtimeRefreshTokenByDeployment.delete(deploymentId)
}

function normalizeDeploymentRuntimeMode(value: string | null | undefined): DeploymentRuntimeMode {
  return String(value ?? '').trim().toLowerCase() === 'async' ? 'async' : 'sync'
}

function normalizeModelTaskType(value: string | null | undefined): ModelTaskType {
  const normalized = String(value ?? '').trim().toLowerCase()
  return TASK_TYPES.includes(normalized as ModelTaskType) ? normalized as ModelTaskType : 'detection'
}

function taskTypeForDeployment(item: TaskDeploymentInstance): ModelTaskType {
  return normalizeModelTaskType(item.task_type)
}

function setDeploymentRunningAction(deploymentId: string, action: string | null): void {
  const nextActions = { ...runningActionByDeployment.value }
  if (action) nextActions[deploymentId] = action
  else delete nextActions[deploymentId]
  runningActionByDeployment.value = nextActions
}

function deploymentRunningAction(deploymentId: string): string | null {
  return runningActionByDeployment.value[deploymentId] ?? null
}

function isDeleteActionBusy(deploymentId: string): boolean {
  return deploymentRunningAction(deploymentId) === 'delete'
}

function isRuntimeActionBusy(item: TaskDeploymentInstance): boolean {
  return deploymentRunningAction(item.deployment_instance_id) !== null
}

function canDeleteDeployment(item: TaskDeploymentInstance): boolean {
  if (!canWriteModels.value || isRuntimeActionBusy(item)) return false
  const status = deploymentRuntimeStatus(item.deployment_instance_id)
  if (!status) return true
  return status.desired_state === 'stopped' && status.observed_state === 'stopped' && status.process_state === 'stopped'
}

function canWarmupDeployment(item: TaskDeploymentInstance): boolean {
  return canWriteModels.value && !isRuntimeActionBusy(item) && !isDeploymentWarmupComplete(item)
}

function isDeploymentWarmupComplete(item: TaskDeploymentInstance): boolean {
  const health = deploymentRuntimeHealth(item.deployment_instance_id)
  return health ? isRuntimeHealthWarmupComplete(health, getDeploymentInstanceCount(item)) : false
}

function isRuntimeHealthWarmupComplete(health: TaskDeploymentRuntimeHealth, fallbackInstanceCount: number): boolean {
  const expectedInstanceCount = Math.max(0, Number(health.instance_count || fallbackInstanceCount || 0))
  const warmedInstanceCount = Math.max(0, Number(health.warmed_instance_count || 0))
  const instancesReady = expectedInstanceCount > 0 && warmedInstanceCount >= expectedInstanceCount
  if (!instancesReady) return false
  if (health.keep_warm?.enabled === false) return true
  return health.keep_warm?.activated === true
}

function canResetDeployment(item: TaskDeploymentInstance): boolean {
  return canWriteModels.value && !isRuntimeActionBusy(item)
}

async function refreshHostDevices(): Promise<void> {
  try {
    if (typeof sessionStore.loadBootstrap === 'function') {
      await sessionStore.loadBootstrap({ includeDevices: true })
    } else if (typeof sessionStore.ensureDeviceBootstrap === 'function') {
      await sessionStore.ensureDeviceBootstrap()
    }
  } catch {
    // 设备摘要刷新失败时保留已有 bootstrap，不阻断能力抽屉使用
  }
}

function seedVersionLabelsFromDeployments(
  items: TaskDeploymentInstance[],
  target: Record<string, { modelName: string; versionLabel: string }> = versionLabelsById.value,
): Record<string, { modelName: string; versionLabel: string }> {
  let changed = false
  const next = { ...target }
  for (const item of items) {
    if (!item.model_version_id) continue
    const displayModelName = item.model_display_name?.trim() || ''
    const versionLabel = item.model_version_number ? `v${item.model_version_number}` : ''
    if (!displayModelName && !versionLabel) continue
    const existing = next[item.model_version_id]
    const mergedModelName = existing?.modelName || displayModelName || item.model_name
    const mergedVersionLabel = existing?.versionLabel || versionLabel
    if (!existing || existing.modelName !== mergedModelName || existing.versionLabel !== mergedVersionLabel) {
      next[item.model_version_id] = {
        modelName: mergedModelName,
        versionLabel: mergedVersionLabel,
      }
      changed = true
    }
  }
  return changed ? next : target
}

async function refreshVersionLabels(projectId: string): Promise<void> {
  const seq = ++versionCatalogSequence
  if (!projectId) {
    versionLabelsById.value = {}
    return
  }
  const next = seedVersionLabelsFromDeployments(deployments.value, {})
  const limit = 100
  try {
    if (typeof listProjectModelCatalog !== 'function') {
      versionLabelsById.value = next
      return
    }
    for (let offset = 0; ; offset += limit) {
      const page = await Promise.resolve(listProjectModelCatalog({ projectId, offset, limit })).catch(() => null)
      if (seq !== versionCatalogSequence || selectedProjectId.value !== projectId) return
      const items = page?.items
      if (!Array.isArray(items) || items.length === 0) break
      for (const model of items) {
        const modelName = modelDisplayName(model)
        const versions = Array.isArray(model.available_versions) ? model.available_versions : []
        for (const version of versions) {
          if (!version?.model_version_id) continue
          const shortLabel = modelVersionDisplayName(version, false)
          const resolvedLabel = shortLabel !== '—' ? shortLabel : modelVersionDisplayName(version, true)
          const existing = next[version.model_version_id]
          next[version.model_version_id] = {
            modelName: modelName || existing?.modelName || '',
            versionLabel: resolvedLabel === '—' ? (existing?.versionLabel ?? '') : resolvedLabel,
          }
        }
      }
      if (offset + limit >= (page?.total ?? 0)) break
    }
    if (seq === versionCatalogSequence && selectedProjectId.value === projectId) {
      versionLabelsById.value = seedVersionLabelsFromDeployments(deployments.value, next)
    }
  } catch {
    if (seq === versionCatalogSequence && selectedProjectId.value === projectId) {
      versionLabelsById.value = seedVersionLabelsFromDeployments(deployments.value, next)
    }
  }
}

async function refreshPage(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  const projectId = selectedProjectId.value
  if (projectId) void refreshVersionLabels(projectId)
  else versionLabelsById.value = {}
  try {
    deployments.value = await listAllTaskDeployments()
    versionLabelsById.value = seedVersionLabelsFromDeployments(deployments.value)
    if (!deployments.value.some((item) => item.deployment_instance_id === selectedDeploymentId.value)) {
      selectedDeploymentId.value = deployments.value[0]?.deployment_instance_id ?? ''
      statusDrawerOpen.value = false
    }
    const requested = typeof route?.query?.deployment === 'string' ? route.query.deployment : ''
    if (requested && deployments.value.some(item => item.deployment_instance_id === requested)) {
      selectedDeploymentId.value = requested
      statusDrawerOpen.value = true
    }
    await refreshRuntimeSnapshotsAndEvents()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

async function listAllTaskDeployments(): Promise<TaskDeploymentInstance[]> {
  const groups = await Promise.all(
    TASK_TYPES.map(async (taskType) => {
      const items = await listTaskDeployments(taskType, selectedProjectId.value)
      return items.map((item) => ({
        item: { ...item, task_type: item.task_type || taskType },
        routeTaskType: taskType,
      }))
    }),
  )

  const byDeploymentId = new Map<string, DeploymentListCandidate>()
  for (const candidate of groups.flat()) {
    const existing = byDeploymentId.get(candidate.item.deployment_instance_id)
    if (!existing || shouldPreferDeploymentCandidate(candidate, existing)) {
      byDeploymentId.set(candidate.item.deployment_instance_id, candidate)
    }
  }

  return Array.from(byDeploymentId.values())
    .map((candidate) => candidate.item)
    .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))
}

function shouldPreferDeploymentCandidate(next: DeploymentListCandidate, current: DeploymentListCandidate): boolean {
  const nextMatchesRoute = normalizeModelTaskType(next.item.task_type) === next.routeTaskType
  const currentMatchesRoute = normalizeModelTaskType(current.item.task_type) === current.routeTaskType
  if (nextMatchesRoute !== currentMatchesRoute) return nextMatchesRoute

  const nextHasBuild = Boolean(next.item.model_build_id)
  const currentHasBuild = Boolean(current.item.model_build_id)
  if (nextHasBuild !== currentHasBuild) return nextHasBuild

  return Date.parse(next.item.updated_at) > Date.parse(current.item.updated_at)
}

async function selectDeployment(deploymentId: string): Promise<void> {
  if (selectedDeploymentId.value !== deploymentId) deploymentEvents.value = []
  selectedDeploymentId.value = deploymentId
  const deployment = selectedDeployment.value
  await Promise.all([
    deployment ? refreshDeploymentRuntimeSnapshot(deployment, { showError: true }) : Promise.resolve(null),
    loadDeploymentEvents(),
  ])
}

function openDeploymentStatusDrawer(deploymentId: string, initialTab: DeploymentStatusDrawerTab = 'overview'): void {
  statusDrawerInitialTab.value = initialTab
  statusDrawerOpen.value = true
  void selectDeployment(deploymentId)
}

function closeDeploymentStatusDrawer(): void {
  statusDrawerOpen.value = false
  statusDrawerInitialTab.value = 'overview'
}

async function recheckStatusDrawerDeployment(deploymentId: string): Promise<void> {
  const target = deployments.value.find(item => item.deployment_instance_id === deploymentId)
  if (!target) return
  await Promise.all([
    refreshDeploymentRuntimeSnapshot(target, { showError: true }),
    loadDeploymentEvents(),
  ])
}

async function loadDeploymentEvents(): Promise<void> {
  const deployment = selectedDeployment.value
  if (!deployment) {
    deploymentEvents.value = []
    return
  }
  eventsLoading.value = true
  errorMessage.value = null
  try {
    deploymentEvents.value = await listTaskDeploymentEvents(
      taskTypeForDeployment(deployment),
      deployment.deployment_instance_id,
      runtimeMode.value,
    )
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.eventsFailed')
  } finally {
    eventsLoading.value = false
  }
}

async function refreshRuntimeSnapshotsAndEvents(): Promise<void> {
  await loadDeploymentEvents()
  void refreshRuntimeSnapshotsForDeployments(deployments.value)
}

async function refreshRuntimeSnapshotsForDeployments(items: TaskDeploymentInstance[]): Promise<void> {
  const failures: string[] = []
  let cursor = 0
  const workerCount = Math.min(RUNTIME_REFRESH_CONCURRENCY, items.length)
  await Promise.all(Array.from({ length: workerCount }, async () => {
    while (cursor < items.length) {
      const item = items[cursor]
      cursor += 1
      const message = await refreshDeploymentRuntimeSnapshot(item)
      if (message) failures.push(message)
    }
  }))
  const failed = failures[0]
  if (failed) errorMessage.value = failed
}

async function refreshDeploymentRuntimeSnapshot(deployment: TaskDeploymentInstance, options: { showError?: boolean } = {}): Promise<string | null> {
  const deploymentId = deployment.deployment_instance_id
  const refreshToken = beginDeploymentRuntimeRefresh(deploymentId)
  if (options.showError) errorMessage.value = null
  try {
    const status = await runTaskDeploymentStatusAction(taskTypeForDeployment(deployment), deploymentId, runtimeMode.value, 'status')
    let health: TaskDeploymentRuntimeHealth | null = null
    if (status.process_state === 'running' || status.observed_state === 'running' || status.observed_state === 'degraded') {
      try {
        health = await runTaskDeploymentHealthAction(taskTypeForDeployment(deployment), deploymentId, runtimeMode.value, 'health')
      } catch {
        health = null
      }
    }
    if (!isCurrentDeploymentRuntimeRefresh(deploymentId, refreshToken)) return null
    commitDeploymentRuntimeResult(deploymentId, status, health)
    return null
  } catch (error) {
    if (!isCurrentDeploymentRuntimeRefresh(deploymentId, refreshToken)) return null
    const message = error instanceof Error ? error.message : t('deploymentOps.messages.actionFailed')
    if (options.showError) errorMessage.value = message
    return message
  } finally {
    finishDeploymentRuntimeRefresh(deploymentId, refreshToken)
  }
}

async function handleWizardSubmit(payload: { startAfterCreate: boolean }): Promise<void> {
  if (!selectedDeploymentSource.value || !modelType.value.trim()) {
    errorMessage.value = t('deploymentOps.messages.sourceRequired')
    return
  }
  const unavailableReason = deploymentSourceUnavailableReason(selectedDeploymentSource.value)
  if (unavailableReason) {
    errorMessage.value = unavailableReason
    return
  }
  normalizeInstanceCount()
  if (isOpenVinoBackend.value && openvinoDeviceKind.value !== 'npu') normalizeOpenvinoNumStreams()
  if (isOpenVinoBackend.value && openvinoNumRequestsMode.value === 'manual') normalizeOpenvinoNumRequests()
  if (openvinoDeviceKind.value === 'npu' && openvinoNpuTilesMode.value === 'manual') normalizeOpenvinoNpuTiles()

  creating.value = true
  errorMessage.value = null
  wizardStartFailureMessage.value = null
  try {
    const created = await createTaskDeployment({
      taskType: selectedDeploymentSource.value.taskType,
      projectId: selectedProjectId.value,
      modelType: modelType.value.trim(),
      modelVersionId: modelVersionId.value.trim(),
      modelBuildId: modelBuildId.value.trim(),
      runtimeProfileId: runtimeProfileId.value.trim(),
      runtimeBackend: selectedDeploymentSource.value.runtimeBackend.trim(),
      runtimePrecision: selectedDeploymentSource.value.runtimePrecision === 'fp16' ? 'fp16' : 'fp32',
      deviceName: deviceName.value.trim(),
      runtimeConfiguration: buildRuntimeConfiguration(),
      displayName: displayName.value,
    })
    lastCreatedDeployment.value = created
    wizardCreatedDeployment.value = created
    selectedDeploymentId.value = created.deployment_instance_id
    if (payload.startAfterCreate) {
      try {
        await runStatusAction(created.deployment_instance_id, runtimeMode.value, 'start', { rethrow: true })
      } catch (startCause) {
        const message = startCause instanceof Error ? startCause.message : t('deploymentOps.messages.actionFailed')
        errorMessage.value = null
        wizardStartFailureMessage.value = t('deploymentWorkspace.wizard.createdStartFailed', {
          id: created.deployment_instance_id,
          error: message,
        })
      }
    }
    await refreshPage()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.createFailed')
  } finally {
    creating.value = false
  }
}

async function runStatusAction(
  deploymentId: string,
  modeValue: string,
  action: DeploymentStatusAction,
  options?: { rethrow?: boolean },
): Promise<void> {
  const mode = normalizeDeploymentRuntimeMode(modeValue)
  const deployment = deployments.value.find((item) => item.deployment_instance_id === deploymentId)
  const taskType = deployment ? taskTypeForDeployment(deployment) : selectedTaskType.value
  selectedDeploymentId.value = deploymentId
  setRuntimeModeWithoutRefresh(mode)
  setDeploymentRunningAction(deploymentId, `${mode}:${action}`)
  errorMessage.value = null
  try {
    const status = await runTaskDeploymentStatusAction(taskType, deploymentId, mode, action)
    if (action === 'status') {
      commitDeploymentRuntimeStatus(deploymentId, status)
    } else {
      let health: TaskDeploymentRuntimeHealth | null = null
      try {
        health = await runTaskDeploymentHealthAction(taskType, deploymentId, mode, 'health')
      } catch {
        health = null
      }
      commitDeploymentRuntimeResult(deploymentId, status, health)
    }
    await loadDeploymentEvents()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.actionFailed')
    if (options?.rethrow) throw error
  } finally {
    setDeploymentRunningAction(deploymentId, null)
  }
}

async function runHealthAction(deploymentId: string, modeValue: string, action: DeploymentHealthAction): Promise<void> {
  const mode = normalizeDeploymentRuntimeMode(modeValue)
  const deployment = deployments.value.find((item) => item.deployment_instance_id === deploymentId)
  const taskType = deployment ? taskTypeForDeployment(deployment) : selectedTaskType.value
  selectedDeploymentId.value = deploymentId
  setRuntimeModeWithoutRefresh(mode)
  setDeploymentRunningAction(deploymentId, `${mode}:${action}`)
  errorMessage.value = null
  try {
    if (action === 'warmup') {
      const currentHealth = await loadDeploymentRuntimeHealthBeforeWarmup(taskType, deploymentId, mode)
      if (currentHealth && isRuntimeHealthWarmupComplete(currentHealth, deployment ? getDeploymentInstanceCount(deployment) : 0)) {
        await loadDeploymentEvents()
        return
      }
    }
    const health = await runTaskDeploymentHealthAction(taskType, deploymentId, mode, action)
    commitDeploymentRuntimeHealth(deploymentId, health)
    await loadDeploymentEvents()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.actionFailed')
  } finally {
    setDeploymentRunningAction(deploymentId, null)
  }
}

function openStopDeploymentDialog(deploymentId: string): void {
  pendingStopDeploymentId.value = deploymentId
  stopReferences.value = []
  if (selectedProjectId.value) {
    void listDeploymentReferences(selectedProjectId.value, deploymentId)
      .then((res) => {
        if (pendingStopDeploymentId.value === deploymentId) stopReferences.value = res.items
      })
      .catch(() => { /* 引用只读展示，不阻断停止确认 */ })
  }
}

async function confirmStopDeployment(): Promise<void> {
  const target = pendingStopDeployment.value
  if (!target) return
  pendingStopDeploymentId.value = null
  stopReferences.value = []
  await runStatusAction(target.deployment_instance_id, runtimeMode.value, 'stop')
}

async function openResetDeploymentDialog(deploymentId: string): Promise<void> {
  pendingResetDeploymentId.value = deploymentId
  await recheckResetDeployment()
}

async function recheckResetDeployment(): Promise<void> {
  const target = pendingResetDeployment.value
  if (!target) return
  resetChecking.value = true
  try {
    const health = await runTaskDeploymentHealthAction(taskTypeForDeployment(target), target.deployment_instance_id, runtimeMode.value, 'health')
    commitDeploymentRuntimeHealth(target.deployment_instance_id, health)
  } catch {
    // 若尚未运行则保留已有快照状态，不阻断只读检查。
  } finally {
    resetChecking.value = false
  }
}

async function confirmResetDeployment(): Promise<void> {
  const target = pendingResetDeployment.value
  if (!target || resetBusyCount.value > 0) return
  pendingResetDeploymentId.value = null
  await runHealthAction(target.deployment_instance_id, runtimeMode.value, 'reset')
}

async function openDeleteDeploymentDialog(deploymentId: string): Promise<void> {
  const deployment = deployments.value.find((item) => item.deployment_instance_id === deploymentId)
  if (!deployment || !selectedProjectId.value) return
  errorMessage.value = null
  deleteReferences.value = []
  deletionPreview.value = null
  deleteCheckedAt.value = new Date().toISOString()
  const refs = await listDeploymentReferences(selectedProjectId.value, deploymentId)
    .catch(() => ({ items: [], total: 0 }))
  deleteReferences.value = refs.items
  if (!canDeleteDeployment(deployment) || refs.items.length > 0) {
    pendingDeleteDeploymentId.value = deploymentId
    return
  }
  try {
    deletionPreview.value = await previewDeploymentDeletion(selectedProjectId.value, deploymentId)
  } catch {
    // 预览失败时不阻断打开删除弹窗，也不向页面顶部写入持久化错误横幅
  }
  pendingDeleteDeploymentId.value = deploymentId
}

function openDeleteBlockedReferences(): void {
  const id = pendingDeleteDeploymentId.value
  pendingDeleteDeploymentId.value = null
  if (id) openDeploymentStatusDrawer(id, 'references')
}

function closeDeleteDeploymentDialog(): void {
  const deploymentId = pendingDeleteDeployment.value?.deployment_instance_id
  if (deploymentId && isDeleteActionBusy(deploymentId)) return
  pendingDeleteDeploymentId.value = null
  deleteReferences.value = []
}

async function confirmDeleteDeployment(): Promise<void> {
  const deployment = pendingDeleteDeployment.value
  if (!deployment || !canDeleteDeployment(deployment)) return
  const deploymentId = deployment.deployment_instance_id
  const taskType = taskTypeForDeployment(deployment)
  selectedDeploymentId.value = deploymentId
  setDeploymentRunningAction(deploymentId, 'delete')
  errorMessage.value = null
  try {
    await deleteTaskDeployment(taskType, deploymentId, deletionPreview.value?.revision)
    deleteDeploymentRuntimeSnapshot(deploymentId)
    deploymentEvents.value = []
    lastCreatedDeployment.value = lastCreatedDeployment.value?.deployment_instance_id === deploymentId ? null : lastCreatedDeployment.value
    await refreshPage()
    pendingDeleteDeploymentId.value = null
  } catch (error) {
    const [refs] = await Promise.all([
      selectedProjectId.value
        ? listDeploymentReferences(selectedProjectId.value, deploymentId).catch(() => ({ items: [], total: 0 }))
        : Promise.resolve({ items: [], total: 0 }),
      refreshDeploymentRuntimeSnapshot(deployment),
    ])
    deleteReferences.value = refs.items
    if (!canDeleteDeployment(deployment) || refs.items.length > 0) {
      errorMessage.value = null
      return
    }
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.deleteFailed')
    try { deletionPreview.value = await previewDeploymentDeletion(selectedProjectId.value!, deploymentId) } catch { /* 保留后端错误 */ }
  } finally {
    setDeploymentRunningAction(deploymentId, null)
  }
}

async function loadDeploymentRuntimeHealthBeforeWarmup(
  taskType: ModelTaskType,
  deploymentId: string,
  mode: DeploymentRuntimeMode,
): Promise<TaskDeploymentRuntimeHealth | null> {
  try {
    const health = await runTaskDeploymentHealthAction(taskType, deploymentId, mode, 'health')
    commitDeploymentRuntimeHealth(deploymentId, health)
    return health
  } catch {
    return null
  }
}
</script>

<style scoped>
.deployment-workspace {
  min-width: 0;
  max-width: 100%;
  grid-template-columns: minmax(0, 1fr);
}

.deployment-ops-navigation {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 10px 24px;
  min-height: 48px;
  margin-block-end: 4px;
  box-shadow: inset 0 -1px var(--am-border);
}

.deployment-ops-navigation__actions {
  display: flex;
  flex: none;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  margin-inline-start: auto;
  padding-block: 4px 8px;
}

.deployment-ops-navigation__actions:empty {
  display: none;
}

@media (max-width: 767px) {
  .deployment-ops-navigation {
    flex-wrap: wrap;
    box-shadow: none;
  }

  .deployment-ops-navigation :deep(.local-tabs) {
    box-shadow: inset 0 -1px var(--am-border);
  }
}

.dialog-title-icon {
  vertical-align: -4px;
  margin-right: 8px;
}

.dialog-title-icon.is-warning {
  color: var(--am-warning-icon);
}

.dialog-title-icon.is-danger {
  color: var(--am-danger-icon);
}

.deployment-dialog-card {
  display: grid;
  gap: 8px;
  margin: 0 0 14px;
  padding: 12px 14px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface-muted);
  font-size: 13px;
}

.deployment-dialog-card > div {
  display: grid;
  grid-template-columns: minmax(96px, 34%) minmax(0, 1fr);
  gap: 10px;
}

.deployment-dialog-card dt {
  color: var(--am-text-muted);
}

.deployment-dialog-card dd {
  margin: 0;
  font-weight: 500;
  overflow-wrap: anywhere;
}

.dialog-table-wrap {
  margin-bottom: 12px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  overflow-x: auto;
}

.dialog-table-wrap table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.dialog-table-wrap th,
.dialog-table-wrap td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--am-border);
  text-align: left;
}

.dialog-table-wrap tr:last-child td {
  border-bottom: 0;
}

.dialog-table-wrap th {
  background: var(--am-table-header);
  color: var(--am-text-muted);
  font-size: 12px;
  font-weight: 600;
}

.dialog-dot-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.dialog-dot-status > span {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--am-neutral-icon);
}

.dialog-dot-status.is-running > span {
  background: var(--am-action-primary);
}

.dialog-action-link {
  color: var(--am-action-primary-strong);
  font-weight: 600;
}

.dialog-numbered-section {
  display: grid;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 13px;
}

.dialog-numbered-list {
  margin: 0;
  padding: 0;
  list-style: none;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  counter-reset: dialog-step;
}

.dialog-numbered-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 12px;
  border-bottom: 1px solid var(--am-border);
}

.dialog-numbered-list li:last-child {
  border-bottom: 0;
}

.dialog-numbered-list li::before {
  counter-increment: dialog-step;
  content: counter(dialog-step);
  display: inline-grid;
  place-items: center;
  width: 18px;
  height: 18px;
  margin-right: 8px;
  border-radius: 999px;
  background: var(--am-surface-muted);
  border: 1px solid var(--am-border);
  font-size: 11px;
  color: var(--am-text-muted);
  flex-shrink: 0;
}

.dialog-numbered-list li > span:first-child {
  flex: 1 1 auto;
}

.dialog-numbered-list em {
  font-style: normal;
  font-weight: 600;
  color: var(--am-text-muted);
}

.dialog-numbered-list em.is-warning { color: var(--am-warning-text); }
.dialog-numbered-list em.is-success { color: var(--am-action-primary-strong); }

.dialog-info-bar,
.dialog-warning-bar {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 12px;
  margin-bottom: 8px;
}

.dialog-info-bar {
  border: 1px solid var(--am-border);
  background: var(--am-surface-muted);
  color: var(--am-text-muted);
}

.dialog-warning-bar {
  border: 1px solid var(--am-warning-border);
  background: var(--am-warning-surface);
  color: var(--am-warning-text);
}

.dialog-sub-note {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--am-text-muted);
}

.deployment-create-panel__heading {
  align-items: center;
}

.deployment-source-summary__grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.deployment-source-summary__grid div {
  padding: 10px;
}

.source-empty-card {
  display: grid;
  gap: 4px;
  min-height: 74px;
  align-content: center;
  padding: 12px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface);
}

.source-empty-card span {
  color: var(--am-text-muted);
}

.deployment-create-panel {
  min-width: 0;
}

.deployment-create-grid {
  gap: 10px;
}

.field-control-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 112px;
  gap: 8px;
  align-items: stretch;
}

.field-control-row > :only-child {
  grid-column: 1 / -1;
}

.deployment-profile-summary {
  display: grid;
  gap: 4px;
  min-height: 34px;
  align-content: center;
  padding: 7px 10px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface-muted);
}

.deployment-profile-summary span {
  color: var(--am-text);
  font-weight: 500;
}

@media (max-width: 720px) {
  .deployment-source-summary__grid {
    grid-template-columns: 1fr;
  }
}
</style>
