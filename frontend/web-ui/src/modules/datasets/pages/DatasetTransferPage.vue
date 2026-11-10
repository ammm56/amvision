<template>
  <section class="dataset-workspace">
    <div class="dataset-heading">
      <div class="dataset-actions">
        <Button :disabled="busy" @click="router.push('/datasets')"
          ><ArrowLeft :size="16" />{{ text('back') }}</Button
        >
        <h1 class="dataset-title">
          {{ text(importing ? 'import' : 'export') }}
        </h1>
      </div>
    </div>
    <ol class="dataset-steps" :aria-label="label('操作步骤', 'Steps')">
      <li
        v-for="(title, index) in steps"
        :key="title"
        :class="{ 'is-active': step === index, 'is-complete': step > index }"
      >
        <span>{{ index + 1 }}</span
        >{{ title }}
      </li>
    </ol>
    <InlineError v-if="error" :message="error" />
    <div v-if="unknown" class="resource-section" role="status">
      <p>
        {{
          label(
            '未能确认提交结果。请先查看记录，避免重复提交。',
            'Submission could not be confirmed. Check records before submitting again.',
          )
        }}
      </p>
      <Button
        @click="
          router.push({
            path: '/datasets',
            query: { tab: importing ? 'imports' : 'exports' },
          })
        "
        >{{ label('查看记录', 'View records') }}</Button
      >
    </div>
    <form v-else class="resource-section dataset-wizard" @submit.prevent="next">
      <h2>{{ steps[step] }}</h2>
      <fieldset :disabled="busy" class="dataset-wizard-fields">
        <template v-if="importing">
          <FilePicker
            v-if="step === 0"
            v-model="packageFile"
            icon="archive"
            accept=".zip,application/zip"
            :label="label('ZIP 文件', 'ZIP file')"
          />
          <template v-if="step === 1">
            <label class="field"
              ><span>{{ text('project') }}</span
              ><input :value="projectName" disabled
            /></label>
            <label class="field"
              ><span>{{ text('name') }} *</span
              ><input
                v-model="name"
                maxlength="255"
                :disabled="!!existing"
                required
            /></label>
            <label class="field"
              ><span>{{ text('task') }}</span
              ><SelectField
                v-model="taskType"
                :options="taskOptions"
                :disabled="!!existing"
            /></label>
            <label class="field"
              ><span>{{ label('输入格式', 'Input format') }}</span
              ><SelectField v-model="formatType" :options="formatOptions"
            /></label>
            <label class="field field--wide"
              ><span>{{ text('description') }}</span
              ><textarea
                v-model="description"
                rows="3"
                maxlength="2000"
                :disabled="!!existing"
              />
            </label>
            <details v-if="isMediaTask(taskType)" class="field--wide">
              <summary>{{ label('ZIP 清单格式','ZIP manifest format') }}</summary>
              <pre class="dataset-json">{{ mediaExample }}</pre>
            </details>
          </template>
          <template v-if="step === 2">
            <label class="field"
              ><span>{{ text('splits') }}</span
              ><SelectField v-model="split" :options="splitOptions"
            /></label>
            <div v-if="canMapClasses" class="field field--wide">
              <span>{{
                label('类别重命名（可选）', 'Rename classes (optional)')
              }}</span>
              <div
                v-for="(row, index) in classMap"
                :key="index"
                class="dataset-map-row"
              >
                <input
                  v-model="row.source"
                  :aria-label="label('来源类别', 'Source class')"
                  :placeholder="label('来源类别', 'Source class')"
                /><ArrowRight :size="16" /><input
                  v-model="row.target"
                  :aria-label="label('目标类别', 'Target class')"
                  :placeholder="label('目标类别', 'Target class')"
                /><Button
                  icon-only
                  :aria-label="text('remove')"
                  @click="classMap.splice(index, 1)"
                  ><X :size="16"
                /></Button>
              </div>
              <Button
                class="dataset-add-map"
                @click="classMap.push({ source: '', target: '' })"
                ><Plus :size="16" />{{
                  label('添加映射', 'Add mapping')
                }}</Button
              >
            </div>
          </template>
          <template v-if="step === 3"
            ><dl class="dataset-details">
              <dt>{{ label('ZIP 文件', 'ZIP file') }}</dt>
              <dd>
                {{ file?.name }} ·
                {{ ((file?.size || 0) / 1048576).toFixed(1) }} MB
              </dd>
              <dt>{{ text('name') }}</dt>
              <dd>{{ name }}</dd>
              <dt>{{ text('task') }}</dt>
              <dd>{{ taskType }}</dd>
              <dt>{{ label('输入格式', 'Input format') }}</dt>
              <dd>{{ formatType || label('自动识别', 'Auto detect') }}</dd>
              <dt>{{ text('splits') }}</dt>
              <dd>
                {{ splitOptions.find((item) => item.value === split)?.label }}
              </dd>
              <dt v-if="canMapClasses">{{ label('类别映射', 'Class mapping') }}</dt>
              <dd v-if="canMapClasses">
                {{
                  classMap.length
                    ? classMap
                        .map((row) => `${row.source} → ${row.target}`)
                        .join(' / ')
                    : label('保留原类别', 'Keep source classes')
                }}
              </dd>
            </dl>
            <p class="dataset-muted">
              {{
                label(
                  '提交后由后台检查压缩包、图片和标注，检查通过后生成版本。',
                  'The backend checks the archive, images and annotations after submission, then creates the version.',
                )
              }}
            </p></template
          >
        </template>
        <template v-else>
          <template v-if="step === 0"
            ><p v-if="selection" class="field--wide">
              {{ label('导出所选样本', 'Export selected samples') }} ·
              {{ selectionCounts?.sample_count ?? '…' }}
            </p>
            <div class="input-with-icon dataset-search">
              <Search :size="16" /><input
                v-model="sourceSearch"
                :aria-label="text('search')"
              /><Button size="sm" @click="searchVersions">{{
                label('搜索', 'Search')
              }}</Button>
            </div>
            <ResourceTable
              class="dataset-table field--wide"
              :label="text('versions')"
              ><thead>
                <tr>
                  <th>{{ text('name') }}</th>
                  <th>{{ text('version') }}</th>
                  <th>{{ text('task') }}</th>
                  <th>{{ text('samples') }}</th>
                  <th>{{ text('actions') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="item in versions"
                  :key="item.dataset_version_id"
                  :class="{
                    'is-selected':
                      selected?.dataset_version_id === item.dataset_version_id,
                  }"
                  @click="selectVersion(item)"
                >
                  <td :title="item.display_name || item.dataset_id">
                    {{ item.display_name || item.dataset_id }}
                  </td>
                  <td>
                    {{ `v${item.version_number}` }}
                  </td>
                  <td>{{ text(item.task_type) }}</td>
                  <td>{{ item.sample_count }}</td>
                  <td>
                    <Button size="sm" @click.stop="selectVersion(item)">{{
                      selected?.dataset_version_id === item.dataset_version_id
                        ? label('已选择', 'Selected')
                        : label('选择', 'Select')
                    }}</Button>
                  </td>
                </tr>
              </tbody></ResourceTable
            ><PaginationControls
              v-if="sourceTotal > 20"
              :offset="sourceOffset"
              :limit="20"
              :item-count="versions.length"
              :total-count="sourceTotal"
              @previous="pageVersions(-20)"
              @next="pageVersions(20)"
          /></template>
          <template v-if="step === 1"
            ><label class="field"
              ><span>{{ text('format') }}</span
              ><SelectField v-model="exportFormat" :options="exportOptions"
            /></label>
            <p v-if="!exportOptions.length" class="field--wide">
              {{
                label(
                  '当前任务类型没有可用的导出格式。',
                  'No export format is available for this task type.',
                )
              }}
            </p>
            <label class="field"
              ><span>{{
                label('任务名称（可选）', 'Task name (optional)')
              }}</span
              ><input v-model="displayName" maxlength="255" /></label
          ></template>
          <template v-if="step === 2"
            ><label class="dataset-checkbox field--wide"
              ><input
                v-model="includeTest"
                type="checkbox"
                :disabled="!(selectionCounts || selected)?.split_counts.test"
              />{{ label('包含 test 划分', 'Include test split') }}</label
            >
            <div class="field field--wide">
              <span>{{ label('输出类别名称', 'Output class names') }}</span>
              <div
                v-for="(row, index) in exportClasses"
                :key="row.id"
                class="dataset-map-row"
              >
                <span>{{ row.source }}</span
                ><ArrowRight :size="16" /><input
                  v-model="exportClasses[index].target"
                  :aria-label="row.source"
                />
              </div></div
          ></template>
          <template v-if="step === 3"
            ><dl class="dataset-details">
              <dt>{{ text('name') }}</dt>
              <dd>{{ selected?.display_name || selected?.dataset_id }}</dd>
              <dt>{{ text('version') }}</dt>
              <dd :title="selected?.dataset_version_id">
                {{ selected ? `v${selected.version_number}` : '—' }}
              </dd>
              <dt>{{ text('task') }}</dt>
              <dd>{{ text(selected?.task_type || '') }}</dd>
              <dt>{{ text('format') }}</dt>
              <dd>{{ exportFormat }}</dd>
              <dt>{{ text('samples') }}</dt>
              <dd>{{ exportCount }}</dd>
              <dt>{{ text('splits') }}</dt>
              <dd>
                {{
                  Object.keys((selectionCounts || selected)?.split_counts || {})
                    .filter((key) => includeTest || key !== 'test')
                    .join(' / ')
                }}
              </dd>
              <dt>{{ text('classes') }}</dt>
              <dd>
                {{ exportClasses.map((row) => row.target).join(' / ') }}
              </dd>
            </dl>
            <p class="dataset-muted">
              {{
                label(
                  '导出由后台生成，源版本保持不变。',
                  'The backend creates the export without changing the source version.',
                )
              }}
            </p></template
          >
        </template>
      </fieldset>
      <footer class="dataset-wizard-footer">
        <Button :disabled="busy" @click="router.push('/datasets')">{{
          text('cancel')
        }}</Button>
        <div class="dataset-actions">
          <Button v-if="step > 0" :disabled="busy" @click="previousStep">{{
            label('上一步', 'Previous')
          }}</Button
          ><Button
            type="submit"
            variant="primary"
            :loading="busy"
            :disabled="busy || !canWrite || (!importing && !selected)"
            >{{
              step === 3 ? label('提交', 'Submit') : label('下一步', 'Next')
            }}</Button
          >
        </div>
      </footer>
    </form>
    <ConfirmDialog
      v-if="leaveOpen"
      :title="text('discard')"
      :message="text('unsaved')"
      :confirm-label="text('discard')"
      :cancel-label="text('cancel')"
      @confirm="leave(true)"
      @cancel="leave(false)"
    />
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  onBeforeRouteLeave,
  onBeforeRouteUpdate,
  useRoute,
  useRouter,
} from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, ArrowRight, Plus, Search, X } from '@lucide/vue'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { isMediaTask } from '../sample-media'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import FilePicker from '@/shared/ui/components/FilePicker.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { ApiError } from '@/shared/api/error'
import { useDatasetText, datasetError } from '../dataset-workspace'
import {
  submitDatasetImport,
  createDatasetExport,
  getDatasetExportFormats,
  type DatasetExportFormatCatalog,
  type DatasetSampleSelection,
} from '../services/dataset.service'
import {
  getDatasetInfo,
  getDatasetSelectionSummary,
  getDatasetWorkspace,
  listDatasetVersionPage,
  type DatasetInfo,
  type DatasetVersion,
} from '../services/dataset-workspace.service'
import '../dataset-workspace.css'
const route = useRoute(),
  router = useRouter(),
  project = useProjectStore(),
  session = useSessionStore(),
  text = useDatasetText(),
  { locale } = useI18n()
