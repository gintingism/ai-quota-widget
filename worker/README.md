# Cloudflare quota relay

Create a KV namespace, replace the namespace ID in `wrangler.toml`, and set the
shared relay token as a secret (`wrangler secret put AUTH_TOKEN`). Deploy with
`wrangler deploy`. The Worker never receives provider credentials: it accepts
only the normalized JSON snapshot from the desktop app.

`POST /api/quota/sync` and `GET /api/quota/latest` require the `X-Auth-Token`
header. CORS is enabled for future clients; use a specific origin before
exposing the relay publicly.
