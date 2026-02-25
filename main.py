# main.py
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime

app = FastAPI(title="Nigeria Election Monitoring System")

# --------------------------------------------------
# PATHS & CONFIG (CORRECTED FOR RENDER/LINUX)
# --------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "data" / "full.json"
DB_PATH = BASE_DIR / "election.db"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure static directory exists for logos
(BASE_DIR / "static").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# --------------------------------------------------
# DATA LOADING & DB
# --------------------------------------------------
try:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        ALL_LOCATIONS = json.load(f)
except Exception:
    ALL_LOCATIONS = []

PARTIES = [
    {"name": "APC", "logo": "/static/logos/APC.png"},
    {"name": "PDP", "logo": "/static/logos/PDP.png"},
    {"name": "LP",  "logo": "/static/logos/LP.png"},
    {"name": "NNPP", "logo": "/static/logos/NNPP.png"},
    {"name": "ACCORD", "logo": "/static/logos/ACCORD.png"}
]

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state TEXT, lga TEXT, ward TEXT, pu_name TEXT,
            total_accredited INTEGER, rejected_votes INTEGER,
            incident_type TEXT, incident_desc TEXT,
            latitude REAL, longitude REAL,
            timestamp TEXT, votes_json TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --------------------------------------------------
# ROUTES
# --------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(INDEX_HTML)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(DASHBOARD_HTML)

@app.get("/locations/states")
def list_states():
    return [s["state"] for s in ALL_LOCATIONS]

@app.get("/locations/lgas/{state}")
def list_lgas(state: str):
    for s in ALL_LOCATIONS:
        if s["state"].lower() == state.lower():
            return [l["name"] for l in s["lgas"]]
    return []

@app.get("/locations/wards/{state}/{lga}")
def list_wards(state: str, lga: str):
    for s in ALL_LOCATIONS:
        if s["state"].lower() == state.lower():
            for l in s["lgas"]:
                if l["name"].lower() == lga.lower():
                    return l["wards"]
    return []

@app.get("/parties")
def get_parties():
    return PARTIES

