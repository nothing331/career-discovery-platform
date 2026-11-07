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

    def on_billed_http_error(self, status, detail, reserve):
        if status != 400:
            return
        # Tokens may have been generated and usage is unknown: charge the whole
        # reservation as spent so cost is never under-counted.
        self.store.settle(self.run_id, reserve, reserve)
        self.log.emit(
            "model.charged_reservation",
            "WARNING",
            job_id=self.job_id,
            provider=self.provider,
            amount_usd=str(reserve),
            reason="HTTP 400 without usage",
        )

    def error_code(self, status, detail=None):
        if status != 400:
            return super().error_code(status, detail)
        # Schema-validation failures and other rejections are per-request, not
        # run-wide problems: non-stop codes.
        hint = (
            " ".join(
                str(detail.get(k) or "")
                for k in ("provider_error_code", "provider_error_type", "response_body")
            ).lower()
            if detail
            else ""
        )
        if "json_validate_failed" in hint or "schema" in hint or "validation" in hint:
            return "MODEL_SCHEMA_INVALID"
        return "MODEL_REQUEST_REJECTED"
