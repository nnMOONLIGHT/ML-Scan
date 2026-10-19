"""TrayEye API with persistent SQL storage, searchable events and admin access control."""
import os
import secrets
from datetime import datetime, time, timezone
from io import BytesIO
from typing import Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, ConfigDict
from PIL import Image
from sqlalchemy import JSON, DateTime, Integer, String, Text, create_engine, or_, select, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session

from ml.inference import predict

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./trayeye.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class MenuRow(Base):
    __tablename__ = "menu_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meal: Mapped[str] = mapped_column(String(30), index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    category: Mapped[str] = mapped_column(String(50), default="другое")

class SettingRow(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(500))

class CameraRow(Base):
    __tablename__ = "cameras"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), default="Основная камера")
    url: Mapped[str] = mapped_column(String(500), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    enabled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class EventRow(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    meal: Mapped[str] = mapped_column(String(30), default="Обед", index=True)
    items: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="review", index=True)
    confidence: Mapped[Optional[float]] = mapped_column(nullable=True)
    plate_status: Mapped[str] = mapped_column(String(30), default="unknown")
    model_ready: Mapped[bool] = mapped_column(default=False)
    predictions: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str] = mapped_column(Text, default="")
    filename: Mapped[str] = mapped_column(String(255), default="")
    camera_id: Mapped[Optional[int]] = mapped_column(nullable=True)

class AuditRow(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(100), default="administrator")
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    details: Mapped[str] = mapped_column(Text, default="")

Base.metadata.create_all(engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def require_admin(x_admin_token: Optional[str] = Header(default=None)):
    expected = os.getenv("TRAYEYE_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Административный доступ не настроен: задайте TRAYEYE_ADMIN_TOKEN в переменных окружения API.")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий ключ администратора.")

app = FastAPI(title="TrayEye API", version="1.0.0", description="Система контроля пищевых отходов.")

class ScheduleUpdate(BaseModel):
    breakfast_start: str = "08:00"
    lunch_start: str = "12:00"

class MenuItem(BaseModel):
    meal: str = Field(pattern="^(Завтрак|Обед)$")
    name: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=50)

class ReviewUpdate(BaseModel):
    status: str = Field(pattern="^(approved|corrected|dismissed|review)$")
    note: Optional[str] = Field(default=None, max_length=2000)
    items: Optional[list[str]] = None

class CameraUpdate(BaseModel):
    name: str = Field(default="Основная камера", min_length=1, max_length=100)
    url: str = Field(default="", max_length=500)
    location: str = Field(default="", max_length=200)
    enabled: bool = False

def parse_hhmm(value: str) -> time:
    try:
        parsed = time.fromisoformat(value)
        if parsed.second or parsed.microsecond:
            raise ValueError
        return parsed
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Неверное время: {value}; ожидается HH:MM")

def log_action(db: Session, action: str, entity_type: str, entity_id: Optional[int] = None, details: str = ""):
    db.add(AuditRow(action=action, entity_type=entity_type, entity_id=entity_id, details=details[:2000]))

def meal_for_now(db: Session, now: Optional[datetime] = None) -> str:
    settings = {x.key: x.value for x in db.scalars(select(SettingRow)).all()}
    start = parse_hhmm(settings.get("breakfast_start", "08:00"))
    lunch = parse_hhmm(settings.get("lunch_start", "12:00"))
    current = (now or datetime.now()).time().replace(tzinfo=None)
    return "Завтрак" if start <= current < lunch else "Обед"

def event_dict(e: EventRow):
    return {"id": e.id, "created_at": e.created_at.isoformat(timespec="seconds") + "Z",
            "meal": e.meal, "items": e.items or [], "status": e.status,
            "confidence": e.confidence, "plate_status": e.plate_status,
            "model_ready": e.model_ready, "predictions": e.predictions or [],
            "note": e.note, "filename": e.filename, "camera_id": e.camera_id}

