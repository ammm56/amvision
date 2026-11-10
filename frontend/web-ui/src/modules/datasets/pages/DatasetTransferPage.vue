<template>
  <section class="dataset-workspace transfer-workspace">
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
        :aria-current="step === index ? 'step' : undefined"
        :class="{ 'is-active': step === index, 'is-complete': step > index, 'has-error': step===3 && index===3 && (importing ? (preview?.issues.length || importMismatch) : exportBlocked) }"
      >
        <span
          ><Check v-if="index < step" :size="15" /><template v-else>{{
            index + 1
          }}</template></span
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
      <div v-if="step > 0" class="transfer-summary">
        <component :is="importing ? FileArchive : Database" :size="20" />
        <strong>{{
          importing
            ? file?.name
            : selected?.display_name || selected?.dataset_id
        }}</strong>
        <span>{{
          importing ? formatSize(file?.size) : 'v' + selected?.version_number
        }}</span>
        <span v-if="importing && preview?.format">{{ preview.format }}</span
        ><span v-if="!importing">{{ selected?.task_type }}</span>
        <span v-if="step === 3 && importing && preview?.objects != null"
          >{{ preview.objects }} {{ label('个对象', 'objects') }}</span
        ><span v-if="step === 3 && !importing">→ {{ exportFormat }}</span>
        <span v-if="(importing ? preview?.samples : exportCount) != null"
          >{{ importing ? preview?.samples : exportCount }}
          {{ text('samples') }}</span
        >
      </div>
      <fieldset :disabled="busy" class="dataset-wizard-fields">
        <template v-if="importing">
          <template v-if="step === 0"
            ><h2>{{ label('上传数据集文件', 'Upload dataset file') }}</h2>
            <FilePicker
              class="transfer-drop"
              :show-label="false"
              :description="
                label(
                  '拖入 ZIP 文件，或点击选择',
                  'Drop a ZIP file or choose one',
                )
              "
              v-model="packageFile"
              icon="upload"
              accept=".zip,application/zip"
              :label="label('ZIP 文件', 'ZIP file')"
            />
            <h2 v-if="file">{{ label('上传文件', 'Uploaded file') }}</h2>
            <ResourceTable
              v-if="file"
              class="dataset-table"
              :label="text('file')"
              ><thead>
                <tr>
                  <th>{{ text('fileName') }}</th>
                  <th>{{ label('大小', 'Size') }}</th>
                  <th>{{ text('status') }}</th>
                  <th>{{ label('上传时间', 'Uploaded at') }}</th>
                  <th>{{ text('actions') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td :title="file.name">
                    <FileArchive :size="15" class="file-inline-icon" />
                    {{ file.name }}
                  </td>
                  <td>{{ formatSize(file.size) }}</td>
                  <td :class="{ 'upload-complete': draft && !scanError }">
                    <Check
                      v-if="draft && !scanError"
                      :size="14"
                      aria-hidden="true"
                      class="file-inline-icon"
                    />
                    {{
                      uploadError
                        ? label('上传中断', 'Upload interrupted')
                        : uploading
                          ? label('上传中', 'Uploading')
                          : scanError
                            ? label('读取失败', 'Read failed')
                            : label('上传完成', 'Uploaded')
                    }}
                  </td>
                  <td>{{ draft ? datasetDate(uploadedAt) : '—' }}</td>
                  <td>
                    <Button size="sm" @click="packageFile = null">{{
                      text('remove')
                    }}</Button>
                  </td>
                </tr>
              </tbody></ResourceTable
            >
            <InlineError v-if="uploadError" :message="uploadError" /><Button
              v-if="uploadError && file"
              @click="uploadFile(file)"
              >{{ label('重新上传', 'Retry upload') }}</Button
            >
            <InlineError v-if="scanError" :message="scanError" /><Button
              v-if="scanError && file"
              @click="inspectZip(file)"
              >{{ label('重新读取', 'Read again') }}</Button
            > </template
          ><template v-if="step === 1"
            ><h2>{{ steps[1] }}</h2>
            <div v-if="!route.query.dataset" class="field">
              <span>{{ label('导入方式', 'Destination') }}</span>
              <div class="transfer-choices">
                <label
                  ><input
                    type="radio"
                    :checked="!existingMode"
                    @change="chooseDestination(false)"
                  />
                  {{ label('新建数据集', 'New dataset') }}</label
                ><label
                  ><input
                    type="radio"
                    :checked="existingMode"
                    @change="chooseDestination(true)"
                  />
                  {{
                    label(
                      '已有数据集的新版本',
                      'New version of existing dataset',
                    )
                  }}</label
                >
              </div>
            </div>
            <label v-if="existingMode && !route.query.dataset" class="field"
              ><span>{{ text('datasets') }}</span
              ><SelectField
                :model-value="existing?.dataset_id || ''"
                :options="
                  destinations.map((d) => ({
                    value: d.dataset_id,
                    label: d.display_name,
                  }))
                "
                @update:model-value="setExisting(String($event))"
            /></label>
            <label v-if="!existingMode || route.query.dataset" class="field"
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
              <summary>
                {{ label('ZIP 清单格式', 'ZIP manifest format') }}
              </summary>
              <pre class="dataset-json">{{ mediaExample }}</pre>
            </details>
          </template>
          <template v-if="step === 2"
            ><h2>{{ steps[2] }}</h2>
            <div v-if="canMapClasses" class="field field--wide">
              <span>{{
                label('类别重命名（可选）', 'Rename classes (optional)')
              }}</span>
              <ResourceTable
                v-if="classMap.length"
                class="dataset-table"
                :label="text('classes')"
                ><thead>
                  <tr>
                    <th>ID</th>
                    <th>{{ label('源类别', 'Source class') }}</th>
                    <th>{{ label('目标类别', 'Target class') }}</th>
                    <th>{{ label('对象数', 'Objects') }}</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, index) in classMap" :key="index">
                    <td>
                      {{
                        preview?.classes.find((c) => c.name === row.source)
                          ?.id ?? '—'
                      }}
                    </td>
                    <td>
                      <input
                        v-model="row.source"
                        :aria-label="label('来源类别', 'Source class')"
                      />
                    </td>
                    <td>
                      <input
                        v-model="row.target"
                        :aria-label="label('目标类别', 'Target class')"
                      />
                    </td>
                    <td>
                      {{
                        preview?.classes.find((c) => c.name === row.source)
                          ?.count ?? '—'
                      }}
                    </td>
                    <td>
                      <Button
                        icon-only
                        :aria-label="text('remove')"
                        @click="classMap.splice(index, 1)"
                        ><X :size="14"
                      /></Button>
                    </td>
                  </tr></tbody
              ></ResourceTable>
              <Button
                class="dataset-add-map"
                @click="classMap.push({ source: '', target: '' })"
                ><Plus :size="16" />{{
                  label('添加映射', 'Add mapping')
                }}</Button
              >
            </div>
            <div class="field">
              <span>{{ text('splits') }}</span>
              <div class="transfer-choices">
                <label v-for="option in splitOptions" :key="option.value"
                  ><input
                    type="radio"
                    v-model="split"
                    :value="option.value"
                  />{{ option.label }}</label
                >
              </div>
            </div>
            <div
              v-if="split === 'redistribute'"
              class="transfer-choices split-ratios"
            >
              <label v-for="(key, i) in ['train', 'val', 'test']" :key="key"
                >{{ key }} %
                <input
                  v-model.number="ratios[i]"
                  type="number"
                  min="0"
                  max="100" /></label
              ><label
                >{{ label('随机种子', 'Seed')
                }}<input
                  v-model.number="seed"
                  type="number"
                  min="0"
                  max="2147483647"
              /></label>
            </div>
            <label v-if="split === 'fixed'" class="field"
              ><span>{{ label('目标划分', 'Target split') }}</span
              ><SelectField
                v-model="fixedSplit"
                :options="
                  ['train', 'val', 'test'].map((value) => ({
                    value,
                    label: value,
                  }))
                "
            /></label>
            <ResourceTable
              v-if="Object.keys(effectiveSplits).length"
              class="dataset-table"
              :label="text('splits')"
              ><thead>
                <tr>
                  <th>{{ text('splits') }}</th>
                  <th>{{ text('samples') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="key in ['train', 'val', 'test']" :key="key">
                  <td>{{ key }}</td>
                  <td>{{ effectiveSplits[key] ?? '—' }}</td>
                </tr>
              </tbody></ResourceTable
            >
          </template>
          <template v-if="step === 3">
            <DatasetTransferReview
              :files="preview?.files || []"
              :file-title="text('structure')"
              :title="label('检查结果', 'Check results')"
              :checks="importChecks"
              :note="
                preview && preview.fileCount > preview.files.length
                  ? label('仅展示前 2000 个文件', 'First 2,000 files shown')
                  : ''
              "
            >
              <template v-if="preview?.issues.length"
                ><InlineError
                  :message="
                    label(
                      '文件检查未通过，补齐文件后重新选择 ZIP。',
                      'File check failed. Fix the files and select the ZIP again.',
                    )
                  "
                />
                <ul class="transfer-issues">
                  <li v-for="issue in preview.issues" :key="issue">
                    {{ issue }}
                  </li>
                </ul>
                <Button @click="step = 0">{{
                  label('重新选择 ZIP', 'Choose another ZIP')
                }}</Button></template
              >
              <dl class="transfer-facts">
                <dt>{{ text('datasets') }}</dt>
                <dd>{{ name }}</dd>
                <dt>{{ text('task') }}</dt>
                <dd>{{ text(taskType) }}</dd>
                <dt>{{ text('classes') }}</dt>
                <dd>{{ preview?.classes.length || '—' }}</dd>
                <dt>{{ text('splits') }}</dt>
                <dd>
                  {{
                    split === 'auto'
                      ? label('沿用原划分', 'Keep source splits')
                      : split === 'fixed'
                        ? fixedSplit
                        : ratios.join(' / ') + ' %'
                  }}
                </dd>
              </dl>
            </DatasetTransferReview>
          </template></template
        >
        <template v-else>
          <template v-if="step === 0"
            ><p v-if="selection" class="field--wide">
              {{ label('导出所选样本', 'Export selected samples') }} ·
              {{ selectionCounts?.sample_count ?? '…' }}
            </p>
            <label class="field"
              ><span>{{ text('datasets') }}</span
              ><SelectField
                :model-value="sourceDataset"
                :options="
                  destinations.map((d) => ({
                    value: d.dataset_id,
                    label: d.display_name,
                  }))
                "
                @update:model-value="changeSource(String($event))"
            /></label>
            <h2>{{ label('选择来源版本', 'Select source version') }}</h2>
            <ResourceTable
              class="dataset-table field--wide"
              :label="text('versions')"
              ><thead>
                <tr>
                  <th class="transfer-radio-col"></th>
                  <th>{{ text('version') }}</th>
                  <th>{{ text('task') }}</th>
                  <th>{{ text('samples') }}</th>
                  <th>{{ label('对象数', 'Objects') }}</th>
                  <th>{{ text('created') }}</th>
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
                  <td>
                    <input
                      type="radio"
                      name="source-version"
                      :aria-label="
                        (item.display_name || item.dataset_id) +
                        ' v' +
                        item.version_number
                      "
                      :checked="
                        selected?.dataset_version_id === item.dataset_version_id
                      "
                      @click.stop="selectVersion(item)"
                    />
                  </td>
                  <td :title="item.display_name || item.dataset_id">
                    {{ item.display_name || item.dataset_id }}
                  </td>
                  <td>
                    {{ `v${item.version_number}` }}
                  </td>
                  <td>{{ text(item.task_type) }}</td>
                  <td>{{ item.sample_count }}</td>
                  <td>{{ item.object_count }}</td>
                  <td>{{ datasetDate(item.created_at) }}</td>
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
            ><h2>{{ label('选择目标格式', 'Select target format') }}</h2>
            <label
              v-for="option in exportOptions"
              :key="option.value"
              class="format-option"
              :class="{ chosen: exportFormat === option.value }"
              ><input
                type="radio"
                v-model="exportFormat"
                :value="option.value"
                name="export-format"
              /><span
                ><strong>{{ option.label }}</strong
                ><small>{{ formatHint(option.value) }}</small></span
              ></label
            >
            <p v-if="!exportOptions.length" class="field--wide">
              {{
                label(
                  '当前任务类型没有可用的导出格式。',
                  'No export format is available for this task type.',
                )
              }}
            </p>
            <label class="field"
              ><span>{{ label('输出文件名', 'Output file name') }}</span
              ><input
                v-model="displayName"
                maxlength="180"
                placeholder="dataset.zip" /></label
          ></template>
          <template v-if="step === 2"
            ><h2>{{ label('类别映射', 'Class mapping') }}</h2>
            <ResourceTable
              v-if="exportClasses.length"
              class="dataset-table"
              :label="text('classes')"
              ><thead>
                <tr>
                  <th v-if="canFilterClasses">
                    {{ label('包含', 'Include') }}
                  </th>
                  <th>{{ label('源类别', 'Source class') }}</th>
                  <th>ID</th>
                  <th>{{ label('目标名称', 'Target name') }}</th>
                  <th>{{ label('对象数', 'Objects') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in exportClasses" :key="row.id">
                  <td v-if="canFilterClasses">
                    <input
                      type="checkbox"
                      v-model="row.enabled"
                      :aria-label="row.source"
                      @change="renumberClasses"
                    />
                  </td>
                  <td>{{ row.source }}</td>
                  <td>
                    <input
                      v-if="canFilterClasses"
                      type="number"
                      min="0"
                      v-model.number="row.output"
                      :disabled="!row.enabled"
                      :aria-label="row.source + ' ID'"
                    /><template v-else>{{ row.id }}</template>
                  </td>
                  <td>
                    <input
                      :disabled="!row.enabled"
                      v-model="row.target"
                      :aria-label="row.source"
                    />
                  </td>
                  <td>
                    {{
                      sourceStats.find((c) => c.category_id === row.id)
                        ?.object_count ?? '—'
                    }}
                  </td>
                </tr>
              </tbody></ResourceTable
            >
            <h2>{{ text('splits') }}</h2>
            <ResourceTable class="dataset-table" :label="text('splits')"
              ><thead>
                <tr>
                  <th>{{ label('包含', 'Include') }}</th>
                  <th>{{ text('splits') }}</th>
                  <th>{{ text('samples') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="key in ['train', 'val', 'test']" :key="key">
                  <td>
                    <input
                      type="checkbox"
                      :value="key"
                      v-model="includedSplits"
                      :disabled="!sourceCounts[key]"
                      :aria-label="key"
                    />
                  </td>
                  <td>{{ key }}</td>
                  <td>{{ sourceCounts[key] ?? '—' }}</td>
                </tr>
              </tbody></ResourceTable
            >
          </template>
          <template v-if="step === 3"
            ><InlineError
              v-if="exportBlocked"
              :message="
                label(
                  '当前来源与导出配置不兼容，请调整目标格式或划分。',
                  'Source and export settings are incompatible. Change the target format or splits.',
                )
              "
            /><DatasetTransferReview
              :files="plannedFiles"
              :file-title="label('预计文件结构', 'Expected file structure')"
              :title="steps[3]"
              :checks="exportChecks"
              :note="
                label(
                  '实际文件清单在导出完成后生成。',
                  'The final file list is available after export.',
                )
              "
            >
              <template v-if="exportBlocked" #comparison>
                <h3>{{ label('格式对照', 'Format comparison') }}</h3>
                <dl class="transfer-facts comparison-facts">
                  <dt>{{ label('来源任务', 'Source task') }}</dt>
                  <dd>{{ text(selected?.task_type || '') }}</dd>
                  <dt>{{ label('目标格式', 'Target format') }}</dt>
                  <dd>{{ exportFormat }}</dd>
                  <dt>{{ label('支持的任务', 'Supported tasks') }}</dt>
                  <dd>{{ targetTasks || '—' }}</dd>
                </dl>
                <DatasetSampleImage
                  v-if="comparisonSample && selected"
                  class="comparison-image"
                  :dataset-id="selected.dataset_id"
                  :sample="comparisonSample"
                  :categories="selected.categories"
                  :show-annotations="true"
                />
              </template>
              <dl class="transfer-facts">
                <dt>{{ text('samples') }}</dt>
                <dd>{{ exportCount }}</dd>
                <dt>{{ text('classes') }}</dt>
                <dd>{{ enabledClasses.length }}</dd>
                <dt>{{ text('splits') }}</dt>
                <dd>{{ includedSplits.join(' / ') || '—' }}</dd>
              </dl>
              <ResourceTable
                v-if="enabledClasses.length"
                class="dataset-table"
                :label="text('classes')"
                ><thead>
                  <tr>
                    <th>{{ label('源类别', 'Source class') }}</th>
                    <th>{{ label('目标 ID', 'Target ID') }}</th>
                    <th>{{ label('目标名称', 'Target name') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in enabledClasses" :key="row.id">
                    <td>{{ row.source }}</td>
                    <td>{{ row.output }}</td>
                    <td>{{ row.target }}</td>
                  </tr>
                </tbody></ResourceTable
              ><Button v-if="exportBlocked" variant="primary" @click="step = 1">{{
                label('更换目标格式', 'Change target format')
              }}</Button></DatasetTransferReview
            ></template
          >
        </template>
      </fieldset>
      <footer class="dataset-wizard-footer">
        <Button
          :disabled="busy"
          @click="step ? previousStep() : router.push('/datasets')"
          >{{ step ? label('上一步', 'Previous') : text('cancel') }}</Button
        >
        <div class="dataset-actions">
          <Button
            type="submit"
            variant="primary"
            :loading="busy"
            :disabled="
              busy ||
              !canWrite ||
              (importing
                ? scanBusy ||
                  uploading ||
                  !draft ||
                  !file ||
                  !!scanError ||
                  (step === 3 && (!!preview?.issues.length || importMismatch))
                : !selected || (step === 3 && exportBlocked))
            "
            >{{
              step === 3
                ? importing
                  ? label('提交导入', 'Submit import')
                  : label('创建导出', 'Create export')
                : label('下一步', 'Next')
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
import { ArrowLeft, Database, FileArchive, Check, Plus, X } from '@lucide/vue'
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
import DatasetTransferReview from '../components/DatasetTransferReview.vue'
import DatasetSampleImage from '../components/DatasetSampleImage.vue'
import { apiRequest } from '@/shared/api/http-client'
import ArchiveWorker from '../archive-preview.worker?worker'
import type { ArchivePreview } from '../archive-preview.worker'
import { datasetDate, useDatasetText, datasetError } from '../dataset-workspace'
import {
  submitDatasetImport,
  createDatasetExport,
  getDatasetExportFormats,
  type DatasetExportFormatCatalog,
  type DatasetSampleSelection,
} from '../services/dataset.service'
import {
  getDatasetCategories,
  type CategoryStatistic,
  getDatasetInfo,
  getDatasetSelectionSummary,
  getDatasetWorkspace,
  listDatasetCatalog,
  listDatasetSamples,
  type DatasetSample,
  type DatasetWorkspace,
  type DatasetItem,
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
  projectId = project.selectedProjectId
const steps = computed(() =>
  importing
    ? [
        label('上传 ZIP', 'Upload ZIP'),
        label('数据定义', 'Dataset'),
        label('类别与划分', 'Classes and splits'),
        label('检查并提交', 'Review and submit'),
      ]
    : [
        label('来源版本', 'Source version'),
        label('目标格式', 'Target format'),
        label('类别与划分', 'Classes and splits'),
        label('兼容检查', 'Compatibility check'),
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
  fixedSplit = ref('train'),
  ratios = ref([80, 20, 0]),
  seed = ref(42),
  classMap = ref<{ source: string; target: string }[]>([])
const mediaExample = computed(() => {
  const examples: Record<string, Record<string, unknown>> = {
    anomaly: { image: 'surface.png', label: 'anomaly', defect: 'scratch' },
    'connector-reference': {
      image: 'connector.png',
      synthetic: true,
      unit: 'mm',
      pitch: 2.54,
      pins: [{ id: 'P1', x: 120, y: 80 }],
    },
    rgbd: {
      image: 'color.png',
      depth: 'depth.png',
      unit: 'mm',
      scale: 1,
      invalid: 0,
    },
    'point-cloud': { cloud: 'part.ply', unit: 'mm', frame: 'scanner' },
  }
  return (
    'samples.json\n' +
    JSON.stringify(
      {
        format_id: 'amvision.sample-media.v1',
        task_type: taskType.value,
        samples: [
          { id: 'sample-1', split: 'train', ...examples[taskType.value] },
        ],
      },
      null,
      2,
    )
  )
})
const packageFile = computed<File | File[] | null>({
  get: () => file.value,
  set: (value) => {
    file.value = Array.isArray(value) ? value[0] || null : value
  },
})
const newId = String(
  route.query.dataset || `dataset-${crypto.randomUUID().replaceAll('-', '')}`,
)
const existingMode = ref(!!route.query.dataset),
  destinations = ref<DatasetItem[]>([])
const datasetId = computed(() => existing.value?.dataset_id || newId)
function setExisting(id: string) {
  existing.value = destinations.value.find((d) => d.dataset_id === id) || null
  name.value = existing.value?.display_name || ''
  description.value = existing.value?.description || ''
  if (existing.value) taskType.value = existing.value.task_type
}
async function loadDestinations() {
  const list: DatasetItem[] = []
  for (let offset = 0; active; offset += 100) {
    const page = await listDatasetCatalog({
      project_id: projectId,
      limit: 100,
      offset,
    })
    list.push(...page.items)
    if (!page.items.length || list.length >= page.total) break
  }
  if (active) destinations.value = list
}
async function chooseDestination(mode: boolean) {
  existingMode.value = mode
  setExisting('')
  if (!mode) return
  try {
    if (!destinations.value.length) await loadDestinations()
    if (existingMode.value) setExisting(destinations.value[0]?.dataset_id || '')
  } catch (e) {
    error.value = datasetError(e)
  }
}
const preview = ref<ArchivePreview | null>(null),
  scanBusy = ref(false),
  scanError = ref('')
let archiveWorker: Worker | undefined
const uploadedAt = ref('')
const draft = ref(''),
  uploading = ref(false),
  uploadError = ref('')
let uploadController: AbortController | undefined
function discardDraft(id: string) {
  if (id)
    void apiRequest('/datasets/upload-drafts/' + id, {
      method: 'DELETE',
      query: { project_id: projectId },
    }).catch(() => {})
}
async function uploadFile(input: File | null) {
  uploadController?.abort()
  discardDraft(draft.value)
  draft.value = ''
  uploadError.value = ''
  uploading.value = !!input
  if (!input) return
  const ctl = (uploadController = new AbortController())
  try {
    const form = new FormData()
    form.set('project_id', projectId)
    form.set('package', input)
    const r = await apiRequest<{ draft_id: string }>(
      '/datasets/upload-drafts',
      { method: 'POST', body: form, signal: ctl.signal },
    )
    if (!active || ctl.signal.aborted) {
      discardDraft(r.draft_id)
      return
    }
    draft.value = r.draft_id
    uploadedAt.value = new Date().toISOString()
  } catch (e) {
    if (active && !ctl.signal.aborted) uploadError.value = datasetError(e)
  } finally {
    if (active && ctl === uploadController) uploading.value = false
  }
}
function inspectZip(input: File | null) {
  archiveWorker?.terminate()
  preview.value = null
  classMap.value = []
  scanError.value = ''
  scanBusy.value = !!input
  if (!input) return
  const w = (archiveWorker = new ArchiveWorker())
  const finish = () => {
    w.terminate()
    scanBusy.value = false
  }
  w.onmessage = ({ data }) => {
    if (w !== archiveWorker) return
    finish()
    if (data.error) {
      scanError.value = String(data.error)
      return
    }
    const r = data.result as ArchivePreview
    preview.value = r
    if (!existingMode.value && !name.value.trim())
      name.value = input.name.replace(/\.zip$/i, '')
    if (
      r.task &&
      !existing.value &&
      taskOptions.value.some((t) => t.value === r.task)
    )
      taskType.value = r.task
    classMap.value = r.classes.map((c) => ({ source: c.name, target: c.name }))
  }
  w.onerror = () => {
    if (w === archiveWorker) {
      finish()
      scanError.value = label(
        '无法读取 ZIP，请重新选择文件',
        'Cannot read ZIP. Choose a file again.',
      )
    }
  }
  w.postMessage(input)
}
watch(file, (input) => {
  inspectZip(input)
  void uploadFile(input)
})
function formatSize(bytes?: number) {
  return bytes == null
    ? '—'
    : bytes >= 1048576
      ? (bytes / 1048576).toFixed(1) + ' MB'
      : (bytes / 1024).toFixed(1) + ' KB'
}
function formatHint(id: string) {
  return /coco/i.test(id)
    ? label('图像和共享 JSON 标注', 'Images with shared JSON annotations')
    : /voc/i.test(id)
      ? label('每张图像对应 XML 标注', 'XML annotations per image')
      : /yolo/i.test(id)
        ? label('图像与 YOLO 数据文件', 'Images and YOLO dataset files')
        : label(
            '按此格式组织数据及清单',
            'Package data and manifest in this format',
          )
}
const effectiveSplits = computed<Record<string, number | null | undefined>>(
  () =>
    split.value === 'auto'
      ? preview.value?.splits || {}
      : split.value === 'fixed'
        ? { [fixedSplit.value]: preview.value?.samples }
        : {},
)
const importChecks = computed(() => [
  {
    name: label('ZIP 目录', 'ZIP directory'),
    state: 'pass',
    value:
      String(preview.value?.fileCount ?? 0) +
      (preview.value?.limited ? '+' : '') +
      ' ' +
      label('个文件', 'files'),
  },
  {
    name: label('文件引用', 'File references'),
    state: preview.value?.issues.length
      ? 'error'
      : preview.value?.format === 'coco' ||
          preview.value?.format === 'amvision-media'
        ? 'pass'
        : 'info',
    value: preview.value?.issues.length
      ? label('请修正下列文件', 'Correct the files below')
      : preview.value?.format === 'coco' ||
          preview.value?.format === 'amvision-media'
        ? label('已读取清单', 'Manifest read')
        : label('由后台校验', 'Checked by worker'),
  },
  {
    name: label('任务与格式', 'Task and format'),
    state: importMismatch.value
      ? 'error'
      : preview.value?.format
        ? 'pass'
        : 'info',
    value: importMismatch.value
      ? label('所选任务或格式与 ZIP 不符', 'Selection does not match the ZIP')
      : preview.value?.format || label('后台识别', 'Detected by worker'),
  },
  {
    name: label('图片与标注校验', 'Image and annotation validation'),
    state: 'info',
    value: label('提交后执行', 'Runs after submission'),
  },
])
const importMismatch = computed(
  () =>
    !!preview.value &&
    ((!!preview.value.task && preview.value.task !== taskType.value) ||
      (!!formatType.value &&
        !!preview.value.format &&
        formatType.value !== preview.value.format)),
)
const sourceCounts = computed(
  () => (selectionCounts.value || selected.value)?.split_counts || {},
)
const exportBlocked = computed(
  () =>
    !exportCount.value ||
    !exportOptions.value.some((o) => o.value === exportFormat.value),
)
const comparisonSample = ref<DatasetSample>()
const targetTasks = computed(() =>
  Object.entries(exportFormats.value?.format_types_by_task_type || {})
    .filter(([, ids]) => ids.includes(exportFormat.value))
    .map(([task]) => text(task))
    .join(' / '),
)
watch(
  () => (step.value === 3 && exportBlocked.value ? selected.value : null),
  async (source, _, cleanup) => {
    comparisonSample.value = undefined
    if (!source) return
    const controller = new AbortController()
    cleanup(() => controller.abort())
    try {
      const result = await listDatasetSamples(
        source.dataset_id,
        source.dataset_version_id,
        { limit: 1 },
        controller.signal,
      )
      if (!controller.signal.aborted) comparisonSample.value = result.items[0]
    } catch {
      /* 文件暂不可读时仍可检查格式并返回修改。 */
    }
  },
)
const plannedFiles = computed(() => {
  const id = exportFormat.value
  if (id.startsWith('amvision-')) return ['samples.json', 'assets/']
  const paths = ['manifest.json']
  for (const split of includedSplits.value) {
    if (id.includes('coco'))
      paths.push(
        'images/' + split + '/',
        'annotations/' +
          (id.includes('keypoint') ? 'person_keypoints_' : 'instances_') +
          split +
          '.json',
      )
    else if (id.includes('yolo'))
      paths.push('images/' + split + '/', 'labels/' + split + '/')
    else if (id.includes('imagenet'))
      paths.push(
        ...enabledClasses.value.map((c) => split + '/' + c.target + '/'),
      )
  }
  return paths
})
const exportChecks = computed(() => [
  {
    name: label('来源版本', 'Source version'),
    state: selected.value ? 'pass' : 'error',
    value: selected.value ? 'v' + selected.value.version_number : '—',
  },
  {
    name: label('任务与格式', 'Task and format'),
    state: exportOptions.value.some((o) => o.value === exportFormat.value)
      ? 'pass'
      : 'error',
    value: exportFormat.value || '—',
  },
  {
    name: label('导出范围', 'Export selection'),
    state: exportCount.value > 0 ? 'pass' : 'error',
    value: exportCount.value + ' ' + text('samples'),
  },
])
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
  { value: 'redistribute', label: label('重新划分', 'Redistribute') },
  { value: 'fixed', label: label('指定划分', 'Assign one split') },
])
const exportFormats = ref<DatasetExportFormatCatalog | null>(null),
  exportFormat = ref(''),
  includedSplits = ref<string[]>([]),
  displayName = ref(''),
  selected = ref<DatasetWorkspace | null>(null),
  versions = ref<DatasetVersion[]>([]),
  sourceDataset = ref(String(route.query.dataset || '')),
  sourceOffset = ref(0),
  sourceTotal = ref(0),
  exportClasses = ref<
    {
      id: number
      source: string
      target: string
      output: number
      enabled: boolean
    }[]
  >([])
const sourceStats = ref<CategoryStatistic[]>([])
const exportOptions = computed(() =>
  (
    exportFormats.value?.format_types_by_task_type[
      selected.value?.task_type || ''
    ] || []
  ).map((value) => ({ value, label: value })),
)
const exportCount = computed(() =>
  includedSplits.value.reduce(
    (sum, key) => sum + (sourceCounts.value[key] || 0),
    0,
  ),
)
const canFilterClasses = computed(() =>
  ['detection', 'segmentation', 'pose', 'obb'].includes(
    selected.value?.task_type || '',
  ),
)
const enabledClasses = computed(() =>
  exportClasses.value
    .filter((row) => row.enabled)
    .sort((a, b) => a.output - b.output),
)
function renumberClasses() {
  enabledClasses.value.forEach((r, index) => {
    r.output = index
  })
}
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
      dataset_id: sourceDataset.value,
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
async function selectVersion(
  version: Pick<DatasetVersion, 'dataset_id' | 'dataset_version_id'>,
) {
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
    if (
      selection.value &&
      saved?.revision !== undefined &&
      saved.revision !== String(result.metadata.content_revision || '')
    ) {
      throw new Error(
        label(
          '当前版本已更新，请返回重新选择样本。',
          'This version has changed. Go back and select samples again.',
        ),
      )
    }
    const counts = selection.value
      ? await getDatasetSelectionSummary(
          result.dataset_id,
          result.dataset_version_id,
          selection.value,
        )
      : null
    if (!active || id !== selectionGeneration) return
    const stats = selection.value
      ? []
      : (
          await getDatasetCategories(
            result.dataset_id,
            result.dataset_version_id,
          ).catch(() => ({ items: [] }))
        ).items
    if (!active || id !== selectionGeneration) return
    sourceStats.value = stats
    selectionCounts.value = counts
    selected.value = result
    exportClasses.value = result.categories.map((c, index) => ({
      output: index,
      enabled: true,
      id: c.category_id,
      source: c.name,
      target: c.name,
    }))
    exportFormat.value = exportOptions.value[0]?.value || ''
    includedSplits.value = Object.keys((counts || result).split_counts).filter(
      (k) => (counts || result).split_counts[k],
    )
    displayName.value =
      (result.display_name || result.dataset_id)
        .replace(/[<>:"/\\|?*]/g, '_')
        .slice(0, 110) +
      '-v' +
      result.version_number +
      '.zip'
  } catch (e) {
    if (active && id === selectionGeneration) error.value = datasetError(e)
  } finally {
    if (active && id === selectionGeneration) busy.value = false
  }
}
const canMapClasses = computed(
  () => !isMediaTask(taskType.value) || taskType.value === 'anomaly',
)
watch(taskType, () => {
  if (!canMapClasses.value) classMap.value = []
  if (!formatOptions.value.some((item) => item.value === formatType.value))
    formatType.value = ''
})
async function next() {
  if (
    busy.value ||
    unknown.value ||
    (importing && !draft.value) ||
    scanBusy.value ||
    (importing &&
      (scanError.value ||
        (step.value === 3 &&
          (preview.value?.issues.length || importMismatch.value)))) ||
    (!importing && step.value === 3 && exportBlocked.value)
  )
    return
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
      ((existingMode.value && !existing.value) ||
        !name.value.trim() ||
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
      split.value === 'redistribute' &&
      (ratios.value.some((n) => !Number.isInteger(n) || n < 0 || n > 100) ||
        ratios.value.reduce((a, b) => a + b, 0) !== 100 ||
        !Number.isInteger(seed.value) ||
        seed.value < 0 ||
        seed.value > 2147483647)
    ) {
      error.value = label(
        '划分比例须合计为 100%，请填写有效的种子。',
        'Split percentages must total 100%. Enter a valid seed.',
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
      step.value === 1 &&
      displayName.value &&
      (!displayName.value.toLowerCase().endsWith('.zip') ||
        /[<>:"/\\|?*]/.test(displayName.value))
    ) {
      error.value = label(
        '请输入有效的 ZIP 文件名',
        'Enter a valid ZIP filename',
      )
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
      (!exportCount.value ||
        (canFilterClasses.value &&
          !enabledClasses.value.length &&
          exportClasses.value.length > 0) ||
        enabledClasses.value.some(
          (row, index) =>
            !row.target.trim() ||
            (canFilterClasses.value && row.output !== index),
        ) ||
        new Set(enabledClasses.value.map((row) => row.target.trim())).size !==
          enabledClasses.value.length)
    ) {
      error.value = label(
        '请选择有样本的划分和类别，名称须唯一，目标 ID 从 0 连续编号。',
        'Select populated splits and classes with unique names and consecutive IDs from 0.',
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
        datasetId: datasetId.value,
        draftId: draft.value,
        formatType: formatType.value || undefined,
        taskType: taskType.value,
        splitStrategy: split.value === 'fixed' ? fixedSplit.value : 'auto',
        splitRatios: split.value === 'redistribute' ? ratios.value : undefined,
        splitSeed: split.value === 'redistribute' ? seed.value : undefined,
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
      draft.value = ''
      await router.push(`/datasets/imports/${result.dataset_import_id}`)
    } else {
      const source = selected.value!
      const result = await createDatasetExport({
        projectId,
        datasetId: source.dataset_id,
        datasetVersionId: source.dataset_version_id,
        formatId: exportFormat.value,
        packageName: displayName.value.trim(),
        includedSplits: includedSplits.value,
        sourceCategoryIds: exportClasses.value.some(
          (row, i) =>
            row.target.trim() !== row.source ||
            !row.enabled ||
            row.output !== i,
        )
          ? enabledClasses.value.map((r) => r.id)
          : undefined,
        includeTestSplit: includedSplits.value.includes('test'),
        selection: selection.value,
        categoryNames: enabledClasses.value.map((row) => row.target.trim()),
      })
      submitted.value = true
      busy.value = false
      await router.push(`/datasets/exports/${result.dataset_export_id}`)
    }
  } catch (e) {
    error.value = datasetError(e)
    if (importing && e instanceof ApiError && e.status === 404) {
      draft.value = ''
      uploadError.value = label(
        '上传草稿已过期或不存在，请重新上传',
        'Upload draft expired or missing. Upload again.',
      )
      step.value = 0
    }
    unknown.value = !(e instanceof ApiError) || e.status >= 500
  } finally {
    busy.value = false
  }
}
onMounted(async () => {
  busy.value = true
  try {
    if (importing && route.query.dataset) {
      existing.value = await getDatasetInfo(projectId, datasetId.value)
      name.value = existing.value.display_name
      description.value = existing.value.description
      taskType.value = existing.value.task_type
    } else if (!importing) {
      exportFormats.value = await getDatasetExportFormats()
      await loadDestinations()
      if (!sourceDataset.value)
        sourceDataset.value = destinations.value[0]?.dataset_id || ''
      await loadVersions()
      const v = String(route.query.version || '')
      if (v && route.query.dataset) {
        await selectVersion({
          dataset_id: String(route.query.dataset),
          dataset_version_id: v,
        })
      } else if (versions.value[0]) await selectVersion(versions.value[0])
      if (selected.value && typeof route.query.format === 'string') {
        exportFormat.value = route.query.format
        if (!exportOptions.value.some((o) => o.value === exportFormat.value))
          step.value = 3
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
  archiveWorker?.terminate()
  uploadController?.abort()
  discardDraft(draft.value)
  selectionGeneration++
  listGeneration++
  answer?.(false)
  window.removeEventListener('beforeunload', unload)
})
async function changeSource(id: string) {
  ++selectionGeneration
  sourceDataset.value = id
  sourceOffset.value = 0
  selected.value = null
  versions.value = []
  selection.value = undefined
  await loadVersions()
  if (active && id === sourceDataset.value && versions.value[0])
    await selectVersion(versions.value[0])
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
  width: 100%;
  max-width: none;
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

.transfer-workspace .dataset-steps {
  background: transparent;
  border: 0;
  padding: 8px 0;
  flex-wrap: nowrap;
  gap: 12px;
}
.transfer-workspace .dataset-steps li {
  min-width: 0;
}
.transfer-workspace .dataset-steps li:not(:last-child)::after {
  content: '';
  height: 1px;
  background: var(--am-border);
  flex: 1;
}
.transfer-workspace .dataset-steps li.is-complete::after {
  background: var(--am-brand-primary);
}
.dataset-wizard-fields {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.dataset-wizard h2 {
  font-size: 16px;
  margin: 0;
}
.dataset-wizard .field:not(.field--wide) {
  display: grid;
  grid-template-columns: 140px minmax(220px, 480px);
  align-items: center;
}
.transfer-summary,
.format-option,
.transfer-choices,
.transfer-choices label {
  display: flex;
  align-items: center;
  gap: 12px;
}
.transfer-summary {
  background: var(--am-surface-muted, var(--am-bg));
  padding: 14px 16px;
  margin-bottom: 20px;
  flex-wrap: wrap;
  border-radius: 6px;
}
.transfer-summary strong {
  overflow-wrap: anywhere;
}
.transfer-choices {
  flex-wrap: wrap;
}
.format-option {
  padding: 12px 16px;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  cursor: pointer;
}
.format-option.chosen {
  background: var(--am-success-surface);
  border-color: var(--am-brand-primary);
}
.format-option small {
  display: block;
  color: var(--am-text-muted);
  margin-top: 3px;
}
.transfer-radio-col {
  width: 44px;
}
.transfer-drop :deep(.file-picker__dropzone) {
  min-height: 155px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  text-align: center;
  border-style: dashed;
  background: var(--am-surface-muted, var(--am-bg));
}
.transfer-drop :deep(.file-picker__icon) {
  background: none;
  color: var(--am-text-muted);
}
.transfer-facts {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr) max-content minmax(0, 1fr);
  gap: 10px 16px;
  padding-top: 18px;
}
.transfer-facts dt {
  color: var(--am-text-muted);
}
.transfer-facts dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.transfer-issues {
  overflow-wrap: anywhere;
}
.dataset-wizard-footer {
  position: sticky;
  bottom: 0;
  background: var(--am-surface);
  z-index: 1;
  padding: 12px 0 0;
}
.dataset-wizard-fields input:not([type='radio']):not([type='checkbox']) {
  min-width: 0;
  max-width: 100%;
}
.dataset-wizard .resource-table {
  min-width: 0;
}
@media (max-height: 800px) {
  .dataset-wizard-footer {
    padding-bottom: 10px;
  }
  .dataset-wizard-fields {
    gap: 12px;
  }
}
.transfer-drop :deep(.file-picker__files),
.transfer-drop
  :deep(.file-picker__actions .ui-button:last-child:not(:first-child)) {
  display: none;
}
.transfer-drop :deep(.file-picker__dropzone) {
  background: var(--am-surface-muted, var(--am-bg));
  border: 1px dashed var(--am-border);
}
.transfer-summary {
  background: var(--am-surface-muted, var(--am-bg));
  margin-bottom: 15px;
}
.transfer-choices input,
.format-option input,
.dataset-table input[type='radio'],
.dataset-table input[type='checkbox'] {
  accent-color: var(--am-brand-primary);
}
.transfer-workspace {
  min-height: calc(100dvh - 64px);
  display: flex;
  flex-direction: column;
}
.dataset-wizard {
  display: flex;
  flex: 1;
  flex-direction: column;
}
.dataset-wizard-footer {
  margin-top: auto;
}
.dataset-wizard-fields {
  padding-bottom: 24px;
}
.transfer-drop :deep(.file-picker__dropzone) {
  min-height: clamp(155px, 24vh, 260px);
}
.transfer-workspace .resource-table thead {
  background: var(--am-surface-subtle, var(--am-bg));
}
.transfer-summary,
.transfer-drop :deep(.file-picker__dropzone) {
  background: color-mix(in srgb, var(--am-text) 4%, var(--am-surface));
}
.split-ratios input {
  width: 85px;
}
.split-ratios {
  padding: 10px 0;
}
.file-inline-icon {
  vertical-align: middle;
}
.upload-complete {
  color: var(--am-success-text);
}
.comparison-image {
  aspect-ratio: 4 / 3;
  max-height: 230px;
  background: var(--am-surface);
}
.comparison-facts {
  grid-template-columns: max-content minmax(0, 1fr);
}
.transfer-workspace .dataset-steps .has-error span {
  background: var(--am-danger-icon);
  border-color: var(--am-danger-icon);
}
</style>
