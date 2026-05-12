const http = require('http');
const fs = require('fs');
const path = require('path');
const port = process.env.PORT || 8080;
// Serve from project root so /demo/*, /frontend/*, etc. all resolve correctly
const dir = path.resolve(__dirname, '..');
const mime = { '.html':'text/html','.css':'text/css','.js':'application/javascript','.json':'application/json','.png':'image/png','.jpg':'image/jpeg','.svg':'image/svg+xml' };
http.createServer((req, res) => {
  const urlPath = req.url.split('?')[0];
  // Default root → demo/student.html
  const rel = urlPath === '/' ? 'demo/student.html' : urlPath.replace(/^\//, '');
  if (rel.includes('..')) {
    res.writeHead(403);
    res.end('Forbidden');
    return;
  }
  const p = path.join(dir, rel);
  if (!fs.existsSync(p)) { res.writeHead(404); res.end('Not found'); return; }
  const ext = path.extname(p);
  res.writeHead(200, { 'Content-Type': mime[ext] || 'text/plain' });
  fs.createReadStream(p).pipe(res);
}).listen(port, () => console.log(`Static server on http://localhost:${port}`));
