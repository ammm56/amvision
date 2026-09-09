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
        <Button variant="primary" :disabled="!canWrite" @click="openCreateUser">
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
              :disabled="!canWrite || selectedUser.user_id === currentUserId || Boolean(selectedUser.metadata?.system_default_user) || isSelectedSoleAmvar || accountDangerActionKey !== null"
              :title="isSelectedSoleAmvar ? soleAmvarProtectionMessage : undefined"
              @click="requestRemoveUser(selectedUser)"
            >
              <Trash2 :size="15" />
              {{ t('settingsDiagnostics.actions.delete') }}
            </Button>
          </div>
        </header>

        <div class="settings-panel__actions"><Button v-if="canWrite" variant="secondary" size="sm" @click="openAccess(selectedUser)">{{ t('userAccess.edit') }}</Button></div>
        <dl class="settings-metadata-grid settings-account-summary">
          <div><dt>{{ t('userAccess.pagesTitle') }}</dt><dd>{{ selectedUser.allowed_pages == null ? t('userAccess.compatible') : selectedUser.allowed_pages.map(id => t(`userAccess.pages.${id}`)).join('、') || '—' }}</dd></div>
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

    <ConfirmDialog v-if="showCreateUser" :title="t('settingsDiagnostics.actions.createUser')" :confirm-label="t('settingsDiagnostics.actions.createUser')" :cancel-label="t('common.cancel')" confirm-variant="primary" size="wide" scroll-body initial-focus="first-field" :busy="usersLoading" :confirm-disabled="!canWrite || Boolean(userAccessIssue(createAccess)) || !createUserForm.username || !createUserForm.password" @cancel="showCreateUser = false" @confirm="createUser">
      <div class="form-grid settings-account-form">
        <label class="field"><span>{{ t('settingsDiagnostics.fields.username') }}</span><input v-model.trim="createUserForm.username" autocomplete="off" /></label>
        <label class="field"><span>{{ t('settingsDiagnostics.fields.displayName') }}</span><input v-model.trim="createUserForm.displayName" autocomplete="off" /></label>
        <label class="field field--wide"><span>{{ t('settingsDiagnostics.fields.password') }}</span><input v-model="createUserForm.password" type="password" autocomplete="new-password" /></label>
      </div>
      <UserAccessForm v-model="createAccess" :inert="usersLoading" />
      <label class="checkbox-field"><input v-model="createUserForm.issueToken" type="checkbox" /><span>{{ t('settingsDiagnostics.fields.issueDefaultToken') }}</span></label>
      <label v-if="createUserForm.issueToken" class="field"><span>{{ t('settingsDiagnostics.fields.defaultTokenName') }}</span><input v-model.trim="createUserForm.tokenName" /></label>
      <InlineError :message="errorMessage" />
    </ConfirmDialog>
    <ConfirmDialog v-if="editingUser" :title="t('userAccess.edit')" :message="editingUser.display_name || editingUser.username" :confirm-label="t('startupPage.save')" :cancel-label="t('common.cancel')" confirm-variant="primary" size="wide" scroll-body initial-focus="first-field" :busy="accessSaving" :confirm-disabled="!canWrite || Boolean(userAccessIssue(editAccess))" @cancel="editingUser = null" @confirm="saveAccess">
      <UserAccessForm v-model="editAccess" :inert="accessSaving" />
      <InlineError :message="accessError" />
    </ConfirmDialog>

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
import { Copy, KeyRound, Power, RefreshCw, RotateCcw, Trash2, UserPlus } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { useSessionStore } from '@/app/stores/session.store'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import type { LocalAuthUser } from '@/shared/contracts'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import UserAccessForm from './UserAccessForm.vue'
import { emptyUserAccess, userAccessDraft, userAccessIssue } from '../user-access-form'
import { firstAccessiblePath } from '@/platform/auth/page-access'
import { useRouter } from 'vue-router'
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

const { t, te } = useI18n()
const sessionStore = useSessionStore()
const router = useRouter()
const createAccess = ref(emptyUserAccess())
const editingUser = ref<LocalAuthUser | null>(null)
const editAccess = ref(emptyUserAccess())
const accessSaving = ref(false)
const accessError = ref<string | null>(null)

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
  scopes: [] as string[],
  projectIds: '',
  issueToken: false,
  tokenName: 'default',
})
const tokenForm = reactive({ tokenName: 'default', ttlHours: null as number | null })
const passwordForm = reactive({ newPassword: '', revokeSessions: true, revokeUserTokens: false })

