<script setup>
defineProps({
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  initialTenant: { type: String, default: 'efcx4.expertflow.com' },
  initialUsername: { type: String, default: 'admin' },
})

const emit = defineEmits(['connect'])

const tenant = defineModel('tenant', { default: 'efcx4.expertflow.com' })
const username = defineModel('username', { default: 'admin' })
const password = defineModel('password', { default: 'admin' })

function submit () {
  emit('connect', { tenant: tenant.value, username: username.value, password: password.value })
}
</script>

<template>
  <v-container class="fill-height">
    <v-row
      align="center"
      justify="center"
    >
      <v-col
        cols="12"
        sm="8"
        md="5"
        lg="4"
      >
        <v-card
          class="pa-2"
          elevation="4"
        >
          <v-card-title class="text-h5 d-flex align-center">
            <v-icon
              icon="mdi-chat-processing-outline"
              class="mr-2"
              color="primary"
            />
            Webchat Hub
          </v-card-title>
          <v-card-subtitle class="mb-4">
            Access all ExpertFlow web widgets and bots in one place
          </v-card-subtitle>

          <v-card-text>
            <v-form @submit.prevent="submit">
              <v-text-field
                v-model="tenant"
                label="Tenant host"
                placeholder="efcx4.expertflow.com"
                prepend-inner-icon="mdi-web"
                hint="FQDN of your ExpertFlow tenant"
                persistent-hint
                class="mb-3"
              />
              <v-text-field
                v-model="username"
                label="Username"
                prepend-inner-icon="mdi-account"
                autocomplete="username"
                class="mb-3"
              />
              <v-text-field
                v-model="password"
                label="Password"
                type="password"
                prepend-inner-icon="mdi-lock"
                autocomplete="current-password"
                class="mb-3"
              />
              <v-alert
                v-if="error"
                type="error"
                variant="tonal"
                class="mb-3"
                density="compact"
              >
                {{ error }}
              </v-alert>
              <v-btn
                type="submit"
                color="primary"
                block
                size="large"
                :loading="loading"
              >
                Connect
              </v-btn>
            </v-form>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>
