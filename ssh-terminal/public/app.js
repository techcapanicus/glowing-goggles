(() => {
  'use strict';

  const statusDot = document.getElementById('status-dot');
  const statusText = document.getElementById('status-text');
  const reconnectBtn = document.getElementById('reconnect-btn');
  const authOverlay = document.getElementById('auth-overlay');
  const authForm = document.getElementById('auth-form');
  const authPassword = document.getElementById('auth-password');
  const authError = document.getElementById('auth-error');

  const term = new Terminal({
    cursorBlink: true,
    scrollback: 5000,
    fontFamily: "'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace",
    fontSize: 14,
    lineHeight: 1.2,
    theme: {
      background: '#0d1117',
      foreground: '#c9d1d9',
      cursor: '#58a6ff',
      selectionBackground: '#264f78',
    },
  });

  const fitAddon = new FitAddon.FitAddon();
  term.loadAddon(fitAddon);
  term.loadAddon(new WebLinksAddon.WebLinksAddon());

  term.open(document.getElementById('terminal'));

  try {
    term.loadAddon(new WebglAddon.WebglAddon());
  } catch {
    // WebGL renderer unsupported in this browser; falls back to the default canvas renderer.
  }

  fitAddon.fit();

  let ws = null;
  let awaitingAuth = false;
  let pendingResize = null;

  function setStatus(text, cls) {
    statusText.textContent = text;
    statusDot.className = 'dot' + (cls ? ` ${cls}` : '');
  }

  function showAuthOverlay(show) {
    authOverlay.classList.toggle('hidden', !show);
    if (show) {
      authError.classList.add('hidden');
      authPassword.value = '';
      setTimeout(() => authPassword.focus(), 0);
    }
  }

  function sendResize() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    fitAddon.fit();
    ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
  }

  function connect() {
    if (ws) {
      try {
        ws.close();
      } catch {
        /* ignore */
      }
    }

    term.reset();
    setStatus('connecting…', 'warn');
    showAuthOverlay(false);

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${location.host}/ws`);

    ws.addEventListener('open', () => {
      setStatus('negotiating…', 'warn');
    });

    ws.addEventListener('message', (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }

      switch (msg.type) {
        case 'data':
          term.write(msg.data);
          break;
        case 'status':
          if (msg.data === 'auth-required') {
            awaitingAuth = true;
            showAuthOverlay(true);
            setStatus('awaiting app password', 'warn');
          } else if (msg.data === 'auth-ok') {
            awaitingAuth = false;
            showAuthOverlay(false);
            setStatus('authenticated, connecting to host…', 'warn');
          } else {
            setStatus(msg.data, msg.data.startsWith('connected') ? 'ok' : 'warn');
            if (msg.data.startsWith('connected')) {
              term.focus();
              sendResize();
            }
          }
          break;
        case 'error':
          setStatus(msg.data, 'err');
          if (awaitingAuth) {
            authError.textContent = msg.data;
            authError.classList.remove('hidden');
          } else {
            term.write(`\r\n\x1b[31m[ssh-terminal] ${msg.data}\x1b[0m\r\n`);
          }
          break;
      }
    });

    ws.addEventListener('close', () => {
      setStatus('disconnected — click Reconnect', 'err');
    });

    ws.addEventListener('error', () => {
      setStatus('connection error', 'err');
    });
  }

  term.onData((data) => {
    if (ws && ws.readyState === WebSocket.OPEN && !awaitingAuth) {
      ws.send(JSON.stringify({ type: 'data', data }));
    }
  });

  authForm.addEventListener('submit', (e) => {
    e.preventDefault();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'auth', data: authPassword.value }));
    }
  });

  reconnectBtn.addEventListener('click', connect);

  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(sendResize, 100);
  });

  connect();
})();
