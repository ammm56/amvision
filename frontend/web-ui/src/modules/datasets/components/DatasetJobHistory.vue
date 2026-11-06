<template>
  <section class="resource-section">
    <div class="dataset-heading">
      <h2>{{ label('工作区操作', 'Workspace operations') }}</h2>
      <Button :loading="loading" @click="load">{{ text('refresh') }}</Button>
    </div>
    <InlineError v-if="error" :message="error" />
    <ResourceTable
      v-if="rows.length"
      class="dataset-table"
      :label="label('工作区操作', 'Workspace operations')"
      ><thead>
        <tr>
          <th>{{ label('操作', 'Operation') }}</th>
          <th>{{ text('created') }}</th>
          <th>{{ text('state') }}</th>
          <th>{{ text('actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.task_id">
          <td>{{ operationName(row.operation) }}</td>
          <td>{{ datasetDate(row.created_at) }}</td>
          <td>
            <StatusBadge
              :status="row.state"
              :label="text(row.state)"
              :tone="row.state === 'cancelled' ? 'neutral' : undefined"
            />
          </td>
          <td>
            <Button size="sm" @click="view(row)">{{ text('view') }}</Button>
          </td>
        </tr>
      </tbody></ResourceTable
    >
    <p v-else-if="!loading" class="dataset-muted">
      {{ label('暂无检查或版本操作', 'No workspace operations yet') }}
    </p>
    <PaginationControls
      v-if="total > 20"
      :offset="offset"
      :limit="20"
      :item-count="rows.length"
      :total-count="total"
      @previous="page(-20)"
      @next="page(20)"
    />
  </section>
</template>
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Button from '@/shared/ui/components/Button.vue'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { datasetDate, datasetError, useDatasetText } from '../dataset-workspace'
import {
  listDatasetJobs,
  type DatasetJob,
  type DatasetWorkspace,
} from '../services/dataset-workspace.service'
const props = defineProps<{ workspace: DatasetWorkspace }>(),
  router = useRouter(),
  { locale } = useI18n(),
  text = useDatasetText()
const label = (zh: string, en: string) =>
  locale.value.startsWith('zh') ? zh : en
const rows = ref<DatasetJob[]>([]),
  total = ref(0),
  offset = ref(0),
  loading = ref(false),
  error = ref('')
const operationName = (kind: string) =>
  ({
    quality: label('质量检查', 'Quality checks'),
    'derive-check': label('版本预检查', 'Version preflight'),
    derive: label('创建新版本', 'Create version'),
    revise: label('更新样本', 'Update samples'),
    compare: label('版本比较', 'Compare versions'),
    'return-check': label('回传检查', 'Return checks'),
    'return-apply': label('创建回传版本', 'Create returned version'),
  })[kind] || kind
let active = true,
  generation = 0,
  timer: ReturnType<typeof setTimeout> | undefined
async function load() {
  clearTimeout(timer)
  const id = ++generation
  loading.value = true
  try {
    const page = await listDatasetJobs(
      props.workspace.dataset_id,
      props.workspace.dataset_version_id,
      offset.value,
    )
    if (active && id === generation) {
      rows.value = page.items
      total.value = page.total
      error.value = ''
      if (page.items.some((row) => ['queued', 'running'].includes(row.state)))
        timer = setTimeout(load, 2500)
    }
  } catch (e) {
    if (active && id === generation) error.value = datasetError(e)
  } finally {
    if (active && id === generation) loading.value = false
  }
}
function view(job: DatasetJob) {
  router.push({
    path: `/datasets/${encodeURIComponent(props.workspace.dataset_id)}/versions/${encodeURIComponent(props.workspace.dataset_version_id)}/tools/${job.operation === 'revise' ? 'samples' : job.operation.startsWith('return-') ? 'return' : job.operation === 'derive-check' ? 'derive' : job.operation}`,
    query: { task: job.task_id },
  })
}
function page(delta: number) {
  offset.value += delta
  load()
}
onMounted(load)
onBeforeUnmount(() => {
  active = false
  clearTimeout(timer)
})
</script>
