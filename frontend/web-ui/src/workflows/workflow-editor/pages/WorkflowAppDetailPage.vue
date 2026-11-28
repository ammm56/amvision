<template>
  <section class="app-detail-page">
    <header class="app-detail-header">
      <div class="app-detail-header__left">
        <button
          type="button"
          class="app-back-btn"
          aria-label="返回应用列表"
          title="返回应用列表"
          @click="openAppList"
        >
          <ArrowLeft :size="16" />
        </button>
        <div class="app-detail-title-wrap">
          <h1>{{ application?.display_name || applicationId }}</h1>
          <span class="app-ver-pill" :class="latestVersion ? 'is-published' : 'is-draft'">
            {{ latestVersion ? `最新发布 ${latestVersion.display_version}` : '未发布' }}
          </span>
        </div>
      </div>

      <div class="app-detail-header__right">
        <Button variant="secondary" :disabled="!application" @click="openGraphEditor()">
          <Workflow :size="15" />
          编辑流程
        </button>
        <Button variant="secondary" :disabled="!application" data-app-detail-info-btn @click="openInfoDrawer(false)">
          应用信息
        </Button>
        <button
          type="button"
          class="app-icon-menu-btn"
          aria-label="更多应用操作"
          data-app-detail-more-btn
          :disabled="!application"
          @click.stop="toggleMenu($event, 'header')"
        >
          <MoreHorizontal :size="16" />
        </button>
      </div>
    </header>

    <InlineError :message="errorMessage" />

    <div v-if="!loading && !workflowApp" class="app-detail-card">
      <EmptyState
        :title="t('workflowEditor.appDetail.emptyAppTitle')"
        :description="t('workflowEditor.appDetail.emptyAppDescription')"
      />
    </div>

    <template v-else-if="workflowApp">
      <TabList
        :model-value="activeTab"
        :tabs="detailTabs"
        label="应用详情标签页"
        variant="underline"
        @update:model-value="selectTab"
      />

      <!-- Tab 1: 运行实例 -->
      <div v-if="activeTab === 'runtimes'" class="app-tab-stack">
        <section class="app-detail-card">
          <div class="app-card-toolbar app-card-toolbar--end">
            <div class="app-card-toolbar__actions">
              <Button
                variant="secondary"
                size="sm"
                :disabled="!selectedRuntime"
                @click="selectedRuntime && openRuntimeAppMode(selectedRuntime)"
              >
                <MousePointer2 :size="14" />
                应用模式
              </Button>
              <Button
                variant="secondary"
                size="sm"
                :disabled="!selectedRuntime"
                @click="selectedRuntime && openRuntimeMonitor(selectedRuntime)"
              >
                <Activity :size="14" />
                运行监视
              </Button>
              <Button
                v-if="canWriteWorkflows"
                variant="primary"
                size="sm"
                :disabled="isRuntimeBusy() || publishedVersions.length === 0"
                :title="publishedVersions.length === 0 ? '请先在流程编辑器发布至少一个版本' : '创建运行实例'"
                data-app-create-runtime-btn
                @click="openRuntimeCreateDialog"
              >
                <Plus :size="14" />
                创建实例
              </Button>
            </div>
          </div>

          <div v-if="runtimes.length === 0" class="app-empty-block">
            <p>暂无运行实例</p>
          </div>

          <div v-else class="app-table-wrap">
            <table class="app-table">
              <thead>
                <tr>
                  <th>实例名称</th>
                  <th>运行版本</th>
                  <th>状态</th>
                  <th>触发入口</th>
                  <th>最近心跳</th>
                  <th class="col-actions">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="rt in runtimes"
                  :key="rt.workflow_runtime_id"
                  :class="{ 'is-selected': selectedRuntimeId === rt.workflow_runtime_id }"
                  @click="selectRuntime(rt.workflow_runtime_id)"
                >
                  <td>
                    <div class="app-cell-main">
                      <strong>{{ rt.display_name || rt.workflow_runtime_id }}</strong>
                      <small v-if="rt.last_error" class="app-err-hint" :title="rt.last_error">{{ rt.last_error }}</small>
                    </div>
                  </td>
                  <td class="app-nowrap">{{ runtimeVersionLabel(rt) }}</td>
                  <td>
                    <span class="app-rt-pill" :class="`is-${runtimeDotTone(rt.observed_state)}`">
                      <i class="app-dot" />
                      {{ formatRuntimeStateLabel(rt.observed_state) }}
                    </span>
                  </td>
                  <td class="app-num">{{ runtimeTriggerSourceCount(rt) }}</td>
                  <td class="app-muted app-nowrap">{{ rt.heartbeat_at ? formatSystemDateTime(rt.heartbeat_at) : '—' }}</td>
                  <td class="col-actions" @click.stop>
                    <div class="app-row-actions">
                      <button
                        type="button"
                        class="app-link-btn"
                        @click="openRuntimeDetails(rt, 'overview')"
                      >
                        详情
                      </button>
                      <button
                        v-if="canWriteWorkflows && canStartRuntime(rt)"
                        type="button"
                        class="app-link-btn"
                        :disabled="isRuntimeBusy()"
                        @click="controlRuntime(rt, 'start')"
                      >
                        启动
                      </button>
                      <button
                        v-else-if="canWriteWorkflows && canStopRuntime(rt)"
                        type="button"
                        class="app-link-btn is-danger"
                        :disabled="isRuntimeBusy()"
                        @click="controlRuntime(rt, 'stop')"
                      >
                        {{ runtimeStopActionLabel(rt) }}
                      </button>
                      <button
                        type="button"
                        class="app-more-btn"
                        :aria-label="`实例 ${rt.display_name || rt.workflow_runtime_id} 更多操作`"
                        @click.stop="toggleMenu($event, `rt:${rt.workflow_runtime_id}`)"
                      >
                        <MoreHorizontal :size="16" />
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="app-detail-card">
          <div class="app-card-toolbar">
            <div class="app-current-runtime">
              <strong>关联触发入口</strong>
            </div>
            <Button
              v-if="canWriteWorkflows"
              variant="secondary"
              size="sm"
              :disabled="!selectedRuntime"
              @click="openSelectedRuntimeTriggerSource"
            >
              <Plus :size="14" />
              添加触发入口
            </Button>
          </div>

          <div v-if="!selectedRuntime" class="app-empty-block">
            <p>未选择运行实例</p>
          </div>

          <div v-else-if="selectedRuntimeTriggerSources.length === 0" class="app-empty-block">
            <p>暂无关联触发入口</p>
          </div>

          <div v-else class="app-table-wrap">
            <table class="app-table">
              <thead>
                <tr>
                  <th>名称</th>
                  <th>类型</th>
                  <th>状态</th>
                  <th>最近触发</th>
                  <th class="col-actions">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="src in selectedRuntimeTriggerSources" :key="src.trigger_source_id">
                  <td><strong>{{ src.display_name || src.trigger_source_id }}</strong></td>
                  <td class="app-muted">{{ src.trigger_kind }}</td>
                  <td>
                    <span class="app-rt-pill" :class="`is-${triggerDotTone(src)}`">
                      <i class="app-dot" />
                      {{ formatTriggerStateLabel(src) }}
                    </span>
                  </td>
                  <td class="app-muted app-nowrap">{{ src.updated_at ? formatSystemDateTime(src.updated_at) : '—' }}</td>
                  <td class="col-actions">
                    <div class="app-row-actions">
                      <RouterLink class="app-link-btn" :to="triggerSourceItemPath(src, 'config')">
                        配置
                      </RouterLink>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <!-- Tab 2: 发布版本 -->
      <div v-else-if="activeTab === 'versions'" class="app-tab-stack">
        <section class="app-detail-card">
          <div class="app-card-toolbar">
            <div class="app-toolbar-filters">
              <SelectField
                fit-options
                floating
                :model-value="versionStateFilter"
                :options="versionStateOptions"
                aria-label="按版本状态筛选"
                @update:model-value="onVersionFilterChange"
              />
            </div>

            <div class="app-card-toolbar__actions">
              <Button variant="secondary" size="sm" :disabled="loading" @click="loadPage">
                <RefreshCw :size="14" />
                刷新
              </Button>
              <Button variant="primary" size="sm" @click="openGraphEditor()">
                前往图编辑发布
              </Button>
            </div>
          </div>

          <div v-if="filteredVersions.length === 0" class="app-empty-block">
            <p>暂无发布版本</p>
          </div>

          <template v-else>
            <div class="app-table-wrap">
              <table class="app-table">
                <thead>
                  <tr>
                    <th>版本</th>
                    <th>状态</th>
                    <th>版本说明</th>
                    <th>发布时间</th>
                    <th>引用实例</th>
                    <th class="col-actions-wide">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="ver in pagedVersions" :key="ver.workflow_app_version_id">
                    <td class="app-nowrap">
                      <div class="app-ver-cell">
                        <strong>{{ ver.display_version }}</strong>
                        <span
                          v-if="latestVersion && latestVersion.workflow_app_version_id === ver.workflow_app_version_id"
                          class="app-latest-tag"
                        >
                          最新
                        </span>
                      </div>
                    </td>
                    <td>
                      <span class="app-state-pill" :class="ver.state === 'published' ? 'is-ok' : 'is-neutral'">
                        {{ ver.state === 'published' ? '已发布' : ver.state === 'archived' ? '已归档' : ver.state }}
                      </span>
                    </td>
                    <td class="app-muted app-note-cell">{{ ver.release_notes || '—' }}</td>
                    <td class="app-muted app-nowrap">{{ formatSystemDateTime(ver.completed_at || ver.created_at) }}</td>
                    <td class="app-num">{{ versionReferencingRuntimes(ver.workflow_app_version_id).length }}</td>
                    <td class="col-actions-wide" @click.stop>
                      <div class="app-row-actions">
                        <button
                          type="button"
                          class="app-link-btn"
                          @click="openVersionDetail(ver)"
                        >
                          查看
                        </button>
                        <button
                          type="button"
                          class="app-link-btn"
                          @click="openVersionCompare(ver.workflow_app_version_id, 'draft')"
                        >
                          与草稿比较
                        </button>
                        <button
                          type="button"
                          class="app-more-btn"
                          :aria-label="`版本 ${ver.display_version} 更多操作`"
                          @click.stop="toggleMenu($event, `ver:${ver.workflow_app_version_id}`)"
                        >
                          <MoreHorizontal :size="16" />
                        </button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div class="app-card-pagination">
              <PaginationControls
                numbered
                :offset="versionOffset"
                :limit="versionLimit"
                :item-count="pagedVersions.length"
                :total-count="filteredVersions.length"
                @previous="versionOffset = Math.max(0, versionOffset - versionLimit)"
                @next="versionOffset = versionOffset + versionLimit"
                @go="(nextOffset) => (versionOffset = nextOffset)"
              />
              <Button
                v-if="workflowApp.versionPagination.hasMore"
                variant="secondary"
                size="sm"
                :disabled="loadingMoreVersions"
                :loading="loadingMoreVersions"
                @click="loadMoreVersions"
              >
                加载更多历史版本
              </Button>
            </div>
          </template>
        </section>
      </div>

      <!-- Tab 3: 输入输出 -->
      <div v-else-if="activeTab === 'io'" class="app-tab-stack">
        <section class="app-detail-card">
          <div class="app-card-toolbar">
            <div class="app-io-toolbar-left">
              <span class="app-filter-label">查看版本</span>
              <SelectField
                fit-options
                floating
                :model-value="selectedIoVersionKey"
                :options="ioVersionOptions"
                aria-label="选择查看接口的版本"
                @update:model-value="selectIoVersion"
              />
              <span class="app-io-count-pill">输入 {{ ioInputs.length }} · 输出 {{ ioOutputs.length }}</span>
            </div>

            <Button variant="secondary" size="sm" :disabled="ioLoading" @click="copyIoContractJson">
              <Copy :size="14" />
              {{ ioCopyFeedback || '复制 JSON' }}
            </Button>
          </div>
          <InlineError :message="ioError" />
          <div v-if="ioLoading" class="app-empty-block">
            <span>加载中...</span>
          </div>
        </section>

        <section class="app-detail-card">
          <div class="app-card-subhead">
            <h3>输入 ({{ ioInputs.length }})</h3>
          </div>
          <div v-if="ioInputs.length === 0" class="app-empty-block">
            <span>暂无输入参数</span>
          </div>
          <div v-else class="app-table-wrap">
            <table class="app-table">
              <thead>
                <tr>
                  <th>业务名</th>
                  <th>绑定 ID</th>
                  <th>类型</th>
                  <th>是否必填</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in ioInputs" :key="`in-${row.bindingId}`">
                  <td><strong>{{ row.displayName }}</strong></td>
                  <td>
                    <div class="app-mono-copy-inline">
                      <code>{{ row.bindingId }}</code>
                      <button
                        type="button"
                        class="app-copy-mini"
                        title="复制绑定 ID"
                        @click="copyText(row.bindingId)"
                      >
                        <Copy :size="12" />
                      </button>
                    </div>
                  </td>
                  <td><span class="app-code-pill">{{ row.payloadTypeId || '—' }}</span></td>
                  <td>
                    <span class="app-req-pill" :class="row.required ? 'is-req' : 'is-opt'">
                      {{ row.required ? '必填' : '可选' }}
                    </span>
                  </td>
                  <td class="app-muted">{{ row.description || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="app-detail-card">
          <div class="app-card-subhead">
            <h3>输出 ({{ ioOutputs.length }})</h3>
          </div>
          <div v-if="ioOutputs.length === 0" class="app-empty-block">
            <span>暂无输出字段</span>
          </div>
          <div v-else class="app-table-wrap">
            <table class="app-table">
              <thead>
                <tr>
                  <th>业务名</th>
                  <th>绑定 ID</th>
                  <th>类型</th>
                  <th>说明</th>
                  <th>结构</th>
                </tr>
              </thead>
              <tbody>
                <template v-for="row in ioOutputs" :key="`out-${row.bindingId}`">
                  <tr>
                    <td><strong>{{ row.displayName }}</strong></td>
                    <td>
                      <div class="app-mono-copy-inline">
                        <code>{{ row.bindingId }}</code>
                        <button
                          type="button"
                          class="app-copy-mini"
                          title="复制绑定 ID"
                          @click="copyText(row.bindingId)"
                        >
                          <Copy :size="12" />
                        </button>
                      </div>
                    </td>
                    <td><span class="app-code-pill">{{ row.payloadTypeId || '—' }}</span></td>
                    <td class="app-muted">{{ row.description || '—' }}</td>
                    <td class="app-nowrap">
                      <button
                        v-if="row.schemaNodes.length > 0"
                        type="button"
                        class="app-link-btn app-tree-toggle"
                        @click="toggleIoOutputExpanded(row.bindingId)"
                      >
                        <span>{{ expandedIoOutputs[row.bindingId] ? '收起结构' : '查看结构' }}</span>
                        <ChevronUp v-if="expandedIoOutputs[row.bindingId]" :size="13" />
                        <ChevronDown v-else :size="13" />
                      </button>
                      <span v-else class="app-muted">—</span>
                    </td>
                  </tr>
                  <tr v-if="expandedIoOutputs[row.bindingId] && row.schemaNodes.length > 0" class="app-schema-row">
                    <td colspan="5">
                      <div class="app-schema-tree">
                        <div
                          v-for="node in row.schemaNodes"
                          :key="node.path"
                          class="app-schema-node"
                          :style="{ paddingLeft: `${12 + node.depth * 20}px` }"
                        >
                          <span class="app-schema-name">{{ node.name }}</span>
                          <span class="app-schema-type">{{ node.type }}</span>
                          <span v-if="node.required" class="app-schema-req">必填</span>
                          <span v-if="node.description" class="app-schema-desc">{{ node.description }}</span>
                        </div>
                      </div>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <!-- Tab 4: 调用调试 -->
      <WorkflowAppInvokePanel
        v-else-if="activeTab === 'invoke'"
        :project-id="selectedProjectId"
        :application-id="applicationId"
        :application="application"
        :graph="graph"
        :runtimes="runtimes"
        :selected-runtime-id="selectedRuntimeId"
        :selected-runtime-version-label="selectedRuntime ? runtimeVersionLabel(selectedRuntime) : '—'"
        :contract="selectedRuntimeContract"
        :can-write="canWriteWorkflows"
        :request-examples="requestExamples"
        @select-runtime="selectRuntime"
        @open-examples="requestExamplesDrawerOpen = true"
        @open-runtime-config="openRuntimeConfigFromChild"
        @open-runtime-details="(rt) => openRuntimeDetails(rt, 'overview')"
        @view-run-record="(run) => (inspectedRun = run)"
        @run-completed="handleInvokeCompleted"
      />

      <!-- Tab 5: 执行记录 -->
      <WorkflowAppRunsTab
        v-else-if="activeTab === 'runs'"
        ref="runsTabRef"
        :project-id="selectedProjectId"
        :application-id="applicationId"
        :runtimes="runtimes"
        :versions="versions"
        :selected-run-id="inspectedRun?.workflow_run_id ?? null"
        @inspect-run="(run) => (inspectedRun = run)"
        @open-runtime-config="openRuntimeConfigFromChild"
      />
    </template>

    <!-- Floating Row/Header Action Menu -->
    <div
      v-if="openMenuKey"
      class="app-row-menu"
      :style="menuStyle"
      role="menu"
      @click.stop
    >
      <template v-if="openMenuKey === 'header'">
        <button
          v-if="canWriteWorkflows"
          type="button"
          class="app-row-menu__item"
          role="menuitem"
          @click="openInfoDrawer(true)"
        >
          编辑信息
        </button>
        <button
          v-if="canWriteWorkflows"
          type="button"
          class="app-row-menu__item"
          role="menuitem"
          @click="openCopyDialog"
        >
          复制应用
        </button>
        <button
          v-if="canWriteWorkflows"
          type="button"
          class="app-row-menu__item is-danger"
          role="menuitem"
          @click="requestDeleteApplication"
        >
          删除应用
        </button>
      </template>

      <template v-else-if="menuRuntime">
        <button
          v-if="canWriteWorkflows"
          type="button"
          class="app-row-menu__item"
          role="menuitem"
          :disabled="!canEditRuntimeConfig(menuRuntime)"
          :title="editRuntimeConfigTitle(menuRuntime)"
          @click="openEditConfigDialog(menuRuntime)"
        >
          编辑配置
        </button>
        <button
          v-if="canWriteWorkflows"
          type="button"
          class="app-row-menu__item"
          role="menuitem"
          :disabled="!canRestartRuntime(menuRuntime)"
          :title="restartRuntimeTitle(menuRuntime)"
          @click="menuControlRuntime(menuRuntime, 'restart')"
        >
          重启
        </button>
        <button
          v-if="canWriteWorkflows"
          type="button"
          class="app-row-menu__item"
          role="menuitem"
          :disabled="!canOpenRuntimeVersionDialog(menuRuntime)"
          :title="runtimeVersionActionTitle(menuRuntime)"
          @click="menuOpenVersionDialog(menuRuntime)"
        >
          切换版本
        </button>
        <button
          v-if="canWriteWorkflows"
          type="button"
          class="app-row-menu__item is-danger"
          role="menuitem"
          :disabled="!canDeleteRuntime(menuRuntime)"
          :title="deleteRuntimeTitle(menuRuntime)"
          @click="menuRequestDeleteRuntime(menuRuntime)"
        >
          删除实例
        </button>
      </template>

      <template v-else-if="menuVersion">
        <button
          type="button"
          class="app-row-menu__item"
          role="menuitem"
          @click="openVersionCompare(menuVersion.workflow_app_version_id, versions.find(v => v.workflow_app_version_id !== menuVersion?.workflow_app_version_id)?.workflow_app_version_id || 'draft')"
        >
          版本对比
        </button>
        <button
          type="button"
          class="app-row-menu__item"
          role="menuitem"
          @click="loadVersionIntoEditor(menuVersion.workflow_app_version_id)"
        >
          载入图编辑
        </button>
        <button
          v-if="canWriteWorkflows"
          type="button"
          class="app-row-menu__item"
          role="menuitem"
          :disabled="changingVersionStateId !== null"
          @click="menuChangeVersionState(menuVersion)"
        >
          {{ menuVersion.state === 'published' ? '归档版本' : '恢复发布' }}
        </button>
        <button
          v-if="canWriteWorkflows"
          type="button"
          class="app-row-menu__item is-danger"
          role="menuitem"
          :disabled="versionReferencingRuntimes(menuVersion.workflow_app_version_id).length > 0"
          :title="versionReferencingRuntimes(menuVersion.workflow_app_version_id).length > 0 ? '仍有运行实例引用该版本，无法删除' : '删除版本'"
          @click="menuRequestDeleteVersion(menuVersion)"
        >
          删除版本
        </button>
      </template>
    </div>

    <!-- Drawers & Dialogs -->
    <WorkflowAppInfoDrawer
      :open="infoDrawerOpen"
      :project-id="selectedProjectId"
      :project-name="selectedProjectName"
      :app-summary="appSummaryForDrawer"
      :initial-editing="infoInitialEditing"
      :can-write="canWriteWorkflows"
      @close="infoDrawerOpen = false"
      @updated="handleAppUpdated"
    />

    <WorkflowAppCopyDialog
      :open="copyDialogOpen"
      :project-id="selectedProjectId"
      :source-app="appSummaryForDrawer"
      @close="copyDialogOpen = false"
      @copied="handleAppCopied"
    />

    <WorkflowRuntimeCreateDialog
      :open="runtimeCreateDialogOpen"
      :busy="busyRuntimeId === 'new'"
      :app-name="application?.display_name || applicationId"
      :default-version-id="latestVersion?.workflow_app_version_id || ''"
      :version-options="runtimeVersionOptions"
      :error-message="runtimeDialogError"
      @cancel="closeRuntimeCreateDialog"
      @create="createRuntime"
    />

    <WorkflowRuntimeEditConfigDialog
      :open="editConfigRuntime !== null"
      :app-name="application?.display_name || applicationId"
      :version-label="editConfigRuntime ? runtimeVersionLabel(editConfigRuntime) : '—'"
      :runtime="editConfigRuntime"
      @cancel="editConfigRuntime = null"
      @saved="handleRuntimeConfigSaved"
    />

    <WorkflowRuntimeVersionDialog
      :open="runtimeVersionDialogRuntime !== null"
      :busy="Boolean(runtimeVersionDialogRuntime && busyRuntimeId === runtimeVersionDialogRuntime.workflow_runtime_id)"
      :confirm-disabled="!runtimeVersionDialogRuntime || !canSwitchRuntimeVersion(runtimeVersionDialogRuntime)"
      :current-version-label="runtimeVersionDialogCurrentLabel"
      :target-version-id="runtimeTargetVersionId"
      :target-version-label="versionLabel(runtimeTargetVersionId)"
      :version-options="runtimeVersionOptions"
      :show-breaking-override="Boolean(runtimeVersionDialogRuntime && runtimeVersionDialogRuntime.active_revision_id && runtimeTargetVersionId)"
      :allow-breaking-contract="allowBreakingContract"
      :breaking-change-reason="breakingChangeReason"
      :error-message="runtimeDialogError"
      @update:target-version-id="setRuntimeTargetVersion"
      @update:allow-breaking-contract="(value) => (allowBreakingContract = value)"
      @update:breaking-change-reason="(value) => (breakingChangeReason = value)"
      @cancel="closeRuntimeVersionDialog"
      @confirm="runtimeVersionDialogRuntime && switchRuntimeVersion(runtimeVersionDialogRuntime)"
    />

    <WorkflowRuntimeDetailsDrawer
      :open="runtimeDetailsRuntime !== null"
      :runtime="runtimeDetailsRuntime"
      :application-name="application?.display_name || applicationId"
      :version-label="runtimeDetailsVersionLabel"
      :target-version-label="runtimeDetailsTargetVersionLabel"
      :trigger-source-count="runtimeDetailsRuntime ? runtimeTriggerSourceCount(runtimeDetailsRuntime) : 0"
      :can-write="canWriteWorkflows"
      :initial-tab="runtimeDetailsInitialTab"
      @close="runtimeDetailsRuntimeId = ''"
      @edit-config="(rt) => { runtimeDetailsRuntimeId = ''; openEditConfigDialog(rt) }"
      @monitor="openRuntimeMonitor"
      @refresh-health="refreshRuntimeHealth"
    />

    <WorkflowAppVersionDetailDrawer
      :open="versionDetailVersion !== null"
      :project-id="selectedProjectId"
      :application-id="applicationId"
      :version="versionDetailVersion"
      :referencing-runtimes="versionDetailVersion ? versionReferencingRuntimes(versionDetailVersion.workflow_app_version_id) : []"
      :can-write="canWriteWorkflows"
      @close="versionDetailVersionId = ''"
      @compare="(vid) => { versionDetailVersionId = ''; openVersionCompare(vid, 'draft') }"
      @load-editor="loadVersionIntoEditor"
      @updated="handleVersionUpdated"
    />

    <WorkflowAppVersionCompareDrawer
      :open="compareDrawerOpen"
      :project-id="selectedProjectId"
      :application-id="applicationId"
      :versions="versions"
      :initial-source-version-id="compareSourceVersionId"
      :initial-target-version-id="compareTargetVersionId"
      @close="compareDrawerOpen = false"
      @view-version="(vid) => { compareDrawerOpen = false; versionDetailVersionId = vid }"
    />

    <WorkflowRequestExamplesDrawer
      :open="requestExamplesDrawerOpen"
      :examples="requestExamples"
      :endpoints="requestExampleEndpoints"
      :runtime-name="selectedRuntime?.display_name || selectedRuntime?.workflow_runtime_id || ''"
      :version-label="selectedRuntime ? runtimeVersionLabel(selectedRuntime) : ''"
      @close="requestExamplesDrawerOpen = false"
    />

    <WorkflowRunDetailDrawer
      :open="inspectedRun !== null"
      :project-id="selectedProjectId"
      :application-name="application?.display_name || applicationId"
      :run="inspectedRun"
      :runtime-name="inspectedRun ? runtimeDisplayNameById(inspectedRun.workflow_runtime_id) : ''"
      :version-label="inspectedRun ? versionLabel(inspectedRun.workflow_app_version_id) : '—'"
      :can-write="canWriteWorkflows"
      :cancelling="cancellingInspectedRun"
      @close="inspectedRun = null"
      @cancel-run="handleCancelInspectedRun"
    />

    <ConfirmDialog
      v-if="pendingDeleteRuntime"
      :title="t('workflowEditor.appDetail.deleteRuntimeTitle')"
      :message="t('workflowEditor.appDetail.deleteRuntimeMessage', { runtime: pendingDeleteRuntime.display_name || pendingDeleteRuntime.workflow_runtime_id })"
      :confirm-label="t('common.actions.delete')"
      :cancel-label="t('common.cancel')"
      confirm-variant="danger"
      :busy="busyRuntimeId === pendingDeleteRuntime.workflow_runtime_id"
      @cancel="pendingDeleteRuntime = null"
      @confirm="deleteRuntime"
    />

    <ConfirmDialog
      v-if="pendingDeleteVersion"
      title="删除发布版本"
      :message="`确定删除版本“${pendingDeleteVersion.display_version}”吗？此操作不可恢复。`"
      confirm-label="删除"
      cancel-label="取消"
      confirm-variant="danger"
      :busy="deletingVersionId === pendingDeleteVersion.workflow_app_version_id"
      @cancel="pendingDeleteVersion = null"
      @confirm="confirmDeleteVersion"
    />

    <ConfirmDialog
      v-if="pendingDeleteAppOpen"
      :title="runtimes.length > 0 ? '无法删除应用' : '删除应用'"
      :message="
        runtimes.length > 0
          ? `当前应用仍有 ${runtimes.length} 个运行实例，请先删除全部运行实例后再删除应用。`
          : `确定删除应用“${application?.display_name || applicationId}”及其草稿记录吗？`
      "
      :confirm-label="runtimes.length > 0 ? '知道了' : '删除'"
      :cancel-label="runtimes.length > 0 ? '关闭' : '取消'"
      :confirm-variant="runtimes.length > 0 ? 'primary' : 'danger'"
      :busy="deletingApplication"
      @cancel="pendingDeleteAppOpen = false"
      @confirm="confirmDeleteApplication"
    />
  </section>
</template>

<script setup lang="ts">
import {
  Activity,
  ArrowLeft,
  ChevronDown,
  ChevronUp,
  Copy,
  MoreHorizontal,
  MousePointer2,
  Plus,
  RefreshCw,
  Workflow,
} from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { getErrorMessage } from '@/shared/api/error'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import { useFeedbackStore } from '@/app/stores/feedback.store'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import TabList, { type TabListItem } from '@/shared/ui/navigation/TabList.vue'
import {
  listAllWorkflowTriggerSourcesForRuntime,
  refreshWorkflowTriggerSourceStatuses,
  type WorkflowTriggerSource,
} from '@/modules/integrations/services/trigger-source.service'
import WorkflowAppCopyDialog from '../components/WorkflowAppCopyDialog.vue'
import WorkflowAppInfoDrawer from '../components/WorkflowAppInfoDrawer.vue'
import WorkflowAppInvokePanel from '../components/WorkflowAppInvokePanel.vue'
import WorkflowAppRunsTab from '../components/WorkflowAppRunsTab.vue'
import WorkflowAppVersionCompareDrawer from '../components/WorkflowAppVersionCompareDrawer.vue'
import WorkflowAppVersionDetailDrawer from '../components/WorkflowAppVersionDetailDrawer.vue'
import WorkflowRequestExamplesDrawer from '../components/WorkflowRequestExamplesDrawer.vue'
import WorkflowRunDetailDrawer from '../components/WorkflowRunDetailDrawer.vue'
import WorkflowRuntimeCreateDialog from '../components/WorkflowRuntimeCreateDialog.vue'
import WorkflowRuntimeDetailsDrawer from '../components/WorkflowRuntimeDetailsDrawer.vue'
import WorkflowRuntimeEditConfigDialog from '../components/WorkflowRuntimeEditConfigDialog.vue'
import WorkflowRuntimeVersionDialog from '../components/WorkflowRuntimeVersionDialog.vue'
import { useWorkflowResourceStream } from '../composables/useWorkflowResourceStream'
import {
  buildRuntimeVersionSelectionInput,
  canSelectWorkflowRuntimeVersion,
  selectRuntimeCandidateVersions,
} from '../runtime-version-selection'
import {
  getWorkflowApp,
  resolveLatestPublishedVersion,
  type WorkflowAppDocument,
  type WorkflowAppSummary,
} from '../services/workflow-app.service'
import {
  compareWorkflowAppVersionToDraft,
  deleteWorkflowApplication,
  deleteWorkflowAppVersion,
  getWorkflowAppVersion,
  listWorkflowAppVersions,
  transitionWorkflowAppVersionState,
  type WorkflowAppVersionStateTransition,
} from '../services/workflow-application.service'
import {
  cancelWorkflowRun,
  createWorkflowAppRuntime,
  deleteWorkflowAppRuntime,
  getWorkflowAppRuntimeHealth,
  getWorkflowRuntimeRevision,
  refreshWorkflowAppRuntimeStatuses,
  restartWorkflowAppRuntime,
  selectWorkflowAppRuntimeVersion,
  startWorkflowAppRuntime,
  stopWorkflowAppRuntime,
} from '../services/workflow-runtime.service'
import type {
  FlowApplicationBinding,
  WorkflowAppRuntime,
  WorkflowAppVersion,
  WorkflowAppVersionComparison,
  WorkflowAppVersionDetail,
  WorkflowJsonObject,
  WorkflowRun,
  WorkflowRuntimeRevision,
} from '../types'
import { buildWorkflowAppRequestExamples } from '../workflow-app-request-examples'

type DetailTabId = 'runtimes' | 'versions' | 'io' | 'invoke' | 'runs'
type RuntimeControlAction = 'start' | 'stop' | 'restart'
type WorkflowRunRecordMode = 'full' | 'minimal' | 'none'
type SelectValue = string | number | boolean | null

interface SelectOption {
  label: string
  value: SelectValue
  description?: string
}

interface WorkflowRuntimeCreateDialogValue {
  displayName?: string
  workflowAppVersionId: string
  workflowRunRecordMode: WorkflowRunRecordMode
  returnDiagnostics: boolean
  requestTimeoutSeconds: number | null
}

interface SchemaTreeNode {
  path: string
  name: string
  type: string
  required: boolean
  description: string
  depth: number
}

interface IoContractRow {
  bindingId: string
  displayName: string
  payloadTypeId: string
  required: boolean
  description: string
  schemaNodes: SchemaTreeNode[]
}

const VALID_TABS: readonly DetailTabId[] = ['runtimes', 'versions', 'io', 'invoke', 'runs']

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const projectStore = useProjectStore()
const sessionStore = useSessionStore()

const selectedProjectId = computed(() => projectStore.selectedProjectId || '')
const selectedProjectName = computed(
  () =>
    projectStore.projects.find((p) => p.project_id === selectedProjectId.value)?.display_name
    || selectedProjectId.value
    || '—',
)
const applicationId = computed(() => String(route.params.applicationId ?? ''))
const canWriteWorkflows = computed(() => sessionStore.hasScopes(['workflows:write']))

function resolveInitialTab(): DetailTabId {
  const raw = typeof route.query.tab === 'string' ? route.query.tab : ''
  return (VALID_TABS as readonly string[]).includes(raw) ? (raw as DetailTabId) : 'runtimes'
}

const activeTab = ref<DetailTabId>(resolveInitialTab())
const workflowApp = ref<WorkflowAppDocument | null>(null)
const latestVersionDetail = ref<WorkflowAppVersionDetail | null>(null)
const versionDetailsById = ref<Record<string, WorkflowAppVersionDetail>>({})
const triggerSources = ref<WorkflowTriggerSource[]>([])
const selectedRuntimeId = ref('')
const runsTabRef = ref<{ refresh: () => Promise<void> } | null>(null)
const inspectedRun = ref<WorkflowRun | null>(null)
const cancellingInspectedRun = ref(false)

const loading = ref(true)
const loadingMoreVersions = ref(false)
const changingVersionStateId = ref<string | null>(null)
const busyRuntimeId = ref<string | null>(null)
const runtimeDialogError = ref<string | null>(null)
const runtimeDetailsRuntimeId = ref('')
const runtimeDetailsInitialTab = ref<'overview' | 'diagnostics'>('overview')
const runtimeCreateDialogOpen = ref(false)
const runtimeVersionDialogRuntimeId = ref('')
const runtimeTargetVersionId = ref('')
const allowBreakingContract = ref(false)
const breakingChangeReason = ref('')
const requestExamplesDrawerOpen = ref(false)
const editConfigRuntime = ref<WorkflowAppRuntime | null>(null)
const pendingDeleteRuntime = ref<WorkflowAppRuntime | null>(null)
const revisionsByRuntimeId = ref<Record<string, WorkflowRuntimeRevision[]>>({})
const revisionLoadErrorsByRuntimeId = ref<Record<string, string>>({})
const runtimeVersionSelectionComparison = ref<WorkflowAppVersionComparison | null>(null)
const versionComparisonLoading = ref(false)

const errorMessage = ref<string | null>(null)
const feedbackStore = useFeedbackStore()

// Header / App-level drawers & dialogs
const infoDrawerOpen = ref(false)
const infoInitialEditing = ref(false)
const copyDialogOpen = ref(false)
const pendingDeleteAppOpen = ref(false)
const deletingApplication = ref(false)

// Tab 2: Versions
const versionStateFilter = ref('all')
const versionOffset = ref(0)
const versionLimit = 10
const versionDetailVersionId = ref('')
const compareDrawerOpen = ref(false)
const compareSourceVersionId = ref<string | null>(null)
const compareTargetVersionId = ref<string | null>('draft')
const pendingDeleteVersion = ref<WorkflowAppVersion | null>(null)
const deletingVersionId = ref<string | null>(null)

// Tab 3: Input / Output
const selectedIoVersionKey = ref('latest')
const ioLoading = ref(false)
const ioError = ref<string | null>(null)
const ioCopyFeedback = ref('')
const expandedIoOutputs = ref<Record<string, boolean>>({})

// Floating menu
const openMenuKey = ref<string | null>(null)
const menuStyle = ref<Record<string, string>>({})

const application = computed(() => workflowApp.value?.applicationDocument.application ?? null)
const graph = computed(() => workflowApp.value?.graphDocument.template ?? null)
const latestVersion = computed(() => workflowApp.value?.latestVersion ?? null)
const versions = computed(() => workflowApp.value?.versions ?? [])
const publishedVersions = computed(() => selectRuntimeCandidateVersions(versions.value))
const runtimes = computed(() => workflowApp.value?.runtimes ?? [])
const selectedRuntime = computed(
  () => runtimes.value.find((item) => item.workflow_runtime_id === selectedRuntimeId.value) ?? null,
)

const detailTabs = computed<TabListItem[]>(() => [
  { id: 'runtimes', label: '运行实例', count: runtimes.value.length },
  { id: 'versions', label: '发布版本', count: versions.value.length },
  { id: 'io', label: '输入输出' },
  { id: 'invoke', label: '调用调试' },
  { id: 'runs', label: '执行记录' },
])

const inputBindings = computed(() =>
  (application.value?.bindings ?? []).filter((binding) => binding.direction === 'input'),
)
const outputBindings = computed(() =>
  (application.value?.bindings ?? []).filter((binding) => binding.direction === 'output'),
)
const templateInputById = computed(
  () => new Map((graph.value?.template_inputs ?? []).map((input) => [input.input_id, input])),
)
const templateOutputById = computed(
  () => new Map((graph.value?.template_outputs ?? []).map((output) => [output.output_id, output])),
)
const selectedRuntimeVersionId = computed(() => {
  const rt = selectedRuntime.value
  if (!rt) return ''
  const activeRev = runtimeRevision(rt, rt.active_revision_id)
  if (activeRev?.workflow_app_version_id) return activeRev.workflow_app_version_id
  const desiredRev = runtimeRevision(rt, rt.desired_revision_id)
  if (desiredRev?.workflow_app_version_id) return desiredRev.workflow_app_version_id
  const metaVer = rt.metadata?.workflow_app_version_id
  return typeof metaVer === 'string' ? metaVer : ''
})

const selectedRuntimeContract = computed<WorkflowJsonObject | null>(() => {
  const verId = selectedRuntimeVersionId.value
  if (verId && versionDetailsById.value[verId]) {
    return versionDetailsById.value[verId].contract ?? null
  }
  return latestVersionDetail.value?.contract ?? null
})

const relatedTriggerSources = computed(() => {
  const runtimeIds = new Set(runtimes.value.map((item) => item.workflow_runtime_id))
  return triggerSources.value.filter((src) => runtimeIds.has(src.workflow_runtime_id))
})

const selectedRuntimeTriggerSources = computed(() => {
  if (!selectedRuntimeId.value) return []
  return triggerSources.value.filter((src) => src.workflow_runtime_id === selectedRuntimeId.value)
})

const appSummaryForDrawer = computed<WorkflowAppSummary | null>(() => {
  if (!workflowApp.value || !application.value) return null
  const appDoc = workflowApp.value.applicationDocument
  return {
    application: {
      application_id: application.value.application_id,
      project_id: selectedProjectId.value,
      object_key: appDoc.object_key,
      display_name: application.value.display_name || application.value.application_id,
      description: application.value.description || '',
      template_id: application.value.template_ref.template_id,
      template_version: application.value.template_ref.template_version,
      template_summary: appDoc.template_summary,
      binding_count: appDoc.binding_count,
      input_binding_ids: appDoc.input_binding_ids,
      output_binding_ids: appDoc.output_binding_ids,
      created_at: appDoc.created_at,
      updated_at: appDoc.updated_at,
      created_by: appDoc.created_by,
      updated_by: appDoc.updated_by,
    },
    runtimes: runtimes.value,
    primaryRuntime: workflowApp.value.primaryRuntime,
    latestVersion: latestVersion.value,
    triggerCount: relatedTriggerSources.value.length,
  }
})

// Menu targets
const menuRuntime = computed(() => {
  if (!openMenuKey.value?.startsWith('rt:')) return null
  const id = openMenuKey.value.slice(3)
  return runtimes.value.find((item) => item.workflow_runtime_id === id) ?? null
})
const menuVersion = computed(() => {
  if (!openMenuKey.value?.startsWith('ver:')) return null
  const id = openMenuKey.value.slice(4)
  return versions.value.find((item) => item.workflow_app_version_id === id) ?? null
})

// Tab 2 computed
const versionStateOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'published', label: '已发布' },
  { value: 'archived', label: '已归档' },
]

