<template>
  <div class="dataset-panels" :aria-busy="loading">
    <InlineError v-if="error" :message="error" />
    <div
      v-if="loading && tab !== 'structure'"
      role="status"
      :class="{
        'panel-loading-announcement': tab === 'lineage' && versions.length,
      }"
    >
      {{ text('loading') }}
    </div>
    <template v-if="tab === 'categories' && categoriesReady">
      <section class="resource-section panel-section">
        <h2>{{ label('类别统计', 'Class statistics') }}</h2>
        <ResourceTable
          class="dataset-table stats-table"
          :label="text('classes')"
        >
          <thead>
            <tr>
              <th>{{ text('classes') }}</th>
              <th>{{ label('样本数', 'Samples with class') }}</th>
              <th>{{ label('标注对象', 'Objects') }}</th>
              <th v-for="split in categorySplits" :key="split">
                {{ split }} {{ text('object') }}
              </th>
              <th>{{ text('actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in categories" :key="row.category_id">
              <td :title="row.name">
                <span
                  class="dataset-class-dot"
                  :style="{ background: annotationColor(row.category_id) }"
                />{{ row.name }}
              </td>
              <td>{{ number(row.sample_count) }}</td>
              <td>{{ number(row.object_count) }}</td>
              <td v-for="split in categorySplits" :key="split">
                {{ number(row.split_objects[split] ?? 0) }}
              </td>
              <td>
                <Button
                  size="sm"
                  @click="emit('filter', { category: row.category_id })"
                  >{{ label('查看样本', 'View samples') }}</Button
                >
              </td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <th>{{ label('合计', 'Total') }}</th>
              <td>—</td>
              <td>{{ number(totalObjects) }}</td>
              <td v-for="split in categorySplits" :key="split">
                {{ number(splitObjects(split)) }}
              </td>
              <td>—</td>
            </tr>
          </tfoot>
        </ResourceTable>
        <p class="dataset-muted dataset-note">
          <Info :size="15" />{{
            label(
              '同一样本可包含多个类别，类别样本数不能相加。',
              'A sample can belong to multiple classes. Class sample counts are not additive.',
            )
          }}
        </p>
      </section>
      <section class="resource-section panel-section">
        <h2>{{ text('splits') }}</h2>
        <ResourceTable
          class="dataset-table stats-table"
          :label="text('splits')"
        >
          <thead>
            <tr>
              <th>{{ label('划分', 'Split') }}</th>
              <th>{{ label('样本数量', 'Samples') }}</th>
              <th>{{ label('对象数量', 'Objects') }}</th>
              <th>{{ label('占比', 'Share') }}</th>
              <th>{{ label('说明', 'Purpose') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="split in splits" :key="split">
              <td>{{ split }}</td>
              <td>
                {{
                  configured(split)
                    ? number(workspace.split_counts[split])
                    : label('未配置', 'Not configured')
                }}
              </td>
              <td>
                {{
                  configured(split)
                    ? number(
                        workspace.split_object_counts?.[split] ??
                          splitObjects(split),
                      )
                    : '—'
                }}
              </td>
              <td>
                {{
                  configured(split) && workspace.sample_count
                    ? (
                        (100 * workspace.split_counts[split]) /
                        workspace.sample_count
                      ).toFixed(1) + '%'
                    : '—'
                }}
              </td>
              <td>{{ splitPurpose(split) }}</td>
            </tr>
          </tbody>
        </ResourceTable>
      </section>
    </template>
    <DatasetQualityPanel
      v-else-if="tab === 'quality'"
      :workspace="workspace"
      @sample="emit('sample', $event)"
    />
    <template v-else-if="tab === 'lineage'">
      <ResourceTable
        class="dataset-table lineage-table"
        :label="text('versions')"
      >
        <thead>
          <tr>
            <th>{{ text('version') }}</th>
            <th>{{ text('source') }}</th>
            <th>{{ text('samples') }}</th>
            <th>{{ text('object') }}</th>
            <th>{{ text('created') }}</th>
            <th>{{ label('引用', 'References') }}</th>
            <th>{{ text('actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="version in versions"
            :key="version.dataset_version_id"
            :class="{ 'is-selected': isCurrent(version) }"
          >
            <td>
              <div class="version-label">
                <span
                  class="version-marker"
                  :class="{ active: isCurrent(version) }"
                  aria-hidden="true"
                />
                v{{ version.version_number }}
                <small v-if="isCurrent(version)" class="current-tag">{{
                  label('当前', 'Current')
                }}</small>
              </div>
            </td>
            <td :title="sourceLabel(version)">{{ sourceLabel(version) }}</td>
            <td>{{ number(version.sample_count) }}</td>
            <td>{{ number(version.object_count) }}</td>
            <td :title="datasetDate(version.created_at)">
              {{ datasetDate(version.created_at) }}
            </td>
            <td :title="referenceLabel(version)">
              {{ referenceLabel(version) }}
            </td>
            <td>
              <span class="version-row-actions"
                ><button
                  v-if="
                    canReadTasks &&
                    (version.task_references?.training ||
                      version.task_references?.evaluation)
                  "
                  @click="referenceVersion = version"
                >
                  {{ label('查看引用', 'References') }}
                </button>
                <button
                  v-else
                  @click="
                    isCurrent(version)
                      ? emit('samples')
                      : emit('version', version.dataset_version_id)
                  "
                >
                  {{ text('view') }}
                </button>
                <button
                  v-if="canWrite && !isCurrent(version)"
                  @click="compareWith(version.dataset_version_id)"
                >
                  {{ label('比较', 'Compare') }}
                </button>
              </span>
            </td>
          </tr>
        </tbody>
      </ResourceTable>
      <PaginationControls
        v-if="versionTotal > 20"
        :offset="versionOffset"
        :limit="20"
        :item-count="versions.length"
        :total-count="versionTotal"
        :disabled="loading"
        @previous="pageVersions(-20)"
        @next="pageVersions(20)"
      />
      <DatasetVersionReferences
        v-if="referenceVersion"
        :dataset-id="workspace.dataset_id"
        :version="referenceVersion"
        @close="referenceVersion = null"
      />
      <DatasetSourceSummary
        :workspace="workspace"
        @version="emit('version', $event)"
      />
      <details
        class="panel-history"
        @toggle="
          historyOpen = ($event.currentTarget as HTMLDetailsElement).open
        "
      >
        <summary>{{ label('工作区操作', 'Workspace operations') }}</summary>
        <DatasetJobHistory :workspace="workspace" v-if="historyOpen" />
      </details>
    </template>
    <section
      v-if="structureVisited"
      v-show="tab === 'structure'"
      class="dataset-structure-panel"
    >
      <SegmentedButtonGroup
        v-model="structureMode"
        :label="text('structure')"
        :options="[
          { value: 'samples', label: label('样本结构', 'Sample structure') },
          { value: 'files', label: label('文件结构', 'File structure') },
        ]"
      />
      <DatasetFileBrowser
        v-show="structureMode === 'files'"
        :workspace="workspace"
      />
      <DatasetSampleStructure
        v-if="samplesVisited"
        v-show="structureMode === 'samples'"
        :workspace="workspace"
        @sample="emit('sample', $event)"
      />
    </section>
  </div>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useSessionStore } from '@/app/stores/session.store'
import DatasetFileBrowser from './DatasetFileBrowser.vue'
import DatasetSampleStructure from './DatasetSampleStructure.vue'
import DatasetJobHistory from './DatasetJobHistory.vue'
import Button from '@/shared/ui/components/Button.vue'
import SegmentedButtonGroup from '@/shared/ui/components/SegmentedButtonGroup.vue'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import DatasetQualityPanel from './DatasetQualityPanel.vue'
import DatasetVersionReferences from './DatasetVersionReferences.vue'
import DatasetSourceSummary from './DatasetSourceSummary.vue'
import { Info } from '@lucide/vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { annotationColor } from '../annotations'
import {
  datasetDate,
  datasetError,
  datasetFormatLabel,
  useDatasetText,
} from '../dataset-workspace'
import {
  getDatasetCategories,
  listDatasetVersionPage,
  type DatasetWorkspace,
  type DatasetVersion,
  type CategoryStatistic,
  type DatasetSample,
} from '../services/dataset-workspace.service'
const props = defineProps<{ workspace: DatasetWorkspace; tab: string }>()
const router = useRouter(),
  session = useSessionStore(),
  canWrite = computed(() => session.hasScopes(['datasets:write']))
const referenceVersion = ref<DatasetVersion | null>(null)
const canReadTasks = computed(() => session.hasScopes(['tasks:read']))
function compareWith(id: string) {
  router.push({
    path: `/datasets/${encodeURIComponent(props.workspace.dataset_id)}/versions/${encodeURIComponent(props.workspace.dataset_version_id)}/tools/compare`,
    query: { compare: id },
  })
}
const emit = defineEmits<{
  version: [id: string]
  samples: []
  sample: [sample: DatasetSample]
  filter: [value: { category?: number; split?: string }]
}>()
const { locale } = useI18n(),
  text = useDatasetText(),
  label = (zh: string, en: string) => (locale.value.startsWith('zh') ? zh : en)
const splits = ['train', 'val', 'test'],
  error = ref(''),
  loading = ref(false),
  categories = ref<CategoryStatistic[]>([]),
  versions = ref<DatasetVersion[]>([]),
  versionOffset = ref(0),
  versionTotal = ref(0)
const structureVisited = ref(false),
  structureMode = ref('files'),
  samplesVisited = ref(false)
watch(structureMode, mode => { if (mode === 'samples') samplesVisited.value = true })
const historyOpen = ref(false),
  categoriesReady = ref(false)
const loaded = new Set<string>()
const number = (n: number | undefined) =>
  n == null ? '—' : n.toLocaleString(locale.value)
const configured = (split: string) => split in props.workspace.split_counts
const categorySplits = computed(() =>
  configured('test') ? splits : splits.slice(0, 2),
)
const splitPurpose = (s: string) =>
  s === 'train'
    ? label('用于模型训练', 'Model training')
    : s === 'val'
      ? label('用于模型验证', 'Model validation')
      : label('用于模型测试', 'Model testing')
const totalObjects = computed(() =>
  categories.value.reduce((n, row) => n + row.object_count, 0),
)
const splitObjects = (s: string) =>
  categories.value.reduce((n, row) => n + (row.split_objects[s] ?? 0), 0)
const isCurrent = (v: DatasetVersion) =>
  v.dataset_version_id === props.workspace.dataset_version_id
const sourceLabel = (v: DatasetVersion) =>
  v.metadata.parent_version_id
    ? label('创建版本', 'Derived version')
    : v.metadata.source_import_id
      ? [
          datasetFormatLabel(
            String(v.metadata.format_id || v.metadata.format_type || ''),
          ),
          label('导入', 'import'),
        ]
          .filter((s) => s !== '—')
          .join(' ')
      : '—'
const referenceLabel = (v: DatasetVersion) => {
  const r = v.task_references
  if (!r) return '—'
  return (
    [
      r.training && label('训练 ' + r.training, 'Training ' + r.training),
      r.evaluation &&
        label('评估 ' + r.evaluation, 'Evaluation ' + r.evaluation),
    ]
      .filter(Boolean)
      .join(' · ') || label('无', 'None')
  )
}
let controller: AbortController | undefined,
  generation = 0
async function load() {
  controller?.abort()
  const id = ++generation
  loading.value = false
  error.value = ''
  const key = `${props.tab}:${versionOffset.value}`
  if (
    !['categories', 'lineage'].includes(props.tab) ||
    (props.tab !== 'lineage' && loaded.has(key))
  )
    return
  controller = new AbortController()
  loading.value = true
  error.value = ''
  const w = props.workspace
  try {
    if (props.tab === 'categories') {
      const data = await getDatasetCategories(
        w.dataset_id,
        w.dataset_version_id,
        controller.signal,
      )
      if (id === generation) {
        categories.value = data.items
        categoriesReady.value = true
      }
    } else if (props.tab === 'lineage') {
      const data = await listDatasetVersionPage(
        {
          project_id: w.project_id,
          dataset_id: w.dataset_id,
          offset: versionOffset.value,
          limit: 20,
          include_references: 1,
        },
        controller.signal,
      )
      if (id === generation) {
        versions.value = data.items
        versionTotal.value = data.total
      }
    }
    if (id === generation) loaded.add(key)
  } catch (e) {
    if (id === generation) error.value = datasetError(e)
  } finally {
    if (id === generation) loading.value = false
  }
}
watch(
  () => props.tab,
  () => {
    if (props.tab === 'structure') structureVisited.value = true
    void load()
  },
  { immediate: true },
)
watch(
  () => props.workspace,
  () => {
    generation++
    referenceVersion.value = null
    controller?.abort()
    loading.value = false
    loaded.clear()
    categories.value = []
    versions.value = []
    versionTotal.value = 0
    categoriesReady.value = false
    versionOffset.value = 0
    void load()
  },
)
onBeforeUnmount(() => {
  generation++
  controller?.abort()
})
function pageVersions(delta: number) {
  versionOffset.value = Math.max(0, versionOffset.value + delta)
  void load()
}
</script>
<style scoped>
.panel-loading-announcement {
  position: absolute;
  width: 1px;
  height: 1px;
  clip-path: inset(50%);
  overflow: hidden;
}
.dataset-panels {
  display: grid;
  gap: 16px;
  min-width: 0;
}
.resource-section {
  min-width: 0;
}
.resource-section h2 {
  font-size: 16px;
  margin: 0 0 16px;
  font-weight: 600;
}
.dataset-class-dot {
  display: inline-block !important;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 10px;
}
.dataset-compare-button {
  margin-left: 8px;
}
.dataset-note {
  margin: 12px 0 0;
  font-size: 12px;
}
summary {
  cursor: pointer;
  margin-top: 18px;
}
.dataset-structure-panel {
  display: grid;
  gap: 10px;
  min-width: 0;
}
.dataset-note,
.version-row-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.stats-table :deep(:is(td, th):not(:first-child)) {
  text-align: center;
}
.stats-table :deep(tfoot) {
  background: var(--am-page-bg, var(--am-hover-surface));
  font-weight: 600;
}
.stats-table :deep(th:first-child) {
  width: 17%;
}
.lineage-table :deep(th:nth-child(5)) {
  width: 18%;
}
.lineage-table :deep(th:nth-child(3)),
.lineage-table :deep(th:nth-child(4)) {
  width: 8%;
}
.version-row-actions button {
  font: inherit;
  cursor: pointer;
  background: none;
  border: 0;
  color: var(--am-text);
  padding: 3px 2px;
}
.version-row-actions button:first-child,
.current-tag {
  color: var(--am-brand-primary);
}
.version-row-actions button:hover {
  text-decoration: underline;
}
.version-marker {
  display: inline-block;
  vertical-align: middle;
  border: 1px solid var(--am-border);
  width: 12px;
  height: 12px;
  border-radius: 50%;
}
.version-marker.active {
  border: 4px solid var(--am-brand-primary);
  background: white;
}
.version-label {
  display: flex;
  align-items: center;
  gap: 5px;
}
.lineage-table :deep(td .current-tag) {
  display: inline-block;
  background: var(--am-row-selected);
  color: var(--am-brand-primary);
  margin: 0;
  border-radius: 3px;
}
.lineage-table :deep(td > .version-row-actions) {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.stats-table :deep(tfoot tr > *) {
  background: var(--am-hover-surface);
}
.panel-section {
  margin: 0;
}
.current-tag {
  padding: 2px 4px;
  font-size: 12px;
  font-weight: 500;
}
.panel-history summary {
  margin: 0;
  color: var(--am-text-muted);
}
.panel-history[open] summary {
  margin-bottom: 12px;
}
</style>
