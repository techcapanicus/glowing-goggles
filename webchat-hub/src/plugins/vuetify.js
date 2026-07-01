import 'vuetify/styles'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

export default createVuetify({
  components,
  directives,
  theme: {
    defaultTheme: 'webchatLight',
    themes: {
      webchatLight: {
        dark: false,
        colors: {
          primary: '#00609C',
          secondary: '#546e7a',
          accent: '#2889e9',
          surface: '#ffffff',
          background: '#f4f6f8',
        },
      },
      webchatDark: {
        dark: true,
        colors: {
          primary: '#4da3d9',
          secondary: '#78909c',
          accent: '#64b5f6',
          surface: '#1e2a36',
          background: '#121820',
        },
      },
    },
  },
})
