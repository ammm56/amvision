<template>
  <aside
    v-if="open"
    class="inf-inspector"
    role="complementary"
    aria-label="推理结果详情"
    data-inspector-panel
    @pointerdown.stop
    @pointerup.stop
    @wheel.stop
  >
    <header class="inf-inspector__head">
      <div class="inf-inspector__title-row">
        <div>
          <h3>结果详情</h3>
          <p v-if="inputLabel && payload" class="inf-inspector__subtitle">
            {{ inputLabel }} · {{ payload.image_width }} × {{ payload.image_height }}
          </p>
        </div>
        <button
          type="button"
          class="inf-inspector__close"
          aria-label="收起详情面板"
          title="收起详情面板"
          @click="emit('close')"
        >
          <X :size="16" />
        </button>
      </div>

      <div class="inf-inspector__tabs" role="tablist">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          type="button"
          role="tab"
          class="inf-inspector__tab"
          :class="{ 'is-active': activeTab === tab.id }"
          :aria-selected="activeTab === tab.id"
          @click="activeTab = tab.id"
        >
          {{ tab.label }}
        </button>
      </div>
    </header>

    <div class="inf-inspector__body">
      <template v-if="activeTab === 'overview'">
        <div class="inf-overview-status">
          <CheckCircle2 :size="16" class="inf-overview-status__icon" />
          <strong>推理成功</strong>
        </div>

        <dl class="inf-kv-list">
          <div v-if="overviewSummaryText">
            <dt>目标统计</dt>
            <dd>{{ overviewSummaryText }}</dd>
          </div>
          <div>
            <dt>文件</dt>
            <dd>
              <span>{{ inputLabel || '-' }}</span>
              <small v-if="payload">{{ payload.image_width }} × {{ payload.image_height }}</small>
            </dd>
          </div>
          <div>
            <dt>部署</dt>
            <dd>{{ deploymentMeta?.displayName || payload?.deployment_instance_id || '-' }}</dd>
          </div>
          <div>
            <dt>模型</dt>
            <dd>{{ deploymentMeta?.modelName || payload?.model_version_id || '-' }}</dd>
          </div>
          <div>
            <dt>后端</dt>
            <dd>{{ deploymentMeta?.runtimeLabel || '-' }}</dd>
          </div>
          <div>
            <dt>设备</dt>
            <dd>{{ deploymentMeta?.deviceLabel || '-' }}</dd>
          </div>
          <div>
            <dt>请求耗时</dt>
            <dd>{{ formatMs(requestDurationMs) }}</dd>
          </div>
          <div>
            <dt>服务端耗时</dt>
            <dd>{{ formatMs(payload?.latency_ms) }}</dd>
          </div>
          <div>
            <dt>推理时间</dt>
            <dd>{{ completedAtText }}</dd>
          </div>
          <div>
            <dt>请求 ID</dt>
            <dd class="inf-mono-copy">
              <span>{{ payload?.request_id || requestId || '-' }}</span>
              <button
                v-if="payload?.request_id || requestId"
                type="button"
                class="inf-copy-mini"
                title="复制 request_id"
                @click="copyText(String(payload?.request_id || requestId))"
              >
                <Copy :size="12" />
              </button>
            </dd>
          </div>
          <div>
            <dt>保存状态</dt>
            <dd class="inf-save-status-dd">
              <span v-if="savedRecord" class="inf-saved-badge-row">
                <span class="inf-text-brand">已保存</span>
                <code class="inf-saved-record-id" :title="savedRecord.record_id">{{ savedRecord.record_id }}</code>
              </span>
              <template v-else>
                <span>未保存</span>
                <Button size="sm" variant="secondary" :loading="savingRecord" @click="emit('save-record')">
                  保存结果
                </Button>
              </template>
            </dd>
          </div>
        </dl>
      </template>

      <template v-else-if="activeTab === 'items'">
        <div v-if="taskType !== 'classification' && allItems.length > 0" class="inf-filter-card">
          <h4>显示筛选</h4>
          <div class="inf-filter-row">
            <span>类别</span>
            <select
              :value="selectedClasses[0] || ''"
              class="inf-filter-select"
              aria-label="筛选类别"
              @change="handleClassFilterChange"
            >
              <option value="">全部类别</option>
              <option v-for="cls in availableClasses" :key="cls" :value="cls">
                {{ cls }}
              </option>
            </select>
          </div>
          <div class="inf-filter-row">
            <span>分数 ≥</span>
            <div class="inf-filter-score">
              <input
                type="number"
                class="inf-filter-number"
                min="0"
                max="1"
                step="0.05"
                :value="minDisplayScore"
                aria-label="最小显示分数"
                @input="handleScoreFilterChange"
              />
              <small>仅影响显示</small>
            </div>
          </div>
        </div>

        <template v-if="taskType === 'classification'">
          <div class="inf-kv-list inf-kv-list--compact">
            <div>
              <dt>任务类型</dt>
              <dd>图像分类</dd>
            </div>
            <div v-if="items[0]">
              <dt>首选结果</dt>
              <dd class="inf-dot-value">
                <span class="inf-dot" :style="{ backgroundColor: items[0].color }" />
                <strong>{{ items[0].className }} · {{ items[0].score.toFixed(3) }}</strong>
              </dd>
            </div>
          </div>

          <div v-if="items.length === 0" class="inf-inspector__empty">暂无分类预测结果</div>
          <table v-else class="inf-subtable inf-subtable--cls">
            <thead>
              <tr>
                <th>#</th>
                <th>类别</th>
                <th>分数</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in items"
                :key="item.id"
                :class="{ 'is-selected': selectedItem?.id === item.id }"
                @click="emit('select-item', item.id)"
              >
                <td>{{ item.index }}</td>
                <td>
                  <span class="inf-dot-value">
                    <span class="inf-dot" :style="{ backgroundColor: item.color }" />
                    <span>{{ item.className }}</span>
                  </span>
                </td>
                <td>
                  <div class="inf-score-bar-cell">
                    <span>{{ item.score.toFixed(3) }}</span>
                    <div class="inf-mini-bar">
                      <div
                        class="inf-mini-bar__fill"
                        :style="{
                          width: `${Math.round(Math.min(1, Math.max(0, item.score)) * 100)}%`,
                          backgroundColor: item.color,
                        }"
                      />
                    </div>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="payload" class="inf-inspector__note">
            返回类别 {{ items.length }} · 模型类别 {{ payload.labels?.length || items.length }}
          </p>
        </template>

        <template v-else-if="taskType === 'pose'">
          <div v-if="items.length === 0" class="inf-inspector__empty">当前过滤条件下暂无关键点目标</div>
          <template v-else>
            <div class="inf-filter-row inf-pose-target-bar">
              <span>目标</span>
              <select
                :value="selectedPoseItem?.id || ''"
                class="inf-filter-select"
                @change="emit('select-item', ($event.target as HTMLSelectElement).value)"
              >
                <option v-for="item in items" :key="item.id" :value="item.id">
                  对象 {{ item.index }} · {{ item.className }}
                </option>
              </select>
              <small>检出 {{ detectedPoseKeypointsCount }} / {{ selectedPoseKeypoints.length }}</small>
            </div>

            <table class="inf-subtable">
              <thead>
                <tr>
                  <th>#</th>
                  <th>关键点</th>
                  <th>分数</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(kp, idx) in selectedPoseKeypoints"
                  :key="`pose-kp-${idx}`"
                  :class="{ 'is-selected': selectedKeypointIdx === idx }"
                  @click="selectedKeypointIdx = idx"
                >
                  <td>{{ idx + 1 }}</td>
                  <td>P{{ idx + 1 }}</td>
                  <td>{{ isKeypointDetected(kp) ? (kp.confidence ?? 1).toFixed(2) : '—' }}</td>
                  <td>
                    <span class="inf-dot-value">
                      <span
                        class="inf-dot"
                        :style="{ backgroundColor: isKeypointDetected(kp) ? '#00d992' : '#dc2626' }"
                      />
                      <span>{{ isKeypointDetected(kp) ? '已检出' : '未检出' }}</span>
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>

            <div v-if="selectedKeypoint" class="inf-detail-card">
              <h4>选中点 {{ selectedKeypointIdx + 1 }}</h4>
              <div class="inf-coord-pair">
                <div class="inf-coord-chip">
                  <span>X</span>
                  <strong>{{ Math.round(selectedKeypoint.x) }}</strong>
                </div>
                <div class="inf-coord-chip">
                  <span>Y</span>
                  <strong>{{ Math.round(selectedKeypoint.y) }}</strong>
                </div>
              </div>
            </div>

            <div class="inf-toggle-pair">
              <label class="inf-switch-inline">
                <button
                  type="button"
                  role="switch"
                  class="inf-switch"
                  :class="{ 'is-on': layers.keypoints }"
                  :aria-checked="layers.keypoints"
                  @click="emit('update:layers', { ...layers, keypoints: !layers.keypoints })"
                >
                  <span class="inf-switch__thumb" />
                </button>
                <span>显示关键点</span>
              </label>
              <label class="inf-switch-inline">
                <button
                  type="button"
                  role="switch"
                  class="inf-switch"
                  :class="{ 'is-on': layers.skeleton }"
                  :aria-checked="layers.skeleton"
                  @click="emit('update:layers', { ...layers, skeleton: !layers.skeleton })"
                >
                  <span class="inf-switch__thumb" />
                </button>
                <span>显示连线</span>
              </label>
            </div>
          </template>
        </template>

        <template v-else>
          <div class="inf-section-head">
            <h4>{{ taskType === 'segmentation' ? `实例列表 (${items.length})` : `对象列表 (${items.length})` }}</h4>
            <span>显示 {{ items.length }} / {{ allItems.length }}</span>
          </div>

          <div v-if="items.length === 0" class="inf-inspector__empty">当前过滤条件下暂无匹配结果</div>

          <template v-else>
            <table class="inf-subtable">
              <thead>
                <tr>
                  <th>#</th>
                  <th>类别</th>
                  <th>分数</th>
                  <th v-if="taskType === 'segmentation'">面积 (px²)</th>
                  <th v-else-if="taskType === 'obb'">角度</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="item in items"
                  :key="item.id"
                  :class="{ 'is-selected': selectedItem?.id === item.id }"
                  @click="emit('select-item', item.id)"
                >
                  <td>{{ item.index }}</td>
                  <td>
                    <span class="inf-dot-value">
                      <span class="inf-dot" :style="{ backgroundColor: item.color }" />
                      <span>{{ item.className }}</span>
                    </span>
                  </td>
                  <td>{{ item.score.toFixed(2) }}</td>
                  <td v-if="taskType === 'segmentation'">
                    {{ item.maskArea !== null ? Math.round(item.maskArea) : '—' }}
                  </td>
                  <td v-else-if="taskType === 'obb'">
                    {{ formatObbAngle(item) }}
                  </td>
                </tr>
              </tbody>
            </table>

            <div v-if="selectedItem" class="inf-detail-card">
              <template v-if="taskType === 'segmentation'">
                <h4>选中实例 {{ selectedItem.index }} · {{ selectedItem.className }}</h4>
                <div class="inf-stat-two">
                  <div>
                    <small>掩膜尺寸</small>
                    <strong>{{ payload?.image_width }} × {{ payload?.image_height }}</strong>
                  </div>
                  <div>
                    <small>像素面积</small>
                    <strong>{{ selectedItem.maskArea !== null ? `${Math.round(selectedItem.maskArea)} px²` : '—' }}</strong>
                  </div>
                  <div>
                    <small>图像占比</small>
                    <strong>{{ formatMaskPercent(selectedItem.maskArea) }}</strong>
                  </div>
                </div>
                <div class="inf-seg-options">
                  <label class="inf-switch-inline">
                    <button
                      type="button"
                      role="switch"
                      class="inf-switch"
                      :class="{ 'is-on': isolateItemId === selectedItem.id }"
                      @click="emit('update:isolateItemId', isolateItemId === selectedItem.id ? null : selectedItem.id)"
                    >
                      <span class="inf-switch__thumb" />
                    </button>
                    <span>只显示此实例</span>
                  </label>
                  <label class="inf-switch-inline">
                    <button
                      type="button"
                      role="switch"
                      class="inf-switch"
                      :class="{ 'is-on': showContours }"
                      @click="emit('update:showContours', !showContours)"
                    >
                      <span class="inf-switch__thumb" />
                    </button>
                    <span>显示轮廓</span>
                  </label>
                </div>
              </template>

              <template v-else-if="taskType === 'obb' && selectedItem.obbXywhr">
                <h4>旋转框参数 (对象 {{ selectedItem.index }})</h4>
                <dl class="inf-kv-list inf-kv-list--compact">
                  <div>
                    <dt>中心 X</dt>
                    <dd>{{ Math.round(selectedItem.obbXywhr[0]) }} px</dd>
                  </div>
                  <div>
                    <dt>中心 Y</dt>
                    <dd>{{ Math.round(selectedItem.obbXywhr[1]) }} px</dd>
                  </div>
                  <div>
                    <dt>长边</dt>
                    <dd>{{ Math.round(Math.max(selectedItem.obbXywhr[2], selectedItem.obbXywhr[3])) }} px</dd>
                  </div>
                  <div>
                    <dt>短边</dt>
                    <dd>{{ Math.round(Math.min(selectedItem.obbXywhr[2], selectedItem.obbXywhr[3])) }} px</dd>
                  </div>
                  <div>
                    <dt>角度</dt>
                    <dd>{{ formatObbAngle(selectedItem) }}</dd>
                  </div>
                </dl>
                <p class="inf-inspector__note">图像坐标，顺时针为正。</p>
              </template>

              <template v-else-if="selectedItem.bboxXyxy">
                <h4>选中对象</h4>
                <dl class="inf-kv-list inf-kv-list--compact">
                  <div>
                    <dt>编号 / 类别</dt>
                    <dd class="inf-dot-value">
                      <span class="inf-dot" :style="{ backgroundColor: selectedItem.color }" />
                      <strong>{{ selectedItem.index }} · {{ selectedItem.className }}</strong>
                    </dd>
                  </div>
                  <div>
                    <dt>置信度</dt>
                    <dd>{{ selectedItem.score.toFixed(2) }}</dd>
                  </div>
                </dl>
                <div class="inf-coord-grid">
                  <div class="inf-coord-chip">
                    <span>X</span>
                    <strong>{{ selectedXywh?.x ?? '-' }}</strong>
                  </div>
                  <div class="inf-coord-chip">
                    <span>Y</span>
                    <strong>{{ selectedXywh?.y ?? '-' }}</strong>
                  </div>
                  <div class="inf-coord-chip">
                    <span>宽</span>
                    <strong>{{ selectedXywh?.w ?? '-' }}</strong>
                  </div>
                  <div class="inf-coord-chip">
                    <span>高</span>
                    <strong>{{ selectedXywh?.h ?? '-' }}</strong>
                  </div>
                </div>
                <div class="inf-xyxy-line">
                  <span>边界框 (xyxy, px)</span>
                  <code>{{ selectedItem.bboxXyxy.map((n) => Math.round(n)).join(', ') }}</code>
                </div>
              </template>
            </div>
          </template>
        </template>
      </template>

      <template v-else-if="activeTab === 'timing'">
        <div class="inf-timing-summary-cards">
          <div class="inf-timing-card">
            <small>请求总耗时</small>
            <strong>{{ formatMs(requestDurationMs) }}</strong>
          </div>
          <div class="inf-timing-card">
            <small>服务端</small>
            <strong>{{ formatMs(payload?.latency_ms) }}</strong>
          </div>
        </div>

        <h4 class="inf-timing-heading">阶段耗时（服务端）</h4>
        <div class="inf-timing-bars">
          <div v-for="row in serverPhaseRows" :key="row.label" class="inf-timing-bar-row">
            <span class="inf-timing-bar-row__label">{{ row.label }}</span>
            <div class="inf-timing-bar-row__track">
              <div
                v-if="row.value !== null"
                class="inf-timing-bar-row__fill"
                :style="{ width: `${row.percent}%` }"
              />
            </div>
            <span class="inf-timing-bar-row__val">{{ formatMs(row.value) }}</span>
          </div>
          <div class="inf-timing-bar-row inf-timing-bar-row--total">
            <span class="inf-timing-bar-row__label"><strong>合计</strong></span>
            <div class="inf-timing-bar-row__track">
              <div
                v-if="serverPhaseSum !== null"
                class="inf-timing-bar-row__fill"
                style="width: 100%"
              />
            </div>
            <span class="inf-timing-bar-row__val"><strong>{{ formatMs(serverPhaseSum) }}</strong></span>
          </div>
        </div>
        <p class="inf-inspector__note">请求总耗时含传输与客户端处理；未上报阶段显示 —。</p>

        <h4 class="inf-timing-heading">来源</h4>
        <dl class="inf-kv-list inf-kv-list--compact">
          <div>
            <dt>项目</dt>
            <dd>{{ deploymentMeta?.projectName || '-' }}</dd>
          </div>
          <div>
            <dt>部署</dt>
            <dd>{{ deploymentMeta?.displayName || '-' }}</dd>
          </div>
          <div>
            <dt>模型</dt>
            <dd>{{ deploymentMeta?.modelName || '-' }}</dd>
          </div>
          <div>
            <dt>推理引擎</dt>
            <dd>{{ deploymentMeta?.runtimeLabel || '-' }}</dd>
          </div>
          <div>
            <dt>运行设备</dt>
            <dd>{{ deploymentMeta?.deviceLabel || '-' }}</dd>
          </div>
        </dl>
      </template>

      <template v-else>
        <div v-if="isJsonTruncated" class="inf-json-truncation-bar">
          <span>{{ formatJsonSize(fullJsonByteSize) }} · 仅预览前 {{ MAX_JSON_PREVIEW_LINES }} 行（共 {{ allJsonLines.length }} 行）</span>
        </div>

        <div class="inf-json-toolbar">
          <div class="inf-json-toolbar__btns">
            <Button size="sm" variant="secondary" @click="copyText(previewJsonText)">
              <Copy :size="13" />
              {{ copiedToast ? '已复制' : isJsonTruncated ? '复制当前片段' : '复制 JSON' }}
            </Button>
            <Button size="sm" variant="secondary" @click="downloadJson">
              <Download :size="13" />
              {{ isJsonTruncated ? '下载完整 JSON' : '下载 JSON' }}
            </Button>
          </div>
          <label class="inf-switch-inline">
            <span>换行</span>
            <button
              type="button"
              role="switch"
              class="inf-switch"
              :class="{ 'is-on': wrapJson }"
              :aria-checked="wrapJson"
              @click="wrapJson = !wrapJson"
            >
              <span class="inf-switch__thumb" />
            </button>
          </label>
        </div>

        <div class="inf-json-box" :class="{ 'is-wrap': wrapJson }">
          <div class="inf-json-box__gutter" aria-hidden="true">
            <span v-for="n in previewJsonLines.length" :key="n">{{ n }}</span>
          </div>
          <pre class="inf-json-box__code">{{ previewJsonText }}</pre>
        </div>

        <div v-if="isJsonTruncated" class="inf-json-more">
          更多内容已省略，请点击“下载完整 JSON”查看全部内容。
        </div>
      </template>
    </div>

    <footer class="inf-inspector__footer">
      <div v-if="activeTab === 'overview'" class="inf-download-menu-wrap">
        <div v-if="downloadMenuOpen" class="inf-download-menu">
          <button type="button" @click="triggerDownload('json')">
            <FileCode :size="14" />
            结果 JSON
          </button>
          <button type="button" :disabled="!imageSrc" @click="triggerDownload('original')">
            <ImageIcon :size="14" />
            原图
          </button>
          <button type="button" :disabled="!imageSrc || !payload" @click="triggerDownload('annotated')">
            <ImageIcon :size="14" />
            带标注预览图
          </button>
        </div>
        <Button size="sm" variant="secondary" @click="downloadMenuOpen = !downloadMenuOpen">
          <Download :size="13" />
          下载结果
          <ChevronUp :size="13" />
        </Button>
      </div>
      <div v-else />
      <Button size="sm" variant="secondary" @click="emit('close')">关闭</Button>
    </footer>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CheckCircle2, ChevronUp, Copy, Download, FileCode, Image as ImageIcon, X } from '@lucide/vue'

