from .contracts import PipelineError
from .groq import Groq
from .openrouter import OpenRouter


def extractor(settings, store, run_id, log, client=None):
    providers = {"openrouter": OpenRouter, "groq": Groq}
    if settings.provider not in providers:
        raise PipelineError("MODEL_PROVIDER_UNSUPPORTED", "Choose openrouter or groq")
    return providers[settings.provider](settings, store, run_id, log, client)
