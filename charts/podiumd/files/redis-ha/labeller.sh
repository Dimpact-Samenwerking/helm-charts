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
# - Sentinel promotes a replica before it turns the old master into a replica,
#   and in between the old master still accepts writes, which are lost when it
#   becomes a replica (about 6 s after the operator's preStop failover). So the
#   labeller also listens on every sentinel: at
#   +failover-state-send-slaveof-noone, just before Sentinel promotes the
#   replica, it pauses writes on the old master (CLIENT PAUSE WRITE); at
#   +switch-master it moves the labels and fences the old master: CLIENT KILL of
#   the app connections, which reconnect through redis-ha-master to the new
#   master, then REPLICAOF the new master (what Sentinel itself does some seconds
#   later; REPLICAOF answers clients blocked in BRPOP with UNBLOCKED, which
#   Celery treats as fatal, so they are closed first), and CLIENT UNPAUSE (a long pause also blocks the sentinels' hello PUBLISH,
#   and they would call the pod down). Writes wait during the switch and fail on
#   the closed connection instead of vanishing. The old master is addressed by
#   its pod IP: a terminating pod (the preStop failover) has already lost its DNS
#   name in the headless Service. For events the listener missed,
#   the poll fences a pod that has reported role:master for REPAIR_AFTER seconds
#   while a quorum of sentinels names another, once. Right after a switch the
#   sentinels still disagree for a moment: the grace keeps the poll from fencing
#   the new master, and for REPAIR_AFTER seconds after a +switch-master the poll
#   does not move the labels back to the master a quorum still names.
# - A replica that follows another address than the master for REPAIR_AFTER
#   seconds gets REPLICAOF the master. The operator links replicas by IP and
#   leaves relinking to Sentinel once Sentinel is on, so a master that restarted
#   before Sentinel knew it (the upgrade that turns Sentinel on) would keep its
#   replicas on its old IP; after a partition a replica can also stay linked to
#   an old master.
#
# Environment: NAMESPACE, APP (the pods' app label), CR (RedisReplication
# name), SENTINELS (number of sentinel pods), INTERVAL and REPAIR_AFTER
# (seconds), PAUSE_MS (the write pause of a fenced master), KUBECTL, STALE_DIR
# and FENCE_DIR (only for tests), STATE_FILE (liveness: touched after every round that could
# list the pods).
set -u

# kubectl 1.37 in alpine/k8s ignores the in-cluster config when --request-timeout
# is given, so the calls are bounded with timeout(1) instead.
KUBECTL=${KUBECTL:-kubectl}
STATE_FILE=${STATE_FILE:-/tmp/alive}
STALE_DIR=${STALE_DIR:-/tmp/stale}
FENCE_DIR=${FENCE_DIR:-/tmp/fenced}
SWITCH_FILE=$FENCE_DIR/.switch
# The last pod list of the poll, for the listeners' IP lookup.
PODS_FILE=$FENCE_DIR/.pods
# Longer than a failover takes (sentinel.failoverTimeout is 10 s).
PAUSE_MS=${PAUSE_MS:-15000}
QUORUM=$((SENTINELS / 2 + 1))
mkdir -p "$STALE_DIR" "$FENCE_DIR"

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

# The address of a Redis pod named in a sentinel event ($1, a hostname): its
# pod IP from the last poll, else the hostname.
pod_address() {
  ip=$(grep "^${1%%.*}|" "$PODS_FILE" 2>/dev/null | awk -F'|' '{print $3}')
  echo "${ip:-$1}"
}

# Close the app connections (type normal) of former master $2 (address $1), so
# the apps reconnect through redis-ha-master, turn it into a replica of the
# master at address $3 and lift a write pause. $4 says why.
fence() {
  redis_cmd "$1" 6379 "CLIENT KILL TYPE normal" >/dev/null
  redis_cmd "$1" 6379 "REPLICAOF $3 6379" >/dev/null
  redis_cmd "$1" 6379 "CLIENT UNPAUSE" >/dev/null
  log "fence: $2 ($1) is now a replica of ${3%%.*}, its client connections closed ($4)"
}

