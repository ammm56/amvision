<template>
  <section
    class="inf-page"
    :class="{ 'inf-page--workbench': activeTab === 'workbench', 'inf-page--subview': !showTopTabs }"
  >
    <nav v-if="showTopTabs" class="inf-nav" aria-label="在线推理">
      <TabList
        :tabs="pageTabs"
        :model-value="activeTab"
        variant="underline"
        label="在线推理"
        @update:model-value="setActiveTab"
      />
      <div v-if="activeTab === 'tasks' && tasksViewMode === 'list' && canWriteTasks" class="inf-nav__actions">
        <Button variant="primary" data-create-batch-btn @click="startBatchCreate">
          <Plus :size="15" />
          新建批量任务
        </Button>
      </div>
    </nav>

    <InlineError :message="errorMessage" />

    <div v-if="isReadOnlyUser" class="inf-readonly-banner" role="status" data-readonly-banner>
      <Info :size="15" />
      <span>当前账号为只读权限：仅可查看与导出结果，不可提交异步或批量任务，也不可取消或删除记录。</span>
    </div>

    <template v-if="activeTab === 'workbench'">
      <section class="inf-target-bar">
        <div class="inf-target-bar__left">
          <div class="inf-target-field inf-target-field--deploy">
            <span class="inf-target-field__label">部署</span>
            <DeploymentTargetSelect
              :model-value="selectedDeploymentId"
              :deployments="deployments"
              placeholder="请选择部署"
              aria-label="部署"
              @update:model-value="selectDeployment"
            />
          </div>

          <span v-if="selectedDeployment" class="inf-target-meta" :title="deploymentInlineSummary">
            {{ deploymentInlineSummary }}
          </span>
        </div>

        <div class="inf-target-bar__right">
          <template v-if="selectedDeployment">
            <span class="inf-status-dot-label">
              <span
                class="inf-status-dot"
                :class="versionChangedNotice || !activeChannelReady ? 'is-warn' : 'is-ok'"
              />
              <span>{{ versionChangedNotice ? '版本已更新' : activeChannelStatusLabel }}</span>
            </span>
            <RouterLink :to="`/deployments`" class="inf-deploy-link-btn">
              查看部署
            </RouterLink>
          </template>
          <span v-else class="inf-status-dot-label">
            <span class="inf-status-dot is-warn" />
            <span>无可用部署</span>
          </span>
        </div>
      </section>

      <div v-if="versionChangedNotice" class="inf-version-banner" role="alert" data-version-changed-banner>
        <div class="inf-version-banner__left">
          <AlertTriangle :size="15" />
          <span>
            部署版本已更新：<strong>{{ versionChangedNotice.fromLabel }}</strong> → <strong>{{ versionChangedNotice.toLabel }}</strong>
          </span>
        </div>
        <div class="inf-version-banner__actions">
          <Button size="sm" variant="primary" data-confirm-version-update @click="confirmDeploymentVersionUpdate">
            使用当前版本
          </Button>
          <Button size="sm" variant="secondary" data-change-deployment @click="clearDeploymentSelection">
            更换部署
          </Button>
        </div>
      </div>

      <div class="inf-workbench-grid">
        <InferenceInputPanel
          :project-id="selectedProjectId"
          :task-type="activeTaskType"
          :deployment-input-size="selectedDeployment?.input_size || null"
          :source-mode="sourceMode"
          :invocation-mode="invocationMode"
          :async-task-name="asyncTaskName"
          :async-ready="asyncReady"
          :read-only="isReadOnlyUser"
          :can-submit-async="canWriteTasks"
          :async-error="asyncError"
          :version-blocked="Boolean(versionChangedNotice)"
          :uploaded-file="uploadedFile"
          :selected-file-id="existingFileId"
          :selected-file-label="existingFileLabel"
          :selected-file-size-bytes="existingFileSizeBytes"
          :preview-thumb-url="activeImageSrc"
          :image-width="currentImageWidth"
          :image-height="currentImageHeight"
          :input-uri="inputUri"
          :image-base64="imageBase64"
          :source-error="sourceError"
          :score-threshold="scoreThreshold"
          :top-k="topK"
          :mask-threshold="maskThreshold"
          :keypoint-confidence-threshold="keypointConfidenceThreshold"
          :save-result="saveResult"
          :result-name="resultName"
          :can-run="canRunInference"
          :running="inferRunning"
          :disabled="inferRunning"
          :timeout-pending="timeoutPending"
          :lookup-loading="lookupLoading"
          :last-request-id="lastRequestId"
          @update:source-mode="handleSourceModeChange"
          @update:invocation-mode="handleInvocationModeChange"
          @update:async-task-name="asyncTaskName = $event"
          @update:uploaded-file="handleUploadedFileChange"
          @update:existing-selection="handleExistingSelection"
          @update:input-uri="handleUriChange"
          @update:image-base64="handleBase64Change"
          @update:score-threshold="scoreThreshold = $event"
          @update:top-k="topK = $event"
          @update:mask-threshold="maskThreshold = $event"
          @update:keypoint-confidence-threshold="keypointConfidenceThreshold = $event"
          @update:save-result="saveResult = $event"
          @update:result-name="resultName = $event"
          @run="handleRunAction"
          @open-tasks="setActiveTab('tasks')"
          @lookup-timeout="lookupTimedOutSave"
          @recheck-input="recheckInputSource"
        />

        <div class="inf-canvas-stage" data-canvas-stage>
          <InferenceCanvasViewer
            :image-src="activeImageSrc"
            :image-width="currentImageWidth || 0"
            :image-height="currentImageHeight || 0"
            :task-type="activeTaskType"
            :has-result="Boolean(inferenceResult) && !versionChangedNotice"
            :inspector-open="inspectorOpen"
            :no-deployment="!loading && deployments.length === 0"
            :source-error="sourceError"
            :overload-message="overloadMessage"
            :all-items="allItems"
            :visible-items="visibleItems"
            :selected-item-id="selectedItemId"
            :view-mode="viewMode"
            :layers="layers"
            :mask-opacity="maskOpacity"
            :show-contours="showContours"
            :min-display-score="minDisplayScore"
            :selected-classes="selectedClasses"
            :fullscreen="false"
            @update:view-mode="viewMode = $event"
            @update:layers="layers = $event"
            @update:mask-opacity="maskOpacity = $event"
            @update:min-display-score="minDisplayScore = $event"
            @update:selected-classes="selectedClasses = $event"
            @select-item="handleSelectItem"
            @toggle-inspector="inspectorOpen = !inspectorOpen"
            @toggle-fullscreen="fullscreenOpen = true"
            @dismiss-overload="overloadMessage = null"
            @go-deployments="goToDeployments"
            @refresh="refreshContext"
            @image-loaded="handleImageLoaded"
          >
            <template v-if="inferenceResult && (activeTaskType === 'classification' || activeTaskType === 'pose' || activeTaskType === 'obb')" #below-canvas>
              <div class="inf-below-table-wrap">
                <table v-if="activeTaskType === 'classification'" class="inf-inline-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>类别</th>
                      <th>置信度</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="item in visibleItems.slice(0, 5)"
                      :key="item.id"
                      :class="{ 'is-selected': selectedItemId === item.id }"
                      @click="handleSelectItem(item.id)"
                    >
                      <td>{{ item.index }}</td>
                      <td>
                        <span class="inf-dot-value">
                          <span class="inf-dot" :style="{ backgroundColor: item.color }" />
                          <span>{{ item.className }}</span>
                        </span>
                      </td>
                      <td>{{ item.score.toFixed(3) }}</td>
                    </tr>
                  </tbody>
                </table>

                <div v-else-if="activeTaskType === 'pose' && visibleItems[0]" class="inf-pose-inline-grid">
                  <table class="inf-inline-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>关键点</th>
                        <th>置信度</th>
                        <th>状态</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="(kp, idx) in (visibleItems[0].keypoints || []).slice(0, 6)" :key="`inline-kp-${idx}`">
                        <td>{{ idx + 1 }}</td>
                        <td>P{{ idx + 1 }}</td>
                        <td>{{ isPoseKeypointVisible(visibleItems[0], kp) ? (kp.confidence ?? 1).toFixed(2) : '—' }}</td>
                        <td>
                          <span class="inf-dot-value">
                            <span
                              class="inf-dot"
                              :style="{ backgroundColor: isPoseKeypointVisible(visibleItems[0], kp) ? '#00d992' : '#dc2626' }"
                            />
                            <span>{{ isPoseKeypointVisible(visibleItems[0], kp) ? '已检出' : '未检出' }}</span>
                          </span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                  <div class="inf-pose-inline-summary">
                    <strong>推理结果</strong>
                    <div><span>对象数量</span><span>{{ visibleItems.length }}</span></div>
                    <div>
                      <span>关键点</span>
                      <span>
                        {{ countDetectedPoseKeypoints(visibleItems[0]) }} / {{ visibleItems[0].keypoints?.length || 0 }}
                      </span>
                    </div>
                  </div>
                </div>

                <div v-else-if="activeTaskType === 'obb'" class="inf-obb-inline-wrap">
                  <table class="inf-inline-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>类别</th>
                        <th>置信度</th>
                        <th>角度</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="item in visibleItems.slice(0, 5)"
                        :key="item.id"
                        :class="{ 'is-selected': selectedItemId === item.id }"
                        @click="handleSelectItem(item.id)"
                      >
                        <td>{{ item.index }}</td>
                        <td>{{ item.className }}</td>
                        <td>{{ item.score.toFixed(2) }}</td>
                        <td>{{ formatObbAngleText(item) }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </template>

            <template v-if="activeImageSrc || inferenceResult || saveErrorMessage" #footer>
              <div class="inf-canvas-footer">
                <div v-if="saveErrorMessage" class="inf-save-error-bar">
                  <div class="inf-save-error-bar__left">
                    <AlertTriangle :size="15" />
                    <div>
                      <strong>结果保存失败</strong>
                      <span>{{ saveErrorMessage }}</span>
                    </div>
                  </div>
                  <div class="inf-save-error-bar__actions">
                    <Button size="sm" variant="primary" :loading="savingRecord" @click="retryOrManualSave">
                      仅重试保存
                    </Button>
                  </div>
                </div>

                <div v-if="activeImageSrc" class="inf-canvas-footer__row">
                  <span class="inf-canvas-footer__file">
                    {{ currentInputLabel }}
                    <template v-if="currentImageWidth && currentImageHeight">
                      · {{ currentImageWidth }} × {{ currentImageHeight }}
                    </template>
                  </span>
                  <span class="inf-canvas-footer__time">
                    <template v-if="inferenceResult">{{ completedAtText }}</template>
                    <template v-else>待执行</template>
                  </span>
                </div>

                <div v-if="inferenceResult && !versionChangedNotice" class="inf-canvas-footer__row inf-canvas-footer__row--result">
                  <div class="inf-canvas-footer__stats">
                    <span class="inf-status-dot-label is-brand">
                      <span class="inf-status-dot is-ok" />
                      <span>推理成功</span>
                    </span>
                    <template v-if="activeTaskType === 'classification'">
                      <span>Top-{{ allItems.length }}</span>
                    </template>
                    <template v-else-if="allItems.length === 0">
                      <span>{{ activeTaskType === 'segmentation' ? '实例 0' : '目标 0' }}</span>
                      <span class="inf-muted">未检出目标</span>
                    </template>
                    <template v-else>
                      <span>{{ activeTaskType === 'segmentation' ? `实例 ${visibleItems.length}` : `目标 ${visibleItems.length}` }}</span>
                      <span v-for="cls in classCountPills" :key="cls.className">
                        {{ cls.className }} {{ cls.count }}
                      </span>
                    </template>
                  </div>

                  <div class="inf-canvas-footer__right">
                    <span>请求 {{ formatMs(requestDurationMs) }}</span>
                    <span>服务端 {{ formatMs(inferenceResult.latency_ms) }}</span>
                    <Button
                      v-if="!savedRecord"
                      size="sm"
                      variant="secondary"
                      :loading="savingRecord"
                      @click="retryOrManualSave"
                    >
                      <Bookmark :size="13" />
                      保存结果
                    </Button>
                    <span v-else class="inf-saved-pill">已保存</span>
                  </div>
                </div>
              </div>
            </template>

            <template #overlay>
              <InferenceResultInspector
                :open="inspectorOpen && Boolean(inferenceResult)"
                :task-type="activeTaskType"
                :all-items="allItems"
                :items="displayedInspectorItems"
                :selected-item-id="selectedItemId"
                :payload="inferenceResult"
                :image-src="activeImageSrc"
                :input-label="currentInputLabel"
                :request-id="lastRequestId"
                :request-duration-ms="requestDurationMs"
                :completed-at-text="completedAtText"
                :deployment-meta="inspectorDeploymentMeta"
                :saved-record="savedRecord"
                :saving-record="savingRecord"
                :layers="layers"
                :min-display-score="minDisplayScore"
                :selected-classes="selectedClasses"
                :isolate-item-id="isolateItemId"
                :show-contours="showContours"
                :mask-opacity="maskOpacity"
                @close="inspectorOpen = false"
                @select-item="handleSelectItem"
                @save-record="retryOrManualSave"
                @update:layers="layers = $event"
                @update:min-display-score="minDisplayScore = $event"
                @update:selected-classes="selectedClasses = $event"
                @update:isolate-item-id="isolateItemId = $event"
                @update:show-contours="showContours = $event"
              />
            </template>
          </InferenceCanvasViewer>
        </div>
      </div>
    </template>

    <template v-else>
      <BatchInferenceCreateView
        v-if="tasksViewMode === 'create'"
        :project-id="selectedProjectId"
        :deployments="deployments"
        :initial-deployment-id="createSeedDeploymentId"
        :initial-source-kind="createSeedFileIds.length > 0 ? 'project_files' : undefined"
        :initial-file-ids="createSeedFileIds"
        @cancel="tasksViewMode = 'list'"
        @created="handleBatchCreated"
      />
      <BatchInferenceDetailView
        v-else-if="tasksViewMode === 'detail' && activeBatchTaskId"
        :batch-task-id="activeBatchTaskId"
        :deployments="deployments"
        :can-write-tasks="canWriteTasks"
        @back="closeBatchDetail"
        @deleted="handleBatchDeleted"
        @retry-failed-items="retryBatchFailedItems"
      />
      <InferenceTasksTab
        v-else
        :key="tasksRefreshKey"
        :project-id="selectedProjectId"
        :deployments="deployments"
        :can-write-tasks="canWriteTasks"
        @open-create="startBatchCreate"
        @open-batch="openBatchDetail"
        @open-direct-record="openSavedRecordInWorkbench"
        @open-async-task="openAsyncTaskInWorkbench"
        @back-workbench="setActiveTab('workbench')"
      />
    </template>

    <Teleport to="body">
      <div v-if="fullscreenOpen" class="inf-fullscreen-modal" role="dialog" aria-modal="true" aria-label="样本大图查看器">
        <InferenceCanvasViewer
          :image-src="activeImageSrc"
          :image-width="currentImageWidth || 0"
          :image-height="currentImageHeight || 0"
          :task-type="activeTaskType"
          :has-result="Boolean(inferenceResult)"
          :inspector-open="inspectorOpen"
          :all-items="allItems"
          :visible-items="visibleItems"
          :selected-item-id="selectedItemId"
          :view-mode="viewMode"
          :layers="layers"
          :mask-opacity="maskOpacity"
          :show-contours="showContours"
          :min-display-score="minDisplayScore"
          :selected-classes="selectedClasses"
          :fullscreen="true"
          @update:view-mode="viewMode = $event"
          @update:layers="layers = $event"
          @update:mask-opacity="maskOpacity = $event"
          @update:min-display-score="minDisplayScore = $event"
          @update:selected-classes="selectedClasses = $event"
          @select-item="handleSelectItem"
          @toggle-inspector="inspectorOpen = !inspectorOpen"
          @toggle-fullscreen="fullscreenOpen = false"
          @image-loaded="handleImageLoaded"
        >
          <template #header>
            <header class="inf-fs-header">
              <div class="inf-fs-header__left">
                <Button size="sm" variant="secondary" data-fullscreen-back @click="fullscreenOpen = false">
                  <ArrowLeft :size="14" />
                  返回
                </Button>
                <strong class="inf-fs-header__title">{{ currentInputLabel }}</strong>
                <span v-if="inferenceResult" class="inf-status-dot-label is-brand">
                  <span class="inf-status-dot is-ok" />
                  <span>推理成功</span>
                </span>
                <span v-if="selectedDeployment" class="inf-fs-header__meta">
                  {{ selectedDeployment.display_name }} · {{ selectedDeployment.model_name }}
                </span>
                <span v-if="currentImageWidth && currentImageHeight" class="inf-fs-header__meta">
                  {{ currentImageWidth }} × {{ currentImageHeight }}
                </span>
                <span v-if="inferenceResult && activeTaskType !== 'classification'" class="inf-fs-header__meta">
                  目标 {{ visibleItems.length }}
                </span>
              </div>
            </header>
          </template>

          <template v-if="inferenceResult" #footer>
            <div class="inf-canvas-footer">
              <div class="inf-canvas-footer__row">
                <div class="inf-canvas-footer__stats">
                  <span v-for="cls in classCountPills" :key="cls.className" class="inf-dot-value">
                    <span class="inf-dot" :style="{ backgroundColor: cls.color }" />
                    <span>{{ cls.className }} {{ cls.count }}</span>
                  </span>
                </div>
                <div class="inf-canvas-footer__right">
                  <span>请求 {{ formatMs(requestDurationMs) }}</span>
                  <span>服务端 {{ formatMs(inferenceResult.latency_ms) }}</span>
                  <span>{{ completedAtText }}</span>
                </div>
              </div>
            </div>
          </template>

          <template #overlay>
            <InferenceResultInspector
              :open="inspectorOpen && Boolean(inferenceResult)"
              :task-type="activeTaskType"
              :all-items="allItems"
              :items="displayedInspectorItems"
              :selected-item-id="selectedItemId"
              :payload="inferenceResult"
              :image-src="activeImageSrc"
              :input-label="currentInputLabel"
              :request-id="lastRequestId"
              :request-duration-ms="requestDurationMs"
              :completed-at-text="completedAtText"
              :deployment-meta="inspectorDeploymentMeta"
              :saved-record="savedRecord"
              :saving-record="savingRecord"
              :layers="layers"
              :min-display-score="minDisplayScore"
              :selected-classes="selectedClasses"
              :isolate-item-id="isolateItemId"
              :show-contours="showContours"
              :mask-opacity="maskOpacity"
              @close="inspectorOpen = false"
              @select-item="handleSelectItem"
              @save-record="retryOrManualSave"
              @update:layers="layers = $event"
              @update:min-display-score="minDisplayScore = $event"
              @update:selected-classes="selectedClasses = $event"
              @update:isolate-item-id="isolateItemId = $event"
              @update:show-contours="showContours = $event"
            />
          </template>
        </InferenceCanvasViewer>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { AlertTriangle, ArrowLeft, Bookmark, Info, Plus } from '@lucide/vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import {
  listTaskDeployments,
  runTaskDeploymentStatusAction,
  type ModelTaskType,
  type TaskDeploymentInstance,
  type TaskDeploymentProcessStatus,
} from '@/modules/deployments/services/deployment.service'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import { ApiError, getErrorMessage } from '@/shared/api/error'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import TabList from '@/shared/ui/navigation/TabList.vue'
import BatchInferenceCreateView from '../components/BatchInferenceCreateView.vue'
import BatchInferenceDetailView from '../components/BatchInferenceDetailView.vue'
import DeploymentTargetSelect from '../components/DeploymentTargetSelect.vue'
import type { ExistingFileSelectionResult } from '../components/ExistingFilePickerDrawer.vue'
import InferenceCanvasViewer from '../components/InferenceCanvasViewer.vue'
import InferenceInputPanel, {
  type InferenceInvocationMode,
  type InferenceSourceMode,
} from '../components/InferenceInputPanel.vue'
import InferenceResultInspector, {
  type InspectorDeploymentMeta,
} from '../components/InferenceResultInspector.vue'
import InferenceTasksTab from '../components/InferenceTasksTab.vue'
import {
  filterOverlayItems,
  formatObbAngleDeg,
  normalizeInferenceOverlayItems,
  summarizeOverlayClasses,
  type CanvasViewMode,
  type InferenceLayerVisibility,
  type OverlayRenderItem,
} from '../components/inference-overlay.utils'
import {
  createTaskInferenceTask,
  fetchAuthorizedProjectFileBlob,
  fetchDirectInferenceRecordImageBlob,
  getDirectInferenceRecord,
  getTaskInferenceTaskResult,
  inferTaskDeployment,
  listDirectInferenceRecords,
  saveDirectInferenceRecord,
  SUPPORTED_INFERENCE_TASK_TYPES,
  type BatchInferenceTask,
  type DirectInferenceRecordSummary,
  type PoseInferenceKeypoint,
  type TaskInferencePayload,
  type TaskInferenceTaskSummary,
} from '../services/inference.service'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const sessionStore = useSessionStore()

