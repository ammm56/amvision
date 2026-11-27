<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="inf-picker-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="选择图片"
      @click.self="emit('close')"
    >
      <section class="inf-picker-modal">
        <header class="inf-picker-modal__header">
          <div class="inf-picker-modal__head-left">
            <h2>选择图片</h2>
            <div class="inf-picker-modal__tabs" role="tablist" aria-label="已有文件来源">
              <button
                type="button"
                role="tab"
                class="inf-picker-modal__tab"
                :class="{ 'is-active': activeKind === 'dataset' }"
                :aria-selected="activeKind === 'dataset'"
                @click="switchKind('dataset')"
              >
                数据集样本
              </button>
              <button
                type="button"
                role="tab"
                class="inf-picker-modal__tab"
                :class="{ 'is-active': activeKind === 'project' }"
                :aria-selected="activeKind === 'project'"
                @click="switchKind('project')"
              >
                项目文件
              </button>
            </div>
          </div>

          <button type="button" class="inf-picker-modal__close" aria-label="关闭" @click="emit('close')">
            <X :size="18" />
          </button>
        </header>

        <div class="inf-picker-modal__toolbar">
          <template v-if="activeKind === 'dataset'">
            <div class="inf-picker-filter inf-picker-filter--wide">
              <span>数据集</span>
              <SelectField
                :model-value="selectedDatasetId"
                :options="datasetOptions"
                placeholder="选择数据集"
                floating
                @update:model-value="selectDataset"
              />
            </div>

            <div v-if="selectedDatasetId" class="inf-picker-filter">
              <span>版本</span>
              <SelectField
                :model-value="selectedVersionId"
                :options="versionOptions"
                placeholder="选择版本"
                floating
                @update:model-value="selectVersion"
              />
            </div>

            <div v-if="selectedVersionId" class="inf-picker-filter">
              <span>划分</span>
              <SelectField
                :model-value="selectedSplit"
                :options="splitOptions"
                fit-options
                floating
                @update:model-value="selectSplit"
              />
            </div>

            <div class="inf-picker-search">
              <Search :size="15" />
              <input
                v-model="datasetQuery"
                type="text"
                placeholder="搜索样本文件名"
                @input="scheduleDatasetSearch"
                @keydown.enter.prevent="searchDatasetSamples"
              />
              <button v-if="datasetQuery" type="button" aria-label="清空搜索" @click="clearDatasetSearch">
                <X :size="13" />
              </button>
            </div>

            <div class="inf-picker-toolbar-right">
              <SelectField
                :model-value="datasetSort"
                :options="sortOptions"
                aria-label="排序"
                floating
                @update:model-value="selectSort"
              />
              <div class="inf-picker-view-toggle">
                <Button
                  size="sm"
                  icon-only
                  :variant="viewMode === 'grid' ? 'primary' : 'secondary'"
                  aria-label="网格视图"
                  @click="viewMode = 'grid'"
                >
                  <LayoutGrid :size="15" />
                </Button>
                <Button
                  size="sm"
                  icon-only
                  :variant="viewMode === 'list' ? 'primary' : 'secondary'"
                  aria-label="列表视图"
                  @click="viewMode = 'list'"
                >
                  <List :size="15" />
                </Button>
              </div>
            </div>
          </template>

          <template v-else>
            <div class="inf-picker-filter inf-picker-filter--wide">
              <span>目录范围</span>
              <SelectField
                :model-value="projectScope"
                :options="projectScopeOptions"
                floating
                @update:model-value="selectProjectScope"
              />
            </div>

            <div class="inf-picker-search inf-picker-search--flex">
              <Search :size="15" />
              <input
                v-model="projectQuery"
                type="text"
                placeholder="搜索文件名或相对路径"
                @input="projectOffset = 0"
              />
              <button v-if="projectQuery" type="button" aria-label="清空搜索" @click="projectQuery = ''; projectOffset = 0">
                <X :size="13" />
              </button>
            </div>

            <div class="inf-picker-toolbar-right">
              <Button size="sm" variant="secondary" :loading="projectFilesLoading" @click="loadProjectFiles">
                <RefreshCw :size="14" />
                刷新
              </Button>
              <div class="inf-picker-view-toggle">
                <Button
                  size="sm"
                  icon-only
                  :variant="viewMode === 'grid' ? 'primary' : 'secondary'"
                  aria-label="网格视图"
                  @click="viewMode = 'grid'"
                >
                  <LayoutGrid :size="15" />
                </Button>
                <Button
                  size="sm"
                  icon-only
                  :variant="viewMode === 'list' ? 'primary' : 'secondary'"
                  aria-label="列表视图"
                  @click="viewMode = 'list'"
                >
                  <List :size="15" />
                </Button>
              </div>
            </div>
          </template>
        </div>

        <div class="inf-picker-modal__body">
          <InlineError :message="localError" />

          <div v-if="loadingList" class="inf-picker-state">加载中...</div>

          <template v-else-if="activeKind === 'dataset'">
            <div v-if="!selectedDatasetId" class="inf-picker-state">当前项目暂无可用数据集</div>
            <div v-else-if="samples.length === 0" class="inf-picker-state">
              当前筛选条件下暂无样本图像
            </div>

            <div v-else-if="viewMode === 'grid'" class="inf-sample-grid">
              <article
                v-for="sample in samples"
                :key="sample.sample_id"
                class="inf-sample-card"
                :class="{ 'is-selected': draftSample?.sample_id === sample.sample_id }"
                @click="draftSample = sample"
                @dblclick="quickConfirmSample(sample)"
              >
                <span class="inf-sample-card__check" :class="{ 'is-checked': draftSample?.sample_id === sample.sample_id }">
                  <Check v-if="draftSample?.sample_id === sample.sample_id" :size="12" />
                </span>
                <div class="inf-sample-card__media">
                  <DatasetSampleImage
                    :dataset-id="selectedDatasetId"
                    :sample="sample"
                    :categories="[]"
                    :show-annotations="false"
                  />
                </div>
                <div class="inf-sample-card__caption">
                  <strong :title="sample.file_name">{{ sample.file_name }}</strong>
                  <small>{{ sample.split }} · {{ sample.width }} × {{ sample.height }}</small>
                </div>
              </article>
            </div>

            <table v-else class="inf-picker-table">
              <thead>
                <tr>
                  <th class="col-radio" />
                  <th class="col-thumb">缩略图</th>
                  <th>文件名</th>
                  <th class="col-dims">尺寸</th>
                  <th class="col-split">划分</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="sample in samples"
                  :key="sample.sample_id"
                  :class="{ 'is-selected': draftSample?.sample_id === sample.sample_id }"
                  @click="draftSample = sample"
                  @dblclick="quickConfirmSample(sample)"
                >
                  <td class="col-radio">
                    <input
                      type="radio"
                      name="existing-dataset-sample"
                      :checked="draftSample?.sample_id === sample.sample_id"
                      @change="draftSample = sample"
                    />
                  </td>
                  <td class="col-thumb">
                    <div class="inf-list-thumb">
                      <DatasetSampleImage
                        :dataset-id="selectedDatasetId"
                        :sample="sample"
                        :categories="[]"
                        :show-annotations="false"
                      />
                    </div>
                  </td>
                  <td>
                    <strong class="inf-cell-title" :title="sample.file_name">{{ sample.file_name }}</strong>
                  </td>
                  <td class="col-dims">{{ sample.width }} × {{ sample.height }}</td>
                  <td class="col-split">{{ sample.split }}</td>
                </tr>
              </tbody>
            </table>
          </template>

          <template v-else>
            <div v-if="filteredProjectFiles.length === 0" class="inf-picker-state">
              <span>当前目录暂无图像文件</span>
              <Button
                v-if="projectScope !== 'all'"
                size="sm"
                variant="secondary"
                @click="selectProjectScope('all')"
              >
                查看全部公开文件
              </Button>
            </div>

            <div v-else-if="viewMode === 'grid'" class="inf-sample-grid">
              <article
                v-for="file in pagedProjectFiles"
                :key="file.file_id"
                class="inf-sample-card"
                :class="{ 'is-selected': draftProjectFile?.file_id === file.file_id }"
                @click="draftProjectFile = file"
                @dblclick="quickConfirmProjectFile(file)"
              >
                <span class="inf-sample-card__check" :class="{ 'is-checked': draftProjectFile?.file_id === file.file_id }">
                  <Check v-if="draftProjectFile?.file_id === file.file_id" :size="12" />
                </span>
                <div class="inf-sample-card__media inf-sample-card__media--file">
                  <img
                    v-if="projectThumbUrls[file.file_id]"
                    :src="projectThumbUrls[file.file_id]"
                    :alt="file.file_name"
                  />
                  <ImageIcon v-else :size="24" class="inf-thumb-placeholder" />
                </div>
                <div class="inf-sample-card__caption">
                  <strong :title="file.file_name">{{ file.file_name }}</strong>
                  <small :title="file.object_key">
                    {{ formatRelativeObjectKey(file.object_key) }} · {{ formatSize(file.size_bytes) }}
                  </small>
                </div>
              </article>
            </div>

            <table v-else class="inf-picker-table">
              <thead>
                <tr>
                  <th class="col-radio" />
                  <th class="col-thumb">缩略图</th>
                  <th>文件</th>
                  <th class="col-dims">大小</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="file in pagedProjectFiles"
                  :key="file.file_id"
                  :class="{ 'is-selected': draftProjectFile?.file_id === file.file_id }"
                  @click="draftProjectFile = file"
                  @dblclick="quickConfirmProjectFile(file)"
                >
                  <td class="col-radio">
                    <input
                      type="radio"
                      name="existing-project-file"
                      :checked="draftProjectFile?.file_id === file.file_id"
                      @change="draftProjectFile = file"
                    />
                  </td>
                  <td class="col-thumb">
                    <div class="inf-list-thumb">
                      <img
                        v-if="projectThumbUrls[file.file_id]"
                        :src="projectThumbUrls[file.file_id]"
                        :alt="file.file_name"
                      />
                      <ImageIcon v-else :size="16" class="inf-thumb-placeholder" />
                    </div>
                  </td>
                  <td>
                    <strong class="inf-cell-title" :title="file.file_name">{{ file.file_name }}</strong>
                    <small class="inf-cell-sub" :title="file.object_key">{{ formatRelativeObjectKey(file.object_key) }}</small>
                  </td>
                  <td class="col-dims">{{ formatSize(file.size_bytes) }}</td>
                </tr>
              </tbody>
            </table>
          </template>
        </div>

        <div v-if="showPaginationBar" class="inf-picker-modal__pagination">
          <PaginationControls
            numbered
            :offset="activeKind === 'dataset' ? datasetOffset : projectOffset"
            :limit="pageSize"
            :item-count="activeKind === 'dataset' ? samples.length : pagedProjectFiles.length"
            :total-count="activeKind === 'dataset' ? datasetTotal : filteredProjectFiles.length"
            :disabled="loadingList"
            @previous="goPage(activeKind === 'dataset' ? datasetOffset - pageSize : projectOffset - pageSize)"
            @next="goPage(activeKind === 'dataset' ? datasetOffset + pageSize : projectOffset + pageSize)"
            @go="goPage($event)"
          >
            <template #summary>
              <template v-if="activeKind === 'dataset'">
                共 {{ datasetTotal.toLocaleString() }} 张图像，每页 {{ pageSize }} 条
              </template>
              <template v-else>
                共 {{ filteredProjectFiles.length.toLocaleString() }} 个图像文件，每页 {{ pageSize }} 条
              </template>
            </template>
          </PaginationControls>

          <div class="inf-picker-pagesize">
            <SelectField
              :model-value="String(pageSize)"
              :options="pageSizeOptions"
              aria-label="每页数量"
              floating
              @update:model-value="changePageSize"
            />
          </div>
        </div>

        <footer class="inf-picker-modal__footer">
          <span class="inf-picker-modal__selection">{{ selectionSummaryText }}</span>
          <div class="inf-picker-modal__actions">
            <Button variant="secondary" @click="emit('close')">取消</Button>
            <Button
              variant="primary"
              :disabled="!hasDraftSelection || confirming"
              :loading="confirming"
              @click="confirmSelection"
            >
              使用图片
            </Button>
          </div>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Check, Image as ImageIcon, LayoutGrid, List, RefreshCw, Search, X } from '@lucide/vue'

