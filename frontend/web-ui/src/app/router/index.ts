import { createRouter, createWebHistory } from 'vue-router'

import { routes } from './routes'

export function createAppRouter() {
  return createRouter({
    history: createWebHistory(),
    routes,
    scrollBehavior() {
      return { top: 0 }
    },
  })
}