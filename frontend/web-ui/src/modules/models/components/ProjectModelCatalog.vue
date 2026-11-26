<template>
  <section class="model-catalog" aria-label="模型版本">
    <ModelListToolbar class="model-catalog__toolbar" :zh="zh" :search="initialEmpty ? undefined : search" :search-label="zh ? '搜索模型名称' : 'Search models'"
      @update:search="search = $event.trim()" @open-base-models="$emit('open-base-models')">
      <template v-if="initialEmpty" #leading>
        <ProjectSwitcher class="model-catalog__project-switch" :aria-label="zh ? '切换项目' : 'Switch project'" />
        <span class="model-catalog__hint"><CircleHelp :size="16" aria-hidden="true" />{{ zh ? '基础模型是平台预置资源，不计入当前项目模型版本。' : 'Base models are not counted as project models.' }}</span>
      </template>
      <div v-if="!initialEmpty" class="model-catalog__filter"><span>{{ zh ? '任务类型' : 'Task type' }}</span>
        <Select :model-value="taskType" :options="taskOptions" :aria-label="zh ? '任务类型' : 'Task type'" @update:model-value="updateTaskType($event)" />
      </div>
      <Button v-if="!initialEmpty" :loading="loading" @click="load"><RefreshCw v-if="!loading" :size="16" />{{ zh ? '刷新' : 'Refresh' }}</Button>
    </ModelListToolbar>
    <div v-if="!canEdit && !canTrain" class="model-catalog__notice model-catalog__notice--warning" role="status">
      <LockKeyhole :size="17" aria-hidden="true" /><div><strong>{{ zh ? '只读访问' : 'Read-only access' }}</strong>
        <p>{{ zh ? '可以查看模型和版本详情。当前账号无权创建训练或编辑、删除模型。' : 'You can view model details. This account cannot create training, edit models, or delete them.' }}</p></div>
    </div>
    <div v-if="error && matchingSnapshot" class="model-catalog__notice model-catalog__notice--error" role="alert">
      <WifiOff :size="18" aria-hidden="true" /><div><strong>{{ connectionLost ? (zh ? '无法连接到模型服务' : 'Cannot connect to the model service') : (zh ? '模型列表刷新失败' : 'Model list refresh failed') }}</strong>
        <p>{{ zh ? '当前显示上一次成功加载的结果，数据可能已过期。' : 'Showing the last successful results. Data may be out of date.' }}</p></div>
      <span>{{ zh ? '最后更新：' : 'Last updated: ' }}{{ formatSystemDateTime(matchingSnapshot.updatedAt, 'minutes') }}</span>
      <Button size="sm" variant="primary" @click="load"><RefreshCw :size="15" />{{ connectionLost ? (zh ? '重新连接' : 'Reconnect') : (zh ? '重试刷新' : 'Retry refresh') }}</Button>
    </div>
    <div v-if="error && !matchingSnapshot" class="model-catalog__message" role="alert">{{ accessDenied ? (zh ? '当前账号无权读取此项目的模型。' : 'This account cannot read models in this project.') : (zh ? '模型列表加载失败，请重试。' : 'Could not load models. Please retry.') }} <Button size="sm" @click="load">{{ zh ? '重试' : 'Retry' }}</Button>
      <Button v-if="page > 1 && !accessDenied" size="sm" variant="ghost" @click="page--">{{ zh ? '返回上一页' : 'Back to the previous page' }}</Button>
    </div>
    <div v-else-if="loading && !matchingSnapshot" class="model-catalog__message" role="status">{{ zh ? '正在加载模型…' : 'Loading models…' }}</div>
    <div v-else-if="initialEmpty" class="model-catalog__initial-empty">
      <svg class="model-catalog__empty-art" viewBox="0 0 240 168" fill="none" aria-hidden="true">
        <ellipse cx="120" cy="140" rx="109" ry="22" fill="currentColor" opacity=".09" />
        <path d="m54 69 61-23 70 18v71l-63 22-68-17z" fill="currentColor" fill-opacity=".1" stroke="currentColor" stroke-opacity=".66" stroke-width="1.5" stroke-linejoin="round" />
        <path d="m54 69 68 17 63-22m-63 22v71" stroke="currentColor" stroke-opacity=".5" stroke-width="1.5" />
        <path d="m78 92 39 10v37l-39-10z" fill="currentColor" opacity=".2" />
        <path d="m86 107 9-3 10 5v12l-9 4-10-6zm0 0 10 6 9-4m-9 4v12" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" />
        <path d="m174 38 2-18m13 23 13-14m-4 28 16-6" stroke="currentColor" stroke-opacity=".75" stroke-width="3.5" stroke-linecap="round" />
      </svg>
      <h2>{{ zh ? '当前项目还没有模型版本' : 'No model versions in this project' }}</h2>
      <div v-if="canTrain || canEdit" class="model-catalog__empty-actions">
        <Button v-if="canTrain" variant="primary" @click="$emit('create-training')"><Plus :size="18" />{{ zh ? '创建训练' : 'Create training' }}</Button>
        <Button v-if="canEdit" @click="$emit('import-model-package')"><Upload :size="18" />{{ zh ? '导入模型包' : 'Import model package' }}</Button>
      </div>
    </div>
    <div v-else-if="matchingSnapshot" class="resource-table model-catalog__table" :aria-busy="loading">
      <p v-if="loading" class="model-catalog__refresh-state" role="status">{{ zh ? '正在刷新模型列表…' : 'Refreshing the model list…' }}</p>
      <table>
        <colgroup><col class="model-catalog__name-column" /><col class="model-catalog__task-column" /><col class="model-catalog__version-column" /><col class="model-catalog__source-column" /><col class="model-catalog__format-column" /><col class="model-catalog__action-column" /></colgroup>
        <thead><tr><th>{{ zh ? '模型名称' : 'Model' }}</th><th>{{ zh ? '任务' : 'Task' }}</th><th>{{ zh ? '最新版本' : 'Latest version' }}</th><th>{{ zh ? '来源' : 'Source' }}</th><th>{{ zh ? '运行格式' : 'Formats' }}</th><th>{{ zh ? '操作' : 'Actions' }}</th></tr></thead>
        <tbody>
          <tr v-for="model in items" :key="model.model_id" :class="{ 'is-selected': selected?.model_id === model.model_id }">
            <td :title="displayName(model)"><strong>{{ displayName(model) }}</strong></td><td>{{ modelTaskLabel(model.task_type, zh) }}</td>
            <td :title="latestVersionLabel(model, false)">{{ latestVersionLabel(model, true) }}</td>
            <td>{{ sources(model) }}</td>
            <td><ModelRuntimeFormats :formats="formats(model)" :fallback-label="model.build_count ? (zh ? `${model.build_count} 个产物` : `${model.build_count} builds`) : undefined" /></td>
            <td><div class="model-catalog__actions"><Button size="sm" variant="ghost" class="ui-button--row-view" @click="openDetail(model)">{{ zh ? '查看' : 'View' }}</Button><ResourceMenu v-if="canEdit && !error" :label="zh ? '更多操作' : 'More actions'" :items="[{ id: 'edit', label: zh ? '编辑' : 'Edit', icon: Pencil }]" @action="editing = model" /></div></td>
          </tr>
          <tr v-if="!items.length"><td colspan="6" class="model-catalog__empty">
            <div v-if="filtered" class="model-catalog__no-results"><Search :size="25" aria-hidden="true" />
              <strong>{{ zh ? '没有符合条件的模型' : 'No matching models' }}</strong>
              <p v-if="search">{{ zh ? `没有找到与“${search}”相关的模型。` : `No models match “${search}”.` }}</p>
              <Button variant="primary" size="sm" @click="clearFilters">{{ zh ? '清除筛选条件' : 'Clear filters' }}</Button>
            </div>
            <template v-else>{{ zh ? '当前项目暂无模型' : 'No models in this project' }}</template>
          </td></tr>
        </tbody>
      </table>
      <ModelListPagination v-if="total" :page="page" :page-size="pageSize" :item-count="items.length" :total="total" :zh="zh" :loading="loading"
        @page="page = $event" @page-size="pageSize = $event; page = 1" />
    </div>
    <p v-if="deepLinkError" class="model-catalog__message" role="alert">{{ zh ? '无法打开指定的模型版本。' : 'Unable to open the requested model version.' }}</p>
    <SideDrawer :panel-class="`model-drawer model-version-drawer${artifactView ? ' model-artifact-drawer' : ''}`" :open="!!selected" :title="referenceView ? (zh ? '关联引用' : 'References') : artifactView ? (zh ? '模型产物' : 'Model artifact') : (zh ? '模型版本' : 'Model version')" :close-label="zh ? '关闭' : 'Close'" @close="selected = null">
      <template v-if="referenceView || artifactView" #header-leading>
        <Button size="sm" variant="ghost" icon-only :aria-label="zh ? '返回版本' : 'Back to version'" @click="referenceView ? backFromReferences() : backFromArtifact()"><ArrowLeft :size="17" /></Button>
      </template>
      <p v-if="detailLoading" role="status">{{ zh ? '正在加载版本…' : 'Loading versions…' }}</p>
      <p v-else-if="detailError" role="alert">{{ zh ? '版本详情加载失败，请重试。' : 'Could not load model details.' }} <Button size="sm" @click="selected && openDetail(selected)">{{ zh ? '重试' : 'Retry' }}</Button></p>
      <template v-else-if="detail">
        <template v-if="referenceView">
          <h2 ref="referenceHeading" class="model-detail__name model-reference__title" tabindex="-1">{{ displayName(detail) }}</h2>
          <p class="model-reference__version">{{ activeVersion ? modelVersionDisplayName(activeVersion) : '—' }}<template v-if="referenceBuild"> · {{ formatBuild(referenceBuild) }} {{ referenceBuild.runtime_precision.toUpperCase() }}</template></p>
          <p class="model-reference__hint">{{ zh ? '仅显示直接引用；间接引用可从部署详情查看。' : 'Only direct references are shown; indirect references can be viewed from the deployment.' }}</p>
          <label class="model-reference__search"><Search :size="16" /><input v-model.trim="referenceQuery" :placeholder="zh ? '搜索名称' : 'Search name'" :aria-label="zh ? '搜索引用名称' : 'Search references'" /></label>
          <p v-if="referenceError" class="model-reference__state" role="alert">{{ zh ? '引用加载失败。' : 'Could not load references.' }} <Button size="sm" @click="loadReferences">{{ zh ? '重试' : 'Retry' }}</Button></p>
          <p v-else-if="referenceLoading && !references.length" class="model-reference__state" role="status">{{ zh ? '正在加载引用…' : 'Loading references…' }}</p>
          <template v-else>
            <p class="model-reference__count">{{ zh ? `共 ${referenceTotal} 条` : `${referenceTotal} references` }}</p>
            <div class="resource-table model-reference__table" :aria-busy="referenceLoading"><table><colgroup><col style="width:16%" /><col style="width:26%" /><col style="width:17%" /><col style="width:27%" /><col style="width:14%" /></colgroup><thead><tr><th>{{ zh ? '类型' : 'Type' }}</th><th>{{ zh ? '名称' : 'Name' }}</th><th>{{ zh ? '产物' : 'Artifact' }}</th><th>{{ zh ? '状态' : 'State' }}</th><th>{{ zh ? '操作' : 'Action' }}</th></tr></thead><tbody>
              <tr v-for="item in references" :key="item.deployment_id">
                <td><span class="model-reference__cell"><Rocket :size="15" aria-hidden="true" />{{ zh ? '部署' : 'Deployment' }}</span></td>
                <td :title="item.display_name">{{ item.display_name }}</td>
                <td :title="item.build_format || ''">{{ item.build_format ? formatBuildName(item.build_format) : (zh ? '原始权重' : 'Original') }}</td>
                <td class="model-reference__runtime"><span v-for="state in runtimeStates(item.runtime_states)" :key="state.key" class="model-reference__cell" :class="{ 'is-running': state.status === 'running', 'is-failed': state.status === 'failed' }">
                  <CirclePlay v-if="state.status === 'running'" :size="14" aria-hidden="true" /><CircleStop v-else-if="state.status === 'stopped'" :size="14" aria-hidden="true" /><CircleAlert v-else :size="14" aria-hidden="true" />{{ state.label }}
                </span></td>
                <td><ButtonLink size="sm" variant="ghost" class="ui-button--row-view" :to="{ path: '/deployments', query: { deployment: item.deployment_id } }"><Eye :size="15" aria-hidden="true" />{{ zh ? '查看' : 'View' }}</ButtonLink></td>
              </tr>
              <tr v-if="!references.length"><td colspan="5">{{ referenceQuery ? (zh ? '没有符合条件的引用' : 'No matching references') : (zh ? '暂无直接部署引用' : 'No direct deployment references') }}</td></tr>
            </tbody></table></div>
            <div class="model-reference__pagination"><span>{{ zh ? '每页 6 条' : '6 per page' }}</span><div><Button size="sm" :disabled="referencePage <= 1 || referenceLoading" @click="referencePage--">{{ zh ? '上一页' : 'Previous' }}</Button><span>{{ referencePage }} / {{ referencePageCount }}</span><Button size="sm" :disabled="referencePage >= referencePageCount || referenceLoading" @click="referencePage++">{{ zh ? '下一页' : 'Next' }}</Button></div></div>
          </template>
        </template>
        <ModelPackageExport v-else-if="exportView && activeVersion" :project-id="projectId" :name="displayName(detail)" :task-type="detail.task_type" :version="activeVersion" :builds="versionBuilds" :zh="zh" @back="exportView = false" />
        <ModelBuildDetail v-else-if="artifactView && activeVersion" ref="artifactDetail" drawer :build="selectedBuild" :version="activeVersion" :model-id="detail.model_id" :project-id="projectId" :model-name="displayName(detail)" />
        <template v-else>
        <div class="model-detail__heading-row">
          <h2 class="model-detail__name">{{ displayName(detail) }}</h2>
          <TooltipProvider :delay-duration="150">
            <TooltipRoot>
              <TooltipTrigger as-child>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  icon-only
                  class="model-detail__copy-btn"
                  data-model-action="copy-id"
                  :aria-label="`${zh ? '复制 ID' : 'Copy ID'}: ${activeVersion?.model_version_id || detail.model_id}`"
                  @click="copyModelDetailId(activeVersion?.model_version_id || detail.model_id)"
                >
                  <Check v-if="copiedDetailId" :size="14" class="is-copied" aria-hidden="true" />
                  <Copy v-else :size="14" aria-hidden="true" />
                </Button>
              </TooltipTrigger>
              <TooltipPortal>
                <TooltipContent class="model-detail-id-tooltip" side="bottom" align="end" :side-offset="6" :collision-padding="12">
                  <div>
                    <span>{{ zh ? '模型 ID' : 'Model ID' }}</span>
                    <code>{{ detail.model_id }}</code>
                  </div>
                  <div v-if="activeVersion?.model_version_id">
                    <span>{{ zh ? '版本 ID' : 'Version ID' }}</span>
                    <code>{{ activeVersion.model_version_id }}</code>
                  </div>
                </TooltipContent>
              </TooltipPortal>
            </TooltipRoot>
          </TooltipProvider>
        </div>
        <div v-if="detail.versions.length" class="model-detail__version"><span>{{ zh ? '版本' : 'Version' }}</span>
          <Select :model-value="selectedVersionId" :options="versionOptions" :aria-label="zh ? '版本' : 'Version'" @update:model-value="selectedVersionId = typeof $event === 'string' ? $event : ''" />
        </div>
        <p v-else>{{ zh ? '暂无版本' : 'No versions' }}</p>
        <dl class="model-detail__meta">
          <div><dt>{{ zh ? '任务' : 'Task' }}</dt><dd>{{ modelTaskLabel(detail.task_type, zh) }}</dd></div>
          <div v-if="categoryCount !== null"><dt>{{ zh ? '类别数' : 'Classes' }}</dt><dd>{{ categoryCount }}</dd></div>
          <div v-if="inputSize"><dt>{{ zh ? '输入尺寸' : 'Input size' }}</dt><dd>{{ inputSize }}</dd></div>
        </dl>
        <section v-if="modelDescription" class="model-detail__section model-detail__description">
          <h3>{{ zh ? '模型描述' : 'Model description' }}</h3>
          <p ref="descriptionElement" :class="{ 'is-collapsed': !descriptionExpanded }">{{ modelDescription }}</p>
          <Button v-if="descriptionOverflow || descriptionExpanded" size="sm" variant="ghost" :aria-expanded="descriptionExpanded" @click="descriptionExpanded = !descriptionExpanded">{{ descriptionExpanded ? (zh ? '收起说明' : 'Collapse description') : (zh ? '展开说明' : 'Expand description') }}</Button>
        </section>
        <section v-if="activeVersion" class="model-detail__section">
          <h3>{{ zh ? '来源' : 'Source' }}</h3>
          <ol class="model-source">
            <li v-if="activeVersion.dataset_version_id || versionSource?.dataset" class="model-source__step">
              <Database :size="19" aria-hidden="true" />
              <div>
                <RouterLink v-if="versionSource?.dataset" class="model-source__dataset" :title="versionSource.dataset.display_name" :to="`/datasets/${encodeURIComponent(versionSource.dataset.dataset_id)}/versions/${encodeURIComponent(versionSource.dataset.dataset_version_id)}`">{{ versionSource.dataset.display_name }}</RouterLink>
                <strong v-else>{{ sourceLoading ? (zh ? '正在读取数据集' : 'Loading dataset') : (zh ? '数据集详情不可用' : 'Dataset details unavailable') }}</strong>
                <span>{{ versionSource?.dataset ? `v${versionSource.dataset.version_number}` : '—' }}</span>
              </div>
            </li>
            <li class="model-source__step">
              <CircleCheck v-if="trainingTask?.state === 'succeeded'" class="model-source__success" :size="19" aria-hidden="true" />
              <FileText v-else :size="19" aria-hidden="true" />
              <div>
                <RouterLink v-if="trainingTask && activeVersion.training_task_id && isKnownTask(detail.task_type)" :to="`/models/${detail.task_type}/training-tasks/${activeVersion.training_task_id}`">
                  {{ trainingTask.state === 'succeeded' ? (zh ? '训练完成' : 'Training completed') : (trainingTask.display_name || sourceName(activeVersion.source_kind)) }}
                </RouterLink>
                <strong v-else>{{ sourceName(activeVersion.source_kind) }}</strong>
                <span v-if="trainingTask?.finished_at">{{ formatSystemDateTime(trainingTask.finished_at) }}</span>
              </div>
            </li>
            <li class="model-source__step">
              <Package :size="19" aria-hidden="true" />
              <div><strong>{{ modelVersionDisplayName(activeVersion) }}</strong><span>{{ zh ? '当前版本' : 'Current version' }}</span></div>
            </li>
          </ol>
          <p v-if="sourceError" class="model-source__error" role="status">{{ zh ? '来源详情暂不可用。' : 'Source details are unavailable.' }} <Button size="sm" variant="ghost" @click="sourceRetry++">{{ zh ? '重试' : 'Retry' }}</Button></p>
        </section>
        <section v-if="versionMetric" class="model-detail__section">
          <h3>{{ zh ? '评估指标' : 'Evaluation metrics' }}</h3>
          <dl class="model-detail__metric">
            <div><dt>{{ versionMetric.name.replace(/^val_map50_95$/, 'val mAP50–95') }}</dt><dd><strong>{{ formatModelNumber(versionMetric.value) }}</strong></dd></div>
            <div><dt>{{ zh ? '最佳轮次' : 'Best epoch' }}</dt><dd>{{ versionMetric.epoch ?? '—' }}<template v-if="versionMetric.epoch !== undefined && versionMetric.maxEpochs !== undefined"> / {{ versionMetric.maxEpochs }}</template></dd></div>
          </dl>
        </section>
        <section class="model-detail__section"><h3>{{ zh ? '模型产物' : 'Model artifacts' }}</h3>
          <div class="resource-table model-detail__table"><table><thead><tr><th>{{ zh ? '文件格式' : 'Format' }}</th><th>{{ zh ? '精度' : 'Precision' }}</th><th>{{ zh ? '状态' : 'Status' }}</th><th>{{ zh ? '操作' : 'Action' }}</th></tr></thead><tbody>
            <tr v-if="checkpoint">
              <td><span class="model-reference__cell"><FileText :size="15" aria-hidden="true" />{{ zh ? 'PyTorch（原始文件）' : 'PyTorch (original)' }}</span></td>
              <td>{{ originalPrecision }}</td>
              <td><span class="model-reference__cell" :class="{ 'model-artifact__success': checkpointState === 'present' }"><CircleCheck v-if="checkpointState === 'present'" :size="15" aria-hidden="true" />{{ checkpointStatusLabel }}</span></td>
              <td><Button size="sm" variant="ghost" :disabled="checkpointState !== 'present'" :loading="checkpointDownloading" @click="downloadCheckpoint"><Download :size="15" />{{ zh ? '下载' : 'Download' }}</Button></td>
            </tr>
            <tr v-for="build in versionBuilds" :key="build.model_build_id">
              <td><span class="model-reference__cell"><FileText :size="15" aria-hidden="true" />{{ formatBuild(build) }}</span></td>
              <td>{{ build.runtime_precision.toUpperCase() }}</td>
              <td><span class="model-reference__cell" :class="{ 'model-artifact__success': modelBuildValidation(build) === true }">
                <CircleCheck v-if="modelBuildValidation(build) === true" :size="15" aria-hidden="true" />{{ buildStatusLabel(build) }}
              </span></td>
              <td><div class="model-detail__artifact-actions">
                <Button size="sm" variant="ghost" :data-artifact="build.model_build_id" @click="selectedBuild = build"><List :size="15" />{{ zh ? '详情' : 'Details' }}</Button>
                <Button v-if="canEdit" size="sm" variant="ghost" icon-only :disabled="error" :aria-label="`${zh ? '删除产物' : 'Delete artifact'} ${formatBuild(build)} ${build.runtime_precision.toUpperCase()}`" @click="buildToDelete = build"><Trash2 :size="15" /></Button>
              </div></td>
            </tr>
            <tr v-if="!checkpoint && !versionBuilds.length"><td colspan="4">{{ zh ? '暂无产物' : 'No artifacts' }}</td></tr>
          </tbody></table></div>
          <p v-if="checkpointDownloadError" class="model-detail__action-error" role="alert">{{ zh ? '下载失败，请重试。' : 'Download failed. Try again.' }}</p>
        </section>
        <div class="model-detail__disclosures">
          <details class="model-detail__disclosure"><summary><span>{{ zh ? '输入输出与类别' : 'Inputs, outputs and classes' }}</span><ChevronRight :size="16" class="model-detail__chevron" aria-hidden="true" /></summary><p>{{ categoryNames.length ? categoryNames.join(' / ') : (zh ? '暂无类别信息' : 'No class information') }}</p></details>
          <button class="model-detail__files" type="button" data-artifact="" :disabled="!activeVersion?.files.length" @click="originalFilesView = true">
            {{ zh ? '文件与校验' : 'Files and validation' }}<ChevronRight :size="16" aria-hidden="true" />
          </button>
          <button v-if="activeVersion" ref="referencesButton" class="model-detail__references" type="button" @click="referenceView = true">{{ zh ? '关联引用' : 'References' }} <span v-if="referenceLoading">…</span><span v-else-if="referenceError">{{ zh ? '（读取失败）' : '(unavailable)' }}</span><span v-else>（{{ referenceOverallTotal }}）</span><ChevronRight :size="16" /></button>
        </div>
        </template>
      </template>
      <template v-if="referenceView || (artifactView ? selectedBuild : versionActionsVisible)" #footer>
        <Button v-if="referenceView" class="model-reference__close" @click="selected = null">{{ zh ? '关闭' : 'Close' }}</Button>
        <div v-else-if="artifactView" class="model-artifact__actions">
          <Button v-if="selectedBuild" variant="primary" :disabled="!artifactDetail?.filesPresent || !canDeployVersion" @click="deployArtifact"><Package :size="16" />{{ zh ? '创建部署' : 'Create deployment' }}</Button>
        </div>
        <div v-else class="model-detail__footer">
          <p v-if="launchError" class="model-detail__action-error" role="alert">{{ launchError }}</p>
          <div class="model-detail__actions">
            <Button size="sm" :disabled="!canEdit || error" @click="exportView = true">{{ zh ? '导出模型包' : 'Export model package' }}</Button>
            <Button size="sm" variant="danger" :disabled="!canEdit || error" @click="deletionOpen = true">{{ zh ? '删除版本' : 'Delete version' }}</Button>
            <div class="model-detail__launch">
              <Button size="sm" :loading="launchingConversion" :disabled="!canConvertVersion" :title="conversionUnavailable || undefined" @click="requestVersionAction('create-conversion')">{{ zh ? '创建转换' : 'Create conversion' }}</Button>
              <Button size="sm" :variant="canDeployVersion ? 'primary' : 'secondary'" :disabled="!canDeployVersion" :title="deploymentUnavailable || undefined" @click="requestVersionAction('create-deployment')">{{ zh ? '创建部署' : 'Create deployment' }}</Button>
            </div>
          </div>
        </div>
      </template>
    </SideDrawer>
    <ModelPresentationEditor ref="presentationEditor" :open="!!editing" :model="editing" :project-id="projectId" @close="editing = null" @saved="editing = null; load()" />
    <ModelVersionDeleteDialog :open="deletionOpen" :project-id="projectId" :model-id="detail?.model_id ?? ''" :version-id="selectedVersionId" :version-label="activeVersion ? modelVersionDisplayName(activeVersion) : undefined"
      :model-name="detail ? displayName(detail) : ''" :task-type="detail?.task_type" :formats="selectedVersionFormats"
      :other-version-count="Math.max(0, (detail?.versions.length ?? 0) - 1)"
      @close="deletionOpen = false" @references="openVersionDeletionReferences" @deleted="onVersionDeleted" @uncertain="refreshAfterUnknownDeletion" />
    <ModelBuildDeleteDialog v-if="buildToDelete && detail" :key="buildToDelete.model_build_id" :zh="zh" :project-id="projectId"
      :model-id="detail.model_id" :model-name="displayName(detail)" :version-id="selectedVersionId" :version-label="activeVersion ? modelVersionDisplayName(activeVersion) : undefined" :build="buildToDelete" :format="formatBuild(buildToDelete)"
      @close="closeBuildDeletion" @references="referenceBuild = buildToDelete; buildToDelete = null; referenceView = true"
      @deleted="onArtifactDeleted" @uncertain="buildDeletionUncertain = true" />
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import ProjectSwitcher from '@/modules/projects/components/ProjectSwitcher.vue'
import { ArrowLeft, Check, ChevronRight, CircleAlert, CircleCheck, CircleHelp, CirclePlay, CircleStop, Copy, Database, Download, Eye, FileText, List, LockKeyhole, Package, Pencil, Plus, RefreshCw, Rocket, Search, Trash2, Upload, WifiOff } from '@lucide/vue'
import { TooltipContent, TooltipPortal, TooltipProvider, TooltipRoot, TooltipTrigger } from 'reka-ui'
import Button from '@/shared/ui/components/Button.vue'
import ButtonLink from '@/shared/ui/components/ButtonLink.vue'
import Select from '@/shared/ui/components/Select.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import ResourceMenu from '@/shared/ui/components/ResourceMenu.vue'
import ModelBuildDetail from './ModelBuildDetail.vue'
import ModelRuntimeFormats from './ModelRuntimeFormats.vue'
import ModelListToolbar from './ModelListToolbar.vue'
import ModelBuildDeleteDialog from './ModelBuildDeleteDialog.vue'
import ModelPresentationEditor from './ModelPresentationEditor.vue'
import ModelVersionDeleteDialog from './ModelVersionDeleteDialog.vue'
import ModelPackageExport from './ModelPackageExport.vue'
import ModelListPagination from './ModelListPagination.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import { ApiError } from '@/shared/api/error'
import { formatModelNumber } from '../model-number-format'
import { latestModelVersion, modelDisplayName as displayName, modelVersionCustomName, modelVersionDisplayName } from '../model-display-name'
import { modelTaskLabel } from '../model-evaluation-types'
import { modelVersionMetric, type TrainingMetricOutputs } from '../model-version-metrics'
import { resolveTrainingBestCheckpointEpoch } from '../training-metric-history'
import { modelBuildValidation, saveProjectModelDownload } from '../model-artifact-presentation'
import { conversionSourceIssue } from '../conversion-source-support'
import { isModelVersionTaskType, type ModelVersionAction } from '../model-version-action'
import { downloadProjectModelFile, getProjectModelFileStatus, getModelTrainingOutputFileDetail, getModelTrainingTaskDetail, getProjectModelCatalogDetail, getProjectModelVersionSource, listModelVersionReferences, listProjectModelCatalog, type ModelDeploymentReference, type ModelTaskType, type ModelTrainingTaskDetail, type PlatformBaseModelBuild, type PlatformBaseModelDetail, type PlatformBaseModelSummary, type ProjectModelCatalogItem, type ProjectModelVersionSource } from '../services/model.service'

