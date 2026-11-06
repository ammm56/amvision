<template>
  <section class="dataset-workspace dataset-version-workspace">
    <div v-show="!viewer" class="dataset-heading">
      <div class="dataset-actions">
        <Button @click="backToCatalog"
          ><ArrowLeft :size="16" />{{ text('back') }}</Button
        >
        <h1
          class="dataset-title"
          :title="workspace?.dataset.display_name || datasetId"
        >
          {{ workspace?.dataset.display_name || text('datasets') }}
        </h1>
        <DatasetVersionSelect
          v-if="workspace"
          :workspace="workspace"
          @change="changeVersion"
          @more="tab = 'lineage'"
        />
        <span v-if="workspace" class="dataset-task-label">{{ workspace.task_type }}</span>
      </div>
      <div class="dataset-actions">
        <ResourceMenu :label="text('more')" :items="headerActions" @action="headerAction" />
        <Button
          v-if="canWrite"
          variant="primary"
          :disabled="loading || !currentWorkspace"
          @click="
            router.push({
              path: '/datasets/export',
              query: { dataset: datasetId, version: versionId },
            })
          "
          ><Download :size="16" />{{ text('export') }}</Button
        >
      </div>
    </div>
    <InlineError v-if="error" :message="error" />
    <div
      v-if="workspace"
      v-show="!viewer"
      class="dataset-version-content"
      :aria-busy="loading"
      :inert="loading || !currentWorkspace"
    >
      <div class="dataset-stats">
        <div><strong>{{ workspace.sample_count.toLocaleString() }}</strong><span>{{ label('图像数量', 'Images') }}</span></div>
        <div><strong>{{ workspace.object_count.toLocaleString() }}</strong><span>{{ label('对象数量', 'Objects') }}</span></div>
        <div><strong>{{ workspace.category_count.toLocaleString() }}</strong><span>{{ label('类别数量', 'Classes') }}</span></div>
        <div><strong>{{ ['train', 'val', 'test'].map(key => (workspace!.split_counts[key] ?? 0).toLocaleString()).join(' / ') }}</strong><span>train / val / test</span></div>
        <div class="dataset-test-status"><strong>{{ workspace.split_counts.test ? label('已配置', 'Configured') : label('未配置', 'Not configured') }}</strong><span>{{ label('测试集', 'Test set') }}</span></div>
      </div>
      <div class="dataset-tabs" role="tablist">
        <button
          v-for="item in tabs"
          :key="item"
          role="tab"
          :aria-selected="tab === item"
          @click="tab = item"
        >
          {{ text(item) }}
        </button>
      </div>
      <template v-if="tab === 'sampleTab'">
        <div class="dataset-toolbar dataset-sample-filters">

          <label class="dataset-filter"
            >{{ label('数据划分', 'Split')
            }}<SelectField
              v-model="split"
              :options="[
                { value: '', label: text('all') },
                ...Object.keys(workspace.split_counts).map((value) => ({
                  value,
                  label: value,
                })),
              ]"
              @update:model-value="search" /></label
          ><label class="dataset-filter"
            >{{ text('classes')
            }}<SelectField
              v-model="category"
              :options="[
                { value: '', label: text('all') },
                ...workspace.categories.map((c) => ({
                  value: String(c.category_id),
                  label: c.name,
                })),
              ]"
              @update:model-value="search" /></label
          ><label class="dataset-filter"
            >{{ text('annotation')
            }}<SelectField
              v-model="annotationState"
              :options="[
                { value: '', label: text('all') },
                { value: 'annotated', label: text('annotated') },
                { value: 'empty', label: text('unannotated') },
              ]"
              @update:model-value="search"
          /></label>
          <form class="input-with-icon dataset-search" @submit.prevent="search">
            <Search :size="16" /><input
              v-model="q"
              :aria-label="label('搜索', 'Search')"
              :placeholder="label('搜索', 'Search')"
              @input="scheduleSearch"
            />
          </form>
          <div class="dataset-actions dataset-view-controls">
            <Button
              icon-only
              :aria-label="text('grid')"
              :class="{ 'is-active': grid }" :aria-pressed="grid"
              @click="grid = true"
              ><LayoutGrid :size="16" /></Button
            ><Button
              icon-only
              :aria-label="text('list')"
              :class="{ 'is-active': !grid }" :aria-pressed="!grid"
              @click="grid = false"
              ><List :size="16"
            /></Button>
            <label class="dataset-checkbox dataset-annotation-toggle"
              ><input v-model="annotations" type="checkbox" />{{
                text('showAnnotations')
              }}</label
            >
          </div>
          <div class="dataset-filter dataset-sort-filter">
            <SelectField
              v-model="sort"
              :aria-label="label('排序', 'Sort')"
              :options="[
                {
                  value: 'filename',
                  label: label('文件名升序', 'Filename A–Z'),
                },
                {
                  value: 'filename_desc',
                  label: label('文件名降序', 'Filename Z–A'),
                },
                { value: 'image_id', label: label('导入顺序', 'Import order') },
              ]"
              @update:model-value="search"
            >
              <template #value="{ option }"><span class="dataset-sort-value" :aria-label="option?.label">{{ option?.value === 'image_id' ? label('导入顺序', 'Import order') : label('文件名', 'Filename') }}<component :is="option?.value === 'filename_desc' ? ArrowDown : ArrowUp" :size="15" aria-hidden="true" /></span></template>
              <template #option="{ option }"><span class="dataset-sort-value" :aria-label="option.label">{{ option.value === 'image_id' ? label('导入顺序', 'Import order') : label('文件名', 'Filename') }}<component :is="option.value === 'filename_desc' ? ArrowDown : ArrowUp" :size="15" aria-hidden="true" /></span></template>
            </SelectField>
          </div>

        </div>
        <div v-if="canWrite" class="dataset-toolbar dataset-selection-bar" :class="{ 'has-selection': allFiltered || checked.size }">
          <div class="dataset-actions dataset-selection-summary">
            <label v-if="samples.length && (!grid || (!allFiltered && !checked.size))" class="dataset-checkbox"><input type="checkbox" :aria-label="text('selectPage')" :disabled="allFiltered" :checked="allFiltered || samples.every(s => checked.has(s.sample_id))" @change="selectPage(($event.target as HTMLInputElement).checked)" /><span v-if="!allFiltered && !checked.size">{{ text('selectPage') }}</span></label>
            <template v-if="allFiltered || checked.size">
              <span>{{ label('已选', 'Selected') }} <strong>{{ (allFiltered ? total : checked.size).toLocaleString() }}</strong> {{ label('张', 'images') }}</span>
              <Button v-if="grid && !allFiltered" size="sm" :disabled="samples.every(s => checked.has(s.sample_id))" @click="selectPage(true)">{{ label(`选择本页 ${samples.length} 张`, `Select page (${samples.length})`) }}</Button>
              <Button v-if="checked.size && !allFiltered && checked.size < total" size="sm" @click="selectFiltered">{{ label(`选择全部 ${total.toLocaleString()} 张`, `Select all ${total.toLocaleString()} images`) }}</Button>
              <Button size="sm" @click="clearSelection">{{ label('取消选择', 'Clear selection') }}</Button>
            </template>
          </div>
          <div class="dataset-actions dataset-selection-actions">
            <template v-if="allFiltered || checked.size">
              <Button size="sm" @click="exportSelected"><Download :size="15" />{{ text('exportSelected') }}</Button>
              <Button size="sm" @click="createFromSelection">{{ label('从所选创建版本', 'Create version from selection') }}</Button>
              <Button size="sm" @click="removeSelected"><Trash2 :size="15" />{{ label('删除所选', 'Remove selected') }}</Button>
            </template>
            <Button v-else size="sm" @click="addSamples"><Plus :size="15" />{{ label('添加样本', 'Add samples') }}</Button>
          </div>
        </div>
        <div v-if="samples.length && grid" class="dataset-sample-grid">
          <article
            v-for="sample in samples"
            :key="sample.sample_id"
            class="dataset-sample-card"
            :class="{
              'is-selected': allFiltered || checked.has(sample.sample_id),
              'is-focused': selected === sample.sample_id,
            }"
            @click="selected = sample.sample_id"
            @dblclick="showImage(sample)"
          >
            <label
              v-if="canWrite"
              class="dataset-card-selection"
              @click.stop
              @dblclick.stop
            >
              <input
                type="checkbox"
                :disabled="allFiltered"
                :aria-label="`${text('selection')} ${sample.file_name}`"
                :checked="allFiltered || checked.has(sample.sample_id)"
                @change="toggleSample(sample.sample_id)"
              />
            </label>
            <div
              role="button"
              tabindex="0"
              class="dataset-image-button"
              :aria-label="`${text('view')} ${sample.file_name}`"
              @keydown.enter.prevent="showImage(sample)"
              @keydown.space.prevent="showImage(sample)"
            >
              <DatasetSampleImage
                :dataset-id="datasetId"
                :sample="sample"
                :categories="workspace.categories"
                :show-annotations="annotations"
                :pose-schemas="poseSchemas"
              />
            </div>
            <div class="dataset-sample-caption">
              <div>
                <strong :title="sample.file_name">{{ sample.file_name }}</strong
                ><small
                  >{{ sample.split }} · {{ sample.annotations.length }}
                  {{ text('object') }}</small
                >
              </div>
              <ResourceMenu
                :label="text('more')"
                :items="[
                  { id: 'image', label: text('view'), icon: Maximize2 },
                  { id: 'info', label: text('sampleInfo'), icon: Info },
                ]"
                @action="
                  $event === 'image' ? showImage(sample) : showInfo(sample)
                "
              />
            </div>
          </article>
        </div>
        <ResourceTable
          v-else-if="samples.length"
          class="dataset-table dataset-sample-list"
          :label="text('samples')"
          ><thead>
            <tr>
              <th v-if="canWrite" style="width: 48px"></th>
              <th style="width:80px">{{ label('缩略图', 'Thumbnail') }}</th><th style="width:28%">{{ text('fileName') }}</th>
              <th>{{ label('划分', 'Split') }}</th>
              <th>{{ label('对象数量', 'Objects') }}</th>
              <th>{{ text('annotation') }}</th>
              <th style="width:140px">{{ text('actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="sample in samples"
              :key="sample.sample_id"
              class="is-clickable"
              :class="{
                'is-selected': allFiltered || checked.has(sample.sample_id),
              }"
              @click="showInfo(sample)"
            >
              <td v-if="canWrite" @click.stop>
                <input
                  type="checkbox"
                  :disabled="allFiltered"
                  :aria-label="`${text('selection')} ${sample.file_name}`"
                  :checked="allFiltered || checked.has(sample.sample_id)"
                  @change="toggleSample(sample.sample_id)"
                />
              </td>
              <td><DatasetSampleImage class="dataset-list-thumbnail" :dataset-id="datasetId" :sample="sample" :categories="workspace.categories" :show-annotations="annotations" :pose-schemas="poseSchemas" /></td>
              <td>
                <span class="dataset-sample-filename" :title="sample.file_name">{{ sample.file_name }}</span>
              </td>
              <td><span class="dataset-task-label">{{ sample.split }}</span></td>
              <td>{{ sample.annotations.length }}</td>
              <td><span class="dataset-annotation-status" :class="{ 'is-annotated': sample.annotations.length > 0 }"><Circle :size="8" fill="currentColor" />{{ sample.annotations.length ? label('已标注', 'Annotated') : text('unannotated') }}</span></td>
              <td>
                <div class="dataset-actions"><Button size="sm" variant="ghost" class="dataset-sample-view" @click.stop="showImage(sample)">{{ text('view') }}</Button><Button size="sm" variant="ghost" @click.stop="showInfo(sample)">{{ label('信息', 'Info') }}</Button></div>
              </td>
            </tr>
          </tbody></ResourceTable
        >
        <div v-else class="dataset-empty">
          {{ text(loading ? 'loading' : 'noMatches') }}
          <Button v-if="q || split || category || annotationState" @click="q = ''; split = ''; category = ''; annotationState = ''; search()">{{ text('clear') }}</Button>
        </div>
        <div v-if="total > limit || offset > 0" class="dataset-sample-pagination">
        <PaginationControls
          numbered
          :offset="offset"
          :limit="limit"
          :item-count="samples.length"
          :total-count="total"
          :disabled="loading"
          @previous="page(-limit)"
          @next="page(limit)"
          @go="page($event - offset)"
        ><template #summary>{{ label(`共 ${total.toLocaleString()} 张图像，每页 ${limit} 条`, `${total.toLocaleString()} images, ${limit} per page`) }}</template></PaginationControls>
        <SelectField :model-value="String(limit)" :aria-label="label('每页样本', 'Samples per page')" :options="[8, 16, 24, 48].map(n => ({ value: String(n), label: `${n} ${label('条/页', '/ page')}` }))" @update:model-value="limit = Number($event); search()" />
        </div>
      </template>
      <DatasetVersionPanels
        v-show="tab !== 'sampleTab'"
        :key="workspace.dataset_version_id"
        :workspace="workspace"
        :tab="tab"
        @filter="filterSamples"
        @version="changeVersion"
        @sample="showExternalImage"
      />
    </div>
    <SideDrawer
      :open="infoOpen"
      :title="workspace?.task_type === 'classification' ? label('样本与标签', 'Sample and labels') : label('样本与对象', 'Sample and objects')" size="compact" plain :nonmodal="!!viewer"
      :close-label="text('close')"
      @close="infoOpen = false"
      @after-leave="afterInfoClose"
      ><template v-if="detail && workspace"
        ><DatasetSampleImage
          v-if="!viewer"
          :dataset-id="datasetId"
          :sample="detail"
          :categories="workspace.categories"
          :show-annotations="true"
          :selected-object="selectedObject"
          :pose-schemas="poseSchemas"
        />
        <DatasetSampleDetails :sample="detail" :categories="workspace.categories" :selected="selectedObject" :task="workspace.task_type" :source="typeof workspace.metadata.format_type === 'string' ? workspace.metadata.format_type.toUpperCase() : '—'" @select="selectObject" />
        </template
      ><template #footer
        ><Button v-if="!viewer" :disabled="!detail" @click="detail && showImage(detail)"
          ><Maximize2 :size="16" />{{ text('view') }}</Button
        ><span v-else /><Button @click="infoOpen = false">{{ text('close') }}</Button></template
      ></SideDrawer
    >
    <DatasetImageViewer v-if="viewer && workspace" :open="!!viewer" :image="viewer"
      :dataset-name="workspace.dataset.display_name" :version="`v${workspace.version_number}`"
      :split="viewerSample?.split || ''" :object-count="viewerSample?.annotations.length || 0"
      :annotations="viewerAnnotations" :busy="viewerBusy" :invalid="viewerInvalid"
      :info-open="infoOpen" :focused-bounds="selectedAnnotation ? annotationBounds(selectedAnnotation) : null" :task="workspace.task_type"
      :has-previous="!viewerStandalone && viewerIndex > 0" :has-next="!viewerStandalone && viewerIndex < total - 1"
      @close="closeViewer" @close-info="infoOpen = false" @previous="adjacent(-1)" @next="adjacent(1)"
      @info="viewerSample && showInfo(viewerSample)" @annotations="viewerAnnotations = $event; updateViewerImage()" />
    <DatasetInfoDrawer v-if="datasetInfoMode && workspace" :info="workspace.dataset" :mode="datasetInfoMode" :editable="canWrite"
      @close="datasetInfoMode = null" @saved="saveInfo" />

  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import DatasetVersionSelect from '../components/DatasetVersionSelect.vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  ArrowUp,
  ArrowDown,
  Circle,
  Download,
  Info,
  LayoutGrid,
  List,
  Maximize2,
  RefreshCw,
  Search,
  Plus,
  Trash2,
  Pencil,
} from '@lucide/vue'
import { useSessionStore } from '@/app/stores/session.store'
import { useFeedbackStore } from '@/app/stores/feedback.store'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import ResourceMenu from '@/shared/ui/components/ResourceMenu.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import DatasetSampleDetails from '../components/DatasetSampleDetails.vue'
import DatasetImageViewer from '../components/DatasetImageViewer.vue'
import DatasetInfoDrawer from '../components/DatasetInfoDrawer.vue'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import DatasetSampleImage from '../components/DatasetSampleImage.vue'
import DatasetVersionPanels from '../components/DatasetVersionPanels.vue'
import {
  getDatasetWorkspace,
  getDatasetSample,
  listDatasetSamples,
  getDatasetImage,
  type DatasetWorkspace,
  type DatasetSample,
  type DatasetInfo,
} from '../services/dataset-workspace.service'
import { annotatedImage, annotationBounds } from '../annotations'
import { datasetError, useDatasetText } from '../dataset-workspace'
import type { DatasetSampleSelection } from '../services/dataset.service'
import '../dataset-workspace.css'
const route = useRoute(),
  router = useRouter(),
  session = useSessionStore(),
  text = useDatasetText()
const { locale } = useI18n()
const label = (zh: string, en: string) =>
  locale.value.startsWith('zh') ? zh : en
const feedback = useFeedbackStore()
const datasetId = computed(() => String(route.params.datasetId)),
  versionId = computed(() => String(route.params.versionId)),
  canWrite = computed(() => session.hasScopes(['datasets:write']))
const datasetInfoMode = ref<'info' | 'edit' | null>(null)
const headerActions = computed(() => [
  { id: 'info', label: text('info'), icon: Info },
  ...(canWrite.value ? [{ id: 'edit', label: text('editShort'), icon: Pencil }, { id: 'create', label: label('创建新版本', 'Create new version'), icon: Plus }] : []),
  { id: 'refresh', label: text('refresh'), icon: RefreshCw },
])
function headerAction(id: string) {
  if (id === 'info' || id === 'edit') datasetInfoMode.value = id
  else if (id === 'refresh') void load()
  else if (id === 'create' && canWrite.value) void router.push(`/datasets/${datasetId.value}/versions/${versionId.value}/tools/derive`)
}
function saveInfo(info: DatasetInfo) { if (workspace.value) workspace.value.dataset = info; datasetInfoMode.value = null }
function selectObject(id: string) { selectedObject.value = id; if (viewer.value) void selectViewerObject(id) }
const tabs = [
    'sampleTab',
    'structure',
    'categories',
    'quality',
    'lineage',
  ] as const,
  tab = ref<(typeof tabs)[number]>('sampleTab'),
  workspace = ref<DatasetWorkspace | null>(null),
  samples = ref<DatasetSample[]>([]),
  loading = ref(false),
  error = ref(''),
  q = ref(''),
  split = ref(''),
  category = ref(''),
  annotationState = ref(''),
  sort = ref('filename'),
  offset = ref(0),
  limit = ref(8),
  total = ref(0),
  grid = ref(true),
  annotations = ref(true),
  selected = ref(''),
  detail = ref<DatasetSample | null>(null),
  infoOpen = ref(false),
  selectedObject = ref('')
const selectedAnnotation = computed(() => detail.value?.annotations.find(a => a.annotation_id === selectedObject.value))
const viewer = ref<InstanceType<typeof DatasetImageViewer>['$props']['image']>(null),
  viewerSample = ref<DatasetSample | null>(null),
  viewerIndex = ref(0)
const viewerBusy = ref(false),
  viewerSelectedObject = ref(''),
  viewerAnnotations = ref(true),
  viewerInvalid = ref(0)
const checked = ref(new Set<string>()),
  allFiltered = ref(false)
const currentWorkspace = computed(
  () =>
    workspace.value?.dataset_id === datasetId.value &&
    workspace.value?.dataset_version_id === versionId.value,
)
function clearSelection() {
  checked.value = new Set()
  allFiltered.value = false
}
function selectPage(value: boolean) {
  if (allFiltered.value) return
  const next = new Set(checked.value)
  for (const sample of samples.value) {
    if (value) next.add(sample.sample_id)
    else next.delete(sample.sample_id)
  }
  if (next.size > 1000) {
    feedback.info(text('selectionLimit'))
    return
  }
  checked.value = next
}
function toggleSample(id: string) {
  if (allFiltered.value) return
  const next = new Set(checked.value)
  if (next.has(id)) next.delete(id)
  else if (next.size < 1000) next.add(id)
  else feedback.info(text('selectionLimit'))
  checked.value = next
}
function exportSelected() {
  sendSelection('/datasets/export')
}
function createFromSelection() {
  sendSelection(
    `/datasets/${encodeURIComponent(datasetId.value)}/versions/${encodeURIComponent(versionId.value)}/tools/derive`,
  )
}
function addSamples() {
  void router.push(
    `/datasets/${encodeURIComponent(datasetId.value)}/versions/${encodeURIComponent(versionId.value)}/tools/samples`,
  )
}
function removeSelected() {
  sendSelection(
    `/datasets/${encodeURIComponent(datasetId.value)}/versions/${encodeURIComponent(versionId.value)}/tools/samples`,
  )
}
function sendSelection(path: string) {
  const selection: DatasetSampleSelection = allFiltered.value
    ? {
        mode: 'filter',
        q: q.value,
        split: split.value,
        category_id: category.value === '' ? undefined : Number(category.value),
        annotation_state: annotationState.value,
      }
    : { mode: 'ids', sample_ids: [...checked.value] }
  void router.push({
    path,
    query: { dataset: datasetId.value, version: versionId.value },
    state: {
      datasetSelection: {
        version: versionId.value,
        revision: String(workspace.value?.metadata.content_revision || ''),
        names: samples.value
          .filter(
            (sample) =>
              allFiltered.value || checked.value.has(sample.sample_id),
          )
          .slice(0, 8)
          .map((sample) => sample.file_name),
        selection: JSON.parse(JSON.stringify(selection)),
      },
    },
  })
}
const poseSchemas = computed(
  () =>
    (workspace.value?.metadata.pose_category_schemas || {}) as Record<
      string,
      unknown
    >,
)
let controller: AbortController | undefined,
  viewerController: AbortController | undefined,
  timer: ReturnType<typeof setTimeout> | undefined,
  generation = 0,
  workspaceGeneration = 0,
  viewerGeneration = 0,
  viewerUrl = '',
  annotatedUrl = ''
let originalMediaType = ''
let viewerBlob: Blob | null = null,
  overlayGeneration = 0
let pendingImage: DatasetSample | null = null
const sampleQuery = () => ({
  q: q.value,
  split: split.value,
  category_id: category.value || undefined,
  annotation_state: annotationState.value,
  sort: sort.value,
  offset: offset.value,
  limit: limit.value,
})
async function load() {
  ++generation
  controller?.abort()
  controller = new AbortController()
  const request = ++workspaceGeneration
  loading.value = true
  error.value = ''
  try {
    const data = await getDatasetWorkspace(
      datasetId.value,
      versionId.value,
      controller.signal,
    )
    if (request !== workspaceGeneration) return
    if (
      workspace.value?.metadata.content_revision !==
      data.metadata.content_revision
    ) {
      clearSelection()
      closeViewer()
      offset.value = 0
      infoOpen.value = false
      detail.value = null
    }
    // 工作区与样本一起切换，避免新版本标题短暂配上旧版本图片。
    const page = await listDatasetSamples(
      datasetId.value,
      versionId.value,
      sampleQuery(),
      controller.signal,
    )
    if (request !== workspaceGeneration) return
    workspace.value = data
    samples.value = page.items
    total.value = page.total
    if (page.total > 0 && offset.value >= page.total) {
      offset.value = Math.floor((page.total - 1) / limit.value) * limit.value
      await syncQuery()
      await loadSamples()
    }
    if (route.query.sample && request === workspaceGeneration) {
      const sample = await getDatasetSample(
        datasetId.value,
        versionId.value,
        String(route.query.sample),
      )
      if (request === workspaceGeneration) showExternalImage(sample)
    }
  } catch (e) {
    if (request === workspaceGeneration) error.value = datasetError(e)
  } finally {
    if (request === workspaceGeneration) loading.value = false
  }
}
async function loadSamples() {
  const request = ++generation
  loading.value = true
  error.value = ''
  try {
    const data = await listDatasetSamples(
      datasetId.value,
      versionId.value,
      sampleQuery(),
      controller?.signal,
    )
    if (request !== generation) return
    if (data.total > 0 && offset.value >= data.total) {
      offset.value = Math.floor((data.total - 1) / limit.value) * limit.value
      await syncQuery()
      return loadSamples()
    }
    samples.value = data.items
    total.value = data.total
  } catch (e) {
    if (request === generation) error.value = datasetError(e)
  } finally {
    if (request === generation) loading.value = false
  }
}
function search() {
  clearTimeout(timer)
  offset.value = 0
  clearSelection()
  closeViewer()
  void syncQuery()
  void loadSamples()
}
function scheduleSearch() {
  clearTimeout(timer)
  timer = setTimeout(search, 250)
}
function page(delta: number) {
  offset.value = Math.max(0, offset.value + delta)
  void syncQuery()
  void loadSamples()
}
function backToCatalog() {
  const back = window.history.state?.back
  if (typeof back === 'string' && /^\/datasets(?:\?|$)/.test(back))
    router.back()
  else void router.push('/datasets')
}
function syncQuery() {
  return router.replace({
    query: {
      tab: tab.value === 'sampleTab' ? undefined : tab.value,
      q: q.value || undefined,
      split: split.value || undefined,
      category: category.value || undefined,
      annotation: annotationState.value || undefined,
      sort: sort.value === 'filename' ? undefined : sort.value,
      offset: offset.value || undefined,
      view: grid.value ? undefined : 'list',
    },
  })
}
function readQuery() {
  sort.value = ['filename', 'filename_desc', 'image_id'].includes(
    String(route.query.sort),
  )
    ? String(route.query.sort)
    : 'filename'
  q.value = String(route.query.q || '').slice(0, 200)
  split.value = ['train', 'val', 'test'].includes(String(route.query.split))
    ? String(route.query.split)
    : ''
  category.value = /^-?\d+$/.test(String(route.query.category))
    ? String(route.query.category)
    : ''
  annotationState.value = ['annotated', 'empty'].includes(
    String(route.query.annotation),
  )
    ? String(route.query.annotation)
    : ''
  offset.value = Math.min(
    10000000,
    Math.max(0, Math.floor(Number(route.query.offset) || 0)),
  )
  tab.value = tabs.includes(route.query.tab as typeof tab.value)
    ? (route.query.tab as typeof tab.value)
    : 'sampleTab'
  grid.value = route.query.view !== 'list'
}
function filterSamples(value: { category?: number; split?: string }) {
  category.value = value.category === undefined ? '' : String(value.category)
  split.value = value.split || ''
  tab.value = 'sampleTab'
  search()
}
function showInfo(sample: DatasetSample) {
  detail.value = sample
  selectedObject.value = (viewer.value ? viewerSelectedObject.value : '') || sample.annotations[0]?.annotation_id || ''
  if (viewer.value && selectedObject.value) void selectViewerObject(selectedObject.value)
  infoOpen.value = true
}
function afterInfoClose() {
  detail.value = null
  if (pendingImage) {
    const sample = pendingImage
    pendingImage = null
    void showImage(sample)
  }
}
async function showImage(
  sample: DatasetSample,
  index?: number,
  standalone = false,
) {
  viewerStandalone.value = standalone
  if (infoOpen.value) {
    pendingImage = sample
    infoOpen.value = false
    return
  }
  viewerController?.abort()
  viewerController = new AbortController()
  const request = ++viewerGeneration
  viewerBusy.value = true
  error.value = ''
  try {
    const blob = await getDatasetImage(
      datasetId.value,
      versionId.value,
      sample.sample_id,
      false,
      viewerController.signal,
    )
    if (request !== viewerGeneration) return
    const annotated = await annotatedImage(
      blob,
      sample,
      new Map(workspace.value!.categories.map((c) => [c.category_id, c.name])),
      poseSchemas.value,
    )
    if (request !== viewerGeneration) return
    viewerBlob = blob
    viewerSelectedObject.value = ''
    overlayGeneration++
    if (viewerUrl) URL.revokeObjectURL(viewerUrl)
    if (annotatedUrl) URL.revokeObjectURL(annotatedUrl)
    viewerUrl = URL.createObjectURL(blob)
    originalMediaType = blob.type
    annotatedUrl = URL.createObjectURL(annotated.blob)
    viewerInvalid.value = annotated.invalid
    viewerSample.value = sample
    viewerIndex.value =
      index ??
      offset.value +
        samples.value.findIndex((s) => s.sample_id === sample.sample_id)
    updateViewerImage()
  } catch (e) {
    if (request === viewerGeneration) error.value = datasetError(e)
  } finally {
    if (request === viewerGeneration) viewerBusy.value = false
  }
}
function updateViewerImage() {
  const sample = viewerSample.value
  if (!sample) return
  viewer.value = {
    id: sample.sample_id,
    title: sample.file_name,
    src: viewerAnnotations.value ? annotatedUrl : viewerUrl,
    width: sample.width,
    height: sample.height,
    mediaType: viewerAnnotations.value ? 'image/jpeg' : originalMediaType,
  }
}
async function selectViewerObject(id: string) {
  if (!viewerBlob || !viewerSample.value || viewerBusy.value) return
  const request = ++overlayGeneration
  const imageRequest = viewerGeneration
  viewerSelectedObject.value = id
  try {
    const result = await annotatedImage(
      viewerBlob,
      viewerSample.value,
      new Map(workspace.value!.categories.map((c) => [c.category_id, c.name])),
      poseSchemas.value,
      id,
    )
    if (request !== overlayGeneration || imageRequest !== viewerGeneration)
      return
    if (annotatedUrl) URL.revokeObjectURL(annotatedUrl)
    annotatedUrl = URL.createObjectURL(result.blob)
    viewerAnnotations.value = true
    updateViewerImage()
  } catch (e) {
    if (request === overlayGeneration && imageRequest === viewerGeneration)
      feedback.error(datasetError(e))
  }
}
function closeViewer() {
  overlayGeneration++
  viewerBlob = null
  viewerSelectedObject.value = ''
  viewerGeneration++
  viewerController?.abort()
  viewerBusy.value = false
  viewer.value = null
  viewerSample.value = null
  infoOpen.value = false
  if (viewerUrl) URL.revokeObjectURL(viewerUrl)
  if (annotatedUrl) URL.revokeObjectURL(annotatedUrl)
  viewerUrl = ''
  annotatedUrl = ''
}
async function adjacent(delta: number) {
  if (viewerBusy.value || viewerStandalone.value) return
  const index = viewerIndex.value + delta
  if (index < 0 || index >= total.value) return
  const request = viewerGeneration
  viewerBusy.value = true
  try {
    const data = await listDatasetSamples(datasetId.value, versionId.value, {
      ...sampleQuery(),
      offset: index,
      limit: 1,
    })
    if (request === viewerGeneration && data.items[0])
      await showImage(data.items[0], index)
  } catch (e) {
    if (request === viewerGeneration) error.value = datasetError(e)
  } finally {
    viewerBusy.value = false
  }
}
function changeVersion(id: string) {
  void router.push(
    `/datasets/${encodeURIComponent(datasetId.value)}/versions/${encodeURIComponent(id)}`,
  )
}
watch(
  () => [datasetId.value, versionId.value],
  () => {
    clearTimeout(timer)
    if (workspace.value?.dataset_id !== datasetId.value) workspace.value = null
    offset.value = 0
    q.value = ''
    split.value = ''
    category.value = ''
    annotationState.value = ''
    readQuery()
    selected.value = ''
    clearSelection()
    detail.value = null
    infoOpen.value = false
    closeViewer()
    void load()
  },
  { immediate: true },
)
watch([tab, grid], () => {
  void syncQuery()
})
watch(
  () => route.query,
  () => {
    const before = JSON.stringify(sampleQuery())
    readQuery()
    if (workspace.value && before !== JSON.stringify(sampleQuery())) {
      clearSelection()
      void loadSamples()
    }
  },
)
onBeforeUnmount(() => {
  generation++
  workspaceGeneration++
  controller?.abort()
  clearTimeout(timer)
  closeViewer()
})
const viewerStandalone = ref(false)
function showExternalImage(sample: DatasetSample) {
  void showImage(sample, 0, true)
}
function selectFiltered() {
  allFiltered.value = true
  checked.value = new Set()
}
</script>
<style scoped>
.dataset-stats { display:grid; grid-template-columns:1fr 1fr 1fr 1.7fr 1fr; align-items:center; padding:18px 22px; background:var(--am-surface); border:1px solid var(--am-border); border-radius:var(--am-radius-md); }
.dataset-stats > div { display:flex; flex-direction:column; gap:7px; min-width:0; padding:0 20px; border-right:1px solid var(--am-border); }
.dataset-stats > div:first-child { padding-left:0; }
.dataset-stats > div:last-child { border:0; padding-right:0; align-items:flex-end; }
.dataset-stats strong { font-size:22px; line-height:28px; font-weight:500; font-variant-numeric:tabular-nums; white-space:nowrap; }
.dataset-stats > div > span { font-size:13px; color:var(--am-text-muted); }
.dataset-stats .dataset-test-status strong { font-size:14px; }
.dataset-checkbox {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 13px;
}
.dataset-annotation-toggle input[type='checkbox'] {
  width: 30px;
  height: 18px;
  border-radius: 999px;
  background: var(--am-border-strong);
  border: 0;
  position: relative;
  background-image: none;
  cursor: pointer;
}
.dataset-annotation-toggle input[type='checkbox']::after {
  content: '';
  position: absolute;
  top: 3px;
  left: 3px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #fff;
  transition: transform 0.16s ease;
}
.dataset-annotation-toggle input[type='checkbox']:checked {
  background: var(--am-brand-primary);
  background-image: none;
}
.dataset-annotation-toggle input[type='checkbox']:checked::after {
  transform: translateX(12px);
}
.dataset-sample-pagination { display:flex; align-items:center; gap:12px; min-width:0; }
.dataset-sample-pagination :deep(.pagination-controls) { flex:1; min-width:0; }
.dataset-sample-pagination > :last-child { width:105px; flex-shrink:0; }
.dataset-sample-pagination :deep(.ui-select__menu) {
  top: auto;
  bottom: calc(100% + 4px);
}
.dataset-sample-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}
.dataset-sample-card {
  position: relative;
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  overflow: hidden;
  cursor: pointer;
}
.dataset-selection-bar {
  font-size: 13px;
}
.dataset-selection-bar > span {
  color: var(--am-text-muted);
}
.dataset-sample-card:hover {
  box-shadow: var(--am-shadow-sm);
}
.dataset-sample-card.is-selected {
  border-color: var(--am-brand-primary);
  outline: 2px solid var(--am-brand-primary);
  outline-offset: -2px;
}
.dataset-sample-card.is-focused:not(.is-selected) {
  border-color: var(--am-border-strong);
}
.dataset-card-selection {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 1;
  display: grid;
  place-items: center;
  padding: 1px;
  background: var(--am-surface);
  border-radius: var(--am-radius-sm);
  box-shadow: var(--am-shadow-sm);
}
.dataset-card-selection input {
  margin: 0;
}
.dataset-version-content {
  display: grid;
  gap: 16px;
  min-width: 0;
}
.dataset-version-content > .dataset-tabs button[aria-selected='true'] {
  background: transparent;
}
.dataset-version-content[inert] {
  opacity: 0.55;
}
.dataset-selection-bar {
  min-height: 40px;
  padding: 4px 0;
  border: 1px solid transparent;
  border-radius: var(--am-radius-md);
}
.dataset-selection-bar.has-selection {
  padding: 8px 12px;
  background: color-mix(in srgb, var(--am-row-selected) 45%, var(--am-surface));
  border-color: var(--am-row-selected);
}
.dataset-task-label { padding:4px 8px; border-radius:var(--am-radius-sm); background:var(--am-surface-muted); color:var(--am-text-muted); font-size:13px; white-space:nowrap; }
.dataset-table td > .dataset-task-label { display:inline-block; }
.dataset-sample-list :deep(td > .dataset-sample-filename) { font-size:inherit; font-family:inherit; color:var(--am-text); }
.dataset-table td > .dataset-annotation-status { display:inline-flex; align-items:center; gap:6px; font-size:13px; }
.dataset-annotation-status { color:var(--am-text-muted); }
.dataset-annotation-status.is-annotated { color:var(--am-brand-primary); }
.dataset-sample-view { color:var(--am-brand-primary); }
.dataset-sort-value { display:flex; align-items:center; gap:6px; }
.dataset-selection-bar strong { color:var(--am-brand-primary); font-weight:500; }
.dataset-sample-pagination :deep(.pagination-controls__summary) { color:var(--am-text-muted); font-weight:400; font-size:13px; }
.dataset-image-button {
  display: block;
  width: 100%;
  padding: 0;
  border: 0;
  background: none;
  cursor: pointer;
}
.dataset-sample-caption {
  padding: 10px 12px;
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
}
.dataset-sample-caption > div {
  flex: 1;
  min-width: 0;
}
.dataset-sample-caption strong {
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 13px;
  font-weight: 500;
}
.dataset-sample-caption small {
  display: block;
  margin-top: 5px;
  color: var(--am-text-muted);
}
.dataset-objects {
  display: grid;
  gap: 8px;
}
.dataset-objects button {
  min-width: 0;
  overflow-wrap: anywhere;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px;
  background: var(--am-surface);
  color: var(--am-text);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  cursor: pointer;
}
.dataset-objects button:hover {
  background: var(--am-hover-surface);
}
.dataset-objects button.is-selected {
  border-color: var(--am-brand-primary);
}
.dataset-viewer-results {
  display: grid;
  align-content: start;
  gap: 12px;
  padding: 8px 16px 16px;
  overflow: auto;
  color: var(--am-text);
}
.dataset-viewer-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}
.dataset-view-controls :deep(.ui-button.is-active) { color:var(--am-brand-primary); background:var(--am-row-selected); border-color:var(--am-border); }
</style>

