# API edge proxy

Cloudflare terminates HTTPS for `api.songqi.online` and proxies requests through
`origin-tunnel.songqi.online` and the named Cloudflare Tunnel to the Tencent
Cloud origin at `101.35.148.70`. The production entry is
`https://api.songqi.online/business/`.

Required DNS record:

```text
api.songqi.online            A      101.35.148.70                                Proxied
origin-tunnel.songqi.online  CNAME  f09de1cd-fe3c-4e8e-9b58-f0a7408f8be5.cfargotunnel.com  Proxied
```

Deploy from this directory with a Cloudflare API token that can edit Workers:

```bash
npx wrangler deploy
```
