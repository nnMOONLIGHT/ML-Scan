from datetime import datetime, time
from io import BytesIO
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from PIL import Image

from ml.inference import predict

app = FastAPI(title="TrayEye API", version="0.2.0",
              description="Prototype API for cafeteria tray-waste monitoring.")

# Demo-only in-memory storage. Replace with a database before production.
settings = {"breakfast_start": "08:00", "lunch_start": "12:00"}
menu = [
    {"id": 1, "meal": "Завтрак", "name": "Каша", "category": "гарнир"},
    {"id": 2, "meal": "Обед", "name": "Рыба", "category": "рыба"},
    {"id": 3, "meal": "Обед", "name": "Овощи", "category": "овощи"},
]
events = [{
    "id": 1001, "created_at": datetime.now().isoformat(timespec="minutes"),
    "meal": "Обед", "items": [], "status": "review", "confidence": None,
    "note": "Демо-событие: требуется ручная проверка."
}]

class ScheduleUpdate(BaseModel):
    breakfast_start: str = "08:00"
    lunch_start: str = "12:00"

class MenuItem(BaseModel):
    meal: str = Field(pattern="^(Завтрак|Обед)$")
    name: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=50)

class ReviewUpdate(BaseModel):
    status: str = Field(pattern="^(approved|corrected|dismissed|review)$")
    note: Optional[str] = Field(default=None, max_length=500)
    items: Optional[list[str]] = None

def parse_hhmm(value: str) -> time:
    try:
        return time.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid time: {value}; expected HH:MM")

def meal_for_now(now: Optional[datetime] = None) -> str:
    now = now or datetime.now()
    start = parse_hhmm(settings["breakfast_start"])
    lunch = parse_hhmm(settings["lunch_start"])
    current = now.time().replace(tzinfo=None)
    return "Завтрак" if start <= current < lunch else "Обед"

@app.get("/health")
def health():
    return {"status": "ok", "service": "TrayEye API",
            "model_weights_configured": bool(__import__("os").getenv("TRAYEYE_MODEL_PATH"))}

@app.get("/api/schedule")
def get_schedule():
    return {**settings, "current_meal": meal_for_now(),
            "timezone_note": "Uses server local time in this prototype."}

@app.put("/api/schedule")
def update_schedule(payload: ScheduleUpdate):
    start, lunch = parse_hhmm(payload.breakfast_start), parse_hhmm(payload.lunch_start)
    if start >= lunch:
        raise HTTPException(status_code=422, detail="Breakfast start must be earlier than lunch start.")
    settings.update(payload.model_dump())
    return get_schedule()

@app.get("/api/menu")
def get_menu():
    return menu

@app.post("/api/menu")
def add_menu_item(payload: MenuItem):
    item = {"id": max([x["id"] for x in menu], default=0) + 1, **payload.model_dump()}
    menu.append(item)
    return item

@app.delete("/api/menu/{item_id}")
def delete_menu_item(item_id: int):
    for i, item in enumerate(menu):
        if item["id"] == item_id:
            return {"deleted": menu.pop(i)}
    raise HTTPException(status_code=404, detail="Menu item not found")

@app.get("/api/events")
def list_events(status: Optional[str] = None):
    return [e for e in reversed(events) if status is None or e["status"] == status]

@app.delete("/api/events/{event_id}")
def delete_event(event_id: int):
    """Delete one event when an administrator confirms cleanup."""
    for index, event in enumerate(events):
        if event["id"] == event_id:
            return {"deleted": events.pop(index), "success": True}
    raise HTTPException(status_code=404, detail="Event not found")

@app.patch("/api/events/{event_id}")
def review_event(event_id: int, payload: ReviewUpdate):
    for event in events:
        if event["id"] == event_id:
            event["status"] = payload.status
            if payload.note is not None:
                event["note"] = payload.note
            if payload.items is not None:
                event["items"] = payload.items
            event["reviewed_at"] = datetime.now().isoformat(timespec="seconds")
            return event
    raise HTTPException(status_code=404, detail="Event not found")

@app.post("/api/infer")
async def infer_image(file: UploadFile = File(...)):
    """Run optional trained model; if absent, enqueue for human review."""
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="Upload a JPEG, PNG, or WebP image.")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image limit is 10 MB.")
    try:
        probe = Image.open(BytesIO(data))
        probe.verify()
        image = Image.open(BytesIO(data)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="File is not a valid image.")
    try:
        inference = predict(image)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    predictions = inference.get("predictions", [])
    labels = sorted({p["label"] for p in predictions})
    event = {
        "id": max([e["id"] for e in events], default=1000) + 1,
        "created_at": datetime.now().isoformat(timespec="minutes"),
        "meal": meal_for_now(), "items": labels, "status": "review",
        "plate_status": inference.get("plate_status", "unknown"),
        "model_ready": inference.get("model_ready", False),
        "confidence": max([p["confidence"] for p in predictions], default=None),
        "predictions": predictions,
        "note": inference["message"],
        "filename": file.filename or "upload"
    }
    events.append(event)
    return {"event": event, "inference": {
        **inference, "requires_human_review": True
    }}
