# Interne Taak Afhandeling — PodiumD 4.8

← [Terug naar PodiumD 4.8 overzicht](podiumd-4.8.md)

| | |
|---|---|
| Component | Interne Taak Afhandeling |
| Gemaakt door | ITA project |
| Vorige app versie | 3.1.0 |
| Vorige chart versie | 3.1.0 |
| Huidige app versie | 3.2.0 |
| Huidige chart versie | 3.2.0 |
| Bijgewerkt (datum) | — |

## Wijzigingen

**⇧ Minor update**

### 📗 Further details

[ITA GitHub releases](https://github.com/interne-taak-afhandeling/internetaakafhandeling/releases/tag/3.2.0)

### 🚀 New functionality

- Medewerker-objecttype configuratie — nieuw verplicht `ita.medewerker` blok

### ⚠ Actie vereist per gemeente

Stel de environment-specifieke Medewerker objecttype URL in:

```yaml
ita:
  medewerker:
    type: "https://<env>-objecttypen.<gemeente>.nl/api/v2/objecttypes/<UUID>"
    typeVersion: 1
```

De render mislukt als `ita.medewerker.type` leeg is terwijl ITA ingeschakeld is.
