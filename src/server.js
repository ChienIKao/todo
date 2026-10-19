// Local web server for the desktop board. Binds to 127.0.0.1 only.
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as store from './store.js';

const WEB_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'web');
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.webmanifest': 'application/manifest+json',
};

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (c) => (data += c));
    req.on('end', () => {
      try {
        resolve(data ? JSON.parse(data) : {});
      } catch (err) {
        reject(err);
      }
    });
    req.on('error', reject);
  });
}

function json(res, status, body) {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}

export function createServer() {
  const clients = new Set();

  // Agents and the CLI write the file from other processes; push a refresh to open boards.
  fs.mkdirSync(store.dataDir(), { recursive: true });
  let timer;
  const watcher = fs.watch(store.dataDir(), (_event, file) => {
    if (file !== 'todos.json') return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      for (const res of clients) res.write('data: changed\n\n');
    }, 100);
  });

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const parts = url.pathname.split('/').filter(Boolean);

    try {
      // Reject cross-site requests and DNS rebinding so random web pages can't read or edit todos.
      const host = (req.headers.host || '').replace(/:\d+$/, '');
      if (!['localhost', '127.0.0.1'].includes(host)) return json(res, 403, { error: 'forbidden' });
      const origin = req.headers.origin;
      if (origin && new URL(origin).host !== req.headers.host) return json(res, 403, { error: 'forbidden' });

      if (parts[0] === 'api') {
        if (parts[1] === 'events') {
          res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache', connection: 'keep-alive' });
          res.write('retry: 2000\n\n');
          clients.add(res);
          req.on('close', () => clients.delete(res));
          return;
        }
        if (parts[1] !== 'todos') return json(res, 404, { error: 'not found' });
        const id = parts[2];
        if (!id && req.method === 'GET') return json(res, 200, store.list({ status: 'all' }));
        if (!id && req.method === 'POST') return json(res, 201, store.add(await readBody(req)));
        if (id && parts[3] === 'notes' && req.method === 'POST') {
          const body = await readBody(req);
          return json(res, 200, store.addNote(id, body.text, 'me'));
        }
        if (id && !parts[3] && req.method === 'PATCH') return json(res, 200, store.update(id, await readBody(req)));
        if (id && !parts[3] && req.method === 'DELETE') return json(res, 200, store.remove(id));
        return json(res, 404, { error: 'not found' });
      }

      const file = path.join(WEB_DIR, path.normalize(url.pathname === '/' ? '/index.html' : url.pathname));
      if (!file.startsWith(WEB_DIR) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
        res.writeHead(404);
        return res.end('not found');
      }
      res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' });
      fs.createReadStream(file).pipe(res);
    } catch (err) {
      json(res, 400, { error: err.message });
    }
  });

  server.on('close', () => {
    watcher.close();
    for (const res of clients) res.end();
  });
  return server;
}

export function runServer(port = Number(process.env.AGENT_TODO_PORT) || 4567) {
  const server = createServer();
  server.listen(port, '127.0.0.1', () => {
    console.log(`agent-todo board: http://localhost:${port}`);
    console.log(`data: ${store.dataFile()}`);
  });
  return server;
}
