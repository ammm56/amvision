<template>
  <section class="inf-batch-detail">
    <header class="inf-bd-header">
      <div class="inf-bd-header__left">
        <Button size="sm" variant="secondary" @click="emit('back')">
          <ArrowLeft :size="14" />
          返回
        </Button>
        <span class="inf-bd-header__sep" aria-hidden="true" />
        <h2>{{ task?.display_name || batchTaskId }}</h2>
        <span v-if="task" class="inf-bd-state-pill" :class="`is-${statusTone(task.state)}`">
          <span class="inf-dot" :class="`is-${statusTone(task.state)}`" />
          <span>{{ formatTaskStatus(task.state) }}</span>
        </span>
      </div>

      <div class="inf-bd-header__right">
        <Button size="sm" variant="secondary" :loading="loading" @click="refreshAll">
          <RefreshCw :size="14" />
          刷新
        </Button>
        <Button
          v-if="canWriteTasks && isActive"
          size="sm"
          variant="primary"
          class="inf-btn-warn"
          @click="cancelModalOpen = true"
        >
          取消任务
        </Button>
        <Button
          v-else-if="canWriteTasks && task"
          size="sm"
          variant="danger"
          @click="deleteModalOpen = true"
        >
          删除
        </Button>
      </div>
    </header>

    <InlineError :message="errorMessage" />

    <section v-if="task" class="inf-bd-summary-card">
      <div class="inf-bd-meta-grid">
        <div class="inf-bd-meta-item">
          <small>部署</small>
          <strong :title="task.deployment_display_name || task.deployment_instance_id">
            {{ task.deployment_display_name || task.deployment_instance_id }}
          </strong>
        </div>
        <div class="inf-bd-meta-item">
          <small>模型</small>
          <strong :title="deploymentInfo?.model_name || task.model_version_id || '—'">
            {{ deploymentInfo?.model_name || task.model_version_id || '—' }}
          </strong>
        </div>
        <div class="inf-bd-meta-item">
          <small>任务 / 通道</small>
          <strong :title="`${modelTaskLabel(task.task_type, true)} · ${executionChannelLabel}`">
            {{ modelTaskLabel(task.task_type, true) }} · {{ executionChannelLabel }}
          </strong>
        </div>
        <div class="inf-bd-meta-item">
          <small>运行环境</small>
          <strong :title="deploymentEnvText">{{ deploymentEnvText }}</strong>
        </div>
        <div class="inf-bd-meta-item">
          <small>开始时间</small>
          <strong>{{ formatSystemDateTime(task.started_at || task.created_at) }}</strong>
        </div>
        <div class="inf-bd-meta-item">
          <small>结束时间</small>
          <strong>{{ task.finished_at ? formatSystemDateTime(task.finished_at) : '—' }}</strong>
        </div>
      </div>

      <div class="inf-bd-progress-row">
        <span class="inf-bd-progress-label">整体进度</span>
        <strong class="inf-bd-progress-nums">
          {{ task.completed_items }} / {{ task.total_items }} ({{ progressPercent }}%)
        </strong>
        <div class="inf-bd-progress-track">
          <div class="inf-bd-progress-fill" :style="{ width: `${progressPercent}%` }" />
        </div>
      </div>

      <div class="inf-bd-counts-row">
        <div class="inf-bd-counts-left">
          <span><i class="inf-dot is-ok" /> 成功 <strong>{{ task.succeeded_items }}</strong></span>
          <span><i class="inf-dot is-danger" /> 失败 <strong>{{ task.failed_items }}</strong></span>
          <span><i class="inf-dot is-warn" /> 执行中/排队 <strong>{{ runningOrQueuedCount }}</strong></span>
          <span><i class="inf-dot is-neutral" /> 未执行 <strong>{{ pendingOrSkippedCount }}</strong></span>
        </div>
        <div class="inf-bd-counts-total">
          合计 <strong>{{ task.total_items }}</strong>
        </div>
      </div>
    </section>

    <section v-if="task" class="inf-bd-main-card">
      <nav class="inf-bd-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          :class="{ 'is-active': activeTab === 'items' }"
          @click="activeTab = 'items'"
        >
          样本结果
        </button>
        <button
          type="button"
          role="tab"
          :class="{ 'is-active': activeTab === 'info' }"
          @click="activeTab = 'info'"
        >
          任务信息
        </button>
        <button
          type="button"
          role="tab"
          :class="{ 'is-active': activeTab === 'json' }"
          @click="activeTab = 'json'"
        >
          汇总 JSON
        </button>
      </nav>

      <template v-if="activeTab === 'items'">
        <div class="inf-bd-items-toolbar">
          <div class="inf-bd-filter-pills">
            <button
              v-for="pill in itemStatePills"
              :key="pill.value"
              type="button"
              class="inf-pill-btn"
              :class="{ 'is-active': itemStateFilter === pill.value }"
              @click="selectItemStateFilter(pill.value)"
            >
              {{ pill.label }}
            </button>
          </div>
          <div class="inf-bd-search">
            <Search :size="14" />
            <input
              v-model="itemSearch"
              type="text"
              placeholder="搜索文件名"
              @input="itemOffset = 0"
            />
          </div>
        </div>

        <div class="inf-bd-table-wrap">
          <table class="inf-bd-table">
            <thead>
              <tr>
                <th>文件名</th>
                <th>状态</th>
                <th>目标数</th>
                <th>服务端耗时</th>
                <th v-if="showFailureReasonColumn">失败原因</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in pagedItems"
                :key="item.item_id"
                :class="{ 'is-selected': activeFailureItem?.item_id === item.item_id }"
              >
                <td class="col-fname">
                  <strong :title="item.input_label">{{ item.input_label }}</strong>
                </td>
                <td class="col-state">
                  <span class="inf-dot-status">
                    <span class="inf-dot" :class="`is-${statusTone(item.state)}`" />
                    <span>{{ formatItemStatus(item.state) }}</span>
                  </span>
                </td>
                <td>{{ typeof item.item_count === 'number' ? item.item_count : '—' }}</td>
                <td>{{ typeof item.latency_ms === 'number' ? `${item.latency_ms.toFixed(1)} ms` : '—' }}</td>
                <td v-if="showFailureReasonColumn" class="col-err">
                  <span :title="item.error_message || ''">{{ item.error_message || '—' }}</span>
                </td>
                <td class="col-actions">
                  <button
                    v-if="item.state === 'succeeded'"
                    type="button"
                    class="inf-link-action is-primary"
                    @click="openFullscreenForItem(item)"
                  >
                    查看结果
                  </button>
                  <button
                    v-else-if="item.state === 'failed'"
                    type="button"
                    class="inf-link-action is-primary"
                    @click="openFailureDrawer(item)"
                  >
                    查看原因
                  </button>
                  <span v-else class="inf-muted">—</span>
                </td>
              </tr>
              <tr v-if="pagedItems.length === 0">
                <td :colspan="showFailureReasonColumn ? 6 : 5" class="inf-bd-empty-td">当前筛选条件下暂无样本记录</td>
              </tr>
            </tbody>
          </table>

          <div v-if="filteredItems.length > 0 || task.failed_items > 0" class="inf-bd-items-footer">
            <div v-if="task.failed_items > 0" class="inf-bd-items-footer__left">
              <span class="inf-bd-retain-note">
                <Info :size="14" />
                成功结果已保留
              </span>
              <Button
                v-if="canWriteTasks && failedRetryFileIds.length > 0"
                size="sm"
                variant="primary"
                @click="retryFailed"
              >
                以失败项新建任务
              </Button>
            </div>

            <div v-if="filteredItems.length > 0" class="inf-bd-items-footer__pager">
              <PaginationControls
                numbered
                :offset="itemOffset"
                :limit="itemPageSize"
                :item-count="pagedItems.length"
                :total-count="filteredItems.length"
                @previous="itemOffset = Math.max(0, itemOffset - itemPageSize)"
                @next="itemOffset = itemOffset + itemPageSize"
                @go="itemOffset = $event"
              >
                <template #summary>共 {{ filteredItems.length }} 项</template>
              </PaginationControls>
              <SelectField
                fit-options
                floating
                :model-value="String(itemPageSize)"
                :options="pageSizeOptions"
                @update:model-value="changeItemPageSize"
              />
            </div>
          </div>
        </div>
      </template>

      <template v-else-if="activeTab === 'info'">
        <div class="inf-bd-info-sections">
          <div class="inf-bd-info-box">
            <h4>执行配置</h4>
            <dl class="inf-bd-kv-two">
              <div><dt>部署</dt><dd>{{ task.deployment_display_name || task.deployment_instance_id }}</dd></div>
              <div><dt>执行通道</dt><dd>{{ executionChannelLabel }}</dd></div>
              <div><dt>任务类型</dt><dd>{{ modelTaskLabel(task.task_type, true) }}</dd></div>
              <div><dt>模型名称</dt><dd>{{ deploymentInfo?.model_name || task.model_version_id || '—' }}</dd></div>
              <div><dt>运行环境</dt><dd>{{ deploymentEnvText }}</dd></div>
              <div><dt>创建时间</dt><dd>{{ formatSystemDateTime(task.created_at) }}</dd></div>
            </dl>
          </div>

          <div class="inf-bd-info-box">
            <h4>输入与参数</h4>
            <dl class="inf-bd-kv-two">
              <div><dt>输入来源</dt><dd>{{ formatSourceKindLabel(task.source_kind) }}</dd></div>
              <div><dt>总样本数</dt><dd>{{ task.total_items }} 张</dd></div>
              <div>
                <dt>{{ task.task_type === 'classification' ? 'Top-K' : '置信度阈值' }}</dt>
                <dd>{{ task.task_type === 'classification' ? (task.parameters?.top_k ?? '—') : (task.parameters?.score_threshold ?? '—') }}</dd>
              </div>
              <div><dt>保存预览图</dt><dd>{{ task.parameters?.save_result_image ? '是' : '否' }}</dd></div>
            </dl>
          </div>

          <div class="inf-bd-info-box">
            <h4>标识信息</h4>
            <dl class="inf-bd-kv-two">
              <div>
                <dt>任务 ID</dt>
                <dd class="inf-mono-row">
                  <code>{{ task.batch_task_id }}</code>
                  <button type="button" class="inf-copy-mini" title="复制任务 ID" @click="copyText(task.batch_task_id)">
                    <Copy :size="12" />
                  </button>
                </dd>
              </div>
              <div>
                <dt>结果前缀</dt>
                <dd class="inf-mono-row">
                  <code>{{ task.output_object_prefix }}</code>
                  <button type="button" class="inf-copy-mini" title="复制结果前缀" @click="copyText(task.output_object_prefix)">
                    <Copy :size="12" />
                  </button>
                </dd>
              </div>
            </dl>
          </div>
        </div>
      </template>

      <template v-else>
        <div class="inf-bd-json-wrap">
          <div class="inf-bd-json-actions">
            <Button size="sm" variant="secondary" @click="copyText(taskSummaryJson)">
              <Copy :size="13" />
              复制 JSON
            </Button>
            <Button size="sm" variant="secondary" @click="downloadSummaryJson">
              <Download :size="13" />
              下载 JSON
            </Button>
          </div>
          <pre class="inf-bd-json-pre">{{ taskSummaryJson }}</pre>
        </div>
      </template>
    </section>

    <aside
      v-if="activeFailureItem"
      class="inf-failure-drawer"
      role="complementary"
      aria-label="失败样本详情"
      data-failure-drawer
    >
      <header class="inf-failure-drawer__head">
        <h3>样本详情</h3>
        <button type="button" class="inf-modal-x" aria-label="关闭样本详情" @click="closeFailureDrawer">
          <X :size="16" />
        </button>
      </header>

      <div class="inf-failure-drawer__body">
        <div class="inf-failure-drawer__title">
          <strong>{{ activeFailureItem.input_label }}</strong>
          <span class="inf-dot-status is-danger">
            <span class="inf-dot is-danger" />
            <span>失败</span>
          </span>
        </div>

        <div class="inf-failure-drawer__preview">
          <img v-if="failurePreviewUrl" :src="failurePreviewUrl" :alt="activeFailureItem.input_label" />
          <div v-else class="inf-failure-drawer__noprev">
            <ImageOff :size="28" />
            <strong>无法预览图片</strong>
            <span>{{ activeFailureItem.error_message || '文件损坏或读取失败' }}</span>
          </div>
        </div>

        <dl class="inf-failure-kv">
          <div>
            <dt>错误代码</dt>
            <dd class="is-danger-text">{{ activeFailureItem.error_code || 'EXECUTION_ERROR' }}</dd>
          </div>
          <div>
            <dt>错误信息</dt>
            <dd>{{ activeFailureItem.error_message || '推理执行失败' }}</dd>
          </div>
          <div>
            <dt>部署</dt>
            <dd>{{ task?.deployment_display_name || '-' }}</dd>
          </div>
          <div>
            <dt>原始文件</dt>
            <dd>{{ activeFailureItem.input_label }}</dd>
          </div>
          <div>
            <dt>图像尺寸</dt>
            <dd>
              {{
                activeFailureItem.image_width && activeFailureItem.image_height
                  ? `${activeFailureItem.image_width} × ${activeFailureItem.image_height}`
                  : '—'
              }}
            </dd>
          </div>
          <div>
            <dt>推理耗时</dt>
            <dd>
              {{ typeof activeFailureItem.latency_ms === 'number' ? `${activeFailureItem.latency_ms.toFixed(1)} ms` : '—' }}
            </dd>
          </div>
        </dl>

        <div class="inf-failure-diag">
          <div class="inf-failure-diag__head">
            <button type="button" @click="showFailureDiag = !showFailureDiag">
              <ChevronDown :size="14" />
              诊断信息
            </button>
            <button type="button" @click="copyText(JSON.stringify(activeFailureItem, null, 2))">
              <Copy :size="12" />
              复制
            </button>
          </div>
          <pre v-if="showFailureDiag" class="inf-failure-diag__pre">{{ JSON.stringify(activeFailureItem, null, 2) }}</pre>
        </div>
      </div>

      <footer class="inf-failure-drawer__foot">
        <Button variant="secondary" @click="closeFailureDrawer">关闭</Button>
        <Button
          v-if="canWriteTasks && activeFailureItem.input_file_id"
          variant="primary"
          @click="retrySingleSample(activeFailureItem.input_file_id)"
        >
          以此样本新建任务
        </Button>
      </footer>
    </aside>

    <Teleport to="body">
      <div
        v-if="fullscreenItem"
        class="inf-batch-fullscreen"
        role="dialog"
        aria-modal="true"
        aria-label="批量样本大图"
      >
        <InferenceCanvasViewer
          :image-src="fullscreenImageUrl"
          :image-width="fullscreenItem.image_width || 0"
          :image-height="fullscreenItem.image_height || 0"
          :task-type="taskType"
          :has-result="Boolean(fullscreenResultPayload)"
          :loading-image="fullscreenLoading"
          :inspector-open="fullscreenInspectorOpen"
          :source-error="fullscreenItem.state === 'failed' ? fullscreenItem.error_message : null"
          :all-items="fullscreenAllItems"
          :visible-items="fullscreenVisibleItems"
          :selected-item-id="fullscreenSelectedItemId"
          :view-mode="fullscreenViewMode"
          :layers="fullscreenLayers"
          :mask-opacity="fullscreenMaskOpacity"
          :show-contours="fullscreenShowContours"
          :min-display-score="fullscreenMinScore"
          :selected-classes="fullscreenSelectedClasses"
          :fullscreen="true"
          @update:view-mode="fullscreenViewMode = $event"
          @update:layers="fullscreenLayers = $event"
          @update:mask-opacity="fullscreenMaskOpacity = $event"
          @update:min-display-score="fullscreenMinScore = $event"
          @update:selected-classes="fullscreenSelectedClasses = $event"
          @select-item="handleFullscreenSelectItem"
          @toggle-inspector="fullscreenInspectorOpen = !fullscreenInspectorOpen"
          @toggle-fullscreen="closeFullscreen"
        >
          <template #header>
            <header class="inf-bfs-header">
              <div class="inf-bfs-header__left">
                <Button size="sm" variant="secondary" data-batch-fs-back @click="closeFullscreen">
                  <ArrowLeft :size="14" />
                  返回任务
                </Button>
                <span class="inf-bfs-task">{{ task?.display_name }}</span>
                <strong class="inf-bfs-file">{{ fullscreenItem.input_label }}</strong>
                <span
                  class="inf-dot-status"
                  :class="fullscreenItem.state === 'succeeded' ? 'is-brand' : 'is-danger'"
                >
                  <span
                    class="inf-dot"
                    :class="fullscreenItem.state === 'succeeded' ? 'is-ok' : 'is-danger'"
                  />
                  <span>{{ fullscreenItem.state === 'succeeded' ? '推理成功' : '推理失败' }}</span>
                </span>
                <span class="inf-bfs-meta">
                  {{
                    fullscreenItem.image_width && fullscreenItem.image_height
                      ? `${fullscreenItem.image_width} × ${fullscreenItem.image_height}`
                      : '尺寸 —'
                  }}
                </span>
                <span v-if="fullscreenItem.state === 'succeeded'" class="inf-bfs-meta">
                  目标 {{ fullscreenVisibleItems.length }}
                </span>
              </div>

              <div class="inf-bfs-header__nav">
                <select v-model="fullscreenNavScope" class="inf-bfs-scope" aria-label="翻页筛选范围">
                  <option value="all">全部 {{ allItems.length }}</option>
                  <option value="succeeded">仅成功 {{ succeededNavList.length }}</option>
                  <option value="failed">仅失败 {{ failedNavList.length }}</option>
                </select>
                <Button
                  size="sm"
                  variant="secondary"
                  :disabled="fullscreenNavIndex <= 0"
                  data-batch-fs-prev
                  @click="navigateFullscreen(-1)"
                >
                  <ChevronLeft :size="14" />
                  上一张
                </Button>
                <span class="inf-bfs-pos">
                  {{ fullscreenNavIndex >= 0 ? fullscreenNavIndex + 1 : 0 }} / {{ fullscreenNavPool.length }}
                </span>
                <Button
                  size="sm"
                  variant="secondary"
                  :disabled="fullscreenNavIndex < 0 || fullscreenNavIndex >= fullscreenNavPool.length - 1"
                  data-batch-fs-next
                  @click="navigateFullscreen(1)"
                >
                  下一张
                  <ChevronRight :size="14" />
                </Button>
                <Button
                  v-if="failedNavList.length > 0"
                  size="sm"
                  variant="secondary"
                  @click="jumpNextFailed"
                >
                  下一失败项
                  <ChevronRight :size="14" />
                </Button>
              </div>
            </header>
          </template>

          <template #footer>
            <div class="inf-bfs-footer">
              <div class="inf-bfs-footer__classes">
                <span v-for="cls in fullscreenClassPills" :key="cls.className" class="inf-dot-status">
                  <span class="inf-dot" :style="{ backgroundColor: cls.color }" />
                  <span>{{ cls.className }} {{ cls.count }}</span>
                </span>
              </div>
              <div class="inf-bfs-footer__timing">
                <span>
                  服务端 {{ typeof fullscreenItem.latency_ms === 'number' ? `${fullscreenItem.latency_ms.toFixed(1)} ms` : '—' }}
                </span>
                <span v-if="fullscreenItem.finished_at">
                  {{ formatSystemDateTime(fullscreenItem.finished_at) }}
                </span>
              </div>
            </div>
          </template>

          <template #overlay>
            <InferenceResultInspector
              :open="fullscreenInspectorOpen && Boolean(fullscreenResultPayload)"
              :task-type="taskType"
              :all-items="fullscreenAllItems"
              :items="fullscreenInspectorItems"
              :selected-item-id="fullscreenSelectedItemId"
              :payload="fullscreenResultPayload"
              :image-src="fullscreenImageUrl"
              :input-label="fullscreenItem.input_label"
              :request-id="fullscreenResultPayload?.request_id || null"
              :request-duration-ms="fullscreenItem.latency_ms ?? null"
              :completed-at-text="fullscreenItem.finished_at ? formatSystemDateTime(fullscreenItem.finished_at) : '—'"
              :deployment-meta="fullscreenDeploymentMeta"
              :layers="fullscreenLayers"
              :min-display-score="fullscreenMinScore"
              :selected-classes="fullscreenSelectedClasses"
              :isolate-item-id="fullscreenIsolateItemId"
              :show-contours="fullscreenShowContours"
              :mask-opacity="fullscreenMaskOpacity"
              @close="fullscreenInspectorOpen = false"
              @select-item="handleFullscreenSelectItem"
              @update:layers="fullscreenLayers = $event"
              @update:min-display-score="fullscreenMinScore = $event"
              @update:selected-classes="fullscreenSelectedClasses = $event"
              @update:isolate-item-id="fullscreenIsolateItemId = $event"
              @update:show-contours="fullscreenShowContours = $event"
            />
          </template>
        </InferenceCanvasViewer>
      </div>

      <div
        v-if="cancelModalOpen"
        class="inf-modal-backdrop"
        role="dialog"
        aria-modal="true"
        @click.self="cancelModalOpen = false"
      >
        <div class="inf-confirm-modal">
          <header class="inf-confirm-modal__head">
            <h3>取消推理任务?</h3>
            <button type="button" class="inf-modal-x" @click="cancelModalOpen = false">
              <X :size="16" />
            </button>
          </header>
          <div class="inf-confirm-modal__body">
            <p>任务：{{ task?.display_name }}</p>
            <p class="inf-muted-sm">取消后将保留已完成的结果，未执行的样本将标记为已取消。</p>
          </div>
          <footer class="inf-confirm-modal__foot">
            <Button variant="secondary" @click="cancelModalOpen = false">继续执行</Button>
            <Button variant="primary" class="inf-btn-warn" :loading="actionBusy" @click="confirmCancel">
              确认取消
            </Button>
          </footer>
        </div>
      </div>

      <div
        v-if="deleteModalOpen"
        class="inf-modal-backdrop"
        role="dialog"
        aria-modal="true"
        @click.self="deleteModalOpen = false"
      >
        <div class="inf-confirm-modal">
          <header class="inf-confirm-modal__head">
            <h3>删除批量任务?</h3>
            <button type="button" class="inf-modal-x" @click="deleteModalOpen = false">
              <X :size="16" />
            </button>
          </header>
          <div class="inf-confirm-modal__body">
            <p>确认删除 “{{ task?.display_name }}” 及关联产物文件？</p>
          </div>
          <footer class="inf-confirm-modal__foot">
            <Button variant="secondary" @click="deleteModalOpen = false">取消</Button>
            <Button variant="danger" :loading="actionBusy" @click="confirmDelete">确认删除</Button>
          </footer>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ArrowLeft,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  ImageOff,
  Info,
  RefreshCw,
  Search,
  X,
} from '@lucide/vue'