import type { ModelTaskType } from '@/modules/deployments/services/deployment.service'
import Button from '@/shared/ui/components/Button.vue'
import type {
  DirectInferenceRecordSummary,
  PoseInferenceKeypoint,
  TaskInferencePayload,
} from '../services/inference.service'
import {
  formatObbAngleDeg,
  formatXywh,
  renderAnnotatedPreviewBlob,
  summarizeOverlayClasses,
  type InferenceLayerVisibility,
  type OverlayRenderItem,
} from './inference-overlay.utils'

export interface InspectorDeploymentMeta {
  projectName: string
  displayName: string
  modelName: string
  runtimeLabel: string
  deviceLabel: string
}

const props = defineProps<{
  open: boolean
  taskType: ModelTaskType
  allItems: OverlayRenderItem[]
  items: OverlayRenderItem[]
  selectedItemId?: string | null
  payload: TaskInferencePayload | null
  imageSrc?: string | null
  inputLabel?: string
  requestId?: string | null
  requestDurationMs?: number | null
  completedAtText?: string
  deploymentMeta?: InspectorDeploymentMeta | null
  savedRecord?: DirectInferenceRecordSummary | null
  savingRecord?: boolean
  layers: InferenceLayerVisibility
  minDisplayScore: number
  selectedClasses: string[]
  isolateItemId?: string | null
  showContours?: boolean
  maskOpacity?: number
}>()

