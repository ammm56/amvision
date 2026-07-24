<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <h1>{{ t('settingsDiagnostics.title') }}</h1>
      </div>
      <div class="page-actions">
        <Button variant="secondary" :disabled="loading" @click="loadDiagnostics">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </div>
    </header>

    <InlineError :message="errorMessage" />

    <div class="view-tabs settings-diagnostics__tabs" role="tablist" aria-label="Settings sections">
      <button
        v-for="tab in categoryTabs"
        :key="tab.id"
        class="view-tab"
        :class="{ 'is-active': activeCategory === tab.id }"
        type="button"
        role="tab"
        :aria-selected="activeCategory === tab.id"
        @click="activeCategory = tab.id"
      >
        <component :is="tab.icon" :size="15" />
        <span>{{ tab.label }}</span>
      </button>
    </div>

    <div class="summary-grid settings-diagnostics__summary">
      <div>
        <span>{{ t('settingsDiagnostics.fields.backendStatus') }}</span>
        <strong>{{ serviceStatus }}</strong>
      </div>
      <div>
        <span>{{ t('settingsDiagnostics.fields.currentUser') }}</span>
        <strong>{{ sessionStore.displayName || sessionStore.currentUser?.principal_id || '-' }}</strong>
      </div>
      <div>
        <span>{{ t('settingsDiagnostics.fields.selectedProject') }}</span>
        <strong>{{ projectStore.selectedProjectId || '-' }}</strong>
      </div>
      <div>
        <span>{{ t('settingsDiagnostics.fields.generatedAt') }}</span>
        <strong>{{ diagnostics?.generated_at ? formatSystemDateTime(diagnostics.generated_at) : '-' }}</strong>
      </div>
    </div>

    <section v-if="activeCategory === 'preferences'" class="settings-category-panel">
      <section class="resource-section diagnostic-section">
        <div>
          <h2>{{ t('settingsDiagnostics.sections.preferences') }}</h2>
        </div>
        <div class="settings-control-grid">
          <label class="field">
            <span>{{ t('preferences.language') }}</span>
            <SelectField :model-value="preferencesStore.locale" :options="localeOptions" @update:model-value="setLocale" />
          </label>
          <div class="field">
            <span>{{ t('preferences.theme') }}</span>
            <div class="settings-segmented-control" :aria-label="t('preferences.theme')">
              <button type="button" :class="{ 'is-active': preferencesStore.theme === 'light' }" @click="setTheme('light')">
                <Sun :size="15" />
                {{ t('preferences.light') }}
              </button>
              <button type="button" :class="{ 'is-active': preferencesStore.theme === 'dark' }" @click="setTheme('dark')">
                <Moon :size="15" />
                {{ t('preferences.dark') }}
              </button>
            </div>
          </div>
        </div>
        <dl class="settings-info-list">
          <InfoRow :label="t('settingsDiagnostics.fields.currentLocale')" :value="preferencesStore.locale" />
          <InfoRow :label="t('settingsDiagnostics.fields.currentTheme')" :value="preferencesStore.theme" />
          <InfoRow :label="t('settingsDiagnostics.fields.preferenceStorage')" value="localStorage" />
          <InfoRow :label="t('settingsDiagnostics.fields.defaultProjectId')" :value="runtimeConfig.defaultProjectId" />
        </dl>
      </section>
    </section>

    <section v-else-if="activeCategory === 'services'" class="settings-category-panel">
      <section class="resource-section diagnostic-section">
        <div>
          <h2>{{ t('settingsDiagnostics.sections.services') }}</h2>
        </div>
        <div class="summary-grid">
          <div v-for="service in serviceRows" :key="service.name">
            <span>{{ service.label }}</span>
            <StatusPill :status="service.status" :label="service.statusLabel" with-dot />
          </div>
        </div>
        <dl class="settings-info-list">
          <InfoRow :label="t('settingsDiagnostics.fields.apiBaseUrl')" :value="runtimeConfig.apiBaseUrl" />
          <InfoRow :label="t('settingsDiagnostics.fields.wsBaseUrl')" :value="runtimeConfig.wsBaseUrl" />
          <InfoRow :label="t('settingsDiagnostics.fields.runMode')" :value="stringValue(about.run_mode)" />
          <InfoRow :label="t('settingsDiagnostics.fields.generatedAt')" :value="diagnostics?.generated_at ? formatSystemDateTime(diagnostics.generated_at) : '-'" />
        </dl>
      </section>

      <section class="resource-section diagnostic-section">
        <div>
          <h2>{{ t('settingsDiagnostics.sections.capabilities') }}</h2>
        </div>
        <dl class="settings-info-list">
          <InfoRow :label="t('settingsDiagnostics.fields.bearerAuth')" :value="booleanText(sessionStore.bearerAuthEnabled)" />
          <InfoRow :label="t('settingsDiagnostics.fields.websocketQueryToken')" :value="booleanText(sessionStore.websocketQueryTokenEnabled)" />
          <InfoRow :label="t('settingsDiagnostics.fields.projectBootstrapEnabled')" :value="booleanText(platformCapabilities.project_bootstrap_enabled)" />
          <InfoRow :label="t('settingsDiagnostics.fields.datasetExportDefaultFormat')" :value="stringValue(platformCapabilities.dataset_export?.default_format)" />
          <InfoRow :label="t('settingsDiagnostics.fields.datasetExportFormats')" :value="implementedDatasetFormatsText" />
          <InfoRow :label="t('settingsDiagnostics.fields.projectSummaryTopics')" :value="projectSummaryTopicsText" />
          <InfoRow :label="t('settingsDiagnostics.fields.featureFlags')" :value="enabledFeatureFlagsText" />
        </dl>
      </section>
    </section>

    <section v-else-if="activeCategory === 'security'" class="settings-category-panel">
      <section class="resource-section diagnostic-section">
        <div>
          <h2>{{ t('settingsDiagnostics.sections.security') }}</h2>
        </div>
        <dl class="settings-info-list">
          <InfoRow :label="t('settingsDiagnostics.fields.loginState')" :value="sessionStore.loginState" />
          <InfoRow :label="t('settingsDiagnostics.fields.currentUser')" :value="sessionStore.displayName || sessionStore.currentUser?.principal_id || '-'" />
          <InfoRow :label="t('settingsDiagnostics.fields.authMode')" :value="sessionStore.authMode || '-'" />
          <InfoRow :label="t('settingsDiagnostics.fields.credentialKind')" :value="sessionStore.credentialKind || '-'" />
          <InfoRow :label="t('settingsDiagnostics.fields.authProviderId')" :value="sessionStore.currentUser?.auth_provider_id || '-'" />
          <InfoRow :label="t('settingsDiagnostics.fields.authProviderKind')" :value="sessionStore.currentUser?.auth_provider_kind || '-'" />
          <InfoRow :label="t('settingsDiagnostics.fields.authCredentialId')" :value="sessionStore.currentUser?.auth_credential_id || '-'" />
          <InfoRow :label="t('settingsDiagnostics.fields.authSessionId')" :value="sessionStore.currentUser?.auth_session_id || '-'" />
          <InfoRow :label="t('settingsDiagnostics.fields.authTokenId')" :value="sessionStore.currentUser?.auth_token_id || '-'" />
          <InfoRow :label="t('settingsDiagnostics.fields.authTokenName')" :value="sessionStore.currentUser?.auth_token_name || '-'" />
          <InfoRow :label="t('settingsDiagnostics.fields.scopes')" :value="sessionStore.currentUser?.scopes?.join(', ') || '-'" />
          <InfoRow :label="t('settingsDiagnostics.fields.projectVisibility')" :value="formatProjectVisibility(sessionStore.currentUser?.project_ids)" />
          <InfoRow :label="t('settingsDiagnostics.fields.sessionStorage')" :value="runtimeConfig.storage.sessionTokenStorage" />
          <InfoRow :label="t('settingsDiagnostics.fields.manualLoginStorage')" :value="runtimeConfig.storage.manualLoginStorage" />
        </dl>
      </section>

      <section class="resource-section diagnostic-section">
        <div>
          <h2 class="heading-with-hint">
            {{ t('settingsDiagnostics.sections.projects') }}
            <InfoHint :text="t('settingsDiagnostics.sections.projectsHint')" />
          </h2>
        </div>
        <div class="resource-table diagnostic-section__table">
          <table>
            <thead>
              <tr>
                <th>{{ t('settingsDiagnostics.columns.project') }}</th>
                <th>{{ t('settingsDiagnostics.columns.projectId') }}</th>
                <th>{{ t('settingsDiagnostics.columns.projectSource') }}</th>
                <th>{{ t('settingsDiagnostics.columns.selected') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="project in visibleProjects" :key="project.project_id">
                <td>{{ project.display_name || project.project_id }}</td>
                <td>{{ project.project_id }}</td>
                <td>
                  <StatusPill
                    :status="project.project_source === 'local_disk' ? 'local_disk' : 'configured'"
                    :label="formatProjectSource(project.project_source)"
                    :tone="project.project_source === 'local_disk' ? 'info' : 'success'"
                  />
                </td>
                <td>
                  <StatusPill
                    :status="project.project_id === projectStore.selectedProjectId ? 'active' : 'available'"
                    :label="booleanText(project.project_id === projectStore.selectedProjectId)"
                    :tone="project.project_id === projectStore.selectedProjectId ? 'success' : 'neutral'"
                  />
                </td>
              </tr>
              <tr v-if="visibleProjects.length === 0">
                <td colspan="4">{{ t('settingsDiagnostics.emptyVisibleProjects') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="resource-section diagnostic-section">
        <div>
          <h2>{{ t('settingsDiagnostics.sections.providers') }}</h2>
        </div>
        <div class="resource-table diagnostic-section__table">
          <table>
            <thead>
              <tr>
                <th>{{ t('settingsDiagnostics.columns.provider') }}</th>
                <th>{{ t('settingsDiagnostics.columns.type') }}</th>
                <th>{{ t('settingsDiagnostics.columns.mode') }}</th>
                <th>{{ t('settingsDiagnostics.columns.capabilities') }}</th>
                <th>{{ t('settingsDiagnostics.columns.enabled') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="provider in bootstrapProviders" :key="provider.provider_id">
                <td>{{ provider.display_name }}</td>
                <td>{{ provider.provider_kind }}</td>
                <td>{{ provider.login_mode }}</td>
                <td>{{ formatProviderCapabilities(provider) }}</td>
                <td>
                  <StatusPill
                    :status="provider.enabled ? 'enabled' : 'disabled'"
                    :label="provider.enabled ? t('settingsDiagnostics.status.enabled') : t('settingsDiagnostics.status.disabled')"
                  />
                </td>
              </tr>
              <tr v-if="bootstrapProviders.length === 0">
                <td colspan="5">{{ t('settingsDiagnostics.emptyProviders') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </section>

    <SettingsAccountsPanel v-else-if="activeCategory === 'accounts'" />

    <section v-else class="settings-workbench">
      <aside class="settings-workbench__sidebar" aria-label="Settings diagnostic sections">
        <a v-for="section in sections" :key="section.id" :href="`#${section.id}`" class="settings-section-link">
          <component :is="section.icon" :size="16" />
          <span>{{ section.label }}</span>
        </a>
      </aside>

      <div class="settings-workbench__content">
        <section id="settings-about" class="resource-section diagnostic-section">
          <div class="section-heading">
            <div>
              <h2>{{ t('settingsDiagnostics.sections.about') }}</h2>
            </div>
            <StatusBadge tone="info">{{ stringValue(about.app_version) }}</StatusBadge>
          </div>
          <dl class="settings-info-list">
            <InfoRow :label="t('settingsDiagnostics.fields.appName')" :value="stringValue(about.app_name)" />
            <InfoRow :label="t('settingsDiagnostics.fields.frontendVersion')" :value="frontendVersion" />
            <InfoRow :label="t('settingsDiagnostics.fields.backendVersion')" :value="stringValue(about.backend_version)" />
            <InfoRow :label="t('settingsDiagnostics.fields.gitCommit')" :value="stringValue(about.git_commit)" />
            <InfoRow :label="t('settingsDiagnostics.fields.buildTime')" :value="formatOptionalDate(about.build_time)" />
            <InfoRow :label="t('settingsDiagnostics.fields.license')" :value="stringValue(about.license)" />
            <InfoRow :label="t('settingsDiagnostics.fields.runMode')" :value="stringValue(about.run_mode)" />
            <div>
              <dt>{{ t('settingsDiagnostics.fields.githubRepository') }}</dt>
              <dd><a href="https://github.com/ammm56/amvision" target="_blank" rel="noreferrer">https://github.com/ammm56/amvision</a></dd>
            </div>
            <div>
              <dt>{{ t('settingsDiagnostics.fields.amvarWebsite') }}</dt>
              <dd><a href="https://www.amvar.io" target="_blank" rel="noreferrer">https://www.amvar.io</a></dd>
            </div>
          </dl>
        </section>

        <section id="settings-runtime" class="resource-section diagnostic-section">
          <div>
            <h2>{{ t('settingsDiagnostics.sections.runtime') }}</h2>
          </div>
          <div class="summary-grid">
            <div>
              <span>{{ t('settingsDiagnostics.fields.apiBaseUrl') }}</span>
              <strong>{{ runtimeConfig.apiBaseUrl }}</strong>
            </div>
            <div>
              <span>{{ t('settingsDiagnostics.fields.wsBaseUrl') }}</span>
              <strong>{{ runtimeConfig.wsBaseUrl }}</strong>
            </div>
            <div>
              <span>{{ t('settingsDiagnostics.fields.authMode') }}</span>
              <strong>{{ sessionStore.authMode || '-' }}</strong>
            </div>
            <div>
              <span>{{ t('settingsDiagnostics.fields.credentialKind') }}</span>
              <strong>{{ sessionStore.credentialKind || '-' }}</strong>
            </div>
          </div>
          <dl class="settings-info-list">
            <InfoRow :label="t('settingsDiagnostics.fields.loginState')" :value="sessionStore.loginState" />
            <InfoRow :label="t('settingsDiagnostics.fields.defaultProjectId')" :value="runtimeConfig.defaultProjectId" />
            <InfoRow :label="t('settingsDiagnostics.fields.sessionStorage')" :value="runtimeConfig.storage.sessionTokenStorage" />
            <InfoRow :label="t('settingsDiagnostics.fields.manualLoginStorage')" :value="runtimeConfig.storage.manualLoginStorage" />
            <InfoRow :label="t('settingsDiagnostics.fields.featureFlags')" :value="enabledFeatureFlagsText" />
            <InfoRow :label="t('settingsDiagnostics.fields.scopes')" :value="sessionStore.currentUser?.scopes?.join(', ') || '-'" />
          </dl>
        </section>

        <section id="settings-system" class="resource-section diagnostic-section">
          <div>
            <h2>{{ t('settingsDiagnostics.sections.system') }}</h2>
          </div>
          <dl class="settings-info-list">
            <InfoRow :label="t('settingsDiagnostics.fields.os')" :value="stringValue(system.os)" />
            <InfoRow :label="t('settingsDiagnostics.fields.cpu')" :value="formatCpu" />
            <InfoRow :label="t('settingsDiagnostics.fields.memory')" :value="formatMemory(system.memory)" />
            <InfoRow :label="t('settingsDiagnostics.fields.workingDirectory')" :value="stringValue(system.working_directory)" />
            <InfoRow :label="t('settingsDiagnostics.fields.dataRoot')" :value="stringValue(system.data_root_dir)" />
            <InfoRow :label="t('settingsDiagnostics.fields.objectStoreRoot')" :value="stringValue(system.object_store_root_dir)" />
            <InfoRow :label="t('settingsDiagnostics.fields.queueRoot')" :value="stringValue(system.queue_root_dir)" />
            <InfoRow :label="t('settingsDiagnostics.fields.customNodesRoot')" :value="stringValue(system.custom_nodes_root_dir)" />
          </dl>
          <div class="resource-table diagnostic-section__table">
            <table>
              <thead>
                <tr>
                  <th>{{ t('settingsDiagnostics.columns.disk') }}</th>
                  <th>{{ t('settingsDiagnostics.columns.path') }}</th>
                  <th>{{ t('settingsDiagnostics.columns.free') }}</th>
                  <th>{{ t('settingsDiagnostics.columns.total') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="disk in diskRows" :key="disk.name">
                  <td>{{ disk.label }}</td>
                  <td>{{ disk.path }}</td>
                  <td>{{ disk.free }}</td>
                  <td>{{ disk.total }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section id="settings-python" class="resource-section diagnostic-section">
          <div>
            <h2>{{ t('settingsDiagnostics.sections.python') }}</h2>
          </div>
          <dl class="settings-info-list">
            <InfoRow :label="t('settingsDiagnostics.fields.pythonVersion')" :value="stringValue(pythonRuntime.python_version)" />
            <InfoRow :label="t('settingsDiagnostics.fields.pythonExecutable')" :value="stringValue(pythonRuntime.executable)" />
            <InfoRow :label="t('settingsDiagnostics.fields.condaEnv')" :value="stringValue(pythonRuntime.conda_env)" />
            <InfoRow :label="t('settingsDiagnostics.fields.condaPrefix')" :value="stringValue(pythonRuntime.conda_prefix)" />
            <InfoRow :label="t('settingsDiagnostics.fields.virtualEnv')" :value="stringValue(pythonRuntime.virtual_env)" />
            <InfoRow :label="t('settingsDiagnostics.fields.bundledPython')" :value="booleanText(pythonRuntime.bundled_python)" />
          </dl>
          <div class="resource-table diagnostic-section__table">
            <table>
              <thead>
                <tr>
                  <th>{{ t('settingsDiagnostics.columns.dependency') }}</th>
                  <th>{{ t('settingsDiagnostics.columns.status') }}</th>
                  <th>{{ t('settingsDiagnostics.columns.version') }}</th>
                  <th>{{ t('settingsDiagnostics.columns.importName') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="dependency in dependencyRows" :key="dependency.package_name">
                  <td>{{ dependency.package_name }}</td>
                  <td><StatusBadge :tone="dependency.installed ? 'success' : 'warning'">{{ dependency.installed ? t('settingsDiagnostics.status.installed') : t('settingsDiagnostics.status.missing') }}</StatusBadge></td>
                  <td>{{ dependency.version || '-' }}</td>
                  <td>{{ dependency.import_name }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section id="settings-devices" class="resource-section diagnostic-section">
          <div>
            <h2>{{ t('settingsDiagnostics.sections.devices') }}</h2>
          </div>
          <div class="summary-grid">
            <div v-for="runtime in deviceRuntimeRows" :key="runtime.name">
              <span>{{ runtime.label }}</span>
              <StatusPill :status="runtime.status" :label="runtime.statusLabel" with-dot />
            </div>
          </div>
          <div class="resource-table diagnostic-section__table">
            <table>
              <thead>
                <tr>
                  <th>{{ t('settingsDiagnostics.columns.device') }}</th>
                  <th>{{ t('settingsDiagnostics.columns.driver') }}</th>
                  <th>{{ t('settingsDiagnostics.columns.memory') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="device in gpuRows" :key="device.name">
                  <td>{{ device.name }}</td>
                  <td>{{ device.driver_version || '-' }}</td>
                  <td>{{ formatMiB(device.memory_total_mib) }}</td>
                </tr>
                <tr v-if="gpuRows.length === 0">
                  <td colspan="3">{{ t('settingsDiagnostics.emptyGpu') }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section id="settings-services" class="resource-section diagnostic-section">
          <div>
            <h2>{{ t('settingsDiagnostics.sections.services') }}</h2>
          </div>
          <div class="summary-grid">
            <div v-for="service in serviceRows" :key="service.name">
              <span>{{ service.label }}</span>
              <StatusPill :status="service.status" :label="service.statusLabel" with-dot />
            </div>
          </div>
        </section>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onMounted, ref } from 'vue'
import { Cpu, HardDrive, Info, Moon, RefreshCw, ServerCog, Settings2, ShieldCheck, Sun, UsersRound, Wrench } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { usePreferencesStore, type ThemeMode } from '@/app/stores/preferences.store'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { supportedLocaleOptions, type SupportedLocale } from '@/platform/i18n'
import { getRuntimeConfig } from '@/platform/runtime/runtime-config'
import type { AuthProvider, ProjectCatalogItem, SystemCapabilities } from '@/shared/contracts'
import Button from '@/shared/ui/components/Button.vue'
import InfoHint from '@/shared/ui/components/InfoHint.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import StatusPill from '@/shared/ui/data-display/StatusPill.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import SettingsAccountsPanel from '../components/SettingsAccountsPanel.vue'
import { getSystemDiagnostics, type SystemDiagnosticsResponse } from '../services/settings-diagnostics.service'

interface DependencyRow {
  package_name: string
  import_name: string
  installed: boolean
  version: string | null
}

interface GpuRow {
  name: string
  driver_version?: string | null
  memory_total_mib?: number | null
}

interface SectionItem {
  id: string
  label: string
  icon: object
}

type SelectValue = string | number | boolean | null
type SettingsCategoryId = 'preferences' | 'services' | 'system' | 'security' | 'accounts'

interface SettingsCategoryTab {
  id: SettingsCategoryId
  label: string
  icon: object
}

const InfoRow = defineComponent({
  props: {
    label: { type: String, required: true },
    value: { type: String, required: true },
  },
  setup(props) {
    return () => h('div', [h('dt', props.label), h('dd', props.value)])
  },
})

const { t } = useI18n()
const preferencesStore = usePreferencesStore()
const sessionStore = useSessionStore()
const projectStore = useProjectStore()
const runtimeConfig = getRuntimeConfig()
const frontendVersion = __AMVISION_FRONTEND_VERSION__

const diagnostics = ref<SystemDiagnosticsResponse | null>(null)
const loading = ref(false)
const errorMessage = ref<string | null>(null)
const activeCategory = ref<SettingsCategoryId>('system')

const localeOptions = supportedLocaleOptions.map((item) => ({ label: item.label, value: item.locale }))
const categoryTabs = computed<SettingsCategoryTab[]>(() => [
  { id: 'preferences', label: t('settingsDiagnostics.tabs.preferences'), icon: Settings2 },
  { id: 'services', label: t('settingsDiagnostics.tabs.services'), icon: ServerCog },
  { id: 'system', label: t('settingsDiagnostics.tabs.system'), icon: HardDrive },
  { id: 'security', label: t('settingsDiagnostics.tabs.security'), icon: ShieldCheck },
  { id: 'accounts', label: t('settingsDiagnostics.tabs.accounts'), icon: UsersRound },
])

const sections = computed<SectionItem[]>(() => [
  { id: 'settings-about', label: t('settingsDiagnostics.sections.about'), icon: Info },
  { id: 'settings-runtime', label: t('settingsDiagnostics.sections.runtime'), icon: Settings2 },
  { id: 'settings-system', label: t('settingsDiagnostics.sections.system'), icon: HardDrive },
  { id: 'settings-python', label: t('settingsDiagnostics.sections.python'), icon: Wrench },
  { id: 'settings-devices', label: t('settingsDiagnostics.sections.devices'), icon: Cpu },
  { id: 'settings-services', label: t('settingsDiagnostics.sections.services'), icon: ServerCog },
])

const about = computed(() => diagnostics.value?.about ?? {})
const system = computed(() => diagnostics.value?.system ?? {})
const pythonRuntime = computed(() => diagnostics.value?.python_runtime ?? {})
const devices = computed(() => diagnostics.value?.devices ?? {})
const services = computed(() => diagnostics.value?.services ?? {})
const bootstrapProviders = computed<AuthProvider[]>(() => sessionStore.bootstrap?.providers ?? [])
const visibleProjects = computed<ProjectCatalogItem[]>(() => sessionStore.bootstrap?.visible_projects ?? [])
const platformCapabilities = computed<SystemCapabilities>(() => sessionStore.bootstrap?.capabilities ?? {})
const serviceStatus = computed(() => stringValue(recordValue(services.value, 'backend_service', 'status')))
const formatCpu = computed(() =>
  [stringValue(system.value.processor), stringValue(system.value.cpu_count)].filter((value) => value !== '-').join(' / ') || '-',
)
const implementedDatasetFormatsText = computed(() => formatStringList(platformCapabilities.value.dataset_export?.implemented_formats))
const projectSummaryTopicsText = computed(() => formatStringList(platformCapabilities.value.project_summary_topics))
const enabledFeatureFlagsText = computed(() => formatEnabledFeatureFlags(runtimeConfig.features))
const diskRows = computed(() => {
  const disk = recordValue(system.value, 'disk')
  const diskRecord = isRecord(disk) ? disk : {}
  return [
    buildDiskRow('working_directory', t('settingsDiagnostics.disk.workingDirectory'), diskRecord.working_directory),
    buildDiskRow('data_root', t('settingsDiagnostics.disk.dataRoot'), diskRecord.data_root),
    buildDiskRow('object_store_root', t('settingsDiagnostics.disk.objectStoreRoot'), diskRecord.object_store_root),
  ]
})
const dependencyRows = computed<DependencyRow[]>(() => {
  const dependencies = pythonRuntime.value.dependencies
  if (!Array.isArray(dependencies)) return []
  return dependencies.filter(isRecord).map((item) => ({
    package_name: stringValue(item.package_name),
    import_name: stringValue(item.import_name),
    installed: item.installed === true,
    version: typeof item.version === 'string' ? item.version : null,
  }))
})
const gpuRows = computed<GpuRow[]>(() => {
  const gpu = recordValue(devices.value, 'gpu')
  const rows = isRecord(gpu) && Array.isArray(gpu.devices) ? gpu.devices : []
  return rows.filter(isRecord).map((item) => ({
    name: stringValue(item.name),
    driver_version: typeof item.driver_version === 'string' ? item.driver_version : null,
    memory_total_mib: typeof item.memory_total_mib === 'number' ? item.memory_total_mib : null,
  }))
})
const deviceRuntimeRows = computed(() => [
  buildAvailabilityRow('cuda', 'CUDA', recordValue(devices.value, 'cuda', 'available')),
  buildAvailabilityRow('openvino', 'OpenVINO', recordValue(devices.value, 'openvino', 'installed')),
  buildAvailabilityRow('tensorrt', 'TensorRT', recordValue(devices.value, 'tensorrt', 'installed')),
  buildAvailabilityRow('onnxruntime', 'ONNX Runtime', recordValue(devices.value, 'onnxruntime', 'installed')),
  buildAvailabilityRow('npu', 'NPU runtime', recordValue(devices.value, 'npu_runtime', 'available')),
])
const serviceRows = computed(() => [
  buildStatusRow('backend_service', 'backend-service', recordValue(services.value, 'backend_service', 'status')),
  buildStatusRow('worker', 'backend-worker', recordValue(services.value, 'backend_worker', 'health')),
  buildStatusRow('websocket', 'WebSocket', recordValue(services.value, 'websocket', 'status')),
  buildStatusRow('zeromq', 'ZeroMQ', recordValue(services.value, 'zeromq', 'available') === true ? 'available' : 'missing'),
  buildStatusRow('database', 'Database', recordValue(services.value, 'database', 'database')),
  buildStatusRow('local_buffer_broker', 'LocalBufferBroker', recordValue(services.value, 'local_buffer_broker', 'state')),
])

onMounted(() => {
  void loadDiagnostics()
})

function setLocale(value: SelectValue): void {
  if (typeof value !== 'string') return
  preferencesStore.setLocale(value as SupportedLocale)
}

function setTheme(theme: ThemeMode): void {
  preferencesStore.setTheme(theme)
}

async function loadDiagnostics(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    const [nextDiagnostics] = await Promise.all([
      getSystemDiagnostics(),
      sessionStore.loadBootstrap().catch(() => sessionStore.bootstrap),
    ])
    diagnostics.value = nextDiagnostics
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('settingsDiagnostics.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function recordValue(record: Record<string, unknown>, key: string, nestedKey?: string): unknown {
  const value = record[key]
  if (!nestedKey) return value
  return isRecord(value) ? value[nestedKey] : undefined
}

function stringValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  return formatJson(value)
}

function booleanText(value: unknown): string {
  if (value === true) return t('settingsDiagnostics.status.yes')
  if (value === false) return t('settingsDiagnostics.status.no')
  return '-'
}

function formatJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2)
}

function formatStringList(value: unknown): string {
  if (!Array.isArray(value)) return '-'
  const items = value.filter((item): item is string => typeof item === 'string' && item.length > 0)
  return items.length > 0 ? items.join(', ') : '-'
}

function formatEnabledFeatureFlags(value: object): string {
  const enabledFlags = Object.entries(value)
    .filter(([, enabled]) => enabled === true)
    .map(([name]) => name)
  return enabledFlags.length > 0 ? enabledFlags.join(', ') : '-'
}

function formatOptionalDate(value: unknown): string {
  return typeof value === 'string' && value ? formatSystemDateTime(value) : '-'
}

function formatBytes(value: unknown): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let size = value
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }
  return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`
}

function formatMiB(value: unknown): string {
  return typeof value === 'number' ? `${value} MiB` : '-'
}

function formatMemory(value: unknown): string {
  if (!isRecord(value)) return '-'
  const total = formatBytes(value.total_bytes)
  const available = formatBytes(value.available_bytes)
  if (total === '-' && available === '-') return stringValue(value.status)
  return `${available} / ${total}`
}

function buildDiskRow(name: string, label: string, value: unknown): { name: string; label: string; path: string; free: string; total: string } {
  const record = isRecord(value) ? value : {}
  return {
    name,
    label,
    path: stringValue(record.path),
    free: formatBytes(record.free_bytes),
    total: formatBytes(record.total_bytes),
  }
}

function buildAvailabilityRow(name: string, label: string, value: unknown): { name: string; label: string; status: string; statusLabel: string } {
  const status = value === true ? 'available' : value === false ? 'unavailable' : 'unknown'
  return {
    name,
    label,
    status,
    statusLabel: value === true ? t('settingsDiagnostics.status.available') : value === false ? t('settingsDiagnostics.status.unavailable') : '-',
  }
}

function buildStatusRow(name: string, label: string, value: unknown): { name: string; label: string; status: string; statusLabel: string } {
  const status = stringValue(value)
  return {
    name,
    label,
    status,
    statusLabel: formatServiceStatus(status),
  }
}

function formatProjectSource(value: ProjectCatalogItem['project_source']): string {
  if (value === 'configured') return t('settingsDiagnostics.projectSources.configured')
  if (value === 'local_disk') return t('settingsDiagnostics.projectSources.localDisk')
  return '-'
}

function formatProjectVisibility(value: string[] | undefined): string {
  return Array.isArray(value) && value.length > 0 ? value.join(', ') : t('settingsDiagnostics.fields.allProjects')
}

function formatServiceStatus(value: string): string {
  const normalized = value.toLowerCase().trim()
  if (normalized === 'available') return t('settingsDiagnostics.status.available')
  if (normalized === 'unavailable') return t('settingsDiagnostics.status.unavailable')
  if (normalized === 'enabled') return t('settingsDiagnostics.status.enabled')
  if (normalized === 'disabled') return t('settingsDiagnostics.status.disabled')
  if (normalized === 'ok') return t('settingsDiagnostics.status.ok')
  if (normalized === 'configured') return t('settingsDiagnostics.status.configured')
  if (normalized === 'reachable') return t('settingsDiagnostics.status.reachable')
  if (normalized === 'running') return t('settingsDiagnostics.status.running')
  if (normalized === 'stale') return t('settingsDiagnostics.status.stale')
  if (normalized === 'offline') return t('settingsDiagnostics.status.offline')
  if (normalized === 'stopped') return t('settingsDiagnostics.status.stopped')
  if (normalized === 'not_probed') return t('settingsDiagnostics.status.notProbed')
  if (normalized === 'unknown') return t('tasks.status.unknown')
  return value.replace(/[_-]+/g, ' ')
}

function formatProviderCapabilities(provider: AuthProvider): string {
  const capabilities: string[] = []
  if (provider.supports_password_login) capabilities.push(t('settingsDiagnostics.providerCapabilities.passwordLogin'))
  if (provider.supports_refresh) capabilities.push(t('settingsDiagnostics.providerCapabilities.refresh'))
  if (provider.supports_bootstrap_admin) capabilities.push(t('settingsDiagnostics.providerCapabilities.bootstrapAdmin'))
  if (provider.supports_user_management) capabilities.push(t('settingsDiagnostics.providerCapabilities.userManagement'))
  if (provider.supports_long_lived_tokens) capabilities.push(t('settingsDiagnostics.providerCapabilities.longLivedTokens'))
  return capabilities.length > 0 ? capabilities.join(', ') : '-'
}
</script>