def menu_dict(x: MenuRow):
    return {"id": x.id, "meal": x.meal, "name": x.name, "category": x.category}

def camera_dict(x: CameraRow):
    return {"id": x.id, "name": x.name, "url": x.url, "location": x.location,
            "enabled": x.enabled, "created_at": x.created_at.isoformat() + "Z"}

@app.get("/health")
def health(db: Session = Depends(get_db)):
    return {"status": "ok", "service": "TrayEye API", "database": "connected",
            "model_weights_configured": bool(os.getenv("TRAYEYE_MODEL_PATH") and os.path.isfile(os.getenv("TRAYEYE_MODEL_PATH"))),
            "admin_auth_configured": bool(os.getenv("TRAYEYE_ADMIN_TOKEN"))}

@app.get("/api/schedule", dependencies=[Depends(require_admin)])
def get_schedule(db: Session = Depends(get_db)):
    values = {x.key: x.value for x in db.scalars(select(SettingRow)).all()}
    return {"breakfast_start": values.get("breakfast_start", "08:00"),
            "lunch_start": values.get("lunch_start", "12:00"),
            "current_meal": meal_for_now(db), "timezone_note": "Server local time; configure TZ in deployment."}

@app.put("/api/schedule", dependencies=[Depends(require_admin)])
def update_schedule(payload: ScheduleUpdate, db: Session = Depends(get_db)):
    start, lunch = parse_hhmm(payload.breakfast_start), parse_hhmm(payload.lunch_start)
    if start >= lunch:
        raise HTTPException(status_code=422, detail="Начало завтрака должно быть раньше начала обеда.")
    for key, value in payload.model_dump().items():
        row = db.get(SettingRow, key)
        if row: row.value = value
        else: db.add(SettingRow(key=key, value=value))
    log_action(db, "schedule.updated", "settings", details=str(payload.model_dump()))
    db.commit()
    return get_schedule(db)

@app.get("/api/menu", dependencies=[Depends(require_admin)])
def get_menu(db: Session = Depends(get_db)):
    return [menu_dict(x) for x in db.scalars(select(MenuRow).order_by(MenuRow.meal, MenuRow.name)).all()]

@app.post("/api/menu", dependencies=[Depends(require_admin)])
def add_menu_item(payload: MenuItem, db: Session = Depends(get_db)):
    row = MenuRow(meal=payload.meal, name=payload.name.strip(), category=payload.category)
    db.add(row); db.flush()
    log_action(db, "menu.created", "menu", row.id, row.name); db.commit(); db.refresh(row)
    return menu_dict(row)

@app.delete("/api/menu/{item_id}", dependencies=[Depends(require_admin)])
def delete_menu_item(item_id: int, db: Session = Depends(get_db)):
    row = db.get(MenuRow, item_id)
    if not row: raise HTTPException(status_code=404, detail="Блюдо не найдено.")
    payload = menu_dict(row)
    log_action(db, "menu.deleted", "menu", row.id, row.name); db.delete(row); db.commit()
    return {"deleted": payload, "success": True}

@app.get("/api/events", dependencies=[Depends(require_admin)])
def list_events(status: Optional[str] = None, q: str = Query(default="", max_length=200),
                meal: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
                limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
                db: Session = Depends(get_db)):
    stmt = select(EventRow)
    count_stmt = select(func.count()).select_from(EventRow)
    filters = []
    if status and status != "all": filters.append(EventRow.status == status)
    if meal and meal != "all": filters.append(EventRow.meal == meal)
    if q.strip():
        needle = f"%{q.strip()}%"
        filters.append(or_(EventRow.note.ilike(needle), EventRow.filename.ilike(needle),
                           EventRow.items.cast(String).ilike(needle), EventRow.id.cast(String).ilike(needle)))
    try:
        if date_from: filters.append(EventRow.created_at >= datetime.fromisoformat(date_from).replace(tzinfo=None))
        if date_to: filters.append(EventRow.created_at < datetime.fromisoformat(date_to).replace(tzinfo=None).replace(hour=23, minute=59, second=59))
    except ValueError:
        raise HTTPException(status_code=422, detail="Неверный формат даты. Используй YYYY-MM-DD.")
    if filters:
        from sqlalchemy import and_
        stmt = stmt.where(and_(*filters)); count_stmt = count_stmt.where(and_(*filters))
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(EventRow.created_at.desc(), EventRow.id.desc()).offset(offset).limit(limit)).all()
    return {"items": [event_dict(e) for e in rows], "total": total, "limit": limit, "offset": offset}

