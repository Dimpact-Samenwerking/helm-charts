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
-- Environment (the chart exposes these to nginx workers via
-- nginx_config.main_configuration_snippet and sets them on the gateway
-- container; see podiumd.frankgateway.config):
--
--   OPENBAO_TOKEN      scoped reader token; required
--   OPENBAO_ADDR       default http://podiumd-openbao-active:8200
--   OPENBAO_MOUNT      default secret
--   OPENBAO_KV         kv engine version, "1" or "2"; default 2
--   OPENBAO_FAIL_MODE  "closed" (default) or "open"
--
-- The kv version matters because the read path and the response shape differ:
-- v1 is  <mount>/<path>       -> body.data
-- v2 is  <mount>/data/<path>  -> body.data.data
-- The chart provisions kv-v2 (openbao.configuration.kvPath, default "secret"),
-- so v2 is the default here; v1 remains supported because the jim00 rig was
-- built against a hand-made kv-v1 "apisix" mount and has not been migrated yet.
--
-- FAIL CLOSED by default. The earlier version failed open: on any error the
-- header was simply not set and the upstream rejected the call itself. That
-- turns "OpenBao is unreachable" into an upstream 401 — indistinguishable from
-- a wrong or expired key, and one of the faults IN-2596 §4 names as invisible
-- from outside. Now the gateway answers 503 itself, with a log line saying
-- which path failed, so the cause is in the first place anyone looks.
--
-- OPENBAO_FAIL_MODE=open restores the old behaviour for a deployment that would
-- rather serve a doomed request than none at all. It is not the default because
-- a silent 401 costs more to diagnose than a loud 503.
--
-- Caching: per-worker lrucache, 300s TTL. Rotation in OpenBao is picked up
-- within the TTL, or immediately after a frankgateway pod restart. Failures are
-- NOT cached: a transient outage would otherwise persist for the full TTL after
-- OpenBao came back.

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

-- Returns the secret table, or nil plus a short reason. The reason is for the
-- log only: it never reaches the client, and it never contains secret material
-- or an OpenBao response body (an error body can echo the requested path).
local function fetch(path)
  local token = os.getenv("OPENBAO_TOKEN")
  if not token or token == "" then
    return nil, "OPENBAO_TOKEN is not set in the nginx environment"
  end

  local httpc = http.new()
  local res, err = httpc:request_uri(secret_url(path), {
    headers = { ["X-Vault-Token"] = token },
  })
  if not res then
    return nil, "request failed: " .. tostring(err)
  end
  if res.status ~= 200 then
    return nil, "status " .. res.status
  end

  local body = core.json.decode(res.body)
  if not body or not body.data then
    return nil, "malformed response"
  end

  local data
  if env("OPENBAO_KV", DEFAULT_KV) == "1" then
    data = body.data
  else
    data = body.data.data
  end
  if not data then
    return nil, "no data at path"
  end
  return data
end

-- lrucache stores only successes: the creation function returns nil on failure,
-- so nothing is cached and the next request retries instead of serving a cached
-- failure for the rest of the TTL. The reason travels out through an upvalue
-- rather than a second return value, because lrucache keeps only the first —
-- and a second fetch just to recover the error message would double the load on
-- an OpenBao that is already struggling.
local function fetch_cached(path)
  local last_err
  local secret = cache(path, nil, function(p)
    local v, e = fetch(p)
    last_err = e
    return v
  end, path)
  if secret then
    return secret
  end
  return nil, last_err or "unavailable"
end

return function(opts)
  local path   = assert(opts and opts.path, "openbao-secret-header: path is required")
  local field  = assert(opts and opts.field, "openbao-secret-header: field is required")
  local header = assert(opts and opts.header, "openbao-secret-header: header is required")

  return function(_, ctx)
    local secret, err = fetch_cached(path)

    if secret and secret[field] then
      core.request.set_header(ctx, header, secret[field])
      return
    end

    if not err then
      err = "field " .. field .. " not present"
    end
    core.log.error("openbao: cannot set header ", header, " from ", path, ": ", err)

    if env("OPENBAO_FAIL_MODE", "closed") == "open" then
      -- Send the request on without the header; the upstream will reject it.
      return
    end

    return core.response.exit(503, {
      error = "secret_unavailable",
      message = "gateway could not read the upstream credential from OpenBao",
    })
  end
end