import DatasetSampleImage from '@/modules/datasets/components/DatasetSampleImage.vue'
import {
  getDatasetImage,
  listDatasetCatalog,
  listDatasetSamples,
  listDatasetVersionPage,
  type DatasetItem,
  type DatasetSample,
  type DatasetVersion,
} from '@/modules/datasets/services/dataset-workspace.service'
import Button from '@/shared/ui/components/Button.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import {
  fetchAuthorizedProjectFileBlob,
  getDatasetSampleFileRef,
  listProjectPublicFiles,
  type ProjectPublicFileEntry,
} from '../services/inference.service'

const IMAGE_EXT_REGEX = /\.(jpe?g|png|webp|bmp)$/i

export interface ExistingFileSelectionResult {
  fileId: string
  label: string
  previewUrl: string | null
  width?: number | null
  height?: number | null
  sizeBytes?: number | null
  sourceMeta?: string
}

const props = defineProps<{
  open: boolean
  projectId: string
  selectedFileId?: string
}>()

const emit = defineEmits<{
  close: []
  confirm: [payload: ExistingFileSelectionResult]
}>()

const activeKind = ref<'dataset' | 'project'>('dataset')
const viewMode = ref<'grid' | 'list'>('grid')
const pageSize = ref(16)
const localError = ref<string | null>(null)
const confirming = ref(false)

