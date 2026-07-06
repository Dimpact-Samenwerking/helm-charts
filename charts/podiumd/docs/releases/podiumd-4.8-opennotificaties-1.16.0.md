# Open Notificaties — PodiumD 4.8

← [Terug naar PodiumD 4.8 overzicht](podiumd-4.8.md)

| | |
|---|---|
| Component | Open Notificaties |
| Gemaakt door | Maykin Media |
| Vorige app versie | 1.15.0 |
| Vorige chart versie | 1.13.1 |
| Huidige app versie | 1.16.0 |
| Huidige chart versie | 2.0.0 |
| Bijgewerkt (datum) | — |

## Wijzigingen

**⇧ Minor update**

### 📗 Further details

[Open Notificaties 1.16.0 release](https://github.com/open-zaak/open-notificaties/releases/tag/1.16.0)

### ✅ Improvements

- RabbitMQ vervangen door Redis als Celery-broker (minder componenten, geen aparte RabbitMQ-installatie nodig)

### ⚠ Breaking change — actie vereist per gemeente

De Helm chart is van major versie gewisseld (1.x → 2.x). Controleer gemeentespecifieke `open-notificaties:` value-overrides op verwijderde of hernoemde velden.

**Procedure:**
1. Quiesceer producers en wacht tot RabbitMQ-queues leeg zijn
2. Voer de upgrade uit
3. Verwijder daarna de RabbitMQ PVC en het Secret