const canWriteTasks = computed(() => !sessionStore.currentUser || sessionStore.hasScopes(['tasks:write']))
const isReadOnlyUser = computed(() => Boolean(sessionStore.currentUser) && !sessionStore.hasScopes(['tasks:write']))

const activeTab = ref<'workbench' | 'tasks'>(route.query.tab === 'tasks' ? 'tasks' : 'workbench')
const tasksViewMode = ref<'list' | 'create' | 'detail'>(
  typeof route.query.batch_id === 'string' && route.query.batch_id ? 'detail' : 'list',
)
const activeBatchTaskId = ref(
  typeof route.query.batch_id === 'string' ? route.query.batch_id : '',
)
const tasksRefreshKey = ref(0)
const createSeedDeploymentId = ref('')
const createSeedFileIds = ref<string[]>([])
const pageTabs = [
  { id: 'workbench', label: '工作台' },
  { id: 'tasks', label: '推理任务' },
]
const showTopTabs = computed(
  () => activeTab.value === 'workbench' || tasksViewMode.value === 'list',
)

const loading = ref(false)
const errorMessage = ref<string | null>(null)
const sourceError = ref<string | null>(null)
const overloadMessage = ref<string | null>(null)
const saveErrorMessage = ref<string | null>(null)
const asyncError = ref<string | null>(null)
const deployments = ref<TaskDeploymentInstance[]>([])
const selectedDeploymentId = ref('')
const syncStatus = ref<TaskDeploymentProcessStatus | null>(null)
const asyncStatus = ref<TaskDeploymentProcessStatus | null>(null)
const pinnedDeploymentVersion = ref<{
  deploymentId: string
  modelVersionId: string
  versionLabel: string
} | null>(null)
const versionChangedNotice = ref<{
  fromLabel: string
  toLabel: string
  nextVersionId: string
} | null>(null)

