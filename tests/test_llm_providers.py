from apply_bot.config import Settings
from apply_bot.llm import llm_enabled, providers


def test_grok_then_gemini_when_both_keys_exist():
    settings = Settings(use_grok=True, use_gemini=True, grok_api_key="g", gemini_api_key="m")
    assert providers(settings) == ["grok", "gemini"]
    assert llm_enabled(settings)


def test_skips_provider_without_a_key():
    settings = Settings(use_grok=True, use_gemini=True, grok_api_key="", gemini_api_key="m")
    assert providers(settings) == ["gemini"]


def test_off_when_flags_are_false():
    settings = Settings(use_grok=False, use_gemini=False, grok_api_key="g", gemini_api_key="m")
    assert providers(settings) == []


def test_groq_key_routes_to_groq_with_groq_model():
    from apply_bot.llm import GROQ_DEFAULT_MODEL, GROQ_URL, chat_endpoint
    assert chat_endpoint("gsk_abc", "grok-3-mini") == (GROQ_URL, GROQ_DEFAULT_MODEL)
    assert chat_endpoint("gsk_abc", "qwen/qwen3.8-27b") == (GROQ_URL, "qwen/qwen3.8-27b")


def test_xai_key_stays_on_xai():
    from apply_bot.llm import GROK_URL, chat_endpoint
    assert chat_endpoint("xai-abc", "grok-3-mini") == (GROK_URL, "grok-3-mini")