// 数据集样本浏览状态
const datasets = ref<DatasetItem[]>([])
const selectedDatasetId = ref('')
const versions = ref<DatasetVersion[]>([])
const selectedVersionId = ref('')
const selectedSplit = ref('')
const datasetQuery = ref('')
const datasetSort = ref('filename')
const datasetOffset = ref(0)
const datasetTotal = ref(0)
const samples = ref<DatasetSample[]>([])
const samplesLoading = ref(false)
const draftSample = ref<DatasetSample | null>(null)
let datasetSearchTimer: number | undefined

// 项目文件浏览状态
const projectScope = ref<'workspace' | 'inputs' | 'results' | 'all'>('workspace')
const projectFiles = ref<ProjectPublicFileEntry[]>([])
const projectFilesLoading = ref(false)
const projectQuery = ref('')
const projectOffset = ref(0)
const draftProjectFile = ref<ProjectPublicFileEntry | null>(null)
const projectThumbUrls = ref<Record<string, string>>({})
let thumbLoadGeneration = 0

const loadingList = computed(() =>
  activeKind.value === 'dataset' ? samplesLoading.value : projectFilesLoading.value,
)

const datasetOptions = computed(() =>
  datasets.value.map((item) => ({
    label: item.display_name || item.dataset_id,
    value: item.dataset_id,
  })),
)