const sourceMode = ref<InferenceSourceMode>('upload')
const invocationMode = ref<InferenceInvocationMode>('sync')
const asyncTaskName = ref('')
const uploadedFile = ref<File | null>(null)
const uploadObjectUrl = ref<string | null>(null)
const existingFileId = ref('')
const existingFileLabel = ref('')
const existingFileSizeBytes = ref<number | null>(null)
const existingPreviewUrl = ref<string | null>(null)
const inputUri = ref('')
const imageBase64 = ref('')
const externalImageUrl = ref<string | null>(null)
const loadedImageDims = ref<{ width: number; height: number } | null>(null)

const scoreThreshold = ref(0.3)
const topK = ref(5)
const maskThreshold = ref(0.5)
const keypointConfidenceThreshold = ref(0.3)
const saveResult = ref(false)
const resultName = ref('')

const inferRunning = ref(false)
const savingRecord = ref(false)
const lookupLoading = ref(false)
const timeoutPending = ref(false)
const lastRequestId = ref<string | null>(null)
const requestDurationMs = ref<number | null>(null)
const completedAtText = ref('—')
const inferenceResult = ref<TaskInferencePayload | null>(null)
const savedRecord = ref<DirectInferenceRecordSummary | null>(null)

const inspectorOpen = ref(false)
const fullscreenOpen = ref(false)
const selectedItemId = ref<string | null>(null)
const isolateItemId = ref<string | null>(null)
const viewMode = ref<CanvasViewMode>('overlay')
const minDisplayScore = ref(0)
const selectedClasses = ref<string[]>([])
const maskOpacity = ref(0.35)
const showContours = ref(true)
const layers = ref<InferenceLayerVisibility>({
  boxes: true,
  masks: true,
  keypoints: true,
  skeleton: true,
  labels: true,
})

