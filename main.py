#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smart Cable Calculator - FastAPI Backend
API për llogaritjet e kabllove - Për Android App
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import math

# ==================== KONSTANTE ====================
VOLTAGE = 230.0
VOLTAGE_3PHASE = 400.0
RHO_CU_20 = 0.0175
AL_RHO_20 = 0.0282
ALPHA_CU = 0.00393
VOLTAGE_DROP_INTERNAL = 3.0
VOLTAGE_DROP_EXTERNAL = 5.0

CABLE_TABLE_CU = {1.5:16.5,2.5:23,4:30,6:38,10:52,16:70,25:94,35:119,50:149,70:184,95:226,120:260,150:300,185:342,240:405}
CABLE_TABLE_CU_AIR = {1.5:19.5,2.5:27,4:36,6:46,10:63,16:85,25:112,35:140,50:175,70:215,95:260,120:300,150:340,185:385,240:455}
CABLE_TABLE_AL = {16:55,25:73,35:92,50:115,70:142,95:175,120:201,150:232,185:266,240:315}

INSTALLATION_FACTORS = {"A1":0.70,"A2":0.80,"B1":0.85,"B2":0.90,"C":1.00}
MCB_RATINGS = [6,10,16,20,25,32,40,50,63,80,100,125,160]

# ==================== PYDANTIC MODELS ====================
class CalculationRequest(BaseModel):
    power: float
    length: float
    cosphi: float
    phases: int
    install: str
    load: str
    cable_material: str
    temp: float

class CalculationResponse(BaseModel):
    current: float
    section: float
    ampacity: float
    mcb_rating: int
    mcb_type: str
    pe: float
    voltage_drop: float
    compliance: list
    overall_ok: bool

# ==================== FASTAPI APP ====================
app = FastAPI(
    title="Cable Calculator API",
    description="API për llogaritjen e kabllove elektrike",
    version="1.0.0"
)

# Lejo CORS për Flutter App
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== FUNKSIONET E LLOGARITJES ====================
def get_cable_table(cable_material="cu", for_air=False):
    if cable_material == "al":
        table = CABLE_TABLE_AL
    else:
        table = CABLE_TABLE_CU_AIR if for_air else CABLE_TABLE_CU
    sections = sorted(list(table.keys()))
    return table, sections

def normalize_section_to_table(sections, desired):
    try:
        d = float(desired)
    except:
        return sections[-1]
    for s in sections:
        if float(s) >= d:
            return s
    return sections[-1]

def get_ampacity_for_section(table, sections, requested_section):
    if requested_section in table:
        return table[requested_section], requested_section
    try:
        reqf = float(requested_section)
        for s in sections:
            if float(s) == reqf:
                return table[s], s
    except:
        pass
    chosen = normalize_section_to_table(sections, requested_section)
    return table.get(chosen, 0), chosen

def calculate_current(power, cos_phi, num_phases):
    if num_phases == 1:
        return power / (VOLTAGE * cos_phi)
    else:
        return power / (math.sqrt(3) * VOLTAGE_3PHASE * cos_phi)

def calculate_voltage_drop(current, length, section, num_phases, cable_material="cu", cos_phi=0.9, temp_ambient=30):
    if section <= 0:
        raise ValueError("Seksioni duhet > 0")
    if str(cable_material).strip().lower() == "cu":
        rho = RHO_CU_20 * (1.0 + ALPHA_CU * (float(temp_ambient) - 20.0))
    else:
        rho = AL_RHO_20 * (1.0 + 0.0039 * (float(temp_ambient) - 20.0))
    R_per_m = rho / float(section)
    if section <= 10:
        X_per_m = 0.00008
    elif section <= 50:
        X_per_m = 0.000075
    else:
        X_per_m = 0.00007
    sin_phi = math.sqrt(max(0.0, 1.0 - cos_phi * cos_phi))
    if num_phases == 1:
        delta_u = 2.0 * current * length * (R_per_m * cos_phi + X_per_m * sin_phi)
        nominal = VOLTAGE
    else:
        delta_u = math.sqrt(3) * current * length * (R_per_m * cos_phi + X_per_m * sin_phi)
        nominal = VOLTAGE_3PHASE
    return (delta_u / nominal) * 100.0

