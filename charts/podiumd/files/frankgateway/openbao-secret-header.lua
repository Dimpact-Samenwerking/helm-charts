-- openbao-secret-header.lua
--
-- APISIX serverless-pre-function (phase: rewrite) that fetches a secret from
-- OpenBao at request time and sets it as an upstream header, so the value lives
-- only in OpenBao and the gateway holds nothing but a scoped reader token.
--
--   local set_secret_header = require("openbao-secret-header")
--   return set_secret_header({
--     path   = "frankgateway",   -- secret path within the mount
--     field  = "bag_api_key",    -- key inside that secret
--     header = "X-Api-Key",      -- header to set upstream
--   })
--
-- The call sites that exist today:
--   BAG           field bag_api_key,      header X-Api-Key
--   KVK           field kvk_api_key,      header apikey
--   ESB consumer  field esb_consumer_key, header apikey        (IN-2543)
--
-- Environment, caching and the kv v1/v2 difference live in openbao-client.lua.
--
-- FAIL CLOSED by default. An earlier version failed open: on any error the
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
-- No stale serving here: an API key that OpenBao can no longer hand out should
-- stop being sent, and the 503 is the signal that something needs attention.

local core = require("apisix.core")
local bao  = require("openbao-client")

return function(opts)
  local path   = assert(opts and opts.path, "openbao-secret-header: path is required")
  local field  = assert(opts and opts.field, "openbao-secret-header: field is required")
  local header = assert(opts and opts.header, "openbao-secret-header: header is required")

  return function(_, ctx)
    local secret, err = bao.get(path)

    if secret and secret[field] then
      core.request.set_header(ctx, header, secret[field])
      return
    end

    if not err then
      err = "field " .. field .. " not present"
    end
    core.log.error("openbao: cannot set header ", header, " from ", path, ": ", err)

    if bao.fail_open() then
      -- Send the request on without the header; the upstream will reject it.
      return
    end

    return core.response.exit(503, {
      error = "secret_unavailable",
      message = "gateway could not read the upstream credential from OpenBao",
    })
  end
end