const versionOptions = computed(() =>
  versions.value.map((item) => ({
    label: `v${item.version_number} (${item.sample_count})`,
    value: item.dataset_version_id,
  })),
)

const splitOptions = [
  { label: '全部划分', value: '' },
  { label: 'train', value: 'train' },
  { label: 'val', value: 'val' },
  { label: 'test', value: 'test' },
]

const sortOptions = [
  { label: '文件名升序', value: 'filename' },
  { label: '文件名降序', value: 'filename_desc' },
  { label: '导入顺序', value: 'image_id' },
]

const projectScopeOptions = [
  { label: '项目输入与结果', value: 'workspace' },
  { label: '项目输入 (inputs)', value: 'inputs' },
  { label: '推理与结果 (results)', value: 'results' },
  { label: '全部公开文件', value: 'all' },
]

const pageSizeOptions = [12, 16, 24, 48].map((n) => ({
  value: String(n),
  label: `${n} 条/页`,
}))

const filteredProjectFiles = computed(() => {
  const kw = projectQuery.value.trim().toLowerCase()
  return projectFiles.value.filter((entry) => {
    const isImage =
      entry.media_type.startsWith('image/') || IMAGE_EXT_REGEX.test(entry.object_key)
    if (!isImage) return false
    if (!kw) return true
    return (
      entry.file_name.toLowerCase().includes(kw) ||
      entry.object_key.toLowerCase().includes(kw)
    )
  })
})

const pagedProjectFiles = computed(() =>
  filteredProjectFiles.value.slice(projectOffset.value, projectOffset.value + pageSize.value),
)

const showPaginationBar = computed(() => {
  if (activeKind.value === 'dataset') {
    return datasetTotal.value > 0
  }
  return filteredProjectFiles.value.length > 0
})

const hasDraftSelection = computed(() =>
  activeKind.value === 'dataset' ? Boolean(draftSample.value) : Boolean(draftProjectFile.value),
)

