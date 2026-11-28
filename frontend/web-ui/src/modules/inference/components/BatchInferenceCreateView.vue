<template>
  <section class="inf-batch-create">
    <nav class="inf-bc-breadcrumb" aria-label="创建批量推理">
      <button type="button" class="inf-bc-crumb-link" @click="emit('cancel')">
        推理任务
      </button>
      <ChevronRight :size="14" aria-hidden="true" />
      <span>创建批量推理</span>
    </nav>

    <ol class="inf-bc-stepper" aria-label="创建步骤">
      <li class="inf-bc-step" :class="{ 'is-active': step === 1, 'is-done': step === 2 }">
        <span class="inf-bc-step__num">{{ step > 1 ? '✓' : '1' }}</span>
        <strong>输入与参数</strong>
        <span class="inf-bc-step__line" :class="{ 'is-active': step === 2 }" aria-hidden="true" />
      </li>
      <li class="inf-bc-step inf-bc-step--last" :class="{ 'is-active': step === 2 }">
        <span class="inf-bc-step__num">2</span>
        <strong>检查</strong>
      </li>
    </ol>

    <section v-if="step === 1" class="inf-bc-target-card">
      <div class="inf-bc-target-field">
        <label class="inf-bc-field-label" for="inf-bc-task-name">任务名称 <em>*</em></label>
        <input
          id="inf-bc-task-name"
          v-model="taskName"
          type="text"
          class="inf-bc-input inf-bc-name-input"
          placeholder="例如：零件抽检-1023"
        />
      </div>

      <div class="inf-bc-target-field inf-bc-target-field--deploy">
        <span class="inf-bc-field-label">部署 <em>*</em></span>
        <DeploymentTargetSelect
          :model-value="selectedDeploymentId"
          :deployments="deployments"
          placeholder="选择推理部署"
          aria-label="批量部署实例"
          @update:model-value="selectDeployment"
        />
      </div>

      <div class="inf-bc-async-status">
        <div v-if="asyncReady && syncReady" class="inf-bc-channel-switch" role="group" aria-label="执行通道">
          <button
            type="button"
            class="inf-bc-channel-btn"
            :class="{ 'is-active': selectedRuntimeMode === 'async' }"
            @click="selectedRuntimeMode = 'async'"
          >
            异步通道
          </button>
          <button
            type="button"
            class="inf-bc-channel-btn"
            :class="{ 'is-active': selectedRuntimeMode === 'sync' }"
            @click="selectedRuntimeMode = 'sync'"
          >
            同步通道
          </button>
        </div>
        <span class="inf-dot-status">
          <span
            class="inf-dot"
            :class="!channelStatusChecked ? 'is-neutral' : effectiveChannelReady ? 'is-ok' : 'is-warn'"
          />
          <span>{{ channelStatusText }}</span>
        </span>
        <RouterLink v-if="selectedDeployment && channelStatusChecked && !anyChannelReady" to="/deployments" class="inf-link-nav">
          前往启动
        </RouterLink>
      </div>
    </section>

    <section v-else class="inf-bc-target-card inf-bc-target-card--readonly">
      <div class="inf-bc-ro-item">
        <small class="inf-bc-ro-label">任务名称</small>
        <strong class="inf-bc-ro-val">{{ taskName }}</strong>
      </div>
      <span class="inf-bc-ro-sep" aria-hidden="true" />
      <div class="inf-bc-ro-item inf-bc-ro-item--grow">
        <small class="inf-bc-ro-label">部署</small>
        <strong class="inf-bc-ro-val">{{ selectedDeployment?.display_name || selectedDeploymentId }}</strong>
      </div>
      <div class="inf-bc-async-status">
        <span class="inf-dot-status">
          <span class="inf-dot" :class="effectiveChannelReady ? 'is-ok' : 'is-warn'" />
          <span>{{ channelStatusText }}</span>
        </span>
        <RouterLink v-if="selectedDeployment && channelStatusChecked && !anyChannelReady" to="/deployments" class="inf-link-nav">
          前往启动
        </RouterLink>
      </div>
    </section>

    <InlineError :message="submitError" />

    <div class="inf-bc-grid">
      <section class="inf-bc-left">
        <template v-if="step === 1">
          <div class="inf-bc-left-card">
            <div class="inf-bc-section">
              <div class="inf-bc-source-row">
                <span class="inf-bc-section-label">输入来源</span>
                <SelectField
                  :model-value="sourceKind"
                  :options="sourceKindOptions"
                  aria-label="批量输入来源"
                  floating
                  @update:model-value="switchSourceKind"
                />
                <template v-if="sourceKind === 'upload'">
                  <Button size="sm" variant="secondary" @click="uploadInputRef?.click()">
                    <FolderOpen :size="14" />
                    选择图片
                  </Button>
                  <Button
                    v-if="uploadedItems.length > 0"
                    size="sm"
                    variant="secondary"
                    @click="clearUploadedFiles"
                  >
                    清空
                  </Button>
                </template>
              </div>

              <template v-if="sourceKind === 'upload'">
                <input
                  ref="uploadInputRef"
                  type="file"
                  accept="image/*"
                  multiple
                  class="inf-hidden-input"
                  @change="handleMultiFileSelect"
                />
                <div class="inf-bc-list-head">
                  <strong>输入清单</strong>
                  <span>共 {{ uploadedItems.length }} 张</span>
                </div>

                <div v-if="uploadedItems.length === 0" class="inf-bc-dropzone" @click="uploadInputRef?.click()">
                  <ImageIcon :size="26" />
                  <span>点击选择多张本地图像（JPG、PNG、WEBP、BMP）</span>
                </div>

                <div v-else class="inf-bc-list-box">
                  <table class="inf-bc-mini-table">
                    <thead>
                      <tr>
                        <th>文件名</th>
                        <th class="col-dims">尺寸</th>
                        <th class="col-size">大小</th>
                        <th class="col-op">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="(item, idx) in pagedUploads"
                        :key="item.uid"
                        :class="{ 'is-selected': previewIndex === uploadOffset + idx }"
                        @click="previewIndex = uploadOffset + idx"
                      >
                        <td class="col-fname" :title="item.file.name">
                          <div class="inf-bc-file-cell">
                            <img :src="item.objectUrl" alt="" class="inf-bc-thumb" />
                            <span>{{ item.file.name }}</span>
                          </div>
                        </td>
                        <td class="col-dims">{{ item.width && item.height ? `${item.width} × ${item.height}` : '—' }}</td>
                        <td class="col-size">{{ formatSize(item.file.size) }}</td>
                        <td class="col-op">
                          <button type="button" class="inf-link-danger" @click.stop="removeUploadedItem(uploadOffset + idx)">
                            移除
                          </button>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                  <div v-if="uploadedItems.length > PAGE_SIZE" class="inf-bc-pager">
                    <PaginationControls
                      numbered
                      :offset="uploadOffset"
                      :limit="PAGE_SIZE"
                      :item-count="pagedUploads.length"
                      :total-count="uploadedItems.length"
                      @previous="uploadOffset = Math.max(0, uploadOffset - PAGE_SIZE)"
                      @next="uploadOffset = uploadOffset + PAGE_SIZE"
                      @go="uploadOffset = $event"
                    >
                      <template #summary>共 {{ uploadedItems.length }} 张</template>
                    </PaginationControls>
                  </div>
                </div>
              </template>

              <template v-else-if="sourceKind === 'dataset_version'">
                <div class="inf-bc-ds-filters">
                  <SelectField
                    :model-value="selectedDatasetId"
                    :options="datasetOptions"
                    placeholder="选择数据集"
                    floating
                    @update:model-value="selectDataset"
                  />
                  <SelectField
                    v-if="selectedDatasetId"
                    :model-value="selectedVersionId"
                    :options="versionOptions"
                    placeholder="选择版本"
                    floating
                    @update:model-value="selectVersion"
                  />
                  <SelectField
                    v-if="selectedVersionId"
                    :model-value="datasetSplit"
                    :options="splitOptions"
                    fit-options
                    floating
                    @update:model-value="selectSplit"
                  />
                </div>

                <div class="inf-bc-list-head">
                  <strong>输入清单</strong>
                  <span>共 {{ datasetTotal }} 张</span>
                </div>

                <div class="inf-bc-list-box">
                  <div v-if="datasetLoading" class="inf-bc-state">加载样本中...</div>
                  <div v-else-if="datasetSamples.length === 0" class="inf-bc-state">当前条件下暂无样本</div>
                  <template v-else>
                    <table class="inf-bc-mini-table">
                      <thead>
                        <tr>
                          <th>文件名</th>
                          <th class="col-dims">尺寸</th>
                          <th class="col-split">划分</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr
                          v-for="(sample, idx) in datasetSamples"
                          :key="sample.sample_id"
                          :class="{ 'is-selected': previewIndex === idx }"
                          @click="previewIndex = idx"
                        >
                          <td class="col-fname" :title="sample.file_name">
                            <div class="inf-bc-file-cell">
                              <img
                                v-if="datasetThumbUrls[sample.sample_id]"
                                :src="datasetThumbUrls[sample.sample_id]"
                                alt=""
                                class="inf-bc-thumb"
                              />
                              <span v-else class="inf-bc-thumb-fallback" aria-hidden="true">
                                <ImageIcon :size="14" />
                              </span>
                              <span>{{ sample.file_name }}</span>
                            </div>
                          </td>
                          <td class="col-dims">{{ sample.width }} × {{ sample.height }}</td>
                          <td class="col-split">{{ sample.split }}</td>
                        </tr>
                      </tbody>
                    </table>
                    <div v-if="datasetTotal > PAGE_SIZE" class="inf-bc-pager">
                      <PaginationControls
                        numbered
                        :offset="datasetOffset"
                        :limit="PAGE_SIZE"
                        :item-count="datasetSamples.length"
                        :total-count="datasetTotal"
                        @previous="goDatasetPage(Math.max(0, datasetOffset - PAGE_SIZE))"
                        @next="goDatasetPage(datasetOffset + PAGE_SIZE)"
                        @go="goDatasetPage($event)"
                      >
                        <template #summary>共 {{ datasetTotal }} 张</template>
                      </PaginationControls>
                    </div>
                  </template>
                </div>
              </template>

              <template v-else>
                <div class="inf-bc-pf-filters">
                  <SelectField
                    :model-value="projectScope"
                    :options="projectScopeOptions"
                    floating
                    @update:model-value="selectProjectScope"
                  />
                  <input
                    v-model="projectSearch"
                    type="text"
                    class="inf-bc-input"
                    placeholder="筛选项目文件"
                    @input="projectOffset = 0"
                  />
                  <Button size="sm" variant="secondary" @click="selectAllFilteredProjectFiles">
                    全选 ({{ filteredProjectFiles.length }})
                  </Button>
                </div>

                <div class="inf-bc-list-head">
                  <strong>输入清单</strong>
                  <div class="inf-bc-list-head__right">
                    <span>已选 {{ selectedFileIds.length }} / 共 {{ filteredProjectFiles.length }} 项</span>
                    <button
                      v-if="selectedFileIds.length > 0"
                      type="button"
                      class="inf-link-danger"
                      @click="selectedFileIds = []"
                    >
                      清空所选
                    </button>
                  </div>
                </div>

                <div class="inf-bc-list-box">
                  <div v-if="projectFilesLoading" class="inf-bc-state">加载文件列表中...</div>
                  <div v-else-if="filteredProjectFiles.length === 0" class="inf-bc-state inf-bc-state--col">
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
                  <template v-else>
                    <table class="inf-bc-mini-table">
                      <thead>
                        <tr>
                          <th class="col-check" />
                          <th>文件名</th>
                          <th class="col-size">大小</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr
                          v-for="file in pagedProjectFiles"
                          :key="file.file_id"
                          :class="{ 'is-selected': selectedFileIds.includes(file.file_id) }"
                          @click="toggleProjectFile(file.file_id); syncProjectPreview(file.file_id)"
                        >
                          <td class="col-check">
                            <input
                              type="checkbox"
                              :checked="selectedFileIds.includes(file.file_id)"
                              @click.stop
                              @change="toggleProjectFile(file.file_id)"
                            />
                          </td>
                          <td class="col-fname" :title="file.object_key">
                            <div class="inf-bc-file-cell">
                              <img
                                v-if="projectThumbUrls[file.file_id]"
                                :src="projectThumbUrls[file.file_id]"
                                alt=""
                                class="inf-bc-thumb"
                              />
                              <span v-else class="inf-bc-thumb-fallback" aria-hidden="true">
                                <ImageIcon :size="14" />
                              </span>
                              <span>{{ file.file_name }}</span>
                            </div>
                          </td>
                          <td class="col-size">{{ formatSize(file.size_bytes) }}</td>
                        </tr>
                      </tbody>
                    </table>
                    <div v-if="filteredProjectFiles.length > PAGE_SIZE" class="inf-bc-pager">
                      <PaginationControls
                        numbered
                        :offset="projectOffset"
                        :limit="PAGE_SIZE"
                        :item-count="pagedProjectFiles.length"
                        :total-count="filteredProjectFiles.length"
                        @previous="projectOffset = Math.max(0, projectOffset - PAGE_SIZE)"
                        @next="projectOffset = projectOffset + PAGE_SIZE"
                        @go="projectOffset = $event"
                      >
                        <template #summary>共 {{ filteredProjectFiles.length }} 项</template>
                      </PaginationControls>
                    </div>
                  </template>
                </div>
              </template>
            </div>

            <div class="inf-bc-section inf-bc-section--divider">
              <h3 class="inf-bc-panel__title">参数设置</h3>
              <div class="inf-bc-param-row">
                <span class="inf-bc-row__label">
                  {{ activeTaskType === 'classification' ? 'Top-K' : activeTaskType === 'pose' ? '对象置信度阈值' : '置信度阈值' }}
                </span>
                <input
                  v-if="activeTaskType === 'classification'"
                  v-model.number="topK"
                  type="number"
                  class="inf-bc-input inf-bc-num"
                  min="1"
                  max="100"
                  step="1"
                />
                <input
                  v-else
                  v-model.number="scoreThreshold"
                  type="number"
                  class="inf-bc-input inf-bc-num"
                  min="0"
                  max="1"
                  step="0.01"
                />
              </div>

              <button
                type="button"
                class="inf-bc-adv-toggle"
                :class="{ 'is-open': advancedExpanded }"
                @click="advancedExpanded = !advancedExpanded"
              >
                <span>高级参数</span>
                <ChevronDown :size="15" />
              </button>

              <div v-if="advancedExpanded" class="inf-bc-adv-body">
                <div v-if="selectedDeployment?.input_size" class="inf-bc-param-row">
                  <span class="inf-bc-row__label">输入尺寸</span>
                  <span class="inf-bc-readonly-dim">
                    {{ selectedDeployment.input_size.width }} × {{ selectedDeployment.input_size.height }}
                  </span>
                </div>
                <div v-if="activeTaskType === 'segmentation'" class="inf-bc-param-row">
                  <span class="inf-bc-row__label">掩码阈值</span>
                  <input
                    v-model.number="maskThreshold"
                    type="number"
                    class="inf-bc-input inf-bc-num"
                    min="0"
                    max="1"
                    step="0.01"
                  />
                </div>
                <div v-if="activeTaskType === 'pose'" class="inf-bc-param-row">
                  <span class="inf-bc-row__label">关键点阈值</span>
                  <input
                    v-model.number="keypointThreshold"
                    type="number"
                    class="inf-bc-input inf-bc-num"
                    min="0"
                    max="1"
                    step="0.01"
                  />
                </div>
              </div>
            </div>

            <div class="inf-bc-section inf-bc-section--divider">
              <div class="inf-bc-result-row">
                <span class="inf-bc-section-label">结果设置</span>
                <label class="inf-bc-checkbox">
                  <input v-model="saveResultImage" type="checkbox" />
                  <span>保存预览图与结构化结果</span>
                </label>
              </div>
            </div>
          </div>
        </template>

        <template v-else>
          <div class="inf-bc-panel">
            <div class="inf-bc-panel__head">
              <h3>输入与参数</h3>
              <button type="button" class="inf-link-edit" @click="step = 1">
                <Pencil :size="13" />
                修改
              </button>
            </div>
            <dl class="inf-bc-summary-kv">
              <div>
                <dt>执行通道</dt>
                <dd>{{ selectedRuntimeMode === 'sync' ? '同步通道' : '异步通道' }}</dd>
              </div>
              <div>
                <dt>输入来源</dt>
                <dd>{{ sourceKindLabel }}</dd>
              </div>
              <div>
                <dt>输入范围</dt>
                <dd>{{ inputRangeSummary }}</dd>
              </div>
              <div>
                <dt>{{ activeTaskType === 'classification' ? 'Top-K' : '置信度阈值' }}</dt>
                <dd>{{ activeTaskType === 'classification' ? topK : scoreThreshold.toFixed(2) }}</dd>
              </div>
              <div>
                <dt>结果保存</dt>
                <dd class="inf-bc-save-dd">
                  <span>{{ saveResultImage ? '结构化结果与预览图' : '仅保留结构化结果' }}</span>
                  <span class="inf-bc-save-pill" :class="{ 'is-on': saveResultImage }">
                    {{ saveResultImage ? '已开启' : '未开启' }}
                  </span>
                </dd>
              </div>
            </dl>
          </div>

          <div class="inf-bc-panel">
            <h3 class="inf-bc-panel__title">检查结果</h3>
            <div class="inf-bc-check-table-wrap">
              <table class="inf-bc-check-table">
                <thead>
                  <tr>
                    <th>检查项</th>
                    <th>状态</th>
                    <th>信息</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="check in preflightChecks" :key="check.id">
                    <td>{{ check.label }}</td>
                    <td>
                      <span class="inf-check-badge" :class="check.passed ? 'is-ok' : 'is-fail'">
                        <span class="inf-check-icon" :class="check.passed ? 'is-ok' : 'is-fail'" aria-hidden="true">
                          <Check v-if="check.passed" :size="11" :stroke-width="3" />
                          <span v-else>!</span>
                        </span>
                        <span>{{ check.statusText }}</span>
                      </span>
                    </td>
                    <td>{{ check.detail }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div class="inf-bc-checklist-box">
              <button
                type="button"
                class="inf-bc-checklist-toggle"
                :class="{ 'is-open': checkListExpanded }"
                @click="checkListExpanded = !checkListExpanded"
              >
                <span class="inf-bc-checklist-toggle__left">
                  <ChevronDown :size="14" class="inf-bc-checklist-chevron" />
                  <strong>输入清单</strong>
                  <span>({{ inputCount }})</span>
                </span>
                <ChevronRight :size="14" class="inf-bc-checklist-arrow" />
              </button>
              <div
                v-if="checkListExpanded && checkListPreviewItems.length > 0"
                class="inf-bc-checklist-body"
              >
                <ul class="inf-bc-checklist-list">
                  <li
                    v-for="item in checkListPreviewItems"
                    :key="item.key"
                    class="inf-bc-checklist-row"
                    :title="item.name"
                  >
                    <span class="inf-bc-checklist-idx">{{ String(item.index).padStart(2, '0') }}</span>
                    <img
                      v-if="item.thumbUrl"
                      :src="item.thumbUrl"
                      :alt="item.name"
                      class="inf-bc-checklist-thumb"
                    />
                    <span v-else class="inf-bc-checklist-thumb inf-bc-checklist-thumb--fallback">
                      <ImageIcon :size="13" />
                    </span>
                    <span class="inf-bc-checklist-name">{{ item.name }}</span>
                    <span v-if="item.meta" class="inf-bc-checklist-meta">{{ item.meta }}</span>
                  </li>
                </ul>
                <div v-if="inputCount > checkListPreviewItems.length" class="inf-bc-checklist-foot">
                  已预览 {{ checkListPreviewItems.length }} 项 · 其余 {{ inputCount - checkListPreviewItems.length }} 项将按清单顺序执行
                </div>
              </div>
            </div>

            <div v-if="invalidUploads.length > 0" class="inf-bc-invalid-box">
              <div class="inf-bc-invalid-box__head">
                <strong>无效项 ({{ invalidUploads.length }})</strong>
                <Button size="sm" variant="secondary" @click="removeInvalidUploads">
                  移除 {{ invalidUploads.length }} 个无效项
                </Button>
              </div>
              <ul>
                <li v-for="bad in invalidUploads" :key="bad.uid">
                  <span>{{ bad.file.name }}</span>
                  <small>{{ bad.invalidReason }}</small>
                </li>
              </ul>
            </div>
          </div>
        </template>
      </section>

      <aside class="inf-bc-right">
        <div class="inf-bc-preview-head">
          <div class="inf-bc-preview-meta">
            <strong>示例图像</strong>
            <span v-if="currentPreviewMeta" :title="currentPreviewMeta">{{ currentPreviewMeta }}</span>
          </div>
          <div v-if="previewTotalCount > 0" class="inf-bc-preview-nav">
            <button type="button" :disabled="globalPreviewIndex <= 0" @click="stepPreview(-1)">
              <ChevronLeft :size="15" />
            </button>
            <span>{{ globalPreviewIndex + 1 }} / {{ previewTotalCount }}</span>
            <button
              type="button"
              :disabled="globalPreviewIndex >= previewTotalCount - 1"
              @click="stepPreview(1)"
            >
              <ChevronRight :size="15" />
            </button>
          </div>
        </div>

        <div class="inf-bc-preview-stage">
          <img v-if="previewImageUrl" :src="previewImageUrl" alt="批量样本示例预览" />
          <div v-else class="inf-bc-preview-empty">
            <ImageIcon :size="36" />
            <span>选择输入图像后显示示例预览</span>
          </div>
        </div>
      </aside>
    </div>

    <footer class="inf-bc-footer">
      <Button variant="secondary" @click="emit('cancel')">取消</Button>
      <div class="inf-bc-footer__right">
        <template v-if="step === 1">
          <Button
            variant="primary"
            :disabled="!canGoNext"
            data-batch-next
            @click="goToCheckStep"
          >
            下一步
          </Button>
        </template>
        <template v-else>
          <Button variant="secondary" @click="step = 1">上一步</Button>
          <Button v-if="hasFailedCheck" variant="secondary" @click="inspectDeploymentChannels">
            重新检查
          </Button>
          <Button
            variant="primary"
            :disabled="hasFailedCheck || submitting"
            :loading="submitting"
            data-batch-submit
            @click="submitBatchTask"
          >
            提交任务
          </Button>
        </template>
      </div>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FolderOpen,
  Image as ImageIcon,
  Pencil,
} from '@lucide/vue'
import { RouterLink } from 'vue-router'

