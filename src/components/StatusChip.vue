<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: { type: String, default: '' },
})

const meta = computed(() => {
  const map = {
    success: { color: 'success', icon: 'mdi-check-circle' },
    error: { color: 'error', icon: 'mdi-close-circle' },
    failed: { color: 'error', icon: 'mdi-close-circle' },
    running: { color: 'info', icon: 'mdi-play-circle' },
    waiting: { color: 'warning', icon: 'mdi-clock-outline' },
    starting: { color: 'warning', icon: 'mdi-progress-clock' },
    stopped: { color: 'grey', icon: 'mdi-stop-circle' },
    stopping: { color: 'grey', icon: 'mdi-stop-circle-outline' },
  }
  return map[(props.status || '').toLowerCase()] || { color: 'grey', icon: 'mdi-help-circle' }
})
</script>

<template>
  <v-chip
    :color="meta.color"
    size="small"
    variant="flat"
    :prepend-icon="meta.icon"
  >
    {{ status || 'unknown' }}
  </v-chip>
</template>
