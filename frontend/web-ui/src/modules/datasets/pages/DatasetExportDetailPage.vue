<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">数据集导出详情</p>
        <h1>{{ datasetExportId }}</h1>
        <p class="page-description">查看数据集导出格式、下载包、运行磁盘数据和附加元数据。</p>
      </div>
      <div class="page-actions">
        <RouterLink to="/datasets">返回数据集页</RouterLink>
        <Button
          v-if="detail"
          variant="secondary"
          :disabled="packaging || !canWriteDatasets"
          @click="packageCurrentExport"
        >
          <PackageCheck :size="16" />
          打包
        </Button>
        <Button
          v-if="detail"
          variant="secondary"
          :disabled="!detail.package_object_key || downloading"
          @click="downloadCurrentExport"
        >
          <Download :size="16" />
          下载
        </Button>
        <Button
          v-if="detail"
          variant="danger"
          :disabled="!canDeleteCurrentExport || deleting"
          @click="deleteDialogOpen = true"
        >
          <Trash2 :size="16" />
          删除导出记录
        </Button>
        <Button variant="secondary" :disabled="loading" @click="loadDetail">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </div>
    </header>

    <InlineError :message="errorMessage" />

    <section v-if="detail" class="resource-section">
      <div class="section-heading">
        <div>
          <p class="page-kicker">Summary</p>
          <h2>导出摘要</h2>
        </div>
        <StatusBadge :tone="statusTone(detail.status)">{{ detail.status }}</StatusBadge>
      </div>
      <div class="summary-grid">
        <div>
          <span>Project id</span>
          <strong>{{ detail.project_id }}</strong>
        </div>
        <div>
          <span>Dataset id</span>
          <strong>{{ detail.dataset_id }}</strong>
        </div>
        <div>
          <span>DatasetVersion id</span>
          <strong>{{ detail.dataset_version_id }}</strong>
        </div>
        <div>
          <span>任务类型</span>
          <strong>{{ detail.task_type }}</strong>
        </div>
      </div>
      <div class="summary-grid">
        <div>
          <span>导出格式</span>
          <strong>{{ detail.format_id }}</strong>
        </div>
        <div>
          <span>样本数</span>
          <strong>{{ detail.sample_count }}</strong>
        </div>
        <div>
          <span>包含 test split</span>
          <strong>{{ detail.include_test_split ? '是' : '否' }}</strong>
        </div>
        <div>
          <span>创建时间</span>
          <strong>{{ formatSystemDateTime(detail.created_at) }}</strong>
        </div>
      </div>
      <InlineError :message="detail.error_message ?? null" />
    </section>

    <section v-if="detail" class="operation-grid">
      <article class="resource-section">
        <div>
          <p class="page-kicker">Package</p>
          <h2>下载包</h2>
        </div>
        <div class="summary-list">
          <div>
            <span>文件名</span>
            <strong>{{ detail.package_file_name || '-' }}</strong>
          </div>
          <div>
            <span>文件 object key</span>
            <strong>{{ detail.package_object_key || '-' }}</strong>
          </div>
          <div>
            <span>文件大小</span>
            <strong>{{ detail.package_size ?? '-' }}</strong>
          </div>
          <div>
            <span>打包时间</span>
            <strong>{{ detail.packaged_at ? formatSystemDateTime(detail.packaged_at) : '-' }}</strong>
          </div>
        </div>
      </article>

      <article class="resource-section">
        <div>
          <p class="page-kicker">Runtime Data</p>
          <h2>运行磁盘数据</h2>
        </div>
        <div class="summary-list">
          <div>
            <span>导出目录</span>
            <strong>{{ detail.export_path || '-' }}</strong>
          </div>
          <div>
            <span>Manifest</span>
            <strong>{{ detail.manifest_object_key || '-' }}</strong>
          </div>
          <div>
            <span>Queue task</span>
            <strong>{{ detail.queue_task_id || '-' }}</strong>
          </div>
          <div>
            <span>Task</span>
            <RouterLink v-if="detail.task_id" :to="`/tasks/${detail.task_id}`">{{ detail.task_id }}</RouterLink>
            <strong v-else>-</strong>
          </div>
        </div>
      </article>

      <article class="resource-section">
        <div>
          <p class="page-kicker">Splits</p>
          <h2>Split 列表</h2>
        </div>
        <pre class="json-view">{{ splitNamesJson }}</pre>
      </article>

      <article class="resource-section">
        <div>
          <p class="page-kicker">Categories</p>
          <h2>类别列表</h2>
        </div>
        <pre class="json-view">{{ categoryNamesJson }}</pre>
      </article>

      <article class="resource-section">
        <div>
          <p class="page-kicker">Metadata</p>
          <h2>附加元数据</h2>
        </div>
        <pre class="json-view">{{ metadataJson }}</pre>
      </article>
    </section>

    <ConfirmDialog
      v-if="detail && deleteDialogOpen"
      kicker="删除"
      title="删除导出记录"
      :message="deleteDialogMessage"
      confirm-label="删除导出记录"
      :cancel-label="t('common.cancel')"
      :busy="deleting"
      confirm-variant="danger"
      @cancel="deleteDialogOpen = false"
      @confirm="deleteCurrentExport"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Download, PackageCheck, RefreshCw, Trash2 } from '@lucide/vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import {
  deleteDatasetExport,
  downloadDatasetExport,
  getDatasetExportDetail,
  packageDatasetExport,
  type DatasetExportDetail,
} from '../services/dataset.service'
import { useSessionStore } from '@/app/stores/session.store'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'

