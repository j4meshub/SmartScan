import {createServer} from "node:http";
import {readFile, stat} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const mimeTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".webmanifest": "application/manifest+json; charset=utf-8",
};

createServer(async (request, response) => {
  try {
    const pathname = decodeURIComponent(new URL(request.url, "http://127.0.0.1").pathname);
    const requested = pathname === "/" ? "/index.html" : pathname;
    const absolute = path.resolve(root, `.${requested}`);
    if (absolute !== root && !absolute.startsWith(`${root}${path.sep}`)) throw new Error("path_outside_root");
    if (!(await stat(absolute)).isFile()) throw new Error("not_a_file");
    response.writeHead(200, {"Content-Type": mimeTypes[path.extname(absolute)] || "application/octet-stream"});
    response.end(await readFile(absolute));
  } catch {
    response.writeHead(404, {"Content-Type": "text/plain; charset=utf-8"});
    response.end("Not found");
  }
}).listen(4173, "127.0.0.1");
