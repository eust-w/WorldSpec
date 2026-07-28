import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL(".", import.meta.url)));
const bundleRoot = resolve(process.env.BUNDLE_DIR || "/tmp/worldspec-threejs-bundle");
const port = Number(process.env.PORT || 4173);
const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json",
  ".glb": "model/gltf-binary",
};

function within(candidate, base) {
  return candidate === base || candidate.startsWith(`${base}${sep}`);
}

createServer((request, response) => {
  const url = new URL(request.url, `http://${request.headers.host}`);
  const fromBundle = url.pathname.startsWith("/bundle/");
  const base = fromBundle ? bundleRoot : root;
  const relative = fromBundle ? url.pathname.slice("/bundle/".length) : url.pathname.slice(1);
  let target = resolve(base, relative || "index.html");
  if (!within(target, base)) {
    response.writeHead(400).end("invalid path");
    return;
  }
  if (existsSync(target) && statSync(target).isDirectory()) target = resolve(target, "index.html");
  if (!existsSync(target)) {
    response.writeHead(404).end("not found");
    return;
  }
  response.writeHead(200, {
    "content-type": types[extname(target)] || "application/octet-stream",
    "cache-control": "no-store",
  });
  createReadStream(target).pipe(response);
}).listen(port, "127.0.0.1", () => {
  console.log(`WorldSpec Three.js preview: http://127.0.0.1:${port}`);
});
