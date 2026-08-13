const PUBLIC_PREFIXES = ["covers/", "previews/", "workflows/", "exports/"];
const MAX_EXPORT_BYTES = 512 * 1024 * 1024;
const MAX_MULTIPART_PART_BYTES = 64 * 1024 * 1024;

const CORS_HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, HEAD, POST, PUT, DELETE, OPTIONS",
  "access-control-allow-headers":
    "Authorization, Content-Type, Content-Length, Range, If-Match, If-None-Match, If-Modified-Since",
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

function bearerToken(request) {
  const header = String(request.headers.get("authorization") || "");
  return header.startsWith("Bearer ") ? header.slice(7) : "";
}

function authorizedServer(request, env) {
  const secret = String(env.EXPORT_UPLOAD_TOKEN || "");
  return Boolean(secret && bearerToken(request) === secret);
}

function decodeBase64Url(value) {
  const normalized = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

async function authorizedUpload(request, env, key) {
  if (authorizedServer(request, env)) return { kind: "server" };
  const secret = String(env.EXPORT_UPLOAD_TOKEN || "");
  const [payloadSegment, signatureSegment, extra] = bearerToken(request).split(".");
  if (!secret || !payloadSegment || !signatureSegment || extra) return null;
  try {
    const cryptoKey = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["verify"],
    );
    const valid = await crypto.subtle.verify(
      "HMAC",
      cryptoKey,
      decodeBase64Url(signatureSegment),
      new TextEncoder().encode(payloadSegment),
    );
    if (!valid) return null;
    const payload = JSON.parse(new TextDecoder().decode(decodeBase64Url(payloadSegment)));
    const now = Math.floor(Date.now() / 1000);
    if (
      payload?.v !== 1 || payload?.op !== "upload" || payload?.key !== key ||
      !Number.isInteger(payload?.exp) || payload.exp < now ||
      !Number.isInteger(payload?.iat) || payload.iat > now + 60 ||
      !Number.isInteger(payload?.size_bytes) || payload.size_bytes < 12 ||
      payload.size_bytes > MAX_EXPORT_BYTES ||
      !Number.isInteger(payload?.part_bytes) || payload.part_bytes < 5 * 1024 * 1024 ||
      payload.part_bytes > MAX_MULTIPART_PART_BYTES ||
      !Number.isInteger(payload?.total_parts) || payload.total_parts < 1 ||
      payload.total_parts !== Math.ceil(payload.size_bytes / payload.part_bytes)
    ) return null;
    return { kind: "scoped", payload };
  } catch {
    return null;
  }
}

