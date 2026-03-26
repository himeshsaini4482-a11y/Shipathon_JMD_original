"""Code Reviewer Agent — executes code, verifies output, provides critique.

Receives generated code, executes it in the sandbox, inspects results
(files generated, stdout, errors), and provides a detailed critique.
If issues are found, returns fix instructions and corrected code.
"""

import json
import os
import re
import logging
import time
import httpx
from pathlib import Path
from core.config import config

log = logging.getLogger("code_reviewer")

MAX_RETRIES = 2  # Max retry attempts for LLM calls (total attempts = MAX_RETRIES + 1)

CODE_REVIEWER_SYSTEM_PROMPT = """You are a meticulous code execution reviewer and quality assurance specialist. Your job is to:

1. ANALYZE the execution results of Python code that generates documents (PPTX, PDF, XLSX) and charts (matplotlib)
2. IDENTIFY any issues with the output
3. PROVIDE specific, actionable fix instructions

You receive:
- The original code that was executed
- The execution result (success/failure, stdout, stderr, files generated, errors)
- The original task instruction

YOUR EVALUATION CRITERIA:

═══════════════════════════════════════════════
EXECUTION STATUS CHECK
═══════════════════════════════════════════════
- Did the code execute successfully without exceptions?
- Were all expected output files actually created?
- Are there any warnings in stdout/stderr that indicate problems?

═══════════════════════════════════════════════
FILE OUTPUT VERIFICATION
═══════════════════════════════════════════════
For CHARTS (.png):
  - Was the chart file actually created?
  - Is the file size reasonable (not 0 bytes)?
  - Is plt.close() called after plt.savefig()?

For PDF:
  - Was the .pdf file created?
  - Does the code call doc.build(elements)?
  - Are all Paragraphs given a style?
  - Are charts/images embedded?

For PPTX:
  - Was the .pptx file created?
  - Are slides added properly?
  - Are charts/images embedded where promised?

For XLSX:
  - Was the .xlsx file created?
  - Is formatting applied?

═══════════════════════════════════════════════
ERROR PATTERN RECOGNITION
═══════════════════════════════════════════════
Pattern: "RGBColor() takes exactly 3 integer arguments"
Fix: Replace RGBColor('#hex') with RGBColor(0xRR, 0xGG, 0xBB)

Pattern: "Spacer() takes at least 2 arguments"
Fix: Replace Spacer(12) with Spacer(1, 12)

Pattern: "'Presentation' object has no attribute 'add_slide'"
Fix: Use prs.slides.add_slide(layout) not prs.add_slide(layout)

Pattern: "module 'matplotlib' has no attribute 'pyplot'"
Fix: import matplotlib.pyplot as plt (not just matplotlib)

YOUR RESPONSE FORMAT:
{
  "verdict": "pass" | "fail" | "partial",
  "issues": [
    {
      "type": "runtime_error|missing_file|empty_output|quality|warning",
      "description": "What went wrong",
      "root_cause": "Why it happened",
      "fix_instruction": "Specific code change to fix this"
    }
  ],
  "files_verified": ["list of files that were confirmed created"],
  "quality_notes": "Overall quality assessment",
  "fix_code": "If verdict is fail, provide COMPLETE corrected Python code. If pass, empty string.",
  "retry_recommended": true/false,
  "summary": "One-line summary"
}

IMPORTANT RULES:
1. If execution succeeded and files were generated, verdict is "pass" unless quality is poor.
2. If execution failed with an error, verdict is "fail" and you MUST provide fix_code.
3. If partial success (some files created but not all), verdict is "partial".
4. The fix_code must be COMPLETE and SELF-CONTAINED — not a patch, the full corrected script.
5. Set retry_recommended=true only if you believe the fix will succeed."""


