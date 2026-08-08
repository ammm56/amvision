<template>
  <section class="settings-panel settings-accounts-panel">
    <header class="settings-panel__heading">
      <div>
        <h2>{{ t('settingsDiagnostics.sections.accounts') }}</h2>
      </div>
      <div class="settings-panel__actions">
        <Button variant="secondary" :disabled="usersLoading" :loading="usersLoading" @click="loadUsers">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
        <Button variant="primary" :disabled="!canWrite" @click="showCreateUser = true">
          <UserPlus :size="16" />
          {{ t('settingsDiagnostics.actions.createUser') }}
        </Button>
      </div>
    </header>

    <InlineError :message="errorMessage" />
    <InlineMessage v-if="statusMessage" tone="success" :message="statusMessage" />

    <div class="settings-account-workspace">
      <aside class="settings-user-directory" :aria-label="t('settingsDiagnostics.sections.accounts')">
        <button
          v-for="user in users"
          :key="user.user_id"
          type="button"
          class="settings-user-item"
          :class="{ 'is-selected': user.user_id === selectedUserId }"
          @click="selectUser(user.user_id)"
        >
          <span class="settings-user-item__identity">
            <strong>{{ user.display_name || user.username }}</strong>
            <small>{{ user.username }}</small>
          </span>
          <StatusBadge :status="user.is_active ? 'enabled' : 'disabled'" :label="user.is_active ? t('settingsDiagnostics.status.enabled') : t('settingsDiagnostics.status.disabled')" />
        </button>
        <p v-if="users.length === 0" class="settings-empty-copy">{{ t('settingsDiagnostics.emptyUsers') }}</p>
      </aside>

      <section v-if="selectedUser" class="settings-account-detail">
        <header class="settings-account-detail__header">
          <div>
            <h3>{{ selectedUser.display_name || selectedUser.username }}</h3>
            <span class="settings-mono-value">{{ selectedUser.user_id }}</span>
          </div>
          <div class="settings-panel__actions">
            <Button
              variant="secondary"
              size="sm"
              :disabled="!canWrite || (isSelectedSoleAmvar && selectedUser.is_active)"
              :title="isSelectedSoleAmvar && selectedUser.is_active ? soleAmvarProtectionMessage : undefined"
              @click="toggleUser(selectedUser.user_id, !selectedUser.is_active)"
            >
              <Power :size="15" />
              {{ selectedUser.is_active ? t('settingsDiagnostics.actions.disable') : t('settingsDiagnostics.actions.enable') }}
            </Button>
            <Button
              variant="danger"
              size="sm"
              :disabled="!canWrite || selectedUser.user_id === currentUserId || isSelectedSoleAmvar || accountDangerActionKey !== null"
              :title="isSelectedSoleAmvar ? soleAmvarProtectionMessage : undefined"
              @click="requestRemoveUser(selectedUser)"
            >
              <Trash2 :size="15" />
              {{ t('settingsDiagnostics.actions.delete') }}
            </Button>
          </div>
        </header>

        <dl class="settings-metadata-grid settings-account-summary">
          <div><dt>{{ t('settingsDiagnostics.columns.status') }}</dt><dd><StatusBadge :status="selectedUser.is_active ? 'enabled' : 'disabled'" :label="selectedUser.is_active ? t('settingsDiagnostics.status.enabled') : t('settingsDiagnostics.status.disabled')" /></dd></div>
          <div><dt>{{ t('settingsDiagnostics.columns.scopes') }}</dt><dd>{{ formatScopeSummary(selectedUser.scopes) }}</dd></div>
          <div><dt>{{ t('settingsDiagnostics.columns.projectVisibility') }}</dt><dd>{{ formatProjectVisibility(selectedUser.project_ids) }}</dd></div>
          <div><dt>{{ t('settingsDiagnostics.columns.lastLogin') }}</dt><dd>{{ formatDate(selectedUser.last_login_at) }}</dd></div>
        </dl>

        <div v-if="issuedToken" class="issued-token-panel">
          <div class="issued-token-panel__meta">
            <span>{{ t('settingsDiagnostics.fields.tokenPlaintext') }}</span>
            <strong>{{ issuedToken.token_name }}</strong>
          </div>
          <input :value="issuedToken.token" readonly />
          <Button variant="secondary" @click="copyIssuedToken"><Copy :size="16" />{{ t('settingsDiagnostics.actions.copyToken') }}</Button>
        </div>

        <section class="settings-account-section">
          <header class="settings-account-section__heading">
            <h3>{{ t('settingsDiagnostics.sections.tokenManagement') }}</h3>
            <Button variant="secondary" size="sm" :disabled="!canWrite" @click="showTokenForm = !showTokenForm">
              <KeyRound :size="15" />
              {{ t('settingsDiagnostics.actions.createToken') }}
            </Button>
          </header>
          <div v-if="showTokenForm" class="settings-inline-form">
            <label class="field"><span>{{ t('settingsDiagnostics.fields.tokenName') }}</span><input v-model.trim="tokenForm.tokenName" autocomplete="off" /></label>
            <label class="field"><span>{{ t('settingsDiagnostics.fields.ttlHours') }}</span><input v-model.number="tokenForm.ttlHours" type="number" min="1" step="1" :placeholder="t('settingsDiagnostics.placeholders.permanentToken')" /></label>
            <Button variant="primary" :disabled="!canWrite || tokensLoading" :loading="tokensLoading" @click="createToken">{{ t('settingsDiagnostics.actions.createToken') }}</Button>
          </div>
          <div class="resource-table settings-account-token-table">
            <table>
              <thead><tr><th>{{ t('settingsDiagnostics.columns.token') }}</th><th>{{ t('settingsDiagnostics.columns.status') }}</th><th>{{ t('settingsDiagnostics.columns.expiresAt') }}</th><th>{{ t('settingsDiagnostics.columns.lastUsedAt') }}</th><th>{{ t('settingsDiagnostics.columns.actions') }}</th></tr></thead>
              <tbody>
                <tr v-for="token in tokens" :key="token.token_id"><td><strong>{{ token.token_name }}</strong></td><td><StatusBadge :status="token.revoked_at ? 'revoked' : 'enabled'" :label="token.revoked_at ? t('settingsDiagnostics.status.revoked') : t('settingsDiagnostics.status.enabled')" /></td><td>{{ formatDate(token.expires_at) }}</td><td>{{ formatDate(token.last_used_at) }}</td><td><Button variant="danger" size="sm" :disabled="!canWrite || Boolean(token.revoked_at) || accountDangerActionKey !== null" :loading="accountDangerActionKey === `token:${token.token_id}`" @click="requestRevokeToken(token)">{{ t('settingsDiagnostics.actions.revoke') }}</Button></td></tr>
                <tr v-if="tokens.length === 0"><td colspan="5">{{ t('settingsDiagnostics.emptyTokens') }}</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        <details class="settings-advanced settings-account-password">
          <summary>{{ t('settingsDiagnostics.sections.passwordReset') }}</summary>
          <div class="settings-password-form">
            <label class="field"><span>{{ t('settingsDiagnostics.fields.newPassword') }}</span><input v-model="passwordForm.newPassword" type="password" autocomplete="new-password" /></label>
            <div class="settings-checkbox-row">
              <label class="checkbox-field checkbox-field--nowrap"><input v-model="passwordForm.revokeSessions" type="checkbox" /><span>{{ t('settingsDiagnostics.fields.revokeSessions') }}</span></label>
              <label class="checkbox-field checkbox-field--nowrap"><input v-model="passwordForm.revokeUserTokens" type="checkbox" /><span>{{ t('settingsDiagnostics.fields.revokeUserTokens') }}</span></label>
            </div>
            <Button variant="secondary" :disabled="!canWrite || !passwordForm.newPassword" @click="resetPassword"><RotateCcw :size="16" />{{ t('settingsDiagnostics.actions.resetPassword') }}</Button>
          </div>
        </details>
      </section>
      <div v-else class="settings-account-empty">{{ t('settingsDiagnostics.emptyUsers') }}</div>
    </div>

    <div v-if="showCreateUser" class="settings-modal-backdrop" @click="showCreateUser = false">
      <section class="settings-modal" role="dialog" aria-modal="true" :aria-label="t('settingsDiagnostics.actions.createUser')" @click.stop @keydown.esc="showCreateUser = false">
        <header class="settings-panel__heading">
          <h2>{{ t('settingsDiagnostics.actions.createUser') }}</h2>
          <button type="button" class="settings-modal__close" :aria-label="t('common.cancel')" @click="showCreateUser = false"><X :size="16" /></button>
        </header>
        <div class="form-grid settings-account-form">
          <label class="field"><span>{{ t('settingsDiagnostics.fields.username') }}</span><input v-model.trim="createUserForm.username" autocomplete="off" /></label>
          <label class="field"><span>{{ t('settingsDiagnostics.fields.displayName') }}</span><input v-model.trim="createUserForm.displayName" autocomplete="off" /></label>
          <label class="field"><span>{{ t('settingsDiagnostics.fields.password') }}</span><input v-model="createUserForm.password" type="password" autocomplete="new-password" /></label>
          <label class="field"><span>{{ t('settingsDiagnostics.fields.defaultTokenName') }}</span><input v-model.trim="createUserForm.tokenName" autocomplete="off" /></label>
          <label class="field field--wide"><span>{{ t('settingsDiagnostics.fields.scopes') }}</span><MultiSelect :model-value="createUserForm.scopes" :options="scopeOptions" :placeholder="t('settingsDiagnostics.placeholders.scopeList')" @update:model-value="updateCreateUserScopes" /></label>
          <label class="field field--wide"><span>{{ t('settingsDiagnostics.fields.projectVisibility') }}</span><input v-model.trim="createUserForm.projectIds" autocomplete="off" :placeholder="t('settingsDiagnostics.placeholders.projectList')" /></label>
          <label class="checkbox-field"><input v-model="createUserForm.issueToken" type="checkbox" /><span>{{ t('settingsDiagnostics.fields.issueDefaultToken') }}</span></label>
        </div>
        <footer class="settings-modal__actions">
          <Button variant="secondary" @click="showCreateUser = false">{{ t('common.cancel') }}</Button>
          <Button variant="primary" :disabled="!canWrite || usersLoading" :loading="usersLoading" @click="createUser"><UserPlus :size="16" />{{ t('settingsDiagnostics.actions.createUser') }}</Button>
        </footer>
      </section>
    </div>

    <ConfirmDialog
      v-if="pendingDeleteUser"
      :title="t('common.confirmDelete')"
      :message="t('settingsDiagnostics.messages.confirmDeleteUser', { username: pendingDeleteUser.display_name || pendingDeleteUser.username })"
      :confirm-label="t('settingsDiagnostics.actions.delete')"
      :cancel-label="t('common.cancel')"
      :busy="accountDangerActionKey === `user:${pendingDeleteUser.user_id}`"
      @cancel="pendingDeleteUser = null"
      @confirm="removeUser"
    />

    <ConfirmDialog
      v-if="pendingRevokeToken"
      :title="t('settingsDiagnostics.actions.revoke')"
      :message="t('settingsDiagnostics.messages.confirmRevokeToken', { tokenName: pendingRevokeToken.token_name })"
      :confirm-label="t('settingsDiagnostics.actions.revoke')"
      :cancel-label="t('common.cancel')"
      :busy="accountDangerActionKey === `token:${pendingRevokeToken.token_id}`"
      @cancel="pendingRevokeToken = null"
      @confirm="revokeToken"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Copy, KeyRound, Power, RefreshCw, RotateCcw, Trash2, UserPlus, X } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { useSessionStore } from '@/app/stores/session.store'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import type { LocalAuthUser } from '@/shared/contracts'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import MultiSelect from '@/shared/ui/components/MultiSelect.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import InlineMessage from '@/shared/ui/feedback/InlineMessage.vue'
