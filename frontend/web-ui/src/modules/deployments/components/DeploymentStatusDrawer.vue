<template>
  <SideDrawer
    :open="open"
    :title="deployment ? displayName : t('deploymentOps.statusDetailsTitle')"
    :close-label="t('common.close')"
    panel-class="deployment-status-drawer"
    @close="emit('close')"
  >
    <template v-if="deployment">
      <div class="deployment-status-drawer__subhead">
        <span class="drawer-status-dot-label" :class="`drawer-status-dot-label--${summaryTone}`">
          <span class="drawer-status-dot" aria-hidden="true" />
          <span>{{ summaryLabel }}</span>
        </span>
        <span class="drawer-mode-chip">{{ modeLabel }}</span>
        <div class="drawer-id-copy">
          <button
            type="button"
            class="drawer-id-copy__btn"
            data-deployment-action="copy-id"
            :aria-label="`${t('deploymentWorkspace.actions.copyId')}: ${deployment.deployment_instance_id}`"
            @click="copyText(deployment.deployment_instance_id, 'id')"
          >
            <Check v-if="copiedKey === 'id'" :size="14" class="is-copied" aria-hidden="true" />
            <Copy v-else :size="14" aria-hidden="true" />
          </button>
          <div class="drawer-id-copy__tooltip" role="tooltip">
            <div>
              <span>{{ t('deploymentOps.fields.deploymentId') }}</span>
              <code>{{ deployment.deployment_instance_id }}</code>
            </div>
            <div v-if="deployment.model_build_id">
              <span>{{ t('deploymentOps.fields.modelBuildId') }}</span>
              <code>{{ deployment.model_build_id }}</code>
            </div>
            <div v-if="deployment.runtime_profile_id">
              <span>{{ t('deploymentOps.fields.runtimeProfileId') }}</span>
              <code>{{ deployment.runtime_profile_id }}</code>
            </div>
          </div>
        </div>
      </div>

      <TabList
        :tabs="tabs"
        :model-value="activeTab"
        variant="underline"
        :label="t('deploymentOps.statusDetailsTitle')"
        @update:model-value="setActiveTab"
      />

      <!-- 1. 概览 -->
      <div v-if="activeTab === 'overview'" class="deployment-status-drawer__panel">
        <section class="deployment-status-drawer__section">
          <h3>{{ t('deploymentOps.instanceDetailsTitle') }}</h3>

          <dl class="drawer-kv-list">
            <div>
              <dt>{{ t('deploymentOps.source.title') }}</dt>
              <dd class="drawer-source-dd">
                <RouterLink
                  class="drawer-source-link"
                  :to="{ path: '/models', query: { tab: 'models', model: deployment.model_id, version: deployment.model_version_id } }"
                >
                  <span>{{ sourceInfo.modelName }}</span>
                  <template v-if="sourceInfo.versionLabel">
                    <span class="drawer-source-sep" aria-hidden="true">·</span>
                    <span class="drawer-version-chip">{{ sourceInfo.versionLabel }}</span>
                  </template>
                </RouterLink>
                <span class="drawer-kv-sep">/</span>
                <span>{{ formatDeploymentBackend(deployment.runtime_backend) }} {{ (deployment.runtime_precision || 'fp32').toUpperCase() }}</span>
              </dd>
            </div>
            <div>
              <dt>{{ t('deploymentWorkspace.columns.runtimeDevice') }}</dt>
              <dd class="drawer-runtime-dd">
                <DeploymentRuntimeBadge
                  :backend="deployment.runtime_backend"
                  :device="deployment.device_name"
                  :precision="deployment.runtime_precision"
                  backend-only
                />
                <span>{{ runtimeDeviceText }}</span>
              </dd>
            </div>
            <div>
              <dt>{{ t('deploymentWorkspace.columns.capacity') }}</dt>
              <dd>
                <template v-if="health">
                  {{ t('deploymentWorkspace.capacity.readyLabel', { ready: capacity.ready, total: capacity.total }) }}
                  <span class="drawer-kv-sep">|</span>
                  {{ t('deploymentWorkspace.capacity.executingLabel', { busy: capacity.busy, total: capacity.total }) }}
                </template>
                <template v-else>
                  {{ deployment.runtime_configuration.execution.instance_count }}
                </template>
              </dd>
            </div>
          </dl>
        </section>

        <hr class="drawer-divider" />

        <section class="deployment-status-drawer__section">
          <h3>{{ t('deploymentWorkspace.drawer.serviceChecksTitle') }}</h3>
          <div class="drawer-check-rows">
            <div v-for="row in overviewCheckRows" :key="row.label" class="drawer-check-row">
              <span class="drawer-check-row__left">
                <CheckCircle2 v-if="row.tone === 'success'" :size="16" class="drawer-check-icon is-success" />
                <XCircle v-else-if="row.tone === 'danger'" :size="16" class="drawer-check-icon is-danger" />
                <MinusCircle v-else :size="16" class="drawer-check-icon is-neutral" />
                <span>{{ row.label }}</span>
              </span>
              <span class="drawer-check-row__right" :class="`is-${row.tone}`">{{ row.statusText }}</span>
            </div>
            <div v-if="lastUpdatedTimestamp" class="drawer-meta-inline">
              <span>{{ t('deploymentWorkspace.columns.updatedAt') }}</span>
              <span>{{ formatSystemDateTime(lastUpdatedTimestamp) }}</span>
            </div>
          </div>
        </section>

        <hr class="drawer-divider" />

        <section class="deployment-status-drawer__section">
          <div class="drawer-section-head">
            <h3>{{ t('deploymentWorkspace.drawer.runtimeStatsTitle') }}</h3>
            <span class="drawer-section-meta">{{ t('deploymentWorkspace.drawer.sinceStart') }}</span>
          </div>

          <div class="drawer-stats-grid">
            <div>
              <span>{{ t('deploymentWorkspace.drawer.completedRequests') }}</span>
              <strong>{{ runtimeStats.completed }}</strong>
            </div>
            <div>
              <span>{{ t('deploymentWorkspace.drawer.successCount') }}</span>
              <strong class="is-success">{{ runtimeStats.success }}</strong>
            </div>
            <div>
              <span>{{ t('deploymentWorkspace.drawer.failedRequests') }}</span>
              <strong :class="{ 'is-danger': runtimeStats.failed !== '—' && Number(runtimeStats.failed) > 0 }">{{ runtimeStats.failed }}</strong>
            </div>
            <div>
              <span>{{ t('deploymentWorkspace.drawer.inFlight') }}</span>
              <strong>{{ runtimeStats.inFlight }}</strong>
            </div>
          </div>

          <InlineMessage v-if="capacity.isFull" tone="info">{{ t('deploymentWorkspace.capacity.busyNote') }}</InlineMessage>
        </section>

        <hr class="drawer-divider" />

        <section class="deployment-status-drawer__section">
          <h3>{{ t('deploymentWorkspace.drawer.runtimeInfoTitle') }}</h3>
          <dl class="drawer-kv-list">
            <div>
              <dt>{{ t('deploymentOps.fields.processId') }}</dt>
              <dd>{{ status?.process_id ?? '—' }}</dd>
            </div>
            <div>
              <dt>{{ t('deploymentOps.fields.warmedInstances') }}</dt>
              <dd>{{ health ? `${capacity.warmed} / ${capacity.total}` : '—' }}</dd>
            </div>
            <div>
              <dt>{{ t('deploymentOps.runtimeConfig.keepWarm') }}</dt>
              <dd>{{ keepWarmLabel }}</dd>
            </div>
            <div>
              <dt>{{ t('deploymentWorkspace.columns.taskType') }}</dt>
              <dd>{{ modelTaskLabel(deployment.task_type, zh) }}</dd>
            </div>
          </dl>
        </section>
      </div>

      <!-- 2. 运行配置 -->
      <div v-else-if="activeTab === 'runtimeConfig'" class="deployment-status-drawer__panel">
        <section class="deployment-status-drawer__section">
          <h3>{{ t('deploymentWorkspace.transfers.basicInfoTitle') }}</h3>
          <dl class="drawer-kv-list">
            <div>
              <dt>{{ t('deploymentOps.source.title') }}</dt>
              <dd class="drawer-source-dd">
                <span>{{ sourceInfo.modelName }}</span>
                <template v-if="sourceInfo.versionLabel">
                  <span class="drawer-source-sep" aria-hidden="true">·</span>
                  <span class="drawer-version-chip">{{ sourceInfo.versionLabel }}</span>
                </template>
                <span class="drawer-kv-sep">/</span>
                <span>{{ formatDeploymentBackend(deployment.runtime_backend) }} {{ (deployment.runtime_precision || 'fp32').toUpperCase() }}</span>
              </dd>
            </div>
            <div>
              <dt>{{ t('deploymentWorkspace.columns.runtimeDevice') }}</dt>
              <dd class="drawer-runtime-dd">
                <DeploymentRuntimeBadge
                  :backend="deployment.runtime_backend"
                  :device="deployment.device_name"
                  :precision="deployment.runtime_precision"
                  backend-only
                />
                <span>{{ runtimeDeviceText }}</span>
              </dd>
            </div>
            <div>
              <dt>{{ t('deploymentOps.fields.instanceCount') }}</dt>
              <dd>{{ deployment.runtime_configuration.execution.instance_count }}</dd>
            </div>
          </dl>
        </section>

        <section v-if="cpuResourceSummary" class="deployment-status-drawer__section">
          <dl class="deployment-status-drawer__grid">
            <div>
              <dt>{{ t('deploymentOps.fields.cpuDeploymentThreadCapacity') }}</dt>
              <dd>{{ cpuResourceSummary.deploymentThreadCapacity }} / {{ cpuResourceSummary.physicalCoreCount }}</dd>
            </div>
            <div>
              <dt>{{ t('deploymentOps.fields.cpuThreadsPerInstance') }}</dt>
              <dd>{{ cpuResourceSummary.threadsPerInstance }}</dd>
            </div>
            <div>
              <dt>{{ t('deploymentOps.fields.cpuSchedulingPolicy') }}</dt>
              <dd>{{ t('deploymentOps.fields.cpuSchedulingPolicyShared') }}</dd>
            </div>
          </dl>
        </section>

        <section class="deployment-status-drawer__section">
          <h3>{{ t('deploymentWorkspace.drawer.effectiveConfigTitle') }}</h3>
          <div v-if="comparisonRows.length" class="drawer-table-card">
            <table>
              <colgroup>
                <col style="width: 40%" />
                <col style="width: 30%" />
                <col style="width: 30%" />
              </colgroup>
              <thead>
                <tr>
                  <th :title="t('deploymentWorkspace.drawer.configTable.field')">{{ t('deploymentWorkspace.drawer.configTable.field') }}</th>
                  <th :title="t('deploymentWorkspace.drawer.configTable.requested')">{{ t('deploymentWorkspace.drawer.configTable.requested') }}</th>
                  <th :title="t('deploymentWorkspace.drawer.configTable.effective')">{{ t('deploymentWorkspace.drawer.configTable.effective') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in comparisonRows" :key="`${row.group}-${row.field}`" :class="{ 'is-config-changed': row.changed }">
                  <td :title="row.fieldLabel">{{ row.fieldLabel }}</td>
                  <td :title="row.requestedLabel">{{ row.requestedLabel }}</td>
                  <td :title="row.effectiveLabel">{{ row.effectiveLabel }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="sanitizedConfigWarnings.length" class="drawer-warning-strip" role="note">
            <AlertCircle :size="15" class="drawer-warning-strip__icon" aria-hidden="true" />
            <ul>
              <li v-for="warning in sanitizedConfigWarnings" :key="warning">{{ warning }}</li>
            </ul>
          </div>
        </section>

        <div v-if="health" class="runtime-configuration-diagnostics">
          <details>
            <summary>{{ t('deploymentOps.runtimeDiagnostics.requested') }}</summary>
            <pre>{{ formatRuntimeConfiguration(health.requested_runtime_configuration) }}</pre>
          </details>
          <details>
            <summary>{{ t('deploymentOps.runtimeDiagnostics.effective') }}</summary>
            <pre>{{ formatRuntimeConfiguration(health.effective_runtime_configuration) }}</pre>
          </details>
        </div>
      </div>

      <!-- 3. 接口 -->
      <div v-else-if="activeTab === 'interface'" class="deployment-status-drawer__panel">
        <section class="deployment-status-drawer__section">
          <h3>{{ t('deploymentWorkspace.drawer.contractTitle') }}</h3>
          <dl class="drawer-boxed-kv">
            <div>
              <dt>{{ t('deploymentWorkspace.columns.taskType') }}</dt>
              <dd>{{ deployment.task_type }}（{{ modelTaskLabel(deployment.task_type, zh) }}）</dd>
            </div>
            <div>
              <dt>{{ t('deploymentOps.fields.inputSize') }}</dt>
              <dd>
                <strong>{{ inputSizeLabel }}</strong>
              </dd>
            </div>
            <div>
              <dt>{{ t('deploymentWorkspace.drawer.outputsTitle') }}</dt>
              <dd>{{ outputContractText }}</dd>
            </div>
            <div>
              <dt>{{ t('deploymentWorkspace.drawer.classesCount') }}</dt>
              <dd>{{ deployment.labels.length }}</dd>
            </div>
            <div class="deployment-status-drawer__copy-row">
              <dt>{{ t('deploymentWorkspace.drawer.httpEndpoint') }}</dt>
              <dd class="deployment-status-drawer__copy-row">
                <code class="drawer-mono-id">{{ inferEndpoint }}</code>
                <Button size="sm" variant="ghost" @click="copyText(inferEndpoint, 'endpoint')">
                  <Copy :size="13" />{{ copiedKey === 'endpoint' ? t('deploymentWorkspace.actions.copied') : t('deploymentWorkspace.actions.copyEndpoint') }}
                </Button>
              </dd>
            </div>
          </dl>
          <div v-if="deployment.labels.length" class="drawer-labels-block">
            <h4 class="drawer-sub-heading">{{ t('deploymentWorkspace.drawer.classesList') }} ({{ deployment.labels.length }})</h4>
            <TrainingCategoryList :categories="deployment.labels" :label="t('deploymentWorkspace.drawer.classesList')" />
          </div>
        </section>

        <section class="deployment-status-drawer__section">
          <h3>{{ t('deploymentWorkspace.drawer.callModesTitle') }}</h3>
          <div class="drawer-table-card">
            <table>
              <colgroup>
                <col style="width: 34%" />
                <col style="width: 66%" />
              </colgroup>
              <thead>
                <tr>
                  <th :title="t('deploymentWorkspace.drawer.callModeColumn')">{{ t('deploymentWorkspace.drawer.callModeColumn') }}</th>
                  <th :title="t('deploymentWorkspace.drawer.callModeNoteColumn')">{{ t('deploymentWorkspace.drawer.callModeNoteColumn') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td :title="t('deploymentWorkspace.drawer.callModeHttp')"><strong>{{ t('deploymentWorkspace.drawer.callModeHttp') }}</strong></td>
                  <td :title="t('deploymentWorkspace.drawer.callModeHttpDesc')">{{ t('deploymentWorkspace.drawer.callModeHttpDesc') }}</td>
                </tr>
                <tr>
                  <td :title="t('deploymentWorkspace.drawer.callModeShm')"><strong>{{ t('deploymentWorkspace.drawer.callModeShm') }}</strong></td>
                  <td :title="t('deploymentWorkspace.drawer.callModeTriggerDesc')">{{ t('deploymentWorkspace.drawer.callModeTriggerDesc') }}</td>
                </tr>
                <tr>
                  <td :title="t('deploymentWorkspace.drawer.callModeZmq')"><strong>{{ t('deploymentWorkspace.drawer.callModeZmq') }}</strong></td>
                  <td :title="t('deploymentWorkspace.drawer.callModeTriggerDesc')">{{ t('deploymentWorkspace.drawer.callModeTriggerDesc') }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="deployment-status-drawer__section">
          <h3>{{ t('deploymentWorkspace.drawer.sdkTitle') }}</h3>
          <div class="drawer-example-actions">
            <span>{{ t('deploymentWorkspace.drawer.examplesLabel') }}</span>
            <Button size="sm" variant="secondary" @click="showInterfaceSpec = !showInterfaceSpec">
              <FileText :size="14" />
              {{ showInterfaceSpec ? t('deploymentWorkspace.actions.hideInterfaceSpec') : t('deploymentWorkspace.actions.viewInterfaceSpec') }}
            </Button>
            <Button size="sm" variant="secondary" @click="copyText(curlExample, 'code')">
              <Copy :size="14" />
              {{ copiedKey === 'code' ? t('deploymentWorkspace.actions.copied') : t('deploymentWorkspace.actions.copyCode') }}
            </Button>
          </div>
          <pre v-if="showInterfaceSpec" class="drawer-code-preview">{{ curlExample }}</pre>
        </section>
      </div>

      <!-- 4. 诊断 -->
      <div v-else-if="activeTab === 'diagnostics'" class="deployment-status-drawer__panel">
        <section class="deployment-status-drawer__section">
          <h3>{{ t('deploymentWorkspace.drawer.statusChecksTitle') }}</h3>
          <div class="drawer-check-rows">
            <div v-for="row in diagnosticCheckRows" :key="row.label" class="drawer-check-row">
              <span class="drawer-check-row__left">
                <CheckCircle2 v-if="row.tone === 'success'" :size="16" class="drawer-check-icon is-success" />
                <XCircle v-else-if="row.tone === 'danger'" :size="16" class="drawer-check-icon is-danger" />
                <MinusCircle v-else :size="16" class="drawer-check-icon is-neutral" />
                <span>{{ row.label }}</span>
              </span>
              <span class="drawer-check-row__right" :class="`is-${row.tone}`">{{ row.statusText }}</span>
            </div>
            <div class="drawer-meta-inline">
              <span>{{ t('deploymentWorkspace.columns.updatedAt') }}</span>
              <span>{{ lastUpdatedTimestamp ? formatSystemDateTime(lastUpdatedTimestamp) : '—' }}</span>
            </div>
          </div>
        </section>

        <section class="deployment-status-drawer__section">
          <div class="drawer-section-head">
            <h3>{{ t('deploymentWorkspace.drawer.diagnosticEventsTitle') }}</h3>
            <div class="deployment-diagnostics-actions">
              <Button size="sm" variant="secondary" :disabled="!canWarmup" @click="emit('warmup', deployment.deployment_instance_id)">
                <Zap :size="14" />{{ t('deploymentOps.actions.warmup') }}
              </Button>
              <Button size="sm" variant="secondary" :disabled="!canReset" @click="emit('reset', deployment.deployment_instance_id)">
                <RotateCcw :size="14" />{{ t('deploymentOps.actions.reset') }}
              </Button>
            </div>
          </div>

          <InlineMessage v-if="eventsLoading" :message="t('deploymentOps.messages.eventsLoading')" />
          <div v-else-if="sortedEvents.length === 0" class="drawer-empty-state">
            <Activity :size="26" class="drawer-empty-state__icon" aria-hidden="true" />
            <span class="drawer-empty-state__text">{{ t('deploymentOps.emptyEventsTitle') }}</span>
          </div>
          <div v-else class="drawer-table-card">
            <table>
              <colgroup>
                <col style="width: 28%" />
                <col style="width: 16%" />
                <col style="width: 56%" />
              </colgroup>
              <thead>
                <tr>
                  <th :title="t('deploymentWorkspace.drawer.eventTime')">{{ t('deploymentWorkspace.drawer.eventTime') }}</th>
                  <th :title="t('deploymentWorkspace.drawer.eventLevel')">{{ t('deploymentWorkspace.drawer.eventLevel') }}</th>
                  <th :title="t('deploymentWorkspace.drawer.eventMessage')">{{ t('deploymentWorkspace.drawer.eventMessage') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="event in sortedEvents" :key="`${event.runtime_mode}-${event.sequence}`">
                  <td class="drawer-time-cell" :title="formatSystemDateTime(event.created_at)">{{ formatSystemDateTime(event.created_at) }}</td>
                  <td :title="isErrorEvent(event) ? t('deploymentWorkspace.drawer.eventErrorLevel') : t('deploymentWorkspace.drawer.eventInfoLevel')">
                    <span class="drawer-event-level" :class="isErrorEvent(event) ? 'is-error' : 'is-info'">
                      <span class="drawer-event-badge" aria-hidden="true">
                        <X v-if="isErrorEvent(event)" :size="11" />
                        <span v-else>i</span>
                      </span>
                      <span>{{ isErrorEvent(event) ? t('deploymentWorkspace.drawer.eventErrorLevel') : t('deploymentWorkspace.drawer.eventInfoLevel') }}</span>
                    </span>
                  </td>
                  <td :title="event.message ? `${event.event_type} · ${event.message}` : event.event_type">
                    <strong>{{ event.event_type }}</strong>
                    <span v-if="event.message" class="drawer-event-msg"> · {{ event.message }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section v-if="lastErrorText" class="deployment-status-drawer__section">
          <h3>{{ t('deploymentWorkspace.drawer.lastErrorTitle') }}</h3>
          <div class="drawer-error-callout">
            <span>{{ lastErrorText }}</span>
            <Button size="sm" variant="secondary" @click="copyText(lastErrorText, 'error')">
              <Copy :size="13" />{{ copiedKey === 'error' ? t('deploymentWorkspace.actions.copied') : t('common.copy') }}
            </Button>
          </div>
        </section>

        <details v-if="status || health" class="drawer-accordion">
          <summary>{{ t('deploymentWorkspace.drawer.fullLogsSummary') }}</summary>
          <div class="drawer-accordion__body">
            <dl class="drawer-kv-list">
              <div><dt>{{ t('deploymentOps.fields.runtimeMode') }}</dt><dd>{{ status?.runtime_mode || deployment.runtime_execution_mode }}</dd></div>
              <div><dt>{{ t('deploymentOps.fields.processState') }}</dt><dd>{{ status?.process_state || '—' }}</dd></div>
              <div><dt>{{ t('deploymentOps.fields.generation') }}</dt><dd>{{ status?.generation ?? '—' }}</dd></div>
              <div><dt>{{ t('deploymentOps.fields.processId') }}</dt><dd>{{ status?.process_id ?? '—' }}</dd></div>
              <div><dt>{{ t('deploymentOps.fields.pinnedBytes') }}</dt><dd>{{ health?.pinned_output_total_bytes ?? '—' }}</dd></div>
            </dl>
          </div>
        </details>
      </div>

      <!-- 5. 引用 -->
      <div v-else-if="activeTab === 'references'" class="deployment-status-drawer__panel">
        <section class="deployment-status-drawer__section">
          <h3>{{ t('deploymentWorkspace.drawer.referencesTitle') }}</h3>

          <label v-if="references.length > 0" class="drawer-ref-search">
            <Search :size="14" aria-hidden="true" />
            <input
              v-model.trim="referenceQuery"
              :placeholder="t('deploymentWorkspace.drawer.referencesSearchPlaceholder')"
            />
          </label>

          <LoadingPanel v-if="referencesLoading" compact :title="t('deploymentWorkspace.drawer.referencesTitle')" />
          <div v-else-if="referencesError" class="deployment-references__error">
            <InlineError :message="t('deploymentWorkspace.drawer.referencesError')" />
            <Button size="sm" variant="secondary" @click="loadReferences">{{ t('deploymentWorkspace.actions.retry') }}</Button>
          </div>
          <div v-else-if="filteredReferences.length === 0" class="drawer-empty-state">
            <Link2 :size="26" class="drawer-empty-state__icon" aria-hidden="true" />
            <span class="drawer-empty-state__text">{{ t('deploymentWorkspace.drawer.referencesEmpty') }}</span>
          </div>
          <div v-else class="drawer-table-card">
            <table>
              <colgroup>
                <col style="width: 34%" />
                <col style="width: 24%" />
                <col style="width: 26%" />
                <col style="width: 16%" />
              </colgroup>
              <thead>
                <tr>
                  <th :title="t('deploymentWorkspace.drawer.referenceObject')">{{ t('deploymentWorkspace.drawer.referenceObject') }}</th>
                  <th :title="t('deploymentWorkspace.drawer.referenceRelation')">{{ t('deploymentWorkspace.drawer.referenceRelation') }}</th>
                  <th :title="t('deploymentWorkspace.columns.status')">{{ t('deploymentWorkspace.columns.status') }}</th>
                  <th :title="t('deploymentWorkspace.columns.actions')">{{ t('deploymentWorkspace.columns.actions') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="refItem in filteredReferences" :key="refItem.workflow_runtime_id">
                  <td :title="refItem.display_name || refItem.workflow_runtime_id"><strong>{{ refItem.display_name || refItem.workflow_runtime_id }}</strong></td>
                  <td :title="t('deploymentWorkspace.drawer.referenceRelationDirect')">{{ t('deploymentWorkspace.drawer.referenceRelationDirect') }}</td>
                  <td :title="referenceStateLabel(refItem.observed_state)">
                    <span class="drawer-status-dot-label" :class="refItem.observed_state === 'running' ? 'drawer-status-dot-label--success' : 'drawer-status-dot-label--neutral'">
                      <span class="drawer-status-dot" aria-hidden="true" />
                      <span>{{ referenceStateLabel(refItem.observed_state) }}</span>
                    </span>
                  </td>
                  <td>
                    <RouterLink class="drawer-action-link" :to="{ path: '/applications', query: { runtime: refItem.workflow_runtime_id } }">
                      {{ t('deploymentWorkspace.actions.view') }}
                    </RouterLink>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </template>

    <template v-if="deployment" #footer>
      <div class="drawer-footer">
        <div class="drawer-footer__left">
          <Button
            v-if="activeTab === 'overview' && canStop"
            variant="secondary"
            size="sm"
            @click="emit('stop', deployment.deployment_instance_id)"
          >
            <Square :size="13" />{{ t('deploymentOps.actions.stop') }}
          </Button>
          <Button
            v-if="activeTab !== 'overview' || !canStop"
            variant="secondary"
            size="sm"
            @click="emit('close')"
          >
            {{ t('common.close') }}
          </Button>
        </div>

        <div class="drawer-footer__right">
          <Button
            v-if="activeTab === 'diagnostics'"
            variant="primary"
            size="sm"
            :loading="eventsLoading"
            @click="emit('recheck', deployment.deployment_instance_id)"
          >
            <RefreshCw :size="14" />{{ t('deploymentWorkspace.actions.recheck') }}
          </Button>
          <Button
            v-else-if="activeTab === 'references' && canStop"
            variant="danger"
            size="sm"
            @click="emit('stop', deployment.deployment_instance_id)"
          >
            {{ t('deploymentOps.actions.stop') }}
          </Button>
          <Button
            v-else-if="isStopped && canStart"
            variant="primary"
            size="sm"
            @click="emit('start', deployment.deployment_instance_id)"
          >
            <Play :size="14" />{{ t('deploymentOps.actions.start') }}
          </Button>
          <ButtonLink
            v-else
            variant="primary"
            size="sm"
            :to="{ path: '/inference', query: { deployment: deployment.deployment_instance_id, task: deployment.task_type || 'detection' } }"
          >
            <ExternalLink :size="14" />{{ t('deploymentWorkspace.actions.openInference') }}
          </ButtonLink>
        </div>
      </div>
    </template>
  </SideDrawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import {
  Activity,
  AlertCircle,
  Check,
  CheckCircle2,
  Copy,
  ExternalLink,
  FileText,
  Link2,
  MinusCircle,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  Square,
  X,
  XCircle,
  Zap,
} from '@lucide/vue'
import { useCatalogVersionLabel } from '@/modules/models/composables/useCatalogVersionLabel'
import TrainingCategoryList from '@/modules/models/components/TrainingCategoryList.vue'
import { modelTaskLabel } from '@/modules/models/model-evaluation-types'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import ButtonLink from '@/shared/ui/components/ButtonLink.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import InlineMessage from '@/shared/ui/feedback/InlineMessage.vue'
import LoadingPanel from '@/shared/ui/feedback/LoadingPanel.vue'
import TabList from '@/shared/ui/navigation/TabList.vue'
import {
  buildDeploymentConfigComparisonRows,
  computeDeploymentCapacity,
  formatDeploymentBackend,
  formatDeploymentDeviceName,
} from '../deployment-presentation'
import { listDeploymentReferences, type DeploymentReferenceItem } from '../services/deployment-transfer.service'
import DeploymentRuntimeBadge from './DeploymentRuntimeBadge.vue'
import type {
  TaskDeploymentInstance,
  TaskDeploymentProcessEvent,
  TaskDeploymentProcessStatus,
  TaskDeploymentRuntimeHealth,
} from '../services/deployment.service'

interface CpuResourceSummary {
  physicalCoreCount: number
  deploymentThreadCapacity: number
  threadsPerInstance: number
}

type StatusBadgeTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info'
export type DeploymentStatusDrawerTab = 'overview' | 'runtimeConfig' | 'interface' | 'diagnostics' | 'references'

const props = defineProps<{
  open: boolean
  initialTab?: DeploymentStatusDrawerTab
  deployment: TaskDeploymentInstance | null
  status: TaskDeploymentProcessStatus | null
  health: TaskDeploymentRuntimeHealth | null
  cpuResourceSummary: CpuResourceSummary | null
  events: TaskDeploymentProcessEvent[]
  eventsLoading: boolean
  displayName: string
  summaryLabel: string
  summaryTone: StatusBadgeTone
  versionLabelsById?: Record<string, { modelName: string; versionLabel: string }>
  canWarmup?: boolean
  canReset?: boolean
  canStart?: boolean
  canStop?: boolean
}>()

const emit = defineEmits<{
  close: []
  start: [deploymentId: string]
  stop: [deploymentId: string]
  warmup: [deploymentId: string]
  reset: [deploymentId: string]
  recheck: [deploymentId: string]
  'refresh-events': []
}>()

const { t, te, locale } = useI18n()
const zh = computed(() => locale.value.startsWith('zh'))
const activeTab = ref<DeploymentStatusDrawerTab>('overview')
const copiedKey = ref('')
const showInterfaceSpec = ref(false)
const referenceQuery = ref('')
const references = ref<DeploymentReferenceItem[]>([])
const referencesLoading = ref(false)
const referencesError = ref(false)
let refSequence = 0

const modelVersionName = useCatalogVersionLabel(() => [
  props.open && !(props.deployment?.model_version_id && props.versionLabelsById?.[props.deployment.model_version_id])
    ? props.deployment?.project_id
    : undefined,
  props.deployment?.task_type,
  props.deployment?.model_version_id,
])

const sourceInfo = computed(() => {
  const dep = props.deployment
  if (!dep) return { modelName: '', versionLabel: '' }
  const entry = dep.model_version_id ? props.versionLabelsById?.[dep.model_version_id] : undefined
  const catalogLabel = modelVersionName.value.trim()
  let catalogModelName = ''
  let catalogVersionLabel = ''
  if (catalogLabel) {
    const parts = catalogLabel.split(' · ')
    if (parts.length >= 2) {
      catalogModelName = parts[0] || ''
      catalogVersionLabel = parts.slice(1).join(' · ')
    } else if (catalogLabel !== dep.model_name) {
      catalogVersionLabel = catalogLabel
    }
  }
  const modelName = dep.model_display_name?.trim() || entry?.modelName || catalogModelName || dep.model_name
  const versionLabel = dep.model_version_number
    ? `v${dep.model_version_number}`
    : entry?.versionLabel || catalogVersionLabel || ''
  return { modelName, versionLabel }
})

const tabs = computed(() => [
  { id: 'overview', label: t('deploymentWorkspace.drawer.tabs.overview') },
  { id: 'runtimeConfig', label: t('deploymentWorkspace.drawer.tabs.runtimeConfig') },
  { id: 'interface', label: t('deploymentWorkspace.drawer.tabs.interface') },
  { id: 'diagnostics', label: t('deploymentWorkspace.drawer.tabs.diagnostics') },
  { id: 'references', label: t('deploymentWorkspace.drawer.tabs.references') },
])

function setActiveTab(value: string): void {
  if (['overview', 'runtimeConfig', 'interface', 'diagnostics', 'references'].includes(value)) {
    activeTab.value = value as DeploymentStatusDrawerTab
  }
}

watch(() => [props.open, props.deployment?.deployment_instance_id, props.initialTab] as const, ([open, , initialTab]) => {
  copiedKey.value = ''
  showInterfaceSpec.value = false
  referenceQuery.value = ''
  references.value = []
  referencesError.value = false
  if (open && initialTab) {
    activeTab.value = initialTab
  } else if (!open) {
    activeTab.value = 'overview'
  }
})

watch(() => [props.open, activeTab.value, props.deployment?.deployment_instance_id] as const, ([open, tab, id]) => {
  if (open && tab === 'references' && id && props.deployment?.project_id) {
    void loadReferences()
  }
})

async function loadReferences(): Promise<void> {
  const deployment = props.deployment
  if (!deployment?.project_id) return
  const seq = ++refSequence
  referencesLoading.value = true
  referencesError.value = false
  try {
    const res = await listDeploymentReferences(deployment.project_id, deployment.deployment_instance_id)
    if (seq !== refSequence) return
    references.value = res.items
  } catch {
    if (seq === refSequence) referencesError.value = true
  } finally {
    if (seq === refSequence) referencesLoading.value = false
  }
}

const filteredReferences = computed(() => {
  const term = referenceQuery.value.toLowerCase()
  if (!term) return references.value
  return references.value.filter(item =>
    `${item.display_name || ''} ${item.workflow_runtime_id} ${item.application_id}`.toLowerCase().includes(term),
  )
})

const sortedEvents = computed(() => [...props.events].sort(compareEventsNewestFirst))

const modeLabel = computed(() => {
  const mode = props.status?.runtime_mode || props.deployment?.runtime_execution_mode || 'sync'
  return t(`deploymentOps.runtimeModes.${mode === 'async' ? 'async' : 'sync'}`)
})

const runtimeDeviceText = computed(() => {
  if (!props.deployment) return '—'
  const backend = formatDeploymentBackend(props.deployment.runtime_backend || 'pytorch')
  const device = formatDeploymentDeviceName(props.deployment.device_name) || t('deploymentOps.options.automaticDefault')
  return `${backend} · ${device}`
})

const lastUpdatedTimestamp = computed(() => (
  sortedEvents.value[0]?.created_at || props.deployment?.updated_at || ''
))

const isStopped = computed(() => {
  const p = String(props.status?.process_state ?? '').toLowerCase()
  const o = String(props.status?.observed_state ?? '').toLowerCase()
  return p === 'stopped' || o === 'stopped' || !props.status
})

const inputSizeLabel = computed(() => {
  const inputSize = props.deployment?.input_size
  return inputSize ? `${inputSize.width} × ${inputSize.height}` : '—'
})

const outputContractText = computed(() => {
  const task = String(props.deployment?.task_type || 'detection').trim().toLowerCase()
  const key = `deploymentWorkspace.drawer.outputContracts.${task}`
  return te(key) ? t(key) : t('deploymentWorkspace.drawer.outputContracts.detection')
})

function referenceStateLabel(state: string): string {
  if (state === 'running') return t('deploymentWorkspace.drawer.referenceStateRunning')
  if (state === 'stopped') return t('deploymentWorkspace.drawer.referenceStateStopped')
  return t('deploymentWorkspace.drawer.referenceStateOther', { state })
}

const keepWarmLabel = computed(() => {
  if (!props.deployment) return '—'
  const lifecycle = props.deployment.runtime_configuration.lifecycle
  if (!lifecycle.keep_warm_enabled) return t('deploymentOps.options.disabled')
  return `${t('deploymentOps.options.enabled')} · ${lifecycle.keep_warm_interval_seconds ?? 0.1} s`
})

const capacity = computed(() => props.deployment
  ? computeDeploymentCapacity(props.deployment, props.health)
  : { total: 0, ready: 0, warmed: 0, busy: 0, isFull: false })

const runtimeStats = computed(() => {
  if (!props.health || isStopped.value) {
    return { completed: '—', success: '—', failed: '—', inFlight: '—' }
  }
  const units = Array.isArray(props.health.instances) ? props.health.instances : []
  const success = units.reduce((sum, u) => sum + Number(u.inference_count ?? 0), 0)
  const failed = units.reduce((sum, u) => sum + Number(u.error_count ?? 0), 0)
  return {
    completed: String(success + failed),
    success: String(success),
    failed: String(failed),
    inFlight: String(capacity.value.busy),
  }
})

const overviewCheckRows = computed(() => {
  const procAlive = props.status?.process_state === 'running'
  const hasHealthy = (props.health?.healthy_instance_count ?? 0) > 0
  const stopped = isStopped.value
  const passedText = t('deploymentWorkspace.drawer.checkStatusPassed')
  const notRunningText = t('deploymentWorkspace.drawer.checkStatusNotRunning')
  const failedText = t('deploymentWorkspace.drawer.checkStatusFailed')
  return [
    {
      label: t('deploymentWorkspace.drawer.processAlive'),
      tone: procAlive ? 'success' : stopped ? 'neutral' : 'danger',
      statusText: procAlive ? passedText : stopped ? notRunningText : failedText,
    },
    {
      label: t('deploymentWorkspace.drawer.modelLoaded'),
      tone: hasHealthy ? 'success' : stopped ? 'neutral' : 'danger',
      statusText: hasHealthy ? passedText : stopped ? notRunningText : failedText,
    },
    {
      label: t('deploymentWorkspace.drawer.serviceAvailable'),
      tone: procAlive && hasHealthy ? 'success' : stopped ? 'neutral' : 'danger',
      statusText: procAlive && hasHealthy ? passedText : stopped ? notRunningText : failedText,
    },
  ] as const
})

const diagnosticCheckRows = computed(() => {
  const procAlive = props.status?.process_state === 'running'
  const hasHealthy = (props.health?.healthy_instance_count ?? 0) > 0
  const stopped = isStopped.value
  const hasErr = Boolean(lastErrorText.value)
  const passedText = t('deploymentWorkspace.drawer.checkStatusPassed')
  const notRunningText = t('deploymentWorkspace.drawer.checkStatusNotRunning')
  const failedText = t('deploymentWorkspace.drawer.checkStatusFailed')
  return [
    {
      label: t('deploymentWorkspace.drawer.processAlive'),
      tone: procAlive ? 'success' : stopped ? 'neutral' : 'danger',
      statusText: procAlive ? passedText : stopped ? notRunningText : failedText,
    },
    {
      label: t('deploymentWorkspace.drawer.modelLoaded'),
      tone: hasHealthy ? 'success' : stopped ? 'neutral' : 'danger',
      statusText: hasHealthy ? passedText : stopped ? notRunningText : failedText,
    },
    {
      label: t('deploymentWorkspace.drawer.interfaceProbe'),
      tone: procAlive && hasHealthy && !hasErr ? 'success' : stopped ? 'neutral' : 'danger',
      statusText: procAlive && hasHealthy && !hasErr ? passedText : stopped ? notRunningText : failedText,
    },
  ] as const
})

function localizeConfigField(field: string): string {
  const key = `deploymentWorkspace.drawer.runtimeFields.${field}`
  return te(key) ? t(key) : field.replace(/_/g, ' ')
}

function localizeConfigValue(value: string): string {
  if (!value || value === '—') return '—'
  if (value === 'true') return t('deploymentOps.options.enabled')
  if (value === 'false') return t('deploymentOps.options.disabled')
  if (value === 'auto') return t('deploymentOps.options.automatic')
  if (value === 'latency') return t('deploymentOps.options.lowestLatency')
  if (value === 'throughput') return t('deploymentOps.options.maximumThroughput')
  if (value === 'cumulative_throughput') return t('deploymentOps.options.cumulativeThroughput')
  if (value === 'none') return t('deploymentOps.options.openvinoRuntimeDefault')
  if (value === 'any_core') return t('deploymentOps.options.anyCore')
  if (value === 'pcore_only') return t('deploymentOps.options.pCoreOnly')
  if (value === 'ecore_only') return t('deploymentOps.options.eCoreOnly')
  if (value === 'session' || value === 'reject' || value === 'balanced' || value === 'default') {
    const key = `deploymentWorkspace.drawer.configValues.${value}`
    if (te(key)) return t(key)
  }
  return value
}

const comparisonRows = computed(() => {
  if (!props.deployment) return []
  const requested = props.health?.requested_runtime_configuration ?? (props.deployment.runtime_configuration as unknown as Record<string, unknown>)
  const effective = props.health?.effective_runtime_configuration ?? requested
  return buildDeploymentConfigComparisonRows(requested, effective).map(row => ({
    ...row,
    fieldLabel: localizeConfigField(row.field),
    requestedLabel: localizeConfigValue(row.requested),
    effectiveLabel: localizeConfigValue(row.effective),
  }))
})

const sanitizedConfigWarnings = computed(() => {
  const warnings = props.health?.configuration_warnings ?? []
  const rawId = props.deployment?.deployment_instance_id
  if (!rawId || !props.displayName) return warnings
  return warnings.map(item => item.split(rawId).join(props.displayName))
})

const inferEndpoint = computed(() => {
  if (!props.deployment) return ''
  const task = props.deployment.task_type || 'detection'
  return `/api/v1/models/${task}/deployment-instances/${props.deployment.deployment_instance_id}/infer`
})

const curlExample = computed(() => [
  `curl -X POST "${inferEndpoint.value}" \\`,
  `  -H "Content-Type: application/json" \\`,
  `  -d '{"input_uri": "/path/to/image.png"}'`,
].join('\n'))

const lastErrorText = computed(() => props.health?.last_error || props.status?.last_error || '')

function isErrorEvent(event: TaskDeploymentProcessEvent): boolean {
  const kind = `${event.event_type} ${event.message}`.toLowerCase()
  return kind.includes('fail') || kind.includes('error') || kind.includes('crash') || kind.includes('timeout')
}

async function copyText(value: string, key: string): Promise<void> {
  if (!value) return
  try {
    await navigator.clipboard?.writeText(value)
    copiedKey.value = key
  } catch {
    copiedKey.value = ''
  }
}

function compareEventsNewestFirst(left: TaskDeploymentProcessEvent, right: TaskDeploymentProcessEvent): number {
  const leftTime = Date.parse(left.created_at)
  const rightTime = Date.parse(right.created_at)
  const safeLeftTime = Number.isFinite(leftTime) ? leftTime : 0
  const safeRightTime = Number.isFinite(rightTime) ? rightTime : 0
  if (safeLeftTime !== safeRightTime) return safeRightTime - safeLeftTime
  return right.sequence - left.sequence
}

function formatRuntimeConfiguration(value: Record<string, unknown>): string {
  return JSON.stringify(value, null, 2)
}
</script>

<style scoped>
:global(.deployment-status-drawer.side-drawer) {
  width: min(680px, calc(100vw - 36px));
}

.deployment-status-drawer__subhead {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.drawer-status-dot-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}

.drawer-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--am-neutral-icon);
}

.drawer-status-dot-label--success { color: var(--am-action-primary-strong); }
.drawer-status-dot-label--success .drawer-status-dot { background: var(--am-action-primary); }
.drawer-status-dot-label--warning,
.drawer-status-dot-label--info { color: var(--am-warning-text); }
.drawer-status-dot-label--warning .drawer-status-dot,
.drawer-status-dot-label--info .drawer-status-dot { background: var(--am-warning-icon); }
.drawer-status-dot-label--danger { color: var(--am-danger-text); }
.drawer-status-dot-label--danger .drawer-status-dot { background: var(--am-danger-icon); }
.drawer-status-dot-label--neutral { color: var(--am-text-muted); }

.drawer-mode-chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border: 1px solid var(--am-border);
  border-radius: 4px;
  background: var(--am-surface);
  font-size: 12px;
  color: var(--am-text-muted);
}

.drawer-id-copy {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.drawer-id-copy__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  background: var(--am-surface);
  color: var(--am-text-muted);
  cursor: pointer;
}

.drawer-id-copy__btn:hover,
.drawer-id-copy__btn:focus-visible {
  border-color: var(--am-border-strong);
  color: var(--am-text);
}

.drawer-id-copy__btn .is-copied {
  color: var(--am-action-primary);
}

.drawer-id-copy__tooltip {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 30;
  display: grid;
  gap: 6px;
  min-width: 260px;
  max-width: min(460px, calc(100vw - 80px));
  padding: 8px 10px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface);
  box-shadow: var(--am-shadow-floating);
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  transition: opacity 120ms ease;
}

.drawer-id-copy:hover .drawer-id-copy__tooltip,
.drawer-id-copy:focus-within .drawer-id-copy__tooltip {
  opacity: 1;
  visibility: visible;
}

.drawer-id-copy__tooltip > div {
  display: grid;
  gap: 2px;
}

.drawer-id-copy__tooltip span {
  font-size: 11px;
  color: var(--am-text-muted);
}

.drawer-id-copy__tooltip code {
  font-family: var(--am-font-mono);
  font-size: 12px;
  color: var(--am-text-strong, var(--am-text));
  overflow-wrap: anywhere;
}

.deployment-status-drawer__panel {
  display: grid;
  gap: 16px;
  padding-top: 16px;
  min-width: 0;
  max-width: 100%;
}

.deployment-status-drawer__section {
  display: grid;
  gap: 10px;
  min-width: 0;
  max-width: 100%;
}

.deployment-status-drawer__section h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
}

.drawer-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.drawer-section-meta,
.drawer-sub-note {
  font-size: 12px;
  color: var(--am-text-muted);
  margin: 0;
}

.drawer-mono-id {
  font-family: var(--am-font-mono);
  font-size: 12.5px;
  overflow-wrap: anywhere;
}

.drawer-source-dd,
.drawer-runtime-dd {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.drawer-source-link {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}

.drawer-source-sep {
  color: var(--am-text-muted);
}

.drawer-version-chip {
  white-space: nowrap;
}

.drawer-kv-list {
  display: grid;
  gap: 8px;
  margin: 0;
  font-size: 14px;
}

.drawer-kv-list > div {
  display: grid;
  grid-template-columns: 128px minmax(0, 1fr);
  gap: 12px;
  align-items: baseline;
}

.drawer-kv-list dt {
  color: var(--am-text-muted);
}

.drawer-kv-list dd {
  margin: 0;
  font-weight: 500;
  overflow-wrap: anywhere;
}

.drawer-kv-list dd a {
  color: var(--am-action-primary-strong);
  font-weight: 600;
}

.drawer-kv-sep {
  margin: 0 6px;
  color: var(--am-border);
}

.drawer-divider {
  border: 0;
  border-top: 1px solid var(--am-border);
  margin: 0;
}

.drawer-check-rows {
  display: grid;
  gap: 10px;
}

.drawer-check-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
}

.drawer-check-row__left {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.drawer-check-icon.is-success { color: var(--am-action-primary); }
.drawer-check-icon.is-danger { color: var(--am-danger-icon); }
.drawer-check-icon.is-neutral { color: var(--am-neutral-icon); }

.drawer-check-row__right.is-success { color: var(--am-action-primary-strong); font-weight: 600; }
.drawer-check-row__right.is-danger { color: var(--am-danger-text); font-weight: 600; }
.drawer-check-row__right.is-neutral { color: var(--am-text-muted); }

.drawer-meta-inline {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  color: var(--am-text-muted);
}

.drawer-stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0;
  padding: 6px 0;
}

.drawer-stats-grid > div {
  display: grid;
  gap: 4px;
  padding: 2px 12px;
  border-right: 1px solid var(--am-border);
}

.drawer-stats-grid > div:first-child {
  padding-left: 0;
}

.drawer-stats-grid > div:last-child {
  border-right: 0;
  padding-right: 0;
}

.drawer-stats-grid span {
  font-size: 12px;
  color: var(--am-text-muted);
}

.drawer-stats-grid strong {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.drawer-stats-grid strong.is-success { color: var(--am-action-primary-strong); }
.drawer-stats-grid strong.is-danger { color: var(--am-danger-text); }

.drawer-table-card {
  border: 1px solid var(--am-border);
  border-radius: 8px;
  max-width: 100%;
  overflow-x: hidden;
}

.drawer-table-card table {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
}

.drawer-table-card th,
.drawer-table-card td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--am-border);
  text-align: left;
  vertical-align: middle;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.drawer-table-card tr:last-child td {
  border-bottom: 0;
}

.drawer-table-card th {
  background: var(--am-surface);
  color: var(--am-text);
  font-size: 14px;
  font-weight: 600;
}

.drawer-table-card td {
  font-size: 14px;
}

.drawer-boxed-kv {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 12px 14px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface);
  font-size: 13px;
}

.drawer-boxed-kv > div {
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
}

.drawer-boxed-kv dt {
  color: var(--am-text-muted);
}

.drawer-boxed-kv dd {
  margin: 0;
  display: grid;
  gap: 3px;
  overflow-wrap: anywhere;
}

.drawer-accordion {
  border: 1px solid var(--am-border);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--am-surface);
}

.drawer-accordion summary {
  cursor: pointer;
  font-weight: 600;
  font-size: 13px;
}

.drawer-accordion__body {
  margin-top: 10px;
}

.drawer-example-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--am-text-muted);
}

.drawer-code-preview {
  max-width: 100%;
  box-sizing: border-box;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface);
  font-family: var(--am-font-mono);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
  overflow-x: hidden;
  overflow-y: auto;
  max-height: 320px;
}

.drawer-time-cell {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  color: var(--am-text-muted);
}

.drawer-event-level {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--am-text);
  white-space: nowrap;
}

