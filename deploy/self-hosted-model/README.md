# Owner-controlled model host

This deployment runs a GPU-backed OpenAI-compatible vLLM service separately from Railway. The inference container is reachable only through an authenticated HTTPS gateway. Model weights and compile caches persist across container restarts.

## Before deployment

1. Purchase an NVIDIA GPU host with Docker, NVIDIA Container Toolkit, persistent disk and a public IP.
2. Point a dedicated DNS name to the host.
3. Copy `.env.example` to `.env` on the host and fill it there. Never commit `.env`.
4. Select the model, context length and parallelism only after confirming usable VRAM.
5. Replace the `latest` image with a reviewed stable tag or immutable digest.
6. Generate a strong random `MODEL_API_KEY`; store it only on the GPU host and in Railway Variables.

Start with `docker compose pull && docker compose up -d`. From a different trusted machine, export the three `SELF_HOSTED_AI_*` variables and run `./verify.sh`.

## Railway variables

```text
AI_PROVIDER=self_hosted
SELF_HOSTED_AI_URL=https://<model-domain>/v1
SELF_HOSTED_AI_API_KEY=<same secret stored on the GPU gateway>
SELF_HOSTED_AI_MODEL=<SERVED_MODEL_NAME>
MODEL_LOCAL_FIRST=true
MODEL_FALLBACK_PROVIDERS=gemini
ALLOW_EXTERNAL_FOR_SENSITIVE=false
```

Sensitive/private retrieval fails closed when the owner-controlled model is unavailable. Normal tasks may use the explicitly allowed Gemini fallback, and every fallback is audited.

Operational checks: verify authorized and unauthorized `/v1/models`, restart recovery, cached model startup, GPU usage, time to first token, generation latency, throughput and error rate. Rotate the gateway key by updating the GPU host and Railway together.

Official references: https://docs.vllm.ai/en/latest/deployment/docker/ and https://docs.vllm.ai/en/latest/serving/openai_compatible_server/