const emit = defineEmits<{
  close: []
  'select-item': [id: string]
  'save-record': []
  'update:layers': [layers: InferenceLayerVisibility]
  'update:minDisplayScore': [score: number]
  'update:selectedClasses': [classes: string[]]
  'update:isolateItemId': [id: string | null]
  'update:showContours': [value: boolean]
}>()

const activeTab = ref<'overview' | 'items' | 'timing' | 'json'>('overview')
const wrapJson = ref(true)
const downloadMenuOpen = ref(false)
const copiedToast = ref(false)
const selectedKeypointIdx = ref(0)

const secondTabLabel = computed(() => {
  if (props.taskType === 'classification') return '类别'
  if (props.taskType === 'segmentation') return '实例'
  if (props.taskType === 'pose') return '关键点'
  return '对象'
})

const tabs = computed(() => [
  { id: 'overview' as const, label: '概览' },
  { id: 'items' as const, label: secondTabLabel.value },
  { id: 'timing' as const, label: '耗时' },
  { id: 'json' as const, label: 'JSON' },
])

watch(
  () => props.selectedItemId,
  () => {
    selectedKeypointIdx.value = 0
  },
)

const availableClasses = computed(() =>
  summarizeOverlayClasses(props.allItems).map((entry) => entry.className),
)