# Follow the failovers that sentinel $1 publishes. Every sentinel publishes the
# switch, so the first one wins and the others repeat what is already done.
watch_switches() {
  while true; do
    { printf 'SUBSCRIBE +failover-state-send-slaveof-noone +switch-master\r\n'; sleep 3600; } |
      nc -w 300 "$CR-s-$1.$CR-s-hl" 26379 2>/dev/null | tr -d '\r' |
      while read -r kind f2 f3 f4 _ f6 f7 f8; do
        case "$kind" in
          # slave <name> <host> <port> @ mymaster <master host> <master port>
          slave)
            if [ "$f6" != "mymaster" ] || [ -z "$f8" ]; then continue; fi
            case "${f7%%.*}" in "$CR"-[0-9]*) ;; *) continue ;; esac
            old_addr=$(pod_address "$f7")
            redis_cmd "$old_addr" "$f8" "CLIENT PAUSE $PAUSE_MS WRITE" >/dev/null
            log "fence: ${f7%%.*} ($old_addr) paused for writes, sentinel $1 promotes ${f3%%.*}" ;;
          # mymaster <old host> <old port> <new host> <new port>
          mymaster)
            old=${f2%%.*}
            new=${f4%%.*}
            case "$old $new" in
              "$CR"-[0-9]*" $CR"-[0-9]*) ;;
              *) continue ;;
            esac
            echo "$(date +%s) $new" > "$SWITCH_FILE"
            if label "$old" slave && label "$new" master; then
              log "master change: $new is master behind $CR-master (+switch-master from $old on sentinel $1)"
            fi
            fence "$(pod_address "$f2")" "$old" "$f4" "+switch-master on sentinel $1" ;;
        esac
      done
    sleep 1
  done
}

i=0
while [ "$i" -lt "$SENTINELS" ]; do
  watch_switches "$i" &
  i=$((i + 1))
done

last_state=""
while true; do
  if ! pods=$(list_pods); then
    log "cannot list the redis-ha pods"
    sleep "$INTERVAL"
    continue
  fi
  # Only a round that reached the Kubernetes API counts for the liveness probe.
  touch "$STATE_FILE"
  printf '%s\n' "$pods" > "$PODS_FILE.new" && mv "$PODS_FILE.new" "$PODS_FILE"
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

  # The sentinels learn a switch some seconds apart; until then a quorum can
  # still name the old master.
  if [ -f "$SWITCH_FILE" ]; then
    read -r switched_at switched_to < "$SWITCH_FILE"
    if [ "$switched_to" != "$master" ] && [ $(( $(date +%s) - switched_at )) -lt "$REPAIR_AFTER" ]; then
      sleep "$INTERVAL"
      continue
    fi
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
      rm -f "$stale" "$FENCE_DIR/$pod" "$FENCE_DIR/$pod.done"
      continue
    fi
    info=$(redis_cmd "$ip" 6379 "INFO replication")
    following=$(info_field "$info" master_host)
    case "$(info_field "$info" role)" in
      slave) rm -f "$FENCE_DIR/$pod" "$FENCE_DIR/$pod.done" ;;
      master)
        rm -f "$stale"
        [ -f "$FENCE_DIR/$pod" ] || date +%s > "$FENCE_DIR/$pod"
        since=$(( $(date +%s) - $(cat "$FENCE_DIR/$pod") ))
        if [ "$since" -ge "$REPAIR_AFTER" ] && [ ! -f "$FENCE_DIR/$pod.done" ]; then
          touch "$FENCE_DIR/$pod.done"
          fence "$ip" "$pod" "$master.$CR-headless.$NAMESPACE.svc" "it reported role:master for ${since}s"
        fi
        continue ;;
      *)
        rm -f "$stale" "$FENCE_DIR/$pod" "$FENCE_DIR/$pod.done"
        continue ;;
    esac
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
  # Timers and fence markers of pods that are gone.
  for stale in "$STALE_DIR"/* "$FENCE_DIR"/*; do
    [ -e "$stale" ] || continue
    name=${stale##*/}
    printf '%s\n' "$pods" | grep -q "^${name%.done}|" || rm -f "$stale"
  done

  last_state="ok:$master"
  sleep "$INTERVAL"
done
