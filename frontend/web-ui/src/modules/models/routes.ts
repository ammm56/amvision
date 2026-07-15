import type { RouteRecordRaw } from 'vue-router'

import ConversionTaskDetailPage from './pages/ConversionTaskDetailPage.vue'
import ModelOperationsPage from './pages/ModelOperationsPage.vue'
import TrainingTaskDetailPage from './pages/TrainingTaskDetailPage.vue'

export const modelRoutes: RouteRecordRaw[] = [
  {
    path: '/models',
    component: ModelOperationsPage,
    meta: { requiredScopes: ['models:read', 'tasks:read'] },
  },
  {
    path: '/models/:taskType/training-tasks/:taskId',
    component: TrainingTaskDetailPage,
    meta: { requiredScopes: ['tasks:read'] },
  },
  {
    path: '/models/:taskType/conversion-tasks/:taskId',
    component: ConversionTaskDetailPage,
    meta: { requiredScopes: ['tasks:read'] },
  },
]