import {
  formatDeploymentBackend,
  formatDeploymentDeviceName,
  formatDeploymentPrecision,
} from '@/modules/deployments/deployment-presentation'
import type { ModelTaskType, TaskDeploymentInstance } from '@/modules/deployments/services/deployment.service'
import { modelTaskLabel } from '@/modules/models/model-evaluation-types'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import { getErrorMessage } from '@/shared/api/error'
import Button from '@/shared/ui/components/Button.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import {
  cancelBatchInferenceTask,
  deleteBatchInferenceTask,
  fetchBatchInferenceTaskItemImageBlob,
  getBatchInferenceTask,
  getBatchInferenceTaskItemResult,
  listBatchInferenceTaskItems,
  type BatchInferenceTask,
  type BatchInferenceTaskItem,
  type TaskInferencePayload,
} from '../services/inference.service'
import InferenceCanvasViewer from './InferenceCanvasViewer.vue'
import InferenceResultInspector, { type InspectorDeploymentMeta } from './InferenceResultInspector.vue'
import {
  filterOverlayItems,
  normalizeInferenceOverlayItems,
  summarizeOverlayClasses,
  type CanvasViewMode,
  type InferenceLayerVisibility,
} from './inference-overlay.utils'

const props = withDefaults(
  defineProps<{
    batchTaskId: string
    deployments: TaskDeploymentInstance[]
    canWriteTasks?: boolean
  }>(),
  {
    canWriteTasks: true,
  },
)

