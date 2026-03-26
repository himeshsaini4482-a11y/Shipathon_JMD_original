import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from core.config import config
from core.schemas import QueryRequest, PipelineResponse, EmailActionRequest, SlotSelectionRequest, EmployeeSelectionRequest
from core.orchestrator import process_query
from core.onboarding_orchestrator import (
    is_onboarding_request, handle_onboarding_message,
    handle_email_action, handle_slot_selection, handle_employee_selection, get_dashboard,
)

# Configure logging for all modules
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-16s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
)

log = logging.getLogger("service")

app = FastAPI(title="Finance Agent")


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    ui_path = Path(__file__).parent / "ui" / "index.html"
    return HTMLResponse(content=ui_path.read_text(encoding="utf-8"))


@app.post("/api/query")
async def handle_query(req: QueryRequest):
    log.info("Incoming request: query=%r, format=%s, history_turns=%d",
             req.query, req.format, len(req.conversation_history))
    history = [{"role": t.role, "content": t.content} for t in req.conversation_history]

    # Route: onboarding or finance?
    if is_onboarding_request(req.query):
        log.info("Routing to onboarding orchestrator")
        result = await handle_onboarding_message(req.query, history)
        return result

    # Existing finance pipeline (unchanged)
    result = await process_query(req.query, req.format, history)
    log.info("Response: status=%s, time=%dms, file=%s",
             result.get("status"), result.get("time_ms", 0),
             result.get("file", {}).get("name") if result.get("file") else "none")
    return result


@app.post("/api/onboarding/select-employee")
async def onboarding_select_employee(req: EmployeeSelectionRequest):
    log.info("Employee selection: onboarding_id=%d", req.onboarding_id)
    result = await handle_employee_selection(req.onboarding_id)
    return result


@app.post("/api/onboarding/{onboarding_id}/email-action")
async def onboarding_email_action(onboarding_id: int, req: EmailActionRequest):
    log.info("Email action: onboarding_id=%d, action=%s", onboarding_id, req.action)
    result = await handle_email_action(onboarding_id, req.action, req.feedback)
    return result


@app.post("/api/onboarding/{onboarding_id}/select-slot")
async def onboarding_select_slot(onboarding_id: int, req: SlotSelectionRequest):
    log.info("Slot selection: onboarding_id=%d, slot_index=%d", onboarding_id, req.slot_index)
    result = await handle_slot_selection(onboarding_id, req.slot_index)
    return result


@app.get("/api/onboarding/dashboard")
async def onboarding_dashboard():
    log.info("Dashboard request")
    result = await get_dashboard()
    return result


@app.get("/api/download/{filename}")
async def download_file(filename: str):
    log.info("Download request: %s", filename)
    # Prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = Path(config.generated_dir).resolve() / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    ext = file_path.suffix.lower()
    media_types = {
        ".pdf": "application/pdf",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    if ext == ".pdf":
        return FileResponse(
            str(file_path),
            media_type=media_type,
            headers={"Content-Disposition": f"inline; filename={filename}"},
        )
    return FileResponse(
        str(file_path),
        media_type=media_type,
        filename=filename,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.server_host, port=config.server_port)