const selectedProjectId = computed(() => projectStore.selectedProjectId)
const selectedProjectName = computed(
  () =>
    projectStore.projects.find((p) => p.project_id === selectedProjectId.value)?.display_name ||
    selectedProjectId.value ||
    '未选择项目',
)
const selectedDeployment = computed(
  () => deployments.value.find((d) => d.deployment_instance_id === selectedDeploymentId.value) ?? null,
)
const activeTaskType = computed<ModelTaskType>(() => {
  const raw = selectedDeployment.value?.task_type
  return SUPPORTED_INFERENCE_TASK_TYPES.includes(raw as ModelTaskType) ? (raw as ModelTaskType) : 'detection'
})

const deploymentInlineSummary = computed(() => {
  const dep = selectedDeployment.value
  if (!dep) return ''
  const parts = [
    dep.task_type,
    dep.model_name || dep.model_version_id,
    `${dep.runtime_backend}${dep.runtime_precision ? ` ${dep.runtime_precision.toUpperCase()}` : ''}`,
    dep.device_name,
  ].filter(Boolean)
  return parts.join(' · ')
})

const inspectorDeploymentMeta = computed<InspectorDeploymentMeta | null>(() => {
  const dep = selectedDeployment.value
  if (!dep) return null
  return {
    projectName: selectedProjectName.value,
    displayName: dep.display_name || dep.deployment_instance_id,
    modelName: dep.model_name || dep.model_version_id,
    runtimeLabel: `${dep.runtime_backend}${dep.runtime_precision ? ` ${dep.runtime_precision.toUpperCase()}` : ''}`,
    deviceLabel: dep.device_name || '-',
  }
})

const syncReady = computed(() => {
  if (!syncStatus.value) return true
  return syncStatus.value.process_state === 'running'
})

const syncStatusLabel = computed(() => {
  if (!syncStatus.value) return '状态未知'
  if (syncStatus.value.process_state === 'running') return '运行正常'
  return `同步${syncStatus.value.process_state}`
})

const asyncReady = computed(() => asyncStatus.value?.process_state === 'running')

const activeChannelReady = computed(() =>
  invocationMode.value === 'async' ? asyncReady.value : syncReady.value,
)

const activeChannelStatusLabel = computed(() => {
  if (invocationMode.value === 'async') {
    if (!asyncStatus.value) return '异步状态未知'
    return asyncReady.value ? '异步通道就绪' : '异步未启动'
  }
  return syncStatusLabel.value
})

