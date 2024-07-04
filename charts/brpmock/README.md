# Haal Centraal BRP bevragen mock

## Parameters

| Name                      | Description                                             | Value                                                 |
|---------------------------|---------------------------------------------------------|-------------------------------------------------------|
| nameOveride               | String to override name template                        | `""`                                                  |
| nodeSelector              | Node labels for pod assignment. Evaluated as a template | `{}`                                                  |
| brpproxy.image.repository | Proxy image repository                                  | `iswish/haal-centraal-brp-bevragen-proxy`             |
| brpproxy.image.tag        | Proxy image tag                                         | `2.0.20`                                              |
| brpproxy.image.pullPolicy | Proxy image pull policy                                 | `IfNotPresent`                                        |
| brpproxy.resources        | Proxy container requests and limits                     | `requests: cpu:10m, memory:150Mi`                     |
| gbamock.image.repository  | Mock image repository                                   | `ghcr.io/brp-api/haal-centraal-brp-bevragen-gba-mock` |
| gbamock.image.tag         | Mock image tag                                          | `2.0.8`                                               |
| gbamock.image.pullPolicy  | Mock image pull policy                                  | `IfNotPresent`                                        |
| gbamock.resources         | Mock container requests and limits                      | `requests: cpu:10m, memory:150Mi`                     |