async def _call_llm(system_prompt: str, user_message: str, label: str = "REVIEWER") -> str:
    """Call OpenRouter for code review."""
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            log.info("[%s] Calling OpenRouter (attempt=%d/%d)...", label, attempt + 1, MAX_RETRIES + 1)
            t0 = time.time()
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {config.openrouter_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": config.openrouter_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message},
                        ],
                        "max_tokens": 8192,
                        "temperature": 0.1,
                        "top_p": 0.95,
                        "reasoning": {"effort": "high"},
                    },
                )
                elapsed = time.time() - t0
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]

                # Strip <think> blocks
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                # Strip markdown fences
                if content.startswith("```"):
                    content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                if content and not content.startswith("{"):
                    idx = content.find("{")
                    if idx > 0:
                        content = content[idx:]

                log.info("[%s] Response in %.1fs", label, elapsed)
                return content.strip()
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.ReadTimeout) as e:
            last_error = e
            log.warning("[%s] Attempt %d failed: %s", label, attempt + 1, e)
            if attempt < MAX_RETRIES:
                import asyncio
                await asyncio.sleep(2)
    raise last_error


def _parse_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {
        "verdict": "fail",
        "issues": [],
        "files_verified": [],
        "quality_notes": "LLM response unparseable",
        "fix_code": "",
        "retry_recommended": False,
        "summary": "Could not parse reviewer response",
    }


def verify_files(generated_dir: str, expected_output: str) -> dict:
    """Verify that expected output file exists and check for other generated files."""
    verified = []
    missing = []
    empty = []

    generated_path = Path(generated_dir)
    expected_path = Path(expected_output)

    # Check the primary expected output
    if expected_path.exists():
        size = expected_path.stat().st_size
        if size > 0:
            verified.append({"path": str(expected_path), "size": size})
        else:
            empty.append(str(expected_path))
    else:
        missing.append(str(expected_path))

    # Also find any chart PNGs that were generated
    if generated_path.is_dir():
        for f in generated_path.iterdir():
            if f.suffix.lower() == ".png" and f != expected_path:
                size = f.stat().st_size
                if size > 0:
                    verified.append({"path": str(f), "size": size})

    return {
        "verified": verified,
        "missing": missing,
        "empty": empty,
        "all_ok": len(missing) == 0 and len(empty) == 0,
    }


async def review_execution(
    code: str,
    instruction: str,
    execution_success: bool,
    stdout: str,
    stderr: str,
    expected_output: str,
    generated_dir: str,
) -> dict:
    """Review code execution results and provide critique.

    Args:
        code: The executed Python code
        instruction: Original coding instruction (for context)
        execution_success: Whether subprocess exited 0
        stdout: Captured stdout
        stderr: Captured stderr
        expected_output: Path to expected output file
        generated_dir: Directory where files are generated

    Returns:
        dict with: verdict, issues, fix_code, retry_recommended, files_verified
    """
    # Verify files
    files_status = verify_files(generated_dir, expected_output)

    # Build context for LLM review
    context_parts = [
        f"## Original Instruction\n{instruction[:500]}",
        f"\n## Execution Result",
        f"Success: {execution_success}",
        f"Stdout (last 1500 chars): {stdout[-1500:] if stdout else 'None'}",
        f"Stderr (last 500 chars): {stderr[-500:] if stderr else 'None'}",
        f"\n## File Verification",
        "Verified files: " + str([(item["path"], item["size"]) for item in files_status["verified"]]),
        f"Missing files: {files_status['missing']}",
        f"Empty files: {files_status['empty']}",
        f"\n## Code (for analysis)\n```python\n{code[:8000]}\n```",
    ]

    raw = await _call_llm(
        CODE_REVIEWER_SYSTEM_PROMPT,
        "\n".join(context_parts),
        label="REVIEWER",
    )
    result = _parse_json(raw)

    # Ensure defaults
    if not execution_success and result.get("verdict") == "pass":
        result["verdict"] = "fail"
    result.setdefault("verdict", "pass" if execution_success and files_status["all_ok"] else "fail")
    result.setdefault("issues", [])
    result.setdefault("files_verified", [f["path"] for f in files_status["verified"]])
    result.setdefault("fix_code", "")
    result.setdefault("retry_recommended", not execution_success)
    result.setdefault("summary", "Review complete")

    log.info("[REVIEWER] Verdict: %s — %s", result["verdict"], result["summary"])
    if result["issues"]:
        for issue in result["issues"][:5]:
            log.info("[REVIEWER]   Issue: [%s] %s", issue.get("type", "?"), issue.get("description", "")[:100])

    return result
