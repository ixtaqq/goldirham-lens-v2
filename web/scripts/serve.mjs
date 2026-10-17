// Serves the static export for end-to-end tests and audits, compressed and cached the way the
// hosting platform serves it. No dependencies, loopback only.
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize, resolve } from "node:path";
import { createGzip } from "node:zlib";

const root = resolve(process.argv[2] ?? "out");
const port = Number(process.argv[3] ?? 4173);
const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
};

createServer((request, response) => {
  const path = decodeURIComponent(new URL(request.url ?? "/", "http://localhost").pathname);
  let file = normalize(join(root, path));
  if (!file.startsWith(root)) {
    response.writeHead(403).end();
    return;
  }
  if (existsSync(file) && statSync(file).isDirectory()) file = join(file, "index.html");
  if (!existsSync(file) && existsSync(`${file}.html`)) file = `${file}.html`;
  if (!existsSync(file)) {
    response.writeHead(404).end("not found");
    return;
  }
  const type = types[extname(file)] ?? "application/octet-stream";
  const headers = { "content-type": type, vary: "accept-encoding" };
  if (path.startsWith("/_next/static/")) headers["cache-control"] = "public, max-age=31536000, immutable";
  const compress = /text|javascript|json|svg/.test(type) && /gzip/.test(request.headers["accept-encoding"] ?? "");
  if (compress) headers["content-encoding"] = "gzip";
  response.writeHead(200, headers);
  const stream = createReadStream(file);
  (compress ? stream.pipe(createGzip()) : stream).pipe(response);
}).listen(port, "127.0.0.1", () => {
  console.log(`serving ${root} on http://127.0.0.1:${port}`);
});