const props = withDefaults(defineProps<{ projectId: string; principalKey?: string; active?: boolean; canEdit?: boolean; canTrain?: boolean; canConvert?: boolean; canDeploy?: boolean; launchingConversion?: boolean; launchError?: string; openModelId?: string; openVersionId?: string; requestedTaskType?: string }>(), { active: true, canEdit: false })
const emit = defineEmits<{ 'open-base-models': []; 'create-training': []; 'import-model-package': []; 'empty-state': [empty: boolean]; 'create-conversion': [source: ModelVersionAction]; 'create-deployment': [source: ModelVersionAction]; 'version-change': [versionId: string]; 'version-deleted': [versionId: string]; 'change-task-type': [task: string] }>()
const { locale } = useI18n()
const zh = computed(() => locale.value.startsWith('zh'))
const taskTypes = ['detection', 'classification', 'segmentation', 'pose', 'obb']
const taskOptions = computed(() => [{ label: zh.value ? '全部' : 'All', value: '' }, ...taskTypes.map(value => ({ label: modelTaskLabel(value, zh.value), value }))])
const search = ref('')
const requestedTaskType = computed(() => taskTypes.find(type => type === props.requestedTaskType) ?? '')
const taskType = ref(requestedTaskType.value)
function updateTaskType(value: unknown): void {
  taskType.value = typeof value === 'string' && taskTypes.includes(value) ? value : ''
  emit('change-task-type', taskType.value)
}
watch([requestedTaskType, () => props.active], ([value, active]) => {
  if (active) taskType.value = value
})
const page = ref(1)
const pageSize = ref(20)
interface CatalogCriteria { project: string; principal: string; query: string; taskType: string; page: number; pageSize: number }
interface CatalogSnapshot { key: string; items: ProjectModelCatalogItem[]; total: number; updatedAt: string }
type CatalogState = 'loading' | 'disconnected' | 'error' | 'denied'
const criteria = computed<CatalogCriteria>(() => ({ project: props.projectId, principal: props.principalKey ?? '', query: search.value, taskType: taskType.value, page: page.value, pageSize: pageSize.value }))
const criteriaKey = computed(() => JSON.stringify(criteria.value))
const snapshot = shallowRef<CatalogSnapshot | null>(null)
const matchingSnapshot = computed(() => snapshot.value?.key === criteriaKey.value ? snapshot.value : null)
const currentRequest = shallowRef<{ key: string; state: CatalogState } | null>(null)
const state = computed(() => currentRequest.value?.key === criteriaKey.value ? currentRequest.value.state : undefined)
const items = computed(() => matchingSnapshot.value?.items ?? [])
const total = computed(() => matchingSnapshot.value?.total ?? 0)
const loading = computed(() => state.value === 'loading')
const error = computed(() => !!state.value && state.value !== 'loading')
const accessDenied = computed(() => state.value === 'denied')
const connectionLost = computed(() => state.value === 'disconnected')
const filtered = computed(() => !!(search.value || taskType.value))
const selected = ref<PlatformBaseModelSummary | null>(null)
const editing = ref<PlatformBaseModelSummary | null>(null)
const presentationEditor = ref<InstanceType<typeof ModelPresentationEditor> | null>(null)
const deletionOpen = ref(false)
const buildToDelete = ref<PlatformBaseModelBuild | null>(null)
const buildDeletionUncertain = ref(false)
const detail = ref<PlatformBaseModelDetail | null>(null)
const selectedVersionId = ref('')
const detailLoading = ref(false)
const detailError = ref(false)
const deepLinkError = ref(false)
const exportView = ref(false)
const trainingTask = ref<ModelTrainingTaskDetail | null>(null)
const versionSource = ref<ProjectModelVersionSource | null>(null)
const sourceError = ref(false)
const sourceLoading = ref(false)
const sourceRetry = ref(0)
const referenceView = ref(false)
const referenceHeading = ref<HTMLHeadingElement>()
const referencesButton = ref<HTMLButtonElement>()
const referenceBuild = ref<PlatformBaseModelBuild | null>(null)
const selectedBuild = ref<PlatformBaseModelBuild | null>(null)
const originalFilesView = ref(false)
const artifactView = computed(() => !referenceView.value && !!(selectedBuild.value || originalFilesView.value))
const artifactDetail = ref<InstanceType<typeof ModelBuildDetail> | null>(null)
const referenceQuery = ref('')
const referencePage = ref(1)
const references = ref<ModelDeploymentReference[]>([])
const referenceTotal = ref(0)
const referenceOverallTotal = ref(0)
const referenceLoading = ref(false)
const referenceError = ref(false)
const referencePageCount = computed(() => Math.max(1, Math.ceil(referenceTotal.value / 6)))
const initialEmpty = computed(() => !error.value && !!matchingSnapshot.value && total.value === 0 && !filtered.value)
watch(initialEmpty, empty => emit('empty-state', empty), { immediate: true })
const activeVersion = computed(() => detail.value?.versions.find(version => version.model_version_id === selectedVersionId.value) ?? null)
const versionOptions = computed(() => detail.value?.versions.map(version => {
  const kind = version.metadata.registration_kind
  const description = kind === 'best-checkpoint' ? (zh.value ? '最佳检查点' : 'Best checkpoint')
    : kind === 'latest-checkpoint' ? (zh.value ? '手动登记的检查点' : 'Manually registered checkpoint')
      : sourceName(version.source_kind)
  return { label: modelVersionDisplayName(version), value: version.model_version_id, description: modelVersionCustomName(version) || description }
}) ?? [])
const metricsReport = shallowRef<unknown>()
const trainingMetricOutputs = shallowRef<TrainingMetricOutputs>()
const versionMetric = computed(() => activeVersion.value
  ? modelVersionMetric(activeVersion.value, trainingTask.value, metricsReport.value, trainingMetricOutputs.value) : null)
