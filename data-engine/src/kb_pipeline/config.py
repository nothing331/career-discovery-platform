from dataclasses import dataclass, field
from decimal import Decimal
import os
from pathlib import Path
from dotenv import dotenv_values

PROJECT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    registry: Path
    user_agent: str = "CareerDiscoveryPOC/0.1"
    delay: float = 3
    max_documents: int = 50
    retries: int = 2
    budget: Decimal = Decimal("5")
    api_key: str = field(default="", repr=False)
    model: str = "qwen/qwen3.5-flash-02-23"
    fallback_model: str = "google/gemini-2.5-flash-lite"
    input_rate: Decimal = Decimal("0.20")
    output_rate: Decimal = Decimal("0.50")
    output_tokens: int = 2048
    provider: str = "openrouter"
    followup_limit: int = 6
    # Pacing/retry knobs do not change outputs, so they stay out of model_config().
    rate_limit_retries: int = 4
    rate_limit_max_wait: float = 60
    tpm_limit: int = 0
    rpm_limit: int = 0

    def model_config(self):
        """Non-secret settings frozen into runs and provider-specific cache keys."""
        return {
            "provider": self.provider,
            "models": [self.model, self.fallback_model],
            "input_rate": str(self.input_rate),
            "output_rate": str(self.output_rate),
            "output_tokens": self.output_tokens,
        }

    @classmethod
    def load(cls):
        env = {**dotenv_values(PROJECT / ".env"), **os.environ}
        provider = (env.get("LLM_PROVIDER") or "openrouter").strip().lower()
        if provider not in ("openrouter", "groq"):
            raise ValueError("LLM_PROVIDER must be openrouter or groq")
        groq = provider == "groq"
        prefix = "GROQ" if groq else "OPENROUTER"
        model = env.get(prefix + "_MODEL") or (
            "openai/gpt-oss-20b" if groq else cls.model
        )
        groq_rates = (
            (".15", ".60") if model == "openai/gpt-oss-120b" else (".075", ".30")
        )

        def path(key, default):
            p = Path(env.get(key) or default).expanduser()
            return p.resolve() if p.is_absolute() else (PROJECT / p).resolve()

        s = cls(
            data_dir=path("ENGINE_DATA_DIR", "data"),
            registry=path("ENGINE_REGISTRY", "config/DE.json"),
            user_agent=env.get("ENGINE_USER_AGENT", "CareerDiscoveryPOC/0.1"),
            delay=float(env.get("ENGINE_DELAY_SECONDS", "3")),
            max_documents=int(env.get("ENGINE_MAX_DOCUMENTS", "50")),
            retries=int(env.get("ENGINE_MAX_RETRIES", "2")),
            followup_limit=int(env.get("ENGINE_FOLLOWUP_LIMIT", "6")),
            budget=Decimal(env.get("ENGINE_RUN_BUDGET_USD", "5")),
            provider=provider,
            api_key=env.get(prefix + "_API_KEY") or "",
            model=model,
            fallback_model=""
            if groq
            else (env.get("OPENROUTER_FALLBACK_MODEL") or cls.fallback_model),
            input_rate=Decimal(
                env.get("GROQ_INPUT_PER_MILLION", groq_rates[0])
                if groq
                else env.get("OPENROUTER_MAX_INPUT_PER_MILLION", ".20")
            ),
            output_rate=Decimal(
                env.get("GROQ_OUTPUT_PER_MILLION", groq_rates[1])
                if groq
                else env.get("OPENROUTER_MAX_OUTPUT_PER_MILLION", ".50")
            ),
            rate_limit_retries=int(env.get("LLM_RATE_LIMIT_RETRIES", "4")),
            rate_limit_max_wait=float(env.get("LLM_RATE_LIMIT_MAX_WAIT", "60")),
            tpm_limit=int(env.get(prefix + "_TPM_LIMIT", "8000" if groq else "0")),
            rpm_limit=int(env.get(prefix + "_RPM_LIMIT", "30" if groq else "0")),
            output_tokens=int(
                env.get(prefix + "_MAX_OUTPUT_TOKENS", "4096" if groq else "2048")
            ),
        )
        if not (
            0 <= s.delay <= 3600
            and 1 <= s.max_documents <= 500
            and 0 <= s.retries <= 2
            and 0 <= s.followup_limit <= 12
        ):
            raise ValueError("Invalid collection limits")
        if (
            not all(
                x.is_finite() and x > 0 for x in (s.budget, s.input_rate, s.output_rate)
            )
            or not 128 <= s.output_tokens <= 8192
        ):
            raise ValueError("Invalid budget or model limits")
        if not (
            0 <= s.rate_limit_retries <= 10
            and 0 <= s.rate_limit_max_wait <= 3600
            and 0 <= s.tpm_limit <= 10_000_000
            and 0 <= s.rpm_limit <= 100_000
        ):
            raise ValueError("Invalid rate-limit settings")
        return s
