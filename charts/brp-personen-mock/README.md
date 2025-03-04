# brp-personen-mock

BRP personen mock Helm chart

## Parameters

| Name | Type | Value | Description |
|-----|------|---------|-------------|
| brp-personen-mock.image.pullPolicy | string | `"IfNotPresent"` | Personen mock image pull policy  |
| brp-personen-mock.image.repository | string | `"ghcr.io/brp-api/personen-mock"` | Personen mock image repository |
| brp-personen-mock.image.tag | string | `"2.6.0-202502261446"` | Personen mock tag  |
| brp-personen-mock.resources.requests.cpu | string | `"10m"` | Personen mock container requests and limits |
| brp-personen-mock.resources.requests.memory | string | `"150Mi"` | Personen mock container requests and limits |

