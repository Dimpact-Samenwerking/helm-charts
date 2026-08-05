# Overzicht van het PodiumD platform

## Achtergrond

PodiumD is opgezet door Dimpact als een platform van applicaties voor gemeentelijke dienstverlening.

## Architectuur

Hieronder staat het System Context diagram van PodiumD, dat de architectuur van het PodiumD systeem weergeeft. 
Het diagram toont de interacties tussen de verschillende componenten, zowel binnen als buiten de PodiumD context.

```mermaid
C4Context
    Enterprise_Boundary(b0, "PodiumD") {
        System_Boundary(products, "Product componenten") {
            System(OpenFormulieren, "Formulier (Open Formulieren)")
            System(OpenInwoner, "Portaal (Open Inwoner platform)")
            System(Contact,"Contact (KISS)")
            System(ITA, "Contact - ITA (interne taken)")
            System(ZAC, "Zaak - ZAC")
            System(OpenArchiefbeheer, "Zaak - Archiefbeheer")
            System(OpenBeheer, "Zaak - Open Beheer")
        }

        System_Boundary(registers, "Common Ground componenten") {
            System(OpenKlant, "Open Klant")
            System(OpenZaak, "Open Zaak")
            System(Objecten, "Objecten (merged Objects+Objecttypes API)")
            System(OpenNotificaties, "Open Notificaties")
            System(Referentielijsten, "Referentielijsten")
        }

        System_Boundary(andersteunend, "Overige componenten") {
            System(keycloak, "Keycloak")
            System(clamav, "Clamav")
            System(PABC, "PABC (autorisatie)")
            System(OMC, "OMC (NotifyNL)")
            System(OfficeAddin, "ZGW Office Add-in")
            System(Zaakbrug, "Zaakbrug (opt-in)")
        }
    }

    Enterprise_Boundary(b1, "Externe diensten") {
        System(BAG, "BAG")
        System(BRP, "BRP")
        System(KVK, "KVK")
        System(SmartDocuments, "SmartDocuments")
    }

    Rel(OpenArchiefbeheer, OpenZaak, "")
    Rel(ZAC, OpenZaak, "")
    Rel(ZAC, PABC, "Autorisatie")

    Rel(Contact, OpenKlant, "")
    Rel(ITA, OpenKlant, "Interne taken")

    Rel(OpenInwoner, OpenKlant, "")

    Rel(OpenBeheer, Objecten, "Beheer (API-token)")
    Rel(OpenNotificaties, OMC, "Notificeer")
    Rel(OfficeAddin, OpenZaak, "Documenten")
    Rel(Zaakbrug, OpenZaak, "ZDS ↔ ZGW")

    UpdateElementStyle(BAG, $bgColor="grey", $borderColor="black")
    UpdateElementStyle(BRP, $bgColor="grey", $borderColor="black")
    UpdateElementStyle(KVK, $bgColor="grey", $borderColor="black")
    UpdateElementStyle(SmartDocuments, $bgColor="grey", $borderColor="black")

   UpdateElementStyle(keycloak, $bgColor="green", $borderColor="black")
   UpdateElementStyle(clamav, $bgColor="green", $borderColor="black")
   UpdateElementStyle(PABC, $bgColor="green", $borderColor="black")
   UpdateElementStyle(OMC, $bgColor="green", $borderColor="black")
   UpdateElementStyle(OfficeAddin, $bgColor="green", $borderColor="black")
   UpdateElementStyle(Zaakbrug, $bgColor="green", $borderColor="black")
```

> Diagram bijgewerkt voor PodiumD **4.8.0**: PABC (autorisatie, standaard aan
> sinds 4.8.0), ITA, Open Beheer, OMC (NotifyNL), Referentielijsten,
> ZGW Office Add-in en Zaakbrug (opt-in) toegevoegd.

## Componenten

### Formulier (Open Formulieren)
Zie voor architectuur context diagram van Open Formulieren de [Open Formulieren documentatie](./formulieren.md).

### Contact (KISS)
Zie voor architectuur context diagram van Contact (KISS) de [Contact documentatie](./contact.md).

## Operationele functionaliteit

### MI exports — wekelijkse database dumps naar SFTP
Wekelijkse exports van alle Postgres-componenten naar een externe SFTP server (CSV of `pg_dump`), per gemeente.
Voor activatie, infra-prerequisites (incl. Terraform-snippet voor externe hosting), en troubleshooting:
zie [MI exports documentatie](../misc/mi-exports.md).
