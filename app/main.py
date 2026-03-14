from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from app.routers import companies, transcripts, analysis

app = FastAPI(title="earnings-lens", version="0.1.0")

app.include_router(companies.router)
app.include_router(transcripts.router)
app.include_router(analysis.router)

# Serve frontend
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_frontend():
        return FileResponse(os.path.join(frontend_dir, "index.html"))


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
