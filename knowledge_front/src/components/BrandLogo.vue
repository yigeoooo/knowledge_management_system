<script setup lang="ts">
defineProps<{ compact?: boolean }>();
</script>
<template>
  <RouterLink
    to="/"
    class="brand"
    aria-label="跨维智能知识平台首页"
  >
    <img
      src="/brand/dexforce-logo.svg"
      alt="跨维智能 DEXFORCE"
      width="159"
      height="50"
    />
    <template v-if="!compact">
      <span class="brand-divider" />
      <span class="brand-product">
        知识平台
        <span>KNOWLEDGE HUB</span>
      </span>
    </template>
  </RouterLink>
</template>
