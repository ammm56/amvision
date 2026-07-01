<template>
  <div v-if="open" class="deployment-source-picker-backdrop" @click="$emit('close')">
    <div
      class="deployment-source-picker"
      role="dialog"
      aria-modal="true"
      aria-label="选择部署来源模型"
      @click.stop
      @keydown.esc.prevent="$emit('close')"
    >
      <header class="deployment-source-picker__header">
        <div>
          <p class="page-kicker">DEPLOYMENT SOURCE</p>
          <h2>选择部署来源模型</h2>
          <p class="deployment-source-picker__description">
            按当前 task_type 浏览已登记的 ModelVersion 和转换完成的 ModelBuild，选择后自动填入部署所需信息。
          </p>
        </div>
        <button
          type="button"
          class="deployment-source-picker__close"
          title="关闭"
          aria-label="关闭"
          @click="$emit('close')"
        >
          <X :size="16" />
        </button>
      </header>

      <div class="deployment-source-picker__toolbar">
        <span class="deployment-source-picker__label">当前任务类型</span>
        <span class="deployment-source-pill">{{ taskType }}</span>
        <Button size="sm" variant="secondary" :disabled="loading" @click.stop="$emit('refresh')">
          <RefreshCw :size="14" />
          刷新
        </Button>
      </div>

      <div class="deployment-source-picker__body">
        <section class="deployment-source-picker__column">
          <header class="deployment-source-picker__section-heading">
            <strong>模型列表</strong>
            <span class="deployment-source-picker__section-count">{{ models.length }}</span>
          </header>

          <EmptyState
            v-if="!loading && models.length === 0"
            title="暂无可部署模型"
            description="完成训练登记或模型转换后，可部署的 ModelVersion / ModelBuild 会显示在这里。"
          />

          <div v-else class="deployment-source-picker__grid">
            <button
              v-for="model in models"
              :key="model.model_id"
              type="button"
              class="deployment-source-card"
              :class="{ 'is-selected': model.model_id === selectedModelId }"
              @click.stop="$emit('select-model', model.model_id)"
            >
              <div class="deployment-source-card__identity">
                <strong>{{ model.model_name }}</strong>
                <span>{{ model.model_id }}</span>
              </div>
              <div class="deployment-source-card__meta">
                <span class="deployment-source-pill">{{ model.model_type }}</span>
                <span class="deployment-source-pill">{{ model.task_type }}</span>
                <span class="deployment-source-pill">Scale · {{ model.model_scale }}</span>
              </div>
              <div class="deployment-source-card__footer">
                <span>版本 {{ model.version_count }}</span>
                <span>构建 {{ model.build_count }}</span>
              </div>
            </button>
          </div>
        </section>

        <section class="deployment-source-picker__column deployment-source-picker__detail">
          <header class="deployment-source-picker__section-heading">
            <strong>模型详情</strong>
          </header>

          <div v-if="selectedModelDetail" class="deployment-source-detail">
            <div class="deployment-source-detail__summary">
              <div class="deployment-source-detail__identity">
                <strong>{{ selectedModelDetail.model_name }}</strong>
                <span>{{ selectedModelDetail.model_id }}</span>
              </div>
              <div class="deployment-source-card__meta">
                <span class="deployment-source-pill">{{ selectedModelDetail.model_type }}</span>
                <span class="deployment-source-pill">{{ selectedModelDetail.task_type }}</span>
                <span class="deployment-source-pill">Scale · {{ selectedModelDetail.model_scale }}</span>
              </div>
            </div>

            <section class="deployment-source-group">
              <header class="deployment-source-picker__section-heading">
                <strong>转换完成的 ModelBuild</strong>
                <span class="deployment-source-picker__section-count">{{ selectedModelDetail.builds.length }}</span>
              </header>
              <div v-if="selectedModelDetail.builds.length > 0" class="compact-list">
                <div
                  v-for="build in selectedModelDetail.builds"
                  :key="build.model_build_id"
                  class="compact-list__item"
                  :class="{ 'is-active': build.model_build_id === selectedBuildId }"
                >
                  <div class="deployment-source-build-meta">
                    <strong>{{ build.model_build_id }}</strong>
                    <span>
                      {{ build.build_format }} · {{ build.runtime_backend }} ·
                      {{ build.runtime_precision.toUpperCase() }}
                    </span>
                    <small>RuntimeProfile（可选）：{{ build.runtime_profile_id || '未绑定' }}</small>
                  </div>
                  <div class="table-actions">
                    <Button size="sm" variant="secondary" @click.stop="$emit('apply-source', buildSelection(build))">
                      使用构建
                    </Button>
                  </div>
                </div>
              </div>
              <div v-else class="deployment-source-detail__empty">
                <strong>暂无转换构建</strong>
                <span>如果需要 ONNX / OpenVINO / TensorRT 部署，先在模型页完成转换。</span>
              </div>
            </section>

            <section class="deployment-source-group">
              <header class="deployment-source-picker__section-heading">
                <strong>可直接部署的 ModelVersion</strong>
                <span class="deployment-source-picker__section-count">{{ selectedModelDetail.versions.length }}</span>
              </header>
              <div v-if="selectedModelDetail.versions.length > 0" class="compact-list">
                <div
                  v-for="version in selectedModelDetail.versions"
                  :key="version.model_version_id"
                  class="compact-list__item"
                  :class="{ 'is-active': version.model_version_id === selectedVersionId && !selectedBuildId }"
                >
                  <div>
                    <strong>{{ version.model_version_id }}</strong>
                    <span>{{ version.source_kind }}</span>
                  </div>
                  <div class="table-actions">
                    <Button size="sm" variant="secondary" @click.stop="$emit('apply-source', versionSelection(version))">
                      使用版本
                    </Button>
                  </div>
                </div>
              </div>
              <div v-else class="deployment-source-detail__empty">
                <strong>暂无 ModelVersion</strong>
                <span>完成训练登记后，可直接部署的版本会显示在这里。</span>
              </div>
            </section>
          </div>

          <div v-else class="deployment-source-detail__empty deployment-source-detail__empty--large">
            <strong>请选择左侧模型</strong>
            <span>选择模型后，这里会显示可部署版本和转换构建。</span>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { X, RefreshCw } from '@lucide/vue'

