import os
import pytest
from dexter_py.model import llm


def test_get_chat_model_no_api_key(monkeypatch):
    # Ensure OPENAI_API_KEY is not set
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        llm.get_chat_model()
