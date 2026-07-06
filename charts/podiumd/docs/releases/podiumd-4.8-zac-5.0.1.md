# Zaak - ZAC — PodiumD 4.8

← [Terug naar PodiumD 4.8 overzicht](podiumd-4.8.md)

| | |
|---|---|
| Component | Zaak - ZAC |
| Gemaakt door | INFO.nl |
| Vorige app versie | 4.7.2 |
| Vorige chart versie | 1.0.228 |
| Huidige app versie | 5.0.1 |
| Huidige chart versie | 1.0.251 |
| Bijgewerkt (datum) | — |

## Wijzigingen

**⇪ Major update**

### 📗 Further details

[ZAC 5.0.1 release](https://github.com/infonl/dimpact-zaakafhandelcomponent/releases/tag/5.0.1)

### ⚠ Breaking changes — actie vereist per gemeente

**1. `zac.brpApi.apiKey` geherstructureerd**

```yaml
# Vóór (4.7.x)
zac:
  brpApi:
    apiKey: "your-api-key"

# Na (5.0.1)
zac:
  brpApi:
    apiKey:
      header: "x-api-key"
      value: "your-api-key"
```

**2. `zac.featureFlags.pabcIntegration` verwijderd**

Verwijder deze regel uit gemeente-values als die aanwezig is.

**3. `zac.brpApi.protocollering` volledig geherstructureerd**

Zie [`../zac-brp-protocollering.md`](../zac-brp-protocollering.md) voor de volledige vendor-specifieke configuratie (iConnect, eServices, 2Secure/EnableU).

| Oud (4.7.x) | Nieuw (5.0.1) |
|---|---|
| `protocollering.aanbieder: "iConnect"` | `protocollering.enabled: true` + expliciete velden |
| `protocollering.aanbieder: ""` | `protocollering.enabled: false` |
| `protocollering.verwerkingsregister` | `protocollering.verwerking.register` |

**4. iConnect: `apiproxy.brp.toepassingHeaderName` uitschakelen**

ZAC 5.0.1 stuurt de toepassing-header zelf via protocollering. Zet in gemeente-values:

```yaml
apiproxy:
  locations:
    brp:
      toepassingHeaderName: ""
```
