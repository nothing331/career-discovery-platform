"""Groq pilot adapter. Token-rate estimates are never presented as billed cost."""

from decimal import Decimal
from .openrouter import OpenRouter
from .contracts import PipelineError


class Groq(OpenRouter):
    provider = "groq"
    endpoint = "https://api.groq.com/openai/v1/chat/completions"
    key_env = "GROQ_API_KEY"
    cost_basis = "token_rate_estimate"
    unbilled_statuses = (401, 402, 403, 404, 422)

    def request(self, blocks, target, model):
        if model not in ("openai/gpt-oss-20b", "openai/gpt-oss-120b"):
            raise PipelineError(
                "MODEL_UNSUPPORTED",
                "The Groq pilot supports GPT-OSS 20B/120B with strict structured output",
            )
        request = super().request(blocks, target, model)
        del request["provider"]
        request["max_completion_tokens"] = request.pop("max_tokens")
        request["reasoning_effort"] = "low"
        request["include_reasoning"] = False
        return request

    def account(self, data):
        if data.get("model") != self.settings.model:
            raise PipelineError(
                "MODEL_BILLING_UNCERTAIN",
                "Groq response model differs from the configured rate estimate; reservation retained",
            )
        usage = data.get("usage")
        if not isinstance(usage, dict) or any(
            type(usage.get(k)) is not int or usage[k] < 0
            for k in ("prompt_tokens", "completion_tokens")
        ):
            raise PipelineError(
                "MODEL_BILLING_UNCERTAIN",
                "Groq did not return usable token counts; reservation retained",
            )
        estimate = (
            Decimal(usage["prompt_tokens"]) * self.settings.input_rate
            + Decimal(usage["completion_tokens"]) * self.settings.output_rate
        ) / Decimal(1_000_000)
        return usage, estimate

    def error_code(self, status):
        # Generation can fail schema validation with HTTP 400. Without usage,
        # retain the reservation and stop rather than assuming it was free.
        return (
            "MODEL_BILLING_UNCERTAIN" if status == 400 else super().error_code(status)
        )
