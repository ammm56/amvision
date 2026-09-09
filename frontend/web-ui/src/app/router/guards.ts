import type { Pinia } from 'pinia'
import type { Router } from 'vue-router'

import { useSessionStore } from '../stores/session.store'
import { canAccessPath, firstAccessiblePath, settingsPath } from '@/platform/auth/page-access'

export function registerRouterGuards(router: Router, pinia: Pinia): void {
  router.beforeEach(async (to) => {
    const sessionStore = useSessionStore(pinia)
    const requiresAuth = to.meta.requiresAuth !== false

    if (!requiresAuth) {
      if (to.path === '/login' && sessionStore.isAuthenticated) {
        return { path: firstAccessiblePath(sessionStore.currentUser), replace: true }
      }
      return true
    }

    if (!sessionStore.isInitialized) {
      return { path: '/', replace: true, query: { redirect: to.fullPath } }
    }

    if (!sessionStore.isAuthenticated) {
      return { path: '/login', replace: true, query: { redirect: to.fullPath } }
    }

    await sessionStore.refreshPermissions()
    if (!sessionStore.isAuthenticated) return { path: '/login', replace: true }

    if (to.path === '/settings' && !to.query.category && !canAccessPath(sessionStore.currentUser, to.fullPath)) {
      return { path: settingsPath(sessionStore.currentUser) ?? '/forbidden', replace: true }
    }
    if (!['/forbidden', '/not-found'].includes(to.path) && !canAccessPath(sessionStore.currentUser, to.fullPath)) {
      return { path: '/forbidden', replace: true }
    }
    const requiredScopes = to.meta.requiredScopes
    if (Array.isArray(requiredScopes) && requiredScopes.length > 0) {
      if (!sessionStore.hasScopes(requiredScopes)) {
        return { path: '/forbidden', replace: true }
      }
    }

    return true
  })
}
