<template>
  <section class="dataset-workspace dataset-operation" :class="{ 'dataset-operation--derive': operation === 'derive', 'dataset-operation--compare': operation === 'compare' }">
    <div class="dataset-heading">
      <div class="dataset-actions">
        <Button @click="back"
          ><ArrowLeft :size="16" />{{ text('back') }}</Button
        >
        <h1 class="dataset-title">{{ title }}</h1>
      </div>
      <ol v-if="operation === 'derive'" class="dataset-steps derivation-steps" :aria-label="label('操作步骤', 'Steps')">
        <li :class="{ 'is-active': !job, 'is-complete': !!job }" :aria-current="!job ? 'step' : undefined"><span><Check v-if="job" :size="18" /><template v-else>1</template></span>{{ label('配置变更', 'Configure changes') }}</li>
        <li :class="{ 'is-active': !!job }" :aria-current="job ? 'step' : undefined"><span>2</span>{{ label('检查并创建', 'Review and create') }}</li>
      </ol>
      <span v-else-if="workspace">{{ workspace.dataset.display_name }}</span>
    </div>
    <InlineError v-if="error" :message="error" />
    <Button v-if="error && !loading && (!workspace || (initializationFailed && !staleSelection) || (pollFailed && !job))" @click="initialize">{{
      text('retry')
    }}</Button>
    <p v-if="loading">{{ text('loading') }}</p>
    <template v-if="workspace && !loading && (!initializationFailed || staleSelection)">
      <form
        v-if="operation === 'derive' && !checked && !job && !route.query.task"
        class="resource-section dataset-config"
        @submit.prevent="submit('derive-check')"
      >
        <fieldset class="dataset-config-fields" :disabled="busy || unknown">
          <section class="derivation-source">
            <h2>{{ label('版本来源', 'Version source') }}</h2>
            <div class="derivation-form-row"><span class="dataset-muted">{{ label('来源数据集', 'Source dataset') }}</span><div class="derivation-source-value">{{ workspace.dataset.display_name }} <span>v{{ workspace.version_number }}</span></div></div>
          </section>
          <section class="derivation-mapping">
            <h2>{{ label('类别映射', 'Class mapping') }}</h2>
            <p class="dataset-muted">{{ label('可将多个源类别合并为同一目标类别，或排除不需要的类别标注。变更后请在下一步检查数量。', 'Merge source classes or exclude class annotations. Review the resulting counts in the next step.') }}</p>
            <ResourceTable class="dataset-table" :label="label('类别映射', 'Class mapping')">
              <thead><tr><th>{{ label('源类别', 'Source class') }}（v{{ workspace.version_number }}）</th><th>{{ label('目标类别', 'Target class') }}</th></tr></thead>
              <tbody><tr v-for="row in names" :key="row.id"><td :title="row.source">{{ row.source }}</td><td>
                <div class="derivation-target">
                  <SelectField v-if="!row.editing" v-model="row.target" :options="mappingOptions(row.id)" :aria-label="`${label('目标类别', 'Target class')} ${row.source}`" floating />
                  <label v-else class="field"><input v-model="row.name" maxlength="255" :aria-label="`${label('新类别名称', 'New class name')} ${row.source}`" /></label>
                  <Button v-if="row.target === row.id" :aria-label="`${label('重命名', 'Rename')} ${row.source}`" :title="label('重命名', 'Rename')" @click="row.editing = !row.editing"><Pencil :size="14" /></Button>
                  <Button v-if="row.target !== row.id || row.name !== row.source" :aria-label="`${label('重置映射', 'Reset mapping')} ${row.source}`" @click="row.target = row.id; row.name = row.source; row.editing = false"><RotateCcw :size="14" /></Button>
                </div>
              </td></tr></tbody>
            </ResourceTable>
          </section>
          <section class="derivation-form-row derivation-partition">
            <h2>{{ text('splits') }}</h2>
            <div class="derivation-partition-fields">
              <div class="dataset-actions">
                <label class="dataset-checkbox"><input v-model="repartition" type="radio" :value="false" name="partition" />{{ label('保留原划分', 'Keep existing splits') }}</label>
                <label class="dataset-checkbox"><input v-model="repartition" type="radio" :value="true" name="partition" />{{ label('重新划分', 'Repartition') }}</label>
              </div>
              <div v-if="repartition" class="derivation-ratios">
                <label v-for="(split, i) in ['train', 'val', 'test']" :key="split" class="field field--compact derivation-ratio"><span>{{ split }}</span><input v-model.number="ratios[i]" :aria-label="`${split} %`" type="number" min="0" max="100" step="1" /><span>%</span></label>
                <div class="derivation-total" :class="{ invalid: ratioTotal !== 100 }">{{ label('总计', 'Total') }} <strong>{{ ratioTotal }}%</strong></div>
              </div>
              <div v-if="repartition" class="derivation-options">
                <label class="field field--compact derivation-option derivation-seed"><span>{{ label('随机种子', 'Seed') }}</span><input v-model.number="seed" type="number" min="0" max="2147483647" step="1" /></label>
              </div>
              <div v-else class="derivation-existing dataset-muted"><span v-for="split in ['train', 'val', 'test']" :key="split">{{ split }} <strong>{{ workspace.split_counts?.[split]?.toLocaleString() ?? label('未配置', 'Not configured') }}</strong></span></div>
            </div>
          </section>
          <section class="derivation-form-row">
            <h2>{{ label('数据范围', 'Data range') }}</h2>
            <div class="derivation-range"><div><ImageIcon :size="26" /><div><span>{{ label('图像数量', 'Images') }}</span><strong>{{ (selectionCount ?? workspace.sample_count).toLocaleString() }} {{ label('张', 'images') }}（{{ selection ? label('所选', 'Selected') : label('全部', 'All') }}）</strong></div></div><div><Database :size="26" /><div><span>{{ label('对象数量（来源）', 'Objects (source)') }}</span><strong>{{ workspace.object_count?.toLocaleString() ?? '—' }} {{ label('个', 'objects') }}</strong></div></div></div>
          </section>
          <label class="field derivation-form-row derivation-notes"><span>{{ label('版本说明', 'Version notes') }}</span><textarea v-model="description" rows="3" maxlength="500" /></label>
          <div class="dataset-actions dataset-form-actions">
            <Button :disabled="busy" @click="back">{{ text('cancel') }}</Button>
            <Button
              type="submit"
              variant="primary"
              :loading="busy"
              :disabled="!canWrite || unknown || staleSelection"
              >{{ label('下一步', 'Next') }}</Button
            >
          </div>
        </fieldset>
      </form>
      <DatasetComparison
        v-if="operation === 'compare'"
        :source="workspace" :target-id="compareVersion" :versions="versions"
        :job="job" :busy="busy || unknown" :can-write="canWrite"
        :initial-filter="String(route.query.diff || 'all')" :initial-offset="Number(route.query.diffOffset || 0)"
        @view-state="router.replace({ query: { ...route.query, diff: $event.filter === 'all' ? undefined : $event.filter, diffOffset: $event.offset || undefined } })"
        @target="selectCompareTarget" @source="selectCompareSource"
        @compare="submit('compare')" @version="viewVersion" @sample="viewSample"
      >
        <template #versions>
          <div v-if="versionTotal > 20 || versionQuery || versionOffset > 0" class="dataset-actions">
            <label class="field"><input v-model="versionQuery" :aria-label="label('搜索版本', 'Search versions')" @input="searchVersions" /></label>
            <PaginationControls :offset="versionOffset" :limit="20" :item-count="versions.length" :total-count="versionTotal" @previous="pageVersions(-20)" @next="pageVersions(20)" />
          </div>
        </template>
        <template #status>
          <section v-if="job && job.state !== 'succeeded'" class="resource-section dataset-compare-status">
            <DatasetJobResult :job="job" />
            <div class="dataset-actions">
              <Button v-if="pollFailed" :loading="busy" @click="loadJob(job.task_id)">{{ text('refresh') }}</Button>
              <Button v-if="canWrite && ['queued', 'running'].includes(job.state)" :loading="busy" @click="cancel">{{ label('取消操作', 'Cancel operation') }}</Button>
              <Button v-if="['failed', 'cancelled', 'timed_out'].includes(job.state)" @click="editConfig">{{ label('返回配置', 'Return to configuration') }}</Button>
            </div>
          </section>
        </template>
      </DatasetComparison>
      <section
        v-if="operation === 'quality' && !job && !route.query.task"
        class="resource-section dataset-config"
      >
        <h2>{{ label('质量检查', 'Quality checks') }}</h2>
        <p class="dataset-muted">
          {{
            label(
              '检查图片可读性、尺寸、完全重复、类别和标注框。原始数据保持不变。',
              'Check image readability, size, exact duplicates, classes and boxes. Source data remains unchanged.',
            )
          }}
        </p>
        <Button
          variant="primary"
          :loading="busy"
          :disabled="!canWrite || unknown"
          @click="submit('quality')"
          >{{ label('开始检查', 'Run checks') }}</Button
        >
      </section>
      <section v-if="job && operation === 'derive'" class="resource-section derivation-source">
        <h2>{{ label('版本来源', 'Version source') }}</h2><div class="derivation-form-row"><span class="dataset-muted">{{ label('来源数据集', 'Source dataset') }}</span><div class="derivation-source-value">{{ workspace.dataset.display_name }} <span>v{{ workspace.version_number }}</span></div></div>
      </section>
      <section v-if="job && operation !== 'compare'" class="resource-section derivation-report">
        <DatasetDerivationReview
          v-if="job.operation === 'derive-check' && job.state === 'succeeded'"
          :job="job"
          :source-number="workspace.version_number"
          :source-name="workspace.dataset.display_name"
        />
        <DatasetJobResult
          v-else
          :job="job"
          :source-name="workspace.dataset.display_name"
          :source-number="workspace.version_number"
          @version="viewVersion"
          @sample="viewSample"
        />
        <div class="dataset-actions dataset-review-actions">
          <Button
            v-if="pollFailed"
            :loading="busy"
            @click="loadJob(job.task_id)"
            >{{ text('refresh') }}</Button
          >
          <Button
            v-if="canWrite && ['queued', 'running'].includes(job.state)"
            :loading="busy"
            @click="cancel"
            >{{ label('取消操作', 'Cancel operation') }}</Button
          ><template
            v-if="job.operation === 'derive-check' && job.state === 'succeeded'"
            ><Button @click="editConfig">{{
              label('上一步', 'Previous')
            }}</Button
            ><Button
              variant="primary"
              :loading="busy"
              :disabled="
                !canWrite || unknown || job.result?.can_create === false
              "
              @click="submit('derive')"
              >{{ label('创建新版本', 'Create version') }}</Button
            ></template
          ><Button
            v-if="['failed', 'cancelled', 'timed_out'].includes(job.state)"
            @click="editConfig"
            >{{ label('返回配置', 'Return to configuration') }}</Button
          >
        </div>
      </section>
      <div v-if="unknown" class="resource-section">
        <p>
          {{
            label(
              '提交结果待确认，请先查询本次请求。',
              'Submission is unconfirmed. Check this request before proceeding.',
            )
          }}
        </p>
        <Button :loading="busy" @click="resolveUnknown">{{
          label('查询提交结果', 'Check submission')
        }}</Button>
      </div>
    </template>
    <ConfirmDialog
      v-if="confirmation"
      :title="confirmation.title"
      :message="confirmation.message"
      :confirm-label="confirmation.confirmText"
      :cancel-label="confirmation.cancelText"
      confirm-variant="primary"
      @confirm="answerConfirm(true)"
      @cancel="answerConfirm(false)"
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
import { ArrowLeft, Check, Database, Image as ImageIcon, Pencil, RotateCcw } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { ApiError } from '@/shared/api/error'
import { useSessionStore } from '@/app/stores/session.store'
import DatasetJobResult from '../components/DatasetJobResult.vue'
import DatasetComparison from '../components/DatasetComparison.vue'
import DatasetDerivationReview from '../components/DatasetDerivationReview.vue'
import { datasetError, useDatasetText } from '../dataset-workspace'
import {
  cancelDatasetJob,
  findDatasetJob,
  getDatasetJob,
  getDatasetWorkspace,
  listDatasetVersionPage,
  submitDatasetJob,
  getDatasetSelectionSummary,
  type DatasetJob,
  type DatasetVersion,
  type DatasetWorkspace,
} from '../services/dataset-workspace.service'
import type { DatasetSampleSelection } from '../services/dataset.service'
import '../dataset-workspace.css'
import '../dataset-derivation.css'
const route = useRoute(),
  router = useRouter(),
  session = useSessionStore(),
  { locale } = useI18n(),
  text = useDatasetText()
