-- openbao-consumer-auth.lua
--
-- TEMPORARY — obsolete with the next Frank!Gateway release. This module exists
-- because Frank!Gateway 1.1.0 runs APISIX 3.16, where $secret:// references do
-- not cover this use. The next release resolves them natively; this file is
-- then deleted, not maintained. Do not build on its interface.
--
-- APISIX serverless-pre-function (phase: access) for the inway: identifies the
-- calling party from the client-certificate identity a trusted front door
-- forwards in a request header, against a consumer list kept in OpenBao.
--
--   local consumer_auth = require("openbao-consumer-auth")
--   return consumer_auth({
--     path               = "frankgateway/consumers",   -- secret within the mount
--     header             = "X-Client-Cert-Fingerprint", -- default; the identity header
--     verificationHeader = "X-Client-Cert-Verification",-- optional; must read SUCCESS
--     allow              = { "vendor-a", "vendor-b" },  -- optional; nil = any known consumer
--     stale_ttl          = 3600,                        -- optional; default 3600 s
--   })
--
-- The secret is a map of consumer name -> identity value(s):
--
--   vendor-a = "ab12cd34...ef"              one SHA-1 fingerprint
--   vendor-b = "ab12...ef,98fe...01"        two, so old and new certificates
--                                            overlap during a rotation
--
-- Both sides are normalised (lower case, colons and whitespace removed) before
-- comparison, so an environment that forwards the certificate SUBJECT instead
-- can point `header` at that and list subject DNs as the values.
--
-- Trust. This function believes the header. That is only sound when every
-- request reaching this route arrived through a proxy that verified the client
-- certificate and OVERWRITES the header on every request (the Azure
-- Application Gateway rewrite rules do), and when the inway is reachable only
-- through that path (NetworkPolicy from the ingress namespace; the ingress
-- reachable only from the front door). templates/validations.yaml refuses this
-- function on any instance whose class is not `inway` for that reason.
--
-- Answers:
--   401  identity header missing/empty, verification header not SUCCESS, or
--        no consumer has that identity
--   403  a known consumer that is not in this route's `allow` list
--   503  OpenBao could not be read and no last-good list is within stale_ttl
--
-- Stale-on-error: the consumer list is served from the last successful read
-- for up to stale_ttl seconds when OpenBao is unreachable, so an OpenBao
-- outage longer than the 300 s cache does not turn into a 503 on every inbound
-- request. The copy is pod-wide (a shared dict, see openbao-client.lua), so
-- one successful read since the pod started is enough for every worker in it.
-- The cost is that revoking a consumer during such an outage takes effect only
-- when OpenBao is back — bounded by stale_ttl. Set stale_ttl = 0 to fail
-- closed immediately.

local core = require("apisix.core")
local bao  = require("openbao-client")

local function norm(s)
  if s == nil then
    return ""
  end
  s = tostring(s):lower()
  s = s:gsub("[%s:]", "")
  return s
end

local function exit(status, err, message)
  return core.response.exit(status, { error = err, message = message })
end

return function(opts)
  local path      = assert(opts and opts.path, "openbao-consumer-auth: path is required")
  local header    = (opts and opts.header) or "X-Client-Cert-Fingerprint"
  local verify_hd = opts and opts.verificationHeader
  local stale_ttl = (opts and opts.stale_ttl) or 3600
  local allow
  if opts and opts.allow then
    allow = {}
    for _, name in ipairs(opts.allow) do
      allow[name] = true
    end
  end

  return function(_, ctx)
    if verify_hd then
      local v = core.request.header(ctx, verify_hd)
      if not v or v:upper() ~= "SUCCESS" then
        core.log.warn("openbao-consumer-auth: ", verify_hd, " is not SUCCESS")
        return exit(401, "client_certificate_not_verified",
                    "a verified client certificate is required")
      end
    end

    local identity = norm(core.request.header(ctx, header))
    if identity == "" then
      core.log.warn("openbao-consumer-auth: no ", header, " on the request")
      return exit(401, "client_certificate_required",
                  "a client certificate is required")
    end

    local consumers, err, stale = bao.get(path, { stale_ttl = stale_ttl })
    if not consumers then
      core.log.error("openbao-consumer-auth: cannot read ", path, ": ", err)
      return exit(503, "secret_unavailable",
                  "gateway could not read the consumer list from OpenBao")
    end
    if stale then
      core.log.warn("openbao-consumer-auth: serving the last-good consumer list for ",
                    path, " because the re-read failed: ", err)
    end

    local who
    for name, values in pairs(consumers) do
      for v in tostring(values):gmatch("[^,]+") do
        if norm(v) == identity then
          who = name
          break
        end
      end
      if who then
        break
      end
    end

    if not who then
      core.log.warn("openbao-consumer-auth: no consumer in ", path, " matches ", header)
      return exit(401, "unknown_client_certificate",
                  "the client certificate is not known to this gateway")
    end
    if allow and not allow[who] then
      core.log.warn("openbao-consumer-auth: consumer ", who, " is not allowed on this route")
      return exit(403, "consumer_not_allowed",
                  "this consumer is not allowed to call this route")
    end

    -- Overwrites anything the client sent under this name: the upstream and the
    -- access log see the identity the gateway established, never a claimed one.
    core.request.set_header(ctx, "X-Consumer-Username", who)
  end
end
