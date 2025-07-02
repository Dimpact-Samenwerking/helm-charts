# Overzicht van het PodiumD platform

## Achtergrond

PodiumD is opgezet door Dimpact als een platform van applicaties voor gemeentelijke dienstverlening.

## Architectuur

Hieronder staat het System Context diagram van PodiumD, dat de architectuur van het PodiumD systeem weergeeft. 
Het diagram toont de interacties tussen de verschillende componenten, zowel binnen als buiten de PodiumD context.

```mermaid
C4Context
    Enterprise_Boundary(b0, "PodiumD") {
        System_Boundary(products, "Producten") {
            System(ZAC, "ZAC")
            System(OpenFormulieren, "Open Formulieren")
            System(OpenInwoner, "Open Inwoner Platform")
            System(Contact,"Contact")
        }

        System_Boundary(registers, "Registers") {
            System(OpenNotificaties, "Open Notificaties")
            System(Objecten, "Objecten")
            System(Objecttypen, "Objecttypen")
            System(OpenZaak, "Open Zaak")
            System(OpenKlant, "Open Klant")
            System(OpenArchiefbeheer, "Open Archiefbeheer")
        }

        System_Boundary(andersteunend, "Ondersteunenende componenten") {
            System(keycloak, "Keycloak")
            System(nginx, "NGINX")
        }
    }

    Enterprise_Boundary(b1, "Gemeentelijke diensten") {
        System(SMTPServer, "SMTP Mail Server")
    }

    Enterprise_Boundary(b1, "Externe diensten") {
        System(BAG, "BAG")
        System(BRP, "BRP")
        System(KVK, "KVK")
        System(SmartDocuments, "SmartDocuments")
    }

    Rel(OpenArchiefbeheer, OpenZaak, "Uses", "ZGW Documenten en Zaken API")
    Rel(ZAC, OpenZaak, "Uses", "ZGW Autorisaties, Besluiten, Catalogi, Documenten, en Zaken API")

    Rel(Contact, OpenKlant, "Uses", "ZGW Klant API")

    Rel(OpenInwoner, OpenKlant, "Uses", "ZGW Klant API")
```
