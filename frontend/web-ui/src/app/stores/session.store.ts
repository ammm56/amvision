import { defineStore } from 'pinia'

import { useAppStore } from './app.store'
import { ApiError } from '@/shared/api/error'
import { apiRequest } from '@/shared/api/http-client'
import type { AuthLoginResponse, CurrentUser, LocalAuthUser, SystemBootstrapResponse } from '@/shared/contracts'
import { getRuntimeConfig } from '@/platform/runtime/runtime-config'
import { readStorageValue, removeStorageValue, writeStorageValue } from '@/platform/storage/browser-storage'
import { translate } from '@/platform/i18n'

type CredentialKind = 'session' | 'user-token' | 'static-bearer' | null
type LoginState = 'checking' | 'auto-authenticated' | 'authenticated' | 'manual-login-required' | 'offline' | 'failed'

const SESSION_TOKEN_KEY = 'amvision.web-ui.session-token'
const REFRESH_TOKEN_KEY = 'amvision.web-ui.refresh-token'
const TOKEN_EXPIRES_AT_KEY = 'amvision.web-ui.token-expires-at'
const REFRESH_EXPIRES_AT_KEY = 'amvision.web-ui.refresh-expires-at'
const USER_TOKEN_KEY = 'amvision.web-ui.user-token'

interface LoginInput {
  username: string
  password: string
  providerId?: string
}

function getManualLoginRequired(): boolean {
  const runtimeConfig = getRuntimeConfig()
  return readStorageValue(runtimeConfig.auth.manualLoginRequiredKey, runtimeConfig.storage.manualLoginStorage) === 'true'
}

function setManualLoginRequired(required: boolean): void {
  const runtimeConfig = getRuntimeConfig()
  if (required) {
    writeStorageValue(runtimeConfig.auth.manualLoginRequiredKey, 'true', runtimeConfig.storage.manualLoginStorage)
    return
  }
  removeStorageValue(runtimeConfig.auth.manualLoginRequiredKey, runtimeConfig.storage.manualLoginStorage)
}

function writeOptionalStorageValue(
  key: string,
  value: string | null,
  storageKind: 'localStorage' | 'sessionStorage' | 'memory',
): void {
  if (value === null) {
    removeStorageValue(key, storageKind)
    return
  }
  writeStorageValue(key, value, storageKind)
}

function normalizeLoginUser(user: LocalAuthUser): CurrentUser {
  return {
    principal_id: user.user_id,
    principal_type: user.principal_type,
    project_ids: user.project_ids,
    scopes: user.scopes,
    username: user.username,
    display_name: user.display_name,
    auth_provider_kind: user.provider_kind,
    auth_credential_kind: 'session',
  }
}