const route = useRoute()
const router = useRouter()
const sessionStore = useSessionStore()
const { t } = useI18n()

const detail = ref<DatasetExportDetail | null>(null)
const loading = ref(false)
const packaging = ref(false)
const downloading = ref(false)
const deleting = ref(false)
const deleteDialogOpen = ref(false)
const errorMessage = ref<string | null>(null)

const datasetExportId = computed(() => String(route.params.datasetExportId ?? ''))
const canWriteDatasets = computed(() => sessionStore.hasScopes(['datasets:write']))
const canDeleteCurrentExport = computed(() => {
  if (!detail.value || !canWriteDatasets.value) return false
  const normalized = String(detail.value.status || '').toLowerCase()
  return normalized === 'completed' || normalized === 'failed'
})
const deleteDialogMessage = computed(() => {
  if (!detail.value) return ''
  return `确认删除导出记录 ${detail.value.dataset_export_id}？这会删除关联任务记录、导出运行磁盘数据和下载包，不会删除 DatasetVersion ${detail.value.dataset_version_id}。此操作不可撤销。`
})
const splitNamesJson = computed(() => JSON.stringify(detail.value?.split_names ?? [], null, 2))
const categoryNamesJson = computed(() => JSON.stringify(detail.value?.category_names ?? [], null, 2))
const metadataJson = computed(() => JSON.stringify(detail.value?.metadata ?? {}, null, 2))

onMounted(() => {
  void loadDetail()
})

function statusTone(status: string | null | undefined): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  const normalized = String(status ?? '').toLowerCase()
  if (normalized.includes('complete') || normalized.includes('success') || normalized.includes('ready')) return 'success'
  if (normalized.includes('fail') || normalized.includes('error')) return 'danger'
  if (normalized.includes('queue') || normalized.includes('pending')) return 'warning'
  if (normalized.includes('run') || normalized.includes('process')) return 'info'
  return 'neutral'
}

async function loadDetail(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    detail.value = await getDatasetExportDetail(datasetExportId.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据集导出详情加载失败'
  } finally {
    loading.value = false
  }
}

async function packageCurrentExport(): Promise<void> {
  if (!detail.value || !canWriteDatasets.value) return

  packaging.value = true
  errorMessage.value = null
  try {
    const packageResult = await packageDatasetExport(detail.value.dataset_export_id)
    detail.value = { ...detail.value, ...packageResult }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据集导出打包失败'
  } finally {
    packaging.value = false
  }
}

async function downloadCurrentExport(): Promise<void> {
  if (!detail.value?.package_object_key) return

  downloading.value = true
  errorMessage.value = null
  try {
    const blob = await downloadDatasetExport(detail.value.dataset_export_id)
    const objectUrl = window.URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = objectUrl
    anchor.download = detail.value.package_file_name || `${detail.value.dataset_export_id}.zip`
    anchor.click()
    window.URL.revokeObjectURL(objectUrl)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据集导出下载失败'
  } finally {
    downloading.value = false
  }
}

async function deleteCurrentExport(): Promise<void> {
  if (!detail.value || !canDeleteCurrentExport.value) return

  deleting.value = true
  errorMessage.value = null
  try {
    await deleteDatasetExport(detail.value.dataset_export_id)
    await router.push('/datasets')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据集导出删除失败'
  } finally {
    deleting.value = false
    deleteDialogOpen.value = false
  }
}
</script>

<style scoped>
.summary-list {
  display: grid;
  gap: 12px;
}

.summary-list > div {
  display: grid;
  gap: 4px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line);
}

.summary-list span {
  color: var(--muted);
  font-weight: 700;
  font-size: 0.86rem;
}

.summary-list strong {
  overflow-wrap: anywhere;
}
</style>
