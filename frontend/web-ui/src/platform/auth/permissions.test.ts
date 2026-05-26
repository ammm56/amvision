import { describe, expect, it } from 'vitest'

import { hasScope, hasScopes } from './permissions'
import type { CurrentUser } from '@/shared/contracts'

const baseUser: CurrentUser = {
  principal_id: 'user-1',
  principal_type: 'user',
  project_ids: ['default'],
  scopes: ['tasks:read', 'datasets:*'],
}

describe('permissions', () => {
  it('matches exact scopes', () => {
    expect(hasScope(baseUser, 'tasks:read')).toBe(true)
    expect(hasScope(baseUser, 'tasks:write')).toBe(false)
  })

  it('matches scope prefixes and required scope lists', () => {
    expect(hasScope(baseUser, 'datasets:write')).toBe(true)
    expect(hasScopes(baseUser, ['tasks:read', 'datasets:write'])).toBe(true)
  })
})