import type {
  DeploymentSourceModelBuild,
  DeploymentSourceModelDetail,
  DeploymentSourceModelSummary,
  DeploymentSourceModelVersionDetail,
} from '@/modules/models/services/model.service'
import Button from '@/shared/ui/components/Button.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import type { ModelTaskType } from '../services/deployment.service'
import type { DeploymentSourceSelection } from './deployment-source.types'

const props = defineProps<{
  open: boolean
  loading: boolean
  taskType: ModelTaskType
  models: DeploymentSourceModelSummary[]
  selectedModelId: string
  selectedModelDetail: DeploymentSourceModelDetail | null
  selectedVersionId: string
  selectedBuildId: string
}>()

defineEmits<{
  close: []
  refresh: []
  'select-model': [modelId: string]
  'apply-source': [selection: DeploymentSourceSelection]
}>()

function buildSelection(build: DeploymentSourceModelBuild): DeploymentSourceSelection {
  const model = props.selectedModelDetail
  if (!model) {
    throw new Error('missing selected model detail')
  }
  return {
    sourceKind: 'model-build',
    modelId: model.model_id,
    modelName: model.model_name,
    modelType: model.model_type,
    modelScale: model.model_scale,
    taskType: props.taskType,
    modelVersionId: build.source_model_version_id,
    modelBuildId: build.model_build_id,
    buildFormat: build.build_format,
    runtimeProfileId: build.runtime_profile_id ?? '',
    runtimeBackend: build.runtime_backend,
    runtimePrecision: build.runtime_precision,
  }
}

