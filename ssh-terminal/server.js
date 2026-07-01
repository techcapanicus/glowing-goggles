'use strict';

require('dotenv').config();

const path = require('path');
const http = require('http');
const net = require('net');
const express = require('express');
const { WebSocketServer } = require('ws');
const { Client } = require('ssh2');

const PORT = parseInt(process.env.PORT || '3001', 10);
const HOST = process.env.HOST || '0.0.0.0';

const SSH_HOST = process.env.SSH_HOST;
const SSH_PORT = parseInt(process.env.SSH_PORT || '22', 10);
const SSH_USER = process.env.SSH_USER;
const SSH_PASSWORD = process.env.SSH_PASSWORD;

// A shared secret the browser must send before we open an SSH session.
// Prevents random visitors on the network from using this box as an SSH
// relay to the configured target host. Leave unset to disable (not
// recommended for anything reachable outside localhost).
const APP_PASSWORD = process.env.APP_PASSWORD || '';

if (!SSH_HOST || !SSH_USER || !SSH_PASSWORD) {
  console.error(
    '[ssh-terminal] Missing SSH_HOST, SSH_USER, or SSH_PASSWORD. ' +
      'Copy .env.example to .env and fill in the target host credentials.'
  );
}

const app = express();
app.use(express.static(path.join(__dirname, 'public')));
app.get('/healthz', (_req, res) => res.json({ ok: true }));

const server = http.createServer(app);
// Disable Nagle's algorithm on every connection: with it on, small frames
// (like single keystrokes) can sit buffered for tens of ms waiting to be
// coalesced with more data, which is the opposite of what a terminal wants.
server.on('connection', (socket) => socket.setNoDelay(true));

const wss = new WebSocketServer({ server, path: '/ws', perMessageDeflate: false });

function send(ws, type, data) {
  if (ws.readyState === ws.OPEN) {
    ws.send(JSON.stringify({ type, data }));
  }
}

wss.on('connection', (ws) => {
  let authed = !APP_PASSWORD;
  let conn = null;
  let stream = null;
  let authTimer = null;

  const cleanup = () => {
    if (authTimer) clearTimeout(authTimer);
    if (stream) {
      try {
        stream.end();
      } catch {
        /* ignore */
      }
    }
    if (conn) {
      try {
        conn.end();
      } catch {
        /* ignore */
      }
    }
  };

  const startSsh = () => {
    if (!SSH_HOST || !SSH_USER || !SSH_PASSWORD) {
      send(ws, 'error', 'Server is missing SSH_HOST/SSH_USER/SSH_PASSWORD configuration.');
      return ws.close();
    }

    conn = new Client();

    conn.on('ready', () => {
      conn.shell({ term: 'xterm-256color', cols: 80, rows: 24 }, (err, str) => {
        if (err) {
          send(ws, 'error', err.message);
          return ws.close();
        }
        // Only announce "connected" once the shell stream itself is ready
        // to accept writes -- otherwise keystrokes typed in that gap would
        // silently hit `stream === null` below and be dropped forever.
        stream = str;
        send(ws, 'status', `connected to ${SSH_USER}@${SSH_HOST}`);
        stream.on('data', (chunk) => send(ws, 'data', chunk.toString('utf8')));
        stream.stderr.on('data', (chunk) => send(ws, 'data', chunk.toString('utf8')));
        stream.on('close', () => {
          send(ws, 'status', 'session closed');
          cleanup();
          ws.close();
        });
      });
    });

    conn.on('error', (err) => {
      send(ws, 'error', `SSH error: ${err.message}`);
      ws.close();
    });

    conn.on('end', () => ws.close());

    // Connect the TCP socket ourselves so we can disable Nagle's algorithm
    // before handing it to ssh2 -- otherwise single-keystroke SSH packets
    // can get buffered for tens of ms on this leg too.
    const sock = net.connect({ host: SSH_HOST, port: SSH_PORT });
    sock.setNoDelay(true);
    sock.once('error', (err) => send(ws, 'error', `TCP error: ${err.message}`));

    conn.connect({
      sock,
      username: SSH_USER,
      password: SSH_PASSWORD,
      readyTimeout: 20000,
      keepaliveInterval: 10000,
      algorithms: {
        serverHostKey: [
          'ssh-ed25519',
          'ecdsa-sha2-nistp256',
          'rsa-sha2-512',
          'rsa-sha2-256',
          'ssh-rsa',
        ],
      },
    });
  };

  if (authed) {
    startSsh();
  } else {
    send(ws, 'status', 'auth-required');
    authTimer = setTimeout(() => {
      if (!authed) {
        send(ws, 'error', 'Authentication timed out.');
        ws.close();
      }
    }, 30000);
  }

  ws.on('message', (raw) => {
    let msg;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }

    if (!authed) {
      if (msg.type === 'auth') {
        if (msg.data === APP_PASSWORD) {
          authed = true;
          if (authTimer) clearTimeout(authTimer);
          send(ws, 'status', 'auth-ok');
          startSsh();
        } else {
          send(ws, 'error', 'Incorrect app password.');
          ws.close();
        }
      }
      return;
    }

    if (msg.type === 'data' && stream) {
      stream.write(msg.data);
    } else if (msg.type === 'resize' && stream) {
      const cols = Math.max(1, parseInt(msg.cols, 10) || 80);
      const rows = Math.max(1, parseInt(msg.rows, 10) || 24);
      stream.setWindow(rows, cols, 0, 0);
    }
  });

  ws.on('close', cleanup);
  ws.on('error', cleanup);
});

server.listen(PORT, HOST, () => {
  console.log(`[ssh-terminal] listening on http://${HOST}:${PORT}`);
  console.log(
    `[ssh-terminal] bridging browser terminals to ${SSH_USER || '<unset>'}@${SSH_HOST || '<unset>'}:${SSH_PORT}`
  );
  if (!APP_PASSWORD) {
    console.warn(
      '[ssh-terminal] APP_PASSWORD is not set: anyone who can reach this port can open a shell on the target host.'
    );
  }
});
