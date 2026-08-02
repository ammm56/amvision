import type { LocalAuthUser } from '@/shared/contracts'

type LocalAuthUserIdentity = Pick<LocalAuthUser, 'user_id' | 'username'>

export function isProtectedSoleAmvarUser(
  users: readonly LocalAuthUserIdentity[],
  userId: string | null | undefined,
): boolean {
  if (!userId || users.length !== 1) return false
  const [user] = users
  return user.user_id === userId && user.username.trim().toLocaleLowerCase() === 'amvar'
}
