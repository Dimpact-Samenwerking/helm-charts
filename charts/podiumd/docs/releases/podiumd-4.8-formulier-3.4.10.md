# Formulier — PodiumD 4.8

← [Terug naar PodiumD 4.8 overzicht](podiumd-4.8.md)

| | |
|---|---|
| Component | Formulier |
| Gemaakt door | Maykin Media |
| Vorige app versie | 3.4.9 |
| Vorige chart versie | 1.12.0 |
| Huidige app versie | 3.4.10 |
| Huidige chart versie | 1.12.0 |
| Bijgewerkt (datum) | 06-07-2026 (aangemaakt) |

## Wijzigingen

**🟦 Patch update**

### ✅ Improvements

- SDK geüpgraded naar 3.4.4
- Overmatige netwerkaanroepen bij adresopzoeking teruggebracht
- StUF-ZDS: tijdstip van indienen beschikbaar als registratievariabele
- StUF-ZDS: ondersteuning voor `extraElementen`-mappings op initiatorniveau
- StUF-ZDS: kommagescheiden serialisatie voor array-waarden in `extraElement`

### 🐞 Bug fixes

- Ontbrekende configuratie voor `application/hal+json` response logging gecorrigeerd
- Objects API en ZGW APIs gebruikten de interne formuliernaam voor gerelateerde documenten
- `addressNL`-validatie hersteld zodat aangepaste foutmeldingen worden ondersteund
- "Cosign vereist"-validatie hield geen rekening met stap-toepasbaarheid
- Validatiefouten bij bestandsupload met soft-hyphens in bestandsnaam
- Formulierthema werd niet correct toegepast op cosign- en uitstelmail 
- Vertaalfouten gecorrigeerd
- SDK: datumtijdvalidatie werd te vroeg getriggerd
- SDK: pinnen, lijnen en polygonen plaatsen in de kaartcomponent werkte niet 
- SDK: tijdwaarden met alleen uren en minuten werden onjuist weergegeven 
- SDK: adresafleiding in tekstvelden niet ondersteund in de nieuwe renderer 
- SDK: childcomponentdata werd niet correct bijgewerkt bij gebruik van voorinvuldata 

### 🔏 Security fixes

- Dependency-updates: urllib3, requests, Tornado, cryptography, josepy, js-cookie, babel, esbuild, dompurify

### 📗 Nadere informatie

Een gedetailleerd overzicht van de stories die zijn ontwikkeld en getest specifiek voor deze release:
[Open Formulieren 3.4.10 changelog](https://open-forms.readthedocs.io/en/3.4.10/changelog.html)
[SDK 3.4.4 changelog](https://open-forms.readthedocs.io/en/3.4.10/changelog-sdk.html)
