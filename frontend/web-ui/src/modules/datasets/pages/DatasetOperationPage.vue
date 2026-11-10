<template>
  <section class="dataset-workspace dataset-operation">
    <div class="dataset-heading">
      <div class="dataset-actions">
        <Button @click="back"
          ><ArrowLeft :size="16" />{{ text('back') }}</Button
        >
        <h1 class="dataset-title">{{ title }}</h1>
      </div>
      <span v-if="workspace">{{ workspace.dataset.display_name }}</span>
    </div>
    <InlineError v-if="error" :message="error" />
    <Button v-if="error && !loading && (!workspace || (initializationFailed && !staleSelection) || (pollFailed && !job))" @click="initialize">{{
      text('retry')
    }}</Button>
    <ol
      v-if="operation === 'derive'"
      class="dataset-steps"
      :aria-label="label('操作步骤', 'Steps')"
    >
      <li :class="{ 'is-active': !job, 'is-complete': !!job }">
        <span>1</span>{{ label('配置变更', 'Configure changes') }}
      </li>
      <li :class="{ 'is-active': !!job }">
        <span>2</span>{{ label('检查并创建', 'Review and create') }}
      </li>
    </ol>
    <p v-if="loading">{{ text('loading') }}</p>
    <template v-if="workspace && !loading && (!initializationFailed || staleSelection)">
      <form
        v-if="operation === 'derive' && !checked && !job && !route.query.task"
        class="resource-section dataset-config"
        @submit.prevent="submit('derive-check')"
      >
        <fieldset class="dataset-config-fields" :disabled="busy || unknown">
          <h2>{{ label('来源与范围', 'Source and range') }}</h2>
          <dl class="dataset-details">
            <dt>{{ text('version') }}</dt>
            <dd :title="version">
              {{ workspace ? `v${workspace.version_number}` : '—' }}
            </dd>
            <dt>{{ text('samples') }}</dt>
            <dd>{{ selectionCount ?? workspace.sample_count }}</dd>
          </dl>
          <h2>{{ label('类别名称', 'Class names') }}</h2>
          <ResourceTable class="dataset-table" :label="text('classes')"
            ><thead>
              <tr>
                <th>{{ label('来源名称', 'Source name') }}</th>
                <th>{{ label('新类别名称', 'New class name') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in names" :key="row.id">
                <td>{{ row.source }}</td>
                <td class="field">
                  <input
                    v-model="row.name"
                    maxlength="255"
                    :aria-label="`${label('新类别名称', 'New class name')} ${row.source}`"
                  />
                </td>
              </tr></tbody
          ></ResourceTable>
          <h2>{{ text('splits') }}</h2>
          <div class="dataset-actions">
            <label class="dataset-checkbox"
              ><input
                v-model="repartition"
                type="radio"
                :value="false"
                name="partition"
              />{{ label('保留原划分', 'Keep existing splits') }}</label
            >
            <label class="dataset-checkbox"
              ><input
                v-model="repartition"
                type="radio"
                :value="true"
                name="partition"
              />{{ label('重新划分', 'Repartition') }}</label
            >
          </div>
          <div v-if="repartition" class="dataset-split-config">
            <label
              v-for="(split, i) in ['train', 'val', 'test']"
              :key="split"
              class="field"
              >{{ split }} %<input
                v-model.number="ratios[i]"
                type="number"
                min="0"
                max="100"
                step="1" /></label
            ><label class="field"
              >{{ label('随机种子', 'Seed')
              }}<input
                v-model.number="seed"
                type="number"
                min="0"
                max="2147483647"
                step="1" /></label
            ><label class="field"
              >{{ label('分组字段（可选）', 'Grouping field (optional)')
              }}<input v-model="groupKey" maxlength="100"
            /></label>
          </div>
          <p v-if="repartition" class="dataset-muted">
            {{ label('比例合计', 'Total') }}
            {{ ratios.reduce((sum, value) => sum + Number(value || 0), 0) }}%
          </p>
          <label class="field"
            >{{ label('版本说明（可选）', 'Version notes (optional)')
            }}<textarea v-model="description" rows="3" maxlength="500" />
          </label>
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
      <section
        v-if="operation === 'compare' && !job && !route.query.task"
        class="resource-section dataset-config"
      >
        <h2>{{ label('选择比较版本', 'Choose a comparison version') }}</h2>
        <label class="field"
          ><input
            v-model="versionQuery"
            :aria-label="label('搜索版本', 'Search versions')"
            @input="searchVersions" /></label
        ><SelectField
          v-model="compareVersion"
          :options="versionOptions"
        /><PaginationControls
          v-if="versionTotal > 20"
          :offset="versionOffset"
          :limit="20"
          :item-count="versions.length"
          :total-count="versionTotal"
          @previous="pageVersions(-20)"
          @next="pageVersions(20)"
        /><Button
          variant="primary"
          :loading="busy"
          :disabled="!canWrite || !compareVersion || unknown"
          @click="submit('compare')"
          >{{ label('开始比较', 'Compare') }}</Button
        >
      </section>
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
      <section v-if="job" class="resource-section">
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
              label('返回修改', 'Edit configuration')
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
import { ArrowLeft } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { ApiError } from '@/shared/api/error'
import { useSessionStore } from '@/app/stores/session.store'
import DatasetJobResult from '../components/DatasetJobResult.vue'
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
const names = ref<{ id: number; source: string; name: string }[]>([]),
  repartition = ref(false),
  ratios = ref([80, 20, 0]),
  seed = ref(42),
  groupKey = ref(''),
  description = ref(''),
  staleSelection = ref(false),
  pollFailed = ref(false),
  selection = ref<DatasetSampleSelection>(),
  selectionCount = ref<number>()
const compareVersion = ref(String(route.query.compare || '')),
  versions = ref<DatasetVersion[]>([]),
  versionOffset = ref(0),
  versionTotal = ref(0),
  versionQuery = ref('')
const versionOptions = computed(() => [
  { value: '', label: label('选择版本', 'Select version') },
  ...versions.value
    .filter((v) => v.dataset_version_id !== version)
    .map((v) => ({
      value: v.dataset_version_id,
      label: `v${v.version_number} · ${v.sample_count} ${text('samples')}`,
    })),
])
const config = computed(() => ({
  selection: selection.value ?? null,
  category_names: Object.fromEntries(
    names.value.map((row) => [row.id, row.name.trim()]),
  ),
  split_ratios: repartition.value ? ratios.value : null,
  seed: seed.value,
  group_key: repartition.value ? groupKey.value.trim() : '',
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
  router.push(
    `/datasets/${encodeURIComponent(dataset)}/versions/${encodeURIComponent(id)}`,
  )
}
function viewSample(id: string, target?: string) {
  router.push({
    path: `/datasets/${encodeURIComponent(dataset)}/versions/${encodeURIComponent(target || version)}`,
    query: { sample: id },
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
      query: { ...route.query, request: undefined, task: response.task_id },
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
  const saved = job.value?.config
  if (!saved) return
  selection.value = saved.selection ?? undefined
  names.value = names.value.map((row) => ({
    ...row,
    name: saved.category_names?.[row.id] ?? row.source,
  }))
  repartition.value = !!saved.split_ratios
  ratios.value = saved.split_ratios ?? [80, 20, 0]
  seed.value = saved.seed ?? 42
  groupKey.value = saved.group_key ?? ''
  description.value = saved.description ?? ''
  configSnapshot = JSON.stringify(config.value)
  formSnapshot = configSnapshot
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
