import json
import re
import logging
import time
import httpx
from core.config import config
from agents.prompts import CODING_SYSTEM_PROMPT

log = logging.getLogger("coding_agent")


async def _call_llm(system_prompt: str, user_message: str, label: str = "LLM") -> str:
    last_error = None
    model = config.openrouter_coding_model
    for attempt in range(3):
        try:
            log.info("[%s] Calling OpenRouter (model=%s, attempt=%d/3)...", label, model, attempt + 1)
            t0 = time.time()
            async with httpx.AsyncClient(timeout=180) as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {config.openrouter_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message},
                        ],
                        "max_tokens": 16384,
                        "temperature": 0.1,
                        "top_p": 0.95,
                    },
                )
                elapsed = time.time() - t0
                response.raise_for_status()
                data = response.json()

                usage = data.get("usage", {})
                log.info("[%s] Response received in %.1fs — tokens: prompt=%s, completion=%s, total=%s",
                         label, elapsed,
                         usage.get("prompt_tokens", "?"),
                         usage.get("completion_tokens", "?"),
                         usage.get("total_tokens", "?"))

                content = data["choices"][0]["message"]["content"]

                # Strip <think>...</think> blocks
                think_match = re.search(r"<think>", content)
                if think_match:
                    log.info("[%s] Stripping <think> block from response", label)
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

                # Strip markdown code fences
                if content.startswith("```"):
                    log.info("[%s] Stripping markdown code fences", label)
                    content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                if content.endswith("```"):
                    content = content[:-3]

                # Strip any pre-code text (safety net for untagged reasoning)
                content = content.strip()
                if content and not content.startswith(("import ", "from ", "#", "def ", "class ", "\"\"\"", "'''")):
                    for marker in ["import ", "from ", "# ", "def ", "class "]:
                        idx = content.find("\n" + marker)
                        if idx >= 0:
                            log.info("[%s] Stripping %d chars of pre-code text", label, idx)
                            content = content[idx + 1:]
                            break

                cleaned = content.strip()
                log.info("[%s] Generated code length: %d chars, ~%d lines", label, len(cleaned), cleaned.count("\n") + 1)
                return cleaned
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.ReadTimeout) as e:
            last_error = e
            log.warning("[%s] Attempt %d failed: %s", label, attempt + 1, e)
            if attempt < 2:
                import asyncio
                log.info("[%s] Retrying in 2s...", label)
                await asyncio.sleep(2)
    log.error("[%s] All 3 attempts failed", label)
    raise last_error


def _postprocess_code(code: str) -> str:
    """Fix common LLM code generation mistakes before syntax validation."""
    import re
    fixed = code
    count = 0

    # Fix unterminated f-strings in print/log statements:
    #   print(f"Error: {e})  →  print(f"Error: {e}")
    #   print(f"...{var})    →  print(f"...{var}")
    # Pattern: f"...{something}) at end of statement — missing closing quote
    fixed = re.sub(
        r'(f"[^"]*\{[^}]*\})\)',
        r'\1")',
        fixed,
    )
    # Same for single-quoted f-strings
    fixed = re.sub(
        r"(f'[^']*\{[^}]*\})\)",
        r"\1')",
        fixed,
    )

    if fixed != code:
        count = sum(1 for a, b in zip(code.splitlines(), fixed.splitlines()) if a != b)
        log.info("[POSTPROCESS] Fixed %d lines with unterminated f-string patterns", count)

    return fixed


async def fix_code(code: str, error: str, output_path: str) -> str:
    """Send broken code + error back to the LLM to fix."""
    log.info("=" * 60)
    log.info("[CODEFIX] Attempting to fix code generation error")
    log.info("[CODEFIX] Error: %s", error[:200])

    user_message = (
        "The following Python code has an error. Fix it and output the COMPLETE corrected Python script.\n\n"
        f"ERROR:\n{error}\n\n"
        f"OUTPUT PATH (must save to this exact path): {output_path}\n\n"
        f"BROKEN CODE:\n{code}\n\n"
        "Output ONLY the corrected Python code. No explanation, no markdown fences."
    )

    fixed = await _call_llm(CODING_SYSTEM_PROMPT, user_message, label="CODEFIX")
    fixed = _postprocess_code(fixed)
    log.info("[CODEFIX] Fixed code length: %d chars, ~%d lines", len(fixed), fixed.count("\n") + 1)
    return fixed


async def generate(analysis: dict, output_path: str) -> str:
    log.info("=" * 60)
    log.info("[CODEGEN] Starting code generation")
    log.info("[CODEGEN] Output path: %s", output_path)

    ci = analysis.get("coding_instructions", {})
    log.info("[CODEGEN] Instructions: format=%s, title=%s, sections=%d",
             ci.get("output_format", "?"), ci.get("title", "?"), len(ci.get("sections", [])))
    for i, sec in enumerate(ci.get("sections", [])):
        log.info("[CODEGEN]   Section %d: type=%s", i + 1, sec.get("type", "?"))

    user_message = json.dumps({
        "coding_instructions": ci,
        "narrative": analysis.get("narrative", {}),
        "output_path": output_path,
    }, default=str)
    log.info("[CODEGEN] User message size: %d chars", len(user_message))

    code = await _call_llm(CODING_SYSTEM_PROMPT, user_message, label="CODEGEN")
    code = _postprocess_code(code)

    # Log first few lines of generated code
    lines = code.split("\n")
    log.info("[CODEGEN] Code preview (first 5 lines):")
    for line in lines[:5]:
        log.info("[CODEGEN]   %s", line)

    return code