import {
  getDatasetImage,
  listDatasetCatalog,
  listDatasetSamples,
  listDatasetVersionPage,
  type DatasetItem,
  type DatasetSample,
  type DatasetVersion,
} from '@/modules/datasets/services/dataset-workspace.service'
import {
  runTaskDeploymentStatusAction,
  type ModelTaskType,
  type TaskDeploymentInstance,
  type TaskDeploymentProcessStatus,
} from '@/modules/deployments/services/deployment.service'
import { getErrorMessage } from '@/shared/api/error'
import Button from '@/shared/ui/components/Button.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import {
  createBatchInferenceTask,
  fetchAuthorizedProjectFileBlob,
  listProjectPublicFiles,
  SUPPORTED_INFERENCE_TASK_TYPES,
  type BatchInferenceTask,
  type ProjectPublicFileEntry,
} from '../services/inference.service'
import DeploymentTargetSelect from './DeploymentTargetSelect.vue'

interface UploadedEntry {
  uid: string
  file: File
  objectUrl: string
  width: number | null
  height: number | null
  invalidReason: string | null
}

const IMAGE_EXT_REGEX = /\.(jpe?g|png|webp|bmp)$/i
const PAGE_SIZE = 5

const props = defineProps<{
  projectId: string
  deployments: TaskDeploymentInstance[]
  initialDeploymentId?: string
  initialSourceKind?: 'upload' | 'dataset_version' | 'project_files'
  initialFileIds?: string[]
}>()

