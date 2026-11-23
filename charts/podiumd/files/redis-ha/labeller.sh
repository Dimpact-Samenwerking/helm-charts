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
# - While no quorum of sentinels agrees on a redis-ha pod (sentinels not
#   configured yet, partition, sentinels down) it only removes the master label
#   from pods that report role:slave themselves. masterReadinessCheck makes such
#   a pod NotReady, and the operator, which skips pods that are not Ready, would
#   leave the label, so a rollout could stall on it.
# - A replica that follows another address than the master for REPAIR_AFTER
#   seconds gets REPLICAOF the master. The operator links replicas by IP and
#   leaves relinking to Sentinel once Sentinel is on, so a master that restarted
#   before Sentinel knew it (the upgrade that turns Sentinel on) would keep its
#   replicas on its old IP; after a partition a replica can also stay linked to
#   an old master.
#
# Environment: NAMESPACE, APP (the pods' app label), CR (RedisReplication
# name), SENTINELS (number of sentinel pods), INTERVAL and REPAIR_AFTER
# (seconds), KUBECTL and STALE_DIR (only for tests), STATE_FILE (liveness:
# touched after every round that could list the pods).
set -u

# kubectl 1.37 in alpine/k8s ignores the in-cluster config when --request-timeout
# is given, so the calls are bounded with timeout(1) instead.
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

label() {
  timeout 5 "$KUBECTL" label pod -n "$NAMESPACE" "$1" "redis-role=$2" --overwrite >/dev/null
}

# name|role|ip, one pod per line; role is empty for a pod without the label.
list_pods() {
  timeout 5 "$KUBECTL" get pods -n "$NAMESPACE" -l "app=$APP,role=replication" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"|"}{.metadata.labels.redis-role}{"|"}{.status.podIP}{"\n"}{end}'
}

last_state=""
while true; do
  if ! pods=$(list_pods); then
    log "cannot list the redis-ha pods"
    sleep "$INTERVAL"
    continue
  fi
  # Only a round that reached the Kubernetes API counts for the liveness probe.
  touch "$STATE_FILE"
  master=$(quorum_master)
  if [ -z "$master" ]; then
    [ "$last_state" = "no-quorum" ] || log "no master agreed by $QUORUM of $SENTINELS sentinels; only replicas lose a master label"
    last_state="no-quorum"
    printf '%s\n' "$pods" | while IFS='|' read -r pod role ip; do
      if [ -z "$pod" ] || [ "$role" != "master" ] || [ -z "$ip" ]; then continue; fi
      [ "$(info_field "$(redis_cmd "$ip" 6379 "INFO replication")" role)" = "slave" ] || continue
      if label "$pod" slave; then
        log "label: $pod redis-role=slave (it reports role:slave)"
      fi
    done
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
    if label "$pod" slave; then
      log "label: $pod redis-role=slave (sentinel master is $master)"
    fi
  done
  if [ "$master_role" != "master" ]; then
    if label "$master" master; then
      log "master change: $master is master behind $CR-master (labelled master before: ${labelled:-none})"
    fi
  fi

  # Replicas that follow another address than the master. A timer file per pod
  # gives Sentinel REPAIR_AFTER seconds to reconfigure them itself; every pod that
  # is not such a replica in this pass loses its timer.
  printf '%s\n' "$pods" | while IFS='|' read -r pod role ip; do
    [ -n "$pod" ] || continue
    stale="$STALE_DIR/$pod"
    if [ "$pod" = "$master" ] || [ -z "$ip" ]; then
      rm -f "$stale"
      continue
    fi
    info=$(redis_cmd "$ip" 6379 "INFO replication")
    following=$(info_field "$info" master_host)
    if [ "$(info_field "$info" role)" != "slave" ]; then
      rm -f "$stale"
      continue
    fi
    case "$following" in
      "$master".*|"$master_ip")
        rm -f "$stale"
        continue ;;
    esac
    # Redis reports no down time for a link that never came up, so time it here.
    [ -f "$stale" ] || date +%s > "$stale"
    since=$(( $(date +%s) - $(cat "$stale") ))
    [ "$since" -ge "$REPAIR_AFTER" ] || continue
    target="$master.$CR-headless.$NAMESPACE.svc"
    if [ "$(redis_cmd "$ip" 6379 "REPLICAOF $target 6379" | head -n 1)" = "+OK" ]; then
      log "repair: $pod followed $following for ${since}s, now replica of $target"
      rm -f "$stale"
    else
      log "repair: REPLICAOF $target on $pod failed"
    fi
  done
  # Timers of pods that are gone.
  for stale in "$STALE_DIR"/*; do
    [ -e "$stale" ] || continue
    printf '%s\n' "$pods" | grep -q "^${stale##*/}|" || rm -f "$stale"
  done

  last_state="ok:$master"
  sleep "$INTERVAL"
done
