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
            System(ZAC, "Zaak - ZAC")
            System(OpenArchiefbeheer, "Zaak - Archiefbeheer")
        }

        System_Boundary(registers, "Common Ground componenten") {
            System(OpenKlant, "Open Klant")
            System(OpenZaak, "Open Zaak")
            System(Objecten, "Objecten")
            System(Objecttypen, "Objecttypen")
            System(OpenNotificaties, "Open Notificaties")
        }

        System_Boundary(andersteunend, "Overige componenten") {
            System(keycloak, "Keycloak")
            System(clamav, "Clamav")
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

    Rel(Contact, OpenKlant, "")

    Rel(OpenInwoner, OpenKlant, "")

    UpdateElementStyle(BAG, $bgColor="grey", $borderColor="black")
    UpdateElementStyle(BRP, $bgColor="grey", $borderColor="black")
    UpdateElementStyle(KVK, $bgColor="grey", $borderColor="black")
    UpdateElementStyle(SmartDocuments, $bgColor="grey", $borderColor="black")

   UpdateElementStyle(keycloak, $bgColor="green", $borderColor="black")
   UpdateElementStyle(clamav, $bgColor="green", $borderColor="black")
```

## Componenten

### Formulier (Open Formulieren)
Zie voor architectuur context diagram van Open Formulieren de [Open Formulieren documentatie](./formulieren.md).