const filteredVersions = computed(() => {
  if (versionStateFilter.value === 'all') return versions.value
  return versions.value.filter((ver) => ver.state === versionStateFilter.value)
})

const pagedVersions = computed(() =>
  filteredVersions.value.slice(versionOffset.value, versionOffset.value + versionLimit),
)

const versionDetailVersion = computed(
  () => versions.value.find((item) => item.workflow_app_version_id === versionDetailVersionId.value) ?? null,
)

// Tab 1 details / version switch drawers
const runtimeDetailsRuntime = computed(
  () => runtimes.value.find((item) => item.workflow_runtime_id === runtimeDetailsRuntimeId.value) ?? null,
)
const runtimeDetailsVersionLabel = computed(() =>
  runtimeDetailsRuntime.value ? runtimeVersionLabel(runtimeDetailsRuntime.value) : '-',
)
const runtimeDetailsTargetVersionLabel = computed(() => {
  const rt = runtimeDetailsRuntime.value
  if (!rt) return ''
  return versionLabel(runtimeDesiredVersionId(rt))
})
const runtimeVersionDialogRuntime = computed(
  () => runtimes.value.find((item) => item.workflow_runtime_id === runtimeVersionDialogRuntimeId.value) ?? null,
)
const runtimeVersionOptions = computed<SelectOption[]>(() =>
  publishedVersions.value.map((version) => ({
    label: version.display_version,
    value: version.workflow_app_version_id,
    description: version.release_notes || formatSystemDateTime(version.created_at),
  })),
)
const runtimeVersionDialogActiveRevision = computed(() => {
  const rt = runtimeVersionDialogRuntime.value
  return rt ? runtimeRevision(rt, rt.active_revision_id) : null
})
const runtimeVersionDialogCurrentLabel = computed(() => {
  const rt = runtimeVersionDialogRuntime.value
  if (!rt) return '-'
  const activeRevision = runtimeVersionDialogActiveRevision.value
  if (activeRevision) return versionLabel(activeRevision.workflow_app_version_id)
  return rt.active_revision_id ? shortId(rt.active_revision_id) : '尚未激活'
})

