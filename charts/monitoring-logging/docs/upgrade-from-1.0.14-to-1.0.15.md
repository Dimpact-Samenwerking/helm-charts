# Upgrade guide: monitoring-logging 1.0.14 → 1.0.15

## Summary of changes

Single dashboard fix in `dashboards/logging-main-dashboard.json`. No component version changes, no values schema changes, no operator action required.

### Fix: successful notifications count in main dashboard

The "successful notifications" panel was counting `task_succeeded` log events on the `opennotificaties-worker` app. That metric counts all Celery task completions, not just notification deliveries.

1.0.15 corrects the LogQL expression to filter on `notification_successful` instead:

```logql
# Before (1.0.14):
{app="opennotificaties-worker"}
|= "task_succeeded"
| json event
| event="task_succeeded"

# After (1.0.15):
{app="opennotificaties-worker"}
|= "notification_successful"
| json event
| event="notification_successful"
```

The panel now shows the number of successfully delivered notifications, which is the intended metric.

---

## No other changes

No breaking changes, no image updates, no values schema migrations.
