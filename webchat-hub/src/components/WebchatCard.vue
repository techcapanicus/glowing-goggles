<script setup>
import { computed } from 'vue'

const props = defineProps({
  entry: { type: Object, required: true },
  tenantBase: { type: String, required: true },
  active: { type: Boolean, default: false },
})

const emit = defineEmits(['open'])

const botLabel = computed(() => {
  if (!props.entry.bot) return 'No bot mapped'
  return `${props.entry.bot.botName} (${props.entry.bot.botType})`
})

const botColor = computed(() => {
  const t = props.entry.bot?.botType
  if (t === 'RASA') return 'blue'
  if (t === 'CUSTOM') return 'deep-purple'
  return 'grey'
})
</script>

<template>
  <v-card
    variant="outlined"
    :class="{ 'border-primary': active }"
    class="webchat-card"
    @click="emit('open', entry)"
  >
    <v-card-item>
      <template #prepend>
        <v-avatar
          :color="entry.theme || 'primary'"
          size="40"
        >
          <v-icon
            icon="mdi-chat"
            color="white"
          />
        </v-avatar>
      </template>
      <v-card-title>{{ entry.title }}</v-card-title>
      <v-card-subtitle>{{ entry.widgetIdentifier }} · {{ entry.channelName }}</v-card-subtitle>
    </v-card-item>
    <v-card-text class="pt-0">
      <v-chip
        size="small"
        :color="botColor"
        variant="tonal"
        class="mr-2 mb-2"
      >
        {{ botLabel }}
      </v-chip>
      <v-chip
        v-if="entry.serviceIdentifier"
        size="small"
        variant="outlined"
        class="mr-2 mb-2"
      >
        Svc {{ entry.serviceIdentifier }}
      </v-chip>
      <v-chip
        v-if="entry.webRtc"
        size="small"
        color="green"
        variant="tonal"
        class="mb-2"
      >
        WebRTC
      </v-chip>
      <v-chip
        v-if="entry.unmatched"
        size="small"
        color="warning"
        variant="tonal"
        class="mb-2"
      >
        No widget config
      </v-chip>
    </v-card-text>
    <v-card-actions>
      <v-btn
        color="primary"
        variant="tonal"
        prepend-icon="mdi-open-in-new"
        size="small"
        :disabled="!entry.serviceIdentifier"
        @click.stop="emit('open', entry)"
      >
        Open chat
      </v-btn>
    </v-card-actions>
  </v-card>
</template>

<style scoped>
.webchat-card {
  cursor: pointer;
  transition: box-shadow 0.2s;
}
.webchat-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
}
.border-primary {
  border-color: rgb(var(--v-theme-primary)) !important;
  border-width: 2px;
}
</style>