// Tab 3 computed
const ioVersionOptions = computed<SelectOption[]>(() => {
  const opts: SelectOption[] = []
  for (const ver of versions.value) {
    const isLatest = latestVersion.value?.workflow_app_version_id === ver.workflow_app_version_id
    opts.push({
      value: ver.workflow_app_version_id,
      label: isLatest ? `${ver.display_version} · 最新发布` : ver.display_version,
    })
  }
  opts.push({ value: 'draft', label: '当前草稿' })
  return opts
})

const activeIoDetail = computed<WorkflowAppVersionDetail | null>(() => {
  const key = selectedIoVersionKey.value
  if (key === 'draft') return null
  if (key === 'latest') return latestVersionDetail.value
  return versionDetailsById.value[key] ?? null
})

function flattenSchemaNodes(
  schema: unknown,
  prefix = '',
  depth = 0,
  requiredFields: Set<string> = new Set(),
): SchemaTreeNode[] {
  if (!isRecord(schema) || depth > 4) return []
  const nodes: SchemaTreeNode[] = []
  const propsObj = isRecord(schema.properties) ? schema.properties : null
  const ownRequired = Array.isArray(schema.required)
    ? new Set(schema.required.filter((item): item is string => typeof item === 'string'))
    : requiredFields

  if (propsObj) {
    for (const [key, propSchema] of Object.entries(propsObj)) {
      if (!isRecord(propSchema)) continue
      const path = prefix ? `${prefix}.${key}` : key
      const rawType = typeof propSchema.type === 'string'
        ? propSchema.type
        : Array.isArray(propSchema.type)
          ? propSchema.type.join(' | ')
          : 'any'
      const itemType = rawType === 'array' && isRecord(propSchema.items) && typeof propSchema.items.type === 'string'
        ? `array<${propSchema.items.type}>`
        : rawType
      nodes.push({
        path,
        name: key,
        type: itemType,
        required: ownRequired.has(key),
        description: typeof propSchema.description === 'string' ? propSchema.description : '',
        depth,
      })
      if (rawType === 'object' && isRecord(propSchema.properties)) {
        nodes.push(...flattenSchemaNodes(propSchema, path, depth + 1))
      } else if (rawType === 'array' && isRecord(propSchema.items)) {
        nodes.push(...flattenSchemaNodes(propSchema.items, `${path}[]`, depth + 1))
      }
    }
  } else if (schema.type === 'array' && isRecord(schema.items)) {
    nodes.push(...flattenSchemaNodes(schema.items, prefix ? `${prefix}[]` : '[]', depth))
  }
  return nodes
}

