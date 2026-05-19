<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <section class="error-view">
    <h1>页面不存在</h1>
    <p>当前路径没有对应的前端视图。</p>
    <RouterLink to="/projects">返回工作台</RouterLink>
  </section>
</template>