const emit = defineEmits<{
  back: []
  deleted: [batchTaskId: string]
  'retry-failed-items': [payload: { deploymentId: string; fileIds: string[] }]
}>()

const loading = ref(false)
const actionBusy = ref(false)
const errorMessage = ref<string | null>(null)
const task = ref<BatchInferenceTask | null>(null)
const allItems = ref<BatchInferenceTaskItem[]>([])

const activeTab = ref<'items' | 'info' | 'json'>('items')
const itemStateFilter = ref<'all' | 'succeeded' | 'failed' | 'pending'>('all')
const itemSearch = ref('')
const itemOffset = ref(0)
const itemPageSize = ref(10)

const activeFailureItem = ref<BatchInferenceTaskItem | null>(null)
const failurePreviewUrl = ref<string | null>(null)
const showFailureDiag = ref(false)

const fullscreenItem = ref<BatchInferenceTaskItem | null>(null)
const fullscreenImageUrl = ref<string | null>(null)
const fullscreenLoading = ref(false)
const fullscreenResultPayload = ref<TaskInferencePayload | null>(null)
const fullscreenInspectorOpen = ref(false)
const fullscreenSelectedItemId = ref<string | null>(null)
const fullscreenIsolateItemId = ref<string | null>(null)
const fullscreenViewMode = ref<CanvasViewMode>('overlay')
const fullscreenMinScore = ref(0)
const fullscreenSelectedClasses = ref<string[]>([])
const fullscreenMaskOpacity = ref(0.35)
const fullscreenShowContours = ref(true)
const fullscreenNavScope = ref<'all' | 'succeeded' | 'failed'>('all')
const fullscreenLayers = ref<InferenceLayerVisibility>({
  boxes: true,
  masks: true,
  keypoints: true,
  skeleton: true,
  labels: true,
})