const emit = defineEmits<{
  cancel: []
  created: [task: BatchInferenceTask]
}>()

const step = ref<1 | 2>(1)
const taskName = ref(`批量推理-${new Date().toISOString().slice(5, 16).replace(/[-T:]/g, '')}`)
const selectedDeploymentId = ref(
  props.initialDeploymentId || props.deployments[0]?.deployment_instance_id || '',
)
const asyncStatus = ref<TaskDeploymentProcessStatus | null>(null)
const syncStatus = ref<TaskDeploymentProcessStatus | null>(null)
const channelStatusChecked = ref(false)
const selectedRuntimeMode = ref<'async' | 'sync'>('async')

const sourceKind = ref<'upload' | 'dataset_version' | 'project_files'>(
  props.initialSourceKind || (props.initialFileIds?.length ? 'project_files' : 'dataset_version'),
)

const scoreThreshold = ref(0.3)
const topK = ref(5)
const maskThreshold = ref(0.5)
const keypointThreshold = ref(0.3)
const saveResultImage = ref(false)
const advancedExpanded = ref(false)
const checkListExpanded = ref(false)

const uploadInputRef = ref<HTMLInputElement | null>(null)
const uploadedItems = ref<UploadedEntry[]>([])
const uploadOffset = ref(0)

const datasets = ref<DatasetItem[]>([])
const selectedDatasetId = ref('')
const versions = ref<DatasetVersion[]>([])
const selectedVersionId = ref('')
const datasetSplit = ref('')
const datasetSamples = ref<DatasetSample[]>([])
const datasetTotal = ref(0)
const datasetOffset = ref(0)
const datasetLoading = ref(false)
const datasetThumbUrls = ref<Record<string, string>>({})