const label = (zh: string, en: string) =>
    locale.value.startsWith('zh') ? zh : en,
  importing = route.path.endsWith('/import'),
  projectId = project.selectedProjectId,
  projectName = project.selectedProject?.display_name || projectId
const steps = computed(() =>
  importing
    ? [
        label('选择 ZIP', 'Choose ZIP'),
        label('数据定义', 'Dataset'),
        label('类别与划分', 'Classes and splits'),
        label('检查并提交', 'Review and submit'),
      ]
    : [
        label('来源版本', 'Source version'),
        label('目标格式', 'Target format'),
        label('类别与划分', 'Classes and splits'),
        label('检查并提交', 'Review and submit'),
      ],
)
const step = ref(0),
  busy = ref(false),
  error = ref(''),
  unknown = ref(false),
  submitted = ref(false),
  file = ref<File | null>(null),
  existing = ref<DatasetInfo | null>(null),
  name = ref(''),
  description = ref(''),
  taskType = ref('detection'),
  formatType = ref(''),
  split = ref('auto'),
  classMap = ref<{ source: string; target: string }[]>([])
const mediaExample = computed(() => {
  const examples: Record<string, Record<string, unknown>> = {
    anomaly: { image:'surface.png', label:'anomaly', defect:'scratch' },
    'connector-reference': {image:'connector.png', synthetic:true, unit:'mm', pitch:2.54, pins:[{id:'P1',x:120,y:80}]},
    rgbd: {image:'color.png',depth:'depth.png',unit:'mm',scale:1,invalid:0},
    'point-cloud': {cloud:'part.ply',unit:'mm',frame:'scanner'},
  }
  return 'samples.json\n' + JSON.stringify({format_id:'amvision.sample-media.v1',task_type:taskType.value,samples:[{id:'sample-1',split:'train',...examples[taskType.value]}]},null,2)
})
const packageFile = computed<File | File[] | null>({
  get: () => file.value,
  set: (value) => {
    file.value = Array.isArray(value) ? value[0] || null : value
  },
})
const datasetId = String(
  route.query.dataset || `dataset-${crypto.randomUUID().replaceAll('-', '')}`,
)
const selection = ref<DatasetSampleSelection | undefined>(
  window.history.state?.datasetSelection?.version ===
    String(route.query.version || '')
    ? window.history.state.datasetSelection.selection
    : undefined,
)
const selectionCounts = ref<{
  sample_count: number
  split_counts: Record<string, number>
} | null>(null)
const canWrite = computed(
  () =>
    session.hasScopes(['datasets:write']) &&
    project.selectedProjectId === projectId,
)
const taskOptions = computed(() =>
  (
    (session.bootstrap?.capabilities?.dataset_import?.implemented_task_types ||
      []) as string[]
  ).map((value) => ({ value, label: text(value) })),
)
const formatOptions = computed(() => [
  { value: '', label: label('自动识别', 'Auto detect') },
  ...(
    (
      (session.bootstrap?.capabilities?.dataset_import
        ?.format_types_by_task_type || {}) as Record<string, string[]>
    )[taskType.value] || []
  ).map((value) => ({ value, label: value.toUpperCase() })),
])
const splitOptions = computed(() => [
  {
    value: 'auto',
    label: label('保留原划分 / 自动识别', 'Keep source splits / Auto detect'),
  },
  ...['train', 'val', 'test'].map((value) => ({ value, label: value })),
])
const exportFormats = ref<DatasetExportFormatCatalog | null>(null),
  exportFormat = ref(''),
  includeTest = ref(true),
  displayName = ref(''),
  selected = ref<DatasetVersion | null>(null),
  versions = ref<DatasetVersion[]>([]),
  sourceSearch = ref(''),
  sourceOffset = ref(0),
  sourceTotal = ref(0),
  exportClasses = ref<{ id: number; source: string; target: string }[]>([])