const cancelModalOpen = ref(false)
const deleteModalOpen = ref(false)

let pollTimer: number | undefined
let fsLoadGen = 0

const pageSizeOptions = [10, 20, 50].map((n) => ({ value: String(n), label: `${n} 条/页` }))

const isActive = computed(() => task.value?.state === 'queued' || task.value?.state === 'running')
const taskType = computed<ModelTaskType>(
  () => (task.value?.task_type as ModelTaskType) || 'detection',
)
const executionChannelLabel = computed(() =>
  task.value?.parameters?.execution_runtime_mode === 'sync' ? '同步通道' : '异步通道',
)
const showFailureReasonColumn = computed(
  () => (task.value?.failed_items ?? 0) > 0 || itemStateFilter.value === 'failed',
)
function formatSourceKindLabel(kind: string): string {
  if (kind === 'dataset_version') return '数据集版本'
  if (kind === 'project_files') return '项目文件'
  if (kind === 'upload') return '上传图片'
  return kind
}
const deploymentInfo = computed(
  () =>
    props.deployments.find((d) => d.deployment_instance_id === task.value?.deployment_instance_id) ??
    null,
)
const deploymentEnvText = computed(() => {
  if (!deploymentInfo.value) return '-'
  return [
    formatDeploymentBackend(deploymentInfo.value.runtime_backend),
    formatDeploymentPrecision(deploymentInfo.value.runtime_precision),
    formatDeploymentDeviceName(deploymentInfo.value.device_name),
  ]
    .filter(Boolean)
    .join(' ')
})

