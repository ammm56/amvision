import { apiRequest } from '@/shared/api/http-client'
import type { LocalAuthUser } from '@/shared/contracts'

export interface LocalAuthUserToken {
  token_id: string
  user_id: string
  token_name: string
  created_at: string
  expires_at?: string | null
  last_used_at?: string | null
  revoked_at?: string | null
  created_by_user_id?: string | null
  metadata?: Record<string, unknown>
}

export interface LocalAuthIssuedUserToken extends LocalAuthUserToken {
  token: string
  token_type: string
}

export interface LocalAuthUserCreateResult {
  user: LocalAuthUser
  initial_user_token?: LocalAuthIssuedUserToken | null
}

export interface LocalAuthInitialUserTokenInput {
  enabled: boolean
  token_name?: string
  ttl_hours?: number | null
  expires_at?: string | null
  metadata?: Record<string, unknown>
}

export interface LocalAuthUserCreateInput {
  username: string
  password: string
  display_name?: string | null
  principal_type?: string
  project_ids?: string[]
  scopes?: string[]
  metadata?: Record<string, unknown>
  initial_user_token?: LocalAuthInitialUserTokenInput | null
}

export interface LocalAuthUserUpdateInput {
  display_name?: string | null
  password?: string | null
  project_ids?: string[] | null
  scopes?: string[] | null
  is_active?: boolean | null
  metadata?: Record<string, unknown> | null
}

export interface LocalAuthPasswordResetInput {
  new_password: string
  revoke_sessions?: boolean
  revoke_user_tokens?: boolean
}

export interface LocalAuthUserTokenCreateInput {
  token_name: string
  ttl_hours?: number | null
  expires_at?: string | null
  metadata?: Record<string, unknown>
}

export async function listLocalAuthUsers(): Promise<LocalAuthUser[]> {
  return apiRequest<LocalAuthUser[]>('/auth/users')
}

export async function createLocalAuthUser(input: LocalAuthUserCreateInput): Promise<LocalAuthUserCreateResult> {
  return apiRequest<LocalAuthUserCreateResult>('/auth/users', { method: 'POST', body: input })
}

export async function updateLocalAuthUser(userId: string, input: LocalAuthUserUpdateInput): Promise<LocalAuthUser> {
  return apiRequest<LocalAuthUser>(`/auth/users/${encodeURIComponent(userId)}`, { method: 'PATCH', body: input })
}

export async function deleteLocalAuthUser(userId: string): Promise<void> {
  return apiRequest<void>(`/auth/users/${encodeURIComponent(userId)}`, { method: 'DELETE', responseType: 'void' })
}

export async function resetLocalAuthUserPassword(userId: string, input: LocalAuthPasswordResetInput): Promise<LocalAuthUser> {
  return apiRequest<LocalAuthUser>(`/auth/users/${encodeURIComponent(userId)}/reset-password`, { method: 'POST', body: input })
}

export async function listLocalAuthUserTokens(userId: string): Promise<LocalAuthUserToken[]> {
  return apiRequest<LocalAuthUserToken[]>(`/auth/users/${encodeURIComponent(userId)}/tokens`)
}

export async function createLocalAuthUserToken(userId: string, input: LocalAuthUserTokenCreateInput): Promise<LocalAuthIssuedUserToken> {
  return apiRequest<LocalAuthIssuedUserToken>(`/auth/users/${encodeURIComponent(userId)}/tokens`, { method: 'POST', body: input })
}

export async function revokeLocalAuthUserToken(userId: string, tokenId: string): Promise<void> {
  return apiRequest<void>(`/auth/users/${encodeURIComponent(userId)}/tokens/${encodeURIComponent(tokenId)}`, { method: 'DELETE', responseType: 'void' })
}