const canWrite = computed(() => sessionStore.hasScopes(['auth:write']))
const currentUserId = computed(() => sessionStore.currentUser?.principal_id ?? '')
const selectedUser = computed(() => users.value.find((user) => user.user_id === selectedUserId.value) ?? null)
const isSelectedSoleAmvar = computed(() => isProtectedSoleAmvarUser(users.value, selectedUser.value?.user_id))
const soleAmvarProtectionMessage = computed(() => t('settingsDiagnostics.messages.soleAmvarProtected'))

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
  tokens.value = []
  editingUser.value = null
  selectedUserId.value = userId
  issuedToken.value = null
  await loadTokens(userId)
}

async function loadTokens(userId: string): Promise<void> {
  tokensLoading.value = true
  errorMessage.value = null
  try {
    const loaded = await listLocalAuthUserTokens(userId)
    if (selectedUserId.value === userId) tokens.value = loaded
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('settingsDiagnostics.messages.tokensLoadFailed')
  } finally {
    tokensLoading.value = false
  }
}

function openCreateUser(): void {
  resetCreateUserForm()
  errorMessage.value = null
  showCreateUser.value = true
}

async function createUser(): Promise<void> {
  if (!canWrite.value || usersLoading.value || userAccessIssue(createAccess.value)) return
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
      scopes: createAccess.value.scopes,
      allowed_pages: createAccess.value.pages,
      project_ids: createAccess.value.allProjects ? [] : createAccess.value.projectIds,
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
    if (!canWrite.value || user.user_id === currentUserId.value || user.metadata?.system_default_user || isProtectedSoleAmvarUser(users.value, user.user_id) || accountDangerActionKey.value) return
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

function formatProjectVisibility(value: string[]): string {
  return value.length > 0 ? value.join(', ') : t('settingsDiagnostics.fields.allProjects')
}

function formatScopeSummary(value: string[]): string {
  if (value.includes('*')) return t('settingsDiagnostics.fields.allScopes')
  if (value.length === 0) return '-'
  return value.map(scope => te(`userAccess.operations.${scope}`) ? t(`userAccess.operations.${scope}`) : scope).join('、')
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
  createUserForm.scopes = []
  createAccess.value = emptyUserAccess()
  createUserForm.projectIds = ''
  createUserForm.tokenName = 'default'
  createUserForm.issueToken = false
}
async function openAccess(user: LocalAuthUser): Promise<void> {
  if (!canWrite.value) return
  accessError.value = null
  try {
    const latest = (await listLocalAuthUsers()).find(item => item.user_id === user.user_id)
    if (!latest) { await loadUsers(); return }
    editAccess.value = userAccessDraft(latest)
    editingUser.value = latest
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : String(error) }
}
async function saveAccess(): Promise<void> {
  const user = editingUser.value
  if (!user || !canWrite.value || accessSaving.value || userAccessIssue(editAccess.value)) return
  accessSaving.value = true
  accessError.value = null
  try {
    const updated = await updateLocalAuthUser(user.user_id, {
      scopes: editAccess.value.scopes, allowed_pages: editAccess.value.pages,
      project_ids: editAccess.value.allProjects ? [] : editAccess.value.projectIds,
    }, user.updated_at)
    users.value = users.value.map(item => item.user_id === updated.user_id ? updated : item)
    editingUser.value = null
    statusMessage.value = t('userAccess.saved')
    if (user.user_id === currentUserId.value) {
      await sessionStore.refreshPermissions()
      if (!sessionStore.currentUser?.scopes.some(scope => scope === '*' || scope === 'auth:*' || scope === 'auth:read') || sessionStore.currentUser.allowed_pages && !sessionStore.currentUser.allowed_pages.includes('settings-accounts')) await router.replace(firstAccessiblePath(sessionStore.currentUser))
    }
  } catch (error) { accessError.value = error instanceof Error ? error.message : String(error) }
  finally { accessSaving.value = false }
}
</script>