const checkpoint = computed(() => activeVersion.value?.files.find(file => file.file_id === activeVersion.value?.checkpoint_file_id))
const checkpointState = ref<'checking' | 'present' | 'missing' | 'unavailable'>('checking')
const checkpointDownloading = ref(false)
const checkpointDownloadError = ref(false)
let checkpointRequest: AbortController | undefined
const checkpointStatusLabel = computed(() => ({
  checking: zh.value ? '检查中' : 'Checking',
  present: zh.value ? '可用' : 'Available',
  missing: zh.value ? '文件缺失' : 'Missing',
  unavailable: zh.value ? '无法检查' : 'Unavailable',
})[checkpointState.value])
const originalPrecision = computed(() => {
  const value = activeVersion.value?.metadata.model_input_spec as { dtype?: string } | undefined
  const type = value?.dtype?.toLowerCase()
  if (type === 'float32' || type === 'fp32') return 'FP32'
  if (type === 'float16' || type === 'fp16') return 'FP16'
  return '—'
})
function buildStatusLabel(build: PlatformBaseModelBuild): string {
  const check = modelBuildValidation(build)
  if (check === true) return zh.value ? '已校验' : 'Validated'
  if (check === false) return zh.value ? '校验未通过' : 'Validation failed'
  return zh.value ? '已登记' : 'Registered'
}
async function downloadCheckpoint(): Promise<void> {
  const file = checkpoint.value, version = activeVersion.value, model = detail.value
  if (!file || !version || !model || checkpointDownloading.value || checkpointState.value !== 'present') return
  const request = new AbortController()
  checkpointRequest = request
  checkpointDownloading.value = true
  checkpointDownloadError.value = false
  try {
    const blob = await downloadProjectModelFile({ projectId: props.projectId, modelId: model.model_id,
      versionId: version.model_version_id, fileId: file.file_id, signal: request.signal })
    if (!request.signal.aborted) saveProjectModelDownload(blob, file.storage_uri.split(/[\\/]/).pop() || file.logical_name)
  } catch (error) {
    if (!request.signal.aborted) {
      checkpointDownloadError.value = true
      if (error instanceof ApiError && error.status === 404) checkpointState.value = 'missing'
    }
  } finally {
    if (!request.signal.aborted) checkpointDownloading.value = false
  }
}
const versionBuilds = computed(() => detail.value?.builds.filter(build => build.source_model_version_id === selectedVersionId.value) ?? [])
const selectedVersionFormats = computed(() => {
  const names = new Set(versionBuilds.value.map(formatBuild))
  if (activeVersion.value?.checkpoint_file_id || activeVersion.value?.files.some(file => /\.(pt|pth)$/i.test(file.storage_uri))) {
    return ['PyTorch', ...names]
  }
  return [...names]
})
const versionActionsVisible = computed(() => !!selected.value && !!activeVersion.value && !detailLoading.value && !detailError.value && !referenceView.value && !selectedBuild.value && !originalFilesView.value && !exportView.value)
const modelDescription = computed(() => typeof detail.value?.metadata.description === 'string' ? detail.value.metadata.description.trim() : '')
const descriptionElement = ref<HTMLElement>()
const descriptionExpanded = ref(false)
const descriptionOverflow = ref(false)
const versionAction = computed<ModelVersionAction | null>(() => {
  const model = detail.value
  const version = activeVersion.value
  if (!model || !version || !isModelVersionTaskType(model.task_type)) return null
  return { projectId: props.projectId, modelId: model.model_id, versionId: version.model_version_id, taskType: model.task_type }
})
const conversionUnavailable = computed(() => {
  if (!props.canConvert) return zh.value ? '当前账号无权创建转换任务' : 'This account cannot create conversion tasks'
  if (error.value || !versionAction.value) return zh.value ? '请刷新并确认版本后再创建转换' : 'Refresh and verify the version before creating a conversion'
  return activeVersion.value && conversionSourceIssue(activeVersion.value) ? (zh.value ? '当前版本缺少可转换的原始权重或类别信息' : 'This version has no usable original weights or class information') : ''
})
const deploymentUnavailable = computed(() => {
  if (!props.canDeploy) return zh.value ? '当前账号无权创建部署' : 'This account cannot create deployments'
  if (error.value || !versionAction.value) return zh.value ? '请刷新并确认版本后再创建部署' : 'Refresh and verify the version before creating a deployment'
  return versionBuilds.value.length ? '' : (zh.value ? '此版本没有转换产物，请先创建转换' : 'Convert this version before creating a deployment')
})
const canConvertVersion = computed(() => !conversionUnavailable.value)
const canDeployVersion = computed(() => !deploymentUnavailable.value && !props.launchingConversion)
function requestVersionAction(action: 'create-conversion' | 'create-deployment'): void {
  const source = versionAction.value
  if (!source || props.launchingConversion) return
  if (action === 'create-conversion' && canConvertVersion.value) emit('create-conversion', source)
  if (action === 'create-deployment' && canDeployVersion.value) emit('create-deployment', source)
}
function deployArtifact(): void {
  const source = versionAction.value
  const build = selectedBuild.value
  if (!source || !build || !canDeployVersion.value || !artifactDetail.value?.filesPresent) return
  emit('create-deployment', { ...source, buildId: build.model_build_id })
}
function backFromArtifact(): void {
  const buildId = selectedBuild.value?.model_build_id ?? ''
  selectedBuild.value = null
  originalFilesView.value = false
  void nextTick(() => [...document.querySelectorAll<HTMLButtonElement>('.model-version-drawer [data-artifact]')]
    .find(button => button.dataset.artifact === buildId)?.focus())
}
watch(artifactDetail, component => {
  const content = component?.$el.closest?.('.side-drawer__content')
  content?.scrollTo({ top: 0 })
}, { flush: 'post' })
watch(selected, () => { descriptionExpanded.value = false })
watch([selected, selectedVersionId, versionActionsVisible], ([model, version, visible]) => emit('version-change', model && visible ? version : ''), { flush: 'sync' })
watch([descriptionElement, descriptionExpanded, modelDescription], ([element, expanded], _, onCleanup) => {
  if (!element || expanded) return
  const updateOverflow = () => { descriptionOverflow.value = element.scrollHeight > element.clientHeight + 1 }
  updateOverflow()
  if (typeof ResizeObserver !== 'undefined') {
    const observer = new ResizeObserver(updateOverflow)
    observer.observe(element)
    onCleanup(() => observer.disconnect())
  }
}, { flush: 'post' })
const categoryNames = computed(() => {
  const value = activeVersion.value?.metadata.category_names
  return Array.isArray(value) ? value.filter((name): name is string => typeof name === 'string') : []
})
const categoryCount = computed(() => Array.isArray(activeVersion.value?.metadata.category_names) ? categoryNames.value.length : null)
const inputSize = computed(() => {
  const value = activeVersion.value?.metadata.input_size
  if (!value || typeof value !== 'object') return ''
  const { width, height } = value as Record<string, unknown>
  return typeof width === 'number' && typeof height === 'number' ? `${width} × ${height}` : ''
})
let requestSerial = 0
let catalogRequest: AbortController | undefined
let scheduledLoad: ReturnType<typeof setTimeout> | undefined
let detailSerial = 0
let referenceSerial = 0
let referenceRequest: AbortController | undefined
async function load(): Promise<void> {
  const serial = ++requestSerial
  clearTimeout(scheduledLoad)
  catalogRequest?.abort()
  const { project, query, taskType, page: requestedPage, pageSize } = criteria.value
  const key = criteriaKey.value
  if (!project) { currentRequest.value = null; return }
  const request = new AbortController()
  catalogRequest = request
  currentRequest.value = { key, state: 'loading' }
  const isCurrent = () => serial === requestSerial && key === criteriaKey.value && !request.signal.aborted
  try {
    const result = await listProjectModelCatalog({ projectId: project, query, taskType, offset: (requestedPage - 1) * pageSize, limit: pageSize, signal: request.signal })
    if (!isCurrent()) return
    currentRequest.value = null
    const lastPage = Math.max(1, Math.ceil(result.total / pageSize))
    if (requestedPage > lastPage) { page.value = lastPage; return }
    snapshot.value = { key, items: result.items, total: result.total, updatedAt: new Date().toISOString() }
  } catch (cause) {
    if (!isCurrent()) return
    const status = cause instanceof ApiError ? cause.status : undefined
    if (status === 401 || status === 403 || status === 404) {
      snapshot.value = null
      closeCatalogDetail()
      currentRequest.value = { key, state: status === 404 ? 'error' : 'denied' }
    } else {
      currentRequest.value = { key, state: status === 0 || status === 502 || status === 503 || status === 504 || !navigator.onLine ? 'disconnected' : 'error' }
    }
  }
}
function clearFilters(): void { search.value = ''; taskType.value = ''; page.value = 1 }
const copiedDetailId = ref(false)
let copyTimer: ReturnType<typeof setTimeout> | undefined
async function copyModelDetailId(id: string): Promise<void> {
  if (!id) return
  try {
    await navigator.clipboard.writeText(id)
    copiedDetailId.value = true
    clearTimeout(copyTimer)
    copyTimer = setTimeout(() => { copiedDetailId.value = false }, 1600)
  } catch { /* ignore clipboard denial */ }
}
function closeCatalogDetail(): void { selected.value = null; editing.value = null; detail.value = null; detailSerial++; copiedDetailId.value = false }
async function allowNavigation(): Promise<boolean> {
  const allowed = await (presentationEditor.value?.allowNavigation?.() ?? true)
  if (allowed) editing.value = null
  return allowed
}
defineExpose({ allowNavigation })
function reconnect(): void { if (props.active && connectionLost.value && !loading.value) void load() }
onMounted(() => window.addEventListener('online', reconnect))
onBeforeUnmount(() => { clearTimeout(scheduledLoad); catalogRequest?.abort(); referenceRequest?.abort(); window.removeEventListener('online', reconnect) })
function sourceName(source: string): string {
  const names: Record<string, string> = { 'training-output': zh.value ? '项目训练' : 'Training', 'deployment-import': zh.value ? '部署导入' : 'Deployment import', 'pretrained-reference': zh.value ? '预训练' : 'Pretrained', 'model-package-import': zh.value ? '模型包导入' : 'Model package import' }
  return names[source] ?? source
}
function latestVersionLabel(model: PlatformBaseModelSummary, compact: boolean): string {
  const version = latestModelVersion(model.available_versions)
  return version ? modelVersionDisplayName(version, compact) : model.version_count ? (zh.value ? '未记录' : 'Not recorded') : '—'
}
function isKnownTask(value: string): value is ModelTaskType { return taskTypes.includes(value) }
function runtimeStates(states: Record<string, string>) {
  const labels: Record<string, string> = zh.value
    ? { running: '运行中', stopped: '已停止', starting: '启动中', degraded: '异常', failed: '失败' }
    : { running: 'Running', stopped: 'Stopped', starting: 'Starting', degraded: 'Degraded', failed: 'Failed' }
  const modes = ['sync', 'async'].filter(mode => states[mode])
  return modes.length
    ? modes.map(mode => ({ key: mode, status: states[mode], label: `${mode === 'sync' ? (zh.value ? '同步' : 'Sync') : (zh.value ? '异步' : 'Async')}: ${labels[states[mode]] ?? states[mode]}` }))
    : [{ key: 'instance', status: states.instance, label: labels[states.instance] ?? (zh.value ? '未知' : 'Unknown') }]
}
function backFromReferences(): void {
  referenceView.value = false
  referenceBuild.value = null
  void nextTick(() => referencesButton.value?.focus())
}
async function loadReferences(): Promise<void> {
  referenceRequest?.abort()
  const serial = ++referenceSerial
  const modelId = detail.value?.model_id
  const versionId = selectedVersionId.value
  if (!selected.value || !modelId || !versionId || !props.projectId) { references.value = []; referenceTotal.value = 0; referenceLoading.value = false; return }
  referenceRequest = new AbortController()
  referenceLoading.value = true; referenceError.value = false
  try {
    const result = await listModelVersionReferences({ projectId: props.projectId, modelId, versionId, buildId: referenceBuild.value?.model_build_id, query: referenceQuery.value, offset: (referencePage.value - 1) * 6, limit: 6, signal: referenceRequest.signal })
    if (serial !== referenceSerial) return
    references.value = result.items; referenceTotal.value = result.total
    if (!referenceQuery.value && !referenceBuild.value) referenceOverallTotal.value = result.total
    if (referencePage.value > referencePageCount.value) referencePage.value = referencePageCount.value
  } catch { if (serial === referenceSerial) referenceError.value = true }
  finally { if (serial === referenceSerial) referenceLoading.value = false }
}
function sources(model: PlatformBaseModelSummary): string {
  const names = [...new Set(model.available_versions.map(version => sourceName(version.source_kind)))]
  return names.length ? names.join(' / ') : '—'
}
function formats(model: ProjectModelCatalogItem): string[] {
  const formats = new Set<string>()
  if (model.available_versions.some(version => /\.(pt|pth)$/i.test(version.checkpoint_storage_uri ?? ''))) formats.add('pytorch')
  for (const format of model.build_formats ?? []) formats.add(format)
  return [...formats]
}
async function openDetail(model: PlatformBaseModelSummary): Promise<void> {
  selected.value = model; detail.value = null; selectedVersionId.value = ''; detailError.value = false
  const serial = ++detailSerial
  if (!model.version_count && !model.build_count) { detailLoading.value = false; detail.value = { ...model, versions: [], builds: [] }; return }
  detailLoading.value = true
  try {
    const result = await getProjectModelCatalogDetail(props.projectId, model.model_id)
    if (serial === detailSerial) {
      detail.value = result
      selectedVersionId.value = (latestModelVersion(result.versions) ?? result.versions[0])?.model_version_id ?? ''
    }
  }
  catch { if (serial === detailSerial) detailError.value = true }
  finally { if (serial === detailSerial) detailLoading.value = false }
}
function formatBuild(build: PlatformBaseModelBuild): string {
  return formatBuildName(build.build_format)
}
function formatBuildName(format: string): string {
  return ({ onnx: 'ONNX', 'onnx-optimized': 'ONNX optimized', 'openvino-ir': 'OpenVINO', 'tensorrt-engine': 'TensorRT' } as Record<string, string>)[format] ?? format
}
async function refreshOpenVersion(): Promise<void> {
  const modelId = detail.value?.model_id
  if (!modelId) return
  const serial = ++detailSerial
  detailLoading.value = true; detailError.value = false
  try {
    const result = await getProjectModelCatalogDetail(props.projectId, modelId)
    if (serial === detailSerial) detail.value = result
  } catch { if (serial === detailSerial) detailError.value = true }
  finally { if (serial === detailSerial) detailLoading.value = false }
}
function closeBuildDeletion(): void {
  buildToDelete.value = null
  if (buildDeletionUncertain.value) { buildDeletionUncertain.value = false; void refreshOpenVersion(); void load() }
}
function onArtifactDeleted(): void {
  const deletedId = buildToDelete.value?.model_build_id
  if (detail.value) detail.value = { ...detail.value, builds: detail.value.builds.filter(build => build.model_build_id !== deletedId) }
  buildToDelete.value = null
  void load()
}
function openVersionDeletionReferences(): void {
  deletionOpen.value = false
  referenceBuild.value = null
  referenceQuery.value = ''
  referencePage.value = 1
  referenceView.value = true
  void loadReferences()
}
function onVersionDeleted(): void {
  const deletedId = selectedVersionId.value
  deletionOpen.value = false
  selected.value = null
  emit('version-deleted', deletedId)
  void load()
}
function refreshAfterUnknownDeletion(): void {
  void refreshOpenVersion()
  void load()
}
watch([() => props.projectId, () => props.principalKey, search, taskType], () => { page.value = 1 }, { flush: 'sync' })
watch([() => props.projectId, () => props.principalKey], () => { closeCatalogDetail(); snapshot.value = null }, { flush: 'sync' })
watch(criteria, (current, previous) => {
  clearTimeout(scheduledLoad)
  catalogRequest?.abort()
  ++requestSerial
  if (previous && current.project === previous.project && current.principal === previous.principal
    && (current.query !== previous.query || current.taskType !== previous.taskType)) {
    currentRequest.value = { key: criteriaKey.value, state: 'loading' }
    scheduledLoad = setTimeout(load, 250)
  } else void load()
}, { immediate: true })
watch(() => props.active, (active, previous) => { if (active && !previous) void load(); else if (!active) closeCatalogDetail() })
watch(selected, (value) => { if (!value) { detailSerial++; referenceSerial++; referenceRequest?.abort(); referenceView.value = false; referenceBuild.value = null; buildToDelete.value = null; buildDeletionUncertain.value = false; selectedBuild.value = null; originalFilesView.value = false; exportView.value = false; deletionOpen.value = false } })
watch(selectedVersionId, () => { referenceSerial++; deletionOpen.value = false; referenceView.value = false; selectedBuild.value = null; originalFilesView.value = false; exportView.value = false; referenceQuery.value = ''; referencePage.value = 1; references.value = []; referenceTotal.value = 0; referenceOverallTotal.value = 0; void loadReferences() })
watch(referenceBuild, () => { referenceSerial++; references.value = []; referenceQuery.value = ''; referencePage.value = 1; void loadReferences() })
watch(referenceView, open => {
  const heading = referenceHeading.value
  if (!open || !heading) return
  heading.closest('.side-drawer__content')?.scrollTo({ top: 0 })
  heading.focus({ preventScroll: true })
}, { flush: 'post' })
watch([referenceQuery, referencePage], ([query], [previousQuery], onCleanup) => {
  referenceSerial++
  referenceRequest?.abort()
  referenceLoading.value = true
  referenceError.value = false
  references.value = []
  if (query === previousQuery) { void loadReferences(); return }
  referenceTotal.value = 0
  if (referencePage.value !== 1) { referencePage.value = 1; return }
  const timer = setTimeout(loadReferences, 250)
  onCleanup(() => clearTimeout(timer))
})
watch([activeVersion, () => detail.value?.task_type, () => props.projectId], async ([version, type, projectId], _, onCleanup) => {
  trainingTask.value = null
  trainingMetricOutputs.value = undefined
  if (!version?.training_task_id || !type || !isKnownTask(type)) return
  const request = new AbortController()
  onCleanup(() => request.abort())
  try {
    const result = await getModelTrainingTaskDetail(type, version.training_task_id, request.signal)
    if (request.signal.aborted || result.project_id !== projectId) return
    trainingTask.value = result
    if (result.state !== 'succeeded' || result.model_version_id !== version.model_version_id
      || resolveTrainingBestCheckpointEpoch(result, []) !== undefined) return

    const bestFile = result.checkpoint_object_key
      ? await getModelTrainingOutputFileDetail(type, result.task_id, 'best-checkpoint', request.signal).catch(() => null)
      : null
    if (request.signal.aborted) return
    if (bestFile?.epoch != null) {
      trainingMetricOutputs.value = { checkpointEpoch: bestFile.epoch }
    } else if (result.validation_metrics_object_key) {
      const report = await getModelTrainingOutputFileDetail(type, result.task_id, 'validation-metrics', request.signal)
      if (!request.signal.aborted && report.file_status === 'ready') {
        trainingMetricOutputs.value = { validationMetrics: report.payload }
      }
    }
  } catch { /* 任务已清理或当前账号无权读取时，版本详情仍可查看。 */ }
})
watch([activeVersion, selected, () => props.projectId] as const, ([version, model, projectId], _, onCleanup) => {
  metricsReport.value = undefined
  checkpointState.value = 'checking'
  checkpointDownloading.value = false
  checkpointDownloadError.value = false
  checkpointRequest?.abort()
  if (!version || !model || !projectId) return
  const request = new AbortController()
  onCleanup(() => { request.abort(); checkpointRequest?.abort() })
  const input = { projectId, modelId: model.model_id, versionId: version.model_version_id, signal: request.signal }
  const file = checkpoint.value
  if (file) void getProjectModelFileStatus({ ...input, fileId: file.file_id }).then(result => {
    if (!request.signal.aborted) checkpointState.value = result.state
  }).catch(() => { if (!request.signal.aborted) checkpointState.value = 'unavailable' })
  if (modelVersionMetric(version, null)?.epoch !== undefined) return
  const report = version.files.find(item => item.file_type.endsWith('training-metrics'))
  if (report) void downloadProjectModelFile({ ...input, fileId: report.file_id }).then(async blob => {
    const data: unknown = JSON.parse(await blob.text())
    if (!request.signal.aborted) metricsReport.value = data
  }).catch(() => { /* 旧记录的指标文件可能已经清理。 */ })
})
watch([activeVersion, selected, () => props.projectId, sourceRetry], async ([version, model, projectId], _, onCleanup) => {
  versionSource.value = null
  sourceError.value = false
  sourceLoading.value = false
  if (!projectId || !model || !version || !version.dataset_version_id) return
  sourceLoading.value = true
  const request = new AbortController()
  onCleanup(() => request.abort())
  try {
    const result = await getProjectModelVersionSource(projectId, model.model_id, version.model_version_id, request.signal)
    if (!request.signal.aborted) versionSource.value = result
  } catch {
    if (!request.signal.aborted) sourceError.value = true
  } finally {
    if (!request.signal.aborted) sourceLoading.value = false
  }
})
watch(() => [props.projectId, props.active, props.openModelId, props.openVersionId] as const, async ([projectId, active, modelId, versionId], _, onCleanup) => {
  deepLinkError.value = false
  if (!active || !projectId || !modelId || !versionId) return
  let cancelled = false
  onCleanup(() => { cancelled = true })
  const serial = ++detailSerial
  try {
    const data = await getProjectModelCatalogDetail(projectId, modelId)
    if (cancelled || serial !== detailSerial) return
    if (!data.versions.some(version => version.model_version_id === versionId)) throw new Error('version missing')
    detailLoading.value = false
    detailError.value = false
    selected.value = data
    detail.value = data
    selectedVersionId.value = versionId
  } catch { if (!cancelled && serial === detailSerial) deepLinkError.value = true }
}, { immediate: true })
</script>