const progressPercent = computed(() => {
  if (!task.value) return 0
  return Math.min(100, Math.round((task.value.completed_items / Math.max(1, task.value.total_items)) * 100))
})
const runningOrQueuedCount = computed(() =>
  allItems.value.filter((i) => i.state === 'running' || i.state === 'pending').length,
)
const pendingOrSkippedCount = computed(() =>
  task.value
    ? Math.max(0, task.value.total_items - task.value.succeeded_items - task.value.failed_items)
    : 0,
)

const itemStatePills = computed(() => [
  { value: 'all' as const, label: `全部 (${allItems.value.length})` },
  {
    value: 'succeeded' as const,
    label: `成功 (${allItems.value.filter((i) => i.state === 'succeeded').length})`,
  },
  {
    value: 'failed' as const,
    label: `失败 (${allItems.value.filter((i) => i.state === 'failed').length})`,
  },
  {
    value: 'pending' as const,
    label: `未完成 (${allItems.value.filter((i) => !['succeeded', 'failed'].includes(i.state)).length})`,
  },
])

const filteredItems = computed(() => {
  const kw = itemSearch.value.trim().toLowerCase()
  return allItems.value.filter((item) => {
    if (itemStateFilter.value === 'succeeded' && item.state !== 'succeeded') return false
    if (itemStateFilter.value === 'failed' && item.state !== 'failed') return false
    if (itemStateFilter.value === 'pending' && ['succeeded', 'failed'].includes(item.state)) return false
    if (!kw) return true
    return item.input_label.toLowerCase().includes(kw)
  })
})

const pagedItems = computed(() =>
  filteredItems.value.slice(itemOffset.value, itemOffset.value + itemPageSize.value),
)

const failedRetryFileIds = computed(() =>
  allItems.value
    .filter((i) => i.state === 'failed' && Boolean(i.input_file_id))
    .map((i) => i.input_file_id as string),
)

const taskSummaryJson = computed(() => (task.value ? JSON.stringify(task.value, null, 2) : '{}'))

const succeededNavList = computed(() => allItems.value.filter((i) => i.state === 'succeeded'))
const failedNavList = computed(() => allItems.value.filter((i) => i.state === 'failed'))
const fullscreenNavPool = computed(() => {
  if (fullscreenNavScope.value === 'succeeded') return succeededNavList.value
  if (fullscreenNavScope.value === 'failed') return failedNavList.value
  return allItems.value
})
const fullscreenNavIndex = computed(() => {
  if (!fullscreenItem.value) return -1
  return fullscreenNavPool.value.findIndex((i) => i.item_id === fullscreenItem.value?.item_id)
})

const fullscreenAllItems = computed(() =>
  normalizeInferenceOverlayItems(taskType.value, fullscreenResultPayload.value),
)
const fullscreenVisibleItems = computed(() =>
  filterOverlayItems(fullscreenAllItems.value, {
    minDisplayScore: fullscreenMinScore.value,
    selectedClasses: fullscreenSelectedClasses.value,
    isolateItemId: fullscreenIsolateItemId.value,
  }),
)
const fullscreenInspectorItems = computed(() =>
  filterOverlayItems(fullscreenAllItems.value, {
    minDisplayScore: fullscreenMinScore.value,
    selectedClasses: fullscreenSelectedClasses.value,
  }),
)
const fullscreenClassPills = computed(() => summarizeOverlayClasses(fullscreenVisibleItems.value))
const fullscreenDeploymentMeta = computed<InspectorDeploymentMeta | null>(() => {
  if (!task.value) return null
  return {
    projectName: task.value.project_id,
    displayName: task.value.deployment_display_name || task.value.deployment_instance_id,
    modelName: deploymentInfo.value?.model_name || task.value.model_version_id || '-',
    runtimeLabel: deploymentEnvText.value,
    deviceLabel: deploymentInfo.value?.device_name || '-',
  }
})

watch(
  () => props.batchTaskId,
  () => {
    void refreshAll()
  },
)

watch(isActive, (active) => {
  syncPolling(active)
})

