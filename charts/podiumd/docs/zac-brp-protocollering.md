# ZAC — BRP protocollering configuration

ZAC 5.0.1 replaced the single `protocollering.aanbieder` selector with an
explicit, field-per-dimension structure. Each gemeente configures the exact
HTTP headers and values their BRP gateway vendor expects, rather than ZAC
inferring them from a vendor name.

Protocollering is **disabled by default** (`protocollering.enabled: false`).
Enable it only when the BRP gateway requires it.

All values below go in the gemeente's `podiumd.yml` under `zac.brpApi`.

---

## iConnect

```yaml
zac:
  brpApi:
    url: http://api-proxy.podiumd.svc.cluster.local/brp
    apiKey:
      header: "x-api-key"
      value: "geldige-brp-api-key"
    logLevel: "OFF"
    protocollering:
      enabled: true
      systemUser: "SystemUser"
      originOin:
        oin: "gemeentelijke OIN"
        header: "x-origin-oin"
      doelbinding:
        perZaaktype: true
        header: "x-doelbinding"
        zoekmet: "BRPACT-ZoekenAlgemeen"
        raadpleegmet: "BRPACT-ZacPersoonBasis"
      verwerking:
        header: "x-verwerking"
        register: "DigitaleDienstverlening"
      gebruiker:
        header: "x-gebruiker"
      toepassing:
        header: "x-toepassing"
        value: "dummy"
```

---

## eServices

```yaml
zac:
  brpApi:
    url: http://api-proxy.podiumd.svc.cluster.local/brp
    apiKey:
      header: "x-api-key"
      value: "dummy"
    logLevel: "OFF"
    protocollering:
      enabled: true
      originOin:
        oin: "gemeentelijke OIN"
        header: "x-request-organization"
      doelbinding:
        perZaaktype: false
        header: ""
      verwerking:
        header: "x-request-afnemerscode"
        register: "dummy"
      gebruiker:
        header: "x-request-user"
      toepassing:
        header: "x-request-application"
        value: "dummy"
```

---

## 2Secure / EnableU

```yaml
zac:
  brpApi:
    url: http://api-proxy.podiumd.svc.cluster.local/brp
    apiKey:
      header: "x-api-key"
      value: "dummy"
    logLevel: "OFF"
    protocollering:
      enabled: true
      systemUser: "SystemUser"
      doelbinding:
        perZaaktype: false
      verwerking:
        header: "x-verwerking"
        register: "dummy"
      gebruiker:
        header: "x-gebruiker"
      toepassing:
        header: "x-applicatie"
        value: "dummy"
```

---

## Field reference

| Field | Required | Description |
|---|---|---|
| `brpApi.logLevel` | no | Log level for BRP API calls. `"OFF"` suppresses request/response logging. |
| `protocollering.enabled` | yes | Enable or disable BRP protocollering. |
| `protocollering.systemUser` | iConnect, 2Secure | Fixed username sent as the acting system user. Omit for eServices. |
| `protocollering.originOin.oin` | when enabled | The gemeente's OIN, sent to identify the requesting organisation. |
| `protocollering.originOin.header` | when enabled | HTTP header name for the OIN. |
| `protocollering.doelbinding.perZaaktype` | yes | When `true`, ZAC derives the doelbinding from the zaaktype. When `false`, a fixed doelbinding header is sent (or omitted if `header` is empty). |
| `protocollering.doelbinding.header` | when `perZaaktype: true` | HTTP header name for the doelbinding value. Set to `""` to omit the header. |
| `protocollering.doelbinding.zoekmet` | iConnect | BRP action code for search operations. |
| `protocollering.doelbinding.raadpleegmet` | iConnect | BRP action code for retrieval operations. |
| `protocollering.verwerking.header` | when enabled | HTTP header name for the verwerking (processing) identifier. |
| `protocollering.verwerking.register` | when enabled | Name of the verwerkingsregister (processing register). |
| `protocollering.gebruiker.header` | when enabled | HTTP header name for the acting end-user. ZAC fills this with the logged-in user. |
| `protocollering.toepassing.header` | when enabled | HTTP header name for the application identifier. |
| `protocollering.toepassing.value` | when enabled | Fixed application identifier value sent in the header. |

## Migration from ZAC 4.7.x

The old `protocollering.aanbieder` field and implicit vendor-specific defaults
are gone in ZAC 5.0.1. Map your previous configuration as follows:

| Old (4.7.x) | New (5.0.1) |
|---|---|
| `protocollering.aanbieder: "iConnect"` | `protocollering.enabled: true` + full iConnect block above |
| `protocollering.aanbieder: "2Secure"` | `protocollering.enabled: true` + full 2Secure block above |
| `protocollering.aanbieder: ""` | `protocollering.enabled: false` |
| `protocollering.verwerkingsregister: "..."` | `protocollering.verwerking.register: "..."` |
| `protocollering.doelbinding.zoekmet` | `protocollering.doelbinding.zoekmet` (unchanged) |
| `protocollering.doelbinding.raadpleegmet` | `protocollering.doelbinding.raadpleegmet` (unchanged) |