const projectScope = ref<'workspace' | 'inputs' | 'results' | 'all'>('workspace')
const projectFiles = ref<ProjectPublicFileEntry[]>([])
const projectFilesLoading = ref(false)
const projectSearch = ref('')
const projectOffset = ref(0)
const selectedFileIds = ref<string[]>(props.initialFileIds ? [...props.initialFileIds] : [])
const projectThumbUrls = ref<Record<string, string>>({})

const previewIndex = ref(0)
const previewImageUrl = ref<string | null>(null)
let activeRemotePreviewUrl: string | null = null
let previewLoadGen = 0
let datasetThumbGen = 0
let projectThumbGen = 0

const submitting = ref(false)
const submitError = ref<string | null>(null)

const sourceKindOptions = [
  { label: '数据集版本', value: 'dataset_version' },
  { label: '项目文件', value: 'project_files' },
  { label: '上传图片', value: 'upload' },
]

const splitOptions = [
  { label: '全部划分', value: '' },
  { label: 'train', value: 'train' },
  { label: 'val', value: 'val' },
  { label: 'test', value: 'test' },
]

const projectScopeOptions = [
  { label: '项目文件', value: 'workspace' },
  { label: '项目输入 (inputs)', value: 'inputs' },
  { label: '推理结果 (results)', value: 'results' },
  { label: '全部公开文件', value: 'all' },
]

const selectedDeployment = computed(
  () => props.deployments.find((d) => d.deployment_instance_id === selectedDeploymentId.value) ?? null,
)
const activeTaskType = computed<ModelTaskType>(() => {
  const raw = selectedDeployment.value?.task_type
  return SUPPORTED_INFERENCE_TASK_TYPES.includes(raw as ModelTaskType) ? (raw as ModelTaskType) : 'detection'
})

interface CheckListPreviewItem {
  key: string
  index: number
  name: string
  thumbUrl: string | null
  meta: string
}

const checkListPreviewItems = computed<CheckListPreviewItem[]>(() => {
  if (sourceKind.value === 'upload') {
    return uploadedItems.value.slice(0, PAGE_SIZE).map((item, idx) => ({
      key: item.uid,
      index: idx + 1,
      name: item.file.name,
      thumbUrl: item.objectUrl,
      meta:
        item.width && item.height
          ? `${item.width} × ${item.height} · ${formatSize(item.file.size)}`
          : formatSize(item.file.size),
    }))
  }
  if (sourceKind.value === 'dataset_version') {
    return datasetSamples.value.slice(0, PAGE_SIZE).map((sample, idx) => ({
      key: sample.sample_id,
      index: datasetOffset.value + idx + 1,
      name: sample.file_name,
      thumbUrl: datasetThumbUrls.value[sample.sample_id] || null,
      meta: `${sample.width} × ${sample.height} · ${sample.split}`,
    }))
  }
  return selectedFileIds.value.slice(0, PAGE_SIZE).map((fid, idx) => {
    const entry = projectFiles.value.find((f) => f.file_id === fid)
    return {
      key: fid,
      index: idx + 1,
      name: entry?.file_name || fid,
      thumbUrl: projectThumbUrls.value[fid] || null,
      meta: entry ? formatSize(entry.size_bytes) : '',
    }
  })
})

const asyncReady = computed(() => asyncStatus.value?.process_state === 'running')
const syncReady = computed(() => syncStatus.value?.process_state === 'running')
const anyChannelReady = computed(() => asyncReady.value || syncReady.value)
const effectiveChannelReady = computed(() =>
  selectedRuntimeMode.value === 'async' ? asyncReady.value : syncReady.value,
)
const channelStatusText = computed(() => {
  if (!selectedDeployment.value) return '未选择部署'
  if (!channelStatusChecked.value) return '检查通道中...'
  if (asyncReady.value && syncReady.value) return '运行正常'
  if (asyncReady.value) return '异步通道就绪'
  if (syncReady.value) return '同步通道就绪'
  return '部署未启动'
})

const datasetOptions = computed(() =>
  datasets.value.map((d) => ({ label: d.display_name || d.dataset_id, value: d.dataset_id })),
)
const versionOptions = computed(() =>
  versions.value.map((v) => ({ label: `v${v.version_number} (${v.sample_count})`, value: v.dataset_version_id })),
)

const filteredProjectFiles = computed(() => {
  const kw = projectSearch.value.trim().toLowerCase()
  return projectFiles.value.filter((entry) => {
    const isImage = entry.media_type.startsWith('image/') || IMAGE_EXT_REGEX.test(entry.object_key)
    if (!isImage) return false
    if (!kw) return true
    return entry.file_name.toLowerCase().includes(kw) || entry.object_key.toLowerCase().includes(kw)
  })
})

const pagedUploads = computed(() => uploadedItems.value.slice(uploadOffset.value, uploadOffset.value + PAGE_SIZE))
const pagedProjectFiles = computed(() =>
  filteredProjectFiles.value.slice(projectOffset.value, projectOffset.value + PAGE_SIZE),
)

const invalidUploads = computed(() =>
  sourceKind.value === 'upload' ? uploadedItems.value.filter((i) => Boolean(i.invalidReason)) : [],
)

const inputCount = computed(() => {
  if (sourceKind.value === 'upload') return uploadedItems.value.length
  if (sourceKind.value === 'dataset_version') return datasetTotal.value
  return selectedFileIds.value.length
})

const canGoNext = computed(
  () => Boolean(taskName.value.trim() && selectedDeploymentId.value && inputCount.value > 0),
)

const sourceKindLabel = computed(() => {
  if (sourceKind.value === 'upload') return '上传图片'
  if (sourceKind.value === 'dataset_version') return '数据集版本'
  return '项目文件'
})

const inputRangeSummary = computed(() => {
  if (sourceKind.value === 'upload') {
    const totalBytes = uploadedItems.value.reduce((acc, i) => acc + i.file.size, 0)
    return `共 ${uploadedItems.value.length} 张 · ${formatSize(totalBytes)}`
  }
  if (sourceKind.value === 'dataset_version') {
    const dsName = datasets.value.find((d) => d.dataset_id === selectedDatasetId.value)?.display_name || ''
    return `${dsName} (${datasetSplit.value || '全部划分'}) · 共 ${datasetTotal.value} 张`
  }
  return `共 ${selectedFileIds.value.length} 个项目文件`
})

