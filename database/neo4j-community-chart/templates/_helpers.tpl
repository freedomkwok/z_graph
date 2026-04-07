{{- define "neo4j-community.chartName" -}}
{{- default .Chart.Name .Values.nameOverride -}}
{{- end -}}

{{- define "neo4j-community.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride -}}
{{- else -}}
{{- default .Values.deployment.name (include "neo4j-community.chartName" .) -}}
{{- end -}}
{{- end -}}

{{- define "neo4j-community.namespace" -}}
{{- .Values.namespace.name -}}
{{- end -}}