const overviewSummaryText = computed(() => {
  if (!props.payload) return ''
  if (props.taskType === 'classification') {
    return props.allItems.length > 0 ? `Top-${props.allItems.length}` : '无类别输出'
  }
  if (props.allItems.length === 0) return '目标 0 | 未检出目标'
  const prefix = props.taskType === 'segmentation' ? `实例 ${props.allItems.length}` : `目标 ${props.allItems.length}`
  const breakdown = summarizeOverlayClasses(props.allItems)
    .slice(0, 4)
    .map((entry) => `${entry.className} ${entry.count}`)
  return [prefix, ...breakdown].join(' | ')
})

const selectedItem = computed(() => {
  if (props.items.length === 0) return null
  return props.items.find((it) => it.id === props.selectedItemId) ?? props.items[0]
})

const selectedXywh = computed(() =>
  selectedItem.value?.bboxXyxy ? formatXywh(selectedItem.value.bboxXyxy) : null,
)

const selectedPoseItem = computed(() => selectedItem.value)
const selectedPoseKeypoints = computed<PoseInferenceKeypoint[]>(
  () => selectedPoseItem.value?.keypoints ?? [],
)
const detectedPoseKeypointsCount = computed(
  () => selectedPoseKeypoints.value.filter((kp) => isKeypointDetected(kp)).length,
)
const selectedKeypoint = computed(
  () => selectedPoseKeypoints.value[selectedKeypointIdx.value] ?? null,
)