async function uploadExport(request, env, key) {
  if (!key.startsWith("exports/") || !key.toLowerCase().endsWith(".mp4")) {
    return errorResponse(404, "Not found");
  }
  const authorization = await authorizedUpload(request, env, key);
  if (!authorization) return errorResponse(401, "Unauthorized");
  const contentLength = Number(request.headers.get("content-length") || 0);
  const scopedExpectedLength = authorization.kind === "scoped"
    ? (partNumber === authorization.payload.total_parts
        ? authorization.payload.size_bytes - authorization.payload.part_bytes * (partNumber - 1)
        : authorization.payload.part_bytes)
    : null;
  if (
    !request.body || contentLength <= 0 || contentLength > MAX_EXPORT_BYTES ||
    (authorization.kind === "scoped" && contentLength !== authorization.payload.size_bytes)
  ) {
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

function multipartUpload(env, key, uploadId) {
  if (!uploadId) return null;
  return env.PUBLIC_BUCKET.resumeMultipartUpload(key, uploadId);
}

async function createMultipartExport(request, env, key) {
  if (!key.startsWith("exports/") || !key.toLowerCase().endsWith(".mp4")) {
    return errorResponse(404, "Not found");
  }
  if (!(await authorizedUpload(request, env, key))) {
    return errorResponse(401, "Unauthorized");
  }
  const upload = await env.PUBLIC_BUCKET.createMultipartUpload(key, {
    httpMetadata: {
      contentType: "video/mp4",
      contentDisposition: "inline",
      cacheControl: "public, max-age=31536000, immutable",
    },
  });
  return Response.json(
    { key: upload.key, uploadId: upload.uploadId },
    { status: 201, headers: { "cache-control": "no-store" } },
  );
}

async function uploadMultipartExportPart(request, env, key, url) {
  const authorization = await authorizedUpload(request, env, key);
  if (!authorization) {
    return errorResponse(401, "Unauthorized");
  }
  const uploadId = url.searchParams.get("uploadId");
  const partNumber = Number(url.searchParams.get("partNumber"));
  const contentLength = Number(request.headers.get("content-length") || 0);
  if (
    !request.body ||
    !uploadId ||
    !Number.isInteger(partNumber) ||
    partNumber < 1 ||
    partNumber > 10000 ||
    contentLength <= 0 ||
    contentLength > MAX_MULTIPART_PART_BYTES ||
    (authorization.kind === "scoped" && (
      partNumber > authorization.payload.total_parts || contentLength !== scopedExpectedLength
    ))
  ) {
    return errorResponse(400, "Invalid multipart upload part");
  }
  try {
    const part = await multipartUpload(env, key, uploadId).uploadPart(partNumber, request.body);
    return Response.json(part, { status: 200, headers: { "cache-control": "no-store" } });
  } catch (error) {
    return errorResponse(400, `Multipart part failed: ${String(error)}`);
  }
}

async function completeMultipartExport(request, env, key, url) {
  const authorization = await authorizedUpload(request, env, key);
  if (!authorization) {
    return errorResponse(401, "Unauthorized");
  }
  const uploadId = url.searchParams.get("uploadId");
  if (!uploadId) return errorResponse(400, "Missing uploadId");
  let payload;
  try {
    payload = await request.json();
  } catch {
    return errorResponse(400, "Invalid multipart completion payload");
  }
  const parts = Array.isArray(payload?.parts) ? payload.parts : [];
  if (
    parts.length < 1 ||
    parts.length > 10000 ||
    parts.some((part) => !Number.isInteger(part?.partNumber) || !String(part?.etag || "")) ||
    (authorization.kind === "scoped" && (
      parts.length !== authorization.payload.total_parts ||
      parts.some((part, index) => part.partNumber !== index + 1)
    ))
  ) {
    return errorResponse(400, "Invalid multipart completion parts");
  }
  try {
    const object = await multipartUpload(env, key, uploadId).complete(parts);
    return Response.json(
      { ok: true, key, etag: object.httpEtag },
      { status: 201, headers: { "cache-control": "no-store" } },
    );
  } catch (error) {
    return errorResponse(400, `Multipart completion failed: ${String(error)}`);
  }
}

async function abortMultipartExport(request, env, key, url) {
  if (!(await authorizedUpload(request, env, key))) {
    return errorResponse(401, "Unauthorized");
  }
  const uploadId = url.searchParams.get("uploadId");
  if (!uploadId) return errorResponse(400, "Missing uploadId");
  try {
    await multipartUpload(env, key, uploadId).abort();
  } catch (error) {
    return errorResponse(400, `Multipart abort failed: ${String(error)}`);
  }
  return new Response(null, { status: 204, headers: { "cache-control": "no-store" } });
}

async function deleteExport(request, env, key) {
  if (!key.startsWith("exports/") || !key.toLowerCase().endsWith(".mp4")) {
    return errorResponse(404, "Not found");
  }
  if (!authorizedServer(request, env)) {
    return errorResponse(401, "Unauthorized");
  }
  await env.PUBLIC_BUCKET.delete(key);
  return new Response(null, { status: 204, headers: { "cache-control": "no-store" } });
}

async function listExports(request, env, url) {
  if (!authorizedServer(request, env)) {
    return errorResponse(401, "Unauthorized");
  }
  const requestedLimit = Number(url.searchParams.get("limit") || 500);
  const limit = Number.isInteger(requestedLimit)
    ? Math.max(1, Math.min(1000, requestedLimit))
    : 500;
  const cursor = String(url.searchParams.get("cursor") || "");
  const listed = await env.PUBLIC_BUCKET.list({
    prefix: "exports/",
    limit,
    ...(cursor ? { cursor } : {}),
  });
  return Response.json(
    {
      objects: listed.objects.map((object) => ({
        key: object.key,
        size: object.size,
        etag: object.httpEtag,
        uploaded: object.uploaded?.toISOString() || null,
      })),
      truncated: listed.truncated,
      cursor: listed.truncated ? listed.cursor : null,
    },
    { headers: { ...CORS_HEADERS, "cache-control": "no-store" } },
  );
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    const key = publicKey(request);
    if (!key) return errorResponse(404, "Not found");

    const url = new URL(request.url);
    const action = url.searchParams.get("action");

    if (request.method === "GET" && action === "list") {
      return listExports(request, env, url);
    }

    if (request.method === "POST" && action === "mpu-create") {
      return createMultipartExport(request, env, key);
    }
    if (request.method === "PUT" && action === "mpu-uploadpart") {
      return uploadMultipartExportPart(request, env, key, url);
    }
    if (request.method === "POST" && action === "mpu-complete") {
      return completeMultipartExport(request, env, key, url);
    }
    if (request.method === "DELETE" && action === "mpu-abort") {
      return abortMultipartExport(request, env, key, url);
    }

    if (request.method === "PUT" && !action) {
      return uploadExport(request, env, key);
    }

    if (request.method === "DELETE" && !action) {
      return deleteExport(request, env, key);
    }

    if (request.method !== "GET" && request.method !== "HEAD") {
      return errorResponse(405, "Method not allowed");
    }

    // Exports are immutable. Cache the exact full/range response at the
    // nearest edge so repeat playback does not re-read R2 on every request.
    // Only Range participates in the key; conditional headers are per-client.
    const streamFull = url.searchParams.get("stream") === "full";
    const cacheHeaders = new Headers();
    if (!streamFull && request.headers.has("range")) {
      cacheHeaders.set("range", request.headers.get("range"));
    }
    const cacheKey = new Request(request.url, {
      method: "GET",
      headers: cacheHeaders,
    });
    if (request.method === "GET") {
      const cached = await caches.default.match(cacheKey);
      if (cached) return cached;
    }

    if (request.method === "HEAD") {
      const object = await env.PUBLIC_BUCKET.head(key);
      if (!object) return errorResponse(404, "Not found");

      const headers = responseHeaders(object);
      headers.set("content-length", String(object.size));
      return new Response(null, { status: 200, headers });
    }

    const object = await env.PUBLIC_BUCKET.get(
      key,
      streamFull
        ? { onlyIf: request.headers }
        : { onlyIf: request.headers, range: request.headers },
    );

    if (!object) return errorResponse(404, "Not found");

    const headers = responseHeaders(object);
    if (!("body" in object)) {
      const status = request.headers.has("if-none-match") ? 304 : 412;
      return new Response(null, { status, headers });
    }

    let status = 200;
    if (!streamFull && request.headers.has("range") && object.range) {
      const offset = object.range.offset ?? 0;
      const length = object.range.length ?? object.size;
      headers.set("content-range", `bytes ${offset}-${offset + length - 1}/${object.size}`);
      headers.set("content-length", String(length));
      status = 206;
    } else {
      headers.set("content-length", String(object.size));
    }

    // Preview URLs use stream=full: R2 range reads are slow on some edges,
    // while one immutable 200 response is cached and plays continuously.
    // Download URLs keep normal Range behavior for seeking/resume.
    headers.set("x-media-stream", streamFull ? "full" : "range");
    const response = new Response(object.body, { status, headers });
    if (request.method === "GET" && response.ok) {
      ctx.waitUntil(caches.default.put(cacheKey, response.clone()));
    }
    return response;
  },
};