const selectionSummaryText = computed(() => {
  if (activeKind.value === 'dataset' && draftSample.value) {
    return `已选择：${draftSample.value.file_name} · ${draftSample.value.width} × ${draftSample.value.height}`
  }
  if (activeKind.value === 'project' && draftProjectFile.value) {
    return `已选择：${draftProjectFile.value.file_name} · ${formatSize(draftProjectFile.value.size_bytes)}`
  }
  return '未选择图片'
})

watch(
  () => [props.open, props.projectId],
  async ([isOpen, projectId]) => {
    if (!isOpen || !projectId) return
    localError.value = null
    if (activeKind.value === 'dataset') {
      if (datasets.value.length === 0) {
        await loadDatasets()
      }
    } else if (projectFiles.value.length === 0) {
      await loadProjectFiles()
    }
  },
)

watch(
  () => [props.open, activeKind.value, pagedProjectFiles.value],
  ([isOpen, kind]) => {
    if (!isOpen || kind !== 'project') return
    void loadProjectPageThumbnails(pagedProjectFiles.value)
  },
)

onBeforeUnmount(() => {
  if (datasetSearchTimer) window.clearTimeout(datasetSearchTimer)
  revokeProjectThumbnails()
})

function revokeProjectThumbnails(): void {
  for (const url of Object.values(projectThumbUrls.value)) {
    URL.revokeObjectURL(url)
  }
  projectThumbUrls.value = {}
}

function switchKind(kind: 'dataset' | 'project'): void {
  activeKind.value = kind
  localError.value = null
  if (kind === 'dataset' && datasets.value.length === 0) {
    void loadDatasets()
  } else if (kind === 'project' && projectFiles.value.length === 0) {
    void loadProjectFiles()
  }
}

async function loadDatasets(): Promise<void> {
  if (!props.projectId) return
  samplesLoading.value = true
  localError.value = null
  try {
    const page = await listDatasetCatalog({ project_id: props.projectId, limit: 100 })
    datasets.value = page.items
    if (page.items.length > 0 && !selectedDatasetId.value) {
      await selectDataset(page.items[0].dataset_id)
    }
  } catch (err) {
    localError.value = err instanceof Error ? err.message : '加载数据集目录失败'
  } finally {
    samplesLoading.value = false
  }
}

async function selectDataset(value: string | number | boolean | null): Promise<void> {
  const nextId = typeof value === 'string' ? value : ''
  selectedDatasetId.value = nextId
  selectedVersionId.value = ''
  datasetOffset.value = 0
  datasetTotal.value = 0
  samples.value = []
  draftSample.value = null
  if (!nextId || !props.projectId) return
  try {
    const page = await listDatasetVersionPage({
      project_id: props.projectId,
      dataset_id: nextId,
      state: 'available',
      limit: 50,
    })
    versions.value = page.items
    if (page.items.length > 0) {
      await selectVersion(page.items[0].dataset_version_id)
    }
  } catch (err) {
    localError.value = err instanceof Error ? err.message : '加载数据集版本失败'
  }
}

async function selectVersion(value: string | number | boolean | null): Promise<void> {
  selectedVersionId.value = typeof value === 'string' ? value : ''
  datasetOffset.value = 0
  await loadDatasetSamples()
}

async function selectSplit(value: string | number | boolean | null): Promise<void> {
  selectedSplit.value = typeof value === 'string' ? value : ''
  datasetOffset.value = 0
  await loadDatasetSamples()
}

async function selectSort(value: string | number | boolean | null): Promise<void> {
  datasetSort.value = typeof value === 'string' && value ? value : 'filename'
  datasetOffset.value = 0
  await loadDatasetSamples()
}

function scheduleDatasetSearch(): void {
  if (datasetSearchTimer) window.clearTimeout(datasetSearchTimer)
  datasetSearchTimer = window.setTimeout(() => {
    void searchDatasetSamples()
  }, 240)
}

async function searchDatasetSamples(): Promise<void> {
  datasetOffset.value = 0
  await loadDatasetSamples()
}

function clearDatasetSearch(): void {
  datasetQuery.value = ''
  void searchDatasetSamples()
}