function buildIoRowsFromContract(items: unknown, direction: 'inputs' | 'outputs'): IoContractRow[] {
  if (!Array.isArray(items)) return []
  return items
    .filter((item): item is WorkflowJsonObject => isRecord(item))
    .map((item) => {
      const bindingId = typeof item.binding_id === 'string' ? item.binding_id : '—'
      const displayName =
        (typeof item.display_name === 'string' && item.display_name.trim())
        || (typeof item.title === 'string' && item.title.trim())
        || bindingId
      const payloadTypeId = typeof item.payload_type_id === 'string' ? item.payload_type_id : ''
      const description = typeof item.description === 'string' ? item.description : ''
      const schemaCandidate = item.json_schema ?? item.payload_schema ?? item.request_schema
      return {
        bindingId,
        displayName,
        payloadTypeId,
        required: item.required !== false,
        description,
        schemaNodes: direction === 'outputs' ? flattenSchemaNodes(schemaCandidate) : [],
      }
    })
}

function buildIoRowsFromDraft(bindings: FlowApplicationBinding[]): IoContractRow[] {
  return bindings.map((binding) => {
    const meta = binding.metadata ?? {}
    const displayName =
      (typeof meta.display_name === 'string' && meta.display_name.trim())
      || (typeof meta.title === 'string' && meta.title.trim())
      || binding.binding_id
    const description = typeof meta.description === 'string' ? meta.description : ''
    return {
      bindingId: binding.binding_id,
      displayName,
      payloadTypeId: getBindingPayloadTypeId(binding),
      required: binding.required,
      description,
      schemaNodes: [],
    }
  })
}

const ioInputs = computed<IoContractRow[]>(() => {
  if (selectedIoVersionKey.value !== 'draft' && activeIoDetail.value) {
    return buildIoRowsFromContract(activeIoDetail.value.contract?.inputs, 'inputs')
  }
  return buildIoRowsFromDraft(inputBindings.value)
})

const ioOutputs = computed<IoContractRow[]>(() => {
  if (selectedIoVersionKey.value !== 'draft' && activeIoDetail.value) {
    return buildIoRowsFromContract(activeIoDetail.value.contract?.outputs, 'outputs')
  }
  return buildIoRowsFromDraft(outputBindings.value)
})

// Tab 4 request examples & last run receipt
const requestExamples = computed(() =>
  buildWorkflowAppRequestExamples(
    latestVersionDetail.value?.contract ?? null,
    selectedRuntime.value?.workflow_runtime_id ?? '',
  ),
)

