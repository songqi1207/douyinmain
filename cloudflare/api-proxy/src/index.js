const ORIGIN = "https://origin-tunnel.songqi.online";

export default {
  async fetch(request) {
    const publicUrl = new URL(request.url);
    const originUrl = new URL(`${publicUrl.pathname}${publicUrl.search}`, ORIGIN);
    const headers = new Headers(request.headers);
    const clientIp = request.headers.get("CF-Connecting-IP");

    headers.delete("host");
    headers.set("X-Forwarded-Host", publicUrl.host);
    headers.set("X-Forwarded-Proto", "https");
    if (clientIp) {
      headers.set("X-Real-IP", clientIp);
    }

    const originRequest = new Request(originUrl, request);
    const response = await fetch(
      new Request(originRequest, {
        headers,
        redirect: "manual",
      }),
    );

    return response;
  },
};