.drawer-event-level.is-error {
  color: var(--am-danger-text);
}

.drawer-event-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 17px;
  height: 17px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  color: #fff;
  background: var(--am-action-primary);
  flex-shrink: 0;
}

.drawer-event-level.is-error .drawer-event-badge {
  background: var(--am-danger-icon, #dc2626);
}

.drawer-event-msg {
  color: var(--am-text-muted);
}

.drawer-error-callout {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--am-danger-border);
  border-radius: 8px;
  background: var(--am-danger-surface);
  color: var(--am-danger-text);
  font-size: 13px;
}

.drawer-ref-search {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  background: var(--am-surface);
  color: var(--am-text-muted);
}

.drawer-ref-search input {
  width: 100%;
  height: 34px;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--am-text);
}

.drawer-action-link {
  color: var(--am-action-primary-strong);
  font-weight: 600;
  white-space: nowrap;
}

.drawer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.drawer-footer__left,
.drawer-footer__right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.deployment-status-drawer__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 0;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface);
  overflow: hidden;
}

.deployment-status-drawer__grid div {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 10px 14px;
  border-right: 1px solid var(--am-border);
}

.deployment-status-drawer__grid div:last-child {
  border-right: 0;
}

.deployment-status-drawer__grid dt {
  color: var(--am-text-muted);
  font-size: 12px;
}

