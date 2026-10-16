{{/* Names and labels */}}
{{- define "gca.fullname" -}}
{{- printf "%s-gca" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "gca.labels" -}}
app.kubernetes.io/part-of: gateway-code-attribution
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "gca.selector" -}}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* image reference: repository:tag@digest (digest optional) */}}
{{- define "gca.image" -}}
{{- $img := . -}}
{{- if $img.digest -}}{{ printf "%s:%s@%s" $img.repository $img.tag $img.digest }}{{- else -}}{{ printf "%s:%s" $img.repository $img.tag }}{{- end -}}
{{- end -}}

{{/* project image: <registry>/gca-<name>:<tag>, plus @<digest> once a release has pinned it (images.digests) */}}
{{- define "gca.projectImage" -}}
{{- $digest := get (.root.Values.images.digests | default dict) .name -}}
{{- printf "%s/gca-%s:%s" .root.Values.images.registry .name .root.Values.images.tag -}}{{ if $digest }}@{{ $digest }}{{ end }}
{{- end -}}

{{- define "gca.postgresHost" -}}
{{- if .Values.postgres.internal -}}{{ include "gca.fullname" . }}-postgres{{- else -}}{{ .Values.postgres.external.host }}{{- end -}}
{{- end -}}

{{- define "gca.postgresSecret" -}}
{{- if .Values.postgres.internal -}}{{ include "gca.fullname" . }}-postgres{{- else -}}{{ .Values.postgres.external.existingSecret }}{{- end -}}
{{- end -}}

{{- define "gca.fingerprintSecret" -}}
{{- default (printf "%s-fingerprint-key" (include "gca.fullname" .)) .Values.fingerprintKey.existingSecret -}}
{{- end -}}

{{/* Database env for services. Generated passwords are alphanumeric, so they are URL-safe. */}}
{{- define "gca.dbEnv" -}}
- name: PGUSER
  valueFrom: {secretKeyRef: {name: {{ include "gca.postgresSecret" . }}, key: username}}
- name: PGPASSWORD
  valueFrom: {secretKeyRef: {name: {{ include "gca.postgresSecret" . }}, key: password}}
- name: GCA_DATABASE_URL
  value: "postgresql+psycopg://$(PGUSER):$(PGPASSWORD)@{{ include "gca.postgresHost" . }}:{{ .Values.postgres.external.port | default 5432 }}/{{ if .Values.postgres.internal }}gca{{ else }}{{ .Values.postgres.external.database }}{{ end }}"
- name: GCA_NATS_URL
  value: "nats://{{ .Release.Name }}-nats:4222"
- name: GCA_GATEWAY_TYPE
  value: {{ .Values.gateway.type | quote }}
- name: GCA_MATCHING_WINDOW_DAYS
  value: {{ .Values.attribution.matchingWindowDays | quote }}
- name: GCA_RETENTION_DAYS
  value: {{ .Values.attribution.retentionDays | quote }}
- name: GCA_KEYS_DIR
  value: /var/run/gca/keys
{{- end -}}

{{- define "gca.keysVolume" -}}
- name: fingerprint-keys
  secret:
    secretName: {{ include "gca.fingerprintSecret" . }}
    defaultMode: 0400
{{- end -}}

{{- define "gca.keysMount" -}}
- name: fingerprint-keys
  mountPath: /var/run/gca/keys
  readOnly: true
{{- end -}}

{{- define "gca.podSecurity" -}}
runAsNonRoot: true
runAsUser: 10001
fsGroup: 10001
seccompProfile: {type: RuntimeDefault}
{{- end -}}

{{- define "gca.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities: {drop: [ALL]}
{{- end -}}
