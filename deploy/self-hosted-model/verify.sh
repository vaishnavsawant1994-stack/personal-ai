#!/usr/bin/env sh
set -eu

: "${SELF_HOSTED_AI_URL:?Set SELF_HOSTED_AI_URL, for example https://model.example.com/v1}"
: "${SELF_HOSTED_AI_API_KEY:?Set SELF_HOSTED_AI_API_KEY}"
: "${SELF_HOSTED_AI_MODEL:?Set SELF_HOSTED_AI_MODEL}"

curl --fail --silent --show-error --connect-timeout 10 --max-time 30 \
  -H "Authorization: Bearer ${SELF_HOSTED_AI_API_KEY}" \
  "${SELF_HOSTED_AI_URL}/models" >/dev/null

curl --fail --silent --show-error --connect-timeout 10 --max-time 120 \
  -H "Authorization: Bearer ${SELF_HOSTED_AI_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${SELF_HOSTED_AI_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: SELF_HOSTED_OK\"}],\"temperature\":0}" \
  "${SELF_HOSTED_AI_URL}/chat/completions" | grep -q 'SELF_HOSTED_OK'

echo "Self-hosted OpenAI-compatible inference verified."