@app.get("/api/events/{event_id}", dependencies=[Depends(require_admin)])
def get_event(event_id: int, db: Session = Depends(get_db)):
    row = db.get(EventRow, event_id)
    if not row: raise HTTPException(status_code=404, detail="Событие не найдено.")
    return event_dict(row)

@app.patch("/api/events/{event_id}", dependencies=[Depends(require_admin)])
def review_event(event_id: int, payload: ReviewUpdate, db: Session = Depends(get_db)):
    row = db.get(EventRow, event_id)
    if not row: raise HTTPException(status_code=404, detail="Событие не найдено.")
    before = {"status": row.status, "items": row.items}
    row.status = payload.status
    if payload.note is not None: row.note = payload.note
    if payload.items is not None: row.items = [x.strip()[:100] for x in payload.items if x.strip()][:100]
    log_action(db, "event.reviewed", "event", row.id, f"before={before}; after={payload.model_dump()}")
    db.commit(); db.refresh(row)
    return event_dict(row)

@app.delete("/api/events/{event_id}", dependencies=[Depends(require_admin)])
def delete_event(event_id: int, db: Session = Depends(get_db)):
    row = db.get(EventRow, event_id)
    if not row: raise HTTPException(status_code=404, detail="Событие не найдено.")
    log_action(db, "event.deleted", "event", row.id, f"filename={row.filename}; status={row.status}")
    db.delete(row); db.commit()
    return {"success": True, "deleted_id": event_id}

@app.post("/api/events/bulk-delete", dependencies=[Depends(require_admin)])
def bulk_delete_events(ids: list[int], db: Session = Depends(get_db)):
    ids = list(dict.fromkeys(ids))
    if not ids or len(ids) > 100: raise HTTPException(status_code=422, detail="Передай от 1 до 100 ID событий.")
    rows = db.scalars(select(EventRow).where(EventRow.id.in_(ids))).all()
    for row in rows: log_action(db, "event.deleted", "event", row.id, f"bulk delete; filename={row.filename}")
    for row in rows: db.delete(row)
    db.commit()
    return {"success": True, "deleted_count": len(rows), "requested_count": len(ids)}

@app.get("/api/audit", dependencies=[Depends(require_admin)])
def list_audit(q: str = Query(default="", max_length=200), limit: int = Query(default=100, ge=1, le=500),
               db: Session = Depends(get_db)):
    stmt = select(AuditRow)
    if q.strip(): stmt = stmt.where(or_(AuditRow.action.ilike(f"%{q}%"), AuditRow.details.ilike(f"%{q}%"), AuditRow.entity_type.ilike(f"%{q}%")))
    rows = db.scalars(stmt.order_by(AuditRow.created_at.desc()).limit(limit)).all()
    return [{"id": r.id, "created_at": r.created_at.isoformat() + "Z", "actor": r.actor,
             "action": r.action, "entity_type": r.entity_type, "entity_id": r.entity_id, "details": r.details} for r in rows]

@app.get("/api/cameras", dependencies=[Depends(require_admin)])
def list_cameras(db: Session = Depends(get_db)):
    return [camera_dict(x) for x in db.scalars(select(CameraRow).order_by(CameraRow.id)).all()]