export const useSessionStore = defineStore('session', {
  state: () => ({
    isInitialized: false,
    authMode: null as string | null,
    bearerAuthEnabled: false,
    websocketQueryTokenEnabled: false,
    currentUser: null as CurrentUser | null,
    credentialKind: null as CredentialKind,
    accessToken: null as string | null,
    refreshToken: null as string | null,
    tokenExpiresAt: null as string | null,
    refreshExpiresAt: null as string | null,
    manualLoginRequired: false,
    defaultAutoLoginAvailable: false,
    loginState: 'checking' as LoginState,
    lastAuthError: null as string | null,
    bootstrap: null as SystemBootstrapResponse | null,
    refreshPromise: null as Promise<boolean> | null,
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.currentUser && state.accessToken),
    displayName: (state) => state.currentUser?.display_name || state.currentUser?.username || '',
  },
  actions: {
    async loadBootstrap(options: { skipAuth?: boolean; includeDevices?: boolean } = {}): Promise<SystemBootstrapResponse> {
      const bootstrap = await apiRequest<SystemBootstrapResponse>('/system/bootstrap', {
        query: options.includeDevices === undefined ? undefined : { include_devices: options.includeDevices },
        skipAuth: options.skipAuth ?? false,
      })
      if (
        options.includeDevices === false
        && this.bootstrap?.devices
        && Object.keys(this.bootstrap.devices).length > 0
        && Object.keys(bootstrap.devices ?? {}).length === 0
      ) {
        bootstrap.devices = this.bootstrap.devices
      }
      this.bootstrap = bootstrap
      this.authMode = bootstrap.auth_mode
      this.bearerAuthEnabled = bootstrap.bearer_auth_enabled
      this.websocketQueryTokenEnabled = bootstrap.websocket_query_token_enabled
      return bootstrap
    },
    async ensureDeviceBootstrap(): Promise<SystemBootstrapResponse | null> {
      const devices = this.bootstrap?.devices
      if (devices && Object.keys(devices).length > 0) {
        return this.bootstrap
      }
      try {
        return await this.loadBootstrap({ includeDevices: true })
      } catch {
        // 设备摘要只影响前端可选设备列表，失败时保持已有 bootstrap，页面主流程继续可用。
        return this.bootstrap
      }
    },
    hasScopes(requiredScopes: string[]): boolean {
      const grantedScopes = this.currentUser?.scopes ?? []
      return requiredScopes.every((requiredScope) =>
        grantedScopes.some((grantedScope) => {
          if (grantedScope === '*' || grantedScope === requiredScope) {
            return true
          }
          return grantedScope.endsWith(':*') && requiredScope.startsWith(grantedScope.slice(0, -1))
        }),
      )
    },
    async initializeSession(): Promise<void> {
      this.loginState = 'checking'
      this.lastAuthError = null
      this.manualLoginRequired = getManualLoginRequired()

      try {
        await this.loadBootstrap({ skipAuth: true, includeDevices: false })
        useAppStore().setBackendConnectionState('online')
      } catch (error) {
        this.isInitialized = true
        this.loginState = 'offline'
        this.lastAuthError = error instanceof Error ? error.message : translate('auth.backendConnectionFailed')
        useAppStore().setBackendConnectionState('offline')
        return
      }

      if (this.manualLoginRequired) {
        this.isInitialized = true
        this.loginState = 'manual-login-required'
        return
      }

      const restoredSessionToken = readStorageValue(SESSION_TOKEN_KEY, getRuntimeConfig().storage.sessionTokenStorage)
      const restoredRefreshToken = readStorageValue(REFRESH_TOKEN_KEY, getRuntimeConfig().storage.sessionTokenStorage)
      if (restoredSessionToken) {
        this.accessToken = restoredSessionToken
        this.refreshToken = restoredRefreshToken
        this.credentialKind = 'session'
        const validated = await this.loadCurrentUser('authenticated', { includeDevices: false })
        if (validated) {
          this.isInitialized = true
          return
        }
      }

      const storedUserToken = readStorageValue(USER_TOKEN_KEY, 'localStorage')
      const defaultUserToken = getRuntimeConfig().auth.defaultUserToken
      const candidateUserToken = storedUserToken || defaultUserToken
      this.defaultAutoLoginAvailable = Boolean(defaultUserToken && getRuntimeConfig().auth.autoLoginEnabled)

      if (getRuntimeConfig().auth.autoLoginEnabled && candidateUserToken) {
        this.accessToken = candidateUserToken
        this.refreshToken = null
        this.credentialKind = 'user-token'
        const validated = await this.loadCurrentUser('auto-authenticated', { includeDevices: false })
        if (validated) {
          this.isInitialized = true
          return
        }
      }

      this.isInitialized = true
      this.loginState = 'manual-login-required'
    },
    async loadCurrentUser(successState: LoginState, options: { includeDevices?: boolean } = {}): Promise<boolean> {
      try {
        const currentUser = await apiRequest<CurrentUser>('/system/me')
        this.currentUser = currentUser
        this.credentialKind = (currentUser.auth_credential_kind ?? this.credentialKind) as CredentialKind
        try {
          await this.loadBootstrap({ includeDevices: options.includeDevices ?? true })
        } catch {
          // 当前用户已完成鉴权，bootstrap 刷新失败时保留现有主体状态。
        }
        this.loginState = successState
        this.lastAuthError = null
        return true
      } catch (error) {
        this.currentUser = null
        this.accessToken = null
        this.refreshToken = null
        this.credentialKind = null
        this.lastAuthError = error instanceof Error ? error.message : translate('auth.sessionValidationFailed')
        return false
      }
    },
    async login(input: LoginInput): Promise<void> {
      const response = await apiRequest<AuthLoginResponse>('/auth/login', {
        method: 'POST',
        skipAuth: true,
        body: {
          provider_id: input.providerId ?? 'local',
          username: input.username,
          password: input.password,
        },
      })
      this.applyLoginResponse(response)
      await this.loadBootstrap()
      setManualLoginRequired(false)
      this.manualLoginRequired = false
      this.isInitialized = true
      this.loginState = 'authenticated'
    },
    applyLoginResponse(response: AuthLoginResponse): void {
      this.accessToken = response.access_token
      this.refreshToken = response.refresh_token
      this.tokenExpiresAt = response.expires_at
      this.refreshExpiresAt = response.refresh_expires_at
      this.currentUser = normalizeLoginUser(response.user)
      this.credentialKind = 'session'
      writeStorageValue(SESSION_TOKEN_KEY, response.access_token, getRuntimeConfig().storage.sessionTokenStorage)
      writeStorageValue(REFRESH_TOKEN_KEY, response.refresh_token, getRuntimeConfig().storage.sessionTokenStorage)
      writeOptionalStorageValue(TOKEN_EXPIRES_AT_KEY, response.expires_at, getRuntimeConfig().storage.sessionTokenStorage)
      writeOptionalStorageValue(REFRESH_EXPIRES_AT_KEY, response.refresh_expires_at, getRuntimeConfig().storage.sessionTokenStorage)
    },
    async refreshAccessToken(): Promise<boolean> {
      if (this.credentialKind !== 'session' || !this.refreshToken) {
        return false
      }
      if (this.refreshPromise) {
        return this.refreshPromise
      }
      this.refreshPromise = this.performRefresh()
      try {
        return await this.refreshPromise
      } finally {
        this.refreshPromise = null
      }
    },
    async performRefresh(): Promise<boolean> {
      try {
        const response = await apiRequest<AuthLoginResponse>('/auth/refresh', {
          method: 'POST',
          skipAuth: true,
          body: { refresh_token: this.refreshToken },
        })
        this.applyLoginResponse(response)
        return true
      } catch {
        this.clearForAuthFailure()
        return false
      }
    },
    async logout(): Promise<void> {
      const shouldCallLogout = this.credentialKind === 'session' && Boolean(this.accessToken)
      if (shouldCallLogout) {
        try {
          await apiRequest<void>('/auth/logout', { method: 'POST', responseType: 'void', retryOnUnauthorized: false })
        } catch (error) {
          if (!(error instanceof ApiError) || error.status !== 401) {
            this.lastAuthError = error instanceof Error ? error.message : translate('auth.logoutFailed')
          }
        }
      }
      this.clearCredentials()
      try {
        await this.loadBootstrap({ skipAuth: true })
      } catch {
        // 登出后刷新匿名 bootstrap 失败不影响本地凭据清理。
      }
      setManualLoginRequired(true)
      this.manualLoginRequired = true
      this.isInitialized = true
      this.loginState = 'manual-login-required'
    },
    clearForAuthFailure(): void {
      this.clearCredentials()
      this.isInitialized = true
      this.loginState = 'manual-login-required'
    },
    clearCredentials(): void {
      this.currentUser = null
      this.accessToken = null
      this.refreshToken = null
      this.tokenExpiresAt = null
      this.refreshExpiresAt = null
      this.credentialKind = null
      removeStorageValue(SESSION_TOKEN_KEY, getRuntimeConfig().storage.sessionTokenStorage)
      removeStorageValue(REFRESH_TOKEN_KEY, getRuntimeConfig().storage.sessionTokenStorage)
      removeStorageValue(TOKEN_EXPIRES_AT_KEY, getRuntimeConfig().storage.sessionTokenStorage)
      removeStorageValue(REFRESH_EXPIRES_AT_KEY, getRuntimeConfig().storage.sessionTokenStorage)
    },
  },
})
