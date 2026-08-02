const PUBLIC_PREFIXES = ["covers/", "previews/", "workflows/", "exports/"];
const MAX_EXPORT_BYTES = 512 * 1024 * 1024;

const CORS_HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, HEAD, PUT, DELETE, OPTIONS",
  "access-control-allow-headers": "Range, If-Match, If-None-Match, If-Modified-Since",
  "access-control-expose-headers":
    "Accept-Ranges, Content-Length, Content-Range, Content-Type, ETag, Last-Modified",
};

function responseHeaders(object) {
  const headers = new Headers(CORS_HEADERS);
  object.writeHttpMetadata(headers);
  headers.set("etag", object.httpEtag);
  headers.set("accept-ranges", "bytes");

  if (!headers.has("cache-control")) {
    headers.set("cache-control", "public, max-age=3600");
  }

  if (object.uploaded && !headers.has("last-modified")) {
    headers.set("last-modified", object.uploaded.toUTCString());
  }

  return headers;
}

function errorResponse(status, message) {
  return new Response(message, {
    status,
    headers: {
      ...CORS_HEADERS,
      "cache-control": "no-store",
      "content-type": "text/plain; charset=utf-8",
    },
  });
}

function publicKey(request) {
  const url = new URL(request.url);
  const encodedKey = url.pathname.replace(/^\/+/, "");

  if (!encodedKey) return null;

  let key;
  try {
    key = decodeURIComponent(encodedKey);
  } catch {
    return null;
  }

  if (
    key.includes("\0") ||
    key.split("/").some((segment) => segment === "." || segment === "..") ||
    !PUBLIC_PREFIXES.some((prefix) => key.startsWith(prefix))
  ) {
    return null;
  }

  return key;
}

function authorizedUpload(request, env) {
  const secret = String(env.EXPORT_UPLOAD_TOKEN || "");
  return secret && request.headers.get("authorization") === `Bearer ${secret}`;
}

async function uploadExport(request, env, key) {
  if (!key.startsWith("exports/") || !key.toLowerCase().endsWith(".mp4")) {
    return errorResponse(404, "Not found");
  }
  if (!authorizedUpload(request, env)) {
    return errorResponse(401, "Unauthorized");
  }
  const contentLength = Number(request.headers.get("content-length") || 0);
  if (!request.body || contentLength <= 0 || contentLength > MAX_EXPORT_BYTES) {
    return errorResponse(413, "Invalid export size");
  }
  if ((request.headers.get("content-type") || "").split(";", 1)[0] !== "video/mp4") {
    return errorResponse(415, "Expected video/mp4");
  }

  const object = await env.PUBLIC_BUCKET.put(key, request.body, {
    httpMetadata: {
      contentType: "video/mp4",
      contentDisposition: "inline",
      cacheControl: "public, max-age=31536000, immutable",
    },
  });
  return Response.json(
    { ok: true, key, etag: object.httpEtag },
    { status: 201, headers: { "cache-control": "no-store" } },
  );
}

async function deleteExport(request, env, key) {
  if (!key.startsWith("exports/") || !key.toLowerCase().endsWith(".mp4")) {
    return errorResponse(404, "Not found");
  }
  if (!authorizedUpload(request, env)) {
    return errorResponse(401, "Unauthorized");
  }
  await env.PUBLIC_BUCKET.delete(key);
  return new Response(null, { status: 204, headers: { "cache-control": "no-store" } });
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    const key = publicKey(request);
    if (!key) return errorResponse(404, "Not found");

    if (request.method === "PUT") {
      return uploadExport(request, env, key);
    }

    if (request.method === "DELETE") {
      return deleteExport(request, env, key);
    }

    if (request.method !== "GET" && request.method !== "HEAD") {
      return errorResponse(405, "Method not allowed");
    }

    if (request.method === "HEAD") {
      const object = await env.PUBLIC_BUCKET.head(key);
      if (!object) return errorResponse(404, "Not found");

      const headers = responseHeaders(object);
      headers.set("content-length", String(object.size));
      return new Response(null, { status: 200, headers });
    }

    const object = await env.PUBLIC_BUCKET.get(key, {
      onlyIf: request.headers,
      range: request.headers,
    });

    if (!object) return errorResponse(404, "Not found");

    const headers = responseHeaders(object);
    if (!("body" in object)) {
      const status = request.headers.has("if-none-match") ? 304 : 412;
      return new Response(null, { status, headers });
    }

    let status = 200;
    if (request.headers.has("range") && object.range) {
      const offset = object.range.offset ?? 0;
      const length = object.range.length ?? object.size;
      headers.set("content-range", `bytes ${offset}-${offset + length - 1}/${object.size}`);
      headers.set("content-length", String(length));
      status = 206;
    } else {
      headers.set("content-length", String(object.size));
    }

    return new Response(object.body, { status, headers });
  },
};
