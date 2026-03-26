import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from core.config import config
from core.schemas import QueryRequest, PipelineResponse
from core.orchestrator import process_query

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
    result = await process_query(req.query, req.format, history)
    log.info("Response: status=%s, time=%dms, file=%s",
             result.get("status"), result.get("time_ms", 0),
             result.get("file", {}).get("name") if result.get("file") else "none")
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