async function loadDatasetSamples(): Promise<void> {
  if (!selectedDatasetId.value || !selectedVersionId.value) return
  samplesLoading.value = true
  localError.value = null
  try {
    const page = await listDatasetSamples(selectedDatasetId.value, selectedVersionId.value, {
      q: datasetQuery.value.trim() || undefined,
      split: selectedSplit.value || undefined,
      sort: datasetSort.value,
      offset: datasetOffset.value,
      limit: pageSize.value,
    })
    samples.value = page.items
    datasetTotal.value = page.total
  } catch (err) {
    localError.value = err instanceof Error ? err.message : '加载数据集样本失败'
  } finally {
    samplesLoading.value = false
  }
}

async function selectProjectScope(value: string | number | boolean | null): Promise<void> {
  if (value === 'workspace' || value === 'inputs' || value === 'results' || value === 'all') {
    projectScope.value = value
    projectOffset.value = 0
    await loadProjectFiles()
  }
}

async function loadProjectFiles(): Promise<void> {
  if (!props.projectId) return
  projectFilesLoading.value = true
  localError.value = null
  projectOffset.value = 0
  try {
    let entries: ProjectPublicFileEntry[] = []
    if (projectScope.value === 'workspace') {
      const [inputs, results] = await Promise.all([
        listProjectPublicFiles(props.projectId, {
          objectPrefix: `projects/${props.projectId}/inputs`,
          limit: 200,
        }).catch(() => [] as ProjectPublicFileEntry[]),
        listProjectPublicFiles(props.projectId, {
          objectPrefix: `projects/${props.projectId}/results`,
          limit: 200,
        }).catch(() => [] as ProjectPublicFileEntry[]),
      ])
      entries = [...inputs, ...results]
    } else if (projectScope.value === 'inputs') {
      entries = await listProjectPublicFiles(props.projectId, {
        objectPrefix: `projects/${props.projectId}/inputs`,
        limit: 200,
      })
    } else if (projectScope.value === 'results') {
      entries = await listProjectPublicFiles(props.projectId, {
        objectPrefix: `projects/${props.projectId}/results`,
        limit: 200,
      })
    } else {
      entries = await listProjectPublicFiles(props.projectId, { limit: 200 })
    }

    const dedup = new Map<string, ProjectPublicFileEntry>()
    for (const item of entries) {
      dedup.set(item.file_id, item)
    }
    projectFiles.value = Array.from(dedup.values())

    if (props.selectedFileId) {
      draftProjectFile.value =
        projectFiles.value.find((f) => f.file_id === props.selectedFileId) ?? draftProjectFile.value
    }
  } catch (err) {
    localError.value = err instanceof Error ? err.message : '加载项目文件失败'
  } finally {
    projectFilesLoading.value = false
  }
}

async function loadProjectPageThumbnails(items: ProjectPublicFileEntry[]): Promise<void> {
  const gen = ++thumbLoadGeneration
  const missing = items.filter((f) => !projectThumbUrls.value[f.file_id])
  if (missing.length === 0) return

  const concurrency = 4
  for (let i = 0; i < missing.length; i += concurrency) {
    if (gen !== thumbLoadGeneration) return
    const batch = missing.slice(i, i + concurrency)
    const loaded = await Promise.all(
      batch.map(async (entry) => {
        try {
          const blob = await fetchAuthorizedProjectFileBlob(props.projectId, entry.object_key)
          return [entry.file_id, URL.createObjectURL(blob)] as const
        } catch {
          return null
        }
      }),
    )
    if (gen !== thumbLoadGeneration) {
      for (const pair of loaded) {
        if (pair) URL.revokeObjectURL(pair[1])
      }
      return
    }
    const additions: Record<string, string> = {}
    for (const pair of loaded) {
      if (pair) additions[pair[0]] = pair[1]
    }
    if (Object.keys(additions).length > 0) {
      projectThumbUrls.value = { ...projectThumbUrls.value, ...additions }
    }
  }
}

function goPage(nextOffset: number): void {
  const safeOffset = Math.max(0, nextOffset)
  if (activeKind.value === 'dataset') {
    datasetOffset.value = safeOffset
    void loadDatasetSamples()
    return
  }
  projectOffset.value = safeOffset
}

