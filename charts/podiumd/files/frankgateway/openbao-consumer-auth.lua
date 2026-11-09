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
--     validity           = true,                        -- optional; default true: refuse a
--                                                       --   certificate outside its validity period
--     certHeader         = "X-Client-Cert",             -- optional; the PEM the front door forwards
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
-- Validity. A front door in passthrough mode (the Azure Application Gateway
-- profile chosen in IN-3287) requests the certificate but validates nothing:
-- an expired, not-yet-valid or rogue-CA certificate completes the handshake
-- and arrives here with its fingerprint. The fingerprint match pins one
-- certificate and the handshake proves possession of the key, so a CA check
-- adds no authentication and is deliberately absent (any CA, allow list in
-- OpenBao). The validity period is different: nothing else on the path reads
-- it, and a registered fingerprint would otherwise keep working for as long as
-- nobody remembers to remove it. So when `validity` is on (the default) the
-- PEM the front door forwards in `certHeader` is parsed and the request is
-- refused outside notBefore..notAfter, and when the PEM's SHA-1 does not match
-- the identity header (the two headers must describe the same certificate; a
-- mismatch is a broken rewrite rule, not a caller). A missing `certHeader` is
-- refused too: a check that silently skips reads exactly like a check that
-- passed. Set `validity = false` only behind a front door that cannot forward
-- the PEM. Revocation stays what it is: remove the fingerprint from OpenBao.
--
-- Answers:
--   401  identity header missing/empty, verification header not SUCCESS, or
--        no consumer has that identity; with `validity`: certificate PEM
--        missing or unparseable, expired, not yet valid, or not the
--        certificate the identity header names
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
local x509 = require("resty.openssl.x509")
local ngx  = ngx

-- Parsed certificates, per worker, keyed by the raw header value. A partner
-- presents the same certificate on every call, so the PEM is decoded once per
-- TTL rather than once per request. Successes only (see openbao-client.lua).
local cert_cache = core.lrucache.new({ ttl = 300, count = 64 })

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

local function iso(t)
  return os.date("!%Y-%m-%dT%H:%M:%SZ", t)
end

-- The front door forwards the PEM URL-encoded (newlines as %0A, "+" as %2B);
-- a plain PEM is accepted too, told apart by the "%" a PEM never contains
-- (unescaping a plain PEM would turn its "+" into a space). Only the first
-- certificate is read: the Application Gateway forwards the leaf, and the leaf
-- is the one the fingerprint names.
-- -> { not_before, not_after, sha1 } or nil, reason
local function parse_cert(raw)
  local pem = raw
  if raw:find("%", 1, true) then
    pem = ngx.unescape_uri(raw)
  end
  local b64 = pem:match("%-%-%-%-%-BEGIN CERTIFICATE%-%-%-%-%-(.-)%-%-%-%-%-END CERTIFICATE%-%-%-%-%-")
  if not b64 then
    return nil, "no PEM certificate in the header"
  end
  local der = ngx.decode_base64((b64:gsub("%s", "")))
  if not der then
    return nil, "PEM body is not base64"
  end
  local cert, err = x509.new(der, "DER")
  if not cert then
    return nil, "not an X.509 certificate: " .. tostring(err)
  end
  local not_before, e1 = cert:get_not_before()
  local not_after,  e2 = cert:get_not_after()
  local digest,     e3 = cert:digest("sha1")
  if not (not_before and not_after and digest) then
    return nil, "cannot read validity or digest: " .. tostring(e1 or e2 or e3)
  end
  return {
    not_before = not_before,
    not_after  = not_after,
    sha1       = (digest:gsub(".", function(c) return string.format("%02x", c:byte()) end)),
  }
end

local function cert_get(raw)
  local last_err
  local info = cert_cache(raw, nil, function(r)
    local v, e = parse_cert(r)
    last_err = e
    return v
  end, raw)
  return info, last_err
end

return function(opts)
  local path      = assert(opts and opts.path, "openbao-consumer-auth: path is required")
  local header    = (opts and opts.header) or "X-Client-Cert-Fingerprint"
  local verify_hd = opts and opts.verificationHeader
  local stale_ttl = (opts and opts.stale_ttl) or 3600
  local validity  = true
  if opts and opts.validity == false then
    validity = false
  end
  local cert_hd   = (opts and opts.certHeader) or "X-Client-Cert"
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

    if validity then
      local raw = core.request.header(ctx, cert_hd)
      if not raw or raw == "" then
        core.log.error("openbao-consumer-auth: consumer ", who, ": no ", cert_hd,
                       " on the request; the front door must forward the certificate PEM")
        return exit(401, "client_certificate_required",
                    "the client certificate was not forwarded to this gateway")
      end
      local info, perr = cert_get(raw)
      if not info then
        core.log.error("openbao-consumer-auth: consumer ", who, ": cannot parse ",
                       cert_hd, ": ", perr)
        return exit(401, "client_certificate_invalid",
                    "the client certificate could not be read")
      end
      if info.sha1 ~= identity then
        core.log.error("openbao-consumer-auth: consumer ", who, ": ", cert_hd,
                       " is not the certificate ", header, " names (", info.sha1, ")")
        return exit(401, "client_certificate_mismatch",
                    "the forwarded certificate does not match its fingerprint")
      end
      local now = ngx.time()
      if now > info.not_after then
        core.log.warn("openbao-consumer-auth: consumer ", who,
                      ": certificate expired on ", iso(info.not_after))
        return exit(401, "client_certificate_expired",
                    "the client certificate expired on " .. iso(info.not_after))
      end
      if now < info.not_before then
        core.log.warn("openbao-consumer-auth: consumer ", who,
                      ": certificate is not valid before ", iso(info.not_before))
        return exit(401, "client_certificate_not_yet_valid",
                    "the client certificate is not valid before " .. iso(info.not_before))
      end
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
