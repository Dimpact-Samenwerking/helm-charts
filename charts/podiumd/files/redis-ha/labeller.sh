#!/bin/sh
# redis-ha labeller (podiumd-chart-24), rendered by templates/redis-ha-labeller.yaml.
#
# Sentinel promotes a replica when the master goes, but the redis-operator only
# moves the redis-role label (the selector of the redis-ha-master Service) once
# every redis-ha and sentinel pod is Ready again: after a node failure that is
# minutes. This loop labels the pod that a quorum of sentinels reports as master,
# so redis-ha-master follows Sentinel within seconds.
#
# - It removes the master label from every other pod before it labels the new
#   master, so the Service never selects two pods.
# - It changes nothing while no quorum of sentinels agrees on a redis-ha pod
#   (sentinels not configured yet, partition, sentinels down).
# - A replica whose link is down for REPAIR_AFTER seconds while it follows
#   another address than the master gets REPLICAOF the master. The operator
#   links replicas by IP and leaves relinking to Sentinel once Sentinel is on,
#   so a master that restarted before Sentinel knew it (the upgrade that turns
#   Sentinel on) would keep its replicas on its old IP.
#
# Environment: NAMESPACE, APP (the pods' app label), CR (RedisReplication
# name), SENTINELS (number of sentinel pods), INTERVAL and REPAIR_AFTER
# (seconds), KUBECTL and STALE_DIR (only for tests), STATE_FILE (liveness).
set -u

KUBECTL=${KUBECTL:-kubectl}
STATE_FILE=${STATE_FILE:-/tmp/alive}
STALE_DIR=${STALE_DIR:-/tmp/stale}
QUORUM=$((SENTINELS / 2 + 1))
mkdir -p "$STALE_DIR"

log() {
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
}

# One command to a Redis or Sentinel server; prints the reply without CRs.
# QUIT makes the server close the connection, so nc returns at once.
redis_cmd() {
  printf '%s\r\nQUIT\r\n' "$3" | timeout 3 nc -w 2 "$1" "$2" 2>/dev/null | tr -d '\r'
}

# The pod that at least QUORUM sentinels report as master, or nothing.
quorum_master() {
  votes=""
  i=0
  while [ "$i" -lt "$SENTINELS" ]; do
    host=$(redis_cmd "$CR-s-$i.$CR-s-hl" 26379 "SENTINEL get-master-addr-by-name mymaster" | sed -n 3p)
    case "${host%%.*}" in
      "$CR"-[0-9]*) votes="$votes ${host%%.*}" ;;
    esac
    i=$((i + 1))
  done
  for candidate in $votes; do
    n=0
    for vote in $votes; do
      [ "$vote" = "$candidate" ] && n=$((n + 1))
    done
    if [ "$n" -ge "$QUORUM" ]; then
      echo "$candidate"
      return
    fi
  done
}

info_field() {
  printf '%s\n' "$1" | sed -n "s/^$2://p"
}

last_state=""
while true; do
  touch "$STATE_FILE"
  master=$(quorum_master)
  if [ -z "$master" ]; then
    [ "$last_state" = "no-quorum" ] || log "no master agreed by $QUORUM of $SENTINELS sentinels, labels unchanged"
    last_state="no-quorum"
    sleep "$INTERVAL"
    continue
  fi

  # name|role|ip, one pod per line; role is empty for a pod without the label.
  if ! pods=$($KUBECTL get pods -n "$NAMESPACE" -l "app=$APP,role=replication" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"|"}{.metadata.labels.redis-role}{"|"}{.status.podIP}{"\n"}{end}'); then
    log "cannot list the redis-ha pods"
    sleep "$INTERVAL"
    continue
  fi
  master_line=$(printf '%s\n' "$pods" | grep "^$master|") || {
    [ "$last_state" = "no-pod:$master" ] || log "sentinel master $master has no pod"
    last_state="no-pod:$master"
    sleep "$INTERVAL"
    continue
  }
  master_role=$(printf '%s\n' "$master_line" | awk -F'|' '{print $2}')
  master_ip=$(printf '%s\n' "$master_line" | awk -F'|' '{print ($3 == "" ? "-" : $3)}')
  labelled=$(printf '%s\n' "$pods" | awk -F'|' '$2 == "master" {print $1}' | tr '\n' ' ')

  # Demote first: the Service must never select two pods.
  printf '%s\n' "$pods" | while IFS='|' read -r pod role ip; do
    if [ -z "$pod" ] || [ "$pod" = "$master" ] || [ "$role" != "master" ]; then continue; fi
    if $KUBECTL label pod -n "$NAMESPACE" "$pod" redis-role=slave --overwrite >/dev/null; then
      log "label: $pod redis-role=slave (sentinel master is $master)"
    fi
  done
  if [ "$master_role" != "master" ]; then
    if $KUBECTL label pod -n "$NAMESPACE" "$master" redis-role=master --overwrite >/dev/null; then
      log "master change: $master is master behind $CR-master (labelled master before: ${labelled:-none})"
    fi
  fi

  # Replicas that still follow an address the master no longer has.
  printf '%s\n' "$pods" | while IFS='|' read -r pod role ip; do
    if [ -z "$pod" ] || [ "$pod" = "$master" ] || [ -z "$ip" ]; then continue; fi
    info=$(redis_cmd "$ip" 6379 "INFO replication")
    [ "$(info_field "$info" role)" = "slave" ] || continue
    following=$(info_field "$info" master_host)
    stale="$STALE_DIR/$pod"
    case "$(info_field "$info" master_link_status) $following" in
      "down $master".*|"down $master_ip"|up*)
        rm -f "$stale"
        continue ;;
    esac
    # Redis reports no down time for a link that never came up, so time it here.
    [ -f "$stale" ] || date +%s > "$stale"
    since=$(( $(date +%s) - $(cat "$stale") ))
    [ "$since" -ge "$REPAIR_AFTER" ] || continue
    target="$master.$CR-headless.$NAMESPACE.svc"
    if [ "$(redis_cmd "$ip" 6379 "REPLICAOF $target 6379" | head -n 1)" = "+OK" ]; then
      log "repair: $pod followed $following (link down for ${since}s), now replica of $target"
      rm -f "$stale"
    else
      log "repair: REPLICAOF $target on $pod failed"
    fi
  done

  last_state="ok:$master"
  sleep "$INTERVAL"
done
