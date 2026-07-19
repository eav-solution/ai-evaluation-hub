from fastapi import FastAPI

from app.routers import (
    assets,
    auth,
    datasets,
    documents,
    endpoint_test,
    exports,
    generation,
    ingestions,
    metrics,
    model_benchmarks,
    provider_connections,
    reasoning_benchmarks,
    runs,
    workspaces,
)

app = FastAPI(title="AI Evaluation Hub")
app.add_middleware(ingestions.AgentTraceBodyLimitMiddleware)
app.include_router(assets.router)
app.include_router(auth.router)
app.include_router(workspaces.router)
app.include_router(provider_connections.router)
app.include_router(datasets.router)
app.include_router(documents.router)
app.include_router(generation.router)
app.include_router(ingestions.router)
app.include_router(endpoint_test.router)
app.include_router(metrics.router)
app.include_router(model_benchmarks.router)
app.include_router(reasoning_benchmarks.router)
app.include_router(exports.router)
app.include_router(runs.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
