import type { RouteRecordRaw } from 'vue-router'

const InferenceWorkspacePage = () => import('./pages/InferenceWorkspacePage.vue')

export const inferenceRoutes: RouteRecordRaw[] = [
  {
    path: '/inference',
    component: InferenceWorkspacePage,
    meta: { requiredScopes: ['models:read'] },
  },
]
