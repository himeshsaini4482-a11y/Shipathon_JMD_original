import time
import uuid
import os
import logging
from datetime import datetime, timedelta
from pathlib import Path

from core.config import config
from core.db import execute_query
from core.sandbox import execute, validate_syntax, SandboxError
from agents import finance_agent, coding_agent

log = logging.getLogger("orchestrator")


def _clean_old_files():
    """Remove generated files older than 1 hour."""
    generated = Path(config.generated_dir).resolve()
    if not generated.exists():
        return
    cutoff = datetime.now() - timedelta(hours=1)
    cleaned = 0
    for f in generated.iterdir():
        if f.name == ".gitkeep":
            continue
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                f.unlink()
                cleaned += 1
        except OSError:
            pass
    if cleaned:
        log.info("[CLEANUP] Removed %d old files", cleaned)


def fetch_all_data(data_requirements: list) -> list:
    log.info("=" * 60)
    log.info("[DATA] Fetching data for %d requirements", len(data_requirements))
    results = []
    for i, req in enumerate(data_requirements):
        req_id = req.get("req_id", "unknown")
        table = req.get("table")
        log.info("[DATA] [%d/%d] Fetching %s from '%s' (priority=%s)",
                 i + 1, len(data_requirements), req_id, table, req.get("priority", "required"))
        try:
            t0 = time.time()
            result = execute_query(
                table=req.get("table"),
                columns=req.get("columns", []),
                filters=req.get("filters", {}),
                group_by=req.get("group_by", []),
                order_by=req.get("order_by"),
                aggregate=req.get("aggregate", {}),
            )
            elapsed = (time.time() - t0) * 1000
            log.info("[DATA] [%d/%d] %s -> %d rows fetched in %.0fms",
                     i + 1, len(data_requirements), req_id, len(result["data"]), elapsed)
            results.append({
                "req_id": req_id,
                "table": table,
                "status": "ok",
                "row_count": len(result["data"]),
                "columns": result["columns"],
                "data": result["data"],
            })
        except Exception as e:
            log.error("[DATA] [%d/%d] %s -> ERROR: %s", i + 1, len(data_requirements), req_id, e)
            results.append({
                "req_id": req_id,
                "table": table,
                "status": "error",
                "error": str(e),
                "columns": [],
                "data": [],
            })
    total_rows = sum(r.get("row_count", 0) for r in results)
    log.info("[DATA] All fetches complete: %d total rows across %d queries", total_rows, len(results))
    return results


def _generate_follow_ups(query: str) -> list[str]:
    follow_ups = [
        "Compare this across all offices",
        "Break this down by product category",
        "What is the profit margin trend over the past quarter?",
        "Which products are below safety stock?",
    ]
    lower = query.lower()
    if "office" in lower or "city" in lower:
        follow_ups[0] = "Compare profit margins across all offices"
    if "employee" in lower or "hr" in lower or "salary" in lower:
        follow_ups[0] = "What is the department-wise headcount and average salary?"
        follow_ups[1] = "Who are the top-rated performers this review cycle?"
    if "inventory" in lower or "stock" in lower or "safety" in lower:
        follow_ups[2] = "What are the reorder recommendations?"
    if "pricing" in lower or "margin" in lower or "competitor" in lower:
        follow_ups[1] = "How do our prices compare to competitor averages?"
    if "skill" in lower or "developer" in lower:
        follow_ups[0] = "What is the skill distribution across departments?"
    return follow_ups[:4]