onMounted(() => {
  void refreshAll()
  window.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
  if (failurePreviewUrl.value) URL.revokeObjectURL(failurePreviewUrl.value)
  if (fullscreenImageUrl.value) URL.revokeObjectURL(fullscreenImageUrl.value)
  window.removeEventListener('keydown', handleKeydown)
})

function syncPolling(active: boolean): void {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
  if (active) {
    pollTimer = window.setInterval(() => {
      void refreshAll(true)
    }, 2500)
  }
}

async function refreshAll(silent = false): Promise<void> {
  if (!props.batchTaskId) return
  if (!silent) loading.value = true
  errorMessage.value = null
  try {
    const [detail, items] = await Promise.all([
      getBatchInferenceTask(props.batchTaskId),
      listBatchInferenceTaskItems(props.batchTaskId, { limit: 200 }),
    ])
    task.value = detail
    allItems.value = items
  } catch (err) {
    if (!silent) errorMessage.value = getErrorMessage(err)
  } finally {
    if (!silent) loading.value = false
  }
}

function selectItemStateFilter(next: 'all' | 'succeeded' | 'failed' | 'pending'): void {
  itemStateFilter.value = next
  itemOffset.value = 0
}

function changeItemPageSize(val: string | number | boolean | null): void {
  const num = Number(val)
  if (!Number.isFinite(num) || num <= 0) return
  itemPageSize.value = num
  itemOffset.value = 0
}

async function openFailureDrawer(item: BatchInferenceTaskItem): Promise<void> {
  activeFailureItem.value = item
  showFailureDiag.value = false
  if (failurePreviewUrl.value) {
    URL.revokeObjectURL(failurePreviewUrl.value)
    failurePreviewUrl.value = null
  }
  if (item.has_input_image) {
    try {
      const blob = await fetchBatchInferenceTaskItemImageBlob(props.batchTaskId, item.item_id, 'input')
      failurePreviewUrl.value = URL.createObjectURL(blob)
    } catch {
      failurePreviewUrl.value = null
    }
  }
}

function closeFailureDrawer(): void {
  activeFailureItem.value = null
  if (failurePreviewUrl.value) {
    URL.revokeObjectURL(failurePreviewUrl.value)
    failurePreviewUrl.value = null
  }
}

async function openFullscreenForItem(item: BatchInferenceTaskItem): Promise<void> {
  const gen = ++fsLoadGen
  fullscreenItem.value = item
  fullscreenLoading.value = true
  fullscreenResultPayload.value = null
  fullscreenSelectedItemId.value = null
  fullscreenIsolateItemId.value = null
  fullscreenMinScore.value = 0
  fullscreenSelectedClasses.value = []
  if (fullscreenImageUrl.value) {
    URL.revokeObjectURL(fullscreenImageUrl.value)
    fullscreenImageUrl.value = null
  }

  try {
    if (item.has_input_image) {
      try {
        const blob = await fetchBatchInferenceTaskItemImageBlob(props.batchTaskId, item.item_id, 'input')
        if (gen !== fsLoadGen) return
        fullscreenImageUrl.value = URL.createObjectURL(blob)
      } catch {
        if (gen === fsLoadGen) fullscreenImageUrl.value = null
      }
    }

    if (item.state === 'succeeded') {
      try {
        const res = await getBatchInferenceTaskItemResult(props.batchTaskId, item.item_id)
        if (gen === fsLoadGen && res.file_status === 'ready') {
          fullscreenResultPayload.value = res.payload as unknown as TaskInferencePayload
        }
      } catch {
        // 失败保留图像展示
      }
    }
  } finally {
    if (gen === fsLoadGen) {
      fullscreenLoading.value = false
    }
  }
}

function closeFullscreen(): void {
  fsLoadGen++
  fullscreenLoading.value = false
  fullscreenItem.value = null
  fullscreenInspectorOpen.value = false
  if (fullscreenImageUrl.value) {
    URL.revokeObjectURL(fullscreenImageUrl.value)
    fullscreenImageUrl.value = null
  }
}

function navigateFullscreen(delta: number): void {
  const nextIdx = fullscreenNavIndex.value + delta
  if (nextIdx < 0 || nextIdx >= fullscreenNavPool.value.length) return
  void openFullscreenForItem(fullscreenNavPool.value[nextIdx])
}

function jumpNextFailed(): void {
  if (failedNavList.value.length === 0) return
  const curId = fullscreenItem.value?.item_id
  const curIdx = failedNavList.value.findIndex((i) => i.item_id === curId)
  const nextItem = failedNavList.value[(curIdx + 1) % failedNavList.value.length]
  void openFullscreenForItem(nextItem)
}

function handleFullscreenSelectItem(id: string): void {
  fullscreenSelectedItemId.value = id
  fullscreenInspectorOpen.value = true
}

function handleKeydown(event: KeyboardEvent): void {
  if (!fullscreenItem.value) return
  if (event.key === 'Escape') {
    closeFullscreen()
  } else if (event.key === 'ArrowLeft') {
    navigateFullscreen(-1)
  } else if (event.key === 'ArrowRight') {
    navigateFullscreen(1)
  }
}

function retryFailed(): void {
  if (!task.value || failedRetryFileIds.value.length === 0) return
  emit('retry-failed-items', {
    deploymentId: task.value.deployment_instance_id,
    fileIds: failedRetryFileIds.value,
  })
}

function retrySingleSample(fileId: string): void {
  if (!task.value) return
  emit('retry-failed-items', {
    deploymentId: task.value.deployment_instance_id,
    fileIds: [fileId],
  })
}

async function confirmCancel(): Promise<void> {
  if (!task.value) return
  actionBusy.value = true
  try {
    task.value = await cancelBatchInferenceTask(task.value.batch_task_id)
    cancelModalOpen.value = false
    await refreshAll(true)
  } catch (err) {
    errorMessage.value = getErrorMessage(err)
  } finally {
    actionBusy.value = false
  }
}

async function confirmDelete(): Promise<void> {
  if (!task.value) return
  actionBusy.value = true
  try {
    await deleteBatchInferenceTask(task.value.batch_task_id)
    deleteModalOpen.value = false
    emit('deleted', task.value.batch_task_id)
  } catch (err) {
    errorMessage.value = getErrorMessage(err)
  } finally {
    actionBusy.value = false
  }
}

async function copyText(text: string): Promise<void> {
  if (!text || typeof navigator === 'undefined' || !navigator.clipboard) return
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // ignore
  }
}