const preflightChecks = computed(() => {
  const badCount = invalidUploads.value.length
  const totalCount = inputCount.value
  const isSync = selectedRuntimeMode.value === 'sync'
  return [
    {
      id: 'channel',
      label: isSync ? '同步部署通道' : '异步部署通道',
      passed: effectiveChannelReady.value,
      statusText: effectiveChannelReady.value ? '通过' : '未就绪',
      detail: effectiveChannelReady.value
        ? isSync
          ? '同步通道运行正常'
          : '异步通道运行正常'
        : '请先启动同步或异步通道',
    },
    {
      id: 'inputs',
      label: '输入清单',
      passed: totalCount > 0,
      statusText: totalCount > 0 ? '通过' : '未通过',
      detail: totalCount > 0 ? `${totalCount} 张` : '至少选择 1 张图像',
    },
    {
      id: 'format',
      label: '图像格式',
      passed: badCount === 0,
      statusText: badCount === 0 ? '通过' : `${badCount} 项未通过`,
      detail: badCount === 0 ? '格式正常' : `${badCount} 项无效`,
    },
    {
      id: 'model',
      label: '模型输入',
      passed: Boolean(selectedDeployment.value),
      statusText: selectedDeployment.value ? '通过' : '未通过',
      detail: selectedDeployment.value?.input_size
        ? `${selectedDeployment.value.input_size.width} × ${selectedDeployment.value.input_size.height}`
        : '默认预处理',
    },
    {
      id: 'output',
      label: '输出位置',
      passed: true,
      statusText: '通过',
      detail: '本项目结果',
    },
  ]
})

const hasFailedCheck = computed(() => preflightChecks.value.some((c) => !c.passed))

const previewTotalCount = computed(() => {
  if (sourceKind.value === 'upload') return uploadedItems.value.length
  if (sourceKind.value === 'dataset_version') return datasetTotal.value
  return selectedFileIds.value.length
})

const globalPreviewIndex = computed(() => {
  if (sourceKind.value === 'dataset_version') {
    return datasetOffset.value + previewIndex.value
  }
  return previewIndex.value
})

const currentPreviewMeta = computed(() => {
  if (sourceKind.value === 'upload') {
    const item = uploadedItems.value[previewIndex.value]
    if (!item) return ''
    const dims = item.width && item.height ? `${item.width} × ${item.height} · ` : ''
    return `${item.file.name} · ${dims}${formatSize(item.file.size)}`
  }
  if (sourceKind.value === 'dataset_version') {
    const sample = datasetSamples.value[previewIndex.value]
    if (!sample) return ''
    return `${sample.file_name} · ${sample.width} × ${sample.height} · ${sample.split}`
  }
  const fid = selectedFileIds.value[previewIndex.value]
  const entry = projectFiles.value.find((f) => f.file_id === fid)
  return entry ? `${entry.file_name} · ${formatSize(entry.size_bytes)}` : ''
})

watch(
  () => [sourceKind.value, previewIndex.value, uploadedItems.value.length, datasetSamples.value, selectedFileIds.value],
  () => {
    void updatePreviewImage()
  },
)

watch(pagedProjectFiles, (files) => {
  if (sourceKind.value === 'project_files') {
    void loadProjectPageThumbs(files)
  }
})

onMounted(async () => {
  if (!selectedDeploymentId.value && props.deployments.length > 0) {
    selectedDeploymentId.value = props.deployments[0].deployment_instance_id
  }
  await inspectDeploymentChannels()
  if (sourceKind.value === 'dataset_version') {
    await loadDatasets()
  } else if (sourceKind.value === 'project_files') {
    await loadProjectFiles()
  }
})

onBeforeUnmount(() => {
  for (const item of uploadedItems.value) {
    URL.revokeObjectURL(item.objectUrl)
  }
  revokeThumbMap(datasetThumbUrls.value)
  revokeThumbMap(projectThumbUrls.value)
  if (activeRemotePreviewUrl) {
    URL.revokeObjectURL(activeRemotePreviewUrl)
  }
})

function revokeThumbMap(map: Record<string, string>): void {
  for (const url of Object.values(map)) {
    URL.revokeObjectURL(url)
  }
}

async function selectDeployment(id: string): Promise<void> {
  selectedDeploymentId.value = id
  await inspectDeploymentChannels()
}

async function inspectDeploymentChannels(): Promise<void> {
  const dep = selectedDeployment.value
  channelStatusChecked.value = false
  if (!dep) {
    asyncStatus.value = null
    syncStatus.value = null
    return
  }
  try {
    const [nextAsync, nextSync] = await Promise.all([
      runTaskDeploymentStatusAction(
        dep.task_type as ModelTaskType,
        dep.deployment_instance_id,
        'async',
        'status',
      ).catch(() => null),
      runTaskDeploymentStatusAction(
        dep.task_type as ModelTaskType,
        dep.deployment_instance_id,
        'sync',
        'status',
      ).catch(() => null),
    ])
    asyncStatus.value = nextAsync
    syncStatus.value = nextSync
    const asyncIsRunning = nextAsync?.process_state === 'running'
    const syncIsRunning = nextSync?.process_state === 'running'
    if (asyncIsRunning && !syncIsRunning) {
      selectedRuntimeMode.value = 'async'
    } else if (syncIsRunning && !asyncIsRunning) {
      selectedRuntimeMode.value = 'sync'
    } else if (asyncIsRunning) {
      selectedRuntimeMode.value = 'async'
    }
  } finally {
    channelStatusChecked.value = true
  }
}

function switchSourceKind(next: string | number | boolean | null): void {
  if (next !== 'upload' && next !== 'dataset_version' && next !== 'project_files') return
  sourceKind.value = next
  previewIndex.value = 0
  if (next === 'dataset_version' && datasets.value.length === 0) {
    void loadDatasets()
  } else if (next === 'project_files' && projectFiles.value.length === 0) {
    void loadProjectFiles()
  }
}

async function handleMultiFileSelect(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (files.length === 0) return

  const newEntries: UploadedEntry[] = await Promise.all(
    files.map(
      (file, idx) =>
        new Promise<UploadedEntry>((resolve) => {
          const objectUrl = URL.createObjectURL(file)
          const uid = `${Date.now()}-${idx}-${file.name}`
          if (file.size <= 0) {
            resolve({ uid, file, objectUrl, width: null, height: null, invalidReason: '空文件 (0 B)' })
            return
          }
          const img = new Image()
          img.onload = () => {
            resolve({
              uid,
              file,
              objectUrl,
              width: img.naturalWidth || null,
              height: img.naturalHeight || null,
              invalidReason: null,
            })
          }
          img.onerror = () => {
            resolve({
              uid,
              file,
              objectUrl,
              width: null,
              height: null,
              invalidReason: '图像解码失败',
            })
          }
          img.src = objectUrl
        }),
    ),
  )
  uploadedItems.value = [...uploadedItems.value, ...newEntries]
}

function removeUploadedItem(idx: number): void {
  const target = uploadedItems.value[idx]
  if (target) URL.revokeObjectURL(target.objectUrl)
  uploadedItems.value = uploadedItems.value.filter((_, i) => i !== idx)
  if (uploadOffset.value >= uploadedItems.value.length) {
    uploadOffset.value = Math.max(0, uploadOffset.value - PAGE_SIZE)
  }
  if (previewIndex.value >= uploadedItems.value.length) {
    previewIndex.value = Math.max(0, uploadedItems.value.length - 1)
  }
}

function removeInvalidUploads(): void {
  const keep: UploadedEntry[] = []
  for (const item of uploadedItems.value) {
    if (item.invalidReason) URL.revokeObjectURL(item.objectUrl)
    else keep.push(item)
  }
  uploadedItems.value = keep
  uploadOffset.value = 0
  previewIndex.value = 0
}

function clearUploadedFiles(): void {
  for (const item of uploadedItems.value) URL.revokeObjectURL(item.objectUrl)
  uploadedItems.value = []
  uploadOffset.value = 0
  previewIndex.value = 0
}

async function loadDatasets(): Promise<void> {
  if (!props.projectId) return
  datasetLoading.value = true
  try {
    const page = await listDatasetCatalog({ project_id: props.projectId, limit: 100 })
    datasets.value = page.items
    if (page.items.length > 0 && !selectedDatasetId.value) {
      await selectDataset(page.items[0].dataset_id)
    }
  } finally {
    datasetLoading.value = false
  }
}