<style scoped>
.dataset-sample-filters {
  align-items: flex-end;
  gap: 10px;
}
.dataset-sample-filters > button {
  flex-shrink: 0;
}
.dataset-sample-filters .dataset-filter {
  flex: 1 1 90px;
  max-width: 150px;
  min-width: 0;
  display: grid;
  gap: 6px;
  color: var(--am-text-muted);
}
.dataset-sample-filters .dataset-filter > div {
  width: 100%;
  min-width: 0;
  color: var(--am-text);
}
.dataset-sample-filters .dataset-search {
  width: 170px;
  min-width: 150px;
  max-width: 240px;
  flex: 1 1 150px;
}
.dataset-view-controls {
  flex-wrap: nowrap;
}
.dataset-view-controls .dataset-checkbox {
  white-space: nowrap;
}
.dataset-sample-caption strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dataset-version-workspace > .dataset-heading > .dataset-actions:first-child {
  flex: 1 1 330px;
  flex-wrap: nowrap;
}
.dataset-version-workspace .dataset-title {
  flex: 0 1 auto;
}
.dataset-sample-caption :deep(.ui-button--icon-only) {
  border-color: transparent;
  background: transparent;
  box-shadow: none;
}
@media (max-width: 1200px) {
  .dataset-stats { padding: 14px 16px; }
  .dataset-stats > div { padding:0 12px; }
  .dataset-stats strong { font-size:19px; }
  .dataset-sample-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .dataset-sample-filters .dataset-filter { flex-basis: 90px; }
}
</style>

<style scoped>
.dataset-sample-card :deep(.dataset-sample-image) { height:164px; }
.dataset-list-thumbnail { height:44px; width:60px; border-radius:var(--am-radius-sm); }
.dataset-selection-actions { margin-left:auto; }
.dataset-card-selection input:not(:checked) { border-color:var(--am-text-muted); }
.dataset-sample-pagination :deep(.pagination-controls) { padding:8px 0; border:0; background:transparent; }
.dataset-view-controls :deep(.ui-button.is-active) { color:var(--am-brand-on-primary); background:var(--am-brand-primary); }
.dataset-sample-filters .dataset-sort-filter { margin-left:auto; display:flex; align-items:center; flex:0 1 130px; max-width:130px; }
.dataset-sample-filters .dataset-sort-filter > div { flex:1; }
.dataset-stats { grid-template-columns: .8fr .8fr .8fr 1.4fr 1.5fr; }
@media(max-width:1200px) { .dataset-sample-filters .dataset-sort-filter { margin-left:0; } }
</style>