import { isProtectedSoleAmvarUser } from '../account-protection'
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
const accountDangerActionKey = ref<string | null>(null)
const pendingDeleteUser = ref<LocalAuthUser | null>(null)
const pendingRevokeToken = ref<LocalAuthUserToken | null>(null)
const showCreateUser = ref(false)
const showTokenForm = ref(false)

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
const isSelectedSoleAmvar = computed(() => isProtectedSoleAmvarUser(users.value, selectedUser.value?.user_id))
const soleAmvarProtectionMessage = computed(() => t('settingsDiagnostics.messages.soleAmvarProtected'))
const scopeOptions = computed(() => [
  { label: t('settingsDiagnostics.fields.allScopes'), value: '*', description: '*' },
  { label: 'workflows:read', value: 'workflows:read' },
  { label: 'workflows:write', value: 'workflows:write' },
  { label: 'projects:delete', value: 'projects:delete' },
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
    showCreateUser.value = false
    statusMessage.value = t('settingsDiagnostics.messages.userCreated')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('settingsDiagnostics.messages.userCreateFailed')
  } finally {
    usersLoading.value = false
  }
}

async function toggleUser(userId: string, isActive: boolean): Promise<void> {
  if (!canWrite.value || (!isActive && isProtectedSoleAmvarUser(users.value, userId))) return
  errorMessage.value = null
  try {
    await updateLocalAuthUser(userId, { is_active: isActive })
    await loadUsers()
    statusMessage.value = isActive ? t('settingsDiagnostics.messages.userEnabled') : t('settingsDiagnostics.messages.userDisabled')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('settingsDiagnostics.messages.userUpdateFailed')
  }
}

