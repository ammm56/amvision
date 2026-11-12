<template>
  <section class="dataset-workspace">
    <div class="dataset-heading">
      <div class="dataset-actions">
        <Button @click="back"
          ><ArrowLeft :size="16" />{{ text('back') }}</Button
        >
        <h1 class="dataset-title">
          {{
            removedCount
              ? label('删除样本', 'Remove samples')
              : label('添加样本', 'Add samples')
          }}
        </h1>
      </div>
      <span>{{ workspace?.dataset.display_name }}</span>
    </div>
    <InlineError v-if="error" :message="error" />
    <Button v-if="error && !loading && (!workspace || (initializationFailed && !staleSelection) || (pollFailed && !job))" @click="initialize">{{
      text('retry')
    }}</Button>
    <p v-if="loading" role="status">{{ text('loading') }}</p>
    <section
      v-if="workspace && !job && !unknown && !route.query.task && !loading && (!initializationFailed || staleSelection)"
      class="resource-section dataset-revision-form"
    >
      <dl class="dataset-details">
        <dt>{{ label('当前版本', 'Current version') }}</dt>
        <dd>v{{ workspace.version_number }}</dd>
        <dt>{{ label('现有样本', 'Existing samples') }}</dt>
        <dd>{{ workspace.sample_count }}</dd>
        <dt v-if="removedCount">
          {{ label('删除所选样本', 'Remove selected samples') }}
        </dt>
        <dd v-if="removedCount">
          {{ removedCount }}
          <Button size="sm" :disabled="busy" @click="clearRemoval">{{
            label('撤回删除', 'Undo removal')
          }}</Button>
        </dd>
      </dl>
      <ul v-if="removedNames.length" class="dataset-removal-list">
        <li v-for="(name, index) in removedNames" :key="index" :title="name">
          {{ name }}
        </li>
        <li v-if="removedCount > removedNames.length" class="dataset-muted">
          {{ label('等', 'and') }} {{ removedCount }} {{ text('samples') }}
        </li>
      </ul>
      <FilePicker
        v-model="packageFile"
        :disabled="busy || !canWrite"
        :label="
          label(
            removedCount ? '添加图片和标注 ZIP（可选）' : '图片和标注 ZIP',
            removedCount
              ? 'Add images and annotations ZIP (optional)'
              : 'Images and annotations ZIP',
          )
        "
        accept=".zip"
        icon="archive"
      />
      <label v-if="file" class="dataset-format-field"
        >{{ label('标注格式', 'Annotation format')
        }}<SelectField
          v-model="format"
          :options="formatOptions"
          :disabled="busy"
      /></label>
      <p class="dataset-muted">
        {{
          label(
            '直接更新当前版本。同名类别合并，同名文件作为新样本添加。',
            'Update this version. Matching class names are merged; matching filenames are added as separate samples.',
          )
        }}
      </p>
      <p v-if="removesAll" role="status">
        {{
          label(
            '已选择全部样本，请添加新的样本 ZIP 或撤回删除。',
            'All samples are selected. Add a ZIP with new samples or undo removal.',
          )
        }}
      </p>
      <div class="dataset-actions">
        <Button @click="back" :disabled="busy">{{ text('cancel') }}</Button
        ><Button
          variant="primary"
          :loading="busy"
          :disabled="
            !canWrite ||
            (!file && !removedCount) ||
            removesAll ||
            staleSelection
          "
          @click="submit"
          >{{ label('保存修改', 'Save changes') }}</Button
        >
      </div>
    </section>
    <section v-if="job" class="resource-section dataset-revision-form">
      <DatasetJobResult :job="job" @version="viewVersion" />
      <div class="dataset-actions">
        <Button
          v-if="['queued', 'running'].includes(job.state)"
          :loading="busy"
          @click="cancel"
          >{{ label('取消操作', 'Cancel operation') }}</Button
        ><Button
          v-if="['failed', 'cancelled', 'timed_out'].includes(job.state)"
          @click="edit"
          >{{ label('返回修改', 'Edit changes') }}</Button
        ><Button v-if="pollFailed" @click="loadJob(job.task_id)">{{
          text('refresh')
        }}</Button>
      </div>
    </section>
    <section v-if="unknown" class="resource-section dataset-revision-form">
      <p>
        {{
          label(
            '提交结果待确认，请先查看本次操作，避免重复提交。',
            'Submission is unconfirmed. Check this operation before submitting again.',
          )
        }}
      </p>
      <Button :loading="busy" @click="resolveUnknown">{{
        uploadUnknown
          ? label('查看导入记录', 'View import records')
          : label('查询提交结果', 'Check submission')
      }}</Button>
    </section>
    <ConfirmDialog
      v-if="confirmation"
      :title="confirmation.title"
      :message="confirmation.message"
      :confirm-label="confirmation.confirmText"
      :cancel-label="text('cancel')"
      confirm-variant="primary"
      @confirm="answer(true)"
      @cancel="answer(false)"
    />
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  onBeforeRouteLeave,
  onBeforeRouteUpdate,
  useRoute,
  useRouter,
} from 'vue-router'
import { ArrowLeft } from '@lucide/vue'
import { useSessionStore } from '@/app/stores/session.store'
import { ApiError } from '@/shared/api/error'
import Button from '@/shared/ui/components/Button.vue'
import FilePicker from '@/shared/ui/components/FilePicker.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import DatasetJobResult from '../components/DatasetJobResult.vue'
import { datasetError, useDatasetText } from '../dataset-workspace'
import {
  submitDatasetImport,
  type DatasetSampleSelection,
} from '../services/dataset.service'
import {
  cancelDatasetJob,
  findDatasetJob,
  getDatasetJob,
  getDatasetSelectionSummary,
  getDatasetWorkspace,
  submitDatasetJob,
  type DatasetJob,
  type DatasetWorkspace,
} from '../services/dataset-workspace.service'
import '../dataset-workspace.css'
const route = useRoute(),
  router = useRouter(),
  session = useSessionStore(),
  { locale } = useI18n(),
  text = useDatasetText()
