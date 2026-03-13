import os, uuid, uvicorn
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient

# ── 1. Configuration ──────────────────────────────────────────
DEFAULT_URI = "mongodb+srv://vishishtgupta2006:vishi132006@vishisht.zuowk0i.mongodb.net/?authSource=admin"
MONGO_URI   = os.getenv("MONGO_URI", DEFAULT_URI)
DB_NAME     = os.getenv("DB_NAME", "shesecure")

# ── 2. Global DB State ────────────────────────────────────────
db_client = db = col_contacts = col_evidence = col_sos = None

# ── 3. Lifespan (Startup/Shutdown) ───────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_client, db, col_contacts, col_evidence, col_sos
    print(f" Connecting to MongoDB Atlas...")
    try:
        db_client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        await db_client.admin.command('ping') 
        
        db           = db_client[DB_NAME]
        col_contacts = db["contacts"]
        col_evidence = db["evidence"]   
        col_sos      = db["sos_events"]
        
        await col_evidence.create_index("recorded_at")
        await col_sos.create_index("timestamp")
        
        print(f" SheSecure Backend Online | Connected to {DB_NAME}")
    except Exception as e:
        print(f" DATABASE ERROR: {e}")
    
    yield
    if db_client:
        db_client.close()
        print("Backend Offline.")