const confirmation = ref<{
  title: string
  message: string
  confirmText: string
  cancelText: string
} | null>(null)
let confirmResolve: ((answer: boolean) => void) | undefined
const feedback = {
  confirm: (options: NonNullable<typeof confirmation.value>) =>
    new Promise<boolean>((resolve) => {
      confirmation.value = options
      confirmResolve = resolve
    }),
}
function answerConfirm(answer: boolean) {
  confirmation.value = null
  confirmResolve?.(answer)
  confirmResolve = undefined
}
const label = (zh: string, en: string) =>
  locale.value.startsWith('zh') ? zh : en
const dataset = String(route.params.datasetId),
  version = String(route.params.versionId),
  operation = String(route.params.operation)
const canWrite = computed(() => session.hasScopes(['datasets:write']))
const title = computed(() =>
  operation === 'derive'
    ? label('创建新版本', 'Create new version')
    : operation === 'compare'
      ? label('版本比较', 'Compare versions')
      : operation === 'return'
        ? label('版本操作', 'Version operation')
        : label('质量检查', 'Quality checks'),
)
const workspace = ref<DatasetWorkspace | null>(null),
  job = ref<DatasetJob | null>(null),
  checked = ref(''),
  busy = ref(false),
  loading = ref(true),
  unknown = ref(false),
  error = ref('')