.deployment-status-drawer__grid dd {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
}

.deployment-status-drawer__copy-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.deployment-diagnostics-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.runtime-configuration-warnings {
  display: grid;
  gap: 6px;
  padding: 10px;
  border: 1px solid var(--am-warning-border);
  border-radius: 6px;
  background: var(--am-warning-surface);
}

.runtime-configuration-warnings ul {
  margin: 0;
  padding-left: 18px;
}

.runtime-configuration-diagnostics {
  display: grid;
  gap: 8px;
  min-width: 0;
  max-width: 100%;
}

.runtime-configuration-diagnostics details {
  min-width: 0;
  max-width: 100%;
}

.runtime-configuration-diagnostics summary {
  cursor: pointer;
  color: var(--am-text-muted);
  font-weight: 600;
}

.runtime-configuration-diagnostics pre {
  max-width: 100%;
  box-sizing: border-box;
  margin: 6px 0 0;
  padding: 10px;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  background: var(--am-surface);
  font-family: var(--am-font-mono);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
  overflow-x: hidden;
  overflow-y: auto;
  max-height: 320px;
}

.is-config-changed td:last-child {
  font-weight: 700;
  color: var(--am-action-primary-strong);
}

.drawer-labels-block {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.drawer-sub-heading {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text);
}

.drawer-empty-state {
  display: grid;
  justify-items: center;
  gap: 8px;
  padding: 32px 16px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface);
  color: var(--am-text-muted);
  text-align: center;
}

.drawer-empty-state__icon {
  color: var(--am-text-muted);
  opacity: 0.72;
}

.drawer-empty-state__text {
  font-size: 13px;
  font-weight: 500;
  color: var(--am-text-muted);
}

@media (max-width: 720px) {
  .deployment-status-drawer__grid,
  .drawer-stats-grid,
  .drawer-kv-list > div,
  .drawer-boxed-kv > div {
    grid-template-columns: 1fr;
  }

  .deployment-status-drawer__grid div,
  .drawer-stats-grid > div {
    border-right: 0;
    border-bottom: 1px solid var(--am-border);
    padding: 8px 0;
  }

  .deployment-status-drawer__grid div {
    padding: 10px 12px;
  }

  .deployment-status-drawer__grid div:last-child,
  .drawer-stats-grid > div:last-child {
    border-bottom: 0;
  }
}
</style>