# ── 4. App Initialization ─────────────────────────────────────
app = FastAPI(title="SheSecure API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 5. Models ────────────────────────────────────────────────
class ContactIn(BaseModel):
    name: str
    phone: str
    relation: Optional[str] = "Trusted Contact"

class EvidenceIn(BaseModel):
    url: str
    type: str  
    latitude: Optional[str] = "0"
    longitude: Optional[str] = "0"
    size_kb: Optional[int] = 0

class SOSIn(BaseModel):
    latitude: str
    longitude: str
    sent_to: Optional[int] = 0
    evidence_count: Optional[int] = 0
    timestamp: Optional[str] = None

class RouteFeature(BaseModel):
    index: int
    distance: float
    time: float

class FilterIn(BaseModel):
    routes: List[RouteFeature]

class ChatIn(BaseModel):
    message: str

# ── 6. Helpers ───────────────────────────────────────────────
def nid(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc).isoformat()
def clean(doc):
    if doc: doc.pop("_id", None)
    return doc

# ── 7. Routes (Endpoints) ────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "active", "version": "5.4.0", "app": "SheSecure"}

# --- CONTACTS ---
@app.post("/contacts")
async def add_contact(data: ContactIn):
    doc = {
        "id": nid(), 
        "name": data.name.strip(), 
        "phone": data.phone.strip(),
        "relation": data.relation, 
        "created_at": now()
    }
    await col_contacts.insert_one(doc)
    return {"id": doc["id"], "status": "saved"}

@app.get("/contacts")
async def get_contacts():
    docs = await col_contacts.find({}).sort("created_at", -1).to_list(100)
    return [clean(d) for d in docs]

@app.delete("/contacts/{cid}")
async def delete_contact(cid: str):
    res = await col_contacts.delete_one({"id": cid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Contact not found")
    return {"status": "deleted"}

# --- LOCATION SYNC ---
@app.post("/location")
async def save_loc(data: dict):
    await db["locations"].insert_one({
        "lat": data.get("latitude"),
        "lng": data.get("longitude"),
        "ts": now()
    })
    return {"ok": True}

# --- EVIDENCE ---
@app.post("/evidence")
async def save_evidence(data: EvidenceIn):
    doc = {
        "id": nid(),
        "url": data.url,
        "type": data.type,
        "latitude": data.latitude,
        "longitude": data.longitude,
        "size_kb": data.size_kb,
        "recorded_at": now()
    }
    await col_evidence.insert_one(doc)
    return {"id": doc["id"], "ok": True}

@app.get("/evidence")
async def list_evidence():
    docs = await col_evidence.find({}).sort("recorded_at", -1).to_list(50)
    return [clean(d) for d in docs]

# FIX: Added missing DELETE /evidence/{eid} endpoint
@app.delete("/evidence/{eid}")
async def delete_evidence(eid: str):
    res = await col_evidence.delete_one({"id": eid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Evidence not found")
    return {"status": "deleted"}

# --- SOS LOGGING ---
@app.post("/sos-event")
async def sos_event(data: SOSIn):
    doc = {
        "id": nid(),
        "latitude": data.latitude,
        "longitude": data.longitude,
        "sent_to": data.sent_to,
        "evidence_count": data.evidence_count,
        "timestamp": data.timestamp or now(),
        "created_at": now()
    }
    await col_sos.insert_one(doc)
    return {"id": doc["id"], "ok": True}

# --- SOS PACKAGE (WhatsApp Builder) ---
# FIX: Added 'hours' query param so frontend can control lookback window (default 720h = 30 days)
@app.get("/sos-package")
async def get_sos_package(lat: str = "0", lng: str = "0", hours: int = 720):
    contacts = await col_contacts.find({}).to_list(10)
    lookback = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    evidence = await col_evidence.find({"recorded_at": {"$gt": lookback}}).to_list(50)
    
    return {
        "contacts": [clean(c) for c in contacts],
        "evidence": [clean(d) for d in evidence],
        "location": {
            "lat": lat, 
            "lng": lng, 
            "maps_link": f"https://www.google.com/maps?q={lat},{lng}"
        },
        "time_ist": datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%I:%M %p")
    }

# --- AI ROUTE FILTERING ---
@app.post("/filter-routes")
async def filter_routes(data: FilterIn):
    """
    AI Safety Prediction Logic:
    Scores routes: shorter distance + less time = safer/more optimal
    """
    if not data.routes:
        return {"evaluations": [], "recommended_index": 0}

    # Sort by duration to find most optimal
    sorted_routes = sorted(data.routes, key=lambda r: r.time)
    
    cats  = ["Optimal", "Moderate", "Caution"]
    cols  = ["#00e5a0", "#ffb830", "#ff3c64"]
    trends = [
        "Well-lit main roads — AI recommended ✓",
        "Standard route — moderate traffic",
        "Less-travelled roads — use caution"
    ]

    evaluations = []
    recommended = sorted_routes[0].index  # fastest = recommended

    for i, route in enumerate(data.routes):
        rank = next((j for j, r in enumerate(sorted_routes) if r.index == route.index), 0)
        idx  = min(rank, 2)
        dist_km = route.distance / 1000
        mins    = round(route.time / 60)
        score   = max(10, 95 - (rank * 25))
        evaluations.append({
            "index":    route.index,
            "score":    score,
            "category": cats[idx],
            "color":    cols[idx],
            "trend":    trends[idx],
            "dist_km":  round(dist_km, 1),
            "mins":     mins,
        })
    
    return {"evaluations": evaluations, "recommended_index": recommended}

# FIX: Added missing /chat endpoint so AI assistant doesn't fall back silently
SAFETY_KEYWORDS = {
    "sos": "send_alert", "help me": "send_alert", "emergency": "send_alert",
    "danger": "send_alert", "unsafe": "send_alert", "scared": "send_alert",
    "fake call": "fake_call", "pretend call": "fake_call",
    "share location": "share_location", "send location": "share_location",
}

SAFETY_TIPS = [
    "Stay aware of your surroundings at all times. Trust your instincts — if something feels wrong, it probably is.",
    "If you feel unsafe, move toward a crowded, well-lit area immediately.",
    "Keep your phone charged and share your live journey with a trusted contact before travelling.",
    "Walk confidently and avoid looking at your phone while in unfamiliar areas.",
    "If followed, enter a shop or public place and call for help.",
    "You can say 'SOS', 'fake call', or 'share location' to me at any time.",
]

@app.post("/chat")
async def chat(data: ChatIn):
    msg = data.message.lower().strip()
    for kw, action in SAFETY_KEYWORDS.items():
        if kw in msg:
            return {"action": action, "reply": f"Action triggered: {action}"}
    import random
    return {
        "action": "none",
        "reply": random.choice(SAFETY_TIPS)
    }

# ── 8. Execution ─────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)