const names = ref<{ id: number; source: string; name: string; target: number | null; editing?: boolean }[]>([]),
  repartition = ref(false),
  ratios = ref([80, 20, 0]),
  seed = ref(42),
  description = ref(''),
  staleSelection = ref(false),
  pollFailed = ref(false),
  selection = ref<DatasetSampleSelection>(),
  selectionCount = ref<number>()
const ratioTotal = computed(() => ratios.value.reduce((sum, value) => sum + Number(value || 0), 0))
function mappingOptions(id: number) {
  const supportsMapping = ['detection', 'classification', 'segmentation', 'obb'].includes(workspace.value?.task_type || '')
  const referenced = names.value.some(row => row.id !== id && row.target === id)
  return [
    ...names.value.map(row => ({ value: row.id, label: row.name, disabled: row.id !== id && (!supportsMapping || referenced || row.target !== row.id) })),
    ...(supportsMapping ? [{ value: null, label: label('排除此类别标注（保留样本）', 'Exclude annotations (keep samples)'), disabled: referenced }] : []),
  ]
}
const compareVersion = ref(String(route.query.compare || '')),
  versions = ref<DatasetVersion[]>([]),
  versionOffset = ref(0),
  versionTotal = ref(0),
  versionQuery = ref('')
function selectCompareSource(id: string) {
  router.push({ path: `/datasets/${encodeURIComponent(dataset)}/versions/${encodeURIComponent(id)}/tools/compare`, query: { compare: id === compareVersion.value ? version : compareVersion.value } })
}
function selectCompareTarget(id: string) {
  if (busy.value || unknown.value || ['queued', 'running'].includes(job.value?.state || '')) return
  compareVersion.value = id
  job.value = null
  router.replace({ query: { compare: id || undefined } })
}
const config = computed(() => ({
  selection: selection.value ?? null,
  category_names: Object.fromEntries(
    names.value.map((row) => [row.id, row.name.trim()]),
  ),
  category_mapping: Object.fromEntries(names.value.filter(row => row.target !== row.id).map(row => [row.id, row.target])),
  split_ratios: repartition.value ? ratios.value : null,
  seed: seed.value,
  group_key: '',
  description: description.value.trim(),
}))
let active = true,
  timer: ReturnType<typeof setTimeout> | undefined,
  searchTimer: ReturnType<typeof setTimeout> | undefined,
  requestId = String(route.query.request || ''),
  configSnapshot = '',
  formSnapshot = '',
  versionGeneration = 0
