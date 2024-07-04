# Open LDAP

## Parameters

| Name                      | Description                                                                 | Value                             |
|---------------------------|-----------------------------------------------------------------------------|-----------------------------------|
| adminUsername             | LDAP administrator username                                                 | `"admin"`                         |
| adminPassword             | LDAP administrator password                                                 | `"admin"`                         |
| root                      | Root of LDAP tree                                                           | `"dc=dimpact,dc=org"`             |
| nameOveride               | String to partially override name template (will maintain the release name) | `""`                              |
| fullnameOverride          | String to fully override name template                                      | `""`                              |
| nodeSelector              | Node labels for pod assignment. Evaluated as a template                     | `{}`                              |
| image.repository          | Image repository                                                            | `bitnami/openldap`                |
| image.tag                 | Image tag                                                                   | `2.6.8`                           |
| image.pullPolicy          | Image pull policy                                                           | `IfNotPresent`                    |
| resources                 | Container requests and limits                                               | `requests: cpu:10m, memory:150Mi` |
| persistence.existingClaim | Manually managed Persistent Volume and Claim                                | `""`                              |
| persistence.subpath       | Path within the volume                                                      | `openldap`                        |


 
