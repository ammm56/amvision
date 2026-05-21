<template>
  <section class="settings-category-panel">
    <section class="resource-section diagnostic-section">
      <div class="section-heading">
        <div>
          <p class="page-kicker">{{ t('settingsDiagnostics.sections.accountsKicker') }}</p>
          <h2>{{ t('settingsDiagnostics.sections.accounts') }}</h2>
        </div>
        <Button variant="secondary" :disabled="usersLoading" @click="loadUsers">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </div>
      <InlineError :message="errorMessage" />
      <p v-if="statusMessage" class="result-note">{{ statusMessage }}</p>

      <div class="form-grid settings-account-form">
        <label class="field">
          <span>{{ t('settingsDiagnostics.fields.username') }}</span>
          <input v-model.trim="createUserForm.username" autocomplete="off" />
        </label>
        <label class="field">
          <span>{{ t('settingsDiagnostics.fields.displayName') }}</span>
          <input v-model.trim="createUserForm.displayName" autocomplete="off" />
        </label>
        <label class="field">
          <span>{{ t('settingsDiagnostics.fields.password') }}</span>
          <input v-model="createUserForm.password" type="password" autocomplete="new-password" />
        </label>
        <label class="field">
          <span>{{ t('settingsDiagnostics.fields.defaultTokenName') }}</span>
          <input v-model.trim="createUserForm.tokenName" autocomplete="off" />
        </label>
        <label class="field field--wide">
          <span>{{ t('settingsDiagnostics.fields.scopes') }}</span>
          <MultiSelect
            :model-value="createUserForm.scopes"
            :options="scopeOptions"
            :placeholder="t('settingsDiagnostics.placeholders.scopeList')"
            @update:model-value="updateCreateUserScopes"
          />
        </label>
        <label class="field field--wide">
          <span>{{ t('settingsDiagnostics.fields.projectScopes') }}</span>
          <input v-model.trim="createUserForm.projectIds" autocomplete="off" :placeholder="t('settingsDiagnostics.placeholders.projectList')" />
        </label>
        <label class="checkbox-field">
          <input v-model="createUserForm.issueToken" type="checkbox" />
          <span>{{ t('settingsDiagnostics.fields.issueDefaultToken') }}</span>
        </label>
        <div class="field settings-account-form__actions">
          <span>{{ t('settingsDiagnostics.columns.actions') }}</span>
          <Button variant="primary" :disabled="!canWrite || usersLoading" @click="createUser">
            <UserPlus :size="16" />
            {{ t('settingsDiagnostics.actions.createUser') }}
          </Button>
        </div>
      </div>
    </section>

    <section class="resource-section diagnostic-section">
      <div class="resource-table diagnostic-section__table">
        <table>
          <thead>
            <tr>
              <th>{{ t('settingsDiagnostics.columns.user') }}</th>
              <th>{{ t('settingsDiagnostics.columns.status') }}</th>
              <th>{{ t('settingsDiagnostics.columns.scopes') }}</th>
              <th>{{ t('settingsDiagnostics.columns.projects') }}</th>
              <th>{{ t('settingsDiagnostics.columns.lastLogin') }}</th>
              <th>{{ t('settingsDiagnostics.columns.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.user_id" :class="{ 'is-selected': user.user_id === selectedUserId }">
              <td>
                <strong>{{ user.display_name || user.username }}</strong>
                <span>{{ user.username }} / {{ user.user_id }}</span>
              </td>
              <td class="status-cell">
                <StatusPill :status="user.is_active ? 'enabled' : 'disabled'" :label="user.is_active ? t('settingsDiagnostics.status.enabled') : t('settingsDiagnostics.status.disabled')" />
              </td>
              <td>
                <span class="compact-info-value">
                  {{ formatScopeSummary(user.scopes) }}
                  <InfoHint v-if="user.scopes.length > 0" :text="formatScopeHint(user.scopes)" />
                </span>
              </td>
              <td>{{ formatList(user.project_ids) }}</td>
              <td>{{ formatDate(user.last_login_at) }}</td>
              <td>
                <div class="table-actions">
                  <Button variant="secondary" @click="selectUser(user.user_id)">
                    <KeyRound :size="15" />
                    {{ t('settingsDiagnostics.actions.manageTokens') }}
                  </Button>
                  <Button variant="secondary" :disabled="!canWrite" @click="toggleUser(user.user_id, !user.is_active)">
                    <Power :size="15" />
                    {{ user.is_active ? t('settingsDiagnostics.actions.disable') : t('settingsDiagnostics.actions.enable') }}
                  </Button>
                  <Button variant="danger" :disabled="!canWrite || user.user_id === currentUserId" @click="removeUser(user.user_id)">
                    <Trash2 :size="15" />
                    {{ t('settingsDiagnostics.actions.delete') }}
                  </Button>
                </div>
              </td>
            </tr>
            <tr v-if="users.length === 0">
              <td colspan="6">{{ t('settingsDiagnostics.emptyUsers') }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="selectedUser" class="resource-section diagnostic-section settings-account-detail">
      <div class="section-heading">
        <div>
          <p class="page-kicker">{{ t('settingsDiagnostics.sections.accountsKicker') }}</p>
          <h2>{{ selectedUser.display_name || selectedUser.username }}</h2>
        </div>
        <StatusPill :status="selectedUser.is_active ? 'enabled' : 'disabled'" :label="selectedUser.is_active ? t('settingsDiagnostics.status.enabled') : t('settingsDiagnostics.status.disabled')" />
      </div>

      <section class="settings-account-subsection">
        <div class="settings-account-subsection__heading">
          <div>
            <h3 class="heading-with-hint">
              {{ t('settingsDiagnostics.sections.tokenManagement') }}
              <InfoHint :text="tokenManagementHint" />
            </h3>
          </div>
        </div>

        <div class="form-grid settings-account-form settings-token-form">
          <label class="field">
            <span>{{ t('settingsDiagnostics.fields.tokenName') }}</span>
            <input v-model.trim="tokenForm.tokenName" autocomplete="off" />
          </label>
          <label class="field">
            <span>{{ t('settingsDiagnostics.fields.ttlHours') }}</span>
            <input v-model.number="tokenForm.ttlHours" type="number" min="1" :placeholder="t('settingsDiagnostics.placeholders.permanentToken')" />
          </label>
          <div class="field settings-account-form__actions">
            <span>{{ t('settingsDiagnostics.columns.actions') }}</span>
            <Button variant="primary" :disabled="!canWrite || tokensLoading" @click="createToken">
              <KeyRound :size="16" />
              {{ t('settingsDiagnostics.actions.createToken') }}
            </Button>
          </div>
        </div>

        <div v-if="issuedToken" class="issued-token-panel">
          <div class="issued-token-panel__meta">
            <span class="heading-with-hint">
              {{ t('settingsDiagnostics.fields.tokenPlaintext') }}
              <InfoHint :text="t('settingsDiagnostics.messages.tokenPlaintextHelp')" />
            </span>
            <strong>{{ issuedToken.token_name }}</strong>
          </div>
          <input :value="issuedToken.token" readonly />
          <Button variant="secondary" @click="copyIssuedToken">
            <Copy :size="16" />
            {{ t('settingsDiagnostics.actions.copyToken') }}
          </Button>
        </div>

        <div class="resource-table diagnostic-section__table">
          <table>
            <thead>
              <tr>
                <th>{{ t('settingsDiagnostics.columns.token') }}</th>
                <th>{{ t('settingsDiagnostics.columns.status') }}</th>
                <th>{{ t('settingsDiagnostics.columns.createdAt') }}</th>
                <th>{{ t('settingsDiagnostics.columns.expiresAt') }}</th>
                <th>{{ t('settingsDiagnostics.columns.lastUsedAt') }}</th>
                <th>{{ t('settingsDiagnostics.columns.actions') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="token in tokens" :key="token.token_id">
                <td>
                  <strong>{{ token.token_name }}</strong>
                  <InfoHint :text="tokenIdHint(token.token_id)" />
                </td>
                <td class="status-cell">
                  <StatusPill :status="token.revoked_at ? 'revoked' : 'enabled'" :label="token.revoked_at ? t('settingsDiagnostics.status.revoked') : t('settingsDiagnostics.status.enabled')" />
                </td>
                <td>{{ formatDate(token.created_at) }}</td>
                <td>{{ formatDate(token.expires_at) }}</td>
                <td>{{ formatDate(token.last_used_at) }}</td>
                <td>
                  <Button variant="danger" :disabled="!canWrite || Boolean(token.revoked_at)" @click="revokeToken(token.token_id)">
                    <Trash2 :size="15" />
                    {{ t('settingsDiagnostics.actions.revoke') }}
                  </Button>
                </td>
              </tr>
              <tr v-if="tokens.length === 0">
                <td colspan="6">{{ t('settingsDiagnostics.emptyTokens') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="settings-account-subsection">
        <div class="settings-account-subsection__heading">
          <div>
            <h3 class="heading-with-hint">
              {{ t('settingsDiagnostics.sections.passwordReset') }}
              <InfoHint :text="t('settingsDiagnostics.messages.passwordResetHint')" />
            </h3>
          </div>
        </div>

        <div class="form-grid settings-account-form">
          <label class="field">
            <span>{{ t('settingsDiagnostics.fields.newPassword') }}</span>
            <input v-model="passwordForm.newPassword" type="password" autocomplete="new-password" />
          </label>
          <div class="field settings-password-options-field">
            <span>{{ t('settingsDiagnostics.fields.resetOptions') }}</span>
            <div class="settings-checkbox-row">
              <label class="checkbox-field checkbox-field--nowrap">
                <input v-model="passwordForm.revokeSessions" type="checkbox" />
                <span>{{ t('settingsDiagnostics.fields.revokeSessions') }}</span>
              </label>
              <label class="checkbox-field checkbox-field--nowrap">
                <input v-model="passwordForm.revokeUserTokens" type="checkbox" />
                <span>{{ t('settingsDiagnostics.fields.revokeUserTokens') }}</span>
              </label>
            </div>
          </div>
          <div class="field settings-account-form__actions">
            <span>{{ t('settingsDiagnostics.columns.actions') }}</span>
            <Button variant="secondary" :disabled="!canWrite || !passwordForm.newPassword" @click="resetPassword">
              <RotateCcw :size="16" />
              {{ t('settingsDiagnostics.actions.resetPassword') }}
            </Button>
          </div>
        </div>
      </section>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Copy, KeyRound, Power, RefreshCw, RotateCcw, Trash2, UserPlus } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { useSessionStore } from '@/app/stores/session.store'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import type { LocalAuthUser } from '@/shared/contracts'
import Button from '@/shared/ui/components/Button.vue'
import InfoHint from '@/shared/ui/components/InfoHint.vue'
import MultiSelect from '@/shared/ui/components/MultiSelect.vue'
import StatusPill from '@/shared/ui/data-display/StatusPill.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import {
  createLocalAuthUser,
  createLocalAuthUserToken,
  deleteLocalAuthUser,
  listLocalAuthUserTokens,
  listLocalAuthUsers,
  resetLocalAuthUserPassword,
  revokeLocalAuthUserToken,
  updateLocalAuthUser,
  type LocalAuthIssuedUserToken,
  type LocalAuthUserToken,
} from '../services/local-auth-management.service'

const { t } = useI18n()
const sessionStore = useSessionStore()

const users = ref<LocalAuthUser[]>([])
const tokens = ref<LocalAuthUserToken[]>([])
const selectedUserId = ref<string | null>(null)
const issuedToken = ref<LocalAuthIssuedUserToken | null>(null)
const usersLoading = ref(false)
const tokensLoading = ref(false)
const errorMessage = ref<string | null>(null)
const statusMessage = ref<string | null>(null)

const createUserForm = reactive({
  username: '',
  displayName: '',
  password: '',
  scopes: ['workflows:read', 'models:read', 'datasets:read', 'tasks:read'],
  projectIds: '',
  issueToken: true,
  tokenName: 'default',
})
const tokenForm = reactive({ tokenName: 'default', ttlHours: null as number | null })
const passwordForm = reactive({ newPassword: '', revokeSessions: true, revokeUserTokens: false })

const canWrite = computed(() => sessionStore.hasScopes(['auth:write']))
const currentUserId = computed(() => sessionStore.currentUser?.principal_id ?? '')
const selectedUser = computed(() => users.value.find((user) => user.user_id === selectedUserId.value) ?? null)
const tokenManagementHint = computed(() => `${t('settingsDiagnostics.messages.tokenUsageHint')} ${t('settingsDiagnostics.messages.tokenListHint')}`)
const scopeOptions = computed(() => [
  { label: t('settingsDiagnostics.fields.allScopes'), value: '*', description: '*' },
  { label: 'workflows:read', value: 'workflows:read' },
  { label: 'workflows:write', value: 'workflows:write' },
  { label: 'models:read', value: 'models:read' },
  { label: 'models:write', value: 'models:write' },
  { label: 'datasets:read', value: 'datasets:read' },
  { label: 'datasets:write', value: 'datasets:write' },
  { label: 'tasks:read', value: 'tasks:read' },
  { label: 'tasks:write', value: 'tasks:write' },
  { label: 'deployments:read', value: 'deployments:read' },
  { label: 'deployments:write', value: 'deployments:write' },
  { label: 'integrations:read', value: 'integrations:read' },
  { label: 'integrations:write', value: 'integrations:write' },
  { label: 'auth:read', value: 'auth:read' },
  { label: 'auth:write', value: 'auth:write' },
  { label: 'system:read', value: 'system:read' },
])

onMounted(() => {
  void loadUsers()
})

async function loadUsers(): Promise<void> {
  usersLoading.value = true
  errorMessage.value = null
  try {
    users.value = await listLocalAuthUsers()
    if (!selectedUserId.value && users.value.length > 0) {
      selectedUserId.value = users.value[0].user_id
      await loadTokens(selectedUserId.value)
    } else if (selectedUserId.value) {
      await loadTokens(selectedUserId.value)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('settingsDiagnostics.messages.usersLoadFailed')
  } finally {
    usersLoading.value = false
  }
}

async function selectUser(userId: string): Promise<void> {
  selectedUserId.value = userId
  issuedToken.value = null
  await loadTokens(userId)
}

async function loadTokens(userId: string): Promise<void> {
  tokensLoading.value = true
  errorMessage.value = null
  try {
    tokens.value = await listLocalAuthUserTokens(userId)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('settingsDiagnostics.messages.tokensLoadFailed')
  } finally {
    tokensLoading.value = false
  }
}

async function createUser(): Promise<void> {
  if (!createUserForm.username || !createUserForm.password) {
    errorMessage.value = t('settingsDiagnostics.messages.userInputRequired')
    return
  }
  usersLoading.value = true
  errorMessage.value = null
  statusMessage.value = null
  try {
    const result = await createLocalAuthUser({
      username: createUserForm.username,
      password: createUserForm.password,
      display_name: createUserForm.displayName || null,
      scopes: createUserForm.scopes,
      project_ids: parseCsv(createUserForm.projectIds),
      initial_user_token: createUserForm.issueToken
        ? { enabled: true, token_name: createUserForm.tokenName || 'default' }
        : { enabled: false },
    })
    resetCreateUserForm()
    users.value = await listLocalAuthUsers()
    selectedUserId.value = result.user.user_id
    issuedToken.value = result.initial_user_token ?? null
    await loadTokens(result.user.user_id)
    statusMessage.value = t('settingsDiagnostics.messages.userCreated')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('settingsDiagnostics.messages.userCreateFailed')
  } finally {
    usersLoading.value = false
  }
}

async function toggleUser(userId: string, isActive: boolean): Promise<void> {
  errorMessage.value = null
  try {
    await updateLocalAuthUser(userId, { is_active: isActive })
    await loadUsers()
    statusMessage.value = isActive ? t('settingsDiagnostics.messages.userEnabled') : t('settingsDiagnostics.messages.userDisabled')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('settingsDiagnostics.messages.userUpdateFailed')
  }
}

async function removeUser(userId: string): Promise<void> {
  if (!globalThis.confirm(t('settingsDiagnostics.messages.confirmDeleteUser'))) return
  errorMessage.value = null
  try {
    await deleteLocalAuthUser(userId)
    if (selectedUserId.value === userId) {
      selectedUserId.value = null
      tokens.value = []
      issuedToken.value = null
    }
    await loadUsers()
    statusMessage.value = t('settingsDiagnostics.messages.userDeleted')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('settingsDiagnostics.messages.userDeleteFailed')
  }
}

async function createToken(): Promise<void> {
  if (!selectedUser.value) return
  tokensLoading.value = true
  errorMessage.value = null
  statusMessage.value = null
  try {
    issuedToken.value = await createLocalAuthUserToken(selectedUser.value.user_id, {
      token_name: tokenForm.tokenName || 'default',
      ttl_hours: normalizeTtlHours(tokenForm.ttlHours),
    })
    await loadTokens(selectedUser.value.user_id)
    statusMessage.value = t('settingsDiagnostics.messages.tokenCreated')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('settingsDiagnostics.messages.tokenCreateFailed')
  } finally {
    tokensLoading.value = false
  }
}

async function revokeToken(tokenId: string): Promise<void> {
  if (!selectedUser.value || !globalThis.confirm(t('settingsDiagnostics.messages.confirmRevokeToken'))) return
  errorMessage.value = null
  try {
    await revokeLocalAuthUserToken(selectedUser.value.user_id, tokenId)
    await loadTokens(selectedUser.value.user_id)
    statusMessage.value = t('settingsDiagnostics.messages.tokenRevoked')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('settingsDiagnostics.messages.tokenRevokeFailed')
  }
}

async function resetPassword(): Promise<void> {
  if (!selectedUser.value || !passwordForm.newPassword) return
  errorMessage.value = null
  try {
    await resetLocalAuthUserPassword(selectedUser.value.user_id, {
      new_password: passwordForm.newPassword,
      revoke_sessions: passwordForm.revokeSessions,
      revoke_user_tokens: passwordForm.revokeUserTokens,
    })
    passwordForm.newPassword = ''
    await loadUsers()
    statusMessage.value = t('settingsDiagnostics.messages.passwordReset')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('settingsDiagnostics.messages.passwordResetFailed')
  }
}

async function copyIssuedToken(): Promise<void> {
  if (!issuedToken.value) return
  try {
    await navigator.clipboard.writeText(issuedToken.value.token)
    statusMessage.value = t('settingsDiagnostics.messages.tokenCopied')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('settingsDiagnostics.messages.tokenCopyFailed')
  }
}

function parseCsv(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function formatList(value: string[]): string {
  return value.length > 0 ? value.join(', ') : '-'
}

function formatScopeSummary(value: string[]): string {
  if (value.includes('*')) return t('settingsDiagnostics.fields.allScopes')
  if (value.length === 0) return '-'
  return t('settingsDiagnostics.messages.selectedScopeCount', { count: value.length })
}

function formatScopeHint(value: string[]): string {
  return value.includes('*') ? '*' : value.join(', ')
}

function tokenIdHint(tokenId: string): string {
  return `${t('settingsDiagnostics.fields.tokenManagementId')}: ${tokenId}`
}

function updateCreateUserScopes(value: string[]): void {
  createUserForm.scopes = normalizeScopeSelection(value)
}

function normalizeScopeSelection(value: string[]): string[] {
  const uniqueValue = Array.from(new Set(value))
  if (uniqueValue.includes('*') && !createUserForm.scopes.includes('*')) return ['*']
  if (createUserForm.scopes.includes('*') && uniqueValue.length > 1) return uniqueValue.filter((item) => item !== '*')
  if (uniqueValue.includes('*')) return ['*']
  return uniqueValue
}

function formatDate(value?: string | null): string {
  return value ? formatSystemDateTime(value) : '-'
}

function normalizeTtlHours(value: number | null): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null
}

function resetCreateUserForm(): void {
  createUserForm.username = ''
  createUserForm.displayName = ''
  createUserForm.password = ''
  createUserForm.scopes = ['workflows:read', 'models:read', 'datasets:read', 'tasks:read']
  createUserForm.projectIds = ''
  createUserForm.tokenName = 'default'
  createUserForm.issueToken = true
}
</script>