async function selectDataset(val: string | number | boolean | null): Promise<void> {
  const nextId = typeof val === 'string' ? val : ''
  selectedDatasetId.value = nextId
  selectedVersionId.value = ''
  datasetOffset.value = 0
  datasetSamples.value = []
  datasetTotal.value = 0
  revokeThumbMap(datasetThumbUrls.value)
  datasetThumbUrls.value = {}
  if (!nextId) return
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
}

async function selectVersion(val: string | number | boolean | null): Promise<void> {
  selectedVersionId.value = typeof val === 'string' ? val : ''
  datasetOffset.value = 0
  revokeThumbMap(datasetThumbUrls.value)
  datasetThumbUrls.value = {}
  await loadDatasetPreviewSamples()
}

async function selectSplit(val: string | number | boolean | null): Promise<void> {
  datasetSplit.value = typeof val === 'string' ? val : ''
  datasetOffset.value = 0
  await loadDatasetPreviewSamples()
}

async function goDatasetPage(nextOffset: number, nextPreviewIndex = 0): Promise<void> {
  datasetOffset.value = Math.max(0, nextOffset)
  await loadDatasetPreviewSamples(nextPreviewIndex)
}

async function loadDatasetPreviewSamples(targetPreviewIdx = 0): Promise<void> {
  if (!selectedDatasetId.value || !selectedVersionId.value) return
  datasetLoading.value = true
  try {
    const page = await listDatasetSamples(selectedDatasetId.value, selectedVersionId.value, {
      split: datasetSplit.value || undefined,
      offset: datasetOffset.value,
      limit: PAGE_SIZE,
    })
    datasetSamples.value = page.items
    datasetTotal.value = page.total
    previewIndex.value = page.items.length > 0 ? Math.min(targetPreviewIdx, page.items.length - 1) : 0
    void loadDatasetPageThumbs(page.items)
  } finally {
    datasetLoading.value = false
  }
}

async function loadDatasetPageThumbs(samples: DatasetSample[]): Promise<void> {
  const dsId = selectedDatasetId.value
  const verId = selectedVersionId.value
  if (!dsId || !verId || samples.length === 0) return
  const gen = ++datasetThumbGen
  await Promise.all(
    samples.map(async (sample) => {
      if (datasetThumbUrls.value[sample.sample_id]) return
      try {
        const blob = await getDatasetImage(dsId, verId, sample.sample_id, true)
        if (!blob) return
        const url = URL.createObjectURL(blob)
        if (gen !== datasetThumbGen) {
          URL.revokeObjectURL(url)
          return
        }
        datasetThumbUrls.value = { ...datasetThumbUrls.value, [sample.sample_id]: url }
      } catch {
        // 缩略图加载失败保留占位图标
      }
    }),
  )
}

async function selectProjectScope(val: string | number | boolean | null): Promise<void> {
  if (val === 'workspace' || val === 'inputs' || val === 'results' || val === 'all') {
    projectScope.value = val
    projectOffset.value = 0
    await loadProjectFiles()
  }
}

async function loadProjectFiles(): Promise<void> {
  if (!props.projectId) return
  projectFilesLoading.value = true
  try {
    if (projectScope.value === 'workspace') {
      const [inputs, results] = await Promise.all([
        listProjectPublicFiles(props.projectId, {
          objectPrefix: `projects/${props.projectId}/inputs`,
          limit: 200,
        }).catch(() => []),
        listProjectPublicFiles(props.projectId, {
          objectPrefix: `projects/${props.projectId}/results`,
          limit: 200,
        }).catch(() => []),
      ])
      const map = new Map<string, ProjectPublicFileEntry>()
      for (const f of [...inputs, ...results]) map.set(f.file_id, f)
      projectFiles.value = Array.from(map.values())
    } else if (projectScope.value === 'inputs' || projectScope.value === 'results') {
      projectFiles.value = await listProjectPublicFiles(props.projectId, {
        objectPrefix: `projects/${props.projectId}/${projectScope.value}`,
        limit: 200,
      })
    } else {
      projectFiles.value = await listProjectPublicFiles(props.projectId, { limit: 200 })
    }
    void loadProjectPageThumbs(pagedProjectFiles.value)
  } finally {
    projectFilesLoading.value = false
  }
}

async function loadProjectPageThumbs(files: ProjectPublicFileEntry[]): Promise<void> {
  if (!props.projectId || files.length === 0) return
  const gen = ++projectThumbGen
  await Promise.all(
    files.map(async (entry) => {
      if (projectThumbUrls.value[entry.file_id]) return
      try {
        const blob = await fetchAuthorizedProjectFileBlob(props.projectId, entry.object_key)
        if (!blob) return
        const url = URL.createObjectURL(blob)
        if (gen !== projectThumbGen) {
          URL.revokeObjectURL(url)
          return
        }
        projectThumbUrls.value = { ...projectThumbUrls.value, [entry.file_id]: url }
      } catch {
        // 缩略图加载失败保留占位图标
      }
    }),
  )
}

function toggleProjectFile(fileId: string): void {
  if (selectedFileIds.value.includes(fileId)) {
    selectedFileIds.value = selectedFileIds.value.filter((id) => id !== fileId)
  } else {
    selectedFileIds.value = [...selectedFileIds.value, fileId]
  }
}

function syncProjectPreview(fileId: string): void {
  const idx = selectedFileIds.value.indexOf(fileId)
  if (idx >= 0) {
    previewIndex.value = idx
  }
}

function selectAllFilteredProjectFiles(): void {
  selectedFileIds.value = filteredProjectFiles.value.map((f) => f.file_id)
}

async function stepPreview(delta: -1 | 1): Promise<void> {
  if (sourceKind.value === 'dataset_version') {
    if (delta > 0) {
      if (previewIndex.value < datasetSamples.value.length - 1) {
        previewIndex.value += 1
      } else if (datasetOffset.value + datasetSamples.value.length < datasetTotal.value) {
        await goDatasetPage(datasetOffset.value + PAGE_SIZE, 0)
      }
      return
    }
    if (previewIndex.value > 0) {
      previewIndex.value -= 1
    } else if (datasetOffset.value > 0) {
      await goDatasetPage(Math.max(0, datasetOffset.value - PAGE_SIZE), PAGE_SIZE - 1)
    }
    return
  }
  const next = previewIndex.value + delta
  if (next >= 0 && next < previewTotalCount.value) {
    previewIndex.value = next
  }
}

async function updatePreviewImage(): Promise<void> {
  const gen = ++previewLoadGen
  if (activeRemotePreviewUrl) {
    URL.revokeObjectURL(activeRemotePreviewUrl)
    activeRemotePreviewUrl = null
  }
  if (sourceKind.value === 'upload') {
    previewImageUrl.value = uploadedItems.value[previewIndex.value]?.objectUrl ?? null
    return
  }
  if (sourceKind.value === 'dataset_version') {
    const sample = datasetSamples.value[previewIndex.value]
    if (!sample || !selectedDatasetId.value || !selectedVersionId.value) {
      previewImageUrl.value = null
      return
    }
    try {
      const blob = await getDatasetImage(
        selectedDatasetId.value,
        selectedVersionId.value,
        sample.sample_id,
        true,
      )
      if (!blob || gen !== previewLoadGen) return
      activeRemotePreviewUrl = URL.createObjectURL(blob)
      previewImageUrl.value = activeRemotePreviewUrl
    } catch {
      if (gen === previewLoadGen) previewImageUrl.value = null
    }
    return
  }
  const fid = selectedFileIds.value[previewIndex.value]
  const entry = projectFiles.value.find((f) => f.file_id === fid)
  if (!entry) {
    previewImageUrl.value = null
    return
  }
  try {
    const blob = await fetchAuthorizedProjectFileBlob(props.projectId, entry.object_key)
    if (!blob || gen !== previewLoadGen) return
    activeRemotePreviewUrl = URL.createObjectURL(blob)
    previewImageUrl.value = activeRemotePreviewUrl
  } catch {
    if (gen === previewLoadGen) previewImageUrl.value = null
  }
}