const requestExampleEndpoints = computed<string[]>(() => {
  const rid = selectedRuntime.value?.workflow_runtime_id || '{workflow_runtime_id}'
  return [
    `POST /api/v1/workflows/app-runtimes/${rid}/invoke`,
    `POST /api/v1/workflows/app-runtimes/${rid}/runs`,
  ]
})
const graphEditorPath = computed(() => `/workflows/graph/apps/${encodeURIComponent(applicationId.value)}`)

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function shortId(value: string): string {
  return value.length > 20 ? `${value.slice(0, 10)}…${value.slice(-6)}` : value
}

function getBindingPayloadTypeId(binding: FlowApplicationBinding): string {
  const configType = binding.config.payload_type_id
  if (typeof configType === 'string' && configType.trim()) return configType.trim()
  const metaType = binding.metadata.payload_type_id
  if (typeof metaType === 'string' && metaType.trim()) return metaType.trim()
  const templatePort =
    binding.direction === 'input'
      ? templateInputById.value.get(binding.template_port_id)
      : templateOutputById.value.get(binding.template_port_id)
  return templatePort?.payload_type_id ?? ''
}

function runtimeDotTone(state: string): 'ok' | 'bad' | 'warn' | 'neutral' {
  if (state === 'running') return 'ok'
  if (state === 'failed') return 'bad'
  if (state === 'starting' || state === 'stopping') return 'warn'
  return 'neutral'
}

function formatRuntimeStateLabel(state: string): string {
  if (state === 'running') return '运行中'
  if (state === 'stopped' || state === 'created') return '已停止'
  if (state === 'starting') return '启动中'
  if (state === 'stopping') return '停止中'
  if (state === 'failed') return '异常'
  return state
}

function triggerDotTone(src: WorkflowTriggerSource): 'ok' | 'bad' | 'warn' | 'neutral' {
  if (!src.enabled) return 'neutral'
  if (src.observed_state === 'running') return 'ok'
  if (src.observed_state === 'failed') return 'bad'
  return 'warn'
}

function formatTriggerStateLabel(src: WorkflowTriggerSource): string {
  if (!src.enabled) return '已禁用'
  if (src.observed_state === 'running') return '运行中'
  if (src.observed_state === 'failed') return '异常'
  return src.observed_state === 'stopped' ? '已停止' : src.observed_state
}

function runtimeDisplayNameById(runtimeId: string): string {
  const found = runtimes.value.find((item) => item.workflow_runtime_id === runtimeId)
  return found?.display_name || shortId(runtimeId)
}

function versionLabel(versionId: string | null | undefined): string {
  if (!versionId) return '-'
  const found = versions.value.find((item) => item.workflow_app_version_id === versionId)
  return found ? found.display_version : shortId(versionId)
}

function runtimeRevision(runtime: WorkflowAppRuntime, revisionId: string | null | undefined): WorkflowRuntimeRevision | null {
  if (!revisionId) return null
  return (revisionsByRuntimeId.value[runtime.workflow_runtime_id] ?? []).find(
    (rev) => rev.workflow_runtime_revision_id === revisionId,
  ) ?? null
}

function runtimeVersionLabel(runtime: WorkflowAppRuntime): string {
  const active = runtimeRevision(runtime, runtime.active_revision_id)
  const desired = runtimeRevision(runtime, runtime.desired_revision_id)
  const activeLabel = active
    ? versionLabel(active.workflow_app_version_id)
    : runtime.active_revision_id
      ? shortId(runtime.active_revision_id)
      : '-'
  const desiredLabel = desired
    ? versionLabel(desired.workflow_app_version_id)
    : runtime.desired_revision_id
      ? shortId(runtime.desired_revision_id)
      : '-'
  if (runtime.active_revision_id && runtime.desired_revision_id && runtime.active_revision_id !== runtime.desired_revision_id) {
    return `${activeLabel} → ${desiredLabel}`
  }
  return activeLabel !== '-' ? activeLabel : desiredLabel
}

function runtimeDesiredVersionId(runtime: WorkflowAppRuntime): string {
  return runtimeRevision(runtime, runtime.desired_revision_id)?.workflow_app_version_id ?? ''
}

function runtimeTriggerSourceCount(runtime: WorkflowAppRuntime): number {
  return triggerSources.value.filter((src) => src.workflow_runtime_id === runtime.workflow_runtime_id).length
}

function versionReferencingRuntimes(versionId: string): WorkflowAppRuntime[] {
  return runtimes.value.filter((rt) => {
    const activeRev = runtimeRevision(rt, rt.active_revision_id)
    const desiredRev = runtimeRevision(rt, rt.desired_revision_id)
    if (activeRev?.workflow_app_version_id === versionId || desiredRev?.workflow_app_version_id === versionId) {
      return true
    }
    const metaVersionId = rt.metadata?.workflow_app_version_id
    return metaVersionId === versionId
  })
}

function isRuntimeBusy(): boolean {
  return busyRuntimeId.value !== null || loading.value
}

function isRuntimeRunning(runtime: WorkflowAppRuntime): boolean {
  return runtime.observed_state === 'running'
}

function canStartRuntime(runtime: WorkflowAppRuntime): boolean {
  if (!canWriteWorkflows.value || isRuntimeBusy()) return false
  if (runtimeRevision(runtime, runtime.desired_revision_id)?.state === 'failed') return false
  return runtime.observed_state !== 'failed' && !isRuntimeRunning(runtime) && runtime.observed_state !== 'starting' && runtime.observed_state !== 'stopping'
}

function canStopRuntime(runtime: WorkflowAppRuntime): boolean {
  if (!canWriteWorkflows.value || isRuntimeBusy()) return false
  return isRuntimeRunning(runtime) || runtime.observed_state === 'starting' || runtime.observed_state === 'failed'
}

function canRestartRuntime(runtime: WorkflowAppRuntime): boolean {
  if (!canWriteWorkflows.value || isRuntimeBusy()) return false
  return isRuntimeRunning(runtime)
}

function runtimeStopActionLabel(runtime: WorkflowAppRuntime): string {
  return runtime.observed_state === 'failed' ? '重置' : '停止'
}

function canEditRuntimeConfig(runtime: WorkflowAppRuntime): boolean {
  if (!canWriteWorkflows.value || isRuntimeBusy()) return false
  if (runtime.desired_state !== 'stopped' || !['stopped', 'failed'].includes(runtime.observed_state)) {
    return false
  }
  return !triggerSources.value.some(
    (src) =>
      src.workflow_runtime_id === runtime.workflow_runtime_id
      && (src.enabled || src.desired_state !== 'stopped' || src.observed_state !== 'stopped'),
  )
}

function editRuntimeConfigTitle(runtime: WorkflowAppRuntime): string {
  if (!canWriteWorkflows.value) return '当前账号无编辑权限'
  if (runtime.desired_state !== 'stopped' || !['stopped', 'failed'].includes(runtime.observed_state)) {
    return '请先停止实例后再编辑配置'
  }
  if (!canEditRuntimeConfig(runtime)) {
    return '请先停用关联触发入口后再编辑配置'
  }
  return '编辑运行实例配置'
}

function canOpenRuntimeVersionDialog(runtime: WorkflowAppRuntime): boolean {
  if (!canWriteWorkflows.value || isRuntimeBusy() || publishedVersions.value.length === 0) return false
  if (runtime.desired_state !== 'stopped' || runtime.observed_state !== 'stopped') return false
  return !triggerSources.value.some(
    (src) =>
      src.workflow_runtime_id === runtime.workflow_runtime_id
      && (src.enabled || src.desired_state !== 'stopped' || src.observed_state !== 'stopped'),
  )
}

function runtimeVersionActionTitle(runtime: WorkflowAppRuntime): string {
  return canOpenRuntimeVersionDialog(runtime)
    ? t('workflowEditor.appDetail.actions.switchVersion')
    : t('workflowEditor.appDetail.hints.stopRuntimeAndTriggersBeforeSwitch')
}

function restartRuntimeTitle(runtime: WorkflowAppRuntime): string {
  if (isRuntimeBusy()) return t('workflowEditor.appDetail.hints.runtimeBusy')
  if (!isRuntimeRunning(runtime)) return t('workflowEditor.appDetail.hints.restartRunningOnly')
  return t('workflowEditor.appDetail.hints.restartRuntime')
}

function canDeleteRuntime(runtime: WorkflowAppRuntime): boolean {
  if (!canWriteWorkflows.value || isRuntimeBusy()) return false
  if (isRuntimeRunning(runtime) || runtime.observed_state === 'starting' || runtime.observed_state === 'stopping') return false
  return runtimeTriggerSourceCount(runtime) === 0
}

function deleteRuntimeTitle(runtime: WorkflowAppRuntime): string {
  const count = runtimeTriggerSourceCount(runtime)
  if (isRuntimeBusy()) return t('workflowEditor.appDetail.hints.runtimeBusy')
  if (isRuntimeRunning(runtime) || runtime.observed_state === 'starting' || runtime.observed_state === 'stopping') {
    return t('workflowEditor.appDetail.hints.stopBeforeDelete')
  }
  if (count > 0) return t('workflowEditor.appDetail.hints.deleteTriggersFirst', { count })
  return t('workflowEditor.appDetail.hints.deleteRuntime')
}

// Navigation helpers
function selectTab(nextTabId: string): void {
  if (!(VALID_TABS as readonly string[]).includes(nextTabId)) return
  activeTab.value = nextTabId as DetailTabId
  void router.replace({
    query: { ...route.query, tab: nextTabId },
  })
}

function openAppList(): void {
  void router.push('/workflows/apps')
}

function openGraphEditor(versionId?: string): void {
  if (versionId) {
    void router.push(`${graphEditorPath.value}?version_id=${encodeURIComponent(versionId)}`)
    return
  }
  void router.push(graphEditorPath.value)
}

function openRuntimeMonitor(runtime: WorkflowAppRuntime): void {
  void router.push(`/workflows/runtime/${encodeURIComponent(runtime.workflow_runtime_id)}/monitor`)
}

function openRuntimeAppMode(runtime: WorkflowAppRuntime): void {
  void router.push(`/workflows/runtime/${encodeURIComponent(runtime.workflow_runtime_id)}/app-mode`)
}

function triggerSourceCreatePath(runtimeId?: string): string {
  const query = new URLSearchParams({ application_id: applicationId.value, mode: 'create' })
  if (runtimeId) query.set('runtime_id', runtimeId)
  return `/integrations/trigger-sources?${query.toString()}`
}

function triggerSourceItemPath(src: WorkflowTriggerSource, mode: 'detail' | 'config'): string {
  const query = new URLSearchParams({
    application_id: applicationId.value,
    runtime_id: src.workflow_runtime_id,
    trigger_source_id: src.trigger_source_id,
    mode,
  })
  return `/integrations/trigger-sources?${query.toString()}`
}

function openSelectedRuntimeTriggerSource(): void {
  const rt = selectedRuntime.value
  if (!rt || !canWriteWorkflows.value) return
  void router.push(triggerSourceCreatePath(rt.workflow_runtime_id))
}

function selectRuntime(runtimeId: string): void {
  selectedRuntimeId.value = runtimeId
  const rt = runtimes.value.find((item) => item.workflow_runtime_id === runtimeId)
  if (rt) void loadRuntimeRevisionSummaries(rt)
}

// Floating menu handling
function toggleMenu(event: MouseEvent, key: string): void {
  if (openMenuKey.value === key) {
    openMenuKey.value = null
    return
  }
  const target = event.currentTarget as HTMLElement | null
  if (target) {
    const rect = target.getBoundingClientRect()
    const top = Math.min(rect.bottom + 6, window.innerHeight - 190)
    const right = Math.max(12, window.innerWidth - rect.right)
    menuStyle.value = { top: `${top}px`, right: `${right}px` }
  }
  openMenuKey.value = key
}

function closeMenu(): void {
  openMenuKey.value = null
}

function handleWindowKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') closeMenu()
}

onMounted(() => {
  window.addEventListener('click', closeMenu)
  window.addEventListener('scroll', closeMenu, true)
  window.addEventListener('resize', closeMenu)
  window.addEventListener('keydown', handleWindowKeydown)
  void loadPage()
})

onBeforeUnmount(() => {
  window.removeEventListener('click', closeMenu)
  window.removeEventListener('scroll', closeMenu, true)
  window.removeEventListener('resize', closeMenu)
  window.removeEventListener('keydown', handleWindowKeydown)
})