function changePageSize(value: string | number | boolean | null): void {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed <= 0) return
  pageSize.value = parsed
  if (activeKind.value === 'dataset') {
    datasetOffset.value = 0
    void loadDatasetSamples()
    return
  }
  projectOffset.value = 0
}

function formatRelativeObjectKey(objectKey: string): string {
  const prefix = `projects/${props.projectId}/`
  return objectKey.startsWith(prefix) ? objectKey.slice(prefix.length) : objectKey
}

async function quickConfirmSample(sample: DatasetSample): Promise<void> {
  draftSample.value = sample
  await confirmSelection()
}

async function quickConfirmProjectFile(file: ProjectPublicFileEntry): Promise<void> {
  draftProjectFile.value = file
  await confirmSelection()
}

async function confirmSelection(): Promise<void> {
  localError.value = null
  confirming.value = true
  try {
    if (activeKind.value === 'project' && draftProjectFile.value) {
      const entry = draftProjectFile.value
      const blob = await fetchAuthorizedProjectFileBlob(props.projectId, entry.object_key)
      const previewUrl = URL.createObjectURL(blob)
      emit('confirm', {
        fileId: entry.file_id,
        label: entry.file_name,
        previewUrl,
        sizeBytes: entry.size_bytes,
        sourceMeta: '项目文件',
      })
      emit('close')
      return
    }

    if (
      activeKind.value === 'dataset' &&
      draftSample.value &&
      selectedDatasetId.value &&
      selectedVersionId.value
    ) {
      const sample = draftSample.value
      const refPayload = await getDatasetSampleFileRef(
        selectedDatasetId.value,
        selectedVersionId.value,
        sample.sample_id,
      )
      let previewUrl: string | null = null
      let sizeBytes: number | null = null
      try {
        const blob = await getDatasetImage(
          selectedDatasetId.value,
          selectedVersionId.value,
          sample.sample_id,
          false,
        )
        sizeBytes = blob.size
        previewUrl = URL.createObjectURL(blob)
      } catch {
        previewUrl = null
      }
      emit('confirm', {
        fileId: refPayload.file_id,
        label: refPayload.file_name,
        previewUrl,
        width: refPayload.width ?? sample.width,
        height: refPayload.height ?? sample.height,
        sizeBytes,
        sourceMeta: '数据集样本',
      })
      emit('close')
    }
  } catch (err) {
    localError.value = err instanceof Error ? err.message : '读取所选图像失败'
  } finally {
    confirming.value = false
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}
</script>

<style scoped>
.inf-picker-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  background: var(--am-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.inf-picker-modal {
  width: min(1080px, 94vw);
  height: min(84vh, 780px);
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  box-shadow: var(--am-shadow-modal);
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

.inf-picker-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 20px 0;
  border-bottom: 1px solid var(--am-border);
}

.inf-picker-modal__head-left {
  display: flex;
  align-items: center;
  gap: 24px;
}

.inf-picker-modal__head-left h2 {
  margin: 0 0 10px;
  font-size: 16px;
  font-weight: 700;
  color: var(--am-text-strong);
}

.inf-picker-modal__tabs {
  display: inline-flex;
  gap: 6px;
}

.inf-picker-modal__tab {
  height: 40px;
  padding: 0 14px;
  border: none;
  border-bottom: 3px solid transparent;
  background: transparent;
  color: var(--am-text-muted);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}

.inf-picker-modal__tab.is-active {
  color: var(--am-brand-primary);
  border-bottom-color: var(--am-brand-primary);
  font-weight: 600;
}

.inf-picker-modal__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  margin-bottom: 8px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--am-text-muted);
  cursor: pointer;
}

.inf-picker-modal__close:hover {
  background: var(--am-hover-surface);
  color: var(--am-text-strong);
}

.inf-picker-modal__toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--am-border);
  background: var(--am-surface);
}

.inf-picker-filter {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--am-text-muted);
}

.inf-picker-filter > span {
  white-space: nowrap;
}

.inf-picker-filter :deep(.ui-select) {
  min-width: 130px;
}

.inf-picker-filter--wide :deep(.ui-select) {
  min-width: 180px;
}

.inf-picker-search {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  min-width: 200px;
  flex: 1 1 200px;
  padding: 0 10px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-input);
  color: var(--am-text-muted);
}

.inf-picker-search input {
  flex: 1 1 auto;
  min-width: 0;
  border: none;
  background: transparent;
  color: var(--am-text-strong);
  font-size: 13px;
  outline: none;
}