const label = (zh: string, en: string) =>
  locale.value.startsWith('zh') ? zh : en
const dataset = String(route.params.datasetId),
  version = String(route.params.versionId)
const workspace = ref<DatasetWorkspace | null>(null),
  loading = ref(true),
  busy = ref(false),
  error = ref(''),
  submitted = ref(false)
const packageFile = ref<File | File[] | null>(null),
  file = computed(() =>
    Array.isArray(packageFile.value) ? packageFile.value[0] : packageFile.value,
  )
const selection = ref<DatasetSampleSelection>(),
  staleSelection = ref(false),
  removedNames = ref<string[]>([]),
  removedCount = ref(0),
  format = ref(''),
  job = ref<DatasetJob | null>(null)
const unknown = ref(false),
  uploadUnknown = ref(false),
  pollFailed = ref(false)
const canWrite = computed(() => session.hasScopes(['datasets:write']))
const removesAll = computed(
  () =>
    !file.value &&
    removedCount.value > 0 &&
    removedCount.value >= (workspace.value?.sample_count || 0),
)
const formatOptions = computed(() => [
  { value: '', label: label('自动识别', 'Auto detect') },
  ...(
    (
      (session.bootstrap?.capabilities?.dataset_import
        ?.format_types_by_task_type || {}) as Record<string, string[]>
    )[workspace.value?.task_type || ''] || []
  ).map((value) => ({ value, label: value.toUpperCase() })),
])
let active = true,
  timer: ReturnType<typeof setTimeout> | undefined,
  requestId = String(route.query.request || '')
