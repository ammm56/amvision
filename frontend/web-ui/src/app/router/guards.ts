import type { Pinia } from 'pinia'
import type { Router } from 'vue-router'

import { useSessionStore } from '../stores/session.store'

export function registerRouterGuards(router: Router, pinia: Pinia): void {
  router.beforeEach((to) => {
    const sessionStore = useSessionStore(pinia)
    const requiresAuth = to.meta.requiresAuth !== false

    if (!requiresAuth) {
      if (to.path === '/login' && sessionStore.isAuthenticated) {
        return { path: '/projects', replace: true }
      }
      return true
    }

    if (!sessionStore.isInitialized) {
      return { path: '/', replace: true, query: { redirect: to.fullPath } }
    }

    if (!sessionStore.isAuthenticated) {
      return { path: '/login', replace: true, query: { redirect: to.fullPath } }
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