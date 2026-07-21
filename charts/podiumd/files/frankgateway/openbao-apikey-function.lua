-- openbao-apikey-function.lua
--
-- APISIX serverless-pre-function (phase: rewrite) that fetches an external-API
-- key from OpenBao at request time and sets it as an upstream header. Replaces
-- the os.getenv("BAG_API_KEY"/"KVK_API_KEY") injection so the key lives only in
-- OpenBao (no API keys in k8s env/secrets — only a scoped reader token).
--
-- Proven working end-to-end 2026-06-24: KVK test key in OpenBao -> this fn ->
-- https://api.kvk.nl/test/api/v2/zoeken -> HTTP 200 with live results.
--
-- Per-route, change two things:
--   * the OpenBao field read (s.bag_api_key vs s.kvk_api_key)
--   * the header name set (BAG: "X-Api-Key", KVK: "apikey")
--
-- The reader token is read from env OPENBAO_TOKEN (expose it in apisix-config
-- nginx_config.main_configuration_snippet: `env OPENBAO_TOKEN;`, fed from the
-- Key Vault secret frankgateway-apisix-vault-token-<env>). The OpenBao address
-- and kv path are fixed for the in-cluster active service + kv-v1 mount.
--
-- Caching: per-worker lrucache, 300s TTL. Key rotation in OpenBao is picked up
-- within the TTL (or immediately after a frankgateway pod restart).

local core  = require("apisix.core")
local http  = require("resty.http")
local cache = core.lrucache.new({ ttl = 300, count = 4 })

local OBAO_URL = "http://podiumd-openbao-active:8200/v1/apisix/frankgateway"

local function fetch()
  local httpc = http.new()
  local res, err = httpc:request_uri(OBAO_URL, {
    headers = { ["X-Vault-Token"] = os.getenv("OPENBAO_TOKEN") },
  })
  if not res then
    core.log.error("openbao fetch failed: ", tostring(err))
    return {}
  end
  if res.status ~= 200 then
    core.log.error("openbao fetch status ", res.status)
    return {}
  end
  local body = core.json.decode(res.body)
  return (body and body.data) or {}
end

-- BAG variant (header X-Api-Key, field bag_api_key):
return function(_, ctx)
  local s = cache("fg-secrets", nil, fetch)
  if s and s.bag_api_key then
    core.request.set_header(ctx, "X-Api-Key", s.bag_api_key)
  end
end