const hasActiveInput = computed(() => {
  if (sourceMode.value === 'upload') return Boolean(uploadedFile.value)
  if (sourceMode.value === 'existing') return Boolean(existingFileId.value.trim())
  if (sourceMode.value === 'uri') return Boolean(inputUri.value.trim())
  return Boolean(imageBase64.value.trim())
})

const canRunInference = computed(() => Boolean(selectedDeployment.value && hasActiveInput.value))

const activeImageSrc = computed(() => {
  if (externalImageUrl.value) return externalImageUrl.value
  if (sourceMode.value === 'upload') return uploadObjectUrl.value
  if (sourceMode.value === 'existing') return existingPreviewUrl.value
  if (sourceMode.value === 'base64') {
    const val = imageBase64.value.trim()
    if (!val) return null
    return val.startsWith('data:image/') ? val : `data:image/jpeg;base64,${val}`
  }
  return null
})

const currentInputLabel = computed(() => {
  if (resultName.value.trim()) return resultName.value.trim()
  if (sourceMode.value === 'upload') return uploadedFile.value?.name || '上传图片'
  if (sourceMode.value === 'existing') return existingFileLabel.value || '已有文件'
  if (sourceMode.value === 'uri') return inputUri.value.trim() || 'URI 图像'
  return 'Base64 图像'
})

const currentImageWidth = computed(
  () => inferenceResult.value?.image_width || loadedImageDims.value?.width || null,
)
const currentImageHeight = computed(
  () => inferenceResult.value?.image_height || loadedImageDims.value?.height || null,
)

const allItems = computed(() => normalizeInferenceOverlayItems(activeTaskType.value, inferenceResult.value))
const visibleItems = computed(() =>
  filterOverlayItems(allItems.value, {
    minDisplayScore: minDisplayScore.value,
    selectedClasses: selectedClasses.value,
    isolateItemId: isolateItemId.value,
  }),
)
const displayedInspectorItems = computed(() =>
  filterOverlayItems(allItems.value, {
    minDisplayScore: minDisplayScore.value,
    selectedClasses: selectedClasses.value,
  }),
)
const classCountPills = computed(() => summarizeOverlayClasses(visibleItems.value))

onMounted(async () => {
  if (projectStore.projects.length === 0) {
    await projectStore.loadProjects()
  }
  await refreshContext()
})

onBeforeUnmount(() => {
  if (uploadObjectUrl.value) URL.revokeObjectURL(uploadObjectUrl.value)
  if (existingPreviewUrl.value) URL.revokeObjectURL(existingPreviewUrl.value)
  if (externalImageUrl.value) URL.revokeObjectURL(externalImageUrl.value)
})

watch(
  () => [route.query.tab, route.query.batch_id] as const,
  ([tab, batchId]) => {
    activeTab.value = tab === 'tasks' ? 'tasks' : 'workbench'
    if (typeof batchId === 'string' && batchId) {
      activeBatchTaskId.value = batchId
      tasksViewMode.value = 'detail'
    } else if (tasksViewMode.value === 'detail') {
      tasksViewMode.value = 'list'
    }
  },
)

watch(
  () => selectedProjectId.value,
  async () => {
    await refreshContext()
  },
)

function setActiveTab(next: string): void {
  const normalized = next === 'tasks' ? 'tasks' : 'workbench'
  activeTab.value = normalized
  const nextQuery: Record<string, string> = { tab: normalized }
  if (normalized === 'tasks' && tasksViewMode.value === 'detail' && activeBatchTaskId.value) {
    nextQuery.batch_id = activeBatchTaskId.value
  }
  void router.replace({ query: nextQuery })
}

function revokeExternalImageUrl(): void {
  if (externalImageUrl.value) {
    URL.revokeObjectURL(externalImageUrl.value)
    externalImageUrl.value = null
  }
}

function goToDeployments(): void {
  void router.push('/deployments')
}

function deploymentVersionLabel(dep: TaskDeploymentInstance): string {
  return dep.model_name || dep.model_version_id
}

function pinDeploymentVersion(dep: TaskDeploymentInstance | null): void {
  versionChangedNotice.value = null
  if (!dep) {
    pinnedDeploymentVersion.value = null
    return
  }
  pinnedDeploymentVersion.value = {
    deploymentId: dep.deployment_instance_id,
    modelVersionId: dep.model_version_id,
    versionLabel: deploymentVersionLabel(dep),
  }
}

function checkPinnedDeploymentVersion(dep: TaskDeploymentInstance | null): void {
  if (!dep) {
    versionChangedNotice.value = null
    return
  }
  const pinned = pinnedDeploymentVersion.value
  if (!pinned || pinned.deploymentId !== dep.deployment_instance_id) {
    pinDeploymentVersion(dep)
    return
  }
  if (pinned.modelVersionId !== dep.model_version_id) {
    versionChangedNotice.value = {
      fromLabel: pinned.versionLabel,
      toLabel: deploymentVersionLabel(dep),
      nextVersionId: dep.model_version_id,
    }
  }
}

async function confirmDeploymentVersionUpdate(): Promise<void> {
  const dep = selectedDeployment.value
  if (!dep) return
  pinDeploymentVersion(dep)
  resetPredictionState()
  await inspectSelectedDeploymentStatus()
}

function clearDeploymentSelection(): void {
  selectedDeploymentId.value = ''
  pinDeploymentVersion(null)
  syncStatus.value = null
  asyncStatus.value = null
  resetPredictionState()
}

async function refreshContext(): Promise<void> {
  if (!selectedProjectId.value) return
  loading.value = true
  errorMessage.value = null
  try {
    const groups = await Promise.all(
      SUPPORTED_INFERENCE_TASK_TYPES.map((taskType) =>
        listTaskDeployments(taskType, selectedProjectId.value).catch(() => [] as TaskDeploymentInstance[]),
      ),
    )
    deployments.value = groups.flat()
    const queryDeployId = typeof route.query.deployment_instance_id === 'string'
      ? route.query.deployment_instance_id
      : ''
    if (queryDeployId && deployments.value.some((d) => d.deployment_instance_id === queryDeployId)) {
      selectedDeploymentId.value = queryDeployId
      pinDeploymentVersion(selectedDeployment.value)
    } else if (!deployments.value.some((d) => d.deployment_instance_id === selectedDeploymentId.value)) {
      selectedDeploymentId.value = deployments.value[0]?.deployment_instance_id ?? ''
      pinDeploymentVersion(selectedDeployment.value)
    } else {
      checkPinnedDeploymentVersion(selectedDeployment.value)
    }
    await inspectSelectedDeploymentStatus()
  } catch (err) {
    errorMessage.value = getErrorMessage(err)
  } finally {
    loading.value = false
  }
}

async function selectDeployment(value: string | number | boolean | null): Promise<void> {
  if (typeof value !== 'string') return
  selectedDeploymentId.value = value
  pinDeploymentVersion(selectedDeployment.value)
  resetPredictionState()
  await inspectSelectedDeploymentStatus()
}