<style scoped>
.model-catalog__toolbar { margin:0 0 16px; }
.model-catalog__project-switch { min-width:0; max-width:min(42vw, 210px); }
.model-catalog__project-switch :deep(.ui-select__button) { border-color:transparent; background:transparent; font-size:16px; font-weight:650; }
.model-catalog__hint { display:flex; align-items:center; gap:8px; color:var(--am-text-muted); }
.model-catalog__hint svg { flex:none; }
.model-catalog__initial-empty { display:flex; flex-direction:column; align-items:center; justify-content:center; min-height:clamp(350px, 63dvh, 610px); padding:24px 16px; text-align:center; color:var(--am-text-muted); }
.model-catalog__empty-art { width:clamp(150px, 23dvh, 225px); height:auto; }
.model-catalog__initial-empty h2 { margin:24px 0 8px; font-size:clamp(21px, 2.1vw, 28px); color:var(--am-text-strong); }
.model-catalog__initial-empty p { margin:0; }
.model-catalog__empty-actions { display:flex; justify-content:center; flex-wrap:wrap; gap:12px; margin-top:24px; }
.model-catalog__empty-actions :deep(.ui-button) { min-width:146px; }
.model-catalog__filter { display:flex; align-items:center; gap:10px; white-space:nowrap; }
.model-catalog__filter :deep(.ui-select) { width:140px; }
.model-catalog__table { border:1px solid var(--am-border); border-radius:8px; background:var(--am-surface-raised); overflow:auto; }
.model-catalog__table table { width:100%; table-layout:fixed; }
.model-catalog__table tr.is-selected { background:var(--am-action-soft); }
.model-catalog__name-column { width:29%; }.model-catalog__task-column { width:12%; }.model-catalog__version-column { width:15%; }.model-catalog__source-column { width:13%; }.model-catalog__format-column { width:19%; }.model-catalog__action-column { width:12%; }
.model-catalog__table th, .model-catalog__table td { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.model-catalog__actions { display:flex; align-items:center; gap:10px; }
.model-catalog__empty, .model-catalog__message { padding:40px 16px; text-align:center; color:var(--am-text-muted); }
.model-catalog__notice { display:flex; align-items:center; flex-wrap:wrap; gap:10px 14px; border:1px solid var(--am-border); border-radius:7px; padding:12px 14px; margin:0 0 14px; }
.model-catalog__notice > svg { flex:none; }
.model-catalog__notice > div { flex:1 1 215px; min-width:0; }
.model-catalog__notice p { margin:3px 0 0; color:var(--am-text); }
.model-catalog__notice--warning { color:var(--am-warning-text); background:var(--am-warning-surface); border-color:var(--am-warning-border); }
.model-catalog__notice--error { color:var(--am-danger-text); background:var(--am-danger-surface); }
.model-catalog__refresh-state { text-align:end; color:var(--am-text-muted); margin:0; padding:6px 16px; border-bottom:1px solid var(--am-border); }
.model-catalog__no-results { display:grid; place-items:center; gap:8px; white-space:normal; overflow-wrap:anywhere; }
.model-catalog__no-results p { margin:0; }
.model-catalog__no-results strong { color:var(--am-text-strong); }
.model-detail__actions .ui-button:disabled { background:var(--am-surface-muted); border-color:var(--am-border); color:var(--am-text-muted); }
@media (max-width:1120px) {
  .model-catalog__filter :deep(.ui-select) { width:112px; }
}
.model-detail__heading-row { display:flex; align-items:center; justify-content:space-between; gap:10px; margin:0 0 18px; }
.model-detail__name { margin:0; font-size:20px; min-width:0; overflow-wrap:anywhere; }
.model-detail__copy-btn { flex:none; color:var(--am-text-muted); }
.model-detail__copy-btn .is-copied { color:var(--am-action-primary); }
.model-detail__version { display:flex; align-items:center; gap:12px; color:var(--am-text-muted); }
.model-detail__version :deep(.ui-select) { min-width:136px; max-width:100%; }
.model-detail__meta { display:flex; flex-wrap:wrap; gap:8px 16px; margin:0; padding:16px 0; border-bottom:1px solid var(--am-border); }
.model-detail__meta > div { display:flex; align-items:center; gap:10px; }
.model-detail__meta > div:not(:last-child) { padding-inline-end:16px; border-inline-end:1px solid var(--am-border); }
.model-detail__meta dt,.model-detail__metric dt { color:var(--am-text-muted); }
.model-detail__meta dd,.model-detail__metric dd { margin:0; }
.model-detail__section { margin:18px 0; }
.model-detail__section h3 { margin:0 0 10px; font-size:15px; }
.model-detail__section p { overflow-wrap:anywhere; }
.model-source { display:flex; flex-wrap:wrap; gap:12px 24px; margin:0; padding:0; list-style:none; }
.model-source__step {
  flex:1 1 125px;
  display:flex;
  align-items:center;
  gap:8px;
  position:relative;
  min-width:0;
  padding:9px 10px;
  border:1px solid var(--am-border);
  border-radius:6px;
}
.model-source__step > svg { flex:none; color:var(--am-text-muted); }
.model-source__step > .model-source__success { color:var(--am-brand-primary); }
.model-source__step:not(:last-child)::after {
  content:'→';
  position:absolute;
  inset-inline-end:-20px;
  color:var(--am-text-muted);
}
.model-source__step > div { min-width:0; overflow-wrap:anywhere; }
.model-source__step a { font-weight:600; color:var(--am-brand-primary); }
.model-source__dataset { display:-webkit-box; overflow:hidden; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
.model-source__step span { display:block; font-size:12px; color:var(--am-text-muted); }
.model-source__error { color:var(--am-text-muted); }
:global(.model-version-drawer.side-drawer) { width:min(540px, calc(100vw - 36px)); }
:global(.model-artifact-drawer.side-drawer) { width:min(680px, calc(100vw - 36px)); }
.model-artifact__actions { display:flex; justify-content:flex-end; flex-wrap:wrap; gap:10px; width:100%; }
.model-artifact__actions .ui-button { flex:1 1 auto; }
.model-detail__footer { display:grid; gap:8px; width:100%; min-width:0; }
.model-detail__actions, .model-detail__launch { display:flex; flex-wrap:wrap; align-items:center; gap:8px; }
.model-detail__launch { margin-inline-start:auto; }
.model-detail__description p { margin:0; line-height:1.5; white-space:pre-wrap; overflow-wrap:anywhere; }
.model-detail__description p.is-collapsed { display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2; overflow:hidden; }
.model-detail__description .ui-button { color:var(--am-brand-primary); }
.model-detail__action-error { margin:0; color:var(--am-danger-text); overflow-wrap:anywhere; }
.model-detail__table { border:1px solid var(--am-border); border-radius:5px; overflow:hidden; }
.model-detail__table table { table-layout:fixed; width:100%; }
.model-detail__table :is(th, td) { padding:7px 10px; border-block-end:1px solid var(--am-border); overflow-wrap:anywhere; }
.model-detail__table th { background:var(--am-table-header); color:var(--am-text-muted); }
.model-detail__table tr:last-child td { border-block-end:0; }
.model-detail__table :is(th, td) + :is(th, td) { border-inline-start:1px solid var(--am-border); }
.model-detail__table th:first-child { width:38%; }
.model-detail__table th:nth-child(2) { width:14%; }
.model-detail__table th:last-child { width:26%; }
.model-detail__table .ui-button { min-height:28px; padding-inline:4px; gap:4px; }
.model-artifact__success { color:var(--am-success-text); }
.model-detail__disclosures { display:grid; gap:10px; min-width:0; }
.model-detail__disclosure { min-width:0; border:1px solid var(--am-border); border-radius:5px; overflow-wrap:anywhere; }
.model-detail__disclosure summary { display:flex; align-items:center; justify-content:space-between; gap:8px; padding:12px; cursor:pointer; list-style:none; }
.model-detail__disclosure summary::-webkit-details-marker { display:none; }
.model-detail__chevron { flex:none; color:var(--am-text-muted); transition:transform 140ms ease; }
.model-detail__disclosure[open] .model-detail__chevron { transform:rotate(90deg); }
.model-detail__disclosure p { margin:0; padding:0 12px 12px; }
.model-detail__metric { display:flex; align-items:center; gap:20px; margin:0; padding:14px; border:1px solid var(--am-border); border-radius:5px; }
.model-detail__metric > div { display:grid; flex:1; gap:6px; min-width:0; overflow-wrap:anywhere; }
.model-detail__metric > div + div { border-inline-start:1px solid var(--am-border); padding-inline-start:20px; }
.model-detail__metric strong { font-size:20px; }
:is(.model-detail__references, .model-detail__files) { display:flex; align-items:center; width:100%; gap:4px; padding:12px; border:1px solid var(--am-border); border-radius:5px; background:var(--am-surface-raised); color:var(--am-text); text-align:left; cursor:pointer; }
:is(.model-detail__references, .model-detail__files) svg { margin-left:auto; }
.model-detail__files:disabled { color:var(--am-text-disabled); cursor:default; }
.model-reference__title { margin:10px 0 8px; overflow-wrap:anywhere; }
.model-reference__title:focus { outline:none; }
.model-reference__version,.model-reference__hint { margin:8px 0; color:var(--am-text-muted); }
.model-reference__search { display:flex; align-items:center; gap:8px; margin:16px 0; padding:0 12px; border:1px solid var(--am-border); border-radius:5px; }
.model-reference__search input { width:100%; min-width:0; height:40px; border:0; outline:0; background:transparent; color:var(--am-text); }
.model-reference__count,.model-reference__state { color:var(--am-text-muted); }
.model-reference__table { border:1px solid var(--am-border); border-radius:5px; overflow:auto; }
.model-reference__table table { table-layout:fixed; width:100%; }
.model-reference__table :is(th,td) { padding:7px 8px; }
.model-reference__table td { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.model-reference__table td.model-reference__runtime { white-space:normal; overflow-wrap:anywhere; line-height:1.4; }
.model-reference__cell { display:flex; align-items:center; gap:5px; }
.model-reference__cell svg { flex:none; }
.model-reference__runtime .is-running { color:var(--am-success-text); }
.model-reference__runtime .is-failed { color:var(--am-danger-text); }
.model-reference__close { margin-inline-start:auto; min-width:100px; }
.model-detail__artifact-actions { display:flex; align-items:center; flex-wrap:wrap; gap:3px; }
.model-reference__pagination,.model-reference__pagination div { display:flex; align-items:center; gap:12px; }
.model-reference__pagination { justify-content:space-between; padding:14px 0; }
</style>

<style>
.model-detail-id-tooltip {
  z-index: var(--am-z-tooltip);
  display: grid;
  gap: 6px;
  min-width: 240px;
  max-width: min(440px, calc(100vw - 80px));
  padding: 8px 10px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface-raised, var(--am-surface));
  box-shadow: var(--am-shadow-floating);
  pointer-events: none;
}
.model-detail-id-tooltip > div {
  display: grid;
  gap: 2px;
}
.model-detail-id-tooltip span {
  font-size: 11px;
  color: var(--am-text-muted);
}
.model-detail-id-tooltip code {
  font-family: var(--am-font-mono);
  font-size: 12px;
  color: var(--am-text-strong, var(--am-text));
  overflow-wrap: anywhere;
}
</style>
