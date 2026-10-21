"""Local-only FastAPI entry point for the academic review dashboard."""
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from dashboard.adapter import catalog, simulation, comparison

app = FastAPI(title="AutoScheduler Review Demo", docs_url=None, redoc_url=None)


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exception: Exception):
    logging.getLogger(__name__).error("Dashboard request failed", exc_info=exception)
    return JSONResponse(status_code=500, content={"detail": "The demo could not load this result. Try another workload or check the local server terminal."})


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "local_simulator_demo"}


@app.get("/api/catalog")
def get_catalog():
    return catalog()


@app.get("/api/simulation")
def get_simulation(workload: str = "short_jobs", algorithm: str = "Round Robin"):
    try:
        return simulation(workload, algorithm)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error


@app.get("/api/comparison")
def get_comparison(workload: str = "short_jobs"):
    try:
        return comparison(workload)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error


dist = Path(__file__).parent / "web/dist"
if dist.is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")
