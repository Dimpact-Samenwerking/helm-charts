-- openbao-secret-header.lua
--
-- APISIX serverless-pre-function (phase: rewrite) that fetches a secret from
-- OpenBao at request time and sets it as an upstream header, so the value lives
-- only in OpenBao and the gateway holds nothing but a scoped reader token.
--
-- Generalises the earlier openbao-apikey-function.lua, which hard-coded the BAG
-- field and header and needed copy-editing per route. Everything that varied is
-- now configuration:
--
--   local set_secret_header = require("openbao-secret-header")
--   return set_secret_header({
--     path   = "frankgateway",   -- secret path within the mount
--     field  = "bag_api_key",    -- key inside that secret
--     header = "X-Api-Key",      -- header to set upstream
--   })
--
-- The three call sites that exist today:
--   BAG           field bag_api_key,      header X-Api-Key
--   KVK           field kvk_api_key,      header apikey
--   ESB consumer  field esb_consumer_key, header apikey        (IN-2543)
--
-- Environment (expose the names in apisix-config
-- nginx_config.main_configuration_snippet, e.g. `env OPENBAO_TOKEN;`):
--
--   OPENBAO_TOKEN    scoped reader token; required
--   OPENBAO_ADDR     default http://podiumd-openbao-active:8200
--   OPENBAO_MOUNT    default secret
--   OPENBAO_KV       kv engine version, "1" or "2"; default 2
--
-- The kv version matters because the read path and the response shape differ:
-- v1 is  <mount>/<path>       -> body.data
-- v2 is  <mount>/data/<path>  -> body.data.data
-- The chart provisions kv-v2 (openbao.configuration.kvPath, default "secret"),
-- so v2 is the default here; v1 remains supported because the jim00 rig was
-- built against a hand-made kv-v1 "apisix" mount and has not been migrated yet.
--
-- Fail-open by design: on any error the header is simply not set, and the
-- upstream rejects the call itself. A gateway that 500s on an OpenBao blip
-- would turn a secret-store hiccup into an outage.
--
-- Caching: per-worker lrucache, 300s TTL. Rotation in OpenBao is picked up
-- within the TTL, or immediately after a frankgateway pod restart.

local core  = require("apisix.core")
local http  = require("resty.http")
local cache = core.lrucache.new({ ttl = 300, count = 8 })

local DEFAULT_ADDR  = "http://podiumd-openbao-active:8200"
local DEFAULT_MOUNT = "secret"
local DEFAULT_KV    = "2"

local function env(name, fallback)
  local v = os.getenv(name)
  if v == nil or v == "" then
    return fallback
  end
  return v
end

-- Builds the read URL for the configured kv engine version.
local function secret_url(path)
  local addr    = env("OPENBAO_ADDR", DEFAULT_ADDR)
  local mount   = env("OPENBAO_MOUNT", DEFAULT_MOUNT)
  local version = env("OPENBAO_KV", DEFAULT_KV)

  if version == "1" then
    return string.format("%s/v1/%s/%s", addr, mount, path)
  end
  return string.format("%s/v1/%s/data/%s", addr, mount, path)
end

local function fetch(path)
  local token = os.getenv("OPENBAO_TOKEN")
  if not token or token == "" then
    core.log.error("openbao: OPENBAO_TOKEN is not set in the nginx environment")
    return {}
  end

  local httpc = http.new()
  local res, err = httpc:request_uri(secret_url(path), {
    headers = { ["X-Vault-Token"] = token },
  })
  if not res then
    core.log.error("openbao fetch failed: ", tostring(err))
    return {}
  end
  if res.status ~= 200 then
    -- Deliberately does not log the body: an OpenBao error response can echo
    -- the requested path, and this goes to the access log.
    core.log.error("openbao fetch status ", res.status, " for path ", path)
    return {}
  end

  local body = core.json.decode(res.body)
  if not body or not body.data then
    return {}
  end
  if env("OPENBAO_KV", DEFAULT_KV) == "1" then
    return body.data
  end
  return body.data.data or {}
end

return function(opts)
  local path   = assert(opts and opts.path, "openbao-secret-header: path is required")
  local field  = assert(opts and opts.field, "openbao-secret-header: field is required")
  local header = assert(opts and opts.header, "openbao-secret-header: header is required")

  -- Cache key is the secret path: one fetch serves every field in that secret.
  return function(_, ctx)
    local secret = cache(path, nil, fetch, path)
    if secret and secret[field] then
      core.request.set_header(ctx, header, secret[field])
    else
      core.log.warn("openbao: field ", field, " not present at ", path)
    end
  end
end
