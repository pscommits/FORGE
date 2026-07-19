"""
llm_client.py -- Thin wrapper around the Groq chat completions API with retry/backoff, plus
a --dry-run mock mode so the rest of the pipeline (retrieval, context assembly) can be
exercised without a live GROQ_API_KEY or any network calls.

FORGE_Application is Groq-only: the local Hugging Face backend from the original FORGE
package was intentionally dropped (see original llm_client.py / local_llm_client.py for that
variant).
"""
import time

import config


class GroqClientError(RuntimeError):
    pass


class GroqClient:
    def __init__(self, api_key=None, model=None, dry_run=False):
        self.model = model or config.GROQ_MODEL
        self.dry_run = dry_run
        self.api_key = api_key or config.GROQ_API_KEY

        if self.dry_run:
            self._client = None
            return

        if not self.api_key:
            raise GroqClientError(
                "GROQ_API_KEY is not set. Set it in the .env file (see .env.example) or the "
                "environment before making a live request."
            )

        from groq import Groq
        self._client = Groq(api_key=self.api_key)

    def chat(self, system_prompt: str, user_prompt: str,
             temperature: float = None, max_tokens: int = None) -> str:
        if self.dry_run:
            return self._mock_response(user_prompt)

        temperature = config.GROQ_TEMPERATURE if temperature is None else temperature
        max_tokens = max_tokens or config.GROQ_MAX_TOKENS

        last_err = None
        for attempt in range(config.GROQ_MAX_RETRIES):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=config.GROQ_TIMEOUT_S,
                )
                return resp.choices[0].message.content.strip()
            except Exception as e:  # noqa: BLE001 -- Groq SDK raises several exception types
                last_err = e
                wait = 2 ** attempt
                print(f"  [groq] attempt {attempt + 1}/{config.GROQ_MAX_RETRIES} failed "
                      f"({e.__class__.__name__}: {e}); retrying in {wait}s...")
                time.sleep(wait)
        raise GroqClientError(f"Groq API call failed after {config.GROQ_MAX_RETRIES} attempts: {last_err}")

    @staticmethod
    def _mock_response(user_prompt: str) -> str:
        """Deterministic offline stand-in for a real LLM call, used by --dry-run so the
        pipeline can be wired and tested without an API key or network access."""
        snippet = user_prompt[:120].replace("\n", " ")
        return (
            "[DRY-RUN MOCK RESPONSE -- no live Groq call was made] "
            f"Received a prompt of {len(user_prompt)} chars beginning: \"{snippet}...\". "
            "Set GROQ_API_KEY and drop --dry-run to get a real answer."
        )


def get_llm_client(backend: str = "groq", dry_run: bool = False, **kwargs):
    """Factory: returns a client with a .chat(system_prompt, user_prompt) method. This
    standalone app only supports backend="groq"."""
    if backend != "groq":
        raise ValueError(f"FORGE_Application only supports backend='groq', got '{backend}'")
    return GroqClient(dry_run=dry_run, **kwargs)
