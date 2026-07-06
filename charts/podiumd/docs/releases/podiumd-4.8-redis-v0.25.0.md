# Redis — PodiumD 4.8

← [Terug naar PodiumD 4.8 overzicht](podiumd-4.8.md)

| | |
|---|---|
| Component | Redis |
| Gemaakt door | Opstree Solutions |
| Vorige app versie | v8.6.2 |
| Vorige chart versie | 0.24.0 |
| Huidige app versie | v8.6.2 |
| Huidige chart versie | 0.25.0 |
| Bijgewerkt (datum) | — |

## Wijzigingen

**🟦 Patch update** (redis-operator chart 0.24.0 → 0.25.0; app versie ongewijzigd)

### 📗 Further details

[redis-operator 0.25.0 release](https://github.com/OT-CONTAINER-KIT/redis-operator/releases/tag/0.25.0)

### ✅ Improvements

- Crashloop-fix bij gelijktijdige RedisReplication pod-herstart
- `sentinel.conf` wordt nu persistent opgeslagen

### ⚠ Let op

Rolling restart van het redis-ha cluster is te verwachten bij upgrade.
