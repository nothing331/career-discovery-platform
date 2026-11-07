from dataclasses import dataclass
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
    api_key: str = ""
    model: str = "qwen/qwen3.5-flash-02-23"
    fallback_model: str = "google/gemini-2.5-flash-lite"
    input_rate: Decimal = Decimal("0.20")
    output_rate: Decimal = Decimal("0.50")
    output_tokens: int = 2048

    @classmethod
    def load(cls):
        env = {**dotenv_values(PROJECT / ".env"), **os.environ}

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
            budget=Decimal(env.get("ENGINE_RUN_BUDGET_USD", "5")),
            api_key=env.get("OPENROUTER_API_KEY") or "",
            model=env.get("OPENROUTER_MODEL") or cls.model,
            fallback_model=env.get("OPENROUTER_FALLBACK_MODEL") or cls.fallback_model,
            input_rate=Decimal(env.get("OPENROUTER_MAX_INPUT_PER_MILLION", ".20")),
            output_rate=Decimal(env.get("OPENROUTER_MAX_OUTPUT_PER_MILLION", ".50")),
            output_tokens=int(env.get("OPENROUTER_MAX_OUTPUT_TOKENS", "2048")),
        )
        if not (
            0 <= s.delay <= 3600 and 1 <= s.max_documents <= 500 and 0 <= s.retries <= 2
        ):
            raise ValueError("Invalid collection limits")
        if (
            not all(
                x.is_finite() and x > 0 for x in (s.budget, s.input_rate, s.output_rate)
            )
            or not 128 <= s.output_tokens <= 8192
        ):
            raise ValueError("Invalid budget or model limits")
        return s