function downloadSummaryJson(): void {
  const blob = new Blob([taskSummaryJson.value], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${task.value?.batch_task_id || 'batch-summary'}.json`
  a.click()
  URL.revokeObjectURL(url)
}

function formatTaskStatus(status: string): string {
  const labels: Record<string, string> = {
    queued: '排队中',
    running: '执行中',
    succeeded: '已完成',
    partial_failed: '部分失败',
    failed: '失败',
    cancelled: '已取消',
  }
  return labels[status] || status
}

function formatItemStatus(status: string): string {
  const labels: Record<string, string> = {
    pending: '未执行',
    running: '执行中',
    succeeded: '成功',
    failed: '失败',
    cancelled: '已取消',
  }
  return labels[status] || status
}

function statusTone(status: string): 'ok' | 'warn' | 'danger' | 'neutral' {
  if (status === 'succeeded' || status === 'running') return 'ok'
  if (status === 'partial_failed' || status === 'queued') return 'warn'
  if (status === 'failed') return 'danger'
  return 'neutral'
}
</script>

<style scoped>
.inf-batch-detail {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-top: 4px;
  min-width: 0;
}

.inf-bd-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.inf-bd-header__left {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.inf-bd-header__sep {
  width: 1px;
  height: 18px;
  background: var(--am-border);
}

.inf-bd-header__left h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: var(--am-text-strong);
}

.inf-bd-header__right {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.inf-bd-state-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  background: var(--am-surface-muted);
}

.inf-bd-state-pill.is-ok {
  background: var(--am-action-soft);
  color: var(--am-action-primary);
}

.inf-bd-state-pill.is-warn {
  background: color-mix(in srgb, #f59e0b 14%, var(--am-surface));
  color: #d97706;
}

.inf-bd-state-pill.is-danger {
  background: color-mix(in srgb, #dc2626 14%, var(--am-surface));
  color: #dc2626;
}

.inf-bd-summary-card,
.inf-bd-main-card {
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  padding: 16px 20px;
  display: grid;
  gap: 14px;
}

.inf-bd-meta-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 12px 0;
}

.inf-bd-meta-item {
  min-width: 0;
  padding-right: 14px;
}

.inf-bd-meta-item + .inf-bd-meta-item {
  padding-left: 14px;
  border-left: 1px solid var(--am-border);
}

.inf-bd-meta-grid small {
  display: block;
  font-size: 12px;
  color: var(--am-text-muted);
}

.inf-bd-meta-grid strong {
  display: block;
  margin-top: 4px;
  font-size: 13px;
  color: var(--am-text-strong);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 1180px) {
  .inf-bd-meta-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .inf-bd-meta-item {
    padding-left: 0 !important;
    border-left: none !important;
  }
}

.inf-bd-progress-row {
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--am-border);
}

.inf-bd-progress-label {
  font-size: 13px;
  color: var(--am-text-muted);
}

.inf-bd-progress-nums {
  font-size: 15px;
  color: var(--am-text-strong);
  font-variant-numeric: tabular-nums;
}

.inf-bd-progress-track {
  height: 10px;
  border-radius: 999px;
  background: var(--am-progress-track);
  overflow: hidden;
}

.inf-bd-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: var(--am-action-primary);
}

.inf-bd-counts-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 13px;
}

.inf-bd-counts-left {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  color: var(--am-text-muted);
}

.inf-bd-counts-left span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.inf-bd-counts-left strong,
.inf-bd-counts-total strong {
  color: var(--am-text-strong);
}

.inf-bd-tabs {
  display: flex;
  gap: 16px;
  border-bottom: 1px solid var(--am-border);
}

.inf-bd-tabs button {
  padding: 8px 4px 10px;
  border: none;
  border-bottom: 3px solid transparent;
  background: transparent;
  color: var(--am-text-muted);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}

.inf-bd-tabs button.is-active {
  color: var(--am-brand-primary);
  border-bottom-color: var(--am-brand-primary);
  font-weight: 600;
}

.inf-bd-items-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
}

.inf-bd-filter-pills {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 8px;
}

.inf-pill-btn {
  height: 30px;
  padding: 0 12px;
  border-radius: 6px;
  border: 1px solid var(--am-border);
  background: var(--am-surface);
  color: var(--am-text);
  font-size: 13px;
  cursor: pointer;
}

.inf-pill-btn.is-active {
  border-color: var(--am-action-primary);
  background: var(--am-action-soft);
  color: var(--am-action-primary);
  font-weight: 600;
}

.inf-bd-search {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  background: var(--am-input);
  color: var(--am-text-muted);
}

.inf-bd-search input {
  border: none;
  background: transparent;
  color: var(--am-text-strong);
  font-size: 13px;
  outline: none;
}

.inf-bd-table-wrap {
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface-raised);
  overflow-x: auto;
}

.inf-bd-table {
  width: 100%;
  border-collapse: collapse;
}

.inf-bd-table th {
  padding: 12px 14px;
  text-align: left;
  font-size: 14px;
  font-weight: 600;
  color: var(--am-text);
  border-bottom: 1px solid var(--am-border);
  background: var(--am-surface);
  white-space: nowrap;
}

.inf-bd-table td {
  padding: 11px 14px;
  font-size: 14px;
  color: var(--am-text);
  border-bottom: 1px solid var(--am-border);
}

.inf-bd-table tbody tr:last-child td {
  border-bottom: 0;
}

.inf-bd-table tbody tr.is-selected {
  background: var(--am-row-selected);
}

.col-fname strong {
  display: block;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.col-err span {
  display: block;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--am-text-muted);
}

.col-actions {
  white-space: nowrap;
}

.inf-bd-empty-td {
  text-align: center;
  padding: 32px 12px !important;
  color: var(--am-text-muted) !important;
}

.inf-bd-items-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px 12px;
  padding: 0 14px;
  border-top: 1px solid var(--am-border);
}

.inf-bd-items-footer__left {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
}

.inf-bd-retain-note {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--am-text-muted);
}

.inf-bd-items-footer__pager {
  flex: 1 1 auto;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.inf-bd-items-footer__pager :deep(.pagination-controls) {
  flex: 1 1 auto;
  min-width: 0;
  border: none;
  padding-inline: 0;
  background: transparent;
}

.inf-bd-info-sections {
  display: grid;
  gap: 14px;
}

.inf-bd-info-box {
  border: 1px solid var(--am-border);
  border-radius: 8px;
  padding: 14px 16px;
  display: grid;
  gap: 10px;
}

.inf-bd-info-box h4 {
  margin: 0;
  font-size: 14px;
  color: var(--am-text-strong);
}

.inf-bd-kv-two {
  margin: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 24px;
}

.inf-bd-kv-two > div {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.inf-bd-kv-two dt {
  color: var(--am-text-muted);
}

.inf-bd-kv-two dd {
  margin: 0;
  color: var(--am-text-strong);
  overflow-wrap: anywhere;
}

.inf-mono-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.inf-mono-row code {
  min-width: 0;
  overflow-wrap: anywhere;
}

.inf-bd-json-wrap {
  display: grid;
  gap: 10px;
}

.inf-bd-json-actions {
  display: flex;
  gap: 8px;
}

.inf-bd-json-pre {
  margin: 0;
  padding: 12px 14px;
  border-radius: 8px;
  border: 1px solid var(--am-border);
  background: var(--am-code-surface);
  color: var(--am-code-text);
  font-size: 12px;
  max-height: 400px;
  overflow: auto;
}

/* 非模态失败样本抽屉：无底层遮罩 */
.inf-failure-drawer {
  position: fixed;
  top: 16px;
  right: 16px;
  bottom: 16px;
  width: 390px;
  max-width: calc(100vw - 24px);
  z-index: 60;
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  box-shadow: var(--am-shadow-floating);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.inf-failure-drawer__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--am-border);
}

.inf-failure-drawer__head h3 {
  margin: 0;
  font-size: 16px;
  color: var(--am-text-strong);
}

.inf-failure-drawer__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 14px 16px;
  display: grid;
  gap: 12px;
}

.inf-failure-drawer__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.inf-failure-drawer__preview {
  height: 170px;
  border-radius: 8px;
  background: var(--am-surface-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.inf-failure-drawer__preview img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.inf-failure-drawer__noprev {
  display: grid;
  justify-items: center;
  gap: 6px;
  text-align: center;
  padding: 12px;
  color: var(--am-text-muted);
  font-size: 12px;
}

.inf-failure-drawer__noprev strong {
  font-size: 14px;
  color: var(--am-text-strong);
}

.inf-failure-kv {
  margin: 0;
  display: grid;
}

.inf-failure-kv > div {
  display: grid;
  grid-template-columns: 80px minmax(0, 1fr);
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid var(--am-border);
  font-size: 13px;
}

.inf-failure-kv dt {
  color: var(--am-text-muted);
}

.inf-failure-kv dd {
  margin: 0;
  color: var(--am-text-strong);
  overflow-wrap: anywhere;
}

.is-danger-text {
  color: #dc2626 !important;
  font-weight: 500;
}

.inf-failure-diag {
  display: grid;
  gap: 6px;
}

.inf-failure-diag__head {
  display: flex;
  justify-content: space-between;
}

.inf-failure-diag__head button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  color: var(--am-text-muted);
  font-size: 12px;
  cursor: pointer;
}

.inf-failure-diag__pre {
  margin: 0;
  padding: 10px;
  border-radius: 6px;
  background: var(--am-code-surface);
  font-size: 11px;
  overflow: auto;
}

.inf-failure-drawer__foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--am-border);
}

.inf-batch-fullscreen {
  position: fixed;
  inset: 0;
  z-index: 90;
  background: var(--am-page);
  display: flex;
  flex-direction: column;
}

.inf-bfs-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: nowrap;
  gap: 12px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--am-border);
  background: var(--am-surface);
}

.inf-bfs-header__left {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  flex: 1 1 auto;
  min-width: 0;
  gap: 10px;
  overflow: hidden;
}

.inf-bfs-header__left > :deep(*) {
  flex-shrink: 0;
  white-space: nowrap;
}

.inf-bfs-header__nav {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  flex: none;
  gap: 8px;
}

.inf-bfs-task {
  flex-shrink: 1 !important;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--am-text-muted);
}

.inf-bfs-file {
  flex-shrink: 1 !important;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
  color: var(--am-text-strong);
}

@media (max-width: 900px) {
  .inf-bfs-header {
    flex-wrap: wrap;
  }

  .inf-bfs-header__left {
    flex-wrap: wrap;
    overflow: visible;
  }

  .inf-bfs-header__nav {
    flex-wrap: wrap;
  }
}

.inf-bfs-meta,
.inf-bfs-pos {
  font-size: 12px;
  color: var(--am-text-muted);
  font-variant-numeric: tabular-nums;
}

.inf-bfs-scope {
  height: 30px;
  padding: 0 8px;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  background: var(--am-input);
  color: var(--am-text-strong);
  font-size: 12px;
}

.inf-bfs-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  border-top: 1px solid var(--am-border);
  background: var(--am-surface);
  font-size: 13px;
}

.inf-bfs-footer__classes,
.inf-bfs-footer__timing {
  display: inline-flex;
  align-items: center;
  gap: 14px;
}

.inf-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.inf-dot.is-ok {
  background: var(--am-action-primary);
}

.inf-dot.is-warn {
  background: #f59e0b;
}

.inf-dot.is-danger {
  background: #dc2626;
}

.inf-dot.is-neutral {
  background: #98a2b3;
}

.inf-dot-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.inf-dot-status.is-brand {
  color: var(--am-action-primary);
  font-weight: 600;
}

.inf-link-action.is-primary {
  border: none;
  background: transparent;
  padding: 0;
  color: var(--am-action-primary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}

.inf-muted {
  color: var(--am-text-muted);
}

.inf-copy-mini {
  border: 1px solid var(--am-border);
  border-radius: 4px;
  background: var(--am-surface);
  color: var(--am-text-muted);
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.inf-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 95;
  background: var(--am-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
}

.inf-confirm-modal {
  width: min(420px, 92vw);
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  box-shadow: var(--am-shadow-modal);
  overflow: hidden;
}

.inf-confirm-modal__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-bottom: 1px solid var(--am-border);
}

.inf-confirm-modal__head h3 {
  margin: 0;
  font-size: 16px;
}

.inf-modal-x {
  border: none;
  background: transparent;
  color: var(--am-text-muted);
  cursor: pointer;
}

.inf-confirm-modal__body {
  padding: 16px 18px;
  font-size: 13px;
}

.inf-muted-sm {
  font-size: 12px;
  color: var(--am-text-muted);
}

.inf-confirm-modal__foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 18px;
  border-top: 1px solid var(--am-border);
}

.inf-btn-warn {
  background: #f59e0b !important;
  border-color: #f59e0b !important;
  color: #ffffff !important;
}
</style>