function isKeypointDetected(kp: PoseInferenceKeypoint): boolean {
  const th = selectedPoseItem.value?.keypointThreshold ?? 0.3
  return (kp.confidence ?? 1) >= th && (kp.x !== 0 || kp.y !== 0)
}

const serverPhaseRows = computed(() => {
  const p = props.payload
  const raw = [
    { label: '图像解码', value: toFiniteOrNull(p?.decode_ms) },
    { label: '预处理', value: toFiniteOrNull(p?.preprocess_ms) },
    { label: '模型推理', value: toFiniteOrNull(p?.infer_ms) },
    { label: '后处理', value: toFiniteOrNull(p?.postprocess_ms) },
    { label: '结果序列化', value: toFiniteOrNull(p?.serialize_ms) },
  ]
  const maxVal = Math.max(
    1,
    toFiniteOrNull(p?.latency_ms) ?? 0,
    ...raw.map((r) => r.value ?? 0),
  )
  return raw.map((r) => ({
    ...r,
    percent: r.value !== null ? Math.min(100, Math.max(6, Math.round((r.value / maxVal) * 100))) : 0,
  }))
})

const serverPhaseSum = computed(() => {
  const values = serverPhaseRows.value.map((r) => r.value).filter((v): v is number => v !== null)
  if (values.length === 0) return null
  return values.reduce((acc, v) => acc + v, 0)
})

