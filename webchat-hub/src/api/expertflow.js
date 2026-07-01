export class ExpertFlowError extends Error {
  constructor (message, status) {
    super(message)
    this.name = 'ExpertFlowError'
    this.status = status
  }
}

function normalizeTenant (tenant) {
  const trimmed = (tenant || '').trim().replace(/\/+$/, '')
  if (!trimmed) throw new ExpertFlowError('Tenant URL is required')
  if (/^https?:\/\//i.test(trimmed)) return trimmed
  return `https://${trimmed}`
}

async function parseJson (res) {
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    if (text.startsWith('<!DOCTYPE') || text.startsWith('<html')) {
      throw new ExpertFlowError('Unexpected HTML response — check tenant URL or login', res.status)
    }
    throw new ExpertFlowError(text.slice(0, 200) || 'Invalid response', res.status)
  }
}

async function request (url, options = {}) {
  const res = await fetch(url, {
    ...options,
    headers: {
      Accept: 'application/json',
      ...options.headers,
    },
  })
  const data = await parseJson(res)
  if (!res.ok) {
    const msg = data?.message || data?.detail || data?.title || res.statusText
    throw new ExpertFlowError(msg, res.status)
  }
  return data
}

export function buildWidgetIframeUrl (tenantBase, widgetIdentifier, serviceIdentifier) {
  const customerId = `hub-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
  const params = new URLSearchParams({
    widgetIdentifier,
    serviceIdentifier: String(serviceIdentifier),
    channelCustomerIdentifier: customerId,
    Source: 'WebchatHub',
  })
  return `${tenantBase}/customer-widget/#/widget?${params.toString()}`
}

export function buildWidgetScript (tenantBase, widgetIdentifier, serviceIdentifier) {
  return `<!-- ExpertFlow Customer Widget -->
<script type="text/javascript">
  var __cim = __cim || {};
  __cim.customerWidgetUrl = "${tenantBase}/customer-widget";
  __cim.widgetIdentifier = "${widgetIdentifier}";
  __cim.serviceIdentifier = "${serviceIdentifier}";
  __cim.Source = "Web";
  (function () {
    var s = document.createElement("script");
    var t = document.getElementsByTagName("script")[0];
    s.src = __cim.customerWidgetUrl + "/widget-assets/widget/init_widget.js";
    s.charset = "UTF-8";
    t.parentNode.insertBefore(s, t);
  })();
</script>`
}

function authHeaders (token, tenantId) {
  return {
    Authorization: `Bearer ${token}`,
    Tenant: tenantId || '',
    'Content-Type': 'application/json',
  }
}

export const expertflow = {
  normalizeTenant,

  async login (tenant, username, password) {
    const base = normalizeTenant(tenant)
    const data = await request(`${base}/unified-admin/keycloakLogin`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    const token = data?.data?.token
    if (!token) throw new ExpertFlowError('Login succeeded but no token returned')
    return { token, tenantBase: base }
  },

  async getBots (tenantBase, token, tenantId) {
    return request(`${tenantBase}/bot-framework/bot-connectors`, {
      headers: authHeaders(token, tenantId),
    })
  },

  async getWidgets (tenantBase) {
    return request(`${tenantBase}/ccm/widget-configs`)
  },

  async getChannels (tenantBase, token) {
    return request(`${tenantBase}/ccm/channels?limit=500`, {
      headers: authHeaders(token, ''),
    })
  },

  async testCustomBot (botUri, message, sessionId) {
    const payload = {
      message,
      text: message,
      sender: sessionId || `webchat-hub-${Date.now()}`,
      session_id: sessionId || `webchat-hub-${Date.now()}`,
    }
    const res = await fetch(botUri, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify(payload),
    })
    const text = await res.text()
    let body
    try {
      body = JSON.parse(text)
    } catch {
      body = text
    }
    return { status: res.status, ok: res.ok, body }
  },
}

export function mapWebchats (widgets, channels, bots) {
  const botMap = Object.fromEntries((bots || []).map((b) => [b.botId, b]))
  const webChannels = (channels || []).filter(
    (c) => c.channelType?.name === 'WEB' && !c.isDeleted,
  )

  const entries = []

  for (const widget of widgets || []) {
    if (widget.deleted) continue
    const id = widget.widgetIdentifier?.toLowerCase()
    let channel = webChannels.find((c) =>
      c.name?.toLowerCase().includes(id) ||
      c.serviceIdentifier === id ||
      (id === 'efcx4' && c.serviceIdentifier === '1000') ||
      (id === 'demo' && c.serviceIdentifier === '1100') ||
      (id === 'delaware' && c.serviceIdentifier === '1200') ||
      (id === 'florida' && c.serviceIdentifier === '1300'),
    )
    if (!channel && webChannels.length === 1) channel = webChannels[0]

    const botId = channel?.channelConfig?.botId
    entries.push({
      kind: 'webchat',
      id: widget.id,
      widgetIdentifier: widget.widgetIdentifier,
      title: widget.title || widget.widgetIdentifier,
      subtitle: widget.subTitle,
      theme: widget.theme,
      serviceIdentifier: channel?.serviceIdentifier || '',
      channelName: channel?.name || '—',
      bot: botMap[botId] || null,
      botId,
      webRtc: widget.webRtc?.enableWebRtc || false,
    })
  }

  for (const channel of webChannels) {
    const already = entries.some((e) => e.serviceIdentifier === channel.serviceIdentifier)
    if (already) continue
    const botId = channel.channelConfig?.botId
    entries.push({
      kind: 'webchat',
      id: channel.id,
      widgetIdentifier: channel.name?.replace(/\s+/g, '-').toLowerCase(),
      title: channel.name,
      subtitle: `Service ID ${channel.serviceIdentifier}`,
      theme: '#2889e9',
      serviceIdentifier: channel.serviceIdentifier,
      channelName: channel.name,
      bot: botMap[botId] || null,
      botId,
      webRtc: false,
      unmatched: true,
    })
  }

  return entries
}

export function mapBotChannels (bots, channels) {
  return (bots || []).map((bot) => {
    const linked = (channels || []).filter(
      (c) => c.channelConfig?.botId === bot.botId && !c.isDeleted,
    )
    return {
      ...bot,
      channels: linked.map((c) => ({
        id: c.id,
        name: c.name,
        type: c.channelType?.name,
        serviceIdentifier: c.serviceIdentifier,
        isWeb: c.channelType?.name === 'WEB',
      })),
    }
  })
}
