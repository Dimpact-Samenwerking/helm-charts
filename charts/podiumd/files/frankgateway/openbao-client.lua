-- openbao-client.lua
--
-- TEMPORARY — obsolete with the next Frank!Gateway release. This module exists
-- because Frank!Gateway 1.1.0 runs APISIX 3.16, where $secret:// references do
-- not cover this use. The next release resolves them natively; this file is
-- then deleted, not maintained. Do not build on its interface.
--
-- The one place the gateway talks to OpenBao from Lua. Both request-time
-- functions the chart ships are thin wrappers over this:
--
--   openbao-secret-header.lua   API key from OpenBao -> upstream header
--   openbao-consumer-auth.lua   inbound consumer identity from OpenBao
--
-- Environment (declared to nginx workers via nginx_config.main_configuration_
-- snippet and set on the gateway container; see podiumd.frankgateway.config):
--
--   OPENBAO_TOKEN      scoped reader token; required
--   OPENBAO_ADDR       default http://podiumd-openbao-active:8200
--   OPENBAO_MOUNT      default secret
--   OPENBAO_KV         kv engine version, "1" or "2"; default 2
--   OPENBAO_FAIL_MODE  "closed" (default) or "open" — interpreted by callers
--
-- The kv version matters because the read path and the response shape differ:
-- v1 is  <mount>/<path>       -> body.data
-- v2 is  <mount>/data/<path>  -> body.data.data
--
-- Caching: per-worker lrucache, 300 s TTL (successes only), successes only. A rotation in
-- OpenBao is picked up within the TTL, or immediately after a pod restart.
-- Failures are never cached: a transient outage would otherwise persist for
-- the full TTL after OpenBao came back.
--
-- Stale-on-error (opt-in per call, `stale_ttl`): the last value successfully
-- read for a path is remembered per POD, in the `openbao-last-good` shared
-- dict the chart declares (nginx_config.http.custom_lua_shared_dict); when a
-- re-read fails, it is served for up to `stale_ttl` seconds after it was read,
-- and the caller is told it is stale. This bounds the blast radius of an
-- OpenBao outage for callers that would otherwise have to refuse every request
-- (the consumer list on the inway) without keeping a revoked value alive
-- indefinitely. Pod-wide matters: nginx runs one worker per CPU and Lua state
-- is per worker, so a per-worker copy left every cold worker answering 503
-- during an outage (measured on jim00: 50 % of requests). Without the dict
-- (a config that does not declare it) the code falls back to a per-worker
-- table and logs once.

local core = require("apisix.core")
local http = require("resty.http")
local ngx  = ngx

local cache = core.lrucache.new({ ttl = 300, count = 32 })

local SHARED_DICT = "openbao-last-good"
local dict = ngx.shared[SHARED_DICT]
local last_good_local = {}   -- fallback only: path -> { data = table, at = seconds }
if not dict then
  core.log.warn("openbao-client: lua_shared_dict ", SHARED_DICT,
                " is not declared; last-good copies are per worker")
end

-- last-good copy of a path: { data = table, at = seconds } or nil
local function last_good_get(path)
  if not dict then
    return last_good_local[path]
  end
  local raw = dict:get(path)
  local at  = dict:get(path .. "\0at")
  if not raw or not at then
    return nil
  end
  local data = core.json.decode(raw)
  if not data then
    return nil
  end
  return { data = data, at = at }
end

local function last_good_set(path, data)
  if not dict then
    last_good_local[path] = { data = data, at = ngx.now() }
    return
  end
  local raw = core.json.encode(data)
  if raw then
    -- no expiry: stale_ttl is judged against `at` by the reader, so one long
    -- stale_ttl route and one short one can share the same copy
    dict:set(path, raw)
    dict:set(path .. "\0at", ngx.now())
  end
end

local DEFAULT_ADDR  = "http://podiumd-openbao-active:8200"
local DEFAULT_MOUNT = "secret"
local DEFAULT_KV    = "2"

local _M = {}

function _M.env(name, fallback)
  local v = os.getenv(name)
  if v == nil or v == "" then
    return fallback
  end
  return v
end

-- true when OPENBAO_FAIL_MODE asks for the request to go on without the secret
function _M.fail_open()
  return _M.env("OPENBAO_FAIL_MODE", "closed") == "open"
end

-- Builds the read URL for the configured kv engine version.
local function secret_url(path)
  local addr    = _M.env("OPENBAO_ADDR", DEFAULT_ADDR)
  local mount   = _M.env("OPENBAO_MOUNT", DEFAULT_MOUNT)
  local version = _M.env("OPENBAO_KV", DEFAULT_KV)

  if version == "1" then
    return string.format("%s/v1/%s/%s", addr, mount, path)
  end
  return string.format("%s/v1/%s/data/%s", addr, mount, path)
end

-- Returns the secret's fields as a table, or nil plus a short reason. The
-- reason is for the log only: it never reaches the client, and it never
-- contains secret material or an OpenBao response body (an error body can
-- echo the requested path).
local function fetch(path)
  local token = os.getenv("OPENBAO_TOKEN")
  if not token or token == "" then
    return nil, "OPENBAO_TOKEN is not set in the nginx environment"
  end

  local httpc = http.new()
  httpc:set_timeout(5000)
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
  if _M.env("OPENBAO_KV", DEFAULT_KV) == "1" then
    data = body.data
  else
    data = body.data.data
  end
  if not data then
    return nil, "no data at path"
  end
  return data
end

-- get(path, opts) -> data, err, stale
--   data   the secret's fields, or nil
--   err    the reason for the last failed read (also set when stale is true)
--   stale  true when data comes from the last-good copy because a re-read failed
--
-- lrucache stores only successes: the creation function returns nil on
-- failure, so nothing is cached and the next request retries. The reason
-- travels out through an upvalue rather than a second return value, because
-- lrucache keeps only the first.
function _M.get(path, opts)
  local stale_ttl = (opts and opts.stale_ttl) or 0
  local last_err
  local data = cache(path, nil, function(p)
    local v, e = fetch(p)
    last_err = e
    if v then
      last_good_set(p, v)
    end
    return v
  end, path)
  if data then
    return data, nil, false
  end
  local lg = last_good_get(path)
  if stale_ttl > 0 and lg and (ngx.now() - lg.at) <= stale_ttl then
    return lg.data, last_err or "unavailable", true
  end
  return nil, last_err or "unavailable", false
end

return _M