function resetPredictionState(): void {
  inferenceResult.value = null
  savedRecord.value = null
  selectedItemId.value = null
  isolateItemId.value = null
  inspectorOpen.value = false
  saveErrorMessage.value = null
  overloadMessage.value = null
  asyncError.value = null
  timeoutPending.value = false
  requestDurationMs.value = null
  completedAtText.value = '—'
}

async function inspectSelectedDeploymentStatus(): Promise<void> {
  const dep = selectedDeployment.value
  if (!dep || !SUPPORTED_INFERENCE_TASK_TYPES.includes(dep.task_type as ModelTaskType)) {
    syncStatus.value = null
    asyncStatus.value = null
    return
  }
  const [nextSync, nextAsync] = await Promise.all([
    runTaskDeploymentStatusAction(
      dep.task_type as ModelTaskType,
      dep.deployment_instance_id,
      'sync',
      'status',
    ).catch(() => null),
    runTaskDeploymentStatusAction(
      dep.task_type as ModelTaskType,
      dep.deployment_instance_id,
      'async',
      'status',
    ).catch(() => null),
  ])
  syncStatus.value = nextSync
  asyncStatus.value = nextAsync
}

function handleInvocationModeChange(mode: InferenceInvocationMode): void {
  invocationMode.value = mode
  asyncError.value = null
  timeoutPending.value = false
}

function handleSourceModeChange(mode: InferenceSourceMode): void {
  sourceMode.value = mode
  externalImageUrl.value = null
  sourceError.value = null
  loadedImageDims.value = null
}

function handleUploadedFileChange(file: File | null): void {
  if (uploadObjectUrl.value) {
    URL.revokeObjectURL(uploadObjectUrl.value)
    uploadObjectUrl.value = null
  }
  uploadedFile.value = file
  externalImageUrl.value = null
  sourceError.value = null
  loadedImageDims.value = null
  resetPredictionState()
  if (file) {
    uploadObjectUrl.value = URL.createObjectURL(file)
  }
}

function handleExistingSelection(payload: ExistingFileSelectionResult | null): void {
  if (!payload) {
    if (existingPreviewUrl.value) {
      URL.revokeObjectURL(existingPreviewUrl.value)
      existingPreviewUrl.value = null
    }
    existingFileId.value = ''
    existingFileLabel.value = ''
    existingFileSizeBytes.value = null
    loadedImageDims.value = null
    resetPredictionState()
    return
  }
  if (existingPreviewUrl.value && existingPreviewUrl.value !== payload.previewUrl) {
    URL.revokeObjectURL(existingPreviewUrl.value)
  }
  existingFileId.value = payload.fileId
  existingFileLabel.value = payload.label
  existingFileSizeBytes.value = payload.sizeBytes ?? null
  existingPreviewUrl.value = payload.previewUrl
  externalImageUrl.value = null
  sourceError.value = null
  loadedImageDims.value =
    payload.width && payload.height ? { width: payload.width, height: payload.height } : null
  resetPredictionState()
}

function handleUriChange(value: string): void {
  inputUri.value = value
  sourceError.value = null
}

function handleBase64Change(value: string): void {
  imageBase64.value = value
  externalImageUrl.value = null
  sourceError.value = null
}

function recheckInputSource(): void {
  if (sourceMode.value === 'uri' && !inputUri.value.trim()) {
    sourceError.value = '请输入有效的文件 URI'
    return
  }
  sourceError.value = null
}

function handleImageLoaded(dims: { width: number; height: number }): void {
  loadedImageDims.value = dims
}

function createClientRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

async function handleRunAction(): Promise<void> {
  if (invocationMode.value === 'async') {
    await submitAsyncInference()
    return
  }
  await runSyncInference()
}

async function submitAsyncInference(): Promise<void> {
  const dep = selectedDeployment.value
  if (!dep || !hasActiveInput.value || !asyncReady.value || !canWriteTasks.value || versionChangedNotice.value) {
    return
  }
  inferRunning.value = true
  errorMessage.value = null
  sourceError.value = null
  asyncError.value = null
  timeoutPending.value = false

  const requestId = createClientRequestId()
  lastRequestId.value = requestId

  try {
    await createTaskInferenceTask({
      taskType: activeTaskType.value,
      projectId: selectedProjectId.value,
      deploymentInstanceId: dep.deployment_instance_id,
      displayName: asyncTaskName.value.trim() || currentInputLabel.value,
      inputFileId: sourceMode.value === 'existing' ? existingFileId.value : undefined,
      inputUri: sourceMode.value === 'uri' ? inputUri.value.trim() : undefined,
      imageBase64: sourceMode.value === 'base64' ? imageBase64.value.trim() : undefined,
      inputImage: sourceMode.value === 'upload' ? uploadedFile.value : undefined,
      inputTransportMode: sourceMode.value === 'existing' || sourceMode.value === 'uri' ? 'storage' : 'memory',
      scoreThreshold: scoreThreshold.value,
      topK: topK.value,
      maskThreshold: maskThreshold.value,
      keypointConfidenceThreshold: keypointConfidenceThreshold.value,
      saveResultImage: saveResult.value,
      returnPreviewImageBase64: false,
      requestId,
    })
    asyncTaskName.value = ''
    tasksRefreshKey.value++
    setActiveTab('tasks')
  } catch (err) {
    if (
      (err instanceof DOMException && err.name === 'AbortError') ||
      (err instanceof ApiError && (err.status === 408 || err.status === 504))
    ) {
      timeoutPending.value = true
      return
    }
    asyncError.value = getErrorMessage(err)
  } finally {
    inferRunning.value = false
  }
}