def calculate_min_cable_section_by_current(current, installation_code, cable_material="cu"):
    for_air = (installation_code == "C")
    table, sections = get_cable_table(cable_material, for_air)
    correction = INSTALLATION_FACTORS.get(installation_code, 1.0)
    corrected = current / correction
    for s in sections:
        if table.get(s, 0) >= corrected:
            return s
    return sections[-1]

def calculate_min_cable_section_by_voltage_drop(current, length, installation_code, num_phases=1, cable_material="cu", cos_phi=0.9, temp_ambient=30):
    max_vd = VOLTAGE_DROP_EXTERNAL if installation_code == "C" else VOLTAGE_DROP_INTERNAL
    if int(num_phases) == 1:
        max_vd = 3.0
    for_air = (installation_code == "C")
    table, sections = get_cable_table(cable_material, for_air)
    for s in sections:
        vd = calculate_voltage_drop(current, length, s, num_phases, cable_material, cos_phi, temp_ambient)
        if vd <= max_vd:
            return s, vd
    s = sections[-1]
    return s, calculate_voltage_drop(current, length, s, num_phases, cable_material, cos_phi, temp_ambient)

def calculate_earthing(section):
    try:
        s = float(section)
    except:
        return 16
    if s <= 16:
        return int(s)
    if s <= 35:
        return 16
    return max(16, int(round(s / 2)))

def calculate_final_cable_section(current, length, installation_code, num_phases=1, cable_material="cu", cos_phi=0.9, load_type=None, temp_ambient=30):
    min_required = 1.5
    try:
        lt = str(load_type or "").strip().lower()
        if "motor" in lt or "induktive" in lt:
            min_required = 2.5
        else:
            min_required = 1.5
    except:
        min_required = 1.5
    s1 = calculate_min_cable_section_by_current(current, installation_code, cable_material)
    s2, vd2 = calculate_min_cable_section_by_voltage_drop(current, length, installation_code, num_phases, cable_material, cos_phi, temp_ambient)
    desired = max(float(s1), float(s2), float(min_required))
    for_air = (installation_code == "C")
    table, sections = get_cable_table(cable_material, for_air)
    final_section = normalize_section_to_table(sections, desired)
    ampacity, final_section_key = get_ampacity_for_section(table, sections, final_section)
    vd_final = calculate_voltage_drop(current, length, final_section_key, num_phases, cable_material, cos_phi, temp_ambient)
    max_vd = VOLTAGE_DROP_EXTERNAL if installation_code == "C" else VOLTAGE_DROP_INTERNAL
    if int(num_phases) == 1:
        max_vd = 3.0
    try:
        if final_section_key not in sections:
            final_section_key = normalize_section_to_table(sections, final_section_key)
    except:
        final_section_key = normalize_section_to_table(sections, final_section)
    try:
        while float(vd_final) > float(max_vd):
            idx = sections.index(final_section_key)
            if idx + 1 < len(sections):
                final_section_key = sections[idx + 1]
                ampacity = table.get(final_section_key, ampacity)
                vd_final = calculate_voltage_drop(current, length, final_section_key, num_phases, cable_material, cos_phi, temp_ambient)
            else:
                break
    except:
        pass
    try:
        if float(final_section_key) < float(min_required):
            final_section_key = normalize_section_to_table(sections, min_required)
            ampacity = table.get(final_section_key, ampacity)
            vd_final = calculate_voltage_drop(current, length, final_section_key, num_phases, cable_material, cos_phi, temp_ambient)
    except:
        pass
    pe_section = calculate_earthing(final_section_key)
    return final_section_key, vd_final, ampacity, pe_section

