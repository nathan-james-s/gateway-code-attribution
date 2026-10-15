{{- define "gca.litellmConfig" -}}
{{- $fn := include "gca.fullname" . -}}
model_list:
  {{- if .Values.demo.enabled }}
  - model_name: demo-openai
    litellm_params: {model: openai/demo, api_base: "http://{{ $fn }}-demo-model:8080/v1", api_key: demo}
  - model_name: demo-anthropic
    litellm_params: {model: anthropic/demo, api_base: "http://{{ $fn }}-demo-model:8080", api_key: demo}
  - model_name: demo-gemini
    litellm_params: {model: gemini/demo-gemini, api_base: "http://{{ $fn }}-demo-model:8080", api_key: demo}
  {{- end }}
  {{- range .Values.providers.models }}
  - model_name: {{ .name }}
    litellm_params:
      model: {{ if eq .provider "openAI" }}openai{{ else }}{{ .provider }}{{ end }}/{{ .model }}
      api_key: os.environ/PROVIDER_{{ .provider | upper }}_KEY
  {{- end }}
litellm_settings:
  callbacks: ["gca_capture_litellm.handler.handler"]
  # Not `turn_off_message_logging`: LiteLLM 1.105 then redacts the response handed to *every* callback,
  # including capture (found on the first kind install). Content stays out of storage through
  # store_prompts_in_spend_logs: false and having no other logging callbacks; the privacy audit checks both.
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  disable_spend_logs: false             # usage only
  store_prompts_in_spend_logs: false    # pinned explicitly; asserted by the privacy audit (T064)
{{- end -}}