async def process_query(raw_query: str, output_format: str = "auto", conversation_history: list[dict] = None) -> dict:
    start = time.time()
    query_id = str(uuid.uuid4())[:8]

    log.info("")
    log.info("*" * 70)
    log.info("  PIPELINE START — Query ID: %s", query_id)
    log.info("  Query: %s", raw_query)
    if conversation_history:
        log.info("  Conversation context: %d previous turns", len(conversation_history))
    log.info("*" * 70)

    _clean_old_files()

    generated_dir = Path(config.generated_dir).resolve()
    generated_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Step 1: Finance LLM decomposes query
        t1 = time.time()
        log.info("[STEP 1/5] Finance Agent — Decomposing query...")
        decomposition = await finance_agent.decompose(raw_query, output_format, conversation_history)
        log.info("[STEP 1/5] Decomposition complete in %.1fs", time.time() - t1)

        # Step 2: Fetch data from PostgreSQL
        t2 = time.time()
        data_requirements = decomposition.get("data_requirements", [])
        log.info("[STEP 2/5] Data Fetch — %d queries to execute", len(data_requirements))
        data_results = fetch_all_data(data_requirements)
        log.info("[STEP 2/5] Data fetch complete in %.1fs", time.time() - t2)

        # Step 3: Finance LLM analyzes data
        t3 = time.time()
        log.info("[STEP 3/5] Finance Agent — Analyzing data...")
        analysis = await finance_agent.analyze(raw_query, decomposition, data_results, output_format, conversation_history)
        log.info("[STEP 3/5] Analysis complete in %.1fs", time.time() - t3)

        # Extract LLM-generated follow-ups, fallback to static
        follow_ups = analysis.get("follow_ups", [])
        if not follow_ups or not isinstance(follow_ups, list):
            follow_ups = _generate_follow_ups(raw_query)
            log.info("[FOLLOW-UPS] Using static fallback (%d questions)", len(follow_ups))
        else:
            log.info("[FOLLOW-UPS] Using LLM-generated (%d questions):", len(follow_ups))
            for fq in follow_ups:
                log.info("[FOLLOW-UPS]   -> %s", fq)

        # Decision: does this query need a document?
        needs_document = analysis.get("needs_document", True)
        doc_format = analysis.get("document_format", "pdf")
        if doc_format not in ("pdf", "pptx", "xlsx"):
            doc_format = "pdf"
        log.info("[DECISION] Document generation: %s%s",
                 "yes" if needs_document else "no",
                 f" (format: {doc_format})" if needs_document else "")

        if not needs_document:
            # Narrative-only response — skip coding and sandbox
            elapsed = int((time.time() - start) * 1000)
            log.info("")
            log.info("*" * 70)
            log.info("  PIPELINE COMPLETE (narrative only) — %s", query_id)
            log.info("  Total time: %.1fs", elapsed / 1000)
            log.info("*" * 70)
            return {
                "query_id": query_id,
                "status": "complete",
                "narrative": analysis.get("narrative", {}),
                "file": None,
                "follow_ups": follow_ups,
                "time_ms": elapsed,
            }

        # Step 4 + 5: Generate code, validate, execute — with auto-retry on failure
        t4 = time.time()
        filename = f"report_{query_id}.{doc_format}"
        output_path = str(generated_dir / filename)
        log.info("[STEP 4/5] Coding Agent — Generating %s code...", doc_format.upper())
        code = await coding_agent.generate(analysis, output_path)
        log.info("[STEP 4/5] Code generation complete in %.1fs (%d lines)", time.time() - t4, code.count("\n") + 1)

        max_retries = 2
        last_error = None
        for attempt in range(max_retries + 1):
            # Validate syntax before executing
            syntax_err = validate_syntax(code)
            if syntax_err:
                log.warning("[STEP 5/5] Syntax error on attempt %d/%d: %s", attempt + 1, max_retries + 1, syntax_err[:150])
                if attempt < max_retries:
                    log.info("[STEP 5/5] Sending code back to LLM for fix...")
                    code = await coding_agent.fix_code(code, syntax_err, output_path)
                    continue
                else:
                    last_error = f"Syntax error after {max_retries + 1} attempts: {syntax_err}"
                    break

            # Execute in sandbox
            log.info("[STEP 5/5] Sandbox — Executing generated code (attempt %d/%d)...", attempt + 1, max_retries + 1)
            try:
                t5 = time.time()
                execute(code, output_path)
                log.info("[STEP 5/5] Sandbox execution complete in %.1fs", time.time() - t5)
                last_error = None
                break
            except SandboxError as e:
                last_error = str(e)
                log.error("[STEP 5/5] Sandbox FAILED on attempt %d/%d: %s", attempt + 1, max_retries + 1, last_error[:200])
                if attempt < max_retries:
                    log.info("[STEP 5/5] Sending error back to LLM for fix...")
                    code = await coding_agent.fix_code(code, last_error, output_path)

        if last_error:
            elapsed = int((time.time() - start) * 1000)
            narrative = analysis.get("narrative", {})
            log.info("*" * 70)
            log.info("  PIPELINE PARTIAL — %s (document failed after %d attempts, narrative returned)", query_id, max_retries + 1)
            log.info("  Total time: %.1fs", elapsed / 1000)
            log.info("*" * 70)
            return {
                "query_id": query_id,
                "status": "complete",
                "narrative": narrative,
                "file": None,
                "follow_ups": follow_ups,
                "time_ms": elapsed,
                "error": None,
            }

        # Step 6: Assemble response
        file_size = os.path.getsize(output_path) // 1024
        elapsed = int((time.time() - start) * 1000)

        log.info("")
        log.info("*" * 70)
        log.info("  PIPELINE COMPLETE — %s", query_id)
        log.info("  Total time: %.1fs", elapsed / 1000)
        log.info("  Output: %s (%d KB)", filename, file_size)
        log.info("*" * 70)

        return {
            "query_id": query_id,
            "status": "complete",
            "narrative": analysis.get("narrative", {}),
            "file": {
                "name": filename,
                "download_url": f"/api/download/{filename}",
                "size_kb": file_size,
            },
            "follow_ups": follow_ups,
            "time_ms": elapsed,
        }

    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        log.error("")
        log.error("*" * 70)
        log.error("  PIPELINE ERROR — %s", query_id)
        log.error("  Error: %s", str(e)[:300])
        log.error("  Total time: %.1fs", elapsed / 1000)
        log.error("*" * 70)
        return {
            "query_id": query_id,
            "status": "error",
            "narrative": None,
            "file": None,
            "follow_ups": [],
            "time_ms": elapsed,
            "error": str(e)[:500],
        }