def select_mcb(current, load_type, cable_section, cable_material="cu", installation_code="A1"):
    load_type_clean = (str(load_type).strip().lower() if load_type is not None else "")
    if "motor" in load_type_clean or "induktive" in load_type_clean:
        design_current = current * 1.25
        mcb_char = "C"
    else:
        design_current = current
        mcb_char = "B"
    for_air = (installation_code == "C")
    table, sections = get_cable_table(cable_material, for_air)
    ampacity, section_key = get_ampacity_for_section(table, sections, cable_section)
    candidate = next((r for r in MCB_RATINGS if r >= math.ceil(design_current)), MCB_RATINGS[-1])
    ok = True
    selected = candidate
    if ampacity <= 0:
        ok = False
    elif candidate > ampacity:
        ok = False
    return selected, mcb_char, ok

def check_legal_compliance(section, vd_percent, max_vd, current, mcb_rating, cable_ampacity):
    res = []
    ok = True
    if cable_ampacity <= 0:
        res.append({"title": "Kapaciteti", "status": "Të dhëna mungojnë", "ok": False})
        ok = False
    elif current <= cable_ampacity + 1e-9:
        res.append({"title": "Kapaciteti", "status": f"I_b ≤ I_z", "ok": True})
    else:
        res.append({"title": "Kapaciteti", "status": f"I_b > I_z", "ok": False})
        ok = False
    if vd_percent <= max_vd + 1e-9:
        res.append({"title": "Rënia e tensionit", "status": f"ΔU ≤ {max_vd}%", "ok": True})
    else:
        res.append({"title": "Rënia e tensionit", "status": f"ΔU > {max_vd}%", "ok": False})
        ok = False
    if mcb_rating >= math.ceil(current) and (cable_ampacity <= 0 or mcb_rating <= cable_ampacity):
        res.append({"title": "Mbrojtja", "status": "I_b ≤ I_n ≤ I_z", "ok": True})
    else:
        res.append({"title": "Mbrojtja", "status": "NUK plotësohet", "ok": False})
        ok = False
    try:
        if float(section) >= 1.5:
            res.append({"title": "Seksioni minimal", "status": "≥ 1.5 mm²", "ok": True})
        else:
            res.append({"title": "Seksioni minimal", "status": "< 1.5 mm²", "ok": False})
            ok = False
    except:
        res.append({"title": "Seksioni minimal", "status": "Gabim", "ok": False})
        ok = False
    return res, ok

# ==================== ROUTES ====================
@app.get("/")
async def root():
    return {
        "message": "Welcome to Cable Calculator API",
        "version": "1.0.0",
        "endpoints": [
            "/calculate - POST",
            "/health - GET"
        ]
    }

@app.get("/health")
async def health():
    return {"status": "OK", "message": "API is running"}

@app.post("/calculate", response_model=CalculationResponse)
async def calculate(request: CalculationRequest):
    try:
        # Validimi
        if request.power <= 0 or request.length <= 0:
            raise HTTPException(status_code=400, detail="Fuqia dhe gjatësia duhet > 0")
        if request.cosphi <= 0 or request.cosphi > 1:
            raise HTTPException(status_code=400, detail="cos φ duhet ndërmjet 0 dhe 1")
        
        # Llogaritje
        current = calculate_current(request.power, request.cosphi, request.phases)
        section, vd_percent, ampacity, pe = calculate_final_cable_section(
            current, request.length, request.install, request.phases, 
            request.cable_material, request.cosphi, request.load, request.temp
        )
        mcb_rating, mcb_type, mcb_ok = select_mcb(
            current, request.load, section, request.cable_material, request.install
        )
        
        max_vd = VOLTAGE_DROP_EXTERNAL if request.install == "C" else VOLTAGE_DROP_INTERNAL
        compliance_list, overall_ok = check_legal_compliance(
            section, vd_percent, max_vd, current, mcb_rating, ampacity
        )
        
        return CalculationResponse(
            current=round(current, 2),
            section=float(section),
            ampacity=ampacity,
            mcb_rating=mcb_rating,
            mcb_type=mcb_type,
            pe=pe,
            voltage_drop=round(vd_percent, 2),
            compliance=compliance_list,
            overall_ok=overall_ok
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==================== RUN ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
