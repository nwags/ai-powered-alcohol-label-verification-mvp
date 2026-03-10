from fastapi import FastAPI

app = FastAPI(title="AI-Powered Alcohol Label Verification")

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.get("/readyz")
def readyz():
    return {"status": "ready", "ocr_loaded": False, "storage_ok": True, "db_ok": True}