function goToCheckStep(): void {
  submitError.value = null
  step.value = 2
  void inspectDeploymentChannels()
}

async function submitBatchTask(): Promise<void> {
  if (hasFailedCheck.value || !selectedDeployment.value) return
  submitting.value = true
  submitError.value = null
  try {
    const created = await createBatchInferenceTask({
      projectId: props.projectId,
      taskType: activeTaskType.value,
      deploymentInstanceId: selectedDeployment.value.deployment_instance_id,
      runtimeMode: selectedRuntimeMode.value,
      displayName: taskName.value.trim(),
      sourceKind: sourceKind.value,
      files: sourceKind.value === 'upload' ? uploadedItems.value.map((i) => i.file) : undefined,
      datasetId: sourceKind.value === 'dataset_version' ? selectedDatasetId.value : undefined,
      datasetVersionId: sourceKind.value === 'dataset_version' ? selectedVersionId.value : undefined,
      datasetSplit: sourceKind.value === 'dataset_version' ? datasetSplit.value : undefined,
      inputFileIds: sourceKind.value === 'project_files' ? selectedFileIds.value : undefined,
      scoreThreshold: scoreThreshold.value,
      topK: topK.value,
      maskThreshold: maskThreshold.value,
      keypointConfidenceThreshold: keypointThreshold.value,
      saveResultImage: saveResultImage.value,
    })
    emit('created', created)
  } catch (err) {
    submitError.value = getErrorMessage(err)
  } finally {
    submitting.value = false
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}
</script>

<style scoped>
.inf-batch-create {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-top: 4px;
  min-width: 0;
}

.inf-bc-breadcrumb {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--am-text-muted);
}

.inf-bc-crumb-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--am-text);
  font: inherit;
  cursor: pointer;
}

.inf-bc-crumb-link:hover {
  color: var(--am-action-primary-strong);
  text-decoration: underline;
}

.inf-bc-stepper {
  display: flex;
  align-items: center;
  width: 100%;
  margin: 0;
  padding: 8px 4px;
  box-sizing: border-box;
  list-style: none;
}

.inf-bc-step {
  display: flex;
  align-items: center;
  flex: 1 1 0;
  min-width: 0;
  gap: 8px;
  font-size: 13px;
  color: var(--am-text-muted);
}

.inf-bc-step--last {
  flex: 0 0 auto;
}

.inf-bc-step strong {
  white-space: nowrap;
  font-weight: 600;
}

.inf-bc-step.is-active {
  color: var(--am-action-primary-strong);
}

.inf-bc-step.is-done {
  color: var(--am-text);
}

.inf-bc-step__num {
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  border-radius: 50%;
  border: 1px solid var(--am-border-strong);
  background: var(--am-surface);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
}

.inf-bc-step.is-active .inf-bc-step__num {
  background: var(--am-brand-primary);
  border-color: var(--am-brand-primary);
  color: #ffffff;
}

.inf-bc-step.is-done .inf-bc-step__num {
  border-color: var(--am-brand-primary);
  color: var(--am-brand-primary);
}

.inf-bc-step__line {
  flex: 1 1 auto;
  height: 1px;
  margin: 0 12px;
  background: var(--am-border);
}

.inf-bc-step__line.is-active {
  background: var(--am-brand-primary);
}

.inf-bc-target-card {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px 24px;
  padding: 12px 18px;
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
}

.inf-bc-target-field {
  display: flex;
  align-items: center;
  gap: 10px;
}

.inf-bc-field-label {
  font-size: 13px;
  line-height: 36px;
  color: var(--am-text-muted);
  white-space: nowrap;
}

.inf-bc-field-label em {
  color: #dc2626;
  font-style: normal;
}

.inf-bc-name-input {
  width: 220px;
}

.inf-bc-input {
  height: 36px;
  padding: 0 10px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-input);
  color: var(--am-text-strong);
  font-size: 13px;
}

.inf-bc-num {
  width: 112px;
  height: 34px;
  font-variant-numeric: tabular-nums;
}

.inf-bc-async-status {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  min-height: 36px;
  margin-left: auto;
}

.inf-bc-channel-switch {
  display: inline-flex;
  padding: 2px;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  background: var(--am-surface-soft);
}

.inf-bc-channel-btn {
  border: none;
  border-radius: 4px;
  padding: 3px 8px;
  background: transparent;
  color: var(--am-text-muted);
  font-size: 12px;
  cursor: pointer;
}

.inf-bc-channel-btn.is-active {
  background: var(--am-surface);
  color: var(--am-text-strong);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
}

.inf-bc-target-card--readonly {
  align-items: center;
  gap: 20px;
}

.inf-bc-ro-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 120px;
}

.inf-bc-ro-item--grow {
  min-width: 240px;
}

.inf-bc-ro-label {
  font-size: 12px;
  color: var(--am-text-muted);
}

.inf-bc-ro-val {
  font-size: 14px;
  font-weight: 600;
  color: var(--am-text-strong);
}

.inf-bc-ro-sep {
  width: 1px;
  height: 32px;
  background: var(--am-border);
}

.inf-dot-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
}

.inf-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.inf-dot.is-ok {
  background: var(--am-brand-primary);
}

.inf-dot.is-warn {
  background: #f59e0b;
}

.inf-dot.is-neutral {
  background: #98a2b3;
}

.inf-link-nav {
  font-size: 13px;
  color: var(--am-action-primary);
  text-decoration: none;
  font-weight: 500;
  white-space: nowrap;
}

.inf-bc-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(0, 0.95fr);
  gap: 14px;
  align-items: stretch;
}

@media (max-width: 1080px) {
  .inf-bc-grid {
    grid-template-columns: 1fr;
  }
}

.inf-bc-left {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.inf-bc-left-card,
.inf-bc-panel {
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
}

.inf-bc-left-card {
  display: flex;
  flex-direction: column;
}

.inf-bc-section {
  padding: 14px 18px;
  display: grid;
  gap: 10px;
}

.inf-bc-section--divider {
  border-top: 1px solid var(--am-border);
}

.inf-bc-panel {
  padding: 16px 18px;
  display: grid;
  gap: 12px;
}

.inf-bc-panel__title {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--am-text-strong);
}

.inf-bc-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.inf-bc-panel__head h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--am-text-strong);
}

.inf-link-edit {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  color: var(--am-text);
  font-size: 13px;
  cursor: pointer;
}

.inf-bc-source-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px 12px;
}

.inf-bc-source-row :deep(.ui-select) {
  width: 200px;
  min-width: 180px;
}

.inf-bc-section-label {
  width: 68px;
  flex: none;
  font-size: 14px;
  font-weight: 700;
  color: var(--am-text-strong);
  white-space: nowrap;
}

.inf-bc-list-head {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  color: var(--am-text-muted);
}

.inf-bc-list-head strong {
  font-size: 14px;
  color: var(--am-text-strong);
}

.inf-bc-list-head__right {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  justify-content: space-between;
}

.inf-bc-param-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.inf-bc-row__label {
  width: 84px;
  flex: none;
  font-size: 13px;
  color: var(--am-text-muted);
  white-space: nowrap;
}

.inf-bc-result-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px 16px;
}

.inf-bc-state--col {
  display: grid;
  justify-items: center;
  gap: 10px;
}

.inf-hidden-input {
  display: none;
}

.inf-bc-dropzone {
  min-height: 132px;
  border: 1px dashed var(--am-border-strong);
  border-radius: 8px;
  background: var(--am-surface-soft);
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 8px;
  color: var(--am-text-muted);
  font-size: 13px;
  cursor: pointer;
}

.inf-bc-ds-filters {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr) 108px;
  gap: 8px;
}

.inf-bc-pf-filters {
  display: grid;
  grid-template-columns: minmax(140px, 0.9fr) minmax(0, 1.2fr) auto;
  gap: 8px;
  align-items: center;
}

.inf-bc-list-box {
  border: 1px solid var(--am-border);
  border-radius: 8px;
  overflow: hidden;
  background: var(--am-surface-raised);
}

.inf-bc-state {
  padding: 28px 12px;
  text-align: center;
  font-size: 13px;
  color: var(--am-text-muted);
}

