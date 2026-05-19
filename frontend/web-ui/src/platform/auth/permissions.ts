import type { CurrentUser } from '@/shared/contracts'

export function hasScope(user: CurrentUser | null, requiredScope: string): boolean {
  const grantedScopes = user?.scopes ?? []
  return grantedScopes.some((grantedScope) => {
    if (grantedScope === '*' || grantedScope === requiredScope) {
      return true
    }
    return grantedScope.endsWith(':*') && requiredScope.startsWith(grantedScope.slice(0, -1))
  })
}

export function hasScopes(user: CurrentUser | null, requiredScopes: string[]): boolean {
  return requiredScopes.every((requiredScope) => hasScope(user, requiredScope))
}