watch(
  () => route.query.tab,
  (tabParam) => {
    if (typeof tabParam === 'string' && (VALID_TABS as readonly string[]).includes(tabParam)) {
      activeTab.value = tabParam as DetailTabId
    }
  },
)

watch(
  [() => selectedProjectId.value, () => applicationId.value],
  ([nextProj, nextApp], [prevProj, prevApp]) => {
    if (nextProj !== prevProj || nextApp !== prevApp) {
      void loadPage()
    }
  },
)

watch(selectedRuntimeId, (workflowRuntimeId) => {
  if (workflowRuntimeId) {
    workflowAppRuntimeStream.start(workflowRuntimeId)
  } else {
    workflowAppRuntimeStream.stop()
  }
})

watch(
  activeTab,
  (tab) => {
    if (tab === 'io') {
      void ensureSelectedIoDetail()
    } else if (tab === 'runs') {
      void runsTabRef.value?.refresh()
    }
  },
)

watch(
  selectedRuntimeVersionId,
  (verId) => {
    if (verId && !versionDetailsById.value[verId] && selectedProjectId.value && applicationId.value) {
      void getWorkflowAppVersion(selectedProjectId.value, applicationId.value, verId)
        .then((detail) => {
          versionDetailsById.value = { ...versionDetailsById.value, [verId]: detail }
        })
        .catch(() => {
          // 保留回退契约即可
        })
    }
  },
  { immediate: true },
)

// Data loading
function replaceRuntime(updatedRuntime: WorkflowAppRuntime): void {
  if (!workflowApp.value) return
  const idx = workflowApp.value.runtimes.findIndex(
    (item) => item.workflow_runtime_id === updatedRuntime.workflow_runtime_id,
  )
  if (idx >= 0) workflowApp.value.runtimes.splice(idx, 1, updatedRuntime)
  else workflowApp.value.runtimes.unshift(updatedRuntime)
  workflowApp.value.primaryRuntime =
    workflowApp.value.runtimes.find((item) => item.observed_state === 'running')
    ?? workflowApp.value.runtimes[0]
    ?? null
}

async function ensureVersionSummary(versionId: string): Promise<WorkflowAppVersion> {
  const existing = versions.value.find((item) => item.workflow_app_version_id === versionId)
  if (existing) return existing
  const detail = await getWorkflowAppVersion(selectedProjectId.value, applicationId.value, versionId)
  versionDetailsById.value = {
    ...versionDetailsById.value,
    [versionId]: detail,
  }
  if (workflowApp.value) {
    workflowApp.value.versions = [
      ...workflowApp.value.versions.filter((item) => item.workflow_app_version_id !== detail.workflow_app_version_id),
      detail,
    ].sort((left, right) => right.version_number - left.version_number)
  }
  return detail
}

async function loadRuntimeRevision(
  runtime: WorkflowAppRuntime,
  revisionId: string,
  forceRefresh = false,
): Promise<WorkflowRuntimeRevision> {
  const existing = runtimeRevision(runtime, revisionId)
  if (existing && !forceRefresh) return existing
  const rev = await getWorkflowRuntimeRevision(runtime.workflow_runtime_id, revisionId)
  const current = revisionsByRuntimeId.value[runtime.workflow_runtime_id] ?? []
  revisionsByRuntimeId.value = {
    ...revisionsByRuntimeId.value,
    [runtime.workflow_runtime_id]: [
      ...current.filter((item) => item.workflow_runtime_revision_id !== rev.workflow_runtime_revision_id),
      rev,
    ],
  }
  return rev
}

async function loadRuntimeRevisionSummaries(runtime: WorkflowAppRuntime, forceRefresh = false): Promise<void> {
  const revisionIds = [
    ...new Set([runtime.active_revision_id, runtime.desired_revision_id].filter((v): v is string => Boolean(v))),
  ]
  if (revisionIds.length === 0) return
  const results = await Promise.allSettled(revisionIds.map((revId) => loadRuntimeRevision(runtime, revId, forceRefresh)))
  const versionResults = await Promise.allSettled(
    results.flatMap((res) => (res.status === 'fulfilled' ? [ensureVersionSummary(res.value.workflow_app_version_id)] : [])),
  )
  const failed = results.find((r) => r.status === 'rejected') ?? versionResults.find((r) => r.status === 'rejected')
  if (failed?.status === 'rejected') {
    revisionLoadErrorsByRuntimeId.value = {
      ...revisionLoadErrorsByRuntimeId.value,
      [runtime.workflow_runtime_id]:
        failed.reason instanceof Error ? failed.reason.message : t('workflowEditor.appDetail.messages.revisionSummaryFailed'),
    }
  }
}

async function loadPage(): Promise<void> {
  if (!selectedProjectId.value || !applicationId.value) return
  loading.value = true
  errorMessage.value = null
  try {
    const appDocument = await getWorkflowApp(selectedProjectId.value, applicationId.value)
    const appTriggerSources: WorkflowTriggerSource[] = []
    const concurrency = 8
    for (let offset = 0; offset < appDocument.runtimes.length; offset += concurrency) {
      const batch = await Promise.all(
        appDocument.runtimes.slice(offset, offset + concurrency).map((rt) =>
          listAllWorkflowTriggerSourcesForRuntime(selectedProjectId.value, rt.workflow_runtime_id),
        ),
      )
      appTriggerSources.push(...batch.flat())
    }
    const [runtimeStatusResult, triggerStatusResult] = await Promise.all([
      refreshWorkflowAppRuntimeStatuses(appDocument.runtimes),
      refreshWorkflowTriggerSourceStatuses(appTriggerSources),
    ])
    revisionsByRuntimeId.value = {}
    revisionLoadErrorsByRuntimeId.value = {}
    versionDetailsById.value = {}
    appDocument.runtimes = runtimeStatusResult.items
    appDocument.primaryRuntime =
      runtimeStatusResult.items.find((rt) => rt.observed_state === 'running')
      ?? runtimeStatusResult.items[0]
      ?? null
    workflowApp.value = appDocument
    latestVersionDetail.value = appDocument.latestVersion
      ? await getWorkflowAppVersion(
          selectedProjectId.value,
          applicationId.value,
          appDocument.latestVersion.workflow_app_version_id,
        )
      : null
    if (latestVersionDetail.value) {
      versionDetailsById.value[latestVersionDetail.value.workflow_app_version_id] = latestVersionDetail.value
    }
    selectedIoVersionKey.value = appDocument.latestVersion?.workflow_app_version_id ?? 'draft'
    triggerSources.value = triggerStatusResult.items

    const queryRuntimeId = typeof route.query.runtime_id === 'string' ? route.query.runtime_id : ''
    selectedRuntimeId.value = appDocument.runtimes.some((rt) => rt.workflow_runtime_id === queryRuntimeId)
      ? queryRuntimeId
      : appDocument.primaryRuntime?.workflow_runtime_id ?? appDocument.runtimes[0]?.workflow_runtime_id ?? ''

    // 预加载实例版本摘要，避免表中绑定版本列只显示 ID 缩写
    await Promise.allSettled(appDocument.runtimes.map((rt) => loadRuntimeRevisionSummaries(rt)))

    const failedIds = [...runtimeStatusResult.failedRuntimeIds, ...triggerStatusResult.failedTriggerSourceIds]
    if (failedIds.length > 0) {
      errorMessage.value = t('workflowEditor.appDetail.messages.partialRefreshFailed', {
        runtimeIds: failedIds.join(', '),
      })
    }
    if (activeTab.value === 'runs') {
      await runsTabRef.value?.refresh()
    }
  } catch (error) {
    errorMessage.value = getErrorMessage(error)
  } finally {
    loading.value = false
  }
}

// Header actions
function openInfoDrawer(editing: boolean): void {
  closeMenu()
  infoInitialEditing.value = editing
  infoDrawerOpen.value = true
}

function openCopyDialog(): void {
  closeMenu()
  copyDialogOpen.value = true
}

function requestDeleteApplication(): void {
  closeMenu()
  pendingDeleteAppOpen.value = true
}

async function handleAppUpdated(): Promise<void> {
  infoDrawerOpen.value = false
  await loadPage()
}

async function handleAppCopied(doc: { application: { application_id: string } }): Promise<void> {
  copyDialogOpen.value = false
  await router.push(`/workflows/apps/${encodeURIComponent(doc.application.application_id)}`)
}

async function confirmDeleteApplication(): Promise<void> {
  if (runtimes.value.length > 0) {
    pendingDeleteAppOpen.value = false
    return
  }
  deletingApplication.value = true
  errorMessage.value = null
  try {
    await deleteWorkflowApplication(selectedProjectId.value, applicationId.value)
    pendingDeleteAppOpen.value = false
    void router.push('/workflows/apps')
  } catch (error) {
    errorMessage.value = getErrorMessage(error)
  } finally {
    deletingApplication.value = false
  }
}

// Tab 1 actions
function openRuntimeDetails(runtime: WorkflowAppRuntime, tab: 'overview' | 'diagnostics'): void {
  runtimeDetailsInitialTab.value = tab
  runtimeDetailsRuntimeId.value = runtime.workflow_runtime_id
}

function openRuntimeCreateDialog(): void {
  if (!canWriteWorkflows.value || isRuntimeBusy() || publishedVersions.value.length === 0) return
  runtimeDialogError.value = null
  runtimeCreateDialogOpen.value = true
}

function closeRuntimeCreateDialog(): void {
  if (busyRuntimeId.value === 'new') return
  runtimeCreateDialogOpen.value = false
  runtimeDialogError.value = null
}

function buildRuntimeDefaultExecutionMetadata(value: WorkflowRuntimeCreateDialogValue): WorkflowJsonObject {
  return {
    workflow_run_record_mode: value.workflowRunRecordMode,
    return_timing_metadata_enabled: value.returnDiagnostics,
    return_node_timings_enabled: value.returnDiagnostics,
    trace_level: 'none',
    retain_trace_enabled: false,
    retain_node_records_enabled: false,
  }
}

async function createRuntime(value: WorkflowRuntimeCreateDialogValue): Promise<void> {
  if (!application.value || !canWriteWorkflows.value) return
  if (!publishedVersions.value.some((v) => v.workflow_app_version_id === value.workflowAppVersionId)) return
  busyRuntimeId.value = 'new'
  errorMessage.value = null
  runtimeDialogError.value = null
  try {
    const runtime = await createWorkflowAppRuntime({
      projectId: selectedProjectId.value,
      workflowAppVersionId: value.workflowAppVersionId,
      displayName: value.displayName?.trim() || `${application.value.display_name || application.value.application_id} runtime`,
      requestTimeoutSeconds: value.requestTimeoutSeconds,
      metadata: {
        source: 'web-ui-app-detail',
        default_execution_metadata: buildRuntimeDefaultExecutionMetadata(value),
      },
    })
    replaceRuntime(runtime)
    selectedRuntimeId.value = runtime.workflow_runtime_id
    await loadRuntimeRevisionSummaries(runtime)
    feedbackStore.success(`运行实例 ${runtime.display_name || runtime.workflow_runtime_id} 已创建`)
    runtimeCreateDialogOpen.value = false
  } catch (error) {
    const msg = getErrorMessage(error)
    runtimeDialogError.value = msg
    errorMessage.value = msg
  } finally {
    busyRuntimeId.value = null
  }
}

function openEditConfigDialog(runtime: WorkflowAppRuntime): void {
  closeMenu()
  if (!canEditRuntimeConfig(runtime)) return
  editConfigRuntime.value = runtime
}

function handleRuntimeConfigSaved(updatedRuntime: WorkflowAppRuntime): void {
  editConfigRuntime.value = null
  replaceRuntime(updatedRuntime)
  void loadRuntimeRevisionSummaries(updatedRuntime, true)
  feedbackStore.success(`实例配置已保存（修订 #${updatedRuntime.revision_generation}），将在下次启动生效`)
}

