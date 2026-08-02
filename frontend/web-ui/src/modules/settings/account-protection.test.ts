import { describe, expect, it } from 'vitest'

import { isProtectedSoleAmvarUser } from './account-protection'

describe('isProtectedSoleAmvarUser', () => {
  it('protects the only amvar user', () => {
    expect(isProtectedSoleAmvarUser([{ user_id: 'user-amvar', username: 'amvar' }], 'user-amvar')).toBe(true)
  })

  it('matches the amvar username without case or surrounding whitespace', () => {
    expect(isProtectedSoleAmvarUser([{ user_id: 'user-amvar', username: ' AMVAR ' }], 'user-amvar')).toBe(true)
  })

  it('does not protect a non-amvar user or amvar when another user exists', () => {
    expect(isProtectedSoleAmvarUser([{ user_id: 'user-admin', username: 'admin' }], 'user-admin')).toBe(false)
    expect(isProtectedSoleAmvarUser([
      { user_id: 'user-amvar', username: 'amvar' },
      { user_id: 'user-admin', username: 'admin' },
    ], 'user-amvar')).toBe(false)
  })
})