function back() {
  return router.push({
    path: `/datasets/${encodeURIComponent(dataset)}/versions/${encodeURIComponent(version)}`,
    query: { tab: operation === 'quality' ? 'quality' : 'lineage' },
  })
}
function viewVersion(id: string) {
  router.push({
    path: `/datasets/${encodeURIComponent(dataset)}/versions/${encodeURIComponent(id)}`,
    state: { datasetReturnTo: route.fullPath },
  })
}
function viewSample(id: string, target?: string) {
  router.push({
    path: `/datasets/${encodeURIComponent(dataset)}/versions/${encodeURIComponent(target || version)}`,
    query: { sample: id },
    state: { datasetReturnTo: route.fullPath },
  })
}
async function loadJob(id: string) {
  clearTimeout(timer)
  if (job.value?.task_id !== id) job.value = null
  pollFailed.value = false
  try {
    const result = await getDatasetJob(dataset, version, id)
    if (!active) return
    job.value = result
    error.value = ''
    if (result.operation === 'derive-check' && result.state === 'succeeded')
      checked.value = result.task_id
    if (['queued', 'running'].includes(result.state))
      timer = setTimeout(() => loadJob(id), 1500)
  } catch (e) {
    if (active) {
      error.value = datasetError(e)
      pollFailed.value = true
    }
  }
}
async function submit(kind: DatasetJob['operation']) {
  if (busy.value || unknown.value || !canWrite.value || staleSelection.value)
    return
  error.value = ''
  if (kind === 'derive-check' && names.value.length && names.value.every(row => row.target === null)) {
    error.value = label('至少保留一个目标类别。', 'Keep at least one target class.')
    return
  }
  if (
    kind === 'derive-check' &&
    (names.value.some((row) => !row.name.trim()) ||
      new Set(names.value.map((row) => row.name.trim().toLowerCase())).size !==
        names.value.length ||
      (repartition.value &&
        (ratios.value.some((n) => !Number.isInteger(n) || n < 0) ||
          ratios.value.reduce((a, b) => a + b, 0) !== 100)))
  ) {
    error.value = label(
      '类别名称不能为空或重复，划分比例须合计 100%。',
      'Class names must be unique and non-empty. Split ratios must total 100%.',
    )
    return
  }
  if (kind === 'derive' && configSnapshot !== JSON.stringify(config.value)) {
    error.value = label(
      '配置已修改，请重新检查。',
      'Configuration changed. Check again.',
    )
    return
  }
  // 未确认请求继续使用同一 ID；查询暂时不存在也不能重复创建后台任务。
  requestId = String(route.query.request || '') || crypto.randomUUID()
  busy.value = true
  try {
    await router.replace({
      query: { ...route.query, request: requestId, task: undefined },
    })
    const response = await submitDatasetJob(dataset, version, {
      request_id: requestId,
      operation: kind,
      expected_content_revision: String(
        workspace.value?.metadata.content_revision || '',
      ),
      config: config.value,
      compare_version_id: kind === 'compare' ? compareVersion.value : null,
      checked_task_id: kind === 'derive' ? checked.value : null,
    })
    if (!active) return
    configSnapshot = JSON.stringify(config.value)
    await router.replace({
      query: { ...route.query, compare: kind === 'compare' ? compareVersion.value : undefined, request: undefined, task: response.task_id },
    })
    await loadJob(response.task_id)
  } catch (e) {
    if (active) {
      error.value = datasetError(e)
      unknown.value = !(e instanceof ApiError) || e.status >= 500
    }
  } finally {
    if (active) busy.value = false
  }
}
async function resolveUnknown() {
  busy.value = true
  try {
    const result = await findDatasetJob(dataset, version, requestId)
    if (!active) return
    unknown.value = false
    error.value = ''
    configSnapshot = JSON.stringify(config.value)
    await router.replace({
      query: { ...route.query, request: undefined, task: result.task_id },
    })
    await loadJob(result.task_id)
    restoreConfig()
  } catch (e) {
    if (!active) return
    if (e instanceof ApiError && e.status === 404) {
      unknown.value = false
      error.value = label(
        '未找到本次提交，可以重新提交。',
        'This request was not received. You can submit again.',
      )
    } else error.value = datasetError(e)
  } finally {
    if (active) busy.value = false
  }
}
async function cancel() {
  if (!job.value) return
  const accepted = await feedback.confirm({
    title: label('取消数据集操作', 'Cancel dataset operation'),
    message: label(
      '保留来源版本，停止本次检查或创建。',
      'Keep the source version and stop this operation.',
    ),
    confirmText: text('cancel'),
    cancelText: label('继续执行', 'Keep running'),
  })
  if (!accepted) return
  busy.value = true
  try {
    await cancelDatasetJob(dataset, version, job.value.task_id)
    await loadJob(job.value.task_id)
  } catch (e) {
    error.value = datasetError(e)
    await loadJob(job.value.task_id)
  } finally {
    busy.value = false
  }
}
function editConfig() {
  job.value = null
  checked.value = ''
  router.replace({ query: { ...route.query, task: undefined } })
}
async function loadVersions() {
  if (!workspace.value) return
  const generation = ++versionGeneration
  try {
    const page = await listDatasetVersionPage({
      project_id: workspace.value.project_id,
      dataset_id: dataset,
      q: versionQuery.value,
      offset: versionOffset.value,
      limit: 20,
    })
    if (active && generation === versionGeneration) {
      versions.value = page.items
      versionTotal.value = page.total
    }
  } catch (e) {
    if (active && generation === versionGeneration)
      error.value = datasetError(e)
  }
}
function pageVersions(delta: number) {
  versionOffset.value += delta
  loadVersions()
}
function searchVersions() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    versionOffset.value = 0
    loadVersions()
  }, 250)
}
const dirty = computed(
  () =>
    operation === 'derive' &&
    !!workspace.value &&
    (!job.value || job.value.operation === 'derive-check') &&
    !loading.value &&
    JSON.stringify(config.value) !== formSnapshot,
)
const confirmLeave = async () =>
  !busy.value &&
  (unknown.value
    ? await feedback.confirm({
        title: label('提交结果待确认', 'Submission unconfirmed'),
        message: label(
          '离开不会取消后台操作。',
          'Leaving does not cancel the operation.',
        ),
        confirmText: text('back'),
        cancelText: text('cancel'),
      })
    : !dirty.value ||
      (await feedback.confirm({
        title: text('discard'),
        message: text('unsaved'),
        confirmText: text('discard'),
        cancelText: text('cancel'),
      })))