function requestRemoveUser(user: LocalAuthUser): void {
  if (!canWrite.value || user.user_id === currentUserId.value || isProtectedSoleAmvarUser(users.value, user.user_id) || accountDangerActionKey.value) return
  pendingDeleteUser.value = user
}

async function removeUser(): Promise<void> {
  const user = pendingDeleteUser.value
  if (!user) return
  const userId = user.user_id
  accountDangerActionKey.value = `user:${userId}`
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
  } finally {
    accountDangerActionKey.value = null
    pendingDeleteUser.value = null
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
    showTokenForm.value = false
    statusMessage.value = t('settingsDiagnostics.messages.tokenCreated')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('settingsDiagnostics.messages.tokenCreateFailed')
  } finally {
    tokensLoading.value = false
  }
}

function requestRevokeToken(token: LocalAuthUserToken): void {
  if (!selectedUser.value || !canWrite.value || token.revoked_at || accountDangerActionKey.value) return
  pendingRevokeToken.value = token
}

async function revokeToken(): Promise<void> {
  const user = selectedUser.value
  const token = pendingRevokeToken.value
  if (!user || !token) return
  const tokenId = token.token_id
  accountDangerActionKey.value = `token:${tokenId}`
  errorMessage.value = null
  try {
    await revokeLocalAuthUserToken(user.user_id, tokenId)
    await loadTokens(user.user_id)
    statusMessage.value = t('settingsDiagnostics.messages.tokenRevoked')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('settingsDiagnostics.messages.tokenRevokeFailed')
  } finally {
    accountDangerActionKey.value = null
    pendingRevokeToken.value = null
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

function formatProjectVisibility(value: string[]): string {
  return value.length > 0 ? value.join(', ') : t('settingsDiagnostics.fields.allProjects')
}

function formatScopeSummary(value: string[]): string {
  if (value.includes('*')) return t('settingsDiagnostics.fields.allScopes')
  if (value.length === 0) return '-'
  return value.join(', ')
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