.inf-picker-search button {
  border: none;
  background: transparent;
  color: var(--am-text-muted);
  cursor: pointer;
  padding: 2px;
}

.inf-picker-toolbar-right {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.inf-picker-view-toggle {
  display: inline-flex;
  gap: 4px;
}

.inf-picker-modal__body {
  flex: 1 1 0;
  min-height: 0;
  overflow: auto;
  padding: 16px 20px;
  background: var(--am-page);
}

.inf-picker-state {
  min-height: 220px;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 10px;
  text-align: center;
  font-size: 13px;
  color: var(--am-text-muted);
}

.inf-sample-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(186px, 1fr));
  gap: 12px;
}

.inf-sample-card {
  position: relative;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  background: var(--am-surface);
  overflow: hidden;
  cursor: pointer;
  transition: border-color 120ms ease, background-color 120ms ease;
}

.inf-sample-card:hover {
  border-color: var(--am-border-strong);
}

.inf-sample-card.is-selected {
  border-color: var(--am-brand-primary);
  box-shadow: 0 0 0 1px var(--am-brand-primary);
  background: var(--am-row-selected);
}

.inf-sample-card__check {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 2;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 1px solid var(--am-border-strong);
  background: rgb(255 255 255 / 0.88);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
}

.inf-sample-card__check.is-checked {
  border-color: var(--am-brand-primary);
  background: var(--am-brand-primary);
}

.inf-sample-card__media {
  height: 144px;
  background: var(--am-surface-muted);
  overflow: hidden;
}

.inf-sample-card__media :deep(.dataset-sample-image) {
  height: 144px;
}

.inf-sample-card__media--file {
  display: flex;
  align-items: center;
  justify-content: center;
}

.inf-sample-card__media--file img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.inf-thumb-placeholder {
  color: var(--am-text-muted);
}

.inf-sample-card__caption {
  padding: 8px 10px;
  display: grid;
  gap: 2px;
  min-width: 0;
}

.inf-sample-card__caption strong {
  font-size: 13px;
  font-weight: 500;
  color: var(--am-text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inf-sample-card__caption small {
  font-size: 11px;
  color: var(--am-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inf-picker-table {
  width: 100%;
  border-collapse: collapse;
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  overflow: hidden;
}

.inf-picker-table th {
  padding: 10px 12px;
  text-align: left;
  font-size: 14px;
  font-weight: 600;
  color: var(--am-text);
  border-bottom: 1px solid var(--am-border);
  background: var(--am-table-header);
}

.inf-picker-table td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--am-border);
  font-size: 13px;
  color: var(--am-text);
  cursor: pointer;
}

.inf-picker-table tbody tr:hover {
  background: var(--am-row-hover);
}

.inf-picker-table tbody tr.is-selected {
  background: var(--am-row-selected);
}

.col-radio {
  width: 38px;
  text-align: center;
}

.col-thumb {
  width: 72px;
}

.col-dims,
.col-split {
  white-space: nowrap;
  color: var(--am-text-muted);
  font-variant-numeric: tabular-nums;
}

.inf-list-thumb {
  width: 52px;
  height: 40px;
  border-radius: 4px;
  border: 1px solid var(--am-border);
  background: var(--am-surface-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.inf-list-thumb :deep(.dataset-sample-image) {
  width: 52px;
  height: 40px;
}

.inf-list-thumb img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.inf-cell-title {
  display: block;
  font-weight: 500;
  color: var(--am-text-strong);
}

.inf-cell-sub {
  display: block;
  font-size: 11px;
  color: var(--am-text-muted);
}

.inf-picker-modal__pagination {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 20px;
  border-top: 1px solid var(--am-border);
  background: var(--am-surface);
}

.inf-picker-modal__pagination :deep(.pagination-controls) {
  flex: 1 1 auto;
  border: none;
  padding: 0;
}

.inf-picker-pagesize :deep(.ui-select) {
  min-width: 104px;
}

.inf-picker-modal__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 20px;
  border-top: 1px solid var(--am-border);
  background: var(--am-surface);
}

.inf-picker-modal__selection {
  font-size: 13px;
  color: var(--am-text-muted);
}

.inf-picker-modal__actions {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}
</style>
