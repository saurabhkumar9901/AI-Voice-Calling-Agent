from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
import math

app = FastAPI(title="FOIR Eligibility Service", version="1.0.0")

# Per-lac EMI @ 11% ROI as given by client
PER_LAC_EMI = {
    5: 2174,
    6: 1903,  # default - all banks offer up to 6 years
    7: 1712,  # only some banks
}

FOIR_CAP = 0.70


class FoirRequest(BaseModel):
    net_monthly_income: float = Field(..., gt=0, description="LOCKED net monthly income/salary")
    existing_emi: float = Field(..., ge=0, description="LOCKED existing EMI, 0 if none")
    other_obligations: Optional[float] = Field(0, ge=0, description="Other monthly obligations")
    tenure_years: int = Field(..., description="5, 6 or 7 - ask customer, default 6")


class FoirResponse(BaseModel):
    max_total_emi: float
    available_emi: float
    per_lac_emi: int
    max_loan_amount: float
    max_loan_lakh: float
    tenure_years: int
    eligible: bool
    message: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/calculate-foir", response_model=FoirResponse)
def calculate_foir(req: FoirRequest):
    if req.tenure_years not in PER_LAC_EMI:
        raise HTTPException(status_code=400, detail="tenure_years must be 5, 6 or 7")

    other = req.other_obligations or 0
    max_total = round(req.net_monthly_income * FOIR_CAP, 2)
    available = round(max_total - req.existing_emi - other, 2)
    per_lac = PER_LAC_EMI[req.tenure_years]

    if available <= 0:
        return FoirResponse(
            max_total_emi=max_total,
            available_emi=available,
            per_lac_emi=per_lac,
            max_loan_amount=0,
            max_loan_lakh=0,
            tenure_years=req.tenure_years,
            eligible=False,
            message="Is profile par eligibility limited ho sakti hai.",
        )

    max_loan = available / per_lac * 100000
    # floor to nearest 10k for clean voice speak-out
    max_loan = math.floor(max_loan / 10000) * 10000
    max_lakh = round(max_loan / 100000, 2)

    return FoirResponse(
        max_total_emi=max_total,
        available_emi=available,
        per_lac_emi=per_lac,
        max_loan_amount=max_loan,
        max_loan_lakh=max_lakh,
        tenure_years=req.tenure_years,
        eligible=True,
        message=f"{req.tenure_years} saal par lagbhag {max_lakh} lakh indicative eligibility",
    )
