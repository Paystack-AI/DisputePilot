from fastapi import FastAPI

app = FastAPI(title="Backend")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
