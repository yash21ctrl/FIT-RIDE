const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname);
const PORT = Number(process.env.PORT || 3100);

const MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon"
};

function safePath(requestUrl) {
    const pathname = decodeURIComponent(new URL(requestUrl, "http://127.0.0.1").pathname);
    const relativePath = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
    const resolved = path.resolve(ROOT, relativePath);
    return resolved.startsWith(`${ROOT}${path.sep}`) ? resolved : null;
}

const server = http.createServer((request, response) => {
    if (!["GET", "HEAD"].includes(request.method)) {
        response.writeHead(405, { "Content-Type": "text/plain; charset=utf-8" });
        response.end("Method not allowed");
        return;
    }

    let filePath;
    try {
        filePath = safePath(request.url);
    } catch {
        filePath = null;
    }
    if (!filePath) {
        response.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
        response.end("Bad request");
        return;
    }

    fs.stat(filePath, (statError, stats) => {
        if (statError || !stats.isFile()) {
            response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
            response.end("Not found");
            return;
        }

        const contentType = MIME_TYPES[path.extname(filePath).toLowerCase()] || "application/octet-stream";
        response.writeHead(200, {
            "Content-Type": contentType,
            "Cache-Control": "no-cache"
        });
        if (request.method === "HEAD") {
            response.end();
            return;
        }
        fs.createReadStream(filePath).pipe(response);
    });
});

server.listen(PORT, "127.0.0.1", () => {
    console.log(`FITRIDE frontend running at http://127.0.0.1:${PORT}`);
    console.log("Backend API runs separately from fitride/backend on port 5001.");
});
