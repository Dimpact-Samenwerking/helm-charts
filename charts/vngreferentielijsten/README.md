# VNG Referentielijsten

## Parameters

| Name             | Description                                             | Value                                  |
|------------------|---------------------------------------------------------|----------------------------------------|
| nameOveride      | String to override name template                        | `""`                                   |
| nodeSelector     | Node labels for pod assignment. Evaluated as a template | `{}`                                   |
| image.repository | Image repository                                        | `ghcr.io/infonl/vng-referentielijsten` |
| image.tag        | Image tag                                               | `0.6.1`                                |
| image.pullPolicy | Image pull policy                                       | `IfNotPresent`                         |
| resources        | Container requests and limits                           | `requests: cpu:10m, memory:150Mi`      |