async function runSyncInference(): Promise<void> {
  const dep = selectedDeployment.value
  if (!dep || !hasActiveInput.value || versionChangedNotice.value) return
  inferRunning.value = true
  errorMessage.value = null
  sourceError.value = null
  overloadMessage.value = null
  saveErrorMessage.value = null
  timeoutPending.value = false
  savedRecord.value = null
  selectedItemId.value = null
  isolateItemId.value = null
  minDisplayScore.value = 0
  selectedClasses.value = []

  const requestId = createClientRequestId()
  lastRequestId.value = requestId
  const startedAt = typeof performance !== 'undefined' ? performance.now() : Date.now()

  try {
    const payload = await inferTaskDeployment({
      taskType: activeTaskType.value,
      projectId: selectedProjectId.value,
      deploymentInstanceId: dep.deployment_instance_id,
      inputFileId: sourceMode.value === 'existing' ? existingFileId.value : undefined,
      inputUri: sourceMode.value === 'uri' ? inputUri.value.trim() : undefined,
      imageBase64: sourceMode.value === 'base64' ? imageBase64.value.trim() : undefined,
      inputImage: sourceMode.value === 'upload' ? uploadedFile.value : undefined,
      inputTransportMode: sourceMode.value === 'existing' || sourceMode.value === 'uri' ? 'storage' : 'memory',
      scoreThreshold: scoreThreshold.value,
      topK: topK.value,
      maskThreshold: maskThreshold.value,
      keypointConfidenceThreshold: keypointConfidenceThreshold.value,
      saveResultImage: saveResult.value,
      returnPreviewImageBase64: false,
      requestId,
    })
    const finishedAt = typeof performance !== 'undefined' ? performance.now() : Date.now()
    requestDurationMs.value = Math.max(0.1, finishedAt - startedAt)
    completedAtText.value = formatSystemDateTime(new Date().toISOString())
    inferenceResult.value = payload
    lastRequestId.value = payload.request_id || requestId
    if (saveResult.value) {
      await persistCurrentResult()
    }
  } catch (err) {
    if (err instanceof ApiError && (err.status === 429 || err.status === 503)) {
      overloadMessage.value = '本次未执行，可稍后手动调用。'
      return
    }
    if (
      (err instanceof DOMException && err.name === 'AbortError') ||
      (err instanceof ApiError && (err.status === 408 || err.status === 504))
    ) {
      timeoutPending.value = true
      return
    }
    if (
      (sourceMode.value === 'uri' || sourceMode.value === 'base64') &&
      err instanceof ApiError &&
      (err.status === 400 || err.status === 404 || err.status === 422)
    ) {
      sourceError.value = getErrorMessage(err)
      return
    }
    errorMessage.value = getErrorMessage(err)
  } finally {
    inferRunning.value = false
  }
}

async function persistCurrentResult(): Promise<void> {
  const payload = inferenceResult.value
  const dep = selectedDeployment.value
  if (!payload || !dep) return
  savingRecord.value = true
  saveErrorMessage.value = null
  try {
    savedRecord.value = await saveDirectInferenceRecord({
      projectId: selectedProjectId.value,
      requestId: payload.request_id || lastRequestId.value || createClientRequestId(),
      taskType: activeTaskType.value,
      deploymentInstanceId: dep.deployment_instance_id,
      resultPayload: payload as unknown as Record<string, unknown>,
      inputLabel: currentInputLabel.value,
      inputImageBase64: sourceMode.value === 'base64' ? imageBase64.value.trim() : undefined,
      inputImageFile: sourceMode.value === 'upload' ? uploadedFile.value : undefined,
      parameters: {
        score_threshold: scoreThreshold.value,
        top_k: topK.value,
        mask_threshold: maskThreshold.value,
        keypoint_confidence_threshold: keypointConfidenceThreshold.value,
      },
    })
  } catch (err) {
    saveErrorMessage.value = getErrorMessage(err)
  } finally {
    savingRecord.value = false
  }
}

async function retryOrManualSave(): Promise<void> {
  await persistCurrentResult()
}

async function lookupTimedOutSave(): Promise<void> {
  if (!selectedProjectId.value || !lastRequestId.value) return
  lookupLoading.value = true
  try {
    const matches = await listDirectInferenceRecords({
      projectId: selectedProjectId.value,
      requestId: lastRequestId.value,
    })
    if (matches.length === 0) {
      errorMessage.value = '暂未查询到对应 request_id 的已保存记录。'
      return
    }
    await openSavedRecordInWorkbench(matches[0].record_id)
    timeoutPending.value = false
  } catch (err) {
    errorMessage.value = getErrorMessage(err)
  } finally {
    lookupLoading.value = false
  }
}

async function openSavedRecordInWorkbench(recordId: string): Promise<void> {
  try {
    const detail = await getDirectInferenceRecord(recordId)
    if (deployments.value.some((d) => d.deployment_instance_id === detail.deployment_instance_id)) {
      selectedDeploymentId.value = detail.deployment_instance_id
    }
    inferenceResult.value = detail.result_payload as unknown as TaskInferencePayload
    savedRecord.value = detail
    lastRequestId.value = detail.request_id
    requestDurationMs.value = detail.latency_ms ?? null
    completedAtText.value = formatSystemDateTime(detail.created_at)
    revokeExternalImageUrl()
    if (detail.has_input_image || detail.has_preview_image) {
      try {
        const blob = await fetchDirectInferenceRecordImageBlob(
          detail.record_id,
          detail.has_input_image ? 'input' : 'preview',
        )
        externalImageUrl.value = URL.createObjectURL(blob)
      } catch {
        externalImageUrl.value = null
      }
    }
    inspectorOpen.value = true
    setActiveTab('workbench')
  } catch (err) {
    errorMessage.value = getErrorMessage(err)
  }
}

async function openAsyncTaskInWorkbench(
  asyncTask: TaskInferenceTaskSummary & { task_type: ModelTaskType },
): Promise<void> {
  try {
    const res = await getTaskInferenceTaskResult(asyncTask.task_type, asyncTask.task_id)
    if (deployments.value.some((d) => d.deployment_instance_id === asyncTask.deployment_instance_id)) {
      selectedDeploymentId.value = asyncTask.deployment_instance_id
    }
    inferenceResult.value = res.payload as unknown as TaskInferencePayload
    savedRecord.value = null
    lastRequestId.value = asyncTask.task_id
    requestDurationMs.value = asyncTask.latency_ms ?? null
    completedAtText.value = formatSystemDateTime(asyncTask.finished_at || asyncTask.created_at)
    revokeExternalImageUrl()
    const imgKey =
      asyncTask.preview_image_object_key ||
      (typeof asyncTask.input_uri === 'string' && asyncTask.input_uri.startsWith('projects/')
        ? asyncTask.input_uri
        : null)
    if (imgKey) {
      try {
        const blob = await fetchAuthorizedProjectFileBlob(selectedProjectId.value, imgKey)
        externalImageUrl.value = URL.createObjectURL(blob)
      } catch {
        externalImageUrl.value = null
      }
    }
    inspectorOpen.value = true
    setActiveTab('workbench')
  } catch (err) {
    errorMessage.value = getErrorMessage(err)
  }
}

function startBatchCreate(): void {
  createSeedDeploymentId.value = selectedDeploymentId.value
  createSeedFileIds.value = []
  tasksViewMode.value = 'create'
}

function openBatchDetail(batchTaskId: string): void {
  activeBatchTaskId.value = batchTaskId
  tasksViewMode.value = 'detail'
  void router.replace({ query: { tab: 'tasks', batch_id: batchTaskId } })
}

function handleBatchCreated(task: BatchInferenceTask): void {
  openBatchDetail(task.batch_task_id)
}

function closeBatchDetail(): void {
  activeBatchTaskId.value = ''
  tasksViewMode.value = 'list'
  void router.replace({ query: { tab: 'tasks' } })
}

function handleBatchDeleted(): void {
  closeBatchDetail()
}

