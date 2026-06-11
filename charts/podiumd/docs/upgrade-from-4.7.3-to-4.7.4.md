# Upgrade guide: PodiumD 4.7.3 → 4.7.4


## Changes

### Add Datamigratie Keycloak client and Open Zaak secret

Datamigratie is deployed in a separate pipeline. But Datamigratie needs a connection to Open Zaak,
plus it needs a Keycloak Client, to allow user to log on. 

The PodiumD helm-chart includes these.

Update podiumd.yml for each gemeente
 

#### Action required

Verify if these 2 secrets exist in the Keyvault. If not, at them: 

`OPENZAAK_CREDENTIALS_DATAMIGRATIE_SECRET:   $(openzaak-credentials-datamigratie-secret)`

`DATAMIGRATIE_OIDC_SECRET:  $(datamigratie-oidc-secret)`


Update podiumd.yml for each gemeente, to add the Keycloak client for datamigratie, and
to add the Datamigratie application to Open Zaak. 

* In Keycloak, add client for Datamigratie

```
keycloak:
  ...
  config:
    ...
    clients:
      datamigratie:
        name: Datamigratie
        enabled: true
        secret: "REP_DATAMIGRATIE_OIDC_SECRET_REP"
        oidcUrl: "https://datamigratie.example.nl"

```

* In Open Zaak, add the application and the client secret for Datamigratie

```
openzaak:
  ...
  configuration:
    ...
    data: |
      ...
      vng_api_common_credentials:
        items:
          ...
          - identifier: datamigratie
            secret: "REP_OPENZAAK_CREDENTIALS_DATAMIGRATIE_SECRET_REP"  
      vng_api_common_applicaties_config_enable: true
      vng_api_common_applicaties:
        items:
          ...
          - uuid: dc69a5f8-c00a-4302-ada5-c67beddbc65c
            client_ids:
              - datamigratie
            heeft_alle_autorisaties: true
            label: Datamigratie
```