const MAX_JSON_PREVIEW_LINES = 2000

const fullJsonText = computed(() => (props.payload ? JSON.stringify(props.payload, null, 2) : '{}'))
const fullJsonByteSize = computed(() => {
  if (typeof TextEncoder !== 'undefined') {
    return new TextEncoder().encode(fullJsonText.value).length
  }
  return fullJsonText.value.length
})
const allJsonLines = computed(() => fullJsonText.value.split('\n'))
const isJsonTruncated = computed(() => allJsonLines.value.length > MAX_JSON_PREVIEW_LINES)
const previewJsonLines = computed(() =>
  isJsonTruncated.value ? allJsonLines.value.slice(0, MAX_JSON_PREVIEW_LINES) : allJsonLines.value,
)
const previewJsonText = computed(() => previewJsonLines.value.join('\n'))

function formatJsonSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

function toFiniteOrNull(val: unknown): number | null {
  return typeof val === 'number' && Number.isFinite(val) ? val : null
}

function formatMs(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)} ms` : '—'
}

function formatObbAngle(item: OverlayRenderItem): string {
  const deg = formatObbAngleDeg(item)
  return deg !== null ? `${deg.toFixed(1)}°` : '—'
}

function formatMaskPercent(area: number | null): string {
  if (area === null || !props.payload?.image_width || !props.payload?.image_height) return '—'
  const total = props.payload.image_width * props.payload.image_height
  if (total <= 0) return '—'
  return `${((area / total) * 100).toFixed(3)}%`
}

function handleClassFilterChange(event: Event): void {
  const val = (event.target as HTMLSelectElement).value
  emit('update:selectedClasses', val ? [val] : [])
}

function handleScoreFilterChange(event: Event): void {
  const num = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(num) || num < 0 || num > 1) return
  emit('update:minDisplayScore', num)
}

async function copyText(text: string): Promise<void> {
  if (!text || typeof navigator === 'undefined' || !navigator.clipboard) return
  try {
    await navigator.clipboard.writeText(text)
    copiedToast.value = true
    window.setTimeout(() => {
      copiedToast.value = false
    }, 1400)
  } catch {
    // 忽略剪贴板权限拒绝
  }
}

function saveBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function downloadJson(): void {
  saveBlobDownload(
    new Blob([fullJsonText.value], { type: 'application/json;charset=utf-8' }),
    `${props.payload?.request_id || 'inference-result'}.json`,
  )
}

async function triggerDownload(kind: 'json' | 'original' | 'annotated'): Promise<void> {
  downloadMenuOpen.value = false
  if (kind === 'json') {
    downloadJson()
    return
  }
  if (!props.imageSrc) return
  const baseName = (props.inputLabel || 'inference-image').replace(/\.[^.]+$/, '')
  if (kind === 'original') {
    const resp = await fetch(props.imageSrc)
    const blob = await resp.blob()
    saveBlobDownload(blob, props.inputLabel || `${baseName}.png`)
    return
  }
  if (props.payload) {
    const blob = await renderAnnotatedPreviewBlob({
      imageSrc: props.imageSrc,
      taskType: props.taskType,
      items: props.items,
      maskOpacity: props.maskOpacity,
    })
    saveBlobDownload(blob, `${baseName}-annotated.png`)
  }
}
</script>

<style scoped>
.inf-inspector {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 372px;
  max-width: calc(100% - 12px);
  z-index: 30;
  display: flex;
  flex-direction: column;
  background: var(--am-surface);
  border-left: 1px solid var(--am-border);
  box-shadow: var(--am-shadow-floating);
  overflow: hidden;
  pointer-events: auto;
  cursor: default;
  user-select: text;
}

.inf-inspector__head {
  padding: 14px 16px 0;
  border-bottom: 1px solid var(--am-border);
  background: var(--am-surface);
}

.inf-inspector__title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.inf-inspector__title-row h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--am-text-strong);
}

.inf-inspector__subtitle {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--am-text-muted);
}

.inf-inspector__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--am-text-muted);
  cursor: pointer;
}

.inf-inspector__close:hover {
  background: var(--am-hover-surface);
  color: var(--am-text-strong);
}

.inf-inspector__tabs {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 4px;
}

.inf-inspector__tab {
  height: 36px;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--am-text-muted);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}

.inf-inspector__tab.is-active {
  color: var(--am-action-primary);
  border-bottom-color: var(--am-action-primary);
  font-weight: 600;
}

.inf-inspector__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.inf-overview-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--am-text-strong);
}

.inf-overview-status__icon {
  color: var(--am-action-primary);
}

.inf-kv-list {
  margin: 0;
  display: grid;
  gap: 2px;
}

.inf-kv-list > div {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: 10px;
  padding: 6px 0;
  font-size: 13px;
}

.inf-kv-list--compact > div {
  padding: 4px 0;
}

.inf-kv-list dt {
  color: var(--am-text-muted);
}

.inf-kv-list dd {
  margin: 0;
  color: var(--am-text-strong);
  display: grid;
  gap: 2px;
  overflow-wrap: anywhere;
}

.inf-kv-list dd small {
  color: var(--am-text-muted);
  font-size: 12px;
}

.inf-mono-copy {
  display: flex !important;
  align-items: center;
  gap: 6px;
  font-family: var(--am-font-mono);
  font-size: 12px;
}

.inf-copy-mini {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: 1px solid var(--am-border);
  border-radius: 4px;
  background: var(--am-surface);
  color: var(--am-text-muted);
  cursor: pointer;
  flex: none;
}

.inf-save-status-dd {
  display: flex !important;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.inf-text-brand {
  color: var(--am-action-primary);
  font-weight: 600;
  white-space: nowrap;
}

.inf-saved-badge-row {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.inf-saved-record-id {
  max-width: 170px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--am-surface-soft);
  border: 1px solid var(--am-border);
  font-family: var(--am-font-mono);
  font-size: 11px;
  color: var(--am-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.inf-filter-card {
  display: grid;
  gap: 8px;
}

.inf-filter-card h4,
.inf-section-head h4,
.inf-detail-card h4,
.inf-timing-heading {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  color: var(--am-text-strong);
}

.inf-filter-row {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--am-text-muted);
}

.inf-filter-select,
.inf-filter-number {
  height: 32px;
  padding: 0 8px;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  background: var(--am-input);
  color: var(--am-text-strong);
  font-size: 13px;
  width: 100%;
}

.inf-filter-score {
  display: grid;
  gap: 3px;
}

.inf-filter-score small {
  font-size: 11px;
  color: var(--am-text-muted);
}

.inf-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.inf-section-head span {
  font-size: 12px;
  color: var(--am-text-muted);
}

.inf-subtable {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.inf-subtable th {
  text-align: left;
  padding: 7px 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text-muted);
  border-bottom: 1px solid var(--am-border);
}

.inf-subtable td {
  padding: 7px 8px;
  border-bottom: 1px solid var(--am-border);
  color: var(--am-text-strong);
  font-variant-numeric: tabular-nums;
  cursor: pointer;
}

.inf-subtable tbody tr:last-child td {
  border-bottom: none;
}

.inf-subtable tbody tr:hover {
  background: var(--am-row-hover);
}

.inf-subtable tbody tr.is-selected {
  background: var(--am-row-selected);
}

.inf-dot-value {
  display: inline-flex !important;
  align-items: center;
  gap: 6px;
}

.inf-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}

.inf-score-bar-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.inf-mini-bar {
  flex: 1 1 auto;
  height: 6px;
  border-radius: 999px;
  background: var(--am-surface-muted);
  overflow: hidden;
}

.inf-mini-bar__fill {
  height: 100%;
  border-radius: 999px;
}

.inf-detail-card {
  display: grid;
  gap: 10px;
  padding-top: 4px;
}

.inf-coord-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.inf-coord-pair {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.inf-coord-chip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  background: var(--am-input);
  font-size: 13px;
}

.inf-coord-chip span {
  color: var(--am-text-muted);
}

.inf-xyxy-line {
  display: grid;
  gap: 4px;
  font-size: 12px;
  color: var(--am-text-muted);
}

.inf-xyxy-line code {
  padding: 6px 8px;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  background: var(--am-input);
  color: var(--am-text-strong);
  font-family: var(--am-font-mono);
}

.inf-stat-two {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.inf-stat-two small {
  display: block;
  font-size: 12px;
  color: var(--am-text-muted);
}

.inf-stat-two strong {
  font-size: 14px;
  color: var(--am-text-strong);
}

.inf-seg-options,
.inf-toggle-pair {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.inf-switch-inline {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--am-text-strong);
}

.inf-switch {
  position: relative;
  width: 34px;
  height: 20px;
  border-radius: 999px;
  border: none;
  padding: 2px;
  background: var(--am-border-strong);
  cursor: pointer;
}

.inf-switch.is-on {
  background: var(--am-action-primary);
}

.inf-switch__thumb {
  display: block;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #ffffff;
  transition: transform 140ms ease;
}

.inf-switch.is-on .inf-switch__thumb {
  transform: translateX(14px);
}

.inf-timing-summary-cards {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.inf-timing-card {
  padding: 10px 12px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface-soft);
}

.inf-timing-card small {
  display: block;
  font-size: 12px;
  color: var(--am-text-muted);
}

.inf-timing-card strong {
  display: block;
  margin-top: 4px;
  font-size: 18px;
  color: var(--am-text-strong);
  font-variant-numeric: tabular-nums;
}

.inf-timing-bars {
  display: grid;
  gap: 8px;
}

.inf-timing-bar-row {
  display: grid;
  grid-template-columns: 74px minmax(0, 1fr) 64px;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.inf-timing-bar-row--total {
  padding-top: 4px;
  font-weight: 600;
}

.inf-timing-bar-row__label {
  color: var(--am-text);
}

.inf-timing-bar-row__track {
  height: 7px;
  border-radius: 999px;
  background: var(--am-progress-track);
  overflow: hidden;
}

.inf-timing-bar-row__fill {
  height: 100%;
  border-radius: 999px;
  background: var(--am-action-primary);
}

.inf-timing-bar-row__val {
  text-align: right;
  color: var(--am-text-strong);
  font-variant-numeric: tabular-nums;
}

.inf-inspector__note {
  margin: 0;
  font-size: 12px;
  color: var(--am-text-muted);
}

.inf-inspector__empty {
  padding: 28px 10px;
  text-align: center;
  font-size: 13px;
  color: var(--am-text-muted);
}

.inf-json-truncation-bar {
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid var(--am-border);
  background: var(--am-surface-soft);
  font-size: 12px;
  color: var(--am-text-muted);
}

.inf-json-more {
  padding: 6px 10px;
  border-radius: 6px;
  background: var(--am-surface-soft);
  font-size: 12px;
  color: var(--am-text-muted);
  text-align: center;
}

.inf-json-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.inf-json-toolbar__btns {
  display: inline-flex;
  gap: 6px;
}

.inf-json-box {
  flex: 1 1 auto;
  min-height: 220px;
  display: flex;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-code-surface);
  overflow: auto;
  font-family: var(--am-font-mono);
  font-size: 12px;
  line-height: 1.55;
}

.inf-json-box__gutter {
  display: flex;
  flex-direction: column;
  padding: 10px 8px;
  border-right: 1px solid var(--am-border);
  color: var(--am-text-muted);
  text-align: right;
  user-select: none;
}

.inf-json-box__code {
  margin: 0;
  padding: 10px 12px;
  color: var(--am-code-text);
  white-space: pre;
}

.inf-json-box.is-wrap .inf-json-box__code {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.inf-inspector__footer {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 16px;
  border-top: 1px solid var(--am-border);
  background: var(--am-surface);
}

.inf-download-menu-wrap {
  position: relative;
}

.inf-download-menu {
  position: absolute;
  left: 0;
  bottom: calc(100% + 6px);
  min-width: 150px;
  padding: 6px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface);
  box-shadow: var(--am-shadow-floating);
  display: grid;
  gap: 2px;
  z-index: 5;
}

.inf-download-menu button {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--am-text-strong);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.inf-download-menu button:hover:not(:disabled) {
  background: var(--am-hover-surface);
}

.inf-download-menu button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
