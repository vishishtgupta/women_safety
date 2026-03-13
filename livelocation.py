from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pymongo import MongoClient

# --- DATABASE SETUP ---
# WARNING: It is highly recommended to move this string into a .env file later 
# so your password isn't exposed if you push this to GitHub.
MONGO_URI = "mongodb+srv://vishishtgupta2006:vishi132006@vishisht.zuowk0i.mongodb.net/?retryWrites=true&w=majority&authSource=admin"
client = MongoClient(MONGO_URI)
db = client["women_safety"]
location_collection = db["live_locations"]

router = APIRouter()

class LocationData(BaseModel):
    latitude: float
    longitude: float

@router.post("/save-location")
def save_location(data: LocationData):
    try:
        # Save the validated coordinates directly to MongoDB
        result = location_collection.insert_one(data.model_dump())
        
        return {
            "status": "ok",
            "message": "Location saved securely",
            "id": str(result.inserted_id),
            "latitude": data.latitude,
            "longitude": data.longitude
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))