async function controlRuntime(runtime: WorkflowAppRuntime, action: RuntimeControlAction): Promise<void> {
  if (!canWriteWorkflows.value) return
  if (action === 'start' && !canStartRuntime(runtime)) return
  if (action === 'stop' && !canStopRuntime(runtime)) return
  if (action === 'restart' && !canRestartRuntime(runtime)) return
  busyRuntimeId.value = runtime.workflow_runtime_id
  errorMessage.value = null
  try {
    const actions = {
      start: startWorkflowAppRuntime,
      stop: stopWorkflowAppRuntime,
      restart: restartWorkflowAppRuntime,
    }
    const updated = await actions[action](runtime.workflow_runtime_id)
    replaceRuntime(updated)
    await loadRuntimeRevisionSummaries(updated, true)
    feedbackStore.success(`实例 ${updated.display_name || updated.workflow_runtime_id} 操作已提交`)
  } catch (error) {
    errorMessage.value = getErrorMessage(error)
  } finally {
    busyRuntimeId.value = null
  }
}

async function menuControlRuntime(runtime: WorkflowAppRuntime, action: RuntimeControlAction): Promise<void> {
  closeMenu()
  await controlRuntime(runtime, action)
}

async function refreshRuntimeHealth(runtime: WorkflowAppRuntime): Promise<void> {
  if (isRuntimeBusy()) return
  busyRuntimeId.value = runtime.workflow_runtime_id
  errorMessage.value = null
  try {
    const updated = await getWorkflowAppRuntimeHealth(runtime.workflow_runtime_id)
    replaceRuntime(updated)
    feedbackStore.success(`实例 ${updated.display_name || updated.workflow_runtime_id} 健康状态已刷新`)
  } catch (error) {
    errorMessage.value = getErrorMessage(error)
  } finally {
    busyRuntimeId.value = null
  }
}

function menuRequestDeleteRuntime(runtime: WorkflowAppRuntime): void {
  closeMenu()
  if (!canDeleteRuntime(runtime)) return
  pendingDeleteRuntime.value = runtime
}

async function deleteRuntime(): Promise<void> {
  const runtime = pendingDeleteRuntime.value
  if (!runtime || !canDeleteRuntime(runtime)) return
  busyRuntimeId.value = runtime.workflow_runtime_id
  errorMessage.value = null
  try {
    await deleteWorkflowAppRuntime(runtime.workflow_runtime_id)
    if (workflowApp.value) {
      workflowApp.value.runtimes = workflowApp.value.runtimes.filter(
        (item) => item.workflow_runtime_id !== runtime.workflow_runtime_id,
      )
      workflowApp.value.primaryRuntime =
        workflowApp.value.runtimes.find((item) => item.observed_state === 'running')
        ?? workflowApp.value.runtimes[0]
        ?? null
      if (selectedRuntimeId.value === runtime.workflow_runtime_id) {
        selectedRuntimeId.value = workflowApp.value.primaryRuntime?.workflow_runtime_id ?? ''
      }
    }
    if (runtimeDetailsRuntimeId.value === runtime.workflow_runtime_id) {
      runtimeDetailsRuntimeId.value = ''
    }
    feedbackStore.success(`实例 ${runtime.display_name || runtime.workflow_runtime_id} 已删除`)
  } catch (error) {
    errorMessage.value = getErrorMessage(error)
  } finally {
    busyRuntimeId.value = null
    pendingDeleteRuntime.value = null
  }
}

// Switch version dialog
async function menuOpenVersionDialog(runtime: WorkflowAppRuntime): Promise<void> {
  closeMenu()
  if (!canOpenRuntimeVersionDialog(runtime)) return
  runtimeDialogError.value = null
  allowBreakingContract.value = false
  breakingChangeReason.value = ''
  runtimeVersionDialogRuntimeId.value = runtime.workflow_runtime_id
  await loadRuntimeRevisionSummaries(runtime)
  if (runtimeVersionDialogRuntimeId.value !== runtime.workflow_runtime_id) return
  runtimeTargetVersionId.value = runtimeDesiredVersionId(runtime) || latestVersion.value?.workflow_app_version_id || ''
}

function closeRuntimeVersionDialog(): void {
  const rt = runtimeVersionDialogRuntime.value
  if (rt && busyRuntimeId.value === rt.workflow_runtime_id) return
  runtimeVersionDialogRuntimeId.value = ''
  runtimeTargetVersionId.value = ''
  allowBreakingContract.value = false
  breakingChangeReason.value = ''
  runtimeDialogError.value = null
  runtimeVersionSelectionComparison.value = null
}

function setRuntimeTargetVersion(value: SelectValue): void {
  runtimeTargetVersionId.value = typeof value === 'string' ? value : String(value ?? '')
  allowBreakingContract.value = false
  breakingChangeReason.value = ''
}

watch(
  [() => runtimeVersionDialogRuntime.value, () => runtimeTargetVersionId.value],
  async ([rt, targetId]) => {
    runtimeVersionSelectionComparison.value = null
    if (!rt || !targetId || versionComparisonLoading.value) return
    const activeRev = runtimeRevision(rt, rt.active_revision_id)
    if (!activeRev || activeRev.workflow_app_version_id === targetId) return
    versionComparisonLoading.value = true
    try {
      const [srcCmp, tgtCmp] = await Promise.all([
        compareWorkflowAppVersionToDraft(selectedProjectId.value, applicationId.value, activeRev.workflow_app_version_id),
        compareWorkflowAppVersionToDraft(selectedProjectId.value, applicationId.value, targetId),
      ])
      if (srcCmp && tgtCmp) {
        // 如需精确对比两个版本，使用 getWorkflowAppVersion 也可在 Drawer 进行；此处保留快速兼容检测
      }
    } catch {
      // ignore non-blocking comparison preview failure
    } finally {
      versionComparisonLoading.value = false
    }
  },
)

function canSwitchRuntimeVersion(runtime: WorkflowAppRuntime): boolean {
  if (!publishedVersions.value.some((v) => v.workflow_app_version_id === runtimeTargetVersionId.value)) {
    return false
  }
  return canSelectWorkflowRuntimeVersion({
    runtime,
    desiredRevision: runtimeRevision(runtime, runtime.desired_revision_id),
    targetVersionId: runtimeTargetVersionId.value,
    triggerSources: triggerSources.value,
    canWriteWorkflows: canWriteWorkflows.value,
    runtimeBusy: isRuntimeBusy(),
    allowBreakingContract: allowBreakingContract.value,
    breakingChangeReason: breakingChangeReason.value,
  })
}

async function switchRuntimeVersion(runtime: WorkflowAppRuntime): Promise<void> {
  if (!canSwitchRuntimeVersion(runtime)) return
  const targetId = runtimeTargetVersionId.value
  let switched = false
  busyRuntimeId.value = runtime.workflow_runtime_id
  errorMessage.value = null
  runtimeDialogError.value = null
  try {
    const updated = await selectWorkflowAppRuntimeVersion(
      runtime.workflow_runtime_id,
      buildRuntimeVersionSelectionInput({
        runtime,
        targetVersionId: targetId,
        allowBreakingContract: allowBreakingContract.value,
        breakingChangeReason: breakingChangeReason.value,
      }),
    )
    replaceRuntime(updated)
    await loadRuntimeRevisionSummaries(updated, true)
    feedbackStore.success(`已切换目标版本至 ${versionLabel(targetId)}（修订 #${updated.revision_generation}）`)
    switched = true
  } catch (error) {
    const msg = getErrorMessage(error)
    runtimeDialogError.value = msg
    errorMessage.value = msg
  } finally {
    busyRuntimeId.value = null
  }
  if (switched) closeRuntimeVersionDialog()
}

// Tab 2 actions
function onVersionFilterChange(value: SelectValue): void {
  versionStateFilter.value = typeof value === 'string' ? value : 'all'
  versionOffset.value = 0
}

function openVersionDetail(ver: WorkflowAppVersion): void {
  versionDetailVersionId.value = ver.workflow_app_version_id
}

function openVersionCompare(sourceId: string | null, targetId: string | null): void {
  closeMenu()
  compareSourceVersionId.value = sourceId
  compareTargetVersionId.value = targetId
  compareDrawerOpen.value = true
}

function loadVersionIntoEditor(versionId: string): void {
  closeMenu()
  openGraphEditor(versionId)
}

function handleVersionUpdated(updated: WorkflowAppVersion): void {
  if (!workflowApp.value) return
  workflowApp.value.versions = [
    ...workflowApp.value.versions.filter((item) => item.workflow_app_version_id !== updated.workflow_app_version_id),
    updated,
  ].sort((left, right) => right.version_number - left.version_number)
  if (workflowApp.value.latestVersion?.workflow_app_version_id === updated.workflow_app_version_id) {
    workflowApp.value.latestVersion = updated
  }
}

async function refreshLatestVersionAfterStateChange(app: WorkflowAppDocument): Promise<void> {
  const latest = await resolveLatestPublishedVersion(
    selectedProjectId.value,
    applicationId.value,
    { items: app.versions, pagination: app.versionPagination },
  )
  app.latestVersion = latest
  latestVersionDetail.value = latest
    ? await getWorkflowAppVersion(selectedProjectId.value, applicationId.value, latest.workflow_app_version_id)
    : null
}

async function menuChangeVersionState(version: WorkflowAppVersion): Promise<void> {
  closeMenu()
  if (!canWriteWorkflows.value || changingVersionStateId.value !== null) return
  const transition: WorkflowAppVersionStateTransition = version.state === 'published' ? 'archive' : 'restore'
  changingVersionStateId.value = version.workflow_app_version_id
  errorMessage.value = null
  try {
    const updated = await transitionWorkflowAppVersionState(
      selectedProjectId.value,
      applicationId.value,
      version.workflow_app_version_id,
      transition,
    )
    if (workflowApp.value) {
      workflowApp.value.versions = [
        ...workflowApp.value.versions.filter((item) => item.workflow_app_version_id !== updated.workflow_app_version_id),
        updated,
      ].sort((left, right) => right.version_number - left.version_number)
      await refreshLatestVersionAfterStateChange(workflowApp.value)
    }
    feedbackStore.success(transition === 'archive' ? `版本 ${updated.display_version} 已归档` : `版本 ${updated.display_version} 已恢复发布`)
  } catch (error) {
    errorMessage.value = getErrorMessage(error)
  } finally {
    changingVersionStateId.value = null
  }
}

function menuRequestDeleteVersion(version: WorkflowAppVersion): void {
  closeMenu()
  if (versionReferencingRuntimes(version.workflow_app_version_id).length > 0) return
  pendingDeleteVersion.value = version
}

async function confirmDeleteVersion(): Promise<void> {
  const ver = pendingDeleteVersion.value
  if (!ver) return
  deletingVersionId.value = ver.workflow_app_version_id
  errorMessage.value = null
  try {
    await deleteWorkflowAppVersion(selectedProjectId.value, applicationId.value, ver.workflow_app_version_id)
    if (workflowApp.value) {
      workflowApp.value.versions = workflowApp.value.versions.filter(
        (item) => item.workflow_app_version_id !== ver.workflow_app_version_id,
      )
      await refreshLatestVersionAfterStateChange(workflowApp.value)
    }
    if (versionDetailVersionId.value === ver.workflow_app_version_id) {
      versionDetailVersionId.value = ''
    }
    feedbackStore.success(`版本 ${ver.display_version} 已删除`)
    pendingDeleteVersion.value = null
  } catch (error) {
    errorMessage.value = getErrorMessage(error)
  } finally {
    deletingVersionId.value = null
  }
}

async function loadMoreVersions(): Promise<void> {
  const app = workflowApp.value
  if (!app || loadingMoreVersions.value || !app.versionPagination.hasMore) return
  loadingMoreVersions.value = true
  errorMessage.value = null
  try {
    const response = await listWorkflowAppVersions(selectedProjectId.value, applicationId.value, {
      offset: app.versionPagination.nextOffset ?? app.versionPagination.offset + app.versionPagination.limit,
      limit: app.versionPagination.limit,
    })
    const merged = new Map(app.versions.map((v) => [v.workflow_app_version_id, v]))
    for (const v of response.items) merged.set(v.workflow_app_version_id, v)
    app.versions = [...merged.values()].sort((l, r) => r.version_number - l.version_number)
    app.versionPagination = response.pagination
    app.latestVersion = app.versions.find((v) => v.state === 'published') ?? null
  } catch (error) {
    errorMessage.value = getErrorMessage(error)
  } finally {
    loadingMoreVersions.value = false
  }
}