function retryBatchFailedItems(payload: { deploymentId: string; fileIds: string[] }): void {
  createSeedDeploymentId.value = payload.deploymentId
  createSeedFileIds.value = payload.fileIds
  tasksViewMode.value = 'create'
}

function handleSelectItem(id: string): void {
  selectedItemId.value = id
  inspectorOpen.value = true
}

function isPoseKeypointVisible(item: OverlayRenderItem, kp: PoseInferenceKeypoint): boolean {
  return (kp.confidence ?? 1) >= item.keypointThreshold && (kp.x !== 0 || kp.y !== 0)
}

function countDetectedPoseKeypoints(item: OverlayRenderItem): number {
  return (item.keypoints ?? []).filter((kp) => isPoseKeypointVisible(item, kp)).length
}

function formatObbAngleText(item: OverlayRenderItem): string {
  const deg = formatObbAngleDeg(item)
  return deg !== null ? `${deg.toFixed(1)}°` : '—'
}

function formatMs(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)} ms` : '—'
}
</script>

<style scoped>
.inf-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.inf-page--workbench {
  min-width: 0;
}

.inf-readonly-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid var(--am-border);
  background: var(--am-surface-soft);
  color: var(--am-text-muted);
  font-size: 13px;
  flex: none;
}

.inf-version-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px 14px;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid color-mix(in srgb, #f59e0b 55%, transparent);
  background: color-mix(in srgb, #f59e0b 10%, var(--am-surface));
  flex: none;
}

.inf-version-banner__left {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #b45309;
  font-size: 13px;
}

:root[data-theme='dark'] .inf-version-banner__left {
  color: #fbbf24;
}

.inf-version-banner__actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: none;
}

@media (min-width: 841px) {
  .inf-page--workbench {
    height: calc(100dvh - 56px);
    min-height: 540px;
  }
}

.inf-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--am-border);
  flex: none;
}

.inf-nav__actions {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 6px;
  flex: none;
}

.inf-target-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 2px;
  flex: none;
}

.inf-target-bar__left {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  min-width: 0;
}

.inf-target-field {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.inf-target-field__label {
  font-size: 13px;
  color: var(--am-text-muted);
  white-space: nowrap;
}

.inf-target-meta {
  font-size: 13px;
  color: var(--am-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 480px;
}

.inf-target-bar__right {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  flex: none;
}

.inf-status-dot-label {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  color: var(--am-text-strong);
  white-space: nowrap;
}

.inf-status-dot-label.is-brand {
  color: var(--am-action-primary);
  font-weight: 600;
}

.inf-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}

.inf-status-dot.is-ok {
  background: var(--am-action-primary);
}

.inf-status-dot.is-warn {
  background: #f59e0b;
}

.inf-deploy-link-btn {
  display: inline-flex;
  align-items: center;
  height: 34px;
  padding: 0 12px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface);
  color: var(--am-text-strong);
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  white-space: nowrap;
}

.inf-deploy-link-btn:hover {
  background: var(--am-hover-surface);
}

.inf-workbench-grid {
  display: grid;
  grid-template-columns: 288px minmax(0, 1fr);
  gap: 14px;
  flex: 1 1 0;
  min-height: 0;
}

@media (841px <= width <= 1080px) {
  .inf-workbench-grid {
    grid-template-columns: 248px minmax(0, 1fr);
    gap: 12px;
  }

  .inf-workbench-grid :deep(.inf-input-card__body) {
    gap: 10px;
  }

  .inf-workbench-grid :deep(.inf-dropzone) {
    padding-block: 14px;
  }

  .inf-target-meta {
    max-width: 100%;
  }
}

@media (max-width: 840px) {
  .inf-workbench-grid {
    grid-template-columns: 1fr;
    flex: none;
  }
}

.inf-canvas-stage {
  position: relative;
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: flex;
}

.inf-below-table-wrap {
  padding: 8px 14px;
  border-top: 1px solid var(--am-border);
  background: var(--am-surface);
}

.inf-inline-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.inf-inline-table th {
  padding: 6px 8px;
  text-align: left;
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text-muted);
  border-bottom: 1px solid var(--am-border);
}

.inf-inline-table td {
  padding: 6px 8px;
  color: var(--am-text-strong);
  border-bottom: 1px solid var(--am-border);
  font-variant-numeric: tabular-nums;
}

.inf-inline-table tbody tr:last-child td {
  border-bottom: 0;
}

.inf-inline-table tbody tr.is-selected {
  background: var(--am-row-selected);
}

.inf-pose-inline-grid {
  display: grid;
  grid-template-columns: 1fr 190px;
  gap: 14px;
  align-items: start;
}

.inf-pose-inline-summary {
  display: grid;
  gap: 6px;
  padding: 6px 0;
  font-size: 13px;
}

.inf-pose-inline-summary > div {
  display: flex;
  justify-content: space-between;
  color: var(--am-text-muted);
}

.inf-pose-inline-summary strong {
  color: var(--am-text-strong);
}

.inf-dot-value {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.inf-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}

.inf-canvas-footer {
  display: grid;
  gap: 8px;
  padding: 10px 14px;
  border-top: 1px solid var(--am-border);
  background: var(--am-surface);
}

.inf-save-error-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid #f59e0b;
  background: color-mix(in srgb, #f59e0b 10%, var(--am-surface));
}

.inf-save-error-bar__left {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #d97706;
  font-size: 13px;
}

.inf-save-error-bar__left strong {
  display: block;
}

.inf-save-error-bar__left span {
  font-size: 12px;
  color: var(--am-text);
}

.inf-canvas-footer__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px 16px;
  font-size: 13px;
}

.inf-canvas-footer__row--result {
  padding-top: 6px;
  border-top: 1px solid var(--am-border);
}

.inf-canvas-footer__file {
  color: var(--am-text-strong);
  font-weight: 500;
}

.inf-canvas-footer__time {
  color: var(--am-text-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.inf-canvas-footer__stats,
.inf-canvas-footer__right {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  color: var(--am-text-strong);
  font-variant-numeric: tabular-nums;
}

.inf-muted {
  color: var(--am-text-muted);
}

.inf-saved-pill {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 9px;
  border-radius: 999px;
  background: var(--am-action-soft);
  color: var(--am-action-primary);
  font-size: 12px;
  font-weight: 600;
}

.inf-records-section {
  display: grid;
  gap: 12px;
  padding: 16px;
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
}

.inf-records-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.inf-records-section th {
  font-size: 14px;
  font-weight: 600;
}

.inf-fullscreen-modal {
  position: fixed;
  inset: 0;
  z-index: 90;
  background: var(--am-page);
  display: flex;
  flex-direction: column;
}

.inf-fs-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--am-border);
  background: var(--am-surface);
}

.inf-fs-header__left {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.inf-fs-header__title {
  font-size: 14px;
  color: var(--am-text-strong);
}

.inf-fs-header__meta {
  font-size: 13px;
  color: var(--am-text-muted);
}
</style>