onBeforeRouteLeave(confirmLeave)
onBeforeRouteUpdate((to, from) => to.path === from.path || confirmLeave())
watch(
  () => route.query.task,
  async (id) => {
    if (busy.value || loading.value) return
    clearTimeout(timer)
    if (id) {
      await loadJob(String(id))
      restoreConfig()
    } else {
      job.value = null
      checked.value = ''
    }
  },
)
function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value || busy.value || unknown.value) {
    event.preventDefault()
    event.returnValue = ''
  }
}
const initializationFailed = ref(false)
async function initialize() {
  loading.value = true
  initializationFailed.value = false
  error.value = ''
  try {
    if (
      !['quality', 'derive', 'compare'].includes(operation) &&
      !(operation === 'return' && route.query.task)
    )
      throw new Error('Unknown operation')
    workspace.value = await getDatasetWorkspace(dataset, version)
    if (!active) return
    names.value = workspace.value.categories.map((c) => ({
      id: c.category_id,
      source: c.name,
      name: c.name,
      target: c.category_id,
    }))
    const state = history.state.datasetSelection
    // 历史任务使用当时的配置与统计，不用当前数据重新解释旧选择。
    if (!route.query.task && !requestId && state?.version === version) {
      if (
        state.revision !== undefined &&
        state.revision !==
          String(workspace.value.metadata.content_revision || '')
      ) {
        staleSelection.value = true
        throw new Error(
          label(
            '当前版本已更新，请返回重新选择样本。',
            'This version has changed. Go back and select samples again.',
          ),
        )
      }
      selection.value = state.selection
      selectionCount.value = (
        await getDatasetSelectionSummary(dataset, version, selection.value!)
      ).sample_count
    }
    formSnapshot = JSON.stringify(config.value)
    if (operation === 'compare') await loadVersions()
    if (route.query.task) {
      await loadJob(String(route.query.task))
      restoreConfig()
    } else if (requestId) {
      unknown.value = true
      await resolveUnknown()
    }
  } catch (e) {
    if (active) {
      initializationFailed.value = true
      error.value = datasetError(e)
    }
  } finally {
    if (active) loading.value = false
  }
}
onMounted(() => {
  window.addEventListener('beforeunload', beforeUnload)
  void initialize()
})
function restoreConfig() {
  if (job.value?.operation === 'compare' && job.value.result?.compare_version_id)
    compareVersion.value = job.value.result.compare_version_id
  const saved = job.value?.config
  if (!saved) return
  selection.value = saved.selection ?? undefined
  names.value = names.value.map((row) => ({
    ...row,
    name: saved.category_names?.[row.id] ?? row.source,
    target: saved.category_mapping && Object.hasOwn(saved.category_mapping, row.id) ? saved.category_mapping[row.id] : row.id,
  }))
  repartition.value = !!saved.split_ratios
  ratios.value = saved.split_ratios ?? [80, 20, 0]
  seed.value = saved.seed ?? 42
  description.value = saved.description ?? ''
  // 历史分组预检查必须返回配置重新检查，不能复用为按样本划分的创建凭据。
  configSnapshot = JSON.stringify({ ...config.value, group_key: saved.group_key ?? '' })
  formSnapshot = JSON.stringify(config.value)
  selectionCount.value = job.value?.result?.sample_count
}
onBeforeUnmount(() => {
  active = false
  clearTimeout(timer)
  clearTimeout(searchTimer)
  window.removeEventListener('beforeunload', beforeUnload)
})
</script>
<style scoped>
.dataset-config {
  display: grid;
  gap: 16px;
}
.dataset-compare-status { display: grid; gap: 20px; }
.dataset-operation--compare > .dataset-heading { justify-content: flex-start; gap: 20px; }
.dataset-operation--compare > .dataset-heading > .dataset-actions { flex: initial; }
.dataset-operation--compare > .dataset-heading > span { color: var(--am-text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dataset-review-actions {
  justify-content: space-between;
}
.dataset-config > h2 {
  margin: 0;
}
.dataset-split-config {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
.dataset-split-config label {
  display: grid;
  gap: 6px;
  max-width: 180px;
}
.dataset-config-fields {
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
  display: grid;
  gap: 16px;
}
.dataset-operation--derive .dataset-config-fields { gap: 0; }
.dataset-config-fields > .dataset-details {
  margin: 0;
  grid-template-columns: auto 1fr auto 1fr;
}
.dataset-config-fields > h2 {
  margin: 0;
}
.dataset-config input:not([type='radio']):not([type='checkbox']),
.dataset-config textarea {
  width: 100%;
  min-width: 0;
}
.dataset-config .field {
  min-width: 0;
}
.dataset-config td.field {
  display: table-cell;
}
.dataset-config p {
  margin: 0;
}
.dataset-config > .dataset-details {
  grid-template-columns: auto minmax(0, 1fr) auto minmax(0, 1fr);
}
</style>