@app.post("/submit")
async def submit_survey(data: dict):
    try:
        timestamp = datetime.utcnow().isoformat()
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO submissions (
                state, lga, ward, pu_name, total_accredited, rejected_votes,
                incident_type, incident_desc, latitude, longitude,
                timestamp, votes_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("state"), data.get("lga"), data.get("ward"), data.get("pu_name"),
            int(data.get("total_accredited") or 0), int(data.get("rejected_votes") or 0),
            data.get("incident_type"), data.get("incident_desc"),
            float(data.get("lat")) if data.get("lat") else None,
            float(data.get("lon")) if data.get("lon") else None,
            timestamp, json.dumps(data.get("votes") or {})
        ))
        conn.commit()
        conn.close()
        return {"status": "success", "message": "Submission successful."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/submissions")
def get_submissions():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM submissions ORDER BY timestamp DESC")
    rows = cursor.fetchall()
    conn.close()
    results = []
    for row in rows:
        r = dict(row)
        votes = json.loads(r.pop("votes_json") or "{}")
        for party, value in votes.items():
            r[f"votes_party_{party}"] = value
        results.append(r)
    return results

# --------------------------------------------------
# HTML TEMPLATES (JS FIXED FOR DYNAMIC WARD STRUCTURE)
# --------------------------------------------------

INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Election Monitoring - Government Portal</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap" rel="stylesheet">
<style>
body { font-family: 'Roboto', sans-serif; background: linear-gradient(to bottom, #f3f4f6, #e5e7eb); color: #111827; }
.navbar { background-color: #0b3d91; }
.navbar-brand, .navbar-text { color: #ffffff; font-weight: 600; }
.card-gov { border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); padding: 30px; background-color: #ffffff; }
.btn-gold { background-color: #ffc107; color: #0b3d91; font-weight: 600; }
.btn-gold:hover { background-color: #e0a800; color: #0b3d91; }
.section-title { font-weight: 700; text-transform: uppercase; margin-bottom: 12px; color: #0b3d91; }
footer { text-align: center; font-size: 13px; color: #6b7280; margin-top: 50px; }
img.party-logo { width: 50px; height: 50px; object-fit: contain; }
</style>
</head>
<body>
<nav class="navbar navbar-expand-lg px-4 py-3">
    <span class="navbar-brand">🗳 Nigeria Election Monitoring</span>
    <span class="navbar-text ms-auto">Field Officer Portal</span>
</nav>
<div class="container mt-5 mb-5">
    <div class="row justify-content-center">
        <div class="col-lg-8">
            <div class="card card-gov">
                <h3 class="mb-4 text-center fw-bold text-uppercase">Polling Unit Reporting</h3>
                <form id="surveyForm">
                    <div class="mb-4">
                        <div class="section-title">📍 Polling Unit Details</div>
                        <select id="stateSelect" class="form-select mb-3" required><option selected disabled>Select State</option></select>
                        <select id="lgaSelect" class="form-select mb-3" required><option selected disabled>Select LGA</option></select>
                        <select id="wardSelect" class="form-select mb-3" required><option selected disabled>Select Ward</option></select>
                        <input type="text" class="form-control" id="puName" placeholder="Polling Unit Name" required>
                    </div>
                    <div class="mb-4">
                        <div class="section-title">🗳 Votes</div>
                        <div id="partyVotes" class="row g-3"></div>
                    </div>
                    <div class="mb-4">
                        <div class="section-title">📊 Accreditation & Ballot Summary</div>
                        <div class="mb-3">
                            <label class="form-label fw-bold">Total Accredited Voters</label>
                            <input type="number" class="form-control" id="totalAccredited" placeholder="Enter total" min="0" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label fw-bold">Rejected Votes</label>
                            <input type="number" class="form-control" id="rejectedVotes" placeholder="Enter rejected" min="0" required>
                        </div>
                    </div>
                    <div class="mb-4">
                        <div class="section-title">⚠ Incident Information</div>
                        <select class="form-select mb-3" id="incidentType">
                            <option selected disabled>Select Incident Type</option>
                            <option>Violence</option><option>Late Opening</option><option>Ballot Shortage</option><option>Equipment Failure</option>
                        </select>
                        <textarea class="form-control" rows="4" id="incidentDesc" placeholder="Describe the incident..."></textarea>
                    </div>
                    <div class="mb-4">
                        <div class="section-title">📡 GPS Capture</div>
                        <button type="button" class="btn btn-gold" onclick="getLocation()">Capture Location</button>
                        <p id="gps" class="mt-2"></p>
                    </div>
                    <div class="d-grid mt-4">
                        <button type="submit" class="btn btn-gold btn-lg">Submit Report</button>
                    </div>
                </form>
            </div>
        </div>
    </div>
</div>
<script>
let lat = null, lon = null;
async function loadStates(){
    const states = await (await fetch("/locations/states")).json();
    const sel = document.getElementById("stateSelect");
    states.forEach(s => { let opt = document.createElement("option"); opt.value = s; opt.innerText = s; sel.appendChild(opt); });
}
document.getElementById("stateSelect").addEventListener("change", async function(){
    const lgas = await (await fetch(`/locations/lgas/${this.value}`)).json();
    const sel = document.getElementById("lgaSelect");
    sel.innerHTML = '<option selected disabled>Select LGA</option>';
    lgas.forEach(l => { let opt = document.createElement("option"); opt.value = l; opt.innerText = l; sel.appendChild(opt); });
});
document.getElementById("lgaSelect").addEventListener("change", async function(){
    const wards = await (await fetch(`/locations/wards/${document.getElementById("stateSelect").value}/${this.value}`)).json();
    const sel = document.getElementById("wardSelect");
    sel.innerHTML = '<option selected disabled>Select Ward</option>';
    wards.forEach(w => { 
        let opt = document.createElement("option"); 
        let name = (typeof w === 'string') ? w : (w.name || "Unknown");
        opt.value = name; opt.innerText = name; sel.appendChild(opt); 
    });
});
async function loadParties(){
    const parties = await (await fetch("/parties")).json();
    const container = document.getElementById("partyVotes");
    parties.forEach(p => {
        const div = document.createElement("div"); div.className = "col-md-6 d-flex align-items-center mb-2";
        div.innerHTML = `<img src="${p.logo}" class="party-logo me-2" onerror="this.src='https://via.placeholder.com/50'"><label class="me-2 fw-bold">${p.name}:</label><input type="number" class="form-control" data-party="${p.name}" placeholder="Votes" required>`;
        container.appendChild(div);
    });
}
function getLocation(){
    navigator.geolocation.getCurrentPosition(p => {
        lat = p.coords.latitude; lon = p.coords.longitude;
        document.getElementById("gps").innerText = `Lat: ${lat} | Lon: ${lon}`;
    });
}
document.getElementById("surveyForm").addEventListener("submit", async function(e){
    e.preventDefault();
    const votes = {};
    document.querySelectorAll("#partyVotes input").forEach(i => votes[i.dataset.party] = parseInt(i.value) || 0);
    const payload = {
        state: document.getElementById("stateSelect").value,
        lga: document.getElementById("lgaSelect").value,
        ward: document.getElementById("wardSelect").value,
        pu_name: document.getElementById("puName").value,
        incident_type: document.getElementById("incidentType").value,
        incident_desc: document.getElementById("incidentDesc").value,
        lat: lat, lon: lon,
        total_accredited: parseInt(document.getElementById("totalAccredited").value),
        rejected_votes: parseInt(document.getElementById("rejectedVotes").value),
        votes: votes
    };
    const res = await fetch("/submit", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload)});
    const result = await res.json();
    alert(result.message);
    this.reset();
});
loadStates(); loadParties();
</script>
</body></html>
"""

# Rest of DASHBOARD_HTML remains the same...
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Accord Situation Room - Final Build</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.0.0"></script>
    <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>
    <script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
    <style>
        :root { --bg: #0d0d0d; --panel: #161616; --gold: #ffc107; --border: #333; --text: #e0e0e0; --pdp: #d9534f; --apc: #0b3d91; }
        body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; height: 100vh; margin: 0; overflow: hidden; display: flex; flex-direction: column; }
        
        select option { background-color: #161616 !important; color: white !important; }

        /* HEADER */
        .navbar-custom { border-bottom: 1px solid var(--gold); padding: 0 15px; display: flex; align-items: center; background: var(--bg); height: 75px; gap: 15px; }
        .brand-section { min-width: 180px; }
        .brand-title { font-size: 13px; font-weight: bold; color: white; letter-spacing: 1px; }
        .brand-sub { font-size: 10px; color: var(--gold); font-weight: bold; }

        .nav-kpi-group { display: flex; flex: 1; align-items: center; justify-content: center; gap: 12px; }
        .party-box { display: flex; align-items: center; background: rgba(255,255,255,0.05); border: 1px solid var(--border); padding: 5px 15px; min-width: 140px; height: 62px; gap: 12px; }
        .party-box img { height: 42px; width: 42px; border-radius: 50%; object-fit: contain; background: white; }
        .party-info label { font-size: 9px; color: #888; text-transform: uppercase; margin: 0; font-weight: bold; display: block; }
        .party-info span { font-size: 18px; font-weight: 900; color: white; line-height: 1; }
        
        .box-accord { border-top: 4px solid var(--gold); }
        .box-apc { border-top: 4px solid var(--apc); }
        .box-pdp { border-top: 4px solid var(--pdp); }
        .box-margin { border-top: 4px solid #555; }

        .filter-group { display: flex; align-items: center; gap: 8px; }
        .filter-item { border-left: 1px solid var(--border); padding-left: 10px; }
        .filter-item label { color: var(--gold); font-size: 9px; text-transform: uppercase; display: block; font-weight: bold; }
        .filter-item select { background: transparent; color: #fff; border: none; font-size: 12px; outline: none; cursor: pointer; font-weight: bold; }

        /* GRID SYSTEM */
        .main-container { display: flex; flex: 1; gap: 10px; padding: 10px; overflow: hidden; height: calc(100vh - 75px); }
        .col-side { width: 320px; display: flex; flex-direction: column; gap: 10px; }
        .col-center { flex: 1; display: flex; flex-direction: column; gap: 10px; }

        .widget { background: var(--panel); border: 1px solid var(--border); padding: 12px; display: flex; flex-direction: column; border-radius: 4px; position: relative; }
        .widget-title { color: var(--gold); font-size: 10px; font-weight: bold; border-bottom: 1px solid var(--border); margin-bottom: 8px; padding-bottom: 4px; text-transform: uppercase; display: flex; justify-content: space-between; }
        
        .map-wrapper { flex: 1; position: relative; background: #000; border-radius: 4px; overflow: hidden; }
        #map { position: absolute; top: 0; bottom: 0; left: 0; right: 0; height: 100% !important; }

        /* LIST FEED INTERACTIVITY */
        .pu-list { flex: 1; overflow-y: auto; }
        .pu-card { border-bottom: 1px solid var(--border); padding: 12px 10px; cursor: pointer; transition: background 0.2s; }
        .pu-card:hover { background: rgba(255, 193, 7, 0.05); }
        .pu-card.active { background: rgba(255, 193, 7, 0.15); border-left: 3px solid var(--gold); }
        .pu-card b { color: var(--gold); font-size: 13px; display: block; margin-bottom: 4px; }
        .pu-loc { font-size: 10px; color: #bbb; display: block; margin-bottom: 8px; }
        .pu-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; background: rgba(0,0,0,0.5); padding: 8px; border-radius: 4px; pointer-events: none; }
        .grid-val { text-align: center; }
        .grid-val small { font-size: 8px; color: #888; display: block; text-transform: uppercase; }
        .grid-val span { font-size: 12px; font-weight: bold; }
        .incident-alert { color: #ff4444; font-size: 10px; font-weight: bold; margin-top: 8px; padding: 6px; background: rgba(255,0,0,0.1); border-radius: 3px; }

        .chart-container { height: 160px; position: relative; }
        .big-total-box { border: 2px solid var(--gold); text-align: center; padding: 15px; }
        .big-val { font-size: 48px; font-weight: 900; color: white; line-height: 1; margin: 5px 0; }
        .ts-box { font-size: 9px; color: #888; text-transform: uppercase; margin-top: 4px; letter-spacing: 1px; }

        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-thumb { background: var(--gold); border-radius: 10px; }
    </style>
</head>
<body>

<nav class="navbar-custom">
    <div class="brand-section">
        <div class="brand-title">ELECTION SITUATION ROOM</div>
        <div class="brand-sub">ACCORD CONSOLIDATED VIEW</div>
    </div>
    <div class="nav-kpi-group">
        <div class="party-box box-accord">
            <img src="/static/logos/ACCORD.png" onerror="this.src='https://via.placeholder.com/42?text=A'">
            <div class="party-info"><label>ACCORD</label><span id="nav-ACCORD">0</span></div>
        </div>
        <div class="party-box box-apc">
            <img src="/static/logos/APC.png" onerror="this.src='https://via.placeholder.com/42?text=APC'">
            <div class="party-info"><label>APC</label><span id="nav-APC">0</span></div>
        </div>
        <div class="party-box box-pdp">
            <img src="/static/logos/PDP.png" onerror="this.src='https://via.placeholder.com/42?text=PDP'">
            <div class="party-info"><label>PDP</label><span id="nav-PDP">0</span></div>
        </div>
        <div class="party-box box-margin">
            <div class="party-info" style="text-align:center; width:100%"><label>LEAD MARGIN</label><span id="nav-Margin" style="color:var(--gold)">0</span></div>
        </div>
    </div>
    <div class="filter-group">
        <div class="filter-item"><label>State</label><select id="stateFilter"><option value="">All States</option></select></div>
        <div class="filter-item"><label>LGA</label><select id="lgaFilter"><option value="">All LGAs</option></select></div>
        <div class="filter-item"><label>Ward</label><select id="wardFilter"><option value="">All Wards</option></select></div>
    </div>
</nav>

<div class="main-container">
    <div class="col-side">
        <div class="widget" style="padding: 8px;">
            <input type="text" id="puSearch" placeholder="🔍 Search Polling Units..." onkeyup="refreshData()" 
                   style="background:#222; border:none; color:white; padding:10px; font-size:12px; width:100%; border-radius:4px;">
        </div>
        <div class="widget pu-list">
            <div class="widget-title">
                Live Result Feed
                <span id="resetFeed" onclick="refreshData()" style="color:var(--gold); cursor:pointer; font-size:9px;">RESET VIEW</span>
            </div>
            <div id="puContainer"></div>
        </div>
    </div>

    <div class="col-center">
        <div class="widget map-wrapper">
            <div id="map"></div>
        </div>
        <div class="widget" style="height: 85px; text-align:center; justify-content:center;">
            <div style="font-size:11px; color:var(--gold); font-weight:bold; text-transform:uppercase;">Reporting Coverage</div>
            <div id="unitCount" style="font-size: 36px; font-weight: 900; color: white;">0 Units Reporting</div>
        </div>
    </div>

    <div class="col-side">
        <div class="widget">
            <div class="widget-title" id="chartLabel">Vote Distribution %</div>
            <div class="chart-container">
                <canvas id="pieChart"></canvas>
            </div>
        </div>
        
        <div class="widget">
            <div class="widget-title">Candidate Comparison</div>
            <div style="height: 100px;"><canvas id="barChart"></canvas></div>
        </div>

        <div class="widget big-total-box">
            <div style="color:var(--gold); font-size:11px; font-weight:bold; text-transform:uppercase;">Total Accord Aggregate</div>
            <div id="totalAccordBig" class="big-val">0</div>
            <div class="ts-box" id="lastUpdateTS">Last Updated: --:--:--</div>
        </div>
    </div>
</div>

<script>
Chart.register(ChartDataLabels);
let map = L.map('map', {zoomControl: false, attributionControl: false}).setView([9.082, 8.675], 6);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png').addTo(map);
let markers = [], charts = {}, globalData = [];

async function initDashboard() {
    try {
        const states = await (await fetch("/locations/states")).json();
        const sS = document.getElementById("stateFilter");
        states.forEach(s => sS.add(new Option(s, s)));
    } catch(e) { console.error(e); }
    refreshData();
}

function focusOnUnit(puName) {
    const unit = globalData.find(d => d.pu_name === puName);
    if (!unit) return;
    document.querySelectorAll('.pu-card').forEach(c => c.classList.remove('active'));
    event.currentTarget.classList.add('active');
    if (unit.latitude && unit.longitude) {
        map.flyTo([unit.latitude, unit.longitude], 14, { duration: 1.5 });
    }
    document.getElementById('chartLabel').innerText = "Unit View: " + puName;
    updateCharts(unit.votes_party_ACCORD || 0, unit.votes_party_APC || 0, unit.votes_party_PDP || 0);
}

document.getElementById("stateFilter").onchange = async (e) => {
    const lS = document.getElementById("lgaFilter");
    lS.innerHTML = '<option value="">All LGAs</option>';
    if(e.target.value) {
        const lgas = await (await fetch("/locations/lgas/"+e.target.value)).json();
        lgas.forEach(l => lS.add(new Option(l, l)));
    }
    refreshData();
};

document.getElementById("lgaFilter").onchange = async (e) => {
    const state = document.getElementById("stateFilter").value;
    const wS = document.getElementById("wardFilter");
    wS.innerHTML = '<option value="">All Wards</option>';
    if(e.target.value) {
        const wards = await (await fetch(`/locations/wards/${state}/${e.target.value}`)).json();
        wards.forEach(w => {
            let name = (typeof w === 'string') ? w : (w.name || "Unknown");
            wS.add(new Option(name, name));
        });
    }
    refreshData();
};

document.getElementById("wardFilter").onchange = () => refreshData();

async function refreshData() {
    try {
        const res = await fetch("/submissions");
        let data = await res.json();
        globalData = data; 
        
        const sF = document.getElementById("stateFilter").value;
        const lF = document.getElementById("lgaFilter").value;
        const wF = document.getElementById("wardFilter").value;
        const sT = document.getElementById("puSearch").value.toLowerCase();

        if(sF) data = data.filter(d => d.state === sF);
        if(lF) data = data.filter(d => d.lga === lF);
        if(wF) data = data.filter(d => d.ward === wF);
        if(sT) data = data.filter(d => d.pu_name.toLowerCase().includes(sT));

        document.getElementById('chartLabel').innerText = "Vote Distribution %";
        updateUI(data);
    } catch(e) { console.error(e); }
}

function updateUI(data) {
    let tA = 0, tAPC = 0, tPDP = 0, listHtml = "";
    markers.forEach(m => map.removeLayer(m));
    markers = [];

    data.forEach(d => {
        const vA = d.votes_party_ACCORD || 0;
        const vAPC = d.votes_party_APC || 0;
        const vPDP = d.votes_party_PDP || 0;
        tA += vA; tAPC += vAPC; tPDP += vPDP;

        listHtml += `
            <div class="pu-card" onclick="focusOnUnit('${d.pu_name}')">
                <b>${d.pu_name}</b>
                <span class="pu-loc">📍 ${d.ward}, ${d.lga}</span>
                <div class="pu-grid">
                    <div class="grid-val"><small>ACC</small><span style="color:var(--gold)">${vA.toLocaleString()}</span></div>
                    <div class="grid-val"><small>APC</small><span>${vAPC.toLocaleString()}</span></div>
                    <div class="grid-val"><small>PDP</small><span>${vPDP.toLocaleString()}</span></div>
                </div>
                ${d.incident_type ? `<div class="incident-alert">🚨 ${d.incident_type}</div>` : ""}
            </div>`;

        if(d.latitude && d.longitude) {
            markers.push(L.circleMarker([d.latitude, d.longitude], {
                radius: 7, color: '#ffc107', fillColor: '#ffc107', fillOpacity: 0.8, weight: 2
            }).addTo(map));
        }
    });

    document.getElementById("puContainer").innerHTML = listHtml;
    document.getElementById("nav-ACCORD").innerText = tA.toLocaleString();
    document.getElementById("nav-APC").innerText = tAPC.toLocaleString();
    document.getElementById("nav-PDP").innerText = tPDP.toLocaleString();
    document.getElementById("nav-Margin").innerText = (tA - Math.max(tAPC, tPDP)).toLocaleString();
    document.getElementById("unitCount").innerText = `${data.length} Units Reporting`;
    document.getElementById("totalAccordBig").innerText = tA.toLocaleString();
    document.getElementById("lastUpdateTS").innerText = "Last Updated: " + new Date().toLocaleTimeString();

    if (markers.length > 0) {
        const group = new L.featureGroup(markers);
        map.fitBounds(group.getBounds(), {padding:[40,40]});
    }
    updateCharts(tA, tAPC, tPDP);
}

function updateCharts(a, apc, pdp) {
    const total = a + apc + pdp;
    const labels = ['ACCORD', 'APC', 'PDP'];
    const colors = ['#ffc107', '#0b3d91', '#d9534f'];
    const values = [a, apc, pdp];

    if(charts.bar) charts.bar.destroy();
    charts.bar = new Chart(document.getElementById('barChart'), {
        type: 'bar',
        data: { labels: labels, datasets: [{ data: values, backgroundColor: colors }] },
        options: {
            maintainAspectRatio: false,
            plugins: { datalabels: { display: false }, legend: { display: false } },
            scales: { 
                y: { grid: { color: '#222' }, ticks: { color: '#555', font: { size: 8 } } }, 
                x: { ticks: { color: '#888', font: { size: 9 } } } 
            }
        }
    });

    if(charts.pie) charts.pie.destroy();
    charts.pie = new Chart(document.getElementById('pieChart'), {
        type: 'doughnut',
        data: { labels: labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 0 }] },
        plugins: [{
            id: 'centerText',
            beforeDraw: (chart) => {
                const { ctx, chartArea: { top, bottom, left, right } } = chart;
                ctx.save();
                const centerX = (left + right) / 2;
                const centerY = (top + bottom) / 2;
                ctx.textAlign = "center"; ctx.textBaseline = "middle";
                ctx.font = "bold 10px Segoe UI"; ctx.fillStyle = "#888";
                ctx.fillText("TOTAL", centerX, centerY - 10);
                ctx.font = "bold 16px Segoe UI"; ctx.fillStyle = "white";
                ctx.fillText(total.toLocaleString(), centerX, centerY + 8);
                ctx.restore();
            }
        }],
        options: {
            cutout: '78%',
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'right', labels: { color: '#888', font: { size: 9 } } },
                datalabels: {
                    color: '#fff',
                    font: { weight: 'bold', size: 10 },
                    formatter: (val) => total > 0 ? (val/total*100).toFixed(1) + '%' : ''
                }
            }
        }
    });
}

initDashboard();
setInterval(refreshData, 20000);
</script>
</body>
</html>
"""