const confirmation = ref<{
  title: string
  message: string
  confirmText: string
} | null>(null)
let confirmResolve: ((value: boolean) => void) | undefined
function ask(value: NonNullable<typeof confirmation.value>) {
  confirmation.value = value
  return new Promise<boolean>((resolve) => {
    confirmResolve = resolve
  })
}
function answer(value: boolean) {
  confirmation.value = null
  confirmResolve?.(value)
  confirmResolve = undefined
}
function clearRemoval() {
  selection.value = undefined
  removedCount.value = 0
  removedNames.value = []
}
function back() {
  return router.push(
    `/datasets/${encodeURIComponent(dataset)}/versions/${encodeURIComponent(version)}`,
  )
}
function viewVersion(id: string) {
  submitted.value = true
  return router.push(
    `/datasets/${encodeURIComponent(dataset)}/versions/${encodeURIComponent(id)}`,
  )
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
    if (['queued', 'running'].includes(result.state))
      timer = setTimeout(() => loadJob(id), 1500)
  } catch (e) {
    if (active) {
      error.value = datasetError(e)
      pollFailed.value = true
    }
  }
}
async function submit() {
  if (
    busy.value ||
    unknown.value ||
    !canWrite.value ||
    !workspace.value ||
    removesAll.value ||
    staleSelection.value ||
    (!file.value && !removedCount.value)
  )
    return
  busy.value = true
  error.value = ''
  uploadUnknown.value = !!file.value
  try {
    if (file.value) {
      const result = await submitDatasetImport({
        projectId: workspace.value.project_id,
        datasetId: dataset,
        taskType: workspace.value.task_type,
        packageFile: file.value,
        formatType: format.value || undefined,
        baseVersionId: version,
        expectedContentRevision: String(
          workspace.value.metadata.content_revision || '',
        ),
        excludeSelection: selection.value,
      })
      submitted.value = true
      busy.value = false
      await router.push(`/datasets/imports/${result.dataset_import_id}`)
    } else {
      requestId ||= crypto.randomUUID()
      await router.replace({ query: { request: requestId } })
      const result = await submitDatasetJob(dataset, version, {
        request_id: requestId,
        operation: 'revise',
        expected_content_revision: String(
          workspace.value.metadata.content_revision || '',
        ),
        config: { exclude_selection: selection.value },
      })
      submitted.value = true
      await router.replace({ query: { task: result.task_id } })
      await loadJob(result.task_id)
    }
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
  if (uploadUnknown.value) {
    submitted.value = true
    unknown.value = false
    return router.push({
      path: '/datasets',
      query: { tab: 'imports', q: dataset },
    })
  }
  busy.value = true
  try {
    const result = await findDatasetJob(dataset, version, requestId)
    if (!active) return
    unknown.value = false
    submitted.value = true
    await router.replace({ query: { task: result.task_id } })
    await loadJob(result.task_id)
  } catch (e) {
    if (!active) return
    if (e instanceof ApiError && e.status === 404) {
      unknown.value = false
      error.value = label(
        '未找到本次提交，可以重新提交。',
        'This request was not found. You can submit again.',
      )
    } else error.value = datasetError(e)
  } finally {
    if (active) busy.value = false
  }
}
async function cancel() {
  if (
    !job.value ||
    !(await ask({
      title: label('取消更新样本', 'Cancel sample update'),
      message: label(
        '停止本次更新，保留修改前的数据。',
        'Stop this update and keep the previous data.',
      ),
      confirmText: label('确认取消', 'Cancel operation'),
    }))
  )
    return
  busy.value = true
  try {
    await cancelDatasetJob(dataset, version, job.value.task_id)
    await loadJob(job.value.task_id)
  } catch (e) {
    error.value = datasetError(e)
  } finally {
    busy.value = false
  }
}
function edit() {
  selection.value = job.value?.config?.exclude_selection
  job.value = null
  submitted.value = false
  requestId = ''
  void router.replace({ query: {} })
}
const dirty = computed(
  () => !submitted.value && (!!file.value || removedCount.value > 0),
)
async function leave() {
  if (busy.value) return false
  if (!dirty.value && !unknown.value) return true
  return ask({
    title: text('discard'),
    message: unknown.value
      ? label(
          '提交结果尚未确认，离开不会取消后台操作。',
          'Submission is unconfirmed. Leaving does not cancel the operation.',
        )
      : text('unsaved'),
    confirmText: text('discard'),
  })
}
onBeforeRouteLeave(leave)
onBeforeRouteUpdate((to, from) => to.path === from.path || leave())
function unload(event: BeforeUnloadEvent) {
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
    const source = await getDatasetWorkspace(dataset, version)
    if (!active) return
    workspace.value = source
    const saved = history.state.datasetSelection
    if (!route.query.task && !requestId && saved?.version === version) {
      if (
        saved.revision !== undefined &&
        saved.revision !== String(source.metadata.content_revision || '')
      ) {
        staleSelection.value = true
        throw new Error(
          label(
            '当前版本已更新，请返回重新选择样本。',
            'This version has changed. Go back and select samples again.',
          ),
        )
      }
      selection.value = saved.selection
      removedNames.value = Array.isArray(saved.names)
        ? saved.names.slice(0, 8)
        : []
      removedCount.value = (
        await getDatasetSelectionSummary(dataset, version, saved.selection)
      ).sample_count
    }
    if (route.query.task) {
      submitted.value = true
      await loadJob(String(route.query.task))
      selection.value = job.value?.config?.exclude_selection
      if (job.value?.state === 'succeeded')
        removedCount.value = Number(job.value.result?.excluded_count || 0)
      else if (selection.value)
        removedCount.value = (
          await getDatasetSelectionSummary(dataset, version, selection.value)
        ).sample_count
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
  window.addEventListener('beforeunload', unload)
  void initialize()
})
onBeforeUnmount(() => {
  active = false
  clearTimeout(timer)
  answer(false)
  window.removeEventListener('beforeunload', unload)
})
</script>
<style scoped>
.dataset-revision-form {
  display: grid;
  gap: 20px;
  max-width: 920px;
  width: 100%;
  box-sizing: border-box;
}
.dataset-revision-form > p {
  margin: 0;
}
.dataset-revision-form > .dataset-actions {
  justify-content: flex-end;
}
.dataset-format-field {
  display: grid;
  gap: 8px;
  max-width: 320px;
}
.dataset-removal-list {
  margin: 0;
  padding: 12px 16px;
  list-style: none;
  background: var(--am-surface-soft);
  border-radius: var(--am-radius-sm);
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 20px;
}
.dataset-removal-list li {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
</style>
