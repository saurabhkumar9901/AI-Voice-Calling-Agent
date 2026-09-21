"""Mock Appointment Booking API for testing Dograh Tools.

Run with:  python scripts/mock_appointment_api.py
Endpoint:  http://localhost:8089/book-appointment  (POST)
"""

import asyncio
import random
import string
from datetime import datetime

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="Mock Appointment API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store
appointments: list[dict] = []


class BookAppointmentRequest(BaseModel):
    customer_name: str = Field(description="Full name of the customer")
    date: str = Field(description="Appointment date (e.g., 2026-04-10)")
    time_slot: str = Field(description="Preferred time slot (e.g., 10:00 AM)")
    service_type: str = Field(description="Type of service requested")


@app.post("/book-appointment")
async def book_appointment(req: BookAppointmentRequest):
    confirmation_id = "APT-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    record = {
        "confirmation_id": confirmation_id,
        "customer_name": req.customer_name,
        "date": req.date,
        "time_slot": req.time_slot,
        "service_type": req.service_type,
        "booked_at": datetime.now().isoformat(),
    }
    appointments.append(record)
    print(f"\n{'='*50}")
    print(f"  NEW APPOINTMENT BOOKED!")
    print(f"  Confirmation: {confirmation_id}")
    print(f"  Customer:     {req.customer_name}")
    print(f"  Date:         {req.date}")
    print(f"  Time:         {req.time_slot}")
    print(f"  Service:      {req.service_type}")
    print(f"{'='*50}\n")
    return {
        "status": "confirmed",
        "confirmation_id": confirmation_id,
        "message": f"Appointment confirmed for {req.customer_name} on {req.date} at {req.time_slot} for {req.service_type}.",
    }


@app.get("/appointments")
async def list_appointments():
    return {"appointments": appointments, "total": len(appointments)}


class MedicalHistoryRequest(BaseModel):
    patient_name: str = Field(description="Name of the patient")
    dob: str = Field(description="Date of birth")


@app.post("/check-medical-history")
async def check_medical_history(req: MedicalHistoryRequest):
    print(f"\n[{datetime.now().isoformat()}] Received request to check medical history for {req.patient_name}...")
    print("Simulating a slow enterprise database lookup (8 seconds)...")
    
    # Intentionally sleep for 8 seconds to trigger the Dograh ambient backchannel fillers
    await asyncio.sleep(8)
    
    print("Database lookup complete!\n")
    return {
        "status": "success",
        "records_found": True,
        "patient": req.patient_name,
        "notes": f"Patient has no known allergies. Last visit was 6 months ago for general checkup.",
        "clearance": "cleared"
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8089)
