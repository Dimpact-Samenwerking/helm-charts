# loki

![Version: 6.25.1](https://img.shields.io/badge/Version-6.25.1-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 3.3.2](https://img.shields.io/badge/AppVersion-3.3.2-informational?style=flat-square)

Helm chart for Grafana Loki and Grafana Enterprise Logs supporting both simple, scalable and distributed modes.

**Homepage:** <https://grafana.github.io/helm-charts>

## Maintainers

| Name | Email | Url |
| ---- | ------ | --- |
| trevorwhitney |  |  |
| jeschkies |  |  |

## Source Code

* <https://github.com/grafana/loki>
* <https://grafana.com/oss/loki/>
* <https://grafana.com/docs/loki/latest/>

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| https://charts.min.io/ | minio(minio) | 5.4.0 |
| https://grafana.github.io/helm-charts | grafana-agent-operator(grafana-agent-operator) | 0.5.1 |
| https://grafana.github.io/helm-charts | rollout_operator(rollout-operator) | 0.23.0 |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| adminApi | object | `{"affinity":{},"annotations":{},"containerSecurityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true},"env":[],"extraArgs":{},"extraContainers":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"hostAliases":[],"initContainers":[],"labels":{},"nodeSelector":{},"podSecurityContext":{"runAsGroup":10001,"runAsNonRoot":true,"runAsUser":10001},"readinessProbe":{"httpGet":{"path":"/ready","port":"http-metrics"},"initialDelaySeconds":45},"replicas":1,"resources":{},"service":{"annotations":{},"labels":{}},"strategy":{"type":"RollingUpdate"},"terminationGracePeriodSeconds":60,"tolerations":[],"topologySpreadConstraints":[]}` | Configuration for the `admin-api` target |
| adminApi.affinity | object | `{}` | Affinity for admin-api Pods |
| adminApi.annotations | object | `{}` | Additional annotations for the `admin-api` Deployment |
| adminApi.env | list | `[]` | Configure optional environment variables |
| adminApi.extraArgs | object | `{}` | Additional CLI arguments for the `admin-api` target |
| adminApi.extraContainers | list | `[]` | Conifgure optional extraContainers |
| adminApi.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the admin-api pods |
| adminApi.extraVolumeMounts | list | `[]` | Additional volume mounts for Pods |
| adminApi.extraVolumes | list | `[]` | Additional volumes for Pods |
| adminApi.hostAliases | list | `[]` | hostAliases to add |
| adminApi.initContainers | list | `[]` | Configure optional initContainers |
| adminApi.labels | object | `{}` | Additional labels for the `admin-api` Deployment |
| adminApi.nodeSelector | object | `{}` | Node selector for admin-api Pods |
| adminApi.podSecurityContext | object | `{"runAsGroup":10001,"runAsNonRoot":true,"runAsUser":10001}` | Run container as user `enterprise-logs(uid=10001)` `fsGroup` must not be specified, because these security options are applied on container level not on Pod level. |
| adminApi.readinessProbe | object | `{"httpGet":{"path":"/ready","port":"http-metrics"},"initialDelaySeconds":45}` | Readiness probe |
| adminApi.replicas | int | `1` | Define the amount of instances |
| adminApi.resources | object | `{}` | Values are defined in small.yaml and large.yaml |
| adminApi.service | object | `{"annotations":{},"labels":{}}` | Additional labels and annotations for the `admin-api` Service |
| adminApi.strategy | object | `{"type":"RollingUpdate"}` | Update strategy |
| adminApi.terminationGracePeriodSeconds | int | `60` | Grace period to allow the admin-api to shutdown before it is killed |
| adminApi.tolerations | list | `[]` | Tolerations for admin-api Pods |
| adminApi.topologySpreadConstraints | list | `[]` | Topology Spread Constraints for admin-api pods |
| backend | object | `{"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"app.kubernetes.io/component":"backend"}},"topologyKey":"kubernetes.io/hostname"}]}},"annotations":{},"autoscaling":{"behavior":{},"enabled":false,"maxReplicas":6,"minReplicas":3,"targetCPUUtilizationPercentage":60,"targetMemoryUtilizationPercentage":null},"dnsConfig":{},"extraArgs":[],"extraEnv":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"image":{"registry":null,"repository":null,"tag":null},"initContainers":[],"nodeSelector":{},"persistence":{"annotations":{},"dataVolumeParameters":{"emptyDir":{}},"enableStatefulSetAutoDeletePVC":true,"selector":null,"size":"10Gi","storageClass":null,"volumeClaimsEnabled":true},"podAnnotations":{},"podLabels":{},"podManagementPolicy":"Parallel","priorityClassName":null,"replicas":3,"resources":{},"selectorLabels":{},"service":{"annotations":{},"labels":{}},"targetModule":"backend","terminationGracePeriodSeconds":300,"tolerations":[],"topologySpreadConstraints":[]}` | Configuration for the backend pod(s) |
| backend.affinity | object | Hard node anti-affinity | Affinity for backend pods. |
| backend.annotations | object | `{}` | Annotations for backend StatefulSet |
| backend.autoscaling.behavior | object | `{}` | Behavior policies while scaling. |
| backend.autoscaling.enabled | bool | `false` | Enable autoscaling for the backend. |
| backend.autoscaling.maxReplicas | int | `6` | Maximum autoscaling replicas for the backend. |
| backend.autoscaling.minReplicas | int | `3` | Minimum autoscaling replicas for the backend. |
| backend.autoscaling.targetCPUUtilizationPercentage | int | `60` | Target CPU utilization percentage for the backend. |
| backend.autoscaling.targetMemoryUtilizationPercentage | string | `nil` | Target memory utilization percentage for the backend. |
| backend.dnsConfig | object | `{}` | DNS config for backend pods |
| backend.extraArgs | list | `[]` | Additional CLI args for the backend |
| backend.extraEnv | list | `[]` | Environment variables to add to the backend pods |
| backend.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the backend pods |
| backend.extraVolumeMounts | list | `[]` | Volume mounts to add to the backend pods |
| backend.extraVolumes | list | `[]` | Volumes to add to the backend pods |
| backend.image.registry | string | `nil` | The Docker registry for the backend image. Overrides `loki.image.registry` |
| backend.image.repository | string | `nil` | Docker image repository for the backend image. Overrides `loki.image.repository` |
| backend.image.tag | string | `nil` | Docker image tag for the backend image. Overrides `loki.image.tag` |
| backend.initContainers | list | `[]` | Init containers to add to the backend pods |
| backend.nodeSelector | object | `{}` | Node selector for backend pods |
| backend.persistence.annotations | object | `{}` | Annotations for volume claim |
| backend.persistence.dataVolumeParameters | object | `{"emptyDir":{}}` | Parameters used for the `data` volume when volumeClaimEnabled if false |
| backend.persistence.enableStatefulSetAutoDeletePVC | bool | `true` | Enable StatefulSetAutoDeletePVC feature |
| backend.persistence.selector | string | `nil` | Selector for persistent disk |
| backend.persistence.size | string | `"10Gi"` | Size of persistent disk |
| backend.persistence.storageClass | string | `nil` | Storage class to be used. If defined, storageClassName: <storageClass>. If set to "-", storageClassName: "", which disables dynamic provisioning. If empty or set to null, no storageClassName spec is set, choosing the default provisioner (gp2 on AWS, standard on GKE, AWS, and OpenStack). |
| backend.persistence.volumeClaimsEnabled | bool | `true` | Enable volume claims in pod spec |
| backend.podAnnotations | object | `{}` | Annotations for backend pods |
| backend.podLabels | object | `{}` | Additional labels for each `backend` pod |
| backend.podManagementPolicy | string | `"Parallel"` | The default is to deploy all pods in parallel. |
| backend.priorityClassName | string | `nil` | The name of the PriorityClass for backend pods |
| backend.replicas | int | `3` | Number of replicas for the backend |
| backend.resources | object | `{}` | Resource requests and limits for the backend |
| backend.selectorLabels | object | `{}` | Additional selector labels for each `backend` pod |
| backend.service.annotations | object | `{}` | Annotations for backend Service |
| backend.service.labels | object | `{}` | Additional labels for backend Service |
| backend.targetModule | string | `"backend"` | Comma-separated list of Loki modules to load for the backend |
| backend.terminationGracePeriodSeconds | int | `300` | Grace period to allow the backend to shutdown before it is killed. Especially for the ingester, this must be increased. It must be long enough so backends can be gracefully shutdown flushing/transferring all data and to successfully leave the member ring on shutdown. |
| backend.tolerations | list | `[]` | Tolerations for backend pods |
| backend.topologySpreadConstraints | list | `[]` | Topology Spread Constraints for backend pods |
| bloomBuilder | object | `{"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"app.kubernetes.io/component":"bloom-builder"}},"topologyKey":"kubernetes.io/hostname"}]}},"appProtocol":{"grpc":""},"autoscaling":{"behavior":{"enabled":false,"scaleDown":{},"scaleUp":{}},"customMetrics":[],"enabled":false,"maxReplicas":3,"minReplicas":1,"targetCPUUtilizationPercentage":60,"targetMemoryUtilizationPercentage":null},"command":null,"extraArgs":[],"extraContainers":[],"extraEnv":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"hostAliases":[],"image":{"registry":null,"repository":null,"tag":null},"maxUnavailable":null,"nodeSelector":{},"podAnnotations":{},"podLabels":{},"priorityClassName":null,"replicas":0,"resources":{},"serviceAnnotations":{},"serviceLabels":{},"terminationGracePeriodSeconds":30,"tolerations":[]}` | Configuration for the bloom-builder |
| bloomBuilder.affinity | object | Hard node anti-affinity | Affinity for bloom-builder pods. |
| bloomBuilder.appProtocol | object | `{"grpc":""}` | Adds the appProtocol field to the queryFrontend service. This allows bloomBuilder to work with istio protocol selection. |
| bloomBuilder.appProtocol.grpc | string | `""` | Set the optional grpc service protocol. Ex: "grpc", "http2" or "https" |
| bloomBuilder.autoscaling.behavior.enabled | bool | `false` | Enable autoscaling behaviours |
| bloomBuilder.autoscaling.behavior.scaleDown | object | `{}` | define scale down policies, must conform to HPAScalingRules |
| bloomBuilder.autoscaling.behavior.scaleUp | object | `{}` | define scale up policies, must conform to HPAScalingRules |
| bloomBuilder.autoscaling.customMetrics | list | `[]` | Allows one to define custom metrics using the HPA/v2 schema (for example, Pods, Object or External metrics) |
| bloomBuilder.autoscaling.enabled | bool | `false` | Enable autoscaling for the bloom-builder |
| bloomBuilder.autoscaling.maxReplicas | int | `3` | Maximum autoscaling replicas for the bloom-builder |
| bloomBuilder.autoscaling.minReplicas | int | `1` | Minimum autoscaling replicas for the bloom-builder |
| bloomBuilder.autoscaling.targetCPUUtilizationPercentage | int | `60` | Target CPU utilisation percentage for the bloom-builder |
| bloomBuilder.autoscaling.targetMemoryUtilizationPercentage | string | `nil` | Target memory utilisation percentage for the bloom-builder |
| bloomBuilder.command | string | `nil` | Command to execute instead of defined in Docker image |
| bloomBuilder.extraArgs | list | `[]` | Additional CLI args for the bloom-builder |
| bloomBuilder.extraContainers | list | `[]` | Containers to add to the bloom-builder pods |
| bloomBuilder.extraEnv | list | `[]` | Environment variables to add to the bloom-builder pods |
| bloomBuilder.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the bloom-builder pods |
| bloomBuilder.extraVolumeMounts | list | `[]` | Volume mounts to add to the bloom-builder pods |
| bloomBuilder.extraVolumes | list | `[]` | Volumes to add to the bloom-builder pods |
| bloomBuilder.hostAliases | list | `[]` | hostAliases to add |
| bloomBuilder.image.registry | string | `nil` | The Docker registry for the bloom-builder image. Overrides `loki.image.registry` |
| bloomBuilder.image.repository | string | `nil` | Docker image repository for the bloom-builder image. Overrides `loki.image.repository` |
| bloomBuilder.image.tag | string | `nil` | Docker image tag for the bloom-builder image. Overrides `loki.image.tag` |
| bloomBuilder.maxUnavailable | string | `nil` | Pod Disruption Budget maxUnavailable |
| bloomBuilder.nodeSelector | object | `{}` | Node selector for bloom-builder pods |
| bloomBuilder.podAnnotations | object | `{}` | Annotations for bloom-builder pods |
| bloomBuilder.podLabels | object | `{}` | Labels for bloom-builder pods |
| bloomBuilder.priorityClassName | string | `nil` | The name of the PriorityClass for bloom-builder pods |
| bloomBuilder.replicas | int | `0` | Number of replicas for the bloom-builder |
| bloomBuilder.resources | object | `{}` | Resource requests and limits for the bloom-builder |
| bloomBuilder.serviceAnnotations | object | `{}` | Annotations for bloom-builder service |
| bloomBuilder.serviceLabels | object | `{}` | Labels for bloom-builder service |
| bloomBuilder.terminationGracePeriodSeconds | int | `30` | Grace period to allow the bloom-builder to shutdown before it is killed |
| bloomBuilder.tolerations | list | `[]` | Tolerations for bloom-builder pods |
| bloomGateway | object | `{"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"app.kubernetes.io/component":"bloom-gateway"}},"topologyKey":"kubernetes.io/hostname"}]}},"appProtocol":{"grpc":""},"command":null,"extraArgs":[],"extraContainers":[],"extraEnv":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"hostAliases":[],"image":{"registry":null,"repository":null,"tag":null},"initContainers":[],"livenessProbe":{},"nodeSelector":{},"persistence":{"annotations":{},"claims":[{"name":"data","size":"10Gi","storageClass":null}],"enableStatefulSetAutoDeletePVC":false,"enabled":false,"whenDeleted":"Retain","whenScaled":"Retain"},"podAnnotations":{},"podLabels":{},"priorityClassName":null,"readinessProbe":{},"replicas":0,"resources":{},"serviceAccount":{"annotations":{},"automountServiceAccountToken":true,"create":false,"imagePullSecrets":[],"name":null},"serviceAnnotations":{},"serviceLabels":{},"terminationGracePeriodSeconds":30,"tolerations":[]}` | Configuration for the bloom-gateway |
| bloomGateway.affinity | object | Hard node anti-affinity | Affinity for bloom-gateway pods. |
| bloomGateway.appProtocol | object | `{"grpc":""}` | Set the optional grpc service protocol. Ex: "grpc", "http2" or "https" |
| bloomGateway.command | string | `nil` | Command to execute instead of defined in Docker image |
| bloomGateway.extraArgs | list | `[]` | Additional CLI args for the bloom-gateway |
| bloomGateway.extraContainers | list | `[]` | Containers to add to the bloom-gateway pods |
| bloomGateway.extraEnv | list | `[]` | Environment variables to add to the bloom-gateway pods |
| bloomGateway.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the bloom-gateway pods |
| bloomGateway.extraVolumeMounts | list | `[]` | Volume mounts to add to the bloom-gateway pods |
| bloomGateway.extraVolumes | list | `[]` | Volumes to add to the bloom-gateway pods |
| bloomGateway.hostAliases | list | `[]` | hostAliases to add |
| bloomGateway.image.registry | string | `nil` | The Docker registry for the bloom-gateway image. Overrides `loki.image.registry` |
| bloomGateway.image.repository | string | `nil` | Docker image repository for the bloom-gateway image. Overrides `loki.image.repository` |
| bloomGateway.image.tag | string | `nil` | Docker image tag for the bloom-gateway image. Overrides `loki.image.tag` |
| bloomGateway.initContainers | list | `[]` | Init containers to add to the bloom-gateway pods |
| bloomGateway.livenessProbe | object | `{}` | liveness probe settings for ingester pods. If empty use `loki.livenessProbe` |
| bloomGateway.nodeSelector | object | `{}` | Node selector for bloom-gateway pods |
| bloomGateway.persistence.annotations | object | `{}` | Annotations for bloom-gateway PVCs |
| bloomGateway.persistence.claims | list |  | List of the bloom-gateway PVCs |
| bloomGateway.persistence.claims[0].size | string | `"10Gi"` | Size of persistent disk |
| bloomGateway.persistence.enableStatefulSetAutoDeletePVC | bool | `false` | Enable StatefulSetAutoDeletePVC feature |
| bloomGateway.persistence.enabled | bool | `false` | Enable creating PVCs for the bloom-gateway |
| bloomGateway.podAnnotations | object | `{}` | Annotations for bloom-gateway pods |
| bloomGateway.podLabels | object | `{}` | Labels for bloom-gateway pods |
| bloomGateway.priorityClassName | string | `nil` | The name of the PriorityClass for bloom-gateway pods |
| bloomGateway.readinessProbe | object | `{}` | readiness probe settings for ingester pods. If empty, use `loki.readinessProbe` |
| bloomGateway.replicas | int | `0` | Number of replicas for the bloom-gateway |
| bloomGateway.resources | object | `{}` | Resource requests and limits for the bloom-gateway |
| bloomGateway.serviceAccount.annotations | object | `{}` | Annotations for the bloom-gateway service account |
| bloomGateway.serviceAccount.automountServiceAccountToken | bool | `true` | Set this toggle to false to opt out of automounting API credentials for the service account |
| bloomGateway.serviceAccount.imagePullSecrets | list | `[]` | Image pull secrets for the bloom-gateway service account |
| bloomGateway.serviceAccount.name | string | `nil` | The name of the ServiceAccount to use for the bloom-gateway. If not set and create is true, a name is generated by appending "-bloom-gateway" to the common ServiceAccount. |
| bloomGateway.serviceAnnotations | object | `{}` | Annotations for bloom-gateway service |
| bloomGateway.serviceLabels | object | `{}` | Labels for bloom-gateway service |
| bloomGateway.terminationGracePeriodSeconds | int | `30` | Grace period to allow the bloom-gateway to shutdown before it is killed |
| bloomGateway.tolerations | list | `[]` | Tolerations for bloom-gateway pods |
| bloomPlanner | object | `{"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"app.kubernetes.io/component":"bloom-planner"}},"topologyKey":"kubernetes.io/hostname"}]}},"appProtocol":{"grpc":""},"command":null,"extraArgs":[],"extraContainers":[],"extraEnv":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"hostAliases":[],"image":{"registry":null,"repository":null,"tag":null},"initContainers":[],"livenessProbe":{},"nodeSelector":{},"persistence":{"annotations":{},"claims":[{"name":"data","size":"10Gi","storageClass":null}],"enableStatefulSetAutoDeletePVC":false,"enabled":false,"whenDeleted":"Retain","whenScaled":"Retain"},"podAnnotations":{},"podLabels":{},"priorityClassName":null,"readinessProbe":{},"replicas":0,"resources":{},"serviceAccount":{"annotations":{},"automountServiceAccountToken":true,"create":false,"imagePullSecrets":[],"name":null},"serviceAnnotations":{},"serviceLabels":{},"terminationGracePeriodSeconds":30,"tolerations":[]}` | Configuration for the bloom-planner |
| bloomPlanner.affinity | object | Hard node anti-affinity | Affinity for bloom-planner pods. |
| bloomPlanner.appProtocol | object | `{"grpc":""}` | Set the optional grpc service protocol. Ex: "grpc", "http2" or "https" |
| bloomPlanner.command | string | `nil` | Command to execute instead of defined in Docker image |
| bloomPlanner.extraArgs | list | `[]` | Additional CLI args for the bloom-planner |
| bloomPlanner.extraContainers | list | `[]` | Containers to add to the bloom-planner pods |
| bloomPlanner.extraEnv | list | `[]` | Environment variables to add to the bloom-planner pods |
| bloomPlanner.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the bloom-planner pods |
| bloomPlanner.extraVolumeMounts | list | `[]` | Volume mounts to add to the bloom-planner pods |
| bloomPlanner.extraVolumes | list | `[]` | Volumes to add to the bloom-planner pods |
| bloomPlanner.hostAliases | list | `[]` | hostAliases to add |
| bloomPlanner.image.registry | string | `nil` | The Docker registry for the bloom-planner image. Overrides `loki.image.registry` |
| bloomPlanner.image.repository | string | `nil` | Docker image repository for the bloom-planner image. Overrides `loki.image.repository` |
| bloomPlanner.image.tag | string | `nil` | Docker image tag for the bloom-planner image. Overrides `loki.image.tag` |
| bloomPlanner.initContainers | list | `[]` | Init containers to add to the bloom-planner pods |
| bloomPlanner.livenessProbe | object | `{}` | liveness probe settings for ingester pods. If empty use `loki.livenessProbe` |
| bloomPlanner.nodeSelector | object | `{}` | Node selector for bloom-planner pods |
| bloomPlanner.persistence.annotations | object | `{}` | Annotations for bloom-planner PVCs |
| bloomPlanner.persistence.claims | list |  | List of the bloom-planner PVCs |
| bloomPlanner.persistence.claims[0].size | string | `"10Gi"` | Size of persistent disk |
| bloomPlanner.persistence.enableStatefulSetAutoDeletePVC | bool | `false` | Enable StatefulSetAutoDeletePVC feature |
| bloomPlanner.persistence.enabled | bool | `false` | Enable creating PVCs for the bloom-planner |
| bloomPlanner.podAnnotations | object | `{}` | Annotations for bloom-planner pods |
| bloomPlanner.podLabels | object | `{}` | Labels for bloom-planner pods |
| bloomPlanner.priorityClassName | string | `nil` | The name of the PriorityClass for bloom-planner pods |
| bloomPlanner.readinessProbe | object | `{}` | readiness probe settings for ingester pods. If empty, use `loki.readinessProbe` |
| bloomPlanner.replicas | int | `0` | Number of replicas for the bloom-planner |
| bloomPlanner.resources | object | `{}` | Resource requests and limits for the bloom-planner |
| bloomPlanner.serviceAccount.annotations | object | `{}` | Annotations for the bloom-planner service account |
| bloomPlanner.serviceAccount.automountServiceAccountToken | bool | `true` | Set this toggle to false to opt out of automounting API credentials for the service account |
| bloomPlanner.serviceAccount.imagePullSecrets | list | `[]` | Image pull secrets for the bloom-planner service account |
| bloomPlanner.serviceAccount.name | string | `nil` | The name of the ServiceAccount to use for the bloom-planner. If not set and create is true, a name is generated by appending "-bloom-planner" to the common ServiceAccount. |
| bloomPlanner.serviceAnnotations | object | `{}` | Annotations for bloom-planner service |
| bloomPlanner.serviceLabels | object | `{}` | Labels for bloom-planner service |
| bloomPlanner.terminationGracePeriodSeconds | int | `30` | Grace period to allow the bloom-planner to shutdown before it is killed |
| bloomPlanner.tolerations | list | `[]` | Tolerations for bloom-planner pods |
| chunksCache.affinity | object | `{}` | Affinity for chunks-cache pods |
| chunksCache.allocatedMemory | int | `8192` | Amount of memory allocated to chunks-cache for object storage (in MB). |
| chunksCache.annotations | object | `{}` | Annotations for the chunks-cache pods |
| chunksCache.batchSize | int | `4` | Batchsize for sending and receiving chunks from chunks cache |
| chunksCache.connectionLimit | int | `16384` | Maximum number of connections allowed |
| chunksCache.defaultValidity | string | `"0s"` | Specify how long cached chunks should be stored in the chunks-cache before being expired |
| chunksCache.enabled | bool | `true` | Specifies whether memcached based chunks-cache should be enabled |
| chunksCache.extraArgs | object | `{}` | Additional CLI args for chunks-cache |
| chunksCache.extraContainers | list | `[]` | Additional containers to be added to the chunks-cache pod. |
| chunksCache.extraExtendedOptions | string | `""` | Add extended options for chunks-cache memcached container. The format is the same as for the memcached -o/--extend flag. Example: extraExtendedOptions: 'tls,no_hashexpand' |
| chunksCache.extraVolumeMounts | list | `[]` | Additional volume mounts to be added to the chunks-cache pod (applies to both memcached and exporter containers). Example: extraVolumeMounts: - name: extra-volume   mountPath: /etc/extra-volume   readOnly: true |
| chunksCache.extraVolumes | list | `[]` | Additional volumes to be added to the chunks-cache pod (applies to both memcached and exporter containers). Example: extraVolumes: - name: extra-volume   secret:    secretName: extra-volume-secret |
| chunksCache.initContainers | list | `[]` | Extra init containers for chunks-cache pods |
| chunksCache.maxItemMemory | int | `5` | Maximum item memory for chunks-cache (in MB). |
| chunksCache.nodeSelector | object | `{}` | Node selector for chunks-cache pods |
| chunksCache.parallelism | int | `5` | Parallel threads for sending and receiving chunks from chunks cache |
| chunksCache.persistence | object | `{"enabled":false,"mountPath":"/data","storageClass":null,"storageSize":"10G"}` | Persistence settings for the chunks-cache |
| chunksCache.persistence.enabled | bool | `false` | Enable creating PVCs for the chunks-cache |
| chunksCache.persistence.mountPath | string | `"/data"` | Volume mount path |
| chunksCache.persistence.storageClass | string | `nil` | Storage class to be used. If defined, storageClassName: <storageClass>. If set to "-", storageClassName: "", which disables dynamic provisioning. If empty or set to null, no storageClassName spec is set, choosing the default provisioner (gp2 on AWS, standard on GKE, AWS, and OpenStack). |
| chunksCache.persistence.storageSize | string | `"10G"` | Size of persistent disk, must be in G or Gi |
| chunksCache.podAnnotations | object | `{}` | Annotations for chunks-cache pods |
| chunksCache.podDisruptionBudget | object | `{"maxUnavailable":1}` | Pod Disruption Budget |
| chunksCache.podLabels | object | `{}` | Labels for chunks-cache pods |
| chunksCache.podManagementPolicy | string | `"Parallel"` | Management policy for chunks-cache pods |
| chunksCache.port | int | `11211` | Port of the chunks-cache service |
| chunksCache.priorityClassName | string | `nil` | The name of the PriorityClass for chunks-cache pods |
| chunksCache.replicas | int | `1` | Total number of chunks-cache replicas |
| chunksCache.resources | string | `nil` | Resource requests and limits for the chunks-cache By default a safe memory limit will be requested based on allocatedMemory value (floor (* 1.2 allocatedMemory)). |
| chunksCache.service | object | `{"annotations":{},"labels":{}}` | Service annotations and labels |
| chunksCache.statefulStrategy | object | `{"type":"RollingUpdate"}` | Stateful chunks-cache strategy |
| chunksCache.terminationGracePeriodSeconds | int | `60` | Grace period to allow the chunks-cache to shutdown before it is killed |
| chunksCache.timeout | string | `"2000ms"` | Memcached operation timeout |
| chunksCache.tolerations | list | `[]` | Tolerations for chunks-cache pods |
| chunksCache.topologySpreadConstraints | list | `[]` | topologySpreadConstraints allows to customize the default topologySpreadConstraints. This can be either a single dict as shown below or a slice of topologySpreadConstraints. labelSelector is taken from the constraint itself (if it exists) or is generated by the chart using the same selectors as for services. |
| chunksCache.writebackBuffer | int | `500000` | Max number of objects to use for cache write back |
| chunksCache.writebackParallelism | int | `1` | Number of parallel threads for cache write back |
| chunksCache.writebackSizeLimit | string | `"500MB"` | Max memory to use for cache write back |
| clusterLabelOverride | string | `nil` | Overrides the chart's cluster label |
| compactor | object | `{"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"app.kubernetes.io/component":"compactor"}},"topologyKey":"kubernetes.io/hostname"}]}},"appProtocol":{"grpc":""},"command":null,"extraArgs":[],"extraContainers":[],"extraEnv":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"hostAliases":[],"image":{"registry":null,"repository":null,"tag":null},"initContainers":[],"livenessProbe":{},"nodeSelector":{},"persistence":{"annotations":{},"claims":[{"name":"data","size":"10Gi","storageClass":null}],"enableStatefulSetAutoDeletePVC":false,"enabled":false,"size":"10Gi","storageClass":null,"whenDeleted":"Retain","whenScaled":"Retain"},"podAnnotations":{},"podLabels":{},"priorityClassName":null,"readinessProbe":{},"replicas":0,"resources":{},"serviceAccount":{"annotations":{},"automountServiceAccountToken":true,"create":false,"imagePullSecrets":[],"name":null},"serviceAnnotations":{},"serviceLabels":{},"terminationGracePeriodSeconds":30,"tolerations":[]}` | Configuration for the compactor |
| compactor.affinity | object | Hard node anti-affinity | Affinity for compactor pods. |
| compactor.appProtocol | object | `{"grpc":""}` | Set the optional grpc service protocol. Ex: "grpc", "http2" or "https" |
| compactor.command | string | `nil` | Command to execute instead of defined in Docker image |
| compactor.extraArgs | list | `[]` | Additional CLI args for the compactor |
| compactor.extraContainers | list | `[]` | Containers to add to the compactor pods |
| compactor.extraEnv | list | `[]` | Environment variables to add to the compactor pods |
| compactor.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the compactor pods |
| compactor.extraVolumeMounts | list | `[]` | Volume mounts to add to the compactor pods |
| compactor.extraVolumes | list | `[]` | Volumes to add to the compactor pods |
| compactor.hostAliases | list | `[]` | hostAliases to add |
| compactor.image.registry | string | `nil` | The Docker registry for the compactor image. Overrides `loki.image.registry` |
| compactor.image.repository | string | `nil` | Docker image repository for the compactor image. Overrides `loki.image.repository` |
| compactor.image.tag | string | `nil` | Docker image tag for the compactor image. Overrides `loki.image.tag` |
| compactor.initContainers | list | `[]` | Init containers to add to the compactor pods |
| compactor.livenessProbe | object | `{}` | liveness probe settings for ingester pods. If empty use `loki.livenessProbe` |
| compactor.nodeSelector | object | `{}` | Node selector for compactor pods |
| compactor.persistence.annotations | object | `{}` | Annotations for compactor PVCs |
| compactor.persistence.claims | list |  | List of the compactor PVCs |
| compactor.persistence.enableStatefulSetAutoDeletePVC | bool | `false` | Enable StatefulSetAutoDeletePVC feature |
| compactor.persistence.enabled | bool | `false` | Enable creating PVCs for the compactor |
| compactor.persistence.size | string | `"10Gi"` | Size of persistent disk |
| compactor.persistence.storageClass | string | `nil` | Storage class to be used. If defined, storageClassName: <storageClass>. If set to "-", storageClassName: "", which disables dynamic provisioning. If empty or set to null, no storageClassName spec is set, choosing the default provisioner (gp2 on AWS, standard on GKE, AWS, and OpenStack). |
| compactor.podAnnotations | object | `{}` | Annotations for compactor pods |
| compactor.podLabels | object | `{}` | Labels for compactor pods |
| compactor.priorityClassName | string | `nil` | The name of the PriorityClass for compactor pods |
| compactor.readinessProbe | object | `{}` | readiness probe settings for ingester pods. If empty, use `loki.readinessProbe` |
| compactor.replicas | int | `0` | Number of replicas for the compactor |
| compactor.resources | object | `{}` | Resource requests and limits for the compactor |
| compactor.serviceAccount.annotations | object | `{}` | Annotations for the compactor service account |
| compactor.serviceAccount.automountServiceAccountToken | bool | `true` | Set this toggle to false to opt out of automounting API credentials for the service account |
| compactor.serviceAccount.imagePullSecrets | list | `[]` | Image pull secrets for the compactor service account |
| compactor.serviceAccount.name | string | `nil` | The name of the ServiceAccount to use for the compactor. If not set and create is true, a name is generated by appending "-compactor" to the common ServiceAccount. |
| compactor.serviceAnnotations | object | `{}` | Annotations for compactor service |
| compactor.serviceLabels | object | `{}` | Labels for compactor service |
| compactor.terminationGracePeriodSeconds | int | `30` | Grace period to allow the compactor to shutdown before it is killed |
| compactor.tolerations | list | `[]` | Tolerations for compactor pods |
| deploymentMode | string | `"SimpleScalable"` | Deployment mode lets you specify how to deploy Loki. There are 3 options: - SingleBinary: Loki is deployed as a single binary, useful for small installs typically without HA, up to a few tens of GB/day. - SimpleScalable: Loki is deployed as 3 targets: read, write, and backend. Useful for medium installs easier to manage than distributed, up to a about 1TB/day. - Distributed: Loki is deployed as individual microservices. The most complicated but most capable, useful for large installs, typically over 1TB/day. There are also 2 additional modes used for migrating between deployment modes: - SingleBinary<->SimpleScalable: Migrate from SingleBinary to SimpleScalable (or vice versa) - SimpleScalable<->Distributed: Migrate from SimpleScalable to Distributed (or vice versa) Note: SimpleScalable and Distributed REQUIRE the use of object storage. |
| distributor | object | `{"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"app.kubernetes.io/component":"distributor"}},"topologyKey":"kubernetes.io/hostname"}]}},"appProtocol":{"grpc":""},"autoscaling":{"behavior":{"enabled":false,"scaleDown":{},"scaleUp":{}},"customMetrics":[],"enabled":false,"maxReplicas":3,"minReplicas":1,"targetCPUUtilizationPercentage":60,"targetMemoryUtilizationPercentage":null},"command":null,"extraArgs":[],"extraContainers":[],"extraEnv":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"hostAliases":[],"image":{"registry":null,"repository":null,"tag":null},"maxSurge":0,"maxUnavailable":null,"nodeSelector":{},"podAnnotations":{},"podLabels":{},"priorityClassName":null,"replicas":0,"resources":{},"serviceAnnotations":{},"serviceLabels":{},"terminationGracePeriodSeconds":30,"tolerations":[],"topologySpreadConstraints":[]}` | Configuration for the distributor |
| distributor.affinity | object | Hard node anti-affinity | Affinity for distributor pods. |
| distributor.appProtocol | object | `{"grpc":""}` | Adds the appProtocol field to the distributor service. This allows distributor to work with istio protocol selection. |
| distributor.appProtocol.grpc | string | `""` | Set the optional grpc service protocol. Ex: "grpc", "http2" or "https" |
| distributor.autoscaling.behavior.enabled | bool | `false` | Enable autoscaling behaviours |
| distributor.autoscaling.behavior.scaleDown | object | `{}` | define scale down policies, must conform to HPAScalingRules |
| distributor.autoscaling.behavior.scaleUp | object | `{}` | define scale up policies, must conform to HPAScalingRules |
| distributor.autoscaling.customMetrics | list | `[]` | Allows one to define custom metrics using the HPA/v2 schema (for example, Pods, Object or External metrics) |
| distributor.autoscaling.enabled | bool | `false` | Enable autoscaling for the distributor |
| distributor.autoscaling.maxReplicas | int | `3` | Maximum autoscaling replicas for the distributor |
| distributor.autoscaling.minReplicas | int | `1` | Minimum autoscaling replicas for the distributor |
| distributor.autoscaling.targetCPUUtilizationPercentage | int | `60` | Target CPU utilisation percentage for the distributor |
| distributor.autoscaling.targetMemoryUtilizationPercentage | string | `nil` | Target memory utilisation percentage for the distributor |
| distributor.command | string | `nil` | Command to execute instead of defined in Docker image |
| distributor.extraArgs | list | `[]` | Additional CLI args for the distributor |
| distributor.extraContainers | list | `[]` | Containers to add to the distributor pods |
| distributor.extraEnv | list | `[]` | Environment variables to add to the distributor pods |
| distributor.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the distributor pods |
| distributor.extraVolumeMounts | list | `[]` | Volume mounts to add to the distributor pods |
| distributor.extraVolumes | list | `[]` | Volumes to add to the distributor pods |
| distributor.hostAliases | list | `[]` | hostAliases to add |
| distributor.image.registry | string | `nil` | The Docker registry for the distributor image. Overrides `loki.image.registry` |
| distributor.image.repository | string | `nil` | Docker image repository for the distributor image. Overrides `loki.image.repository` |
| distributor.image.tag | string | `nil` | Docker image tag for the distributor image. Overrides `loki.image.tag` |
| distributor.maxSurge | int | `0` | Max Surge for distributor pods |
| distributor.maxUnavailable | string | `nil` | Pod Disruption Budget maxUnavailable |
| distributor.nodeSelector | object | `{}` | Node selector for distributor pods |
| distributor.podAnnotations | object | `{}` | Annotations for distributor pods |
| distributor.podLabels | object | `{}` | Labels for distributor pods |
| distributor.priorityClassName | string | `nil` | The name of the PriorityClass for distributor pods |
| distributor.replicas | int | `0` | Number of replicas for the distributor |
| distributor.resources | object | `{}` | Resource requests and limits for the distributor |
| distributor.serviceAnnotations | object | `{}` | Annotations for distributor service |
| distributor.serviceLabels | object | `{}` | Labels for distributor service |
| distributor.terminationGracePeriodSeconds | int | `30` | Grace period to allow the distributor to shutdown before it is killed |
| distributor.tolerations | list | `[]` | Tolerations for distributor pods |
| distributor.topologySpreadConstraints | list | `[]` | Topology Spread Constraints for distributor pods |
| enterprise | object | `{"adminApi":{"enabled":true},"adminToken":{"additionalNamespaces":[],"secret":null},"canarySecret":null,"cluster_name":null,"config":"{{- if .Values.enterprise.adminApi.enabled }}\nadmin_client:\n  {{ include \"enterprise-logs.adminAPIStorageConfig\" . | nindent 2 }}\n{{ end }}\nauth:\n  type: {{ .Values.enterprise.adminApi.enabled | ternary \"enterprise\" \"trust\" }}\nauth_enabled: {{ .Values.loki.auth_enabled }}\ncluster_name: {{ include \"loki.clusterName\" . }}\nlicense:\n  path: /etc/loki/license/license.jwt\n","enabled":false,"externalConfigName":"","externalLicenseName":null,"gelGateway":true,"image":{"digest":null,"pullPolicy":"IfNotPresent","registry":"docker.io","repository":"grafana/enterprise-logs","tag":"3.3.0"},"license":{"contents":"NOTAVALIDLICENSE"},"provisioner":{"additionalTenants":[],"affinity":{},"annotations":{},"enabled":true,"env":[],"extraVolumeMounts":[],"image":{"digest":null,"pullPolicy":"IfNotPresent","registry":"docker.io","repository":"grafana/enterprise-logs-provisioner","tag":null},"labels":{},"nodeSelector":{},"priorityClassName":null,"provisionedSecretPrefix":null,"securityContext":{"fsGroup":10001,"runAsGroup":10001,"runAsNonRoot":true,"runAsUser":10001},"tolerations":[]},"tokengen":{"affinity":{},"annotations":{},"enabled":true,"env":[],"extraArgs":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"labels":{},"nodeSelector":{},"priorityClassName":"","securityContext":{"fsGroup":10001,"runAsGroup":10001,"runAsNonRoot":true,"runAsUser":10001},"targetModule":"tokengen","tolerations":[]},"useExternalLicense":false,"version":"3.1.1"}` | Configuration for running Enterprise Loki |
| enterprise.adminApi | object | `{"enabled":true}` | If enabled, the correct admin_client storage will be configured. If disabled while running enterprise, make sure auth is set to `type: trust`, or that `auth_enabled` is set to `false`. |
| enterprise.adminToken.additionalNamespaces | list | `[]` | Additional namespace to also create the token in. Useful if your Grafana instance is in a different namespace |
| enterprise.adminToken.secret | string | `nil` | Alternative name for admin token secret, needed by tokengen and provisioner jobs |
| enterprise.canarySecret | string | `nil` | Alternative name of the secret to store token for the canary |
| enterprise.cluster_name | string | `nil` | Optional name of the GEL cluster, otherwise will use .Release.Name The cluster name must match what is in your GEL license |
| enterprise.externalConfigName | string | `""` | Name of the external config secret to use |
| enterprise.externalLicenseName | string | `nil` | Name of external license secret to use |
| enterprise.gelGateway | bool | `true` | Use GEL gateway, if false will use the default nginx gateway |
| enterprise.image.digest | string | `nil` | Overrides the image tag with an image digest |
| enterprise.image.pullPolicy | string | `"IfNotPresent"` | Docker image pull policy |
| enterprise.image.registry | string | `"docker.io"` | The Docker registry |
| enterprise.image.repository | string | `"grafana/enterprise-logs"` | Docker image repository |
| enterprise.image.tag | string | `"3.3.0"` | Docker image tag |
| enterprise.license | object | `{"contents":"NOTAVALIDLICENSE"}` | Grafana Enterprise Logs license In order to use Grafana Enterprise Logs features, you will need to provide the contents of your Grafana Enterprise Logs license, either by providing the contents of the license.jwt, or the name Kubernetes Secret that contains your license.jwt. To set the license contents, use the flag `--set-file 'enterprise.license.contents=./license.jwt'` |
| enterprise.provisioner | object | `{"additionalTenants":[],"affinity":{},"annotations":{},"enabled":true,"env":[],"extraVolumeMounts":[],"image":{"digest":null,"pullPolicy":"IfNotPresent","registry":"docker.io","repository":"grafana/enterprise-logs-provisioner","tag":null},"labels":{},"nodeSelector":{},"priorityClassName":null,"provisionedSecretPrefix":null,"securityContext":{"fsGroup":10001,"runAsGroup":10001,"runAsNonRoot":true,"runAsUser":10001},"tolerations":[]}` | Configuration for `provisioner` target |
| enterprise.provisioner.additionalTenants | list | `[]` | Additional tenants to be created. Each tenant will get a read and write policy and associated token. Tenant must have a name and a namespace for the secret containting the token to be created in. For example additionalTenants:   - name: loki     secretNamespace: grafana |
| enterprise.provisioner.affinity | object | `{}` | Affinity for tokengen Pods |
| enterprise.provisioner.annotations | object | `{}` | Additional annotations for the `provisioner` Job |
| enterprise.provisioner.enabled | bool | `true` | Whether the job should be part of the deployment |
| enterprise.provisioner.env | list | `[]` | Additional Kubernetes environment |
| enterprise.provisioner.extraVolumeMounts | list | `[]` | Volume mounts to add to the provisioner pods |
| enterprise.provisioner.image | object | `{"digest":null,"pullPolicy":"IfNotPresent","registry":"docker.io","repository":"grafana/enterprise-logs-provisioner","tag":null}` | Provisioner image to Utilize |
| enterprise.provisioner.image.digest | string | `nil` | Overrides the image tag with an image digest |
| enterprise.provisioner.image.pullPolicy | string | `"IfNotPresent"` | Docker image pull policy |
| enterprise.provisioner.image.registry | string | `"docker.io"` | The Docker registry |
| enterprise.provisioner.image.repository | string | `"grafana/enterprise-logs-provisioner"` | Docker image repository |
| enterprise.provisioner.image.tag | string | `nil` | Overrides the image tag whose default is the chart's appVersion |
| enterprise.provisioner.labels | object | `{}` | Additional labels for the `provisioner` Job |
| enterprise.provisioner.nodeSelector | object | `{}` | Node selector for tokengen Pods |
| enterprise.provisioner.priorityClassName | string | `nil` | The name of the PriorityClass for provisioner Job |
| enterprise.provisioner.provisionedSecretPrefix | string | `nil` | Name of the secret to store provisioned tokens in |
| enterprise.provisioner.securityContext | object | `{"fsGroup":10001,"runAsGroup":10001,"runAsNonRoot":true,"runAsUser":10001}` | Run containers as user `enterprise-logs(uid=10001)` |
| enterprise.provisioner.tolerations | list | `[]` | Tolerations for tokengen Pods |
| enterprise.tokengen | object | `{"affinity":{},"annotations":{},"enabled":true,"env":[],"extraArgs":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"labels":{},"nodeSelector":{},"priorityClassName":"","securityContext":{"fsGroup":10001,"runAsGroup":10001,"runAsNonRoot":true,"runAsUser":10001},"targetModule":"tokengen","tolerations":[]}` | Configuration for `tokengen` target |
| enterprise.tokengen.affinity | object | `{}` | Affinity for tokengen Pods |
| enterprise.tokengen.annotations | object | `{}` | Additional annotations for the `tokengen` Job |
| enterprise.tokengen.enabled | bool | `true` | Whether the job should be part of the deployment |
| enterprise.tokengen.env | list | `[]` | Additional Kubernetes environment |
| enterprise.tokengen.extraArgs | list | `[]` | Additional CLI arguments for the `tokengen` target |
| enterprise.tokengen.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the tokengen pods |
| enterprise.tokengen.extraVolumeMounts | list | `[]` | Additional volume mounts for Pods |
| enterprise.tokengen.extraVolumes | list | `[]` | Additional volumes for Pods |
| enterprise.tokengen.labels | object | `{}` | Additional labels for the `tokengen` Job |
| enterprise.tokengen.nodeSelector | object | `{}` | Node selector for tokengen Pods |
| enterprise.tokengen.priorityClassName | string | `""` | The name of the PriorityClass for tokengen Pods |
| enterprise.tokengen.securityContext | object | `{"fsGroup":10001,"runAsGroup":10001,"runAsNonRoot":true,"runAsUser":10001}` | Run containers as user `enterprise-logs(uid=10001)` |
| enterprise.tokengen.targetModule | string | `"tokengen"` | Comma-separated list of Loki modules to load for tokengen |
| enterprise.tokengen.tolerations | list | `[]` | Tolerations for tokengen Job |
| enterprise.useExternalLicense | bool | `false` | Set to true when providing an external license |
| enterpriseGateway | object | `{"affinity":{},"annotations":{},"containerSecurityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true},"env":[],"extraArgs":{},"extraContainers":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"hostAliases":[],"initContainers":[],"labels":{},"nodeSelector":{},"podSecurityContext":{"fsGroup":10001,"runAsGroup":10001,"runAsNonRoot":true,"runAsUser":10001},"readinessProbe":{"httpGet":{"path":"/ready","port":"http-metrics"},"initialDelaySeconds":45},"replicas":1,"resources":{},"service":{"annotations":{},"labels":{},"type":"ClusterIP"},"strategy":{"type":"RollingUpdate"},"terminationGracePeriodSeconds":60,"tolerations":[],"topologySpreadConstraints":[],"useDefaultProxyURLs":true}` | If running enterprise and using the default enterprise gateway, configs go here. |
| enterpriseGateway.affinity | object | `{}` | Affinity for gateway Pods |
| enterpriseGateway.annotations | object | `{}` | Additional annotations for the `gateway` Pod |
| enterpriseGateway.env | list | `[]` | Configure optional environment variables |
| enterpriseGateway.extraArgs | object | `{}` | Additional CLI arguments for the `gateway` target |
| enterpriseGateway.extraContainers | list | `[]` | Conifgure optional extraContainers |
| enterpriseGateway.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the enterprise gateway pods |
| enterpriseGateway.extraVolumeMounts | list | `[]` | Additional volume mounts for Pods |
| enterpriseGateway.extraVolumes | list | `[]` | Additional volumes for Pods |
| enterpriseGateway.hostAliases | list | `[]` | hostAliases to add |
| enterpriseGateway.initContainers | list | `[]` | Configure optional initContainers |
| enterpriseGateway.labels | object | `{}` | Additional labels for the `gateway` Pod |
| enterpriseGateway.nodeSelector | object | `{}` | Node selector for gateway Pods |
| enterpriseGateway.podSecurityContext | object | `{"fsGroup":10001,"runAsGroup":10001,"runAsNonRoot":true,"runAsUser":10001}` | Run container as user `enterprise-logs(uid=10001)` |
| enterpriseGateway.readinessProbe | object | `{"httpGet":{"path":"/ready","port":"http-metrics"},"initialDelaySeconds":45}` | Readiness probe |
| enterpriseGateway.replicas | int | `1` | Define the amount of instances |
| enterpriseGateway.resources | object | `{}` | Values are defined in small.yaml and large.yaml |
| enterpriseGateway.service | object | `{"annotations":{},"labels":{},"type":"ClusterIP"}` | Service overriding service type |
| enterpriseGateway.strategy | object | `{"type":"RollingUpdate"}` | update strategy |
| enterpriseGateway.terminationGracePeriodSeconds | int | `60` | Grace period to allow the gateway to shutdown before it is killed |
| enterpriseGateway.tolerations | list | `[]` | Tolerations for gateway Pods |
| enterpriseGateway.topologySpreadConstraints | list | `[]` | Topology Spread Constraints for enterprise-gateway pods |
| enterpriseGateway.useDefaultProxyURLs | bool | `true` | If you want to use your own proxy URLs, set this to false. |
| extraObjects | list | `[]` |  |
| fullnameOverride | string | `nil` | Overrides the chart's computed fullname |
| gateway.affinity | object | Hard node anti-affinity | Affinity for gateway pods. |
| gateway.annotations | object | `{}` | Annotations for gateway deployment |
| gateway.autoscaling.behavior | object | `{}` | Behavior policies while scaling. |
| gateway.autoscaling.enabled | bool | `false` | Enable autoscaling for the gateway |
| gateway.autoscaling.maxReplicas | int | `3` | Maximum autoscaling replicas for the gateway |
| gateway.autoscaling.minReplicas | int | `1` | Minimum autoscaling replicas for the gateway |
| gateway.autoscaling.targetCPUUtilizationPercentage | int | `60` | Target CPU utilisation percentage for the gateway |
| gateway.autoscaling.targetMemoryUtilizationPercentage | string | `nil` | Target memory utilisation percentage for the gateway |
| gateway.basicAuth.enabled | bool | `false` | Enables basic authentication for the gateway |
| gateway.basicAuth.existingSecret | string | `nil` | Existing basic auth secret to use. Must contain '.htpasswd' |
| gateway.basicAuth.htpasswd | string | Either `loki.tenants` or `gateway.basicAuth.username` and `gateway.basicAuth.password`. | Uses the specified users from the `loki.tenants` list to create the htpasswd file. if `loki.tenants` is not set, the `gateway.basicAuth.username` and `gateway.basicAuth.password` are used. The value is templated using `tpl`. Override this to use a custom htpasswd, e.g. in case the default causes high CPU load. |
| gateway.basicAuth.password | string | `nil` | The basic auth password for the gateway |
| gateway.basicAuth.username | string | `nil` | The basic auth username for the gateway |
| gateway.containerPort | int | `8080` | Default container port |
| gateway.containerSecurityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true}` | The SecurityContext for gateway containers |
| gateway.deploymentStrategy.type | string | `"RollingUpdate"` |  |
| gateway.dnsConfig | object | `{}` | DNS config for gateway pods |
| gateway.enabled | bool | `true` | Specifies whether the gateway should be enabled |
| gateway.extraArgs | list | `[]` | Additional CLI args for the gateway |
| gateway.extraContainers | list | `[]` | Containers to add to the gateway pods |
| gateway.extraEnv | list | `[]` | Environment variables to add to the gateway pods |
| gateway.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the gateway pods |
| gateway.extraVolumeMounts | list | `[]` | Volume mounts to add to the gateway pods |
| gateway.extraVolumes | list | `[]` | Volumes to add to the gateway pods |
| gateway.image.digest | string | `nil` | Overrides the gateway image tag with an image digest |
| gateway.image.pullPolicy | string | `"IfNotPresent"` | The gateway image pull policy |
| gateway.image.registry | string | `"docker.io"` | The Docker registry for the gateway image |
| gateway.image.repository | string | `"nginxinc/nginx-unprivileged"` | The gateway image repository |
| gateway.image.tag | string | `"1.27-alpine"` | The gateway image tag |
| gateway.ingress.annotations | object | `{}` | Annotations for the gateway ingress |
| gateway.ingress.enabled | bool | `false` | Specifies whether an ingress for the gateway should be created |
| gateway.ingress.hosts | list | `[{"host":"gateway.loki.example.com","paths":[{"path":"/"}]}]` | Hosts configuration for the gateway ingress, passed through the `tpl` function to allow templating |
| gateway.ingress.ingressClassName | string | `""` | Ingress Class Name. MAY be required for Kubernetes versions >= 1.18 |
| gateway.ingress.labels | object | `{}` | Labels for the gateway ingress |
| gateway.ingress.tls | list | `[{"hosts":["gateway.loki.example.com"],"secretName":"loki-gateway-tls"}]` | TLS configuration for the gateway ingress. Hosts passed through the `tpl` function to allow templating |
| gateway.lifecycle | object | `{}` | Lifecycle for the gateway container |
| gateway.nginxConfig.clientMaxBodySize | string | `"4M"` | Allows customizing the `client_max_body_size` directive |
| gateway.nginxConfig.customBackendUrl | string | `nil` | Override Backend URL |
| gateway.nginxConfig.customReadUrl | string | `nil` | Override Read URL |
| gateway.nginxConfig.customWriteUrl | string | `nil` | Override Write URL |
| gateway.nginxConfig.enableIPv6 | bool | `true` | Enable listener for IPv6, disable on IPv4-only systems |
| gateway.nginxConfig.file | string | See values.yaml | Config file contents for Nginx. Passed through the `tpl` function to allow templating |
| gateway.nginxConfig.httpSnippet | string | `"{{ if .Values.loki.tenants }}proxy_set_header X-Scope-OrgID $remote_user;{{ end }}"` | Allows appending custom configuration to the http block, passed through the `tpl` function to allow templating |
| gateway.nginxConfig.logFormat | string | `"main '$remote_addr - $remote_user [$time_local]  $status '\n        '\"$request\" $body_bytes_sent \"$http_referer\" '\n        '\"$http_user_agent\" \"$http_x_forwarded_for\"';"` | NGINX log format |
| gateway.nginxConfig.resolver | string | `""` | Allows overriding the DNS resolver address nginx will use. |
| gateway.nginxConfig.schema | string | `"http"` | Which schema to be used when building URLs. Can be 'http' or 'https'. |
| gateway.nginxConfig.serverSnippet | string | `""` | Allows appending custom configuration to the server block |
| gateway.nginxConfig.ssl | bool | `false` | Whether ssl should be appended to the listen directive of the server block or not. |
| gateway.nodeSelector | object | `{}` | Node selector for gateway pods |
| gateway.podAnnotations | object | `{}` | Annotations for gateway pods |
| gateway.podLabels | object | `{}` | Additional labels for gateway pods |
| gateway.podSecurityContext | object | `{"fsGroup":101,"runAsGroup":101,"runAsNonRoot":true,"runAsUser":101}` | The SecurityContext for gateway containers |
| gateway.priorityClassName | string | `nil` | The name of the PriorityClass for gateway pods |
| gateway.readinessProbe.httpGet.path | string | `"/"` |  |
| gateway.readinessProbe.httpGet.port | string | `"http-metrics"` |  |
| gateway.readinessProbe.initialDelaySeconds | int | `15` |  |
| gateway.readinessProbe.timeoutSeconds | int | `1` |  |
| gateway.replicas | int | `1` | Number of replicas for the gateway |
| gateway.resources | object | `{}` | Resource requests and limits for the gateway |
| gateway.service.annotations | object | `{}` | Annotations for the gateway service |
| gateway.service.clusterIP | string | `nil` | ClusterIP of the gateway service |
| gateway.service.labels | object | `{}` | Labels for gateway service |
| gateway.service.loadBalancerIP | string | `nil` | Load balancer IPO address if service type is LoadBalancer |
| gateway.service.nodePort | int | `nil` | Node port if service type is NodePort |
| gateway.service.port | int | `80` | Port of the gateway service |
| gateway.service.type | string | `"ClusterIP"` | Type of the gateway service |
| gateway.terminationGracePeriodSeconds | int | `30` | Grace period to allow the gateway to shutdown before it is killed |
| gateway.tolerations | list | `[]` | Tolerations for gateway pods |
| gateway.topologySpreadConstraints | list | `[]` | Topology Spread Constraints for gateway pods |
| gateway.verboseLogging | bool | `true` | Enable logging of 2xx and 3xx HTTP requests |
| global.clusterDomain | string | `"cluster.local"` | configures cluster domain ("cluster.local" by default) |
| global.dnsNamespace | string | `"kube-system"` | configures DNS service namespace |
| global.dnsService | string | `"kube-dns"` | configures DNS service name |
| global.image.registry | string | `nil` | Overrides the Docker registry globally for all images |
| global.priorityClassName | string | `nil` | Overrides the priorityClassName for all pods |
| imagePullSecrets | list | `[]` | Image pull secrets for Docker images |
| indexGateway | object | `{"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"app.kubernetes.io/component":"index-gateway"}},"topologyKey":"kubernetes.io/hostname"}]}},"appProtocol":{"grpc":""},"extraArgs":[],"extraContainers":[],"extraEnv":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"hostAliases":[],"image":{"registry":null,"repository":null,"tag":null},"initContainers":[],"joinMemberlist":true,"maxUnavailable":null,"nodeSelector":{},"persistence":{"annotations":{},"enableStatefulSetAutoDeletePVC":false,"enabled":false,"inMemory":false,"size":"10Gi","storageClass":null,"whenDeleted":"Retain","whenScaled":"Retain"},"podAnnotations":{},"podLabels":{},"priorityClassName":null,"replicas":0,"resources":{},"serviceAnnotations":{},"serviceLabels":{},"terminationGracePeriodSeconds":300,"tolerations":[],"topologySpreadConstraints":[],"updateStrategy":{"type":"RollingUpdate"}}` | Configuration for the index-gateway |
| indexGateway.affinity | object | Hard node anti-affinity | Affinity for index-gateway pods. |
| indexGateway.appProtocol | object | `{"grpc":""}` | Set the optional grpc service protocol. Ex: "grpc", "http2" or "https" |
| indexGateway.extraArgs | list | `[]` | Additional CLI args for the index-gateway |
| indexGateway.extraContainers | list | `[]` | Containers to add to the index-gateway pods |
| indexGateway.extraEnv | list | `[]` | Environment variables to add to the index-gateway pods |
| indexGateway.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the index-gateway pods |
| indexGateway.extraVolumeMounts | list | `[]` | Volume mounts to add to the index-gateway pods |
| indexGateway.extraVolumes | list | `[]` | Volumes to add to the index-gateway pods |
| indexGateway.hostAliases | list | `[]` | hostAliases to add |
| indexGateway.image.registry | string | `nil` | The Docker registry for the index-gateway image. Overrides `loki.image.registry` |
| indexGateway.image.repository | string | `nil` | Docker image repository for the index-gateway image. Overrides `loki.image.repository` |
| indexGateway.image.tag | string | `nil` | Docker image tag for the index-gateway image. Overrides `loki.image.tag` |
| indexGateway.initContainers | list | `[]` | Init containers to add to the index-gateway pods |
| indexGateway.joinMemberlist | bool | `true` | Whether the index gateway should join the memberlist hashring |
| indexGateway.maxUnavailable | string | `nil` | Pod Disruption Budget maxUnavailable |
| indexGateway.nodeSelector | object | `{}` | Node selector for index-gateway pods |
| indexGateway.persistence.annotations | object | `{}` | Annotations for index gateway PVCs |
| indexGateway.persistence.enableStatefulSetAutoDeletePVC | bool | `false` | Enable StatefulSetAutoDeletePVC feature |
| indexGateway.persistence.enabled | bool | `false` | Enable creating PVCs which is required when using boltdb-shipper |
| indexGateway.persistence.inMemory | bool | `false` | Use emptyDir with ramdisk for storage. **Please note that all data in indexGateway will be lost on pod restart** |
| indexGateway.persistence.size | string | `"10Gi"` | Size of persistent or memory disk |
| indexGateway.persistence.storageClass | string | `nil` | Storage class to be used. If defined, storageClassName: <storageClass>. If set to "-", storageClassName: "", which disables dynamic provisioning. If empty or set to null, no storageClassName spec is set, choosing the default provisioner (gp2 on AWS, standard on GKE, AWS, and OpenStack). |
| indexGateway.podAnnotations | object | `{}` | Annotations for index-gateway pods |
| indexGateway.podLabels | object | `{}` | Labels for index-gateway pods |
| indexGateway.priorityClassName | string | `nil` | The name of the PriorityClass for index-gateway pods |
| indexGateway.replicas | int | `0` | Number of replicas for the index-gateway |
| indexGateway.resources | object | `{}` | Resource requests and limits for the index-gateway |
| indexGateway.serviceAnnotations | object | `{}` | Annotations for index-gateway service |
| indexGateway.serviceLabels | object | `{}` | Labels for index-gateway service |
| indexGateway.terminationGracePeriodSeconds | int | `300` | Grace period to allow the index-gateway to shutdown before it is killed. |
| indexGateway.tolerations | list | `[]` | Tolerations for index-gateway pods |
| indexGateway.topologySpreadConstraints | list | `[]` | Topology Spread Constraints for index-gateway pods |
| indexGateway.updateStrategy | object | `{"type":"RollingUpdate"}` | UpdateStrategy for the indexGateway StatefulSet. |
| indexGateway.updateStrategy.type | string | `"RollingUpdate"` | One of  'OnDelete' or 'RollingUpdate' |
| ingester | object | `{"addIngesterNamePrefix":false,"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"app.kubernetes.io/component":"ingester"}},"topologyKey":"kubernetes.io/hostname"}]}},"appProtocol":{"grpc":""},"autoscaling":{"behavior":{"enabled":false,"scaleDown":{},"scaleUp":{}},"customMetrics":[],"enabled":false,"maxReplicas":3,"minReplicas":1,"targetCPUUtilizationPercentage":60,"targetMemoryUtilizationPercentage":null},"command":null,"extraArgs":[],"extraContainers":[],"extraEnv":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"hostAliases":[],"image":{"registry":null,"repository":null,"tag":null},"initContainers":[],"lifecycle":{},"livenessProbe":{},"maxUnavailable":1,"nodeSelector":{},"persistence":{"claims":[{"name":"data","size":"10Gi","storageClass":null}],"enableStatefulSetAutoDeletePVC":false,"enabled":false,"inMemory":false,"whenDeleted":"Retain","whenScaled":"Retain"},"podAnnotations":{},"podLabels":{},"priorityClassName":null,"readinessProbe":{},"replicas":0,"resources":{},"rolloutGroupPrefix":null,"serviceAnnotations":{},"serviceLabels":{},"terminationGracePeriodSeconds":300,"tolerations":[],"topologySpreadConstraints":[{"labelSelector":{"matchLabels":{"app.kubernetes.io/component":"ingester"}},"maxSkew":1,"topologyKey":"kubernetes.io/hostname","whenUnsatisfiable":"ScheduleAnyway"}],"updateStrategy":{"type":"RollingUpdate"},"zoneAwareReplication":{"enabled":true,"maxUnavailablePct":33,"migration":{"enabled":false,"excludeDefaultZone":false,"readPath":false,"writePath":false},"zoneA":{"annotations":{},"extraAffinity":{},"nodeSelector":null,"podAnnotations":{}},"zoneB":{"annotations":{},"extraAffinity":{},"nodeSelector":null,"podAnnotations":{}},"zoneC":{"annotations":{},"extraAffinity":{},"nodeSelector":null,"podAnnotations":{}}}}` | Configuration for the ingester |
| ingester.affinity | object | Hard node anti-affinity | Affinity for ingester pods. Ignored if zoneAwareReplication is enabled. |
| ingester.appProtocol | object | `{"grpc":""}` | Adds the appProtocol field to the ingester service. This allows ingester to work with istio protocol selection. |
| ingester.appProtocol.grpc | string | `""` | Set the optional grpc service protocol. Ex: "grpc", "http2" or "https" |
| ingester.autoscaling.behavior.enabled | bool | `false` | Enable autoscaling behaviours |
| ingester.autoscaling.behavior.scaleDown | object | `{}` | define scale down policies, must conform to HPAScalingRules |
| ingester.autoscaling.behavior.scaleUp | object | `{}` | define scale up policies, must conform to HPAScalingRules |
| ingester.autoscaling.customMetrics | list | `[]` | Allows one to define custom metrics using the HPA/v2 schema (for example, Pods, Object or External metrics) |
| ingester.autoscaling.enabled | bool | `false` | Enable autoscaling for the ingester |
| ingester.autoscaling.maxReplicas | int | `3` | Maximum autoscaling replicas for the ingester |
| ingester.autoscaling.minReplicas | int | `1` | Minimum autoscaling replicas for the ingester |
| ingester.autoscaling.targetCPUUtilizationPercentage | int | `60` | Target CPU utilisation percentage for the ingester |
| ingester.autoscaling.targetMemoryUtilizationPercentage | string | `nil` | Target memory utilisation percentage for the ingester |
| ingester.command | string | `nil` | Command to execute instead of defined in Docker image |
| ingester.extraArgs | list | `[]` | Additional CLI args for the ingester |
| ingester.extraContainers | list | `[]` | Containers to add to the ingester pods |
| ingester.extraEnv | list | `[]` | Environment variables to add to the ingester pods |
| ingester.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the ingester pods |
| ingester.extraVolumeMounts | list | `[]` | Volume mounts to add to the ingester pods |
| ingester.extraVolumes | list | `[]` | Volumes to add to the ingester pods |
| ingester.hostAliases | list | `[]` | hostAliases to add |
| ingester.image.registry | string | `nil` | The Docker registry for the ingester image. Overrides `loki.image.registry` |
| ingester.image.repository | string | `nil` | Docker image repository for the ingester image. Overrides `loki.image.repository` |
| ingester.image.tag | string | `nil` | Docker image tag for the ingester image. Overrides `loki.image.tag` |
| ingester.initContainers | list | `[]` | Init containers to add to the ingester pods |
| ingester.lifecycle | object | `{}` | Lifecycle for the ingester container |
| ingester.livenessProbe | object | `{}` | liveness probe settings for ingester pods. If empty use `loki.livenessProbe` |
| ingester.maxUnavailable | int | `1` | Pod Disruption Budget maxUnavailable |
| ingester.nodeSelector | object | `{}` | Node selector for ingester pods |
| ingester.persistence.claims | list |  | List of the ingester PVCs |
| ingester.persistence.enableStatefulSetAutoDeletePVC | bool | `false` | Enable StatefulSetAutoDeletePVC feature |
| ingester.persistence.enabled | bool | `false` | Enable creating PVCs which is required when using boltdb-shipper |
| ingester.persistence.inMemory | bool | `false` | Use emptyDir with ramdisk for storage. **Please note that all data in ingester will be lost on pod restart** |
| ingester.podAnnotations | object | `{}` | Annotations for ingester pods |
| ingester.podLabels | object | `{}` | Labels for ingester pods |
| ingester.readinessProbe | object | `{}` | readiness probe settings for ingester pods. If empty, use `loki.readinessProbe` |
| ingester.replicas | int | `0` | Number of replicas for the ingester, when zoneAwareReplication.enabled is true, the total number of replicas will match this value with each zone having 1/3rd of the total replicas. |
| ingester.resources | object | `{}` | Resource requests and limits for the ingester |
| ingester.serviceAnnotations | object | `{}` | Annotations for ingestor service |
| ingester.serviceLabels | object | `{}` | Labels for ingestor service |
| ingester.terminationGracePeriodSeconds | int | `300` | Grace period to allow the ingester to shutdown before it is killed. Especially for the ingestor, this must be increased. It must be long enough so ingesters can be gracefully shutdown flushing/transferring all data and to successfully leave the member ring on shutdown. |
| ingester.tolerations | list | `[]` | Tolerations for ingester pods |
| ingester.topologySpreadConstraints | list | Defaults to allow skew no more than 1 node | topologySpread for ingester pods. |
| ingester.updateStrategy | object | `{"type":"RollingUpdate"}` | UpdateStrategy for the ingester StatefulSets. |
| ingester.updateStrategy.type | string | `"RollingUpdate"` | One of  'OnDelete' or 'RollingUpdate' |
| ingester.zoneAwareReplication | object | `{"enabled":true,"maxUnavailablePct":33,"migration":{"enabled":false,"excludeDefaultZone":false,"readPath":false,"writePath":false},"zoneA":{"annotations":{},"extraAffinity":{},"nodeSelector":null,"podAnnotations":{}},"zoneB":{"annotations":{},"extraAffinity":{},"nodeSelector":null,"podAnnotations":{}},"zoneC":{"annotations":{},"extraAffinity":{},"nodeSelector":null,"podAnnotations":{}}}` | Enabling zone awareness on ingesters will create 3 statefulests where all writes will send a replica to each zone. This is primarily intended to accelerate rollout operations by allowing for multiple ingesters within a single zone to be shutdown and restart simultaneously (the remaining 2 zones will be guaranteed to have at least one copy of the data). Note: This can be used to run Loki over multiple cloud provider availability zones however this is not currently recommended as Loki is not optimized for this and cross zone network traffic costs can become extremely high extremely quickly. Even with zone awareness enabled, it is recommended to run Loki in a single availability zone. |
| ingester.zoneAwareReplication.enabled | bool | `true` | Enable zone awareness. |
| ingester.zoneAwareReplication.maxUnavailablePct | int | `33` | The percent of replicas in each zone that will be restarted at once. In a value of 0-100 |
| ingester.zoneAwareReplication.migration | object | `{"enabled":false,"excludeDefaultZone":false,"readPath":false,"writePath":false}` | The migration block allows migrating non zone aware ingesters to zone aware ingesters. |
| ingester.zoneAwareReplication.zoneA | object | `{"annotations":{},"extraAffinity":{},"nodeSelector":null,"podAnnotations":{}}` | zoneA configuration |
| ingester.zoneAwareReplication.zoneA.annotations | object | `{}` | Specific annotations to add to zone A statefulset |
| ingester.zoneAwareReplication.zoneA.extraAffinity | object | `{}` | optionally define extra affinity rules, by default different zones are not allowed to schedule on the same host |
| ingester.zoneAwareReplication.zoneA.nodeSelector | string | `nil` | optionally define a node selector for this zone |
| ingester.zoneAwareReplication.zoneA.podAnnotations | object | `{}` | Specific annotations to add to zone A pods |
| ingester.zoneAwareReplication.zoneB.annotations | object | `{}` | Specific annotations to add to zone B statefulset |
| ingester.zoneAwareReplication.zoneB.extraAffinity | object | `{}` | optionally define extra affinity rules, by default different zones are not allowed to schedule on the same host |
| ingester.zoneAwareReplication.zoneB.nodeSelector | string | `nil` | optionally define a node selector for this zone |
| ingester.zoneAwareReplication.zoneB.podAnnotations | object | `{}` | Specific annotations to add to zone B pods |
| ingester.zoneAwareReplication.zoneC.annotations | object | `{}` | Specific annotations to add to zone C statefulset |
| ingester.zoneAwareReplication.zoneC.extraAffinity | object | `{}` | optionally define extra affinity rules, by default different zones are not allowed to schedule on the same host |
| ingester.zoneAwareReplication.zoneC.nodeSelector | string | `nil` | optionally define a node selector for this zone |
| ingester.zoneAwareReplication.zoneC.podAnnotations | object | `{}` | Specific annotations to add to zone C pods |
| ingress | object | `{"annotations":{},"enabled":false,"hosts":["loki.example.com"],"ingressClassName":"","labels":{},"paths":{"distributor":["/api/prom/push","/loki/api/v1/push","/otlp/v1/logs"],"queryFrontend":["/api/prom/query","/api/prom/label","/api/prom/series","/api/prom/tail","/loki/api/v1/query","/loki/api/v1/query_range","/loki/api/v1/tail","/loki/api/v1/label","/loki/api/v1/labels","/loki/api/v1/series","/loki/api/v1/index/stats","/loki/api/v1/index/volume","/loki/api/v1/index/volume_range","/loki/api/v1/format_query","/loki/api/v1/detected_field","/loki/api/v1/detected_fields","/loki/api/v1/detected_labels","/loki/api/v1/patterns"],"ruler":["/api/prom/rules","/api/prom/api/v1/rules","/api/prom/api/v1/alerts","/loki/api/v1/rules","/prometheus/api/v1/rules","/prometheus/api/v1/alerts"]},"tls":[]}` | Ingress configuration Use either this ingress or the gateway, but not both at once. If you enable this, make sure to disable the gateway. You'll need to supply authn configuration for your ingress controller. |
| ingress.hosts | list | `["loki.example.com"]` | Hosts configuration for the ingress, passed through the `tpl` function to allow templating |
| ingress.paths.distributor | list | `["/api/prom/push","/loki/api/v1/push","/otlp/v1/logs"]` | Paths that are exposed by Loki Distributor. If deployment mode is Distributed, the requests are forwarded to the service: `{{"loki.distributorFullname"}}`. If deployment mode is SimpleScalable, the requests are forwarded to write k8s service: `{{"loki.writeFullname"}}`. If deployment mode is SingleBinary, the requests are forwarded to the central/single k8s service: `{{"loki.singleBinaryFullname"}}` |
| ingress.paths.queryFrontend | list | `["/api/prom/query","/api/prom/label","/api/prom/series","/api/prom/tail","/loki/api/v1/query","/loki/api/v1/query_range","/loki/api/v1/tail","/loki/api/v1/label","/loki/api/v1/labels","/loki/api/v1/series","/loki/api/v1/index/stats","/loki/api/v1/index/volume","/loki/api/v1/index/volume_range","/loki/api/v1/format_query","/loki/api/v1/detected_field","/loki/api/v1/detected_fields","/loki/api/v1/detected_labels","/loki/api/v1/patterns"]` | Paths that are exposed by Loki Query Frontend. If deployment mode is Distributed, the requests are forwarded to the service: `{{"loki.queryFrontendFullname"}}`. If deployment mode is SimpleScalable, the requests are forwarded to write k8s service: `{{"loki.readFullname"}}`. If deployment mode is SingleBinary, the requests are forwarded to the central/single k8s service: `{{"loki.singleBinaryFullname"}}` |
| ingress.paths.ruler | list | `["/api/prom/rules","/api/prom/api/v1/rules","/api/prom/api/v1/alerts","/loki/api/v1/rules","/prometheus/api/v1/rules","/prometheus/api/v1/alerts"]` | Paths that are exposed by Loki Ruler. If deployment mode is Distributed, the requests are forwarded to the service: `{{"loki.rulerFullname"}}`. If deployment mode is SimpleScalable, the requests are forwarded to k8s service: `{{"loki.backendFullname"}}`. If deployment mode is SimpleScalable but `read.legacyReadTarget` is `true`, the requests are forwarded to k8s service: `{{"loki.readFullname"}}`. If deployment mode is SingleBinary, the requests are forwarded to the central/single k8s service: `{{"loki.singleBinaryFullname"}}` |
| ingress.tls | list | `[]` | TLS configuration for the ingress. Hosts passed through the `tpl` function to allow templating |
| kubeVersionOverride | string | `nil` | Overrides the version used to determine compatibility of resources with the target Kubernetes cluster. This is useful when using `helm template`, because then helm will use the client version of kubectl as the Kubernetes version, which may or may not match your cluster's server version. Example: 'v1.24.4'. Set to null to use the version that helm devises. |
| kubectlImage | object | `{"digest":null,"pullPolicy":"IfNotPresent","registry":"docker.io","repository":"bitnami/kubectl","tag":null}` | kubetclImage is used in the enterprise provisioner and tokengen jobs |
| kubectlImage.digest | string | `nil` | Overrides the image tag with an image digest |
| kubectlImage.pullPolicy | string | `"IfNotPresent"` | Docker image pull policy |
| kubectlImage.registry | string | `"docker.io"` | The Docker registry |
| kubectlImage.repository | string | `"bitnami/kubectl"` | Docker image repository |
| kubectlImage.tag | string | `nil` | Overrides the image tag whose default is the chart's appVersion |
| loki | object | See values.yaml | Configuration for running Loki |
| loki.analytics | object | `{}` | Optional analytics configuration |
| loki.annotations | object | `{}` | Common annotations for all deployments/StatefulSets |
| loki.commonConfig | object | `{"compactor_address":"{{ include \"loki.compactorAddress\" . }}","path_prefix":"/var/loki","replication_factor":3}` | Check https://grafana.com/docs/loki/latest/configuration/#common_config for more info on how to provide a common configuration |
| loki.compactor | object | `{}` | Optional compactor configuration |
| loki.config | string | See values.yaml | Config file contents for Loki |
| loki.configObjectName | string | `"{{ include \"loki.name\" . }}"` | The name of the object which Loki will mount as a volume containing the config. If the configStorageType is Secret, this will be the name of the Secret, if it is ConfigMap, this will be the name of the ConfigMap. The value will be passed through tpl. |
| loki.configStorageType | string | `"ConfigMap"` | Defines what kind of object stores the configuration, a ConfigMap or a Secret. In order to move sensitive information (such as credentials) from the ConfigMap/Secret to a more secure location (e.g. vault), it is possible to use [environment variables in the configuration](https://grafana.com/docs/loki/latest/configuration/#use-environment-variables-in-the-configuration). Such environment variables can be then stored in a separate Secret and injected via the global.extraEnvFrom value. For details about environment injection from a Secret please see [Secrets](https://kubernetes.io/docs/concepts/configuration/secret/#use-case-as-container-environment-variables). |
| loki.containerSecurityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true}` | The SecurityContext for Loki containers |
| loki.distributor | object | `{}` | Optional distributor configuration |
| loki.enableServiceLinks | bool | `true` | Should enableServiceLinks be enabled. Default to enable |
| loki.extraMemberlistConfig | object | `{}` | Extra memberlist configuration |
| loki.generatedConfigObjectName | string | `"{{ include \"loki.name\" . }}"` | The name of the Secret or ConfigMap that will be created by this chart. If empty, no configmap or secret will be created. The value will be passed through tpl. |
| loki.image.digest | string | `nil` | Overrides the image tag with an image digest |
| loki.image.pullPolicy | string | `"IfNotPresent"` | Docker image pull policy |
| loki.image.registry | string | `"docker.io"` | The Docker registry |
| loki.image.repository | string | `"grafana/loki"` | Docker image repository |
| loki.image.tag | string | `"3.3.2"` | Overrides the image tag whose default is the chart's appVersion |
| loki.index_gateway | object | `{"mode":"simple"}` | Optional index gateway configuration |
| loki.ingester | object | `{}` | Optional ingester configuration |
| loki.limits_config | object | `{"max_cache_freshness_per_query":"10m","query_timeout":"300s","reject_old_samples":true,"reject_old_samples_max_age":"168h","split_queries_by_interval":"15m","volume_enabled":true}` | Limits config |
| loki.memberlistConfig | object | `{}` | memberlist configuration (overrides embedded default) |
| loki.memcached | object | `{"chunk_cache":{"batch_size":256,"enabled":false,"host":"","parallelism":10,"service":"memcached-client"},"results_cache":{"default_validity":"12h","enabled":false,"host":"","service":"memcached-client","timeout":"500ms"}}` | Configure memcached as an external cache for chunk and results cache. Disabled by default must enable and specify a host for each cache you would like to use. |
| loki.pattern_ingester | object | `{"enabled":false}` | Optional pattern ingester configuration |
| loki.podAnnotations | object | `{}` | Common annotations for all pods |
| loki.podLabels | object | `{}` | Common labels for all pods |
| loki.podSecurityContext | object | `{"fsGroup":10001,"runAsGroup":10001,"runAsNonRoot":true,"runAsUser":10001}` | The SecurityContext for Loki pods |
| loki.querier | object | `{}` | Optional querier configuration |
| loki.query_range | object | `{}` | Optional querier configuration |
| loki.query_scheduler | object | `{}` | Additional query scheduler config |
| loki.revisionHistoryLimit | int | `10` | The number of old ReplicaSets to retain to allow rollback |
| loki.rulerConfig | object | `{"wal":{"dir":"/var/loki/ruler-wal"}}` | Check https://grafana.com/docs/loki/latest/configuration/#ruler for more info on configuring ruler |
| loki.runtimeConfig | object | `{}` | Provides a reloadable runtime configuration file for some specific configuration |
| loki.schemaConfig | object | `{}` | Check https://grafana.com/docs/loki/latest/configuration/#schema_config for more info on how to configure schemas |
| loki.server | object | `{"grpc_listen_port":9095,"http_listen_port":3100,"http_server_read_timeout":"600s","http_server_write_timeout":"600s"}` | Check https://grafana.com/docs/loki/latest/configuration/#server for more info on the server configuration. |
| loki.serviceAnnotations | object | `{}` | Common annotations for all services |
| loki.serviceLabels | object | `{}` | Common labels for all services |
| loki.storage | object | `{"azure":{"accountKey":null,"accountName":null,"chunkDelimiter":null,"connectionString":null,"endpointSuffix":null,"requestTimeout":null,"useFederatedToken":false,"useManagedIdentity":false,"userAssignedId":null},"filesystem":{"admin_api_directory":"/var/loki/admin","chunks_directory":"/var/loki/chunks","rules_directory":"/var/loki/rules"},"gcs":{"chunkBufferSize":0,"enableHttp2":true,"requestTimeout":"0s"},"s3":{"accessKeyId":null,"backoff_config":{},"disable_dualstack":false,"endpoint":null,"http_config":{},"insecure":false,"region":null,"s3":null,"s3ForcePathStyle":false,"secretAccessKey":null,"signatureVersion":null},"swift":{"auth_url":null,"auth_version":null,"connect_timeout":null,"container_name":null,"domain_id":null,"domain_name":null,"internal":null,"max_retries":null,"password":null,"project_domain_id":null,"project_domain_name":null,"project_id":null,"project_name":null,"region_name":null,"request_timeout":null,"user_domain_id":null,"user_domain_name":null,"user_id":null,"username":null},"type":"s3"}` | Storage config. Providing this will automatically populate all necessary storage configs in the templated config. |
| loki.storage.s3.backoff_config | object | `{}` | Check https://grafana.com/docs/loki/latest/configure/#s3_storage_config for more info on how to provide a backoff_config |
| loki.storage_config | object | `{"bloom_shipper":{"working_directory":"/var/loki/data/bloomshipper"},"boltdb_shipper":{"index_gateway_client":{"server_address":"{{ include \"loki.indexGatewayAddress\" . }}"}},"hedging":{"at":"250ms","max_per_second":20,"up_to":3},"tsdb_shipper":{"index_gateway_client":{"server_address":"{{ include \"loki.indexGatewayAddress\" . }}"}}}` | Additional storage config |
| loki.structuredConfig | object | `{}` | Structured loki configuration, takes precedence over `loki.config`, `loki.schemaConfig`, `loki.storageConfig` |
| loki.tenants | list | `[]` | Tenants list to be created on nginx htpasswd file, with name and password keys |
| loki.tracing | object | `{"enabled":false}` | Enable tracing |
| loki.useTestSchema | bool | `false` | a real Loki install requires a proper schemaConfig defined above this, however for testing or playing around you can enable useTestSchema |
| lokiCanary.annotations | object | `{}` | Additional annotations for the `loki-canary` Daemonset |
| lokiCanary.dnsConfig | object | `{}` | DNS config for canary pods |
| lokiCanary.enabled | bool | `true` |  |
| lokiCanary.extraArgs | list | `[]` | Additional CLI arguments for the `loki-canary' command |
| lokiCanary.extraEnv | list | `[]` | Environment variables to add to the canary pods |
| lokiCanary.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the canary pods |
| lokiCanary.extraVolumeMounts | list | `[]` | Volume mounts to add to the canary pods |
| lokiCanary.extraVolumes | list | `[]` | Volumes to add to the canary pods |
| lokiCanary.image | object | `{"digest":null,"pullPolicy":"IfNotPresent","registry":"docker.io","repository":"grafana/loki-canary","tag":null}` | Image to use for loki canary |
| lokiCanary.image.digest | string | `nil` | Overrides the image tag with an image digest |
| lokiCanary.image.pullPolicy | string | `"IfNotPresent"` | Docker image pull policy |
| lokiCanary.image.registry | string | `"docker.io"` | The Docker registry |
| lokiCanary.image.repository | string | `"grafana/loki-canary"` | Docker image repository |
| lokiCanary.image.tag | string | `nil` | Overrides the image tag whose default is the chart's appVersion |
| lokiCanary.labelname | string | `"pod"` | The name of the label to look for at loki when doing the checks. |
| lokiCanary.nodeSelector | object | `{}` | Node selector for canary pods |
| lokiCanary.podLabels | object | `{}` | Additional labels for each `loki-canary` pod |
| lokiCanary.priorityClassName | string | `nil` | The name of the PriorityClass for loki-canary pods |
| lokiCanary.push | bool | `true` |  |
| lokiCanary.resources | object | `{}` | Resource requests and limits for the canary |
| lokiCanary.service.annotations | object | `{}` | Annotations for loki-canary Service |
| lokiCanary.service.labels | object | `{}` | Additional labels for loki-canary Service |
| lokiCanary.tolerations | list | `[]` | Tolerations for canary pods |
| lokiCanary.updateStrategy | object | `{"rollingUpdate":{"maxUnavailable":1},"type":"RollingUpdate"}` | Update strategy for the `loki-canary` Daemonset pods |
| memberlist.service.annotations | object | `{}` |  |
| memberlist.service.publishNotReadyAddresses | bool | `false` |  |
| memcached.containerSecurityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true}` | The SecurityContext for memcached containers |
| memcached.image.pullPolicy | string | `"IfNotPresent"` | Memcached Docker image pull policy |
| memcached.image.repository | string | `"memcached"` | Memcached Docker image repository |
| memcached.image.tag | string | `"1.6.34-alpine"` | Memcached Docker image tag |
| memcached.podSecurityContext | object | `{"fsGroup":11211,"runAsGroup":11211,"runAsNonRoot":true,"runAsUser":11211}` | The SecurityContext override for memcached pods |
| memcached.priorityClassName | string | `nil` | The name of the PriorityClass for memcached pods |
| memcachedExporter.containerSecurityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true}` | The SecurityContext for memcached exporter containers |
| memcachedExporter.enabled | bool | `true` | Whether memcached metrics should be exported |
| memcachedExporter.extraArgs | object | `{}` | Extra args to add to the exporter container. Example: extraArgs:   memcached.tls.enable: true   memcached.tls.cert-file: /certs/cert.crt   memcached.tls.key-file: /certs/cert.key   memcached.tls.ca-file: /certs/ca.crt   memcached.tls.insecure-skip-verify: false   memcached.tls.server-name: memcached |
| memcachedExporter.image.pullPolicy | string | `"IfNotPresent"` |  |
| memcachedExporter.image.repository | string | `"prom/memcached-exporter"` |  |
| memcachedExporter.image.tag | string | `"v0.15.0"` |  |
| memcachedExporter.resources.limits | object | `{}` |  |
| memcachedExporter.resources.requests | object | `{}` |  |
| migrate | object | `{"fromDistributed":{"enabled":false,"memberlistService":""}}` | Options that may be necessary when performing a migration from another helm chart |
| migrate.fromDistributed | object | `{"enabled":false,"memberlistService":""}` | When migrating from a distributed chart like loki-distributed or enterprise-logs |
| migrate.fromDistributed.enabled | bool | `false` | Set to true if migrating from a distributed helm chart |
| migrate.fromDistributed.memberlistService | string | `""` | If migrating from a distributed service, provide the distributed deployment's memberlist service DNS so the new deployment can join its ring. |
| minio | object | `{"address":null,"buckets":[{"name":"chunks","policy":"none","purge":false},{"name":"ruler","policy":"none","purge":false},{"name":"admin","policy":"none","purge":false}],"drivesPerNode":2,"enabled":false,"persistence":{"annotations":{},"size":"5Gi"},"replicas":1,"resources":{"requests":{"cpu":"100m","memory":"128Mi"}},"rootPassword":"supersecretpassword","rootUser":"root-user","users":[{"accessKey":"logs-user","policy":"readwrite","secretKey":"supersecretpassword"}]}` | Configuration for the minio subchart |
| monitoring | object | `{"dashboards":{"annotations":{},"enabled":false,"labels":{"grafana_dashboard":"1"},"namespace":null},"rules":{"additionalGroups":[],"additionalRuleLabels":{},"alerting":true,"annotations":{},"disabled":{},"enabled":false,"labels":{},"namespace":null},"selfMonitoring":{"enabled":false,"grafanaAgent":{"annotations":{},"enableConfigReadAPI":false,"installOperator":false,"labels":{},"priorityClassName":null,"resources":{},"tolerations":[]},"logsInstance":{"annotations":{},"clients":null,"labels":{}},"podLogs":{"additionalPipelineStages":[],"annotations":{},"apiVersion":"monitoring.grafana.com/v1alpha1","labels":{},"relabelings":[]},"tenant":{"name":"self-monitoring","password":null,"secretNamespace":"{{ .Release.Namespace }}"}},"serviceMonitor":{"annotations":{},"enabled":false,"interval":"15s","labels":{},"metricRelabelings":[],"metricsInstance":{"annotations":{},"enabled":true,"labels":{},"remoteWrite":null},"namespaceSelector":{},"relabelings":[],"scheme":"http","scrapeTimeout":null,"tlsConfig":null}}` | DEPRECATED Monitoring section determines which monitoring features to enable, this section is being replaced by https://github.com/grafana/meta-monitoring-chart |
| monitoring.dashboards.annotations | object | `{}` | Additional annotations for the dashboards ConfigMap |
| monitoring.dashboards.enabled | bool | `false` | If enabled, create configmap with dashboards for monitoring Loki |
| monitoring.dashboards.labels | object | `{"grafana_dashboard":"1"}` | Labels for the dashboards ConfigMap |
| monitoring.dashboards.namespace | string | `nil` | Alternative namespace to create dashboards ConfigMap in |
| monitoring.rules | object | `{"additionalGroups":[],"additionalRuleLabels":{},"alerting":true,"annotations":{},"disabled":{},"enabled":false,"labels":{},"namespace":null}` | DEPRECATED Recording rules for monitoring Loki, required for some dashboards |
| monitoring.rules.additionalGroups | list | `[]` | Additional groups to add to the rules file |
| monitoring.rules.additionalRuleLabels | object | `{}` | Additional labels for PrometheusRule alerts |
| monitoring.rules.alerting | bool | `true` | Include alerting rules |
| monitoring.rules.annotations | object | `{}` | Additional annotations for the rules PrometheusRule resource |
| monitoring.rules.disabled | object | `{}` | If you disable all the alerts and keep .monitoring.rules.alerting set to true, the chart will fail to render. |
| monitoring.rules.enabled | bool | `false` | If enabled, create PrometheusRule resource with Loki recording rules |
| monitoring.rules.labels | object | `{}` | Additional labels for the rules PrometheusRule resource |
| monitoring.rules.namespace | string | `nil` | Alternative namespace to create PrometheusRule resources in |
| monitoring.selfMonitoring | object | `{"enabled":false,"grafanaAgent":{"annotations":{},"enableConfigReadAPI":false,"installOperator":false,"labels":{},"priorityClassName":null,"resources":{},"tolerations":[]},"logsInstance":{"annotations":{},"clients":null,"labels":{}},"podLogs":{"additionalPipelineStages":[],"annotations":{},"apiVersion":"monitoring.grafana.com/v1alpha1","labels":{},"relabelings":[]},"tenant":{"name":"self-monitoring","password":null,"secretNamespace":"{{ .Release.Namespace }}"}}` | DEPRECATED Self monitoring determines whether Loki should scrape its own logs. This feature currently relies on the Grafana Agent Operator being installed, which is installed by default using the grafana-agent-operator sub-chart. It will create custom resources for GrafanaAgent, LogsInstance, and PodLogs to configure scrape configs to scrape its own logs with the labels expected by the included dashboards. |
| monitoring.selfMonitoring.grafanaAgent | object | `{"annotations":{},"enableConfigReadAPI":false,"installOperator":false,"labels":{},"priorityClassName":null,"resources":{},"tolerations":[]}` | DEPRECATED Grafana Agent configuration |
| monitoring.selfMonitoring.grafanaAgent.annotations | object | `{}` | Grafana Agent annotations |
| monitoring.selfMonitoring.grafanaAgent.enableConfigReadAPI | bool | `false` | Enable the config read api on port 8080 of the agent |
| monitoring.selfMonitoring.grafanaAgent.installOperator | bool | `false` | DEPRECATED Controls whether to install the Grafana Agent Operator and its CRDs. Note that helm will not install CRDs if this flag is enabled during an upgrade. In that case install the CRDs manually from https://github.com/grafana/agent/tree/main/production/operator/crds |
| monitoring.selfMonitoring.grafanaAgent.labels | object | `{}` | Additional Grafana Agent labels |
| monitoring.selfMonitoring.grafanaAgent.priorityClassName | string | `nil` | The name of the PriorityClass for GrafanaAgent pods |
| monitoring.selfMonitoring.grafanaAgent.resources | object | `{}` | Resource requests and limits for the grafanaAgent pods |
| monitoring.selfMonitoring.grafanaAgent.tolerations | list | `[]` | Tolerations for GrafanaAgent pods |
| monitoring.selfMonitoring.logsInstance.annotations | object | `{}` | LogsInstance annotations |
| monitoring.selfMonitoring.logsInstance.clients | string | `nil` | Additional clients for remote write |
| monitoring.selfMonitoring.logsInstance.labels | object | `{}` | Additional LogsInstance labels |
| monitoring.selfMonitoring.podLogs.additionalPipelineStages | list | `[]` | Additional pipeline stages to process logs after scraping https://grafana.com/docs/agent/latest/operator/api/#pipelinestagespec-a-namemonitoringgrafanacomv1alpha1pipelinestagespeca |
| monitoring.selfMonitoring.podLogs.annotations | object | `{}` | PodLogs annotations |
| monitoring.selfMonitoring.podLogs.apiVersion | string | `"monitoring.grafana.com/v1alpha1"` | PodLogs version |
| monitoring.selfMonitoring.podLogs.labels | object | `{}` | Additional PodLogs labels |
| monitoring.selfMonitoring.podLogs.relabelings | list | `[]` | PodLogs relabel configs to apply to samples before scraping https://github.com/prometheus-operator/prometheus-operator/blob/master/Documentation/api.md#relabelconfig |
| monitoring.selfMonitoring.tenant | object | `{"name":"self-monitoring","password":null,"secretNamespace":"{{ .Release.Namespace }}"}` | Tenant to use for self monitoring |
| monitoring.selfMonitoring.tenant.name | string | `"self-monitoring"` | Name of the tenant |
| monitoring.selfMonitoring.tenant.password | string | `nil` | Password of the gateway for Basic auth |
| monitoring.selfMonitoring.tenant.secretNamespace | string | `"{{ .Release.Namespace }}"` | Namespace to create additional tenant token secret in. Useful if your Grafana instance is in a separate namespace. Token will still be created in the canary namespace. |
| monitoring.serviceMonitor.annotations | object | `{}` | ServiceMonitor annotations |
| monitoring.serviceMonitor.enabled | bool | `false` | If enabled, ServiceMonitor resources for Prometheus Operator are created |
| monitoring.serviceMonitor.interval | string | `"15s"` | ServiceMonitor scrape interval Default is 15s because included recording rules use a 1m rate, and scrape interval needs to be at least 1/4 rate interval. |
| monitoring.serviceMonitor.labels | object | `{}` | Additional ServiceMonitor labels |
| monitoring.serviceMonitor.metricRelabelings | list | `[]` | ServiceMonitor metric relabel configs to apply to samples before ingestion https://github.com/prometheus-operator/prometheus-operator/blob/main/Documentation/api.md#endpoint |
| monitoring.serviceMonitor.metricsInstance | object | `{"annotations":{},"enabled":true,"labels":{},"remoteWrite":null}` | If defined, will create a MetricsInstance for the Grafana Agent Operator. |
| monitoring.serviceMonitor.metricsInstance.annotations | object | `{}` | MetricsInstance annotations |
| monitoring.serviceMonitor.metricsInstance.enabled | bool | `true` | If enabled, MetricsInstance resources for Grafana Agent Operator are created |
| monitoring.serviceMonitor.metricsInstance.labels | object | `{}` | Additional MetricsInstance labels |
| monitoring.serviceMonitor.metricsInstance.remoteWrite | string | `nil` | If defined a MetricsInstance will be created to remote write metrics. |
| monitoring.serviceMonitor.namespaceSelector | object | `{}` | Namespace selector for ServiceMonitor resources |
| monitoring.serviceMonitor.relabelings | list | `[]` | ServiceMonitor relabel configs to apply to samples before scraping https://github.com/prometheus-operator/prometheus-operator/blob/master/Documentation/api.md#relabelconfig |
| monitoring.serviceMonitor.scheme | string | `"http"` | ServiceMonitor will use http by default, but you can pick https as well |
| monitoring.serviceMonitor.scrapeTimeout | string | `nil` | ServiceMonitor scrape timeout in Go duration format (e.g. 15s) |
| monitoring.serviceMonitor.tlsConfig | string | `nil` | ServiceMonitor will use these tlsConfig settings to make the health check requests |
| nameOverride | string | `nil` | Overrides the chart's name |
| networkPolicy.alertmanager.namespaceSelector | object | `{}` | Specifies the namespace the alertmanager is running in |
| networkPolicy.alertmanager.podSelector | object | `{}` | Specifies the alertmanager Pods. As this is cross-namespace communication, you also need the namespaceSelector. |
| networkPolicy.alertmanager.port | int | `9093` | Specify the alertmanager port used for alerting |
| networkPolicy.discovery.namespaceSelector | object | `{}` | Specifies the namespace the discovery Pods are running in |
| networkPolicy.discovery.podSelector | object | `{}` | Specifies the Pods labels used for discovery. As this is cross-namespace communication, you also need the namespaceSelector. |
| networkPolicy.discovery.port | int | `nil` | Specify the port used for discovery |
| networkPolicy.egressKubeApiserver.enabled | bool | `false` | Enable additional cilium egress rules to kube-apiserver for backend. |
| networkPolicy.egressWorld.enabled | bool | `false` | Enable additional cilium egress rules to external world for write, read and backend. |
| networkPolicy.enabled | bool | `false` | Specifies whether Network Policies should be created |
| networkPolicy.externalStorage.cidrs | list | `[]` | Specifies specific network CIDRs you want to limit access to |
| networkPolicy.externalStorage.ports | list | `[]` | Specify the port used for external storage, e.g. AWS S3 |
| networkPolicy.flavor | string | `"kubernetes"` | Specifies whether the policies created will be standard Network Policies (flavor: kubernetes) or Cilium Network Policies (flavor: cilium) |
| networkPolicy.ingress.namespaceSelector | object | `{}` | Specifies the namespaces which are allowed to access the http port |
| networkPolicy.ingress.podSelector | object | `{}` | Specifies the Pods which are allowed to access the http port. As this is cross-namespace communication, you also need the namespaceSelector. |
| networkPolicy.metrics.cidrs | list | `[]` | Specifies specific network CIDRs which are allowed to access the metrics port. In case you use namespaceSelector, you also have to specify your kubelet networks here. The metrics ports are also used for probes. |
| networkPolicy.metrics.namespaceSelector | object | `{}` | Specifies the namespaces which are allowed to access the metrics port |
| networkPolicy.metrics.podSelector | object | `{}` | Specifies the Pods which are allowed to access the metrics port. As this is cross-namespace communication, you also need the namespaceSelector. |
| overridesExporter | object | `{"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"app.kubernetes.io/component":"overrides-exporter"}},"topologyKey":"kubernetes.io/hostname"}]}},"appProtocol":{"grpc":""},"command":null,"enabled":false,"extraArgs":[],"extraContainers":[],"extraEnv":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"hostAliases":[],"image":{"registry":null,"repository":null,"tag":null},"initContainers":[],"maxUnavailable":null,"nodeSelector":{},"podAnnotations":{},"podLabels":{},"priorityClassName":null,"replicas":0,"resources":{},"serviceAnnotations":{},"serviceLabels":{},"terminationGracePeriodSeconds":300,"tolerations":[],"topologySpreadConstraints":[]}` | Configuration for the overrides-exporter |
| overridesExporter.affinity | object | Hard node anti-affinity | Affinity for overrides-exporter pods. |
| overridesExporter.appProtocol | object | `{"grpc":""}` | Set the optional grpc service protocol. Ex: "grpc", "http2" or "https" |
| overridesExporter.command | string | `nil` | Command to execute instead of defined in Docker image |
| overridesExporter.enabled | bool | `false` | The overrides-exporter component is optional and can be disabled if desired. |
| overridesExporter.extraArgs | list | `[]` | Additional CLI args for the overrides-exporter |
| overridesExporter.extraContainers | list | `[]` | Containers to add to the overrides-exporter pods |
| overridesExporter.extraEnv | list | `[]` | Environment variables to add to the overrides-exporter pods |
| overridesExporter.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the overrides-exporter pods |
| overridesExporter.extraVolumeMounts | list | `[]` | Volume mounts to add to the overrides-exporter pods |
| overridesExporter.extraVolumes | list | `[]` | Volumes to add to the overrides-exporter pods |
| overridesExporter.hostAliases | list | `[]` | hostAliases to add |
| overridesExporter.image.registry | string | `nil` | The Docker registry for the overrides-exporter image. Overrides `loki.image.registry` |
| overridesExporter.image.repository | string | `nil` | Docker image repository for the overrides-exporter image. Overrides `loki.image.repository` |
| overridesExporter.image.tag | string | `nil` | Docker image tag for the overrides-exporter image. Overrides `loki.image.tag` |
| overridesExporter.initContainers | list | `[]` | Init containers to add to the overrides-exporter pods |
| overridesExporter.maxUnavailable | string | `nil` | Pod Disruption Budget maxUnavailable |
| overridesExporter.nodeSelector | object | `{}` | Node selector for overrides-exporter pods |
| overridesExporter.podAnnotations | object | `{}` | Annotations for overrides-exporter pods |
| overridesExporter.podLabels | object | `{}` | Labels for overrides-exporter pods |
| overridesExporter.priorityClassName | string | `nil` | The name of the PriorityClass for overrides-exporter pods |
| overridesExporter.replicas | int | `0` | Number of replicas for the overrides-exporter |
| overridesExporter.resources | object | `{}` | Resource requests and limits for the overrides-exporter |
| overridesExporter.serviceAnnotations | object | `{}` | Annotations for overrides-exporter service |
| overridesExporter.serviceLabels | object | `{}` | Labels for overrides-exporter service |
| overridesExporter.terminationGracePeriodSeconds | int | `300` | Grace period to allow the overrides-exporter to shutdown before it is killed |
| overridesExporter.tolerations | list | `[]` | Tolerations for overrides-exporter pods |
| overridesExporter.topologySpreadConstraints | list | `[]` | Topology Spread Constraints for overrides-exporter pods |
| patternIngester | object | `{"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"app.kubernetes.io/component":"pattern-ingester"}},"topologyKey":"kubernetes.io/hostname"}]}},"appProtocol":{"grpc":""},"command":null,"extraArgs":[],"extraContainers":[],"extraEnv":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"hostAliases":[],"image":{"registry":null,"repository":null,"tag":null},"initContainers":[],"livenessProbe":{},"nodeSelector":{},"persistence":{"annotations":{},"claims":[{"name":"data","size":"10Gi","storageClass":null}],"enableStatefulSetAutoDeletePVC":false,"enabled":false,"size":"10Gi","storageClass":null,"whenDeleted":"Retain","whenScaled":"Retain"},"podAnnotations":{},"podLabels":{},"priorityClassName":null,"readinessProbe":{},"replicas":0,"resources":{},"serviceAccount":{"annotations":{},"automountServiceAccountToken":true,"create":false,"imagePullSecrets":[],"name":null},"serviceAnnotations":{},"serviceLabels":{},"terminationGracePeriodSeconds":30,"tolerations":[],"topologySpreadConstraints":[]}` | Configuration for the pattern ingester |
| patternIngester.affinity | object | Hard node anti-affinity | Affinity for pattern ingester pods. |
| patternIngester.appProtocol | object | `{"grpc":""}` | Set the optional grpc service protocol. Ex: "grpc", "http2" or "https" |
| patternIngester.command | string | `nil` | Command to execute instead of defined in Docker image |
| patternIngester.extraArgs | list | `[]` | Additional CLI args for the pattern ingester |
| patternIngester.extraContainers | list | `[]` | Containers to add to the pattern ingester pods |
| patternIngester.extraEnv | list | `[]` | Environment variables to add to the pattern ingester pods |
| patternIngester.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the pattern ingester pods |
| patternIngester.extraVolumeMounts | list | `[]` | Volume mounts to add to the pattern ingester pods |
| patternIngester.extraVolumes | list | `[]` | Volumes to add to the pattern ingester pods |
| patternIngester.hostAliases | list | `[]` | hostAliases to add |
| patternIngester.image.registry | string | `nil` | The Docker registry for the pattern ingester image. Overrides `loki.image.registry` |
| patternIngester.image.repository | string | `nil` | Docker image repository for the pattern ingester image. Overrides `loki.image.repository` |
| patternIngester.image.tag | string | `nil` | Docker image tag for the pattern ingester image. Overrides `loki.image.tag` |
| patternIngester.initContainers | list | `[]` | Init containers to add to the pattern ingester pods |
| patternIngester.livenessProbe | object | `{}` | liveness probe settings for ingester pods. If empty use `loki.livenessProbe` |
| patternIngester.nodeSelector | object | `{}` | Node selector for pattern ingester pods |
| patternIngester.persistence.annotations | object | `{}` | Annotations for pattern ingester PVCs |
| patternIngester.persistence.claims | list |  | List of the pattern ingester PVCs |
| patternIngester.persistence.enableStatefulSetAutoDeletePVC | bool | `false` | Enable StatefulSetAutoDeletePVC feature |
| patternIngester.persistence.enabled | bool | `false` | Enable creating PVCs for the pattern ingester |
| patternIngester.persistence.size | string | `"10Gi"` | Size of persistent disk |
| patternIngester.persistence.storageClass | string | `nil` | Storage class to be used. If defined, storageClassName: <storageClass>. If set to "-", storageClassName: "", which disables dynamic provisioning. If empty or set to null, no storageClassName spec is set, choosing the default provisioner (gp2 on AWS, standard on GKE, AWS, and OpenStack). |
| patternIngester.podAnnotations | object | `{}` | Annotations for pattern ingester pods |
| patternIngester.podLabels | object | `{}` | Labels for pattern ingester pods |
| patternIngester.priorityClassName | string | `nil` | The name of the PriorityClass for pattern ingester pods |
| patternIngester.readinessProbe | object | `{}` | readiness probe settings for ingester pods. If empty, use `loki.readinessProbe` |
| patternIngester.replicas | int | `0` | Number of replicas for the pattern ingester |
| patternIngester.resources | object | `{}` | Resource requests and limits for the pattern ingester |
| patternIngester.serviceAccount.annotations | object | `{}` | Annotations for the pattern ingester service account |
| patternIngester.serviceAccount.automountServiceAccountToken | bool | `true` | Set this toggle to false to opt out of automounting API credentials for the service account |
| patternIngester.serviceAccount.imagePullSecrets | list | `[]` | Image pull secrets for the pattern ingester service account |
| patternIngester.serviceAccount.name | string | `nil` | The name of the ServiceAccount to use for the pattern ingester. If not set and create is true, a name is generated by appending "-pattern-ingester" to the common ServiceAccount. |
| patternIngester.serviceAnnotations | object | `{}` | Annotations for pattern ingester service |
| patternIngester.serviceLabels | object | `{}` | Labels for pattern ingester service |
| patternIngester.terminationGracePeriodSeconds | int | `30` | Grace period to allow the pattern ingester to shutdown before it is killed |
| patternIngester.tolerations | list | `[]` | Tolerations for pattern ingester pods |
| patternIngester.topologySpreadConstraints | list | `[]` | Topology Spread Constraints for pattern ingester pods |
| querier | object | `{"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"app.kubernetes.io/component":"querier"}},"topologyKey":"kubernetes.io/hostname"}]}},"appProtocol":{"grpc":""},"autoscaling":{"behavior":{"enabled":false,"scaleDown":{},"scaleUp":{}},"customMetrics":[],"enabled":false,"maxReplicas":3,"minReplicas":1,"targetCPUUtilizationPercentage":60,"targetMemoryUtilizationPercentage":null},"command":null,"dnsConfig":{},"extraArgs":[],"extraContainers":[],"extraEnv":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"hostAliases":[],"image":{"registry":null,"repository":null,"tag":null},"initContainers":[],"maxSurge":0,"maxUnavailable":null,"nodeSelector":{},"persistence":{"annotations":{},"enabled":false,"size":"10Gi","storageClass":null},"podAnnotations":{},"podLabels":{},"priorityClassName":null,"replicas":0,"resources":{},"serviceAnnotations":{},"serviceLabels":{},"terminationGracePeriodSeconds":30,"tolerations":[],"topologySpreadConstraints":[{"labelSelector":{"matchLabels":{"app.kubernetes.io/component":"querier"}},"maxSkew":1,"topologyKey":"kubernetes.io/hostname","whenUnsatisfiable":"ScheduleAnyway"}]}` | Configuration for the querier |
| querier.affinity | object | Hard node anti-affinity | Affinity for querier pods. |
| querier.appProtocol | object | `{"grpc":""}` | Adds the appProtocol field to the querier service. This allows querier to work with istio protocol selection. |
| querier.appProtocol.grpc | string | `""` | Set the optional grpc service protocol. Ex: "grpc", "http2" or "https" |
| querier.autoscaling.behavior.enabled | bool | `false` | Enable autoscaling behaviours |
| querier.autoscaling.behavior.scaleDown | object | `{}` | define scale down policies, must conform to HPAScalingRules |
| querier.autoscaling.behavior.scaleUp | object | `{}` | define scale up policies, must conform to HPAScalingRules |
| querier.autoscaling.customMetrics | list | `[]` | Allows one to define custom metrics using the HPA/v2 schema (for example, Pods, Object or External metrics) |
| querier.autoscaling.enabled | bool | `false` | Enable autoscaling for the querier, this is only used if `indexGateway.enabled: true` |
| querier.autoscaling.maxReplicas | int | `3` | Maximum autoscaling replicas for the querier |
| querier.autoscaling.minReplicas | int | `1` | Minimum autoscaling replicas for the querier |
| querier.autoscaling.targetCPUUtilizationPercentage | int | `60` | Target CPU utilisation percentage for the querier |
| querier.autoscaling.targetMemoryUtilizationPercentage | string | `nil` | Target memory utilisation percentage for the querier |
| querier.command | string | `nil` | Command to execute instead of defined in Docker image |
| querier.dnsConfig | object | `{}` | DNSConfig for querier pods |
| querier.extraArgs | list | `[]` | Additional CLI args for the querier |
| querier.extraContainers | list | `[]` | Containers to add to the querier pods |
| querier.extraEnv | list | `[]` | Environment variables to add to the querier pods |
| querier.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the querier pods |
| querier.extraVolumeMounts | list | `[]` | Volume mounts to add to the querier pods |
| querier.extraVolumes | list | `[]` | Volumes to add to the querier pods |
| querier.hostAliases | list | `[]` | hostAliases to add |
| querier.image.registry | string | `nil` | The Docker registry for the querier image. Overrides `loki.image.registry` |
| querier.image.repository | string | `nil` | Docker image repository for the querier image. Overrides `loki.image.repository` |
| querier.image.tag | string | `nil` | Docker image tag for the querier image. Overrides `loki.image.tag` |
| querier.initContainers | list | `[]` | Init containers to add to the querier pods |
| querier.maxSurge | int | `0` | Max Surge for querier pods |
| querier.maxUnavailable | string | `nil` | Pod Disruption Budget maxUnavailable |
| querier.nodeSelector | object | `{}` | Node selector for querier pods |
| querier.persistence.annotations | object | `{}` | Annotations for querier PVCs |
| querier.persistence.enabled | bool | `false` | Enable creating PVCs for the querier cache |
| querier.persistence.size | string | `"10Gi"` | Size of persistent disk |
| querier.persistence.storageClass | string | `nil` | Storage class to be used. If defined, storageClassName: <storageClass>. If set to "-", storageClassName: "", which disables dynamic provisioning. If empty or set to null, no storageClassName spec is set, choosing the default provisioner (gp2 on AWS, standard on GKE, AWS, and OpenStack). |
| querier.podAnnotations | object | `{}` | Annotations for querier pods |
| querier.podLabels | object | `{}` | Labels for querier pods |
| querier.priorityClassName | string | `nil` | The name of the PriorityClass for querier pods |
| querier.replicas | int | `0` | Number of replicas for the querier |
| querier.resources | object | `{}` | Resource requests and limits for the querier |
| querier.serviceAnnotations | object | `{}` | Annotations for querier service |
| querier.serviceLabels | object | `{}` | Labels for querier service |
| querier.terminationGracePeriodSeconds | int | `30` | Grace period to allow the querier to shutdown before it is killed |
| querier.tolerations | list | `[]` | Tolerations for querier pods |
| querier.topologySpreadConstraints | list | Defaults to allow skew no more then 1 node | topologySpread for querier pods. |
| queryFrontend | object | `{"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"app.kubernetes.io/component":"query-frontend"}},"topologyKey":"kubernetes.io/hostname"}]}},"appProtocol":{"grpc":""},"autoscaling":{"behavior":{"enabled":false,"scaleDown":{},"scaleUp":{}},"customMetrics":[],"enabled":false,"maxReplicas":3,"minReplicas":1,"targetCPUUtilizationPercentage":60,"targetMemoryUtilizationPercentage":null},"command":null,"extraArgs":[],"extraContainers":[],"extraEnv":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"hostAliases":[],"image":{"registry":null,"repository":null,"tag":null},"maxUnavailable":null,"nodeSelector":{},"podAnnotations":{},"podLabels":{},"priorityClassName":null,"replicas":0,"resources":{},"serviceAnnotations":{},"serviceLabels":{},"terminationGracePeriodSeconds":30,"tolerations":[],"topologySpreadConstraints":[]}` | Configuration for the query-frontend |
| queryFrontend.affinity | object | Hard node anti-affinity | Affinity for query-frontend pods. |
| queryFrontend.appProtocol | object | `{"grpc":""}` | Adds the appProtocol field to the queryFrontend service. This allows queryFrontend to work with istio protocol selection. |
| queryFrontend.appProtocol.grpc | string | `""` | Set the optional grpc service protocol. Ex: "grpc", "http2" or "https" |
| queryFrontend.autoscaling.behavior.enabled | bool | `false` | Enable autoscaling behaviours |
| queryFrontend.autoscaling.behavior.scaleDown | object | `{}` | define scale down policies, must conform to HPAScalingRules |
| queryFrontend.autoscaling.behavior.scaleUp | object | `{}` | define scale up policies, must conform to HPAScalingRules |
| queryFrontend.autoscaling.customMetrics | list | `[]` | Allows one to define custom metrics using the HPA/v2 schema (for example, Pods, Object or External metrics) |
| queryFrontend.autoscaling.enabled | bool | `false` | Enable autoscaling for the query-frontend |
| queryFrontend.autoscaling.maxReplicas | int | `3` | Maximum autoscaling replicas for the query-frontend |
| queryFrontend.autoscaling.minReplicas | int | `1` | Minimum autoscaling replicas for the query-frontend |
| queryFrontend.autoscaling.targetCPUUtilizationPercentage | int | `60` | Target CPU utilisation percentage for the query-frontend |
| queryFrontend.autoscaling.targetMemoryUtilizationPercentage | string | `nil` | Target memory utilisation percentage for the query-frontend |
| queryFrontend.command | string | `nil` | Command to execute instead of defined in Docker image |
| queryFrontend.extraArgs | list | `[]` | Additional CLI args for the query-frontend |
| queryFrontend.extraContainers | list | `[]` | Containers to add to the query-frontend pods |
| queryFrontend.extraEnv | list | `[]` | Environment variables to add to the query-frontend pods |
| queryFrontend.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the query-frontend pods |
| queryFrontend.extraVolumeMounts | list | `[]` | Volume mounts to add to the query-frontend pods |
| queryFrontend.extraVolumes | list | `[]` | Volumes to add to the query-frontend pods |
| queryFrontend.hostAliases | list | `[]` | hostAliases to add |
| queryFrontend.image.registry | string | `nil` | The Docker registry for the query-frontend image. Overrides `loki.image.registry` |
| queryFrontend.image.repository | string | `nil` | Docker image repository for the query-frontend image. Overrides `loki.image.repository` |
| queryFrontend.image.tag | string | `nil` | Docker image tag for the query-frontend image. Overrides `loki.image.tag` |
| queryFrontend.maxUnavailable | string | `nil` | Pod Disruption Budget maxUnavailable |
| queryFrontend.nodeSelector | object | `{}` | Node selector for query-frontend pods |
| queryFrontend.podAnnotations | object | `{}` | Annotations for query-frontend pods |
| queryFrontend.podLabels | object | `{}` | Labels for query-frontend pods |
| queryFrontend.priorityClassName | string | `nil` | The name of the PriorityClass for query-frontend pods |
| queryFrontend.replicas | int | `0` | Number of replicas for the query-frontend |
| queryFrontend.resources | object | `{}` | Resource requests and limits for the query-frontend |
| queryFrontend.serviceAnnotations | object | `{}` | Annotations for query-frontend service |
| queryFrontend.serviceLabels | object | `{}` | Labels for query-frontend service |
| queryFrontend.terminationGracePeriodSeconds | int | `30` | Grace period to allow the query-frontend to shutdown before it is killed |
| queryFrontend.tolerations | list | `[]` | Tolerations for query-frontend pods |
| queryFrontend.topologySpreadConstraints | list | `[]` | Topology Spread Constraints for query-frontend pods |
| queryScheduler | object | `{"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"app.kubernetes.io/component":"query-scheduler"}},"topologyKey":"kubernetes.io/hostname"}]}},"appProtocol":{"grpc":""},"extraArgs":[],"extraContainers":[],"extraEnv":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"hostAliases":[],"image":{"registry":null,"repository":null,"tag":null},"maxUnavailable":1,"nodeSelector":{},"podAnnotations":{},"podLabels":{},"priorityClassName":null,"replicas":0,"resources":{},"serviceAnnotations":{},"serviceLabels":{},"terminationGracePeriodSeconds":30,"tolerations":[],"topologySpreadConstraints":[]}` | Configuration for the query-scheduler |
| queryScheduler.affinity | object | Hard node anti-affinity | Affinity for query-scheduler pods. |
| queryScheduler.appProtocol | object | `{"grpc":""}` | Set the optional grpc service protocol. Ex: "grpc", "http2" or "https" |
| queryScheduler.extraArgs | list | `[]` | Additional CLI args for the query-scheduler |
| queryScheduler.extraContainers | list | `[]` | Containers to add to the query-scheduler pods |
| queryScheduler.extraEnv | list | `[]` | Environment variables to add to the query-scheduler pods |
| queryScheduler.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the query-scheduler pods |
| queryScheduler.extraVolumeMounts | list | `[]` | Volume mounts to add to the query-scheduler pods |
| queryScheduler.extraVolumes | list | `[]` | Volumes to add to the query-scheduler pods |
| queryScheduler.hostAliases | list | `[]` | hostAliases to add |
| queryScheduler.image.registry | string | `nil` | The Docker registry for the query-scheduler image. Overrides `loki.image.registry` |
| queryScheduler.image.repository | string | `nil` | Docker image repository for the query-scheduler image. Overrides `loki.image.repository` |
| queryScheduler.image.tag | string | `nil` | Docker image tag for the query-scheduler image. Overrides `loki.image.tag` |
| queryScheduler.maxUnavailable | int | `1` | Pod Disruption Budget maxUnavailable |
| queryScheduler.nodeSelector | object | `{}` | Node selector for query-scheduler pods |
| queryScheduler.podAnnotations | object | `{}` | Annotations for query-scheduler pods |
| queryScheduler.podLabels | object | `{}` | Labels for query-scheduler pods |
| queryScheduler.priorityClassName | string | `nil` | The name of the PriorityClass for query-scheduler pods |
| queryScheduler.replicas | int | `0` | Number of replicas for the query-scheduler. It should be lower than `-querier.max-concurrent` to avoid generating back-pressure in queriers; it's also recommended that this value evenly divides the latter |
| queryScheduler.resources | object | `{}` | Resource requests and limits for the query-scheduler |
| queryScheduler.serviceAnnotations | object | `{}` | Annotations for query-scheduler service |
| queryScheduler.serviceLabels | object | `{}` | Labels for query-scheduler service |
| queryScheduler.terminationGracePeriodSeconds | int | `30` | Grace period to allow the query-scheduler to shutdown before it is killed |
| queryScheduler.tolerations | list | `[]` | Tolerations for query-scheduler pods |
| queryScheduler.topologySpreadConstraints | list | `[]` | Topology Spread Constraints for query-scheduler pods |
| rbac.namespaced | bool | `false` | Whether to install RBAC in the namespace only or cluster-wide. Useful if you want to watch ConfigMap globally. |
| rbac.pspAnnotations | object | `{}` | Specify PSP annotations Ref: https://kubernetes.io/docs/reference/access-authn-authz/psp-to-pod-security-standards/#podsecuritypolicy-annotations |
| rbac.pspEnabled | bool | `false` | If pspEnabled true, a PodSecurityPolicy is created for K8s that use psp. |
| rbac.sccEnabled | bool | `false` | For OpenShift set pspEnabled to 'false' and sccEnabled to 'true' to use the SecurityContextConstraints. |
| read | object | `{"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"app.kubernetes.io/component":"read"}},"topologyKey":"kubernetes.io/hostname"}]}},"annotations":{},"autoscaling":{"behavior":{},"enabled":false,"maxReplicas":6,"minReplicas":2,"targetCPUUtilizationPercentage":60,"targetMemoryUtilizationPercentage":null},"dnsConfig":{},"extraArgs":[],"extraContainers":[],"extraEnv":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"image":{"registry":null,"repository":null,"tag":null},"legacyReadTarget":false,"lifecycle":{},"nodeSelector":{},"persistence":{"annotations":{},"enableStatefulSetAutoDeletePVC":true,"selector":null,"size":"10Gi","storageClass":null},"podAnnotations":{},"podLabels":{},"podManagementPolicy":"Parallel","priorityClassName":null,"replicas":3,"resources":{},"selectorLabels":{},"service":{"annotations":{},"labels":{}},"targetModule":"read","terminationGracePeriodSeconds":30,"tolerations":[],"topologySpreadConstraints":[]}` | Configuration for the read pod(s) |
| read.affinity | object | Hard node anti-affinity | Affinity for read pods. |
| read.annotations | object | `{}` | Annotations for read deployment |
| read.autoscaling.behavior | object | `{}` | Behavior policies while scaling. |
| read.autoscaling.enabled | bool | `false` | Enable autoscaling for the read, this is only used if `queryIndex.enabled: true` |
| read.autoscaling.maxReplicas | int | `6` | Maximum autoscaling replicas for the read |
| read.autoscaling.minReplicas | int | `2` | Minimum autoscaling replicas for the read |
| read.autoscaling.targetCPUUtilizationPercentage | int | `60` | Target CPU utilisation percentage for the read |
| read.autoscaling.targetMemoryUtilizationPercentage | string | `nil` | Target memory utilisation percentage for the read |
| read.dnsConfig | object | `{}` | DNS config for read pods |
| read.extraArgs | list | `[]` | Additional CLI args for the read |
| read.extraContainers | list | `[]` | Containers to add to the read pods |
| read.extraEnv | list | `[]` | Environment variables to add to the read pods |
| read.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the read pods |
| read.extraVolumeMounts | list | `[]` | Volume mounts to add to the read pods |
| read.extraVolumes | list | `[]` | Volumes to add to the read pods |
| read.image.registry | string | `nil` | The Docker registry for the read image. Overrides `loki.image.registry` |
| read.image.repository | string | `nil` | Docker image repository for the read image. Overrides `loki.image.repository` |
| read.image.tag | string | `nil` | Docker image tag for the read image. Overrides `loki.image.tag` |
| read.legacyReadTarget | bool | `false` | Whether or not to use the 2 target type simple scalable mode (read, write) or the 3 target type (read, write, backend). Legacy refers to the 2 target type, so true will run two targets, false will run 3 targets. |
| read.lifecycle | object | `{}` | Lifecycle for the read container |
| read.nodeSelector | object | `{}` | Node selector for read pods |
| read.persistence | object | `{"annotations":{},"enableStatefulSetAutoDeletePVC":true,"selector":null,"size":"10Gi","storageClass":null}` | read.persistence is used only if legacyReadTarget is set to true |
| read.persistence.annotations | object | `{}` | Annotations for volume claim |
| read.persistence.enableStatefulSetAutoDeletePVC | bool | `true` | Enable StatefulSetAutoDeletePVC feature |
| read.persistence.selector | string | `nil` | Selector for persistent disk |
| read.persistence.size | string | `"10Gi"` | Size of persistent disk |
| read.persistence.storageClass | string | `nil` | Storage class to be used. If defined, storageClassName: <storageClass>. If set to "-", storageClassName: "", which disables dynamic provisioning. If empty or set to null, no storageClassName spec is set, choosing the default provisioner (gp2 on AWS, standard on GKE, AWS, and OpenStack). |
| read.podAnnotations | object | `{}` | Annotations for read pods |
| read.podLabels | object | `{}` | Additional labels for each `read` pod |
| read.podManagementPolicy | string | `"Parallel"` | The default is to deploy all pods in parallel. |
| read.priorityClassName | string | `nil` | The name of the PriorityClass for read pods |
| read.replicas | int | `3` | Number of replicas for the read |
| read.resources | object | `{}` | Resource requests and limits for the read |
| read.selectorLabels | object | `{}` | Additional selector labels for each `read` pod |
| read.service.annotations | object | `{}` | Annotations for read Service |
| read.service.labels | object | `{}` | Additional labels for read Service |
| read.targetModule | string | `"read"` | Comma-separated list of Loki modules to load for the read |
| read.terminationGracePeriodSeconds | int | `30` | Grace period to allow the read to shutdown before it is killed |
| read.tolerations | list | `[]` | Tolerations for read pods |
| read.topologySpreadConstraints | list | `[]` | Topology Spread Constraints for read pods |
| resultsCache.affinity | object | `{}` | Affinity for results-cache pods |
| resultsCache.allocatedMemory | int | `1024` | Amount of memory allocated to results-cache for object storage (in MB). |
| resultsCache.annotations | object | `{}` | Annotations for the results-cache pods |
| resultsCache.connectionLimit | int | `16384` | Maximum number of connections allowed |
| resultsCache.defaultValidity | string | `"12h"` | Specify how long cached results should be stored in the results-cache before being expired |
| resultsCache.enabled | bool | `true` | Specifies whether memcached based results-cache should be enabled |
| resultsCache.extraArgs | object | `{}` | Additional CLI args for results-cache |
| resultsCache.extraContainers | list | `[]` | Additional containers to be added to the results-cache pod. |
| resultsCache.extraExtendedOptions | string | `""` | Add extended options for results-cache memcached container. The format is the same as for the memcached -o/--extend flag. Example: extraExtendedOptions: 'tls,modern,track_sizes' |
| resultsCache.extraVolumeMounts | list | `[]` | Additional volume mounts to be added to the results-cache pod (applies to both memcached and exporter containers). Example: extraVolumeMounts: - name: extra-volume   mountPath: /etc/extra-volume   readOnly: true |
| resultsCache.extraVolumes | list | `[]` | Additional volumes to be added to the results-cache pod (applies to both memcached and exporter containers). Example: extraVolumes: - name: extra-volume   secret:    secretName: extra-volume-secret |
| resultsCache.initContainers | list | `[]` | Extra init containers for results-cache pods |
| resultsCache.maxItemMemory | int | `5` | Maximum item results-cache for memcached (in MB). |
| resultsCache.nodeSelector | object | `{}` | Node selector for results-cache pods |
| resultsCache.persistence | object | `{"enabled":false,"mountPath":"/data","storageClass":null,"storageSize":"10G"}` | Persistence settings for the results-cache |
| resultsCache.persistence.enabled | bool | `false` | Enable creating PVCs for the results-cache |
| resultsCache.persistence.mountPath | string | `"/data"` | Volume mount path |
| resultsCache.persistence.storageClass | string | `nil` | Storage class to be used. If defined, storageClassName: <storageClass>. If set to "-", storageClassName: "", which disables dynamic provisioning. If empty or set to null, no storageClassName spec is set, choosing the default provisioner (gp2 on AWS, standard on GKE, AWS, and OpenStack). |
| resultsCache.persistence.storageSize | string | `"10G"` | Size of persistent disk, must be in G or Gi |
| resultsCache.podAnnotations | object | `{}` | Annotations for results-cache pods |
| resultsCache.podDisruptionBudget | object | `{"maxUnavailable":1}` | Pod Disruption Budget |
| resultsCache.podLabels | object | `{}` | Labels for results-cache pods |
| resultsCache.podManagementPolicy | string | `"Parallel"` | Management policy for results-cache pods |
| resultsCache.port | int | `11211` | Port of the results-cache service |
| resultsCache.priorityClassName | string | `nil` | The name of the PriorityClass for results-cache pods |
| resultsCache.replicas | int | `1` | Total number of results-cache replicas |
| resultsCache.resources | string | `nil` | Resource requests and limits for the results-cache By default a safe memory limit will be requested based on allocatedMemory value (floor (* 1.2 allocatedMemory)). |
| resultsCache.service | object | `{"annotations":{},"labels":{}}` | Service annotations and labels |
| resultsCache.statefulStrategy | object | `{"type":"RollingUpdate"}` | Stateful results-cache strategy |
| resultsCache.terminationGracePeriodSeconds | int | `60` | Grace period to allow the results-cache to shutdown before it is killed |
| resultsCache.timeout | string | `"500ms"` | Memcached operation timeout |
| resultsCache.tolerations | list | `[]` | Tolerations for results-cache pods |
| resultsCache.topologySpreadConstraints | list | `[]` | topologySpreadConstraints allows to customize the default topologySpreadConstraints. This can be either a single dict as shown below or a slice of topologySpreadConstraints. labelSelector is taken from the constraint itself (if it exists) or is generated by the chart using the same selectors as for services. |
| resultsCache.writebackBuffer | int | `500000` | Max number of objects to use for cache write back |
| resultsCache.writebackParallelism | int | `1` | Number of parallel threads for cache write back |
| resultsCache.writebackSizeLimit | string | `"500MB"` | Max memory to use for cache write back |
| rollout_operator | object | `{"enabled":false,"podSecurityContext":{"fsGroup":10001,"runAsGroup":10001,"runAsNonRoot":true,"runAsUser":10001,"seccompProfile":{"type":"RuntimeDefault"}},"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true}}` | Setting for the Grafana Rollout Operator https://github.com/grafana/helm-charts/tree/main/charts/rollout-operator |
| rollout_operator.podSecurityContext | object | `{"fsGroup":10001,"runAsGroup":10001,"runAsNonRoot":true,"runAsUser":10001,"seccompProfile":{"type":"RuntimeDefault"}}` | podSecurityContext is the pod security context for the rollout operator. When installing on OpenShift, override podSecurityContext settings with  rollout_operator:   podSecurityContext:     fsGroup: null     runAsGroup: null     runAsUser: null |
| ruler | object | `{"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"app.kubernetes.io/component":"ruler"}},"topologyKey":"kubernetes.io/hostname"}]}},"appProtocol":{"grpc":""},"command":null,"directories":{},"dnsConfig":{},"enabled":true,"extraArgs":[],"extraContainers":[],"extraEnv":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"hostAliases":[],"image":{"registry":null,"repository":null,"tag":null},"initContainers":[],"maxUnavailable":null,"nodeSelector":{},"persistence":{"annotations":{},"enabled":false,"size":"10Gi","storageClass":null},"podAnnotations":{},"podLabels":{},"priorityClassName":null,"replicas":0,"resources":{},"serviceAnnotations":{},"serviceLabels":{},"terminationGracePeriodSeconds":300,"tolerations":[],"topologySpreadConstraints":[]}` | Configuration for the ruler |
| ruler.affinity | object | Hard node anti-affinity | Affinity for ruler pods. |
| ruler.appProtocol | object | `{"grpc":""}` | Set the optional grpc service protocol. Ex: "grpc", "http2" or "https" |
| ruler.command | string | `nil` | Command to execute instead of defined in Docker image |
| ruler.directories | object | `{}` | Directories containing rules files |
| ruler.dnsConfig | object | `{}` | DNSConfig for ruler pods |
| ruler.enabled | bool | `true` | The ruler component is optional and can be disabled if desired. |
| ruler.extraArgs | list | `[]` | Additional CLI args for the ruler |
| ruler.extraContainers | list | `[]` | Containers to add to the ruler pods |
| ruler.extraEnv | list | `[]` | Environment variables to add to the ruler pods |
| ruler.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the ruler pods |
| ruler.extraVolumeMounts | list | `[]` | Volume mounts to add to the ruler pods |
| ruler.extraVolumes | list | `[]` | Volumes to add to the ruler pods |
| ruler.hostAliases | list | `[]` | hostAliases to add |
| ruler.image.registry | string | `nil` | The Docker registry for the ruler image. Overrides `loki.image.registry` |
| ruler.image.repository | string | `nil` | Docker image repository for the ruler image. Overrides `loki.image.repository` |
| ruler.image.tag | string | `nil` | Docker image tag for the ruler image. Overrides `loki.image.tag` |
| ruler.initContainers | list | `[]` | Init containers to add to the ruler pods |
| ruler.maxUnavailable | string | `nil` | Pod Disruption Budget maxUnavailable |
| ruler.nodeSelector | object | `{}` | Node selector for ruler pods |
| ruler.persistence.annotations | object | `{}` | Annotations for ruler PVCs |
| ruler.persistence.enabled | bool | `false` | Enable creating PVCs which is required when using recording rules |
| ruler.persistence.size | string | `"10Gi"` | Size of persistent disk |
| ruler.persistence.storageClass | string | `nil` | Storage class to be used. If defined, storageClassName: <storageClass>. If set to "-", storageClassName: "", which disables dynamic provisioning. If empty or set to null, no storageClassName spec is set, choosing the default provisioner (gp2 on AWS, standard on GKE, AWS, and OpenStack). |
| ruler.podAnnotations | object | `{}` | Annotations for ruler pods |
| ruler.podLabels | object | `{}` | Labels for compactor pods |
| ruler.priorityClassName | string | `nil` | The name of the PriorityClass for ruler pods |
| ruler.replicas | int | `0` | Number of replicas for the ruler |
| ruler.resources | object | `{}` | Resource requests and limits for the ruler |
| ruler.serviceAnnotations | object | `{}` | Annotations for ruler service |
| ruler.serviceLabels | object | `{}` | Labels for ruler service |
| ruler.terminationGracePeriodSeconds | int | `300` | Grace period to allow the ruler to shutdown before it is killed |
| ruler.tolerations | list | `[]` | Tolerations for ruler pods |
| ruler.topologySpreadConstraints | list | `[]` | Topology Spread Constraints for ruler pods |
| serviceAccount.annotations | object | `{}` | Annotations for the service account |
| serviceAccount.automountServiceAccountToken | bool | `true` | Set this toggle to false to opt out of automounting API credentials for the service account |
| serviceAccount.create | bool | `true` | Specifies whether a ServiceAccount should be created |
| serviceAccount.imagePullSecrets | list | `[]` | Image pull secrets for the service account |
| serviceAccount.labels | object | `{}` | Labels for the service account |
| serviceAccount.name | string | `nil` | The name of the ServiceAccount to use. If not set and create is true, a name is generated using the fullname template |
| sidecar.enableUniqueFilenames | bool | `false` | Ensure that rule files aren't conflicting and being overwritten by prefixing their name with the namespace they are defined in. |
| sidecar.image.pullPolicy | string | `"IfNotPresent"` | Docker image pull policy |
| sidecar.image.repository | string | `"kiwigrid/k8s-sidecar"` | The Docker registry and image for the k8s sidecar |
| sidecar.image.sha | string | `""` | Docker image sha. If empty, no sha will be used |
| sidecar.image.tag | string | `"1.29.1"` | Docker image tag |
| sidecar.livenessProbe | object | `{}` | Liveness probe definition. Probe is disabled on the sidecar by default. |
| sidecar.readinessProbe | object | `{}` | Readiness probe definition. Probe is disabled on the sidecar by default. |
| sidecar.resources | object | `{}` | Resource requests and limits for the sidecar |
| sidecar.rules.enabled | bool | `true` | Whether or not to create a sidecar to ingest rule from specific ConfigMaps and/or Secrets. |
| sidecar.rules.folder | string | `"/rules"` | Folder into which the rules will be placed. |
| sidecar.rules.label | string | `"loki_rule"` | Label that the configmaps/secrets with rules will be marked with. |
| sidecar.rules.labelValue | string | `""` | Label value that the configmaps/secrets with rules will be set to. |
| sidecar.rules.logLevel | string | `"INFO"` | Log level of the sidecar container. |
| sidecar.rules.resource | string | `"both"` | Search in configmap, secret, or both. |
| sidecar.rules.script | string | `nil` | Absolute path to the shell script to execute after a configmap or secret has been reloaded. |
| sidecar.rules.searchNamespace | string | `nil` | Comma separated list of namespaces. If specified, the sidecar will search for config-maps/secrets inside these namespaces. Otherwise the namespace in which the sidecar is running will be used. It's also possible to specify 'ALL' to search in all namespaces. |
| sidecar.rules.watchClientTimeout | int | `60` | WatchClientTimeout: is a client-side timeout, configuring your local socket. If you have a network outage dropping all packets with no RST/FIN, this is how long your client waits before realizing & dropping the connection. Defaults to 66sec. |
| sidecar.rules.watchMethod | string | `"WATCH"` | Method to use to detect ConfigMap changes. With WATCH the sidecar will do a WATCH request, with SLEEP it will list all ConfigMaps, then sleep for 60 seconds. |
| sidecar.rules.watchServerTimeout | int | `60` | WatchServerTimeout: request to the server, asking it to cleanly close the connection after that. defaults to 60sec; much higher values like 3600 seconds (1h) are feasible for non-Azure K8S. |
| sidecar.securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true}` | The SecurityContext for the sidecar. |
| sidecar.skipTlsVerify | bool | `false` | Set to true to skip tls verification for kube api calls. |
| singleBinary.affinity | object | Hard node anti-affinity | Affinity for single binary pods. |
| singleBinary.annotations | object | `{}` | Annotations for single binary StatefulSet |
| singleBinary.autoscaling.enabled | bool | `false` | Enable autoscaling |
| singleBinary.autoscaling.maxReplicas | int | `3` | Maximum autoscaling replicas for the single binary |
| singleBinary.autoscaling.minReplicas | int | `1` | Minimum autoscaling replicas for the single binary |
| singleBinary.autoscaling.targetCPUUtilizationPercentage | int | `60` | Target CPU utilisation percentage for the single binary |
| singleBinary.autoscaling.targetMemoryUtilizationPercentage | string | `nil` | Target memory utilisation percentage for the single binary |
| singleBinary.dnsConfig | object | `{}` | DNS config for single binary pods |
| singleBinary.extraArgs | list | `[]` | Labels for single binary service |
| singleBinary.extraContainers | list | `[]` | Extra containers to add to the single binary loki pod |
| singleBinary.extraEnv | list | `[]` | Environment variables to add to the single binary pods |
| singleBinary.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the single binary pods |
| singleBinary.extraVolumeMounts | list | `[]` | Volume mounts to add to the single binary pods |
| singleBinary.extraVolumes | list | `[]` | Volumes to add to the single binary pods |
| singleBinary.image.registry | string | `nil` | The Docker registry for the single binary image. Overrides `loki.image.registry` |
| singleBinary.image.repository | string | `nil` | Docker image repository for the single binary image. Overrides `loki.image.repository` |
| singleBinary.image.tag | string | `nil` | Docker image tag for the single binary image. Overrides `loki.image.tag` |
| singleBinary.initContainers | list | `[]` | Init containers to add to the single binary pods |
| singleBinary.nodeSelector | object | `{}` | Node selector for single binary pods |
| singleBinary.persistence.annotations | object | `{}` | Annotations for volume claim |
| singleBinary.persistence.enableStatefulSetAutoDeletePVC | bool | `true` | Enable StatefulSetAutoDeletePVC feature |
| singleBinary.persistence.enabled | bool | `true` | Enable persistent disk |
| singleBinary.persistence.selector | string | `nil` | Selector for persistent disk |
| singleBinary.persistence.size | string | `"10Gi"` | Size of persistent disk |
| singleBinary.persistence.storageClass | string | `nil` | Storage class to be used. If defined, storageClassName: <storageClass>. If set to "-", storageClassName: "", which disables dynamic provisioning. If empty or set to null, no storageClassName spec is set, choosing the default provisioner (gp2 on AWS, standard on GKE, AWS, and OpenStack). |
| singleBinary.podAnnotations | object | `{}` | Annotations for single binary pods |
| singleBinary.podLabels | object | `{}` | Additional labels for each `single binary` pod |
| singleBinary.priorityClassName | string | `nil` | The name of the PriorityClass for single binary pods |
| singleBinary.replicas | int | `0` | Number of replicas for the single binary |
| singleBinary.resources | object | `{}` | Resource requests and limits for the single binary |
| singleBinary.selectorLabels | object | `{}` | Additional selector labels for each `single binary` pod |
| singleBinary.service.annotations | object | `{}` | Annotations for single binary Service |
| singleBinary.service.labels | object | `{}` | Additional labels for single binary Service |
| singleBinary.targetModule | string | `"all"` | Comma-separated list of Loki modules to load for the single binary |
| singleBinary.terminationGracePeriodSeconds | int | `30` | Grace period to allow the single binary to shutdown before it is killed |
| singleBinary.tolerations | list | `[]` | Tolerations for single binary pods |
| tableManager | object | `{"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"app.kubernetes.io/component":"table-manager"}},"topologyKey":"kubernetes.io/hostname"}]}},"annotations":{},"command":null,"dnsConfig":{},"enabled":false,"extraArgs":[],"extraContainers":[],"extraEnv":[],"extraEnvFrom":[],"extraVolumeMounts":[],"extraVolumes":[],"image":{"registry":null,"repository":null,"tag":null},"nodeSelector":{},"podAnnotations":{},"podLabels":{},"priorityClassName":null,"resources":{},"retention_deletes_enabled":false,"retention_period":0,"service":{"annotations":{},"labels":{}},"terminationGracePeriodSeconds":30,"tolerations":[]}` | DEPRECATED Configuration for the table-manager. The table-manager is only necessary when using a deprecated index type such as Cassandra, Bigtable, or DynamoDB, it has not been necessary since loki introduced self- contained index types like 'boltdb-shipper' and 'tsdb'. This will be removed in a future helm chart. |
| tableManager.affinity | object | Hard node and anti-affinity | Affinity for table-manager pods. |
| tableManager.annotations | object | `{}` | Annotations for table-manager deployment |
| tableManager.command | string | `nil` | Command to execute instead of defined in Docker image |
| tableManager.dnsConfig | object | `{}` | DNS config table-manager pods |
| tableManager.enabled | bool | `false` | Specifies whether the table-manager should be enabled |
| tableManager.extraArgs | list | `[]` | Additional CLI args for the table-manager |
| tableManager.extraContainers | list | `[]` | Containers to add to the table-manager pods |
| tableManager.extraEnv | list | `[]` | Environment variables to add to the table-manager pods |
| tableManager.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the table-manager pods |
| tableManager.extraVolumeMounts | list | `[]` | Volume mounts to add to the table-manager pods |
| tableManager.extraVolumes | list | `[]` | Volumes to add to the table-manager pods |
| tableManager.image.registry | string | `nil` | The Docker registry for the table-manager image. Overrides `loki.image.registry` |
| tableManager.image.repository | string | `nil` | Docker image repository for the table-manager image. Overrides `loki.image.repository` |
| tableManager.image.tag | string | `nil` | Docker image tag for the table-manager image. Overrides `loki.image.tag` |
| tableManager.nodeSelector | object | `{}` | Node selector for table-manager pods |
| tableManager.podAnnotations | object | `{}` | Annotations for table-manager pods |
| tableManager.podLabels | object | `{}` | Labels for table-manager pods |
| tableManager.priorityClassName | string | `nil` | The name of the PriorityClass for table-manager pods |
| tableManager.resources | object | `{}` | Resource requests and limits for the table-manager |
| tableManager.retention_deletes_enabled | bool | `false` | Enable deletes by retention |
| tableManager.retention_period | int | `0` | Set retention period |
| tableManager.service.annotations | object | `{}` | Annotations for table-manager Service |
| tableManager.service.labels | object | `{}` | Additional labels for table-manager Service |
| tableManager.terminationGracePeriodSeconds | int | `30` | Grace period to allow the table-manager to shutdown before it is killed |
| tableManager.tolerations | list | `[]` | Tolerations for table-manager pods |
| test | object | `{"annotations":{},"canaryServiceAddress":"http://loki-canary:3500/metrics","enabled":true,"image":{"digest":null,"pullPolicy":"IfNotPresent","registry":"docker.io","repository":"grafana/loki-helm-test","tag":"ewelch-distributed-helm-chart-17db5ee"},"labels":{},"prometheusAddress":"","timeout":"1m"}` | Section for configuring optional Helm test |
| test.annotations | object | `{}` | Additional annotations for test pods |
| test.canaryServiceAddress | string | `"http://loki-canary:3500/metrics"` | Used to directly query the metrics endpoint of the canary for testing, this approach avoids needing prometheus for testing. This in a newer approach to using prometheusAddress such that tests do not have a dependency on prometheus |
| test.image | object | `{"digest":null,"pullPolicy":"IfNotPresent","registry":"docker.io","repository":"grafana/loki-helm-test","tag":"ewelch-distributed-helm-chart-17db5ee"}` | Image to use for loki canary |
| test.image.digest | string | `nil` | Overrides the image tag with an image digest |
| test.image.pullPolicy | string | `"IfNotPresent"` | Docker image pull policy |
| test.image.registry | string | `"docker.io"` | The Docker registry |
| test.image.repository | string | `"grafana/loki-helm-test"` | Docker image repository |
| test.image.tag | string | `"ewelch-distributed-helm-chart-17db5ee"` | Overrides the image tag whose default is the chart's appVersion |
| test.labels | object | `{}` | Additional labels for the test pods |
| test.prometheusAddress | string | `""` | Address of the prometheus server to query for the test. This overrides any value set for canaryServiceAddress. This is kept for backward compatibility and may be removed in future releases. Previous value was 'http://prometheus:9090' |
| test.timeout | string | `"1m"` | Number of times to retry the test before failing |
| write.affinity | object | Hard node anti-affinity | Affinity for write pods. |
| write.annotations | object | `{}` | Annotations for write StatefulSet |
| write.autoscaling.behavior | object | `{"scaleDown":{"policies":[{"periodSeconds":1800,"type":"Pods","value":1}],"stabilizationWindowSeconds":3600},"scaleUp":{"policies":[{"periodSeconds":900,"type":"Pods","value":1}]}}` | Behavior policies while scaling. |
| write.autoscaling.behavior.scaleUp | object | `{"policies":[{"periodSeconds":900,"type":"Pods","value":1}]}` | see https://github.com/grafana/loki/blob/main/docs/sources/operations/storage/wal.md#how-to-scale-updown for scaledown details |
| write.autoscaling.enabled | bool | `false` | Enable autoscaling for the write. |
| write.autoscaling.maxReplicas | int | `6` | Maximum autoscaling replicas for the write. |
| write.autoscaling.minReplicas | int | `2` | Minimum autoscaling replicas for the write. |
| write.autoscaling.targetCPUUtilizationPercentage | int | `60` | Target CPU utilisation percentage for the write. |
| write.autoscaling.targetMemoryUtilizationPercentage | string | `nil` | Target memory utilization percentage for the write. |
| write.dnsConfig | object | `{}` | DNS config for write pods |
| write.extraArgs | list | `[]` | Additional CLI args for the write |
| write.extraContainers | list | `[]` | Containers to add to the write pods |
| write.extraEnv | list | `[]` | Environment variables to add to the write pods |
| write.extraEnvFrom | list | `[]` | Environment variables from secrets or configmaps to add to the write pods |
| write.extraVolumeClaimTemplates | list | `[]` | volumeClaimTemplates to add to StatefulSet |
| write.extraVolumeMounts | list | `[]` | Volume mounts to add to the write pods |
| write.extraVolumes | list | `[]` | Volumes to add to the write pods |
| write.image.registry | string | `nil` | The Docker registry for the write image. Overrides `loki.image.registry` |
| write.image.repository | string | `nil` | Docker image repository for the write image. Overrides `loki.image.repository` |
| write.image.tag | string | `nil` | Docker image tag for the write image. Overrides `loki.image.tag` |
| write.initContainers | list | `[]` | Init containers to add to the write pods |
| write.lifecycle | object | `{}` | Lifecycle for the write container |
| write.nodeSelector | object | `{}` | Node selector for write pods |
| write.persistence.annotations | object | `{}` | Annotations for volume claim |
| write.persistence.dataVolumeParameters | object | `{"emptyDir":{}}` | Parameters used for the `data` volume when volumeClaimEnabled if false |
| write.persistence.enableStatefulSetAutoDeletePVC | bool | `false` | Enable StatefulSetAutoDeletePVC feature |
| write.persistence.selector | string | `nil` | Selector for persistent disk |
| write.persistence.size | string | `"10Gi"` | Size of persistent disk |
| write.persistence.storageClass | string | `nil` | Storage class to be used. If defined, storageClassName: <storageClass>. If set to "-", storageClassName: "", which disables dynamic provisioning. If empty or set to null, no storageClassName spec is set, choosing the default provisioner (gp2 on AWS, standard on GKE, AWS, and OpenStack). |
| write.persistence.volumeClaimsEnabled | bool | `true` | Enable volume claims in pod spec |
| write.podAnnotations | object | `{}` | Annotations for write pods |
| write.podLabels | object | `{}` | Additional labels for each `write` pod |
| write.podManagementPolicy | string | `"Parallel"` | The default is to deploy all pods in parallel. |
| write.priorityClassName | string | `nil` | The name of the PriorityClass for write pods |
| write.replicas | int | `3` | Number of replicas for the write |
| write.resources | object | `{}` | Resource requests and limits for the write |
| write.selectorLabels | object | `{}` | Additional selector labels for each `write` pod |
| write.service.annotations | object | `{}` | Annotations for write Service |
| write.service.labels | object | `{}` | Additional labels for write Service |
| write.targetModule | string | `"write"` | Comma-separated list of Loki modules to load for the write |
| write.terminationGracePeriodSeconds | int | `300` | Grace period to allow the write to shutdown before it is killed. Especially for the ingester, this must be increased. It must be long enough so writes can be gracefully shutdown flushing/transferring all data and to successfully leave the member ring on shutdown. |
| write.tolerations | list | `[]` | Tolerations for write pods |
| write.topologySpreadConstraints | list | `[]` | Topology Spread Constraints for write pods |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)