.inf-bc-mini-table,
.inf-bc-check-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.inf-bc-mini-table {
  table-layout: fixed;
}

.inf-bc-mini-table th,
.inf-bc-check-table th {
  padding: 8px 10px;
  text-align: left;
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text);
  border-bottom: 1px solid var(--am-border);
  background: var(--am-table-header);
  white-space: nowrap;
}

.inf-bc-check-table th:first-child,
.inf-bc-check-table td:first-child,
.inf-bc-check-table th:nth-child(2),
.inf-bc-check-table td:nth-child(2) {
  white-space: nowrap;
}

.inf-bc-mini-table td,
.inf-bc-check-table td {
  padding: 6px 10px;
  border-bottom: 1px solid var(--am-border);
  color: var(--am-text-strong);
  vertical-align: middle;
}

.inf-bc-mini-table tbody tr {
  cursor: pointer;
}

.inf-bc-mini-table tbody tr:last-child td,
.inf-bc-check-table tbody tr:last-child td {
  border-bottom: 0;
}

.inf-bc-mini-table tbody tr.is-selected {
  background: var(--am-row-selected);
}

.inf-bc-file-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.inf-bc-file-cell span:last-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inf-bc-thumb,
.inf-bc-thumb-fallback {
  width: 30px;
  height: 30px;
  border-radius: 4px;
  flex: none;
}

.inf-bc-thumb {
  object-fit: cover;
  border: 1px solid var(--am-border);
  background: var(--am-surface-soft);
}

.inf-bc-thumb-fallback {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--am-border);
  background: var(--am-surface-soft);
  color: var(--am-text-muted);
}

.col-check {
  width: 34px;
}

.col-dims {
  width: 108px;
  white-space: nowrap;
}

.col-size {
  width: 84px;
  white-space: nowrap;
}

.col-split {
  width: 68px;
  white-space: nowrap;
}

.col-op {
  width: 58px;
  white-space: nowrap;
}

.inf-link-danger {
  border: none;
  background: transparent;
  padding: 0;
  color: #dc2626;
  font-size: 12px;
  cursor: pointer;
}

.inf-bc-pager {
  padding: 0 10px;
  border-top: 1px solid var(--am-border);
}

.inf-bc-pager :deep(.pagination-controls) {
  border: none;
  padding: 6px 0;
  background: transparent;
}

.inf-bc-adv-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border: none;
  padding: 4px 0 0;
  background: transparent;
  color: var(--am-text);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}

.inf-bc-adv-toggle svg {
  transition: transform 0.15s ease;
}

.inf-bc-adv-toggle.is-open svg {
  transform: rotate(180deg);
}

.inf-bc-adv-body {
  display: grid;
  gap: 8px;
}

.inf-bc-readonly-dim {
  font-size: 13px;
  color: var(--am-text-muted);
}

.inf-bc-checkbox {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--am-text-strong);
  cursor: pointer;
}

.inf-bc-summary-kv {
  margin: 0;
  display: grid;
  gap: 2px;
}

.inf-bc-summary-kv > div {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  font-size: 13px;
}

.inf-bc-summary-kv dt {
  color: var(--am-text-muted);
}

.inf-bc-summary-kv dd {
  margin: 0;
  color: var(--am-text-strong);
}

.inf-bc-save-dd {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 10px;
  flex-wrap: nowrap;
}

.inf-bc-save-pill {
  flex-shrink: 0;
  white-space: nowrap;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  background: var(--am-surface-soft);
  color: var(--am-text-muted);
  border: 1px solid var(--am-border);
}

.inf-bc-save-pill.is-on {
  background: var(--am-action-soft);
  border-color: color-mix(in srgb, var(--am-brand-primary) 40%, transparent);
  color: var(--am-action-primary);
}

.inf-bc-check-table-wrap {
  border: 1px solid var(--am-border);
  border-radius: 8px;
  overflow: hidden;
  background: var(--am-surface-raised);
}

.inf-check-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-weight: 500;
  color: var(--am-text-strong);
}

.inf-check-badge.is-fail {
  color: #dc2626;
}

.inf-check-icon {
  width: 17px;
  height: 17px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  flex: none;
}

.inf-check-icon.is-ok {
  background: var(--am-brand-primary);
  color: #ffffff;
}

.inf-check-icon.is-fail {
  background: #dc2626;
  color: #ffffff;
}

.inf-bc-checklist-box {
  border: 1px solid var(--am-border);
  border-radius: 8px;
  overflow: hidden;
  background: var(--am-surface-raised);
}

.inf-bc-checklist-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 12px;
  border: none;
  background: transparent;
  color: var(--am-text-strong);
  font-size: 13px;
  cursor: pointer;
}

.inf-bc-checklist-toggle:hover {
  background: var(--am-surface-soft);
}

.inf-bc-checklist-toggle__left {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.inf-bc-checklist-toggle__left span {
  color: var(--am-text-muted);
}

.inf-bc-checklist-chevron {
  transition: transform 0.15s ease;
}

.inf-bc-checklist-toggle:not(.is-open) .inf-bc-checklist-chevron {
  transform: rotate(-90deg);
}

.inf-bc-checklist-arrow {
  color: var(--am-text-muted);
}

.inf-bc-checklist-body {
  border-top: 1px solid var(--am-border);
}

.inf-bc-checklist-list {
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 220px;
  overflow-y: auto;
}

.inf-bc-checklist-row {
  display: grid;
  grid-template-columns: 24px 26px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 7px 12px;
  border-bottom: 1px solid var(--am-border);
  font-size: 13px;
  color: var(--am-text-strong);
  transition: background-color 120ms ease;
}

.inf-bc-checklist-row:last-child {
  border-bottom: none;
}

.inf-bc-checklist-row:hover {
  background: var(--am-row-hover);
}

.inf-bc-checklist-idx {
  font-size: 12px;
  color: var(--am-text-muted);
  font-variant-numeric: tabular-nums;
}

.inf-bc-checklist-thumb {
  width: 26px;
  height: 26px;
  border-radius: 4px;
  border: 1px solid var(--am-border);
  background: var(--am-surface-soft);
  object-fit: cover;
  display: block;
}

.inf-bc-checklist-thumb--fallback {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--am-text-muted);
}

.inf-bc-checklist-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}

.inf-bc-checklist-meta {
  font-size: 12px;
  color: var(--am-text-muted);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.inf-bc-checklist-foot {
  padding: 7px 12px;
  border-top: 1px solid var(--am-border);
  background: var(--am-surface-soft);
  font-size: 12px;
  color: var(--am-text-muted);
}

.inf-bc-invalid-box {
  padding: 10px 12px;
  border: 1px solid #fecaca;
  border-radius: 8px;
  background: color-mix(in srgb, #dc2626 8%, var(--am-surface));
  display: grid;
  gap: 8px;
}

.inf-bc-invalid-box__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: #dc2626;
}

.inf-bc-invalid-box ul {
  margin: 0;
  padding-left: 16px;
  display: grid;
  gap: 4px;
  font-size: 12px;
}

.inf-bc-invalid-box li {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}

.inf-bc-right {
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}

.inf-bc-preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex: none;
}

.inf-bc-preview-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  font-size: 13px;
}

.inf-bc-preview-meta span {
  color: var(--am-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inf-bc-preview-nav {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--am-text-muted);
  white-space: nowrap;
}

.inf-bc-preview-nav button {
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--am-text);
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.inf-bc-preview-nav button:hover:not(:disabled) {
  background: var(--am-surface-soft);
}

.inf-bc-preview-nav button:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.inf-bc-preview-stage {
  position: relative;
  flex: 1 1 0;
  min-height: 360px;
  border-radius: 6px;
  background: var(--am-surface-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.inf-bc-preview-stage img {
  position: absolute;
  inset: 10px;
  width: calc(100% - 20px);
  height: calc(100% - 20px);
  object-fit: contain;
  display: block;
}

.inf-bc-preview-empty {
  display: grid;
  justify-items: center;
  gap: 8px;
  color: var(--am-text-muted);
  font-size: 13px;
}

.inf-bc-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0 2px;
  border-top: 1px solid var(--am-border);
}

.inf-bc-footer__right {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}
</style>
