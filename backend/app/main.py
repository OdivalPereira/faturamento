import os
import sys
import webbrowser
from threading import Timer
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from .api.endpoints import router
from .database.db import init_db

app = FastAPI(title="Auditor Portátil - Faturamento")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    init_db()
    Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8123")).start()

app.include_router(router, prefix="/api")

# Serve Frontend - look for "static" folder next to the backend package
def get_frontend_path():
    # Always relative to the project root (parent of backend/)
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "static")

frontend_path = get_frontend_path()

if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
    
    @app.exception_handler(404)
    async def not_found(request, exc):
        return FileResponse(os.path.join(frontend_path, "index.html"))
else:
    @app.get("/")
    async def root():
        return {"message": "Frontend not found.", "path_searched": frontend_path}