// Tab 3 actions
async function ensureSelectedIoDetail(): Promise<void> {
  const key = selectedIoVersionKey.value
  if (!key || key === 'draft' || key === 'latest') return
  if (versionDetailsById.value[key]) return
  ioLoading.value = true
  ioError.value = null
  try {
    const detail = await getWorkflowAppVersion(selectedProjectId.value, applicationId.value, key)
    versionDetailsById.value = { ...versionDetailsById.value, [key]: detail }
  } catch (error) {
    ioError.value = getErrorMessage(error)
  } finally {
    ioLoading.value = false
  }
}

function selectIoVersion(value: SelectValue): void {
  selectedIoVersionKey.value = typeof value === 'string' && value ? value : 'draft'
  expandedIoOutputs.value = {}
  void ensureSelectedIoDetail()
}

function toggleIoOutputExpanded(bindingId: string): void {
  expandedIoOutputs.value = {
    ...expandedIoOutputs.value,
    [bindingId]: !expandedIoOutputs.value[bindingId],
  }
}

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    feedbackStore.success(`已复制: ${text}`)
  } catch {
    feedbackStore.show({ variant: 'info', title: '请手动复制', message: text })
  }
}

async function copyIoContractJson(): Promise<void> {
  const payload = {
    version: selectedIoVersionKey.value === 'draft' ? 'draft' : activeIoDetail.value?.display_version ?? selectedIoVersionKey.value,
    inputs: ioInputs.value.map((i) => ({
      binding_id: i.bindingId,
      display_name: i.displayName,
      payload_type_id: i.payloadTypeId,
      required: i.required,
      description: i.description,
    })),
    outputs: ioOutputs.value.map((o) => ({
      binding_id: o.bindingId,
      display_name: o.displayName,
      payload_type_id: o.payloadTypeId,
      description: o.description,
      fields: o.schemaNodes,
    })),
  }
  try {
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2))
    ioCopyFeedback.value = '已复制'
    window.setTimeout(() => {
      ioCopyFeedback.value = ''
    }, 1800)
  } catch {
    ioError.value = '浏览器剪贴板写入受限，请手动复制。'
  }
}

const workflowAppRuntimeStream = useWorkflowResourceStream<WorkflowAppRuntime>({
  kind: 'app-runtime',
  getSnapshot: getWorkflowAppRuntimeHealth,
  onSnapshot: replaceRuntime,
  isTerminal: () => false,
})

function openRuntimeConfigFromChild(runtime: WorkflowAppRuntime): void {
  if (canEditRuntimeConfig(runtime)) {
    editConfigRuntime.value = runtime
  } else {
    openRuntimeDetails(runtime, 'overview')
  }
}

function handleInvokeCompleted(_run: WorkflowRun): void {
  if (activeTab.value === 'runs') {
    void runsTabRef.value?.refresh()
  }
}

async function handleCancelInspectedRun(run: WorkflowRun): Promise<void> {
  if (!canWriteWorkflows.value || cancellingInspectedRun.value) return
  cancellingInspectedRun.value = true
  try {
    const updated = await cancelWorkflowRun(run.workflow_run_id)
    inspectedRun.value = updated
    if (activeTab.value === 'runs') {
      await runsTabRef.value?.refresh()
    }
  } catch (error) {
    errorMessage.value = getErrorMessage(error)
  } finally {
    cancellingInspectedRun.value = false
  }
}
</script>

<style scoped>
.app-detail-page {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.app-detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.app-detail-header__left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.app-back-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface);
  color: var(--am-text-strong);
  cursor: pointer;
  flex: none;
}

.app-back-btn:hover {
  background: var(--am-hover-surface);
}

.app-detail-title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  min-width: 0;
}

.app-detail-title-wrap h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--am-text-strong);
}

.app-ver-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.app-ver-pill.is-published {
  background: var(--am-row-selected);
  color: var(--am-action-primary);
}

.app-ver-pill.is-draft {
  background: var(--am-surface-soft);
  color: var(--am-text-muted);
}

.app-detail-header__right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.app-icon-menu-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface);
  color: var(--am-text-strong);
  cursor: pointer;
}

.app-icon-menu-btn:hover:not(:disabled) {
  background: var(--am-hover-surface);
}

.app-tab-stack {
  display: grid;
  gap: 14px;
  min-width: 0;
}

.app-detail-card {
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  overflow: hidden;
  min-width: 0;
}

.app-card-padded {
  padding: 18px 20px;
  display: grid;
  gap: 14px;
}

.app-card-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px 14px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--am-border);
}

.app-card-toolbar--end {
  justify-content: flex-end;
}

.app-card-subhead {
  padding: 12px 16px;
  border-bottom: 1px solid var(--am-border);
}

.app-card-subhead h3,
.app-card-subhead-row h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--am-text-strong);
}

.app-card-subhead-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
}

.app-sub-hint {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--am-text-muted);
}

.app-card-toolbar__actions,
.app-toolbar-filters,
.app-current-runtime,
.app-io-toolbar-left {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 10px;
}

.app-filter-label {
  font-size: 13px;
  color: var(--am-text-muted);
}

.app-chip,
.app-io-count-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  background: var(--am-surface-soft);
  color: var(--am-text-muted);
}

.app-table-wrap {
  width: 100%;
  overflow-x: auto;
}

.app-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.app-table th {
  text-align: left;
  padding: 12px 16px;
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text);
  background: var(--am-table-header, var(--am-surface));
  border-bottom: 1px solid var(--am-border);
  white-space: nowrap;
}

.app-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--am-border);
  color: var(--am-text-strong);
  vertical-align: middle;
}

.app-table tbody tr:last-child td {
  border-bottom: none;
}

.app-table tbody tr:hover {
  background: var(--am-hover-surface);
}

.app-table tbody tr.is-selected {
  background: var(--am-row-selected);
}

.app-cell-main {
  display: grid;
  gap: 2px;
}

.app-err-hint {
  color: #dc2626;
  font-size: 11px;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-rt-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
}

.app-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}

.app-rt-pill.is-ok .app-dot {
  background: var(--am-action-primary);
}

.app-rt-pill.is-neutral {
  color: var(--am-text-muted);
}

.app-rt-pill.is-neutral .app-dot {
  background: var(--am-text-muted);
}

.app-rt-pill.is-bad {
  color: #dc2626;
}

.app-rt-pill.is-bad .app-dot {
  background: #dc2626;
}

.app-rt-pill.is-warn {
  color: #d97706;
}

.app-rt-pill.is-warn .app-dot {
  background: #f59e0b;
}

.app-state-pill,
.app-req-pill,
.app-latest-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.app-state-pill.is-ok,
.app-latest-tag {
  background: var(--am-row-selected);
  color: var(--am-action-primary);
}

.app-state-pill.is-neutral,
.app-req-pill.is-opt {
  background: var(--am-surface-soft);
  color: var(--am-text-muted);
}

.app-req-pill.is-req {
  background: rgba(245, 158, 11, 0.14);
  color: #d97706;
}

.app-ver-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.app-note-cell {
  max-width: 280px;
}

.app-muted {
  color: var(--am-text-muted);
}

.app-nowrap {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.app-num {
  font-variant-numeric: tabular-nums;
}

.app-mono-sm {
  font-family: var(--am-font-mono, ui-monospace, monospace);
  font-size: 12px;
}

.app-code-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--am-surface-soft);
  border: 1px solid var(--am-border);
  font-family: var(--am-font-mono, ui-monospace, monospace);
  font-size: 12px;
  color: var(--am-text);
  line-height: 1.4;
}

.app-mono-copy-inline {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.app-mono-copy-inline code {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--am-surface-soft);
  border: 1px solid var(--am-border);
  font-family: var(--am-font-mono, ui-monospace, monospace);
  font-size: 12px;
  color: var(--am-text-strong);
  line-height: 1.4;
}

.app-copy-mini {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--am-text-muted);
  cursor: pointer;
}

.app-copy-mini:hover {
  background: var(--am-hover-surface);
  color: var(--am-text-strong);
}

.col-actions {
  width: 140px;
  white-space: nowrap;
}

.col-actions-wide {
  width: 175px;
  white-space: nowrap;
}

.app-row-actions {
  display: inline-flex;
  align-items: center;
  gap: 12px;
}

.app-link-btn {
  border: none;
  background: transparent;
  padding: 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--am-action-primary);
  cursor: pointer;
  text-decoration: none;
}

.app-link-btn:hover {
  text-decoration: underline;
}

.app-link-btn.is-danger {
  color: #dc2626;
}

.app-tree-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.app-more-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--am-text-strong);
  cursor: pointer;
}

.app-more-btn:hover {
  background: var(--am-hover-surface);
}

.app-schema-row td {
  padding: 0;
  background: var(--am-surface-soft);
}

.app-schema-tree {
  display: grid;
  padding: 8px 12px;
}

.app-schema-node {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px;
  padding-top: 5px;
  padding-bottom: 5px;
  font-size: 12px;
  border-bottom: 1px dashed var(--am-border);
}

.app-schema-node:last-child {
  border-bottom: none;
}

.app-schema-name {
  font-family: var(--am-font-mono, ui-monospace, monospace);
  font-weight: 600;
  color: var(--am-text-strong);
}

.app-schema-type {
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  font-family: var(--am-font-mono, ui-monospace, monospace);
  font-size: 11px;
  color: var(--am-text-muted);
}

.app-schema-req {
  font-size: 11px;
  font-weight: 600;
  color: #d97706;
}

.app-schema-desc {
  color: var(--am-text-muted);
}

.app-empty-block {
  padding: 36px 20px;
  text-align: center;
  display: grid;
  gap: 4px;
}

.app-empty-block p {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--am-text-strong);
}

.app-empty-block span {
  font-size: 13px;
  color: var(--am-text-muted);
}

.app-card-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  padding: 10px 16px;
  border-top: 1px solid var(--am-border);
}

.app-card-pagination :deep(.pagination-controls) {
  border: none;
  padding: 0;
  background: transparent;
  flex: 1 1 auto;
}

.app-inline-inset {
  margin: 12px 16px 0;
}

.app-invoke-form {
  display: grid;
  gap: 12px;
}

.app-field {
  display: grid;
  gap: 6px;
}

.app-field--short {
  max-width: 320px;
}

.app-field > span {
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text-strong);
}

.app-field textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  padding: 10px 12px;
  background: var(--am-input);
  color: var(--am-text-strong);
  font-family: var(--am-font-mono, ui-monospace, monospace);
  font-size: 12px;
  resize: vertical;
}

.app-invoke-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.app-summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}

.app-summary-grid > div {
  display: grid;
  gap: 3px;
  padding: 10px 12px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface-soft);
}

.app-summary-grid span {
  font-size: 12px;
  color: var(--am-text-muted);
}

.app-summary-grid strong {
  font-size: 13px;
  color: var(--am-text-strong);
  overflow-wrap: anywhere;
}

.result-details {
  margin-top: 12px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  padding: 10px 12px;
  background: var(--am-surface-soft);
}

.result-details summary {
  cursor: pointer;
  font-weight: 600;
  font-size: 13px;
}

.result-details .json-view {
  margin-top: 10px;
}

.app-row-menu {
  position: fixed;
  z-index: calc(var(--am-z-modal) + 2);
  min-width: 148px;
  padding: 6px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  background: var(--am-surface);
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.16);
  display: grid;
  gap: 2px;
}

.app-row-menu__item {
  width: 100%;
  text-align: left;
  border: none;
  border-radius: 6px;
  padding: 8px 10px;
  background: transparent;
  color: var(--am-text-strong);
  font-size: 13px;
  cursor: pointer;
}

.app-row-menu__item:hover:not(:disabled) {
  background: var(--am-hover-surface);
}

.app-row-menu__item:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.app-row-menu__item.is-danger {
  color: #dc2626;
}
</style>