const exportOptions = computed(() =>
  (
    exportFormats.value?.format_types_by_task_type[
      selected.value?.task_type || ''
    ] || []
  ).map((value) => ({ value, label: value })),
)
const exportCount = computed(() =>
  selected.value
    ? (selectionCounts.value || selected.value).sample_count -
      (includeTest.value
        ? 0
        : (selectionCounts.value || selected.value).split_counts.test || 0)
    : 0,
)
const dirty = computed(
    () =>
      !submitted.value && (!!file.value || !!selected.value || !!name.value),
  ),
  leaveOpen = ref(false)
let answer: ((value: boolean) => void) | undefined,
  active = true,
  selectionGeneration = 0,
  listGeneration = 0
function leave(value: boolean) {
  leaveOpen.value = false
  answer?.(value)
  answer = undefined
}
function confirmLeave() {
  if (busy.value) return false
  if (!dirty.value) return true
  leaveOpen.value = true
  return new Promise<boolean>((resolve) => {
    answer = resolve
  })
}
onBeforeRouteLeave(confirmLeave)
onBeforeRouteUpdate(confirmLeave)
function unload(event: BeforeUnloadEvent) {
  if (dirty.value || busy.value) {
    event.preventDefault()
    event.returnValue = ''
  }
}
window.addEventListener('beforeunload', unload)
async function loadVersions() {
  const id = ++listGeneration
  try {
    const result = await listDatasetVersionPage({
      project_id: projectId,
      q: sourceSearch.value,
      offset: sourceOffset.value,
      limit: 20,
    })
    if (active && id === listGeneration) {
      versions.value = result.items
      sourceTotal.value = result.total
    }
  } catch (e) {
    if (active && id === listGeneration) error.value = datasetError(e)
  }
}
async function selectVersion(version: Pick<DatasetVersion, 'dataset_id' | 'dataset_version_id'>) {
  const id = ++selectionGeneration
  selected.value = null
  busy.value = true
  error.value = ''
  try {
    const result = await getDatasetWorkspace(
      version.dataset_id,
      version.dataset_version_id,
    )
    if (!active || id !== selectionGeneration) return
    if (result.dataset_version_id !== String(route.query.version || ''))
      selection.value = undefined
    const saved = window.history.state?.datasetSelection
    if (selection.value && saved?.revision !== undefined &&
        saved.revision !== String(result.metadata.content_revision || '')) {
      throw new Error(label('当前版本已更新，请返回重新选择样本。', 'This version has changed. Go back and select samples again.'))
    }
    const counts = selection.value
      ? await getDatasetSelectionSummary(result.dataset_id, result.dataset_version_id, selection.value)
      : null
    if (!active || id !== selectionGeneration) return
    selectionCounts.value = counts
    selected.value = result
    exportClasses.value = result.categories.map((c) => ({
      id: c.category_id,
      source: c.name,
      target: c.name,
    }))
    exportFormat.value = exportOptions.value[0]?.value || ''
    includeTest.value = !!(selectionCounts.value || result).split_counts.test
  } catch (e) {
    if (active && id === selectionGeneration) error.value = datasetError(e)
  } finally {
    if (active && id === selectionGeneration) busy.value = false
  }
}
const canMapClasses = computed(() => !isMediaTask(taskType.value) || taskType.value === 'anomaly')
watch(taskType, () => {
  if (!canMapClasses.value) classMap.value = []
  if (!formatOptions.value.some((item) => item.value === formatType.value))
    formatType.value = ''
})
async function next() {
  if (busy.value || unknown.value) return
  error.value = ''
  if (!canWrite.value) {
    error.value = label(
      '项目已切换或没有写入权限，请返回列表。',
      'Project changed or write permission is unavailable. Return to the list.',
    )
    return
  }
  if (importing) {
    if (
      step.value === 0 &&
      (!file.value ||
        !file.value.name.toLowerCase().endsWith('.zip') ||
        !file.value.size)
    ) {
      error.value = label(
        '请选择有效的 ZIP 文件',
        'Choose a non-empty ZIP file',
      )
      return
    }
    if (
      step.value === 1 &&
      (!name.value.trim() ||
        !taskOptions.value.some((item) => item.value === taskType.value))
    ) {
      error.value = label(
        '请填写名称并选择任务类型',
        'Enter a name and choose a task type',
      )
      return
    }
    if (
      step.value === 2 &&
      (classMap.value.some((row) => !row.source.trim() || !row.target.trim()) ||
        new Set(classMap.value.map((row) => row.source.trim())).size !==
          classMap.value.length)
    ) {
      error.value = label(
        '映射名称不能为空，来源类别不能重复',
        'Mapping names are required and source classes must be unique',
      )
      return
    }
  } else {
    if (!selected.value) {
      error.value = label('请选择来源版本', 'Choose a source version')
      return
    }
    if (
      step.value >= 1 &&
      !exportOptions.value.some((item) => item.value === exportFormat.value)
    ) {
      error.value = label(
        '请选择可用的导出格式',
        'Choose an available export format',
      )
      return
    }
    if (
      step.value === 2 &&
      (exportClasses.value.some((row) => !row.target.trim()) ||
        new Set(exportClasses.value.map((row) => row.target.trim())).size !==
          exportClasses.value.length)
    ) {
      error.value = label(
        '类别名称不能为空或重复',
        'Class names must be non-empty and unique',
      )
      return
    }
  }
  if (step.value < 3) {
    step.value++
    return
  }
  busy.value = true
  try {
    if (importing) {
      const result = await submitDatasetImport({
        projectId,
        datasetId,
        packageFile: file.value!,
        formatType: formatType.value || undefined,
        taskType: taskType.value,
        splitStrategy: split.value,
        displayName: name.value.trim(),
        description: description.value,
        classMapJson: JSON.stringify(
          Object.fromEntries(
            classMap.value.map((row) => [row.source.trim(), row.target.trim()]),
          ),
        ),
      })
      submitted.value = true
      busy.value = false
      await router.push(`/datasets/imports/${result.dataset_import_id}`)
    } else {
      const source = selected.value!
      const result = await createDatasetExport({
        projectId,
        datasetId: source.dataset_id,
        datasetVersionId: source.dataset_version_id,
        formatId: exportFormat.value,
        displayName: displayName.value,
        includeTestSplit: includeTest.value,
        selection: selection.value,
        categoryNames: exportClasses.value.map((row) => row.target.trim()),
      })
      submitted.value = true
      busy.value = false
      await router.push(`/datasets/exports/${result.dataset_export_id}`)
    }
  } catch (e) {
    error.value = datasetError(e)
    unknown.value = !(e instanceof ApiError) || e.status >= 500
  } finally {
    busy.value = false
  }
}
onMounted(async () => {
  busy.value = true
  try {
    if (importing && route.query.dataset) {
      existing.value = await getDatasetInfo(projectId, datasetId)
      name.value = existing.value.display_name
      description.value = existing.value.description
      taskType.value = existing.value.task_type
    } else if (!importing) {
      exportFormats.value = await getDatasetExportFormats()
      await loadVersions()
      const v = String(route.query.version || '')
      if (v && route.query.dataset) {
        await selectVersion({ dataset_id: String(route.query.dataset), dataset_version_id: v })
      }
    }
  } catch (e) {
    if (active) error.value = datasetError(e)
  } finally {
    if (active) busy.value = false
  }
})
onBeforeUnmount(() => {
  active = false
  selectionGeneration++
  listGeneration++
  answer?.(false)
  window.removeEventListener('beforeunload', unload)
})
function searchVersions() {
  sourceOffset.value = 0
  void loadVersions()
}
function pageVersions(delta: number) {
  sourceOffset.value = Math.max(0, sourceOffset.value + delta)
  void loadVersions()
}
function previousStep() {
  step.value--
  error.value = ''
}
</script>
<style scoped>
.dataset-wizard {
  min-width: 0;
  max-width: 1160px;
}
.dataset-wizard h2 {
  font-size: 18px;
  margin: 0 0 24px;
}
.dataset-wizard-fields {
  border: 0;
  padding: 0;
  min-width: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}
.dataset-wizard-fields > .file-picker,
.dataset-wizard-fields > .dataset-details,
.dataset-wizard-fields > .dataset-muted {
  grid-column: 1/-1;
}
.dataset-wizard-footer {
  display: flex;
  justify-content: space-between;
  margin-top: 32px;
  padding-top: 18px;
  border-top: 1px solid var(--am-border);
}
.dataset-map-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 16px minmax(0, 1fr) 36px;
  align-items: center;
  gap: 12px;
}
.dataset-add-map {
  justify-self: start;
}
.dataset-checkbox {
  display: flex;
  align-items: center;
  gap: 10px;
}
.dataset-muted {
  color: var(--am-text-muted);
  font-size: 13px;
}
.dataset-details {
  margin: 0;
}
@media (max-width: 800px) {
  .dataset-wizard-fields {
    grid-template-columns: 1fr;
  }
  .dataset-steps {
    padding: 12px;
    gap: 10px;
  }
  .dataset-steps li {
    min-width: 115px;
  }
}
</style>
