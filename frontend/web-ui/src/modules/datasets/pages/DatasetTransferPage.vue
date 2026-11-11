<template>
  <section class="dataset-workspace transfer-workspace" :class="{ 'import-workspace': importing }">
    <div class="dataset-heading">
      <div class="dataset-actions">
        <Button :disabled="busy" @click="router.push('/datasets')"
          ><ArrowLeft :size="16" />{{ text('back') }}</Button
        >
        <h1 class="dataset-title">
          {{ importing ? text('import') : label('创建数据集导出', 'Create dataset export') }}
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
        ><div class="step-copy">{{ title }}<small v-if="!importing && exportStepDetails[index]" :title="exportStepDetails[index]">{{ exportStepDetails[index] }}</small></div>
      </li>
    </ol>
    <InlineError v-if="error" :message="error" />
    <Button v-if="initFailed" @click="initialize">{{ label('重新加载', 'Retry loading') }}</Button>
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
    <form v-else class="dataset-wizard" :data-step="step" @submit.prevent="next">
      <div :class="{ 'resource-section export-panel': !importing && step < 3, 'import-panel': importing, 'import-upload-panel': importing && step === 0, 'import-review-panel': step === 3 }">
      <div v-if="importing && step > 0 && step < 3" class="import-file-summary">
        <span><FileText :size="22" /><strong :title="file?.name">{{ file?.name }}</strong></span>
        <span>{{ formatSize(file?.size) }}</span>
        <span>{{ label('已上传', 'Uploaded') }}</span>
      </div>
      <div v-if="importing && step === 3" class="import-review-summary">
        <div class="review-file"><FileText :size="24" /><div><strong :title="file?.name">{{ file?.name }}</strong><small class="review-file-meta"><span>{{ formatSize(file?.size) }}</span><span>{{ label('已上传', 'Uploaded') }}</span><span>{{ datasetDate(uploadedAt) }}</span></small></div></div>
        <div><small>{{ label('导入到', 'Destination') }}</small><strong :title="name">{{ name }}</strong><small v-if="!existingMode || currentVersion">{{ label('预计版本', 'Expected version') }} v{{ existingMode ? (currentVersion || 0) + 1 : 1 }}</small></div>
        <div v-for="metric in reviewMetrics" :key="metric.label"><strong :title="String(metric.value)">{{ metric.value }}</strong><small>{{ metric.label }}</small></div>
      </div>
      <div v-if="!importing && step === 3 && selected" class="export-review-summary export-route">
        <Database class="source-symbol" :size="26" /><div><strong>{{ selected.display_name }} v{{ selected.version_number }}</strong><small>{{ exportCount.toLocaleString() }} {{ text('samples') }}<template v-if="exportObjectCount != null"> · {{ exportObjectCount.toLocaleString() }} {{ label('个对象','objects') }}</template> · {{ enabledClasses.length }} {{ text('classes') }} · {{ datasetDate(selected.created_at).split(' ')[0] }}</small></div>
        <ArrowRight :size="21" /><Scan class="source-symbol" :size="25" /><div><strong>{{ exportFormatLabel }}</strong><small>{{ splitSummary }}</small></div>
      </div>
      <div v-else-if="!importing && step > 0" class="transfer-summary">
        <Database class="source-symbol" :size="24" /><strong>{{ selected?.display_name || selected?.dataset_id }} v{{ selected?.version_number }}</strong>
        <span>·</span><span>{{ selected?.task_type }}</span>
        <span>·</span><span>{{ exportCount.toLocaleString() }} {{ text('samples') }}</span><template v-if="step === 1 && !selection"><span>·</span><span>{{ selected?.object_count.toLocaleString() }} {{ label('个对象', 'objects') }}</span></template><strong v-if="step >= 2" class="export-target">→ {{ exportFormatLabel }}</strong>
      </div>
      <fieldset :disabled="busy" class="dataset-wizard-fields">
        <template v-if="importing">
          <template v-if="step === 0">
            <h2>{{ label('上传数据集文件', 'Upload dataset file') }}</h2>
            <FilePicker class="transfer-drop" v-model="packageFile" :show-label="false" :show-clear="false"
              icon="upload" accept=".zip,application/zip" :label="label('ZIP 文件', 'ZIP file')">
              <template #content>
                <strong>{{ label('拖拽 ZIP 文件到此处，或点击选择文件', 'Drop a ZIP here or click to choose a file') }}</strong>
                <span>{{ label('支持 .zip 格式', '.zip format supported') }}</span>
              </template>
              <template #choose-label>{{ file ? label('重新选择', 'Choose again') : label('选择文件', 'Choose file') }}</template>
            </FilePicker>
            <template v-if="file">
              <h2 class="import-file-heading">{{ draft ? label('已上传文件', 'Uploaded file') : label('上传文件', 'File upload') }}</h2>
              <ResourceTable embedded class="dataset-table import-upload-table" :label="label('上传文件', 'File upload')">
                <thead><tr>
                  <th>{{ text('fileName') }}</th><th>{{ label('大小', 'Size') }}</th>
                  <th v-if="!draft">{{ label('上传进度', 'Progress') }}</th><th>{{ text('status') }}</th>
                  <th>{{ label('上传时间', 'Upload time') }}</th><th>{{ text('actions') }}</th>
                </tr></thead>
                <tbody><tr :class="{ 'upload-failed': uploadError }">
                  <td :title="file.name"><FileText :size="18" class="file-inline-icon" /> {{ file.name }}</td>
                  <td>{{ formatSize(file.size) }}</td>
                  <td v-if="!draft"><progress max="100" :value="uploadPercent" /> {{ uploadPercent }}%</td>
                  <td aria-live="polite">
                    <span :class="{ 'upload-complete': draft, 'upload-error': uploadError }">
                      <component v-if="draft || uploadError" :class="{ 'status-disc': draft }" :is="draft ? CircleCheck : CircleAlert" :size="17" />
                      {{ draft ? label('上传完成', 'Uploaded') : uploadError ? (uploadRejected ? label('上传失败', 'Upload failed') : label('上传中断', 'Interrupted')) : label('上传中', 'Uploading') }}
                    </span>
                    <small v-if="uploadError">{{ uploadError }}</small>
                  </td>
                  <td>{{ datasetDate(uploadedAt) }}</td>
                  <td><Button icon-only variant="ghost" :aria-label="text('remove')" :title="text('remove')" @click="packageFile = null"><Trash2 :size="16" /></Button></td>
                </tr></tbody>
              </ResourceTable>
              <InlineError v-if="scanError && !uploadError && !uploading" :message="scanError" />
              <Button v-if="scanError && !uploadError && !uploading" class="dataset-add-map" @click="inspectZip(file)">{{ label('重新读取', 'Read again') }}</Button>
            </template>
          </template>
          <template v-if="step === 1">
            <div class="field definition-field">
              <span>{{ label('导入方式', 'Destination') }} <i>*</i></span>
              <div class="transfer-choices destination-choices">
                <label v-if="!route.query.dataset"><input type="radio" name="destination" :checked="!existingMode" @change="chooseDestination(false)" />{{ label('新建数据集', 'New dataset') }}</label>
                <label><input type="radio" name="destination" :checked="existingMode" :disabled="!!route.query.dataset" @change="chooseDestination(true)" />{{ label('已有数据集的新版本', 'New version of existing dataset') }}</label>
              </div>
            </div>
            <div v-if="existingMode" class="field definition-field">
              <span>{{ text('datasets') }} <i>*</i></span>
              <div>
                <input v-if="route.query.dataset" :value="name" disabled />
                <SelectField v-else :aria-label="text('datasets')" :model-value="existing?.dataset_id || ''"
                  :options="importDestinations.map(d => ({ value: d.dataset_id, label: d.display_name }))" @update:model-value="setExisting(String($event))" />
                <small v-if="currentVersion">{{ label('当前版本', 'Current version') }}　v{{ currentVersion }}</small>
              </div>
            </div>
            <label v-else class="field definition-field"><span>{{ text('name') }} <i>*</i></span><input v-model="name" maxlength="255" required /></label>
            <label class="field definition-field"><span>{{ workflowResource ? label('数据类型', 'Data type') : text('task') }} <i v-if="!workflowResource">*</i></span>
              <input v-if="workflowResource" disabled :value="text(taskType)" />
              <input v-else-if="existing" disabled :value="taskType + '（' + text(taskType) + '）'" />
              <SelectField v-else v-model="taskType" :options="modelTaskOptions" />
            </label>
            <div class="field definition-field"><span>{{ label('来源格式', 'Source format') }} <i>*</i></span>
              <div><SelectField v-model="formatType" :aria-label="label('来源格式', 'Source format')" :options="formatOptions" />
                <small v-if="preview?.format && formatType === preview.format">{{ label('已从 ZIP 识别。','Detected from ZIP.') }}</small>
              </div>
            </div>
            <label v-if="!existingMode" class="field definition-field"><span>{{ text('description') }}</span><textarea v-model="description" rows="2" maxlength="2000" /></label>
            <p v-if="existingMode" class="definition-note"><Info :size="16" />{{ label('导入完成后生成新版本，已有版本保持不变。','Import creates a new version and preserves existing versions.') }}</p>
            <details v-if="isMediaTask(taskType)" class="field--wide">
              <summary>
                {{ label('ZIP 清单格式', 'ZIP manifest format') }}
              </summary>
              <pre class="dataset-json">{{ mediaExample }}</pre>
            </details>
          </template>
          <template v-if="step === 2"
            >
            <div v-if="canMapClasses" class="field field--wide">
              <ImportClassMapping v-model="classMap" :format="formatType || preview?.format || ''"
                :allow-supplement="!!preview?.limited || !preview?.classes.length"
                @editing="mappingPending = $event" />
            </div>
            <div class="import-splits">
              <h2>{{ text('splits') }}</h2>
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
            <ResourceTable v-if="split === 'redistribute' || hasSourceCounts" class="dataset-table split-table" :label="text('splits')">
              <thead><tr>
                <th>{{ label('划分', 'Split') }}</th>
                <th v-if="split === 'redistribute'">{{ label('比例', 'Ratio') }}</th>
                <th>{{ split === 'redistribute' ? label('预计样本数', 'Expected samples') : text('samples') }}</th>
                <th v-if="split === 'auto'">{{ label('对象数', 'Objects') }}</th>
              </tr></thead>
              <tbody><tr v-for="(key, index) in splitKeys" :key="key">
                <td>{{ key }}</td>
                <td v-if="split === 'redistribute'"><label class="field field--compact field--wide split-percent"><input v-model.number="ratios[index]" type="number" min="0" max="100" step="1" :aria-label="key + ' %'" /><span>%</span></label></td>
                <td>{{ effectiveSplits[key] ?? '—' }}</td>
                <td v-if="split === 'auto'">{{ preview?.splitObjects[key] ?? (preview?.objects != null && !preview?.splits[key] ? 0 : '—') }}</td>
              </tr>
              <tr class="split-total"><th scope="row">{{ label('合计', 'Total') }}</th><td v-if="split === 'redistribute'">{{ ratioSum }}%</td><td>{{ preview?.samples ?? '—' }}</td><td v-if="split === 'auto'">{{ preview?.objects ?? '—' }}</td></tr>
              </tbody>
            </ResourceTable>
            <p v-if="split === 'redistribute' && !validRatios" class="upload-error" role="status">{{ label('比例须为 0–100 的整数，合计 100%。', 'Use whole percentages totaling 100%.') }}</p>
            <p v-if="split === 'auto' && !hasSourceCounts" class="import-hint">{{ preview?.limited ? label('文件超出本地预览范围，原划分由导入任务读取。', 'The archive exceeds the preview limit. The import worker reads the source splits.') : label('未识别到原划分清单，提交后由导入任务检查。', 'Source splits could not be previewed. The import worker checks them.') }}</p>
            <label v-if="split === 'redistribute'" class="field field--compact field--wide split-seed">{{ label('随机种子', 'Random seed') }}<input v-model.number="seed" type="number" min="0" max="2147483647" /></label>
          </template>
          <template v-if="step === 3">
            <DatasetTransferReview
              :files="preview?.files || []" :root-label="file?.name"
              :file-title="label('文件结构', 'File structure')"
              :title="label('检查结果', 'Check results')"
              :checks="importChecks"
              embedded
              :note="
                preview && preview.fileCount > preview.files.length
                  ? label('仅展示前 2000 个文件', 'First 2,000 files shown')
                  : ''
              "
            >
              <template v-if="preview?.issues.length || importMismatch" #before>
                <div class="import-blocked" role="alert">
                  <CircleAlert :size="22" /><strong>{{ label('发现阻断问题','Blocking issues') }} ({{ (preview?.issues.length || 0) + Number(importMismatch) }})</strong>
                  <Button v-if="importMismatch" size="sm" @click="step = 1">{{ label('修改数据定义', 'Edit definition') }}</Button>
                  <Button v-if="preview?.issues.length" size="sm" @click="step = 0">{{ label('重新选择 ZIP', 'Choose another ZIP') }}</Button>
                </div>
                <ResourceTable v-if="preview?.issues.length" embedded class="dataset-table import-issues" :label="label('阻断问题','Blocking issues')">
                  <thead><tr><th>{{ label('问题类型','Issue') }}</th><th>{{ label('文件路径','File path') }}</th><th>{{ label('关联标注','Annotation file') }}</th></tr></thead>
                  <tbody><tr v-for="(issue, i) in preview.issues" :key="i"><td>{{ issueNames[issue.kind] }}</td><td :title="issue.path">{{ issue.path }}</td><td :title="issue.manifest">{{ issue.manifest || '—' }}</td></tr></tbody>
                </ResourceTable>
              </template>
              <template v-if="!preview?.issues.length && !importMismatch">
              <h3 class="import-stat-heading">{{ label('统计摘要','Statistics') }}</h3>
              <dl class="import-statistics">
                <div v-for="stat in importStatistics" :key="stat.label">
                  <dt>{{ stat.label }}</dt><dd :title="stat.detail || undefined">{{ stat.value }}</dd>
                  <dd v-if="stat.detail" class="stat-detail" :title="stat.detail">{{ stat.detail }}</dd>
                </div>
              </dl>
              </template>
            </DatasetTransferReview>
          </template></template
        >
        <template v-else>
          <template v-if="step === 0"
            ><p v-if="selection" class="field--wide">
              {{ label('导出所选样本', 'Export selected samples') }} ·
              {{ selectionCounts?.sample_count ?? '…' }}
            </p>
            <label class="field export-source-picker"
              ><span>{{ label('选择数据集','Select dataset') }}</span
              ><SelectField
                :model-value="sourceDataset"
                :options="
                  destinations.map((d) => ({
                    value: d.dataset_id,
                    label: d.display_name,
                  }))
                "
                @update:model-value="changeSource(String($event))"
            ><template #value="{ option }"><span class="export-source-value"><Database :size="20" />{{ option?.label }}</span></template></SelectField></label>
            <h2>{{ label('选择来源版本', 'Select source version') }}</h2>
            <ResourceTable
              class="dataset-table field--wide"
              :inert="listPending || listFailed"
              :aria-busy="listPending"
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
                      requestedVersion?.dataset_version_id === item.dataset_version_id,
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
                        requestedVersion?.dataset_version_id === item.dataset_version_id
                      "
                      @click.stop="selectVersion(item)"
                    />
                  </td>
                  <td>
                    {{ `v${item.version_number}` }}
                  </td>
                  <td>{{ text(item.task_type) }}</td>
                  <td>{{ item.sample_count.toLocaleString() }}</td>
                  <td>{{ item.object_count.toLocaleString() }}</td>
                  <td>{{ datasetDate(item.created_at) }}</td>
                </tr>
              </tbody></ResourceTable
            ><PaginationControls
              v-if="sourceTotal > 20"
              :offset="sourceOffset"
              :limit="20"
              :item-count="versions.length"
              :total-count="sourceTotal"
              :disabled="listPending || listFailed"
              @previous="pageVersions(-20)"
              @next="pageVersions(20)"
          />
            <Button v-if="listFailed" @click="retryVersionList">{{ label('重试加载列表','Retry loading list') }}</Button>
            <p v-else-if="!busy && !listPending && !initFailed && !versions.length">{{ label('没有可选的来源版本','No source versions available') }}</p>
          </template>
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
                maxlength="180" placeholder="dataset.zip" /></label>
          </template>
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
                  <th>{{ label('目标类别 ID','Target class ID') }}</th>
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
                    <label v-if="canFilterClasses" class="field field--wide field--compact"><input
                      type="number"
                      min="0"
                      v-model.number="row.output"
                      :disabled="!row.enabled"
                      :aria-label="row.source + ' ID'"
                    /></label><template v-else>{{ row.id }}</template>
                  </td>
                  <td>
                    <label class="field field--wide field--compact"><input
                      :disabled="!row.enabled"
                      v-model="row.target"
                      :aria-label="row.source"
                    /></label>
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
                  <th>{{ label('对象数','Objects') }}</th>
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
                  <td>{{ key }}<small v-if="!sourceCounts[key]">{{ label('未配置','Not configured') }}</small></td>
                  <td>{{ sourceCounts[key] ?? '—' }}</td>
                  <td>{{ exportSplitObjects(key) ?? '—' }}</td>
                </tr>
              </tbody></ResourceTable
            >
          </template>
          <template v-if="step === 3"
            ><div v-if="exportBlocked" class="compatibility-banner" role="alert">
              <CircleAlert :size="24" /><div><strong>{{ label('当前配置不兼容', 'Incompatible settings') }}</strong>
              <p>{{ label('当前来源与导出配置不兼容，请调整目标格式或划分。','Source and export settings are incompatible. Change the target format or splits.') }}</p></div>
            </div><DatasetTransferReview
              embedded variant="export" :file-counts="plannedCounts" :files="plannedFiles" :root-label="displayName"
              :file-title="label('目标文件结构', 'Target file structure') + ' · ' + exportFormatLabel"
              :title="label('兼容性检查结果', 'Compatibility results')"
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
                <ResourceTable embedded class="dataset-table" :label="label('格式对照', 'Format comparison')">
                  <thead><tr><th>{{ label('项目','Item') }}</th><th>{{ label('来源数据集','Source dataset') }}</th><th>{{ label('目标格式','Target format') }}</th></tr></thead>
                  <tbody><tr><th>{{ text('task') }}</th><td>{{ selected?.task_type }}</td><td :title="targetTasks">{{ targetTasks || '—' }}</td></tr>
                    <tr><th>{{ label('格式','Format') }}</th><td>{{ selected?.metadata.format_type || '—' }}</td><td>{{ exportFormatLabel }}</td></tr></tbody>
                </ResourceTable>
                <div v-if="comparisonSample && selected" class="comparison-pair"><figure>
                <DatasetSampleImage
                  class="comparison-image"
                  :dataset-id="selected.dataset_id"
                  :sample="comparisonSample"
                  :categories="selected.categories"
                  :show-annotations="true"
                /><figcaption>{{ label('来源标注','Source annotations') }}</figcaption></figure>
                <figure><DatasetSampleImage class="comparison-image" :dataset-id="selected.dataset_id" :sample="comparisonSample" :categories="selected.categories" :show-annotations="false" />
                  <figcaption>{{ label('原图 · 未生成目标标注','Original · no target annotation generated') }}</figcaption></figure></div>
              </template>
              <template #statistics><div v-if="!exportBlocked" class="export-review-bottom">
              <section v-if="enabledClasses.length">
              <h3>{{ label('类别映射', 'Class mapping') }} ({{ enabledClasses.length }})</h3>
              <ResourceTable
                embedded
                class="dataset-table export-mapping-table"
                :label="text('classes')"
                ><thead>
                  <tr>
                    <th>{{ label('源类别', 'Source class') }}</th>
                    <th>{{ label('目标 ID', 'Target ID') }}</th>
                    <th>{{ label('对象数','Objects') }}</th><th>{{ label('映射状态','Mapping status') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in enabledClasses" :key="row.id">
                    <td :title="row.source === row.target ? row.source : row.source + ' → ' + row.target">{{ row.source === row.target ? row.source : row.source + ' → ' + row.target }}</td>
                    <td>{{ row.output }}</td>
                    <td>{{ categoryExportObjects(row.id) ?? '—' }}</td>
                    <td><span class="mapped-state"><CircleCheck class="status-disc" :size="15" />{{ label('已映射','Mapped') }}</span></td>
                  </tr>
                </tbody></ResourceTable>
              </section>
              <section><h3>{{ label('导出统计（预计）','Estimated export totals') }}</h3>
                <dl class="export-metrics">
                  <div><dt>{{ text('samples') }}</dt><dd>{{ exportCount.toLocaleString() }}</dd></div>
                  <div v-for="metric in estimatedFiles" :key="metric.label"><dt>{{ metric.label }}</dt><dd>{{ metric.count == null ? '—' : metric.count.toLocaleString() }}</dd></div>
                </dl>
              </section></div></template>
              <div v-if="exportBlocked" class="compatibility-reason"><strong>{{ label('不兼容原因','Incompatibility') }}</strong><p>{{ exportOptions.some(o => o.value === exportFormat) ? label('所选划分没有可导出的样本。','No samples in the selected splits.') : label('来源任务与目标格式不匹配。','The target format does not support the source task.') }}</p></div></DatasetTransferReview
            ></template
          >
        </template>
      </fieldset>
      <div v-if="!importing && step === 0 && sourceSummary" class="transfer-summary source-choice" :aria-busy="versionPending"><Database class="source-symbol" :size="24" />
        <div><strong>{{ label('已选择', 'Selected') }} {{ sourceSummary.display_name }} v{{ sourceSummary.version_number }} · {{ sourceSummary.sample_count.toLocaleString() }} {{ text('samples') }} · {{ sourceSummary.category_count }} {{ text('classes') }}</strong>
        <small><Info :size="14" />{{ label(`本次导出使用 v${sourceSummary.version_number}，新增版本不会改变此选择。`, `This export uses v${sourceSummary.version_number}, even if a newer version is created.`) }}</small></div>
      </div>
      <Button v-if="!importing && step === 0 && versionFailed && requestedVersion" class="dataset-add-map" @click="selectVersion(requestedVersion)">{{ label('重试加载版本', 'Retry loading version') }}</Button>
      <div v-if="!importing && step === 1" class="wizard-note"><Info :size="18" /><div><strong>{{ label('目标任务', 'Target task') }}</strong> {{ targetTasks || '—' }}<small>{{ label('来源版本将保持不变。','The source version is preserved.') }}</small></div></div>
      <div v-if="!importing && step === 2" class="wizard-note"><Info :size="17" />{{ label('本次选择', 'Selection') }}：{{ exportCount }} {{ text('samples') }} · {{ enabledClasses.length }} {{ text('classes') }}</div>
      </div>
      <footer class="dataset-wizard-footer">
        <Button
          :disabled="busy"
          @click="step ? previousStep() : router.push('/datasets')"
          >{{ step ? label('上一步', 'Previous') : text('cancel') }}</Button
        >
        <div class="dataset-actions">
          <template v-if="!importing && step === 3 && exportBlocked"><Button @click="step = 0">{{ label('返回来源版本', 'Source version') }}</Button><Button variant="primary" @click="step = 1">{{ label('更换目标格式', 'Change target format') }}</Button></template>
          <Button v-if="importing && !step && uploadError && !uploadRejected && file" variant="primary" @click="uploadFile(file)">{{ label('重新上传', 'Retry upload') }}</Button>
          <Button
            type="submit"
            variant="primary"
            :loading="busy"
            :disabled="
              busy ||
              !canWrite || initFailed ||
              (importing
                ? scanBusy ||
                  uploading ||
                  !draft ||
                  !file ||
                  !!scanError ||
                  (step === 2 && (mappingPending || (split === 'redistribute' && !validRatios))) ||
                  (step === 3 && (!!preview?.issues.length || importMismatch))
                : !sourceReady || (step === 3 && exportBlocked))
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
import { ArrowLeft, ArrowRight, Scan, Database, FileText, CircleCheck, CircleAlert, Trash2, Info, Check } from '@lucide/vue'
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
import ImportClassMapping, { type ImportMapRow } from '../components/ImportClassMapping.vue'
import DatasetTransferReview from '../components/DatasetTransferReview.vue'
import DatasetSampleImage from '../components/DatasetSampleImage.vue'
import { apiRequest, uploadForm } from '@/shared/api/http-client'
import ArchiveWorker from '../archive-preview.worker?worker'
import type { ArchivePreview } from '../archive-preview.worker'
import { datasetDate, useDatasetText, datasetError, datasetFormatLabel } from '../dataset-workspace'
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
  ratios = ref([80, 20, 0]),
  seed = ref(42),
  mappingPending = ref(false),
  classMap = ref<ImportMapRow[]>([])
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
let newDefinition = { name: '', description: '', task: 'detection', format: '' }
async function chooseDestination(mode: boolean) {
  if (mode === existingMode.value) return
  if (mode) newDefinition = { name: name.value, description: description.value, task: taskType.value, format: formatType.value }
  existingMode.value = mode
  setExisting('')
  if (!mode) {
    name.value = newDefinition.name
    description.value = newDefinition.description
    taskType.value = newDefinition.task
    formatType.value = newDefinition.format
    return
  }
  try {
    if (!destinations.value.length) await loadDestinations()
    if (existingMode.value) {
      const compatible = importDestinations.value.find(item => item.task_type === newDefinition.task)
      setExisting(compatible?.dataset_id || '')
    }
  } catch (e) {
    error.value = datasetError(e)
  }
}
const preview = ref<ArchivePreview | null>(null),
  scanBusy = ref(false),
  scanError = ref('')
let archiveWorker: Worker | undefined
const uploadedAt = ref('')
const uploadPercent = ref(0)
const uploadRejected = ref(false)
const currentVersion = computed(() => destinations.value.find(item => item.dataset_id === existing.value?.dataset_id)?.latest_version?.version_number)
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
  uploadRejected.value = false
  uploadError.value = ''
  uploading.value = !!input
  uploadPercent.value = 0
  uploadedAt.value = new Date().toISOString()
  if (!input) return
  const ctl = (uploadController = new AbortController())
  try {
    const form = new FormData()
    form.set('project_id', projectId)
    form.set('package', input)
    const r = await uploadForm<{ draft_id: string }>(
      '/datasets/upload-drafts',
      form, ctl.signal, fraction => { if (!ctl.signal.aborted) uploadPercent.value = Math.round(100 * fraction) },
    )
    if (!active || ctl.signal.aborted) {
      discardDraft(r.draft_id)
      return
    }
    draft.value = r.draft_id
    uploadedAt.value = new Date().toISOString()
  } catch (e) {
    if (active && !ctl.signal.aborted) {
      uploadRejected.value = e instanceof ApiError && [400, 413, 415, 422].includes(e.status)
      uploadError.value = datasetError(e)
    }
  } finally {
    if (active && ctl === uploadController) uploading.value = false
  }
}
function inspectZip(input: File | null) {
  archiveWorker?.terminate()
  archiveWorker = undefined
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
    if (formatOptions.value.some(item => item.value === r.format)) formatType.value = r.format
    classMap.value = r.classes.map(c => ({ ...c, source: ['coco', 'yolo'].includes(r.format) ? c.id : c.name, target: c.name }))
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
  w.postMessage({ file: input, task: taskType.value })
}
watch(file, (input, previous) => {
  error.value = ''
  formatType.value = ''
  if (!existingMode.value && previous && name.value === previous.name.replace(/\.zip$/i, '')) name.value = ''
  split.value = 'auto'
  if (!existing.value && input && input !== previous) taskType.value = 'detection'
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
  if (id.includes('imagenet')) return label('按划分和类别组织图像，每个划分附带 JSON 清单。', 'Images grouped by split and class, with a JSON manifest for each split.')
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
const splitKeys = ['train', 'val', 'test'] as const
watch(step, () => { mappingPending.value = false })
const hasSourceCounts = computed(() => !!preview.value && Object.keys(preview.value.splits).length > 0)
const ratioSum = computed(() => ratios.value.reduce((sum, value) => sum + Number(value), 0))
const validRatios = computed(() => ratioSum.value === 100 && ratios.value.every(value => Number.isInteger(value) && value >= 0 && value <= 100))
const effectiveSplits = computed<Record<string, number | undefined>>(() => {
  if (split.value === 'auto') {
    if (!hasSourceCounts.value) return {}
    return Object.fromEntries(splitKeys.map(key => [key, preview.value!.splits[key] ?? 0]))
  }
  const total = preview.value?.samples
  if (total == null || !validRatios.value) return {}
  // 导入按单个样本分配；整除后的余量按不足数最大者补齐，相等时先 train、再 val。
  const targets = ratios.value.map(value => total * value / 100)
  const counts = targets.map(Math.floor)
  for (let left = total - counts.reduce((a, b) => a + b, 0); left > 0; left--) {
    const deficits = targets.map((target, i) => target - counts[i])
    counts[deficits.indexOf(Math.max(...deficits))]++
  }
  return Object.fromEntries(splitKeys.map((key, index) => [key, counts[index]]))
})
const reviewMetrics = computed(() => [
  { label: label('样本数', 'Samples'), value: preview.value?.samples?.toLocaleString() ?? '—' },
  { label: label('对象数量', 'Objects'), value: preview.value?.objects?.toLocaleString() ?? '—' },
  { label: label('类别数量', 'Classes'), value: preview.value?.classes.length.toLocaleString() ?? '—' },
  { label: 'train / val / test',
    value: splitKeys.map(key => effectiveSplits.value[key]?.toLocaleString() ?? '—').join(' / ') },
])
const issueNames = computed(() => ({
  missing: label('文件缺失', 'Missing file'), duplicate: label('路径重复', 'Duplicate path'),
  unsafe: label('不支持的路径或加密文件', 'Unsupported path or encrypted entry'), empty: label('空 ZIP', 'Empty ZIP'),
}))
const importStatistics = computed(() => {
  const metrics = reviewMetrics.value
  const manifestFiles = preview.value?.annotationFiles || []
  const format = formatOptions.value.find(option => option.value === (formatType.value || preview.value?.format))
  const testCount = effectiveSplits.value.test
  return [
    { ...metrics[0], detail: splitKeys.map(key => key + ' ' + (effectiveSplits.value[key] ?? '—')).join(' / ') },
    { ...metrics[1], detail: '' },
    { ...metrics[2], detail: classMap.value.map(row => row.target).join(' / ') },
    { label: label('标注清单', 'Manifests'), value: manifestFiles.length || '—', detail: manifestFiles.join(', ') },
    { label: label('数据格式', 'Format'), value: format?.label || '—', detail: text(taskType.value) },
    { label: label('测试集', 'Test set'), value: testCount == null ? '—' : testCount ? label('已配置', 'Configured') : label('未配置', 'Not configured'), detail: '' },
  ]
})
const importChecks = computed(() => {
  const source = preview.value
  const problems = source?.issues || []
  const missing = problems.filter(issue => issue.kind === 'missing')
  const badEntry = problems.find(issue => issue.kind !== 'missing')
  const checkedReferences = !source?.limited && ['coco', 'amvision-media'].includes(source?.format || '')
  const counts = effectiveSplits.value
  const test = counts.test
  const checks = [
    { name: label('图片文件', 'Image files'), state: badEntry ? 'error' : 'info',
      result: badEntry ? undefined : label('待解码', 'Pending decode'),
      value: badEntry ? issueNames.value[badEntry.kind] : label('提交后由导入任务解码检查', 'Decoded by the import worker after submission') },
    { name: label('标注文件关联', 'Annotation references'), state: missing.length ? 'error' : checkedReferences ? 'pass' : 'info',
      value: missing.length ? label('标注引用的文件缺失', 'Referenced files are missing') : checkedReferences ? label('清单引用的文件已找到', 'Referenced files found') : label('提交后检查', 'Checked after submission') },
    { name: label('类别识别', 'Class recognition'), state: source?.classes.length ? 'pass' : 'info',
      value: source?.classes.length ? label('已识别', 'Detected') + ' ' + source.classes.length + ' ' + text('classes') : label('由导入任务检查', 'Checked by worker') },
    { name: text('splits'), state: Object.keys(counts).length ? 'pass' : 'info',
      value: splitKeys.filter(key => counts[key]).map(key => key + ' ' + counts[key]?.toLocaleString()).join(' / ') || '—' },
    { name: label('测试集配置', 'Test split'), state: test ? 'pass' : 'info',
      result: test === 0 ? label('未配置', 'Not configured') : undefined,
      value: test == null ? label('由导入任务检查', 'Checked by worker') : test ? test.toLocaleString() + ' ' + text('samples') : label('本次不包含测试集', 'No test samples in this import') },
  ]
  if (importMismatch.value) checks.unshift({ name: label('任务与格式', 'Task and format'), state: 'error', value: label('所选任务或格式与 ZIP 不符', 'Selection does not match the ZIP') })
  return checks
})
const importMismatch = computed(
  () =>
    !!preview.value &&
    ((!!preview.value.task && preview.value.task !== taskType.value) ||
      (!!preview.value.format && !formatOptions.value.some(option => option.value === preview.value!.format)) ||
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
    else if (id.includes('voc')) {
      if (!paths.includes('JPEGImages/')) paths.push('JPEGImages/', 'Annotations/')
      const masks = id.includes('segmentation')
      if (masks && !paths.includes('SegmentationClass/')) paths.push('SegmentationClass/', 'SegmentationObject/')
      paths.push('ImageSets/' + (masks ? 'Segmentation/' : 'Main/') + split + '.txt')
    } else if (id.includes('dota')) paths.push('images/' + split + '/', 'labels/' + split + '/')
    else if (id.includes('imagenet'))
      paths.push(
        ...enabledClasses.value.map((c) => split + '/' + c.target + '/'),
      )
  }
  if (id.includes('voc')) {
    const dir = 'ImageSets/' + (id.includes('segmentation') ? 'Segmentation/' : 'Main/')
    if (includedSplits.value.some(s => s === 'train' || s === 'val')) paths.push(dir + 'trainval.txt')
    if (id.includes('segmentation')) for (const s of ['train', 'val']) if (!includedSplits.value.includes(s)) paths.push(dir + s + '.txt')
  }
  if (id.includes('dota') || id.includes('yolo-obb') || id.includes('imagenet'))
    paths.push(...includedSplits.value.map(split => 'annotations/' + split + '.json'))
  return paths
})
// 只估算写入器明确保证的文件数量；媒体附件和 ZIP 压缩大小需等执行结束。
const plannedCounts = computed(() => {
  const counts: Record<string, number> = {}
  const classCounts = new Map(enabledClasses.value.map(row => [
    row.target, sourceStats.value.find(item => item.category_id === row.id)?.split_objects,
  ]))
  for (const path of plannedFiles.value) {
    const parts = path.split('/').filter(Boolean)
    if (!path.endsWith('/')) counts[path] = 1
    else if (parts.length === 2 && ['images', 'labels'].includes(parts[0])) counts[path] = sourceCounts.value[parts[1]] ?? 0
    else if (['JPEGImages/', 'Annotations/', 'SegmentationClass/', 'SegmentationObject/'].includes(path)) counts[path] = exportCount.value
    else if (exportFormat.value.includes('imagenet') && !selection.value && classCounts.get(parts[1])) {
      counts[path] = classCounts.get(parts[1])?.[parts[0]] ?? 0
    }
  }
  return counts
})
const estimatedFiles = computed(() => {
  const paths = plannedFiles.value, counts = plannedCounts.value
  const known = paths.every(path => counts[path] != null)
  const sum = (keys: string[]) => keys.reduce((acc, key) => acc + counts[key], 0)
  const annotations = paths.filter(p => /^(labels|annotations|Annotations|SegmentationClass|SegmentationObject)\//.test(p))
  return [
    { label: label('标注文件', 'Annotation files'), count: annotations.length && annotations.every(path => counts[path] != null) ? sum(annotations) : null },
    { label: label('配置文件','Configuration files'), count: 1 },
    { label: label('文件总数', 'Total files'), count: known ? sum(paths) : null },
    { label: label('预计包大小', 'Estimated size'), count: null },
  ]
})
const exportChecks = computed(() => [
  {
    name: label('来源版本', 'Source version'),
    state: selected.value ? 'pass' : 'error',
    value: selected.value ? 'v' + selected.value.version_number : '—',
  },
  {
    name: label('任务兼容性', 'Task compatibility'),
    state: exportOptions.value.some((o) => o.value === exportFormat.value)
      ? 'pass'
      : 'error',
    value: text(selected.value?.task_type || '—') + ' → ' + exportFormatLabel.value,
  },
  {
    name: label('导出范围', 'Export selection'),
    state: exportCount.value > 0 ? 'pass' : 'error',
    value: splitSummary.value,
  },
  { name: label('类别映射', 'Class mapping'), state: enabledClasses.value.length ? 'pass' : 'info',
    value: enabledClasses.value.length + ' ' + text('classes') },
])
const sourceSelection = window.history.state?.datasetSelection
const initialSelection: DatasetSampleSelection | undefined =
  sourceSelection?.version === route.query.version ? sourceSelection?.selection : undefined
const selection = ref(initialSelection)
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
const isWorkflowResource = (type?: string) => isMediaTask(type) && type !== 'anomaly'
const workflowResource = computed(() => isWorkflowResource(taskType.value))
const modelTaskOptions = computed(() => taskOptions.value.filter(item => !isWorkflowResource(item.value)))
const importDestinations = computed(() => destinations.value.filter(item => isWorkflowResource(preview.value?.task)
  ? item.task_type === preview.value?.task : !isWorkflowResource(item.task_type)))
const formatOptions = computed(() => [
  { value: '', label: label('自动识别', 'Auto detect') },
  ...(
    (
      (session.bootstrap?.capabilities?.dataset_import
        ?.format_types_by_task_type || {}) as Record<string, string[]>
    )[taskType.value] || []
  ).map((value) => ({ value, label: ({ coco: 'COCO JSON', imagenet: 'ImageNet', 'amvision-media': 'AMVision Media' } as Record<string,string>)[value] || value.toUpperCase() })),
])
const splitOptions = computed(() => [
  {
    value: 'auto',
    label: label('沿用原划分', 'Keep source splits'),
  },
  { value: 'redistribute', label: label('重新划分', 'Redistribute') },
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
type VersionKey = Pick<DatasetVersion, 'dataset_id' | 'dataset_version_id'>
const requestedVersion = ref<VersionKey | null>(null)
const versionPending = ref(false), versionFailed = ref(false)
const listPending = ref(false), listFailed = ref(false), initFailed = ref(false)
let restoreRouteSource = true
let versionController: AbortController | undefined
const sourceReady = computed(() => !!selected.value && !versionPending.value && !versionFailed.value &&
  selected.value.dataset_version_id === requestedVersion.value?.dataset_version_id)
const sourceSummary = computed(() => sourceReady.value ? selected.value :
  versions.value.find(row => row.dataset_version_id === requestedVersion.value?.dataset_version_id))
const exportOptions = computed(() =>
  (
    exportFormats.value?.format_types_by_task_type[
      selected.value?.task_type || ''
    ] || []
  ).map(value => ({ value, label: datasetFormatLabel(value) })),
)
const exportFormatLabel = computed(() => datasetFormatLabel(exportFormat.value))
const exportStepDetails = computed(() => [
  step.value > 0 && selected.value ? selected.value.display_name + ' v' + selected.value.version_number : label('选择导出的数据版本', 'Choose the source version'),
  step.value > 1 ? exportFormatLabel.value : label('选择导出格式', 'Choose the output format'),
  step.value > 2 ? splitSummary.value : label('设置类别和数据划分', 'Set classes and splits'),
  label('检查数据与格式兼容性', 'Check data and format'),
])
function exportSplitObjects(split: string) {
  if (selection.value || !sourceStats.value.length || !sourceCounts.value[split]) return null
  const enabled = new Set(enabledClasses.value.map(item => item.id))
  return sourceStats.value.reduce((sum, item) => sum + (enabled.has(item.category_id) ? item.split_objects[split] || 0 : 0), 0)
}
function categoryExportObjects(id: number) {
  const stats = sourceStats.value.find(item => item.category_id === id)
  if (!stats || selection.value) return null
  return includedSplits.value.reduce((total, split) => total + (stats.split_objects[split] || 0), 0)
}
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
const splitSummary = computed(() => splitKeys.map(key =>
  key + ' ' + (includedSplits.value.includes(key) ? (sourceCounts.value[key] ?? 0).toLocaleString() : label('未包含','excluded')),
).join(' / '))
const exportObjectCount = computed(() => {
  if (selection.value || !sourceStats.value.length) return null
  return includedSplits.value.reduce((total, key) => total + (exportSplitObjects(key) ?? 0), 0)
})
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
  listPending.value = true
  listFailed.value = false
  error.value = ''
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
      return true
    }
  } catch (e) {
    if (active && id === listGeneration) {
      listFailed.value = true
      error.value = datasetError(e)
    }
  } finally {
    if (active && id === listGeneration) listPending.value = false
  }
  return false
}
async function retryVersionList() {
  if (!(await loadVersions()) || requestedVersion.value) return
  const restore = restoreRouteSource && route.query.dataset === sourceDataset.value
  const version = restore && typeof route.query.version === 'string' && route.query.version
    ? { dataset_id: sourceDataset.value, dataset_version_id: route.query.version }
    : versions.value[0]
  if (!version) return
  await selectVersion(version)
}
async function selectVersion(version: VersionKey) {
  if (requestedVersion.value?.dataset_version_id === version.dataset_version_id && (versionPending.value || sourceReady.value)) return
  const id = ++selectionGeneration
  versionController?.abort()
  const controller = versionController = new AbortController()
  requestedVersion.value = version
  versionPending.value = true
  versionFailed.value = false
  error.value = ''
  try {
    const result = await getDatasetWorkspace(
      version.dataset_id,
      version.dataset_version_id,
      controller.signal,
    )
    if (!active || id !== selectionGeneration) return
    const sampleSelection = result.dataset_version_id === route.query.version ? initialSelection : undefined
    if (
      sampleSelection &&
      sourceSelection?.revision !== undefined &&
      sourceSelection.revision !== String(result.metadata.content_revision || '')
    ) {
      throw new Error(
        label(
          '当前版本已更新，请返回重新选择样本。',
          'This version has changed. Go back and select samples again.',
        ),
      )
    }
    const counts = sampleSelection
      ? await getDatasetSelectionSummary(
          result.dataset_id,
          result.dataset_version_id,
          sampleSelection,
          controller.signal,
        )
      : null
    if (!active || id !== selectionGeneration) return
    const stats = sampleSelection
      ? []
      : (
          await getDatasetCategories(
            result.dataset_id,
            result.dataset_version_id,
            controller.signal,
          )
        ).items
    if (!active || id !== selectionGeneration) return
    selection.value = sampleSelection
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
    const restoreFormat = restoreRouteSource && route.query.version === result.dataset_version_id &&
      typeof route.query.format === 'string' ? route.query.format : undefined
    restoreRouteSource = false
    exportFormat.value = restoreFormat ?? exportOptions.value[0]?.value ?? ''
    if (restoreFormat && !exportOptions.value.some(option => option.value === restoreFormat)) step.value = 3
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
    if (active && id === selectionGeneration) {
      versionFailed.value = true
      error.value = datasetError(e)
    }
  } finally {
    if (active && id === selectionGeneration) versionPending.value = false
  }
}
const canMapClasses = computed(
  () => !isMediaTask(taskType.value) || taskType.value === 'anomaly',
)
watch(taskType, (next, old) => {
  if (preview.value?.format === 'voc' && (next === 'segmentation' || old === 'segmentation')) inspectZip(file.value)
  if (!canMapClasses.value) classMap.value = []
  if (!formatType.value || !formatOptions.value.some(item => item.value === formatType.value)) {
    const detected = preview.value?.format
    formatType.value = formatOptions.value.find(item => item.value === detected)?.value || ''
  }
})
async function next() {
  if (
    busy.value || initFailed.value || (!importing && !sourceReady.value) ||
    unknown.value ||
    (importing && (!draft.value || (step.value === 2 && mappingPending.value))) ||
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
      (classMap.value.some((row) => !row.target.trim()) ||
        ((taskType.value === 'classification' || preview.value?.format === 'yolo') && new Set(classMap.value.map(row => row.target.trim())).size !== classMap.value.length) ||
        new Set(classMap.value.map((row) => row.source.trim())).size !==
          classMap.value.length)
    ) {
      error.value = label(
        '目标类别名称不能为空，分类和 YOLO 的目标名称不能重复。',
        'Target names are required and must be unique for classification and YOLO.',
      )
      return
    }
  } else {
    if (!sourceReady.value || !selected.value) {
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
        splitStrategy: 'auto',
        splitRatios: split.value === 'redistribute' ? ratios.value : undefined,
        splitSeed: split.value === 'redistribute' ? seed.value : undefined,
        displayName: name.value.trim(),
        description: description.value,
        classMapJson: JSON.stringify(
          Object.fromEntries(
            classMap.value.filter(row => row.manual || row.target.trim() !== row.name).map(row => [row.source, row.target.trim()]),
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
    if (importing && e instanceof ApiError && e.status === 404 && (e.details as { resource?: string } | null)?.resource === 'upload_draft') {
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
async function initialize() {
  initFailed.value = false
  error.value = ''
  busy.value = true
  try {
    if (importing && route.query.dataset) {
      await loadDestinations()
      existing.value = await getDatasetInfo(projectId, datasetId.value)
      name.value = existing.value.display_name
      description.value = existing.value.description
      taskType.value = existing.value.task_type
    } else if (!importing) {
      exportFormats.value = await getDatasetExportFormats()
      await loadDestinations()
      if (!sourceDataset.value)
        sourceDataset.value = destinations.value[0]?.dataset_id || ''
      await retryVersionList()
    }
  } catch (e) {
    if (active) {
      initFailed.value = true
      error.value = datasetError(e)
    }
  } finally {
    if (active) busy.value = false
  }
}
onMounted(initialize)
onBeforeUnmount(() => {
  active = false
  archiveWorker?.terminate()
  versionController?.abort()
  uploadController?.abort()
  discardDraft(draft.value)
  selectionGeneration++
  listGeneration++
  answer?.(false)
  window.removeEventListener('beforeunload', unload)
})
async function changeSource(id: string) {
  if (id === sourceDataset.value) return
  restoreRouteSource = false
  ++selectionGeneration
  versionController?.abort()
  requestedVersion.value = null
  versionPending.value = false
  versionFailed.value = false
  error.value = ''
  sourceDataset.value = id
  sourceOffset.value = 0
  selected.value = null
  selection.value = undefined
  await retryVersionList()
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
  width: 46px;
}
.export-panel td:has(> input[name="source-version"]) {
  text-align: center;
  text-overflow: clip;
  padding-inline: 4px;
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
.import-issues { margin: 12px 0 18px; }
.import-issues td { overflow-wrap: anywhere; white-space: normal; }
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
.dataset-wizard .split-percent, .dataset-wizard .split-seed { display: inline-flex; flex-direction: row; align-items: center; gap: 8px; }
.split-percent input { width: 80px; text-align: right; }
.split-percent span { color: var(--am-text-muted); }
.split-seed input { width: 110px; }
.split-total { font-weight: 600; }
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
.comparison-pair { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 16px; }
.comparison-pair figure { margin: 0; min-width: 0; }
.comparison-pair figcaption { margin-top: 6px; font-size: 13px; color: var(--am-text-muted); }
.compatibility-banner { display: flex; gap: 14px; align-items: flex-start; padding: 16px 20px; border-radius: var(--am-radius-sm); background: var(--am-danger-surface); color: var(--am-danger-text); }
.compatibility-banner p { margin: 6px 0 0; color: var(--am-text); }
.transfer-workspace .dataset-steps .has-error span {
  background: var(--am-danger-icon);
  border-color: var(--am-danger-icon);
}

.import-workspace .dataset-steps {
  padding: 4px clamp(18px, 4vw, 64px);
  gap: 14px;
}
.import-workspace .dataset-steps li:last-child { flex: 0 0 auto; }
.import-workspace .dataset-steps li span { width: 34px; height: 34px; flex-shrink: 0; }
.import-workspace { gap: 16px; container-type: inline-size; }
.import-workspace .dataset-wizard { flex: none; gap: 14px; }
.import-panel, .import-review-summary, .import-review-panel :deep(.transfer-review > section),
.import-review-panel :deep(.transfer-files) {
  padding: 20px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  background: var(--am-surface);
}
.import-panel { min-width: 0; }
.import-upload-panel { padding: clamp(16px, 1.6cqi, 24px); padding-bottom: clamp(22px, 4cqi, 52px); }
.import-workspace .import-upload-panel .dataset-wizard-fields { gap: clamp(12px, 1.3cqi, 18px); }
.import-workspace .dataset-wizard-fields { margin: 0; padding: 0; gap: 10px; }
.import-workspace .dataset-wizard-footer {
  margin: 0;
  padding: 4px 0;
  border: 0;
  background: var(--am-page);
}
.import-workspace .dataset-wizard-footer :deep(button) { min-width: 104px; }
.import-workspace .dataset-wizard-footer :deep(button[type='submit']) { min-width: 124px; }
.import-hint, .definition-field small, .definition-note {
  margin: 0; color: var(--am-text-muted); font-size: 14px; font-weight: 400;
}
.import-hint svg { vertical-align: middle; }
.import-workspace .transfer-drop :deep(.file-picker__dropzone) {
  min-height: clamp(170px, min(24cqi, 34dvh), 318px);
  gap: 15px;
  background: color-mix(in srgb, var(--am-text) 2.5%, var(--am-surface));
}
.import-workspace .transfer-drop :deep(.file-picker__content) { display: grid; justify-items: center; gap: 6px; }
.import-workspace .transfer-drop :deep(.file-picker__content strong) { color: var(--am-text); font-size: 16px; font-weight: 500; }
.import-workspace .transfer-drop :deep(.file-picker__icon) { border: 0; background: transparent; box-shadow: none; }
.import-workspace .transfer-drop :deep(.file-picker__actions button) { background: var(--am-surface); }
.import-workspace .transfer-drop :deep(.file-picker__icon svg) { width: 42px; height: 42px; }
.import-workspace .transfer-drop :deep(.file-picker__actions button) { min-width: 140px; height: 36px; }
.import-workspace h2.import-file-heading { margin-top: 8px; }
.import-upload-table th:first-child { width: 33%; }
.import-upload-table th:last-child { width: 8%; }
.import-upload-table td small { display: block; white-space: normal; color: var(--am-danger-text); }
.import-upload-table td span { display: inline-flex; gap: 6px; align-items: center; }
.import-upload-table progress { width: 52%; height: 7px; accent-color: var(--am-brand-primary); }
.upload-failed { background: var(--am-danger-surface); }
.import-upload-table td .upload-complete { color: var(--am-brand-primary); }
.import-upload-table td .upload-complete svg { fill: var(--am-brand-primary); stroke: white; }
.upload-error { color: var(--am-danger-text); }
.import-file-summary { display: grid; grid-template-columns: minmax(0, 43fr) minmax(0,16fr) minmax(0,41fr); align-items: center; padding: 10px 0; background: var(--am-page); border: 1px solid var(--am-border); border-radius: var(--am-radius-sm); margin-bottom: 14px; }
.import-file-summary span { display: flex; gap: 12px; align-items: center; padding: 0 18px; min-width: 0; }
.import-file-summary span + span { border-inline-start: 1px solid var(--am-border); }
.import-file-summary strong { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; font-weight: 500; }
.import-file-summary svg { flex: none; }

.import-workspace .dataset-wizard .definition-field { grid-template-columns: minmax(145px, 21%) minmax(0, 50%); margin: 0; gap: 12px; align-items: start; }
.definition-field > span { padding-top: 8px; color: var(--am-text); font-weight: 500; }
.definition-field i { color: var(--am-danger-text); font-style: normal; }
.definition-field small { display: block; margin-top: 8px; }
.definition-field input:not([type='radio']), .definition-field textarea { width: 100%; }
.destination-choices { flex-direction: column; align-items: flex-start; gap: 12px; padding: 6px 0; }
.definition-note { display: flex; gap: 8px; align-items: center; margin: 0; }
.import-splits .transfer-choices { gap: 22px; margin-top: 8px; }
.import-review-panel { padding: 0; background: transparent; border: 0; }
.import-review-summary { display: grid; grid-template-columns: minmax(0,2.1fr) minmax(0,1.45fr) repeat(3,minmax(0,.75fr)) minmax(0,1.25fr); margin-bottom: 12px; align-items: center; }
.import-review-summary > div { min-width: 0; padding-inline: clamp(10px, 1.5vw, 24px); border-inline-start: 1px solid var(--am-border); }
.import-review-summary > div:not(.review-file), .review-file > div { display: grid; gap: 6px; line-height: 1.35; }
.import-review-summary .review-file-meta { display: flex; flex-wrap: wrap; row-gap: 3px; }
.review-file-meta span + span { border-inline-start: 1px solid var(--am-border); padding-inline-start: 8px; margin-inline-start: 8px; }
.import-review-summary > div:first-child { padding-left: 0; border: 0; }
@media (min-width: 1280px) {
  .import-review-summary { grid-template-columns: minmax(0,1.95fr) minmax(0,1.65fr) repeat(3,minmax(0,.75fr)) minmax(0,1.2fr); }
}
.import-review-summary strong, .import-review-summary small { display: block; }
.import-review-summary strong { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.review-file { display: flex; align-items: center; gap: 10px; }
.review-file svg { flex: none; }
.review-file > div { min-width: 0; }
.import-review-summary > div:nth-child(n+3) strong { font-size: 19px; font-variant-numeric: tabular-nums; }
.import-review-summary > div:last-child strong { font-size: 16px; white-space: normal; }
.import-review-summary strong { font-size: 16px; font-weight: 550; }
.import-review-summary svg { vertical-align: middle; margin-right: 5px; }
.import-review-summary small { color: var(--am-text-muted); }
.import-review-panel :deep(.transfer-review) { gap: 12px; }
.import-review-panel :deep(.transfer-review section) { min-width: 0; }
.import-review-panel :deep(.transfer-files summary) { background: transparent; }
@media (min-width: 1024px) {
  .import-review-panel :deep(details.import-file-tree:not([open])) { padding: 0; }
}
.import-review-panel :deep(.dataset-table td:last-child) { white-space: normal; }
.import-blocked { display: flex; align-items: center; gap: 12px; padding: 12px; background: var(--am-danger-surface); color: var(--am-danger-text); }
.import-blocked button:first-of-type { margin-left: auto; }
.import-stat-heading { margin-top: 20px !important; }
.import-statistics { margin: 0; display: grid; gap: 2px; }
.import-statistics dt { color: var(--am-text-muted); }
.import-statistics div { display: grid; grid-template-columns: 28% 20% minmax(0,1fr); gap: 8px; padding: 4px 8px; }
.import-statistics .stat-detail { color: var(--am-text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.import-statistics dd { margin: 0; overflow-wrap: anywhere; }
@media (max-width: 1099px), (max-height: 779px) {
  .import-statistics { grid-template-columns: 1fr 1fr; grid-template-rows: repeat(3,auto); grid-auto-flow: column; column-gap: 14px; }
  .import-statistics div { grid-template-columns: minmax(88px, 32%) minmax(0,1fr); }
  .import-statistics .stat-detail { display: none; }
  .import-review-panel :deep(.transfer-files:not([open])) { padding-block: 8px; }
}

.import-workspace :deep(thead th) { background: var(--am-page); }
.import-workspace .dataset-table th, .import-workspace .dataset-table td { font-size: 14px; }
.import-workspace .definition-field :disabled { background: var(--am-surface-muted); }
.import-workspace .dataset-wizard-footer { z-index: 3; }
.import-review-panel :deep(.transfer-files nav button) { background: transparent; border: 0; font: inherit; }
.import-review-panel :deep(.transfer-files nav button:hover) { background: var(--am-hover-surface); }
.import-review-panel :deep(.transfer-files nav > *) { font-size: 14px; padding-block: 6px; }
.import-workspace :deep(.dataset-table th), .import-workspace :deep(.dataset-table td) { padding: 7px 10px; }
.import-workspace :deep(.mapping-target input) { min-height: 30px; padding-block: 3px; }
.import-statistics dd { min-width: 0; max-height: 5em; overflow: auto; }

.export-panel { display: block; }
.export-panel .dataset-wizard-fields { padding: 0; margin: 0; gap: 14px; }
.source-choice { margin: 0; }
.export-source-value, .source-choice small { display: flex; align-items: center; gap: 8px; }
.source-choice small, .wizard-note small { color: var(--am-text-muted); font-size: var(--am-type-caption); margin-top: 5px; }
.wizard-note small { display: block; }
.transfer-workspace .source-symbol { box-sizing: content-box; flex: none; padding: 8px; border-radius: var(--am-radius-sm); background: var(--am-surface); }
.export-panel > .transfer-summary { background: var(--am-page); gap: 10px; }
.export-panel > .transfer-summary:not(.source-choice) > span { font-weight: 500; }
.transfer-workspace:not(.import-workspace) .dataset-steps li:not(.is-active, .is-complete) > span { background: var(--am-surface-muted); border-color: transparent; }
.export-panel .format-option { padding: 11px 16px; }
.export-panel .format-option small { margin-top: 4px; color: var(--am-text-muted); }
.step-copy { min-width: 0; }
.step-copy small { display: block; font-weight: 400; font-size: 12px; color: var(--am-text-muted); overflow: hidden; white-space: nowrap; text-overflow: ellipsis; margin-top: 3px; max-width: 12em; }
.export-panel .export-source-picker.field { grid-template-columns: minmax(0, 520px); }
.export-review-summary { background: var(--am-surface); border: 1px solid var(--am-border); }
.export-target { margin-inline-start: auto; }
.export-panel thead th, .import-review-panel :deep(thead th) { background: var(--am-page); }
.export-panel .field:has(> input[maxlength="180"]) { display: grid; grid-template-columns: 1fr; gap: 6px; }
.export-panel .dataset-table th, .export-panel .dataset-table td { padding: 8px 12px; }
.export-panel + .dataset-wizard-footer, .import-review-panel + .dataset-wizard-footer { margin-top: 0; border: 0; background: var(--am-page); padding: 10px 0; }
.export-panel + .dataset-wizard-footer button, .import-review-panel + .dataset-wizard-footer button { min-width: 100px; }
.export-review-bottom { display: grid; gap: 16px; margin-top: 18px; }
.export-metrics { display: flex; flex-wrap: wrap; gap: 12px 24px; margin: 0; }
.export-metrics dt { color: var(--am-text-muted); font-size: 13px; }
.export-metrics dd { margin: 4px 0 0; font-size: 16px; }
.export-review-bottom h3 { margin: 0 0 10px; font-size: 15px; }
.transfer-workspace:not(.import-workspace) .dataset-steps { background: var(--am-surface); border: 1px solid var(--am-border); padding: 14px 18px; border-radius: var(--am-radius-md); }
@media (min-width: 1100px) and (min-height: 780px) {
  .transfer-workspace { gap: clamp(16px, 2vh, 24px); }
  .import-workspace .dataset-wizard-fields, .export-panel .dataset-wizard-fields { gap: 16px; }
  .import-review-panel :deep(.transfer-review > section), .import-review-panel :deep(.transfer-files), .export-panel { padding: clamp(18px, 1.6vw, 26px); }
  .import-review-panel :deep(.check-table td) { padding-block: 11px; }
  .import-statistics div { padding-block: 7px; }
  .import-review-summary { padding-block: 18px; }
  .import-workspace .split-table td { padding-block: 8px; }

  .export-panel .dataset-wizard-fields { gap: 22px; }

  .export-panel .source-choice { margin-top: auto; }
  .export-panel .format-option { padding: 16px 20px; }
  .export-panel .dataset-table td { padding-block: 12px; }
  .transfer-workspace .dataset-steps .step-copy { font-size: 15px; }
}
@media (max-height: 779px), (max-width: 1099px) {
  .export-review-bottom { grid-template-columns: repeat(2,minmax(0,1fr)); }
}

/* 主面板和页脚共用可用高度，表单内部按内容排布；长数据自然向下延伸。 */
.transfer-workspace { min-height: min(calc(100dvh - 44px), max(640px, 70vw)); }
.transfer-workspace .dataset-wizard { flex: 1; gap: clamp(10px,1.4vh,16px); }
.transfer-workspace .dataset-wizard > div:first-child { flex: 1; }
.transfer-workspace .dataset-wizard-footer { flex: none; padding: 8px 0 0; }
.transfer-workspace .dataset-wizard-footer button { min-width: 104px; }
.transfer-workspace .dataset-wizard-footer button[type=submit] { min-width: 128px; }
.transfer-workspace .dataset-steps li > span { width: 34px; height: 34px; flex: none; }
.transfer-workspace .dataset-steps .step-copy { flex: none; max-width: 65%; }
.import-workspace:has(.dataset-wizard[data-step="3"]) .dataset-steps li.is-complete > span { color: var(--am-brand-primary); background: var(--am-surface); }
.transfer-workspace .dataset-wizard[data-step="3"] > div:first-child { display: flex; flex-direction: column; }
.transfer-workspace .dataset-wizard[data-step="3"] .dataset-wizard-fields, .transfer-workspace .dataset-wizard-fields > :deep(.transfer-review) { flex: 1; }
.export-panel { display: flex; flex-direction: column; }
.export-panel > .dataset-wizard-fields { flex: 1; }
.export-panel .source-choice, .export-panel .wizard-note { margin-top: auto; margin-bottom: 0; }
.wizard-note, .compatibility-reason { padding: 12px 16px; border-radius: var(--am-radius-sm); }
.wizard-note { display: flex; align-items: center; gap: 10px; background: var(--am-page); color: var(--am-text-muted); }
.compatibility-reason { margin-top: 14px; background: var(--am-danger-surface); color: var(--am-danger-text); }
.compatibility-reason p { margin: 5px 0 0; }
.export-route { display: grid; grid-template-columns: auto minmax(0,1fr) auto auto minmax(0,1fr); gap: 14px; align-items: center; padding: 14px 20px; border-radius: var(--am-radius-md); margin-bottom: 12px; }
.export-route strong,.export-route small { display: block; overflow-wrap: anywhere; }
.export-route small { color: var(--am-text-muted); margin-top: 4px; }
.export-route > svg { color: var(--am-text-muted); }
.transfer-workspace .export-review-bottom .export-metrics { display: grid; grid-template-columns: repeat(auto-fit,minmax(70px,1fr)); gap: 8px; }
.export-review-bottom .export-metrics dd { font-size: 19px; font-weight: 600; }
.export-panel .format-option.chosen { background: color-mix(in srgb, var(--am-brand-primary) 5%, var(--am-surface)); }
@media (min-width:1100px) and (min-height:780px) {
  .import-workspace .dataset-wizard[data-step="1"] .dataset-wizard-fields { gap: clamp(18px,2.7vh,30px); padding-block: 12px; }
  .import-workspace .dataset-wizard[data-step="2"] .dataset-wizard-fields { gap: 18px; }
  .import-workspace .import-file-summary { padding-block: 15px; margin-bottom: 20px; }
  .transfer-workspace:not(.import-workspace) .dataset-steps { padding-block: 16px; }
  .transfer-workspace .step-copy small { max-width: 100%; }
  .export-panel .export-source-picker.field { grid-template-columns: minmax(0,50%); }
}
@media (max-width:1099px), (max-height:779px) {
  .export-review-bottom { gap: 12px; }
  .transfer-review--export > .export-review-bottom { margin: 0; grid-template-columns: minmax(0,1fr) minmax(0,1.12fr); }
  .transfer-review--export > .export-review-bottom > section { min-width: 0; padding: 12px; border: 1px solid var(--am-border); background: var(--am-surface); border-radius: var(--am-radius-md); }
  .transfer-workspace:not(.import-workspace) .dataset-wizard[data-step="3"] .import-review-panel :deep(.check-table td) { padding-block: 6px; }
  .transfer-workspace .export-review-bottom .export-metrics { grid-template-columns: repeat(5,minmax(0,1fr)); gap: 0; }
  .export-review-bottom .export-metrics > div { padding-inline: 5px; border-inline-start: 1px solid var(--am-border); }
  .export-review-bottom .export-metrics > div:first-child { border: 0; }
  .export-review-bottom .export-metrics dt { font-size: var(--am-type-caption); }
  .export-review-bottom .export-metrics dd { font-size: 16px; }
  .transfer-workspace .export-review-bottom .dataset-table th, .transfer-workspace .export-review-bottom .dataset-table td { padding: 5px 6px; }
  .transfer-workspace .dataset-wizard-footer { background: var(--am-surface); border-radius: var(--am-radius-sm); padding: 8px 12px; }
  .transfer-workspace:not(.import-workspace):has(.dataset-wizard[data-step="3"]) { gap: 9px; }
  .transfer-workspace:not(.import-workspace) .dataset-wizard[data-step="3"] .dataset-wizard-footer { position: static; }
  .transfer-workspace:not(.import-workspace) .dataset-wizard[data-step="3"] .dataset-wizard-fields { padding-bottom: 0; }
  .export-route { padding-block: 9px; margin-bottom: 8px; }
  .import-review-panel :deep(.transfer-review--export > section) { padding: 12px; }
  .import-review-panel :deep(.transfer-review--export > .transfer-files:not([open])) { padding: 3px 12px; }
  .import-review-panel :deep(.transfer-review--export .check-table th) { padding-block: 6px; }
  .import-review-panel :deep(.transfer-review--export .check-table td) { height: auto; }
  .transfer-review--export .export-mapping-table th:first-child { width: 40%; }
  .transfer-review--export .export-mapping-table th:nth-child(2) { width: 15%; }
  .export-review-bottom > section h3 { margin-bottom: 6px; }
}

.dataset-table td > .mapped-state { display: inline-flex; align-items: center; gap: 6px; color: var(--am-success-text); }
.mapped-state svg { fill: var(--am-brand-primary); stroke: white; }
@media (min-width:1280px) and (min-height:780px) {
  .transfer-workspace .dataset-title { font-size: clamp(20px,1.45vw,25px); }
  .transfer-workspace :deep(.dataset-table td), .transfer-workspace :deep(.dataset-table th), .transfer-workspace :deep(.transfer-files nav > *), .transfer-workspace .format-option { font-size: clamp(14px,1.02vw,17px); }
  .transfer-workspace .dataset-wizard h2, .transfer-workspace :deep(.transfer-review h3) { font-size: clamp(17px,1.18vw,20px); }
  .transfer-workspace .dataset-steps li > span { width: clamp(34px,2.65vw,44px); height: clamp(34px,2.65vw,44px); }
  .transfer-workspace .dataset-wizard-footer button { min-width: clamp(108px,8.5vw,144px); min-height: 42px; }
  .transfer-workspace .dataset-wizard-footer button[type=submit] { min-width: clamp(136px,10.3vw,174px); }
  .import-upload-panel .import-file-heading { margin-top: 14px; }
  .import-upload-panel .import-upload-table td { padding-block: 16px; }
  .export-panel .export-source-picker.field > span { font-size: 16px; }
  .transfer-workspace .export-panel { display: flex; }
}
</style>
