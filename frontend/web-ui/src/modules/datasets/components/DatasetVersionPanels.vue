<template>
  <div class="dataset-panels">
    <InlineError v-if="error" :message="error" />
    <div v-if="loading && tab !== 'structure'" role="status">
      {{ text('loading') }}
    </div>
    <template v-if="tab === 'categories'">
      <section class="resource-section">
        <h2>{{ text('classes') }}</h2>
        <ResourceTable class="dataset-table" :label="text('classes')">
          <thead>
            <tr>
              <th rowspan="2" scope="col" style="width: 28%">{{ text('classes') }}</th>
              <th rowspan="2" scope="col" class="dataset-number-cell">{{ text('samples') }}</th>
              <th rowspan="2" scope="col" class="dataset-number-cell">{{ text('object') }}</th>
              <th colspan="3" scope="colgroup" class="dataset-count-heading" style="width: 30%">{{ text('splits') }} · {{ text('object') }}</th>
              <th rowspan="2" scope="col">{{ text('actions') }}</th>
            </tr>
            <tr class="dataset-count-subhead">
              <th scope="col" class="dataset-number-cell">{{ text('trainingSplit') }}</th>
              <th scope="col" class="dataset-number-cell">{{ text('testingSplit') }}</th>
              <th scope="col" class="dataset-number-cell">{{ text('validationSplit') }}</th>
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
              <td class="dataset-number-cell"><DatasetCounts :items="sampleCounts(row.sample_count)" /></td>
              <td class="dataset-number-cell"><DatasetCounts :items="objectCounts(row.object_count)" /></td>
              <td v-for="item in splitColumns(row.split_objects, text('objectUnit'))" :key="item.key" class="dataset-number-cell"><DatasetCounts :items="[item]" /></td>
              <td>
                <Button
                  size="sm"
                  @click="emit('filter', { category: row.category_id })"
                  >{{ text('view') }}</Button
                >
              </td>
            </tr>
          </tbody>
        </ResourceTable>
        <p class="dataset-muted dataset-note">
          {{
            label(
              '同一张图片可包含多个类别，类别样本数不累加。',
              'An image may contain multiple classes; class sample counts are not additive.',
            )
          }}
        </p>
      </section>
      <section class="resource-section">
        <h2>{{ text('splits') }}</h2>
        <ResourceTable class="dataset-table" :label="text('splits')"
          ><thead>
            <tr>
              <th>Split</th>
              <th class="dataset-number-cell">{{ text('samples') }}</th>
              <th class="dataset-number-cell">{{ text('object') }}</th>
              <th class="dataset-number-cell">{{ label('占比', 'Percentage') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="split in splits" :key="split">
              <td>{{ split }}</td>
              <td class="dataset-number-cell"><DatasetCounts :items="countItems(split, workspace.split_counts[split] ?? 0, splitName(split))" /></td>
              <td class="dataset-number-cell"><DatasetCounts :items="objectCounts(categories.reduce((n, item) => n + (item.split_objects[split] ?? 0), 0))" /></td>
              <td class="dataset-number-cell">
                {{
                  workspace.sample_count
                    ? `${((100 * (workspace.split_counts[split] ?? 0)) / workspace.sample_count).toFixed(1)}%`
                    : '—'
                }}
              </td>
            </tr>
          </tbody></ResourceTable
        >
      </section>
    </template>
    <template v-else-if="tab === 'quality'">
      <div v-if="canWrite" class="dataset-actions">
        <Button variant="primary" @click="openTool('quality')">{{
          label('重新检查', 'Run checks')
        }}</Button>
      </div>
      <DatasetJobHistory
        :key="workspace.dataset_version_id"
        :workspace="workspace"
      />
      <section class="resource-section">
        <div class="dataset-heading">
          <h2>{{ label('导入检查', 'Import checks') }}</h2>
          <StatusBadge
            v-if="report?.available"
            :status="String(report.report?.status || 'unknown')"
            :label="text(String(report.report?.status || 'unknown'))"
          />
        </div>
        <template v-if="report?.available"
          ><p>{{ datasetDate(report.checked_at) }}</p>
          <dl class="dataset-details">
            <template v-for="(value, key) in reportCounts" :key="key"
              ><dt>{{ reportLabel(String(key)) }}</dt>
              <dd>{{ value }}</dd></template
            >
          </dl>
          <InlineError
            v-if="report.report?.error"
            :message="
              typeof report.report.error === 'string'
                ? report.report.error
                : JSON.stringify(report.report.error)
            "
          />
          <ul v-if="reportWarnings.length">
            <li v-for="(warning, index) in reportWarnings" :key="index">
              {{
                typeof warning === 'string' ? warning : JSON.stringify(warning)
              }}
            </li>
          </ul>
          <details>
            <summary>
              {{ label('查看检查报告', 'View check report') }}
            </summary>
            <pre class="dataset-json">{{
              JSON.stringify(report.report, null, 2)
            }}</pre>
          </details></template
        >
        <p v-else>
          {{
            label(
              '没有可用的导入检查报告',
              'No import check report is available',
            )
          }}
        </p>
      </section>
    </template>
    <template v-else-if="tab === 'lineage'">
      <div class="dataset-actions">
        <Button v-if="canWrite" @click="openTool('samples')">{{
          label('更新样本', 'Update samples')
        }}</Button
        ><Button v-if="canWrite" @click="openTool('compare')">{{
          label('比较版本', 'Compare versions')
        }}</Button>
      </div>
      <ResourceTable class="dataset-table" :label="text('versions')"
        ><thead>
          <tr>
            <th>{{ text('version') }}</th>
            <th style="width: 26%">{{ label('版本说明', 'Version notes') }}</th>
            <th class="dataset-number-cell">{{ text('samples') }}</th>
            <th class="dataset-number-cell">{{ text('object') }}</th>
            <th style="width: 19%">{{ text('created') }}</th>
            <th style="width: 140px">{{ text('actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="version in versions"
            :key="version.dataset_version_id"
            :class="{
              'is-selected':
                version.dataset_version_id === workspace.dataset_version_id,
            }"
          >
            <td>
              <span :title="version.dataset_version_id">{{
                `v${version.version_number}`
              }}</span>
            </td>
            <td :title="String(version.metadata.description || '')">
              {{ version.metadata.description || '—' }}
            </td>
            <td class="dataset-number-cell"><DatasetCounts :items="sampleCounts(version.sample_count)" /></td>
            <td class="dataset-number-cell"><DatasetCounts :items="objectCounts(version.object_count)" /></td>
            <td>{{ datasetDate(version.created_at) }}</td>
            <td>
              <Button
                size="sm"
                @click="emit('version', version.dataset_version_id)"
                :disabled="
                  version.dataset_version_id === workspace.dataset_version_id
                "
                >{{
                  version.dataset_version_id === workspace.dataset_version_id
                    ? label('当前', 'Current')
                    : text('view')
                }}</Button
              >
              <Button
                v-if="
                  canWrite &&
                  version.dataset_version_id !== workspace.dataset_version_id
                "
                size="sm"
                class="dataset-compare-button"
                @click="compareWith(version.dataset_version_id)"
                >{{ label('比较', 'Compare') }}</Button
              >
            </td>
          </tr>
        </tbody></ResourceTable
      >
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
      <section class="resource-section">
        <h2>{{ text('source') }}</h2>
        <dl class="dataset-details">
          <dt>{{ text('version') }}</dt>
          <dd :title="workspace.dataset_version_id">
            {{ `v${workspace.version_number}` }}
          </dd>
          <dt>{{ text('created') }}</dt>
          <dd>{{ datasetDate(workspace.created_at) }}</dd>
          <template v-if="workspace.metadata.description"
            ><dt>{{ label('版本说明', 'Version notes') }}</dt>
            <dd>{{ workspace.metadata.description }}</dd></template
          >
          <template
            v-if="
              workspace.metadata.format_id || workspace.metadata.format_type
            "
          >
            <dt>{{ label('来源格式', 'Source format') }}</dt>
            <dd>
              {{
                workspace.metadata.format_id || workspace.metadata.format_type
              }}
            </dd>
          </template>
          <dt>{{ text('source') }}</dt>
          <dd
            :title="
              String(
                workspace.metadata.parent_version_id ||
                  workspace.metadata.source_import_id ||
                  '',
              )
            "
          >
            <Button
              v-if="workspace.parent_version_number"
              size="sm"
              @click="
                emit('version', String(workspace.metadata.parent_version_id))
              "
              >{{ `v${workspace.parent_version_number}` }}</Button
            >
            <span v-else-if="workspace.metadata.parent_version_id">{{
              label('来源版本已不可用', 'Source version unavailable')
            }}</span>
            <span v-else>{{
              workspace.metadata.source_import_id
                ? label('导入数据集', 'Dataset import')
                : '—'
            }}</span>
          </dd>
        </dl>
      </section>
      <DatasetJobHistory
        :key="workspace.dataset_version_id"
        :workspace="workspace"
      />
    </template>
    <section v-if="structureVisited" v-show="tab === 'structure'" class="dataset-structure-panel">
      <div class="dataset-structure-switch" role="group" :aria-label="text('structure')">
        <button :aria-pressed="structureMode === 'samples'" @click="structureMode = 'samples'; samplesVisited = true">{{ label('样本结构', 'Sample structure') }}</button>
        <button :aria-pressed="structureMode === 'files'" @click="structureMode = 'files'">{{ label('文件结构', 'File structure') }}</button>
      </div>
      <DatasetFileBrowser v-show="structureMode === 'files'" :workspace="workspace" />
      <DatasetSampleStructure v-if="samplesVisited" v-show="structureMode === 'samples'" :workspace="workspace" @sample="emit('sample', $event)" />
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
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { annotationColor } from '../annotations'
import { datasetDate, datasetError, useDatasetText } from '../dataset-workspace'
import DatasetCounts from './DatasetCounts.vue'
import { useDatasetCounts } from '../dataset-counts'
const { sampleCounts, objectCounts, splitColumns, countItems, splitName } = useDatasetCounts()
import {
  getDatasetCategories,
  getDatasetReport,
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
function openTool(operation: string) {
  router.push(
    `/datasets/${encodeURIComponent(props.workspace.dataset_id)}/versions/${encodeURIComponent(props.workspace.dataset_version_id)}/tools/${operation}`,
  )
}
function compareWith(id: string) {
  router.push({
    path: `/datasets/${encodeURIComponent(props.workspace.dataset_id)}/versions/${encodeURIComponent(props.workspace.dataset_version_id)}/tools/compare`,
    query: { compare: id },
  })
}
const emit = defineEmits<{
  version: [id: string]
  sample: [sample: DatasetSample]
  filter: [value: { category?: number; split?: string }]
}>()
const { locale } = useI18n(),
  text = useDatasetText(),
  label = (zh: string, en: string) => (locale.value.startsWith('zh') ? zh : en)
const splits = ['train', 'test', 'val'],
  error = ref(''),
  loading = ref(false),
  categories = ref<CategoryStatistic[]>([]),
  versions = ref<DatasetVersion[]>([]),
  versionOffset = ref(0),
  versionTotal = ref(0)
const structureVisited = ref(false), structureMode = ref('files'), samplesVisited = ref(false)
const report = ref<Awaited<ReturnType<typeof getDatasetReport>> | null>(null)
const loaded = new Set<string>()
const reportCounts = computed(() =>
  Object.fromEntries(
    Object.entries(report.value?.report || {}).filter(
      ([, value]) => typeof value === 'number',
    ),
  ),
)
const reportWarnings = computed(() =>
  Array.isArray(report.value?.report?.warnings)
    ? (report.value!.report!.warnings as unknown[])
    : [],
)
const reportLabel = (key: string) =>
  ({
    sample_count: label('图像数量', 'Images'),
    annotation_count: label('对象数量', 'Objects'),
    category_count: label('类别数量', 'Classes'),
    warning_count: label('提示数量', 'Warnings'),
    issue_count: label('检查提示', 'Issues'),
    error_count: label('错误数量', 'Errors'),
    retained_issue_count: label('报告包含提示', 'Issues in report'),
  })[key] || key
let controller: AbortController | undefined,
  generation = 0
async function load() {
  controller?.abort()
  const id = ++generation
  loading.value = false
  error.value = ''
  const key = `${props.tab}:${versionOffset.value}`
  if (
    !['categories', 'quality', 'lineage'].includes(props.tab) ||
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
      if (id === generation) categories.value = data.items
    } else if (props.tab === 'quality') {
      const data = await getDatasetReport(
        w.dataset_id,
        w.dataset_version_id,
        controller.signal,
      )
      if (id === generation) report.value = data
    } else if (props.tab === 'lineage') {
      const data = await listDatasetVersionPage(
        {
          project_id: w.project_id,
          dataset_id: w.dataset_id,
          offset: versionOffset.value,
          limit: 20,
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
    controller?.abort()
    loading.value = false
    loaded.clear()
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
@media(max-width:1200px) { .dataset-structure-switch { width:196px; } }
</style>

<style scoped>
.dataset-structure-panel { position:relative; min-width:0; }
.dataset-structure-switch { position:absolute; z-index:1; top:12px; left:12px; display:flex; width:256px; padding:3px; background:var(--am-surface); border:1px solid var(--am-border); border-radius:var(--am-radius-md); }
.dataset-structure-switch button { flex:1; padding:8px 10px; border:0; border-radius:var(--am-radius-sm); color:var(--am-text-muted); background:none; cursor:pointer; }
.dataset-structure-switch button:hover { background:var(--am-hover-surface); }
.dataset-structure-switch button[aria-pressed='true'] { color:var(--am-brand-primary); background:var(--am-row-selected); }
@media(max-width:1200px) { .dataset-structure-switch { width:196px; } }
</style>