@app.post("/api/cameras", dependencies=[Depends(require_admin)])
def save_camera(payload: CameraUpdate, db: Session = Depends(get_db)):
    url = payload.url.strip()
    if url and not url.startswith(("rtsp://", "rtsps://", "http://", "https://")):
        raise HTTPException(status_code=422, detail="URL камеры должен начинаться с rtsp://, rtsps://, http:// или https://.")
    row = CameraRow(name=payload.name.strip(), url=url, location=payload.location.strip(), enabled=payload.enabled)
    db.add(row); db.flush()
    log_action(db, "camera.created", "camera", row.id, f"name={row.name}; enabled={row.enabled}")
    db.commit(); db.refresh(row)
    return camera_dict(row)

@app.patch("/api/cameras/{camera_id}", dependencies=[Depends(require_admin)])
def update_camera(camera_id: int, payload: CameraUpdate, db: Session = Depends(get_db)):
    row = db.get(CameraRow, camera_id)
    if not row: raise HTTPException(status_code=404, detail="Камера не найдена.")
    url = payload.url.strip()
    if url and not url.startswith(("rtsp://", "rtsps://", "http://", "https://")):
        raise HTTPException(status_code=422, detail="Неверный URL камеры.")
    row.name, row.url, row.location, row.enabled = payload.name.strip(), url, payload.location.strip(), payload.enabled
    log_action(db, "camera.updated", "camera", row.id, f"name={row.name}; enabled={row.enabled}")
    db.commit(); db.refresh(row)
    return camera_dict(row)

@app.delete("/api/cameras/{camera_id}", dependencies=[Depends(require_admin)])
def delete_camera(camera_id: int, db: Session = Depends(get_db)):
    row = db.get(CameraRow, camera_id)
    if not row: raise HTTPException(status_code=404, detail="Камера не найдена.")
    log_action(db, "camera.deleted", "camera", row.id, row.name); db.delete(row); db.commit()
    return {"success": True, "deleted_id": camera_id}

@app.post("/api/infer", dependencies=[Depends(require_admin)])
async def infer_image(file: UploadFile = File(...), camera_id: Optional[int] = None, db: Session = Depends(get_db)):
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="Загрузите изображение JPEG, PNG или WebP.")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024: raise HTTPException(status_code=413, detail="Лимит изображения — 10 МБ.")
    try:
        probe = Image.open(BytesIO(data)); probe.verify()
        image = Image.open(BytesIO(data)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="Файл не является корректным изображением.")
    try: inference = predict(image)
    except (RuntimeError, ValueError) as exc: raise HTTPException(status_code=503, detail=str(exc))
    predictions = inference.get("predictions", [])
    labels = sorted({p["label"] for p in predictions})
    row = EventRow(meal=meal_for_now(db), items=labels, status="review",
        plate_status=inference.get("plate_status", "unknown"), model_ready=inference.get("model_ready", False),
        confidence=max((p["confidence"] for p in predictions), default=None), predictions=predictions,
        note=inference.get("message", "Требуется ручная проверка."), filename=(file.filename or "upload")[:255],
        camera_id=camera_id)
    db.add(row); db.flush()
    log_action(db, "inference.created", "event", row.id, f"model_ready={row.model_ready}; detections={len(predictions)}")
    db.commit(); db.refresh(row)
    return {"event": event_dict(row), "inference": {**inference, "requires_human_review": True}}

@app.on_event("startup")
def seed_defaults():
    with SessionLocal() as db:
        if not db.scalars(select(SettingRow)).first():
            db.add_all([SettingRow(key="breakfast_start", value="08:00"), SettingRow(key="lunch_start", value="12:00")])
        if not db.scalars(select(MenuRow)).first():
            db.add_all([MenuRow(meal="Завтрак", name="Каша", category="гарнир"),
                        MenuRow(meal="Обед", name="Рыба", category="рыба"),
                        MenuRow(meal="Обед", name="Овощи", category="овощи")])
        db.commit()