function versionSelection(version: DeploymentSourceModelVersionDetail): DeploymentSourceSelection {
  const model = props.selectedModelDetail
  if (!model) {
    throw new Error('missing selected model detail')
  }
  return {
    sourceKind: 'model-version',
    modelId: model.model_id,
    modelName: model.model_name,
    modelType: model.model_type,
    modelScale: model.model_scale,
    taskType: props.taskType,
    modelVersionId: version.model_version_id,
    modelBuildId: '',
    buildFormat: '',
    runtimeProfileId: '',
    runtimeBackend: 'pytorch',
    runtimePrecision: 'fp32',
  }
}
</script>

<style scoped>
.deployment-source-picker-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 18px;
  background: rgb(16 20 24 / 0.38);
}

.deployment-source-picker {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 12px;
  width: min(1120px, calc(100vw - 36px));
  max-height: min(820px, calc(100vh - 36px));
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  box-shadow: 0 24px 48px rgb(0 0 0 / 0.18);
}

.deployment-source-picker__header,
.deployment-source-picker__toolbar,
.deployment-source-picker__section-heading,
.deployment-source-card__meta,
.deployment-source-card__footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.deployment-source-picker__header h2,
.deployment-source-picker__header p {
  margin: 0;
}

.deployment-source-picker__description {
  margin-top: 8px !important;
  color: var(--muted);
}

.deployment-source-picker__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  color: var(--text);
  background: var(--button-secondary-bg);
  cursor: pointer;
}

.deployment-source-picker__label {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}

.deployment-source-picker__body {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr);
  gap: 14px;
  min-height: 0;
}

.deployment-source-picker__column,
.deployment-source-detail,
.deployment-source-group {
  display: grid;
  gap: 12px;
  min-height: 0;
  align-content: start;
}

.deployment-source-picker__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  align-content: start;
  overflow: auto;
  padding-right: 4px;
}

.deployment-source-card,
.deployment-source-detail__summary,
.deployment-source-detail__empty {
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--summary-bg);
}

.deployment-source-card {
  display: grid;
  gap: 12px;
  width: 100%;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}

.deployment-source-card:hover,
.deployment-source-card.is-selected,
.compact-list__item.is-active {
  border-color: var(--accent);
  background: var(--selected-row-bg);
}

.deployment-source-card__identity,
.deployment-source-detail__identity,
.deployment-source-build-meta,
.deployment-source-detail__empty {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.deployment-source-card__identity strong,
.deployment-source-card__identity span,
.deployment-source-detail__identity strong,
.deployment-source-detail__identity span,
.deployment-source-detail__empty strong,
.deployment-source-detail__empty span {
  overflow-wrap: anywhere;
}

.deployment-source-card__identity span,
.deployment-source-detail__identity span,
.deployment-source-build-meta span,
.deployment-source-build-meta small,
.deployment-source-detail__empty span,
.deployment-source-card__footer {
  color: var(--muted);
  font-size: 12px;
}

.deployment-source-picker__section-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  min-height: 24px;
  padding: 0 8px;
  border-radius: 999px;
  color: var(--muted);
  background: var(--button-secondary-bg);
  font-size: 12px;
  font-weight: 700;
}

.deployment-source-pill {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  color: var(--badge-neutral-text);
  background: var(--badge-neutral-bg);
  font-size: 12px;
  font-weight: 700;
}

.deployment-source-detail__summary {
  display: grid;
  gap: 12px;
  align-content: start;
}

.deployment-source-detail__empty--large {
  min-height: 200px;
  align-content: center;
}

@media (max-width: 960px) {
  .deployment-source-picker {
    width: min(100%, calc(100vw - 24px));
    max-height: min(100%, calc(100vh - 24px));
  }

  .deployment-source-picker__body {
    grid-template-columns: 1fr;
  }
}
</style>
