import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json
import logging
import io
import csv
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# --- CONFIGURATION ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Render-safe Pathing
LOGO_PATH = os.path.join(os.getcwd(), "static", "logos")
if os.path.exists(LOGO_PATH):
    app.mount("/logos", StaticFiles(directory=LOGO_PATH), name="logos")

STATIC_PATH = os.path.join(os.getcwd(), "static")
if os.path.exists(STATIC_PATH):
    app.mount("/static", StaticFiles(directory=STATIC_PATH), name="static")

# --- DATABASE CONNECTION ---
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://election_v3_db_user:KHjYceeGY0OL5w1RMhVFM18AyRipv9Tl@dpg-d6gnomfkijhs73f1cfe0-a.oregon-postgres.render.com/election_v3_db")

def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# --- DATABASE INITIALIZATION ---
def init_db():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS field_submissions (
                id SERIAL PRIMARY KEY,
                officer_id TEXT,
                state TEXT, 
                lg TEXT, 
                ward TEXT, 
                ward_code TEXT, 
                pu_code TEXT, 
                location TEXT,
                reg_voters INTEGER, 
                total_accredited INTEGER, 
                valid_votes INTEGER, 
                rejected_votes INTEGER, 
                total_cast INTEGER,
                lat REAL, 
                lon REAL, 
                timestamp TEXT, 
                votes_json TEXT,
                UNIQUE(pu_code)
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Table created successfully")
    except Exception as e:
        print(f"❌ DB INIT ERROR: {e}")

init_db()

# --- API ENDPOINTS ---

@app.get("/api/states")
def get_states():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT state FROM polling_units ORDER BY state")
            rows = cur.fetchall()
            return [r["state"] for r in rows]

@app.get("/api/lgas/{state}")
def get_lgas(state: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT lg FROM polling_units WHERE state = %s ORDER BY lg", (state,))
            rows = cur.fetchall()
            return [r["lg"] for r in rows]

@app.get("/api/wards/{state}/{lg}")
def get_wards(state: str, lg: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT ward, ward_code FROM polling_units WHERE state = %s AND lg = %s ORDER BY ward", (state, lg))
            rows = cur.fetchall()
            return [{"name": r["ward"], "code": r["ward_code"]} for r in rows]

@app.get("/api/pus/{state}/{lg}/{ward}")
def get_pus(state: str, lg: str, ward: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT location, pu_code FROM polling_units WHERE state = %s AND lg = %s AND ward = %s", (state, lg, ward))
            rows = cur.fetchall()
            return [{"location": r["location"], "pu_code": r["pu_code"]} for r in rows]

@app.post("/submit")
async def submit(data: dict):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO field_submissions (
                    officer_id, state, lg, ward, ward_code, pu_code, location,
                    reg_voters, total_accredited, valid_votes, rejected_votes, total_cast,
                    lat, lon, timestamp, votes_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (
                    data['officer_id'], data['state'], data['lg'], data['ward'], data['ward_code'],
                    data['pu_code'], data['location'], data['reg_voters'], data['total_accredited'],
                    data['valid_votes'], data['rejected_votes'], data['total_cast'],
                    data['lat'], data['lon'], datetime.now().isoformat(), json.dumps(data['votes'])
                ))
                conn.commit()
        return {"status": "success", "message": "Result Uploaded Successfully"}
    except psycopg2.IntegrityError:
        return {"status": "error", "message": "REJECTED: A submission for this Polling Unit already exists."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/ai_interpret")
async def ai_interpret(data: dict):
    acc = data.get('ACCORD', 0); apc = data.get('APC', 0); pdp = data.get('PDP', 0); adc = data.get('ADC', 0)
    total = acc + apc + pdp + adc
    if total == 0: return {"analysis": "SYSTEM STATUS: Awaiting live data stream."}
    share = (acc / total) * 100
    competitors = {"APC": apc, "PDP": pdp, "ADC": adc}
    top_rival = max(competitors, key=competitors.get)
    margin = acc - competitors[top_rival]
    performance = "Leading" if margin > 0 else "Trailing"
    analysis = (f"STATISTICAL AUDIT: Accord maintains a {share:.1f}% vote share. "
                f"Currently {performance} against {top_rival} by {abs(margin):,} votes.")
    return {"analysis": analysis}

@app.get("/api/dashboard_filters")
def get_dash_filters():
    """Helper for the header dropdowns"""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT state, lg, ward FROM polling_units ORDER BY state, lg, ward")
            return cur.fetchall()

@app.get("/export/csv")
async def export_csv():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM field_submissions ORDER BY timestamp DESC")
            rows = cur.fetchall()
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # 18 Parties List
            parties = ["ACCORD", "AA", "AAC", "ADC", "ADP", "APC", "APGA", "APM", "APP", "BP", "LP", "NNPP", "NRM", "PDP", "PRP", "SDP", "YPP", "ZLP"]
            
            # Header
            header = ["Timestamp", "Officer ID", "State", "LGA", "Ward", "PU Code", "Location", "Accredited", "Total Cast"] + parties
            writer.writerow(header)
            
            for r in rows:
                v = json.loads(r['votes_json']) if isinstance(r['votes_json'], str) else r['votes_json']
                # Create row with metadata
                row_data = [r['timestamp'], r['officer_id'], r['state'], r['lg'], r['ward'], r['pu_code'], r['location'], r['total_accredited'], r['total_cast']]
                # Add votes for EVERY party (default to 0 if missing)
                for p in parties:
                    row_data.append(v.get(p, 0))
                writer.writerow(row_data)
            
            output.seek(0)
            return StreamingResponse(output, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=election_audit_full.csv"})

@app.get("/submissions")
async def get_dashboard_data():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM field_submissions ORDER BY timestamp DESC")
            rows = cur.fetchall()
            data = []
            for r in rows:
                v = json.loads(r['votes_json']) if isinstance(r['votes_json'], str) else r['votes_json']
                data.append({
                    "pu_name": r['location'], "state": r['state'], "lga": r['lg'], "ward": r['ward'],
                    "latitude": r['lat'], "longitude": r['lon'],
                    "votes_party_ACCORD": v.get("ACCORD", 0), "votes_party_APC": v.get("APC", 0),
                    "votes_party_PDP": v.get("PDP", 0), "votes_party_ADC": v.get("ADC", 0)
                })
            return data
@app.get("/", response_class=HTMLResponse)
async def index():
    parties = ["ACCORD", "AA", "AAC", "ADC", "ADP", "APC", "APGA", "APM", "APP", "BP", "LP", "NNPP", "NRM", "PDP", "PRP", "SDP", "YPP", "ZLP"]
    party_cards = "".join([f'''
        <div class="col-4 col-md-2 mb-2">
            <div class="p-2 border rounded text-center bg-white shadow-sm">
                <img src="/logos/{p}.png" onerror="this.src='https://via.placeholder.com/30?text={p}'" style="height:30px">
                <small class="d-block fw-bold">{p}</small>
                <input type="number" class="form-control form-control-sm party-v text-center" data-p="{p}" value="0" oninput="calculateTotals()">
            </div>
        </div>''' for p in parties])

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>IMOLE YOUTH ACCORD MOBILIZATION</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {{ background: linear-gradient(rgba(0,0,0,0.6), rgba(0,0,0,0.6)), url('/static/bg.png'); background-size: cover; background-position: center; background-attachment: fixed; min-height: 100vh; margin: 0; }}
        .navbar {{ background: rgba(0, 135, 81, 0.9) !important; backdrop-filter: blur(10px); color: white; border-bottom: 4px solid #ffc107; }}
        .card {{ background: rgba(255, 255, 255, 0.95) !important; border-radius: 12px; border: none; box-shadow: 0 10px 30px rgba(0,0,0,0.3) !important; margin-bottom: 20px; color: #222; }}
        .section-label {{ font-size: 0.75rem; font-weight: bold; color: #008751; text-transform: uppercase; border-left: 3px solid #ffc107; padding-left: 10px; margin-bottom: 15px; display: block; }}
        input[readonly] {{ background-color: #e9ecef !important; font-weight: bold; }}
        #loginArea {{ margin-top: 100px; }}
    </style>
</head>
<body>
    <nav class="navbar py-2 mb-4 text-center"><h5>IMOLE YOUTH ACCORD MOBILIZATION OFFICIAL FIELD COLLATION</h5></nav>
    <div class="container pb-5" style="max-width: 850px;">
        <div id="loginArea" class="card p-5 text-center mx-auto" style="max-width: 400px;">
            <h6>Enter Officer ID</h6>
            <input type="text" id="oid" class="form-control mb-3 text-center">
            <button class="btn btn-success w-100" onclick="start()">Validate Access</button>
        </div>

        <div id="formArea" class="d-none">
            <div class="card p-4">
                <span class="section-label">1. Polling Unit Selection</span>
                <div class="row g-2">
                    <div class="col-4"><select id="s" class="form-select" onchange="loadLGAs()"><option value="">STATE</option></select></div>
                    <div class="col-4"><select id="l" class="form-select" onchange="loadWards()"><option value="">LGA</option></select></div>
                    <div class="col-4"><select id="w" class="form-select" onchange="loadPUs()"><option value="">WARD</option></select></div>
                    <div class="col-12 mt-2"><select id="p" class="form-select" onchange="fillPU()"><option value="">SELECT POLLING UNIT</option></select></div>
                </div>
                <div class="row mt-3 g-2">
                    <div class="col-4"><small>Ward Code</small><input type="text" id="wc" class="form-control" readonly></div>
                    <div class="col-4"><small>PU Code</small><input type="text" id="pc" class="form-control" readonly></div>
                    <div class="col-4"><small>Location</small><input type="text" id="loc" class="form-control" readonly></div>
                </div>
            </div>

            <div class="card p-4">
                <span class="section-label">2. Official 18-Party Scorecard</span>
                <div class="row g-2">{party_cards}</div>
            </div>

            <div class="card p-4">
                <span class="section-label">3. Accreditation & Audit</span>
                <div class="row g-3">
                    <div class="col-4"><label class="small">Registered</label><input type="number" id="rv" class="form-control" value="0"></div>
                    <div class="col-4"><label class="small">Accredited</label><input type="number" id="ta" class="form-control" oninput="calculateTotals()"></div>
                    <div class="col-4"><label class="small">Rejected</label><input type="number" id="rj" class="form-control" value="0" oninput="calculateTotals()"></div>
                    <div class="col-6"><label class="small text-success">Valid</label><input type="number" id="vv" class="form-control" readonly></div>
                    <div class="col-6"><label class="small text-primary">Total Cast</label><input type="number" id="tc" class="form-control" readonly></div>
                </div>
                <div id="auditStatus" class="mt-3 p-2 rounded text-center d-none small fw-bold"></div>
            </div>
            <button class="btn btn-outline-dark w-100 mb-2" onclick="getGPS()">Fix GPS Location</button>
            <button class="btn btn-success btn-lg w-100 py-3 fw-bold" onclick="reviewSubmission()">UPLOAD PU RESULT</button>
        </div>
    </div>

    <script>
        let lat, lon, officerId, puData = [], wardData = [];
        function start() {{
            officerId = document.getElementById('oid').value;
            if(!officerId) return;
            document.getElementById('loginArea').classList.add('d-none');
            document.getElementById('formArea').classList.remove('d-none');
            fetch('/api/states').then(r=>r.json()).then(data=>{{
                const s = document.getElementById('s');
                data.forEach(item => s.add(new Option(item.toUpperCase(), item)));
            }});
        }}
        function loadLGAs() {{
            fetch('/api/lgas/'+encodeURIComponent(document.getElementById('s').value)).then(r=>r.json()).then(data=>{{
                const l = document.getElementById('l'); l.innerHTML = '<option value="">LGA</option>';
                data.forEach(item => l.add(new Option(item.toUpperCase(), item)));
            }});
        }}
        function loadWards() {{
            fetch(`/api/wards/${{encodeURIComponent(document.getElementById('s').value)}}/${{encodeURIComponent(document.getElementById('l').value)}}`).then(r=>r.json()).then(data=>{{
                wardData = data;
                const w = document.getElementById('w'); w.innerHTML = '<option value="">WARD</option>';
                data.forEach(item => w.add(new Option(item.name.toUpperCase(), item.name)));
            }});
        }}
        function loadPUs() {{
            const w = document.getElementById('w').value;
            const wardObj = wardData.find(x => x.name === w);
            document.getElementById('wc').value = wardObj ? wardObj.code : '';
            fetch(`/api/pus/${{encodeURIComponent(document.getElementById('s').value)}}/${{encodeURIComponent(document.getElementById('l').value)}}/${{encodeURIComponent(w)}}`).then(r=>r.json()).then(data=>{{
                puData = data;
                const p = document.getElementById('p'); p.innerHTML = '<option value="">SELECT PU</option>';
                data.forEach((item, idx) => p.add(new Option(item.location.toUpperCase(), idx)));
            }});
        }}
        function fillPU() {{
            const sel = puData[document.getElementById('p').value];
            document.getElementById('pc').value = sel.pu_code;
            document.getElementById('loc').value = sel.location.toUpperCase();
        }}
        function calculateTotals() {{
            let valid = 0;
            document.querySelectorAll('.party-v').forEach(i => valid += parseInt(i.value || 0));
            const rej = parseInt(document.getElementById('rj').value || 0);
            const acc = parseInt(document.getElementById('ta').value || 0);
            const cast = valid + rej;
            document.getElementById('vv').value = valid;
            document.getElementById('tc').value = cast;
            const msg = document.getElementById('auditStatus');
            if (acc > 0 && cast > acc) {{
                msg.innerHTML = "⚠️ ERROR: Over-voting!";
                msg.className = "mt-3 p-2 bg-danger text-white rounded text-center small fw-bold d-block";
            }} else if (cast > 0 && cast === acc) {{
                msg.innerHTML = "✅ AUDIT BALANCED";
                msg.className = "mt-3 p-2 bg-success text-white rounded text-center small fw-bold d-block";
            }} else {{ msg.className = "d-none"; }}
        }}
        function getGPS() {{ navigator.geolocation.getCurrentPosition(pos => {{ lat = pos.coords.latitude; lon = pos.coords.longitude; alert("GPS Fixed!"); }}); }}
        async function reviewSubmission() {{
            if(!lat) return alert("Please Fix GPS first");
            const v = {{}};
            document.querySelectorAll('.party-v').forEach(i => v[i.dataset.p] = parseInt(i.value || 0));
            const payload = {{
                officer_id: officerId, state: document.getElementById('s').value, lg: document.getElementById('l').value,
                ward: document.getElementById('w').value, ward_code: document.getElementById('wc').value,
                pu_code: document.getElementById('pc').value, location: document.getElementById('loc').value,
                reg_voters: parseInt(document.getElementById('rv').value || 0), total_accredited: parseInt(document.getElementById('ta').value || 0),
                valid_votes: parseInt(document.getElementById('vv').value || 0), rejected_votes: parseInt(document.getElementById('rj').value || 0),
                total_cast: parseInt(document.getElementById('tc').value || 0), lat, lon, votes: v
            }};
            const res = await fetch('/submit', {{ method: 'POST', headers: {{'Content-Type':'application/json'}}, body: JSON.stringify(payload)}});
            const out = await res.json();
            alert(out.message);
            if(out.status === 'success') location.reload();
        }}
    </script>
</body>
</html>
"""

# --- DASHBOARD PAGE ---

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    return DASHBOARD_HTML

# ... [The DASHBOARD_HTML string follows exactly from your file, with the added Export button in the navbar as shown in previous sessions] ...
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Accord Situation Room - LIVE</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css">
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        :root { --gold: #ffc107; --green: #008751; --dark: #0a0a0a; --panel: #141414; }
        body { background-color: var(--dark); color: #fff; font-family: 'Segoe UI', sans-serif; overflow: hidden; height: 100vh; }
        
        /* Navbar KPI Styling */
        .navbar-custom { background: #000; border-bottom: 2px solid var(--gold); padding: 10px 20px; display: flex; align-items: center; justify-content: space-between; }
        .brand-section { line-height: 1.2; }
        .brand-title { color: var(--gold); font-weight: 900; font-size: 1.2rem; letter-spacing: 1px; }
        .brand-sub { font-size: 0.7rem; color: #888; text-transform: uppercase; }
        
        .nav-kpi-group { display: flex; gap: 15px; }
        .party-box { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 5px 15px; display: flex; align-items: center; gap: 10px; min-width: 140px; }
        .party-box img { height: 35px; width: 35px; object-fit: contain; }
        .party-info label { display: block; font-size: 0.65rem; color: #aaa; margin: 0; }
        .party-info span { font-size: 1.1rem; font-weight: bold; color: #fff; }
        
        .box-accord { border-top: 3px solid var(--gold); }
        .box-apc { border-top: 3px solid #0b3d91; }
        .box-pdp { border-top: 3px solid #d9534f; }
        .box-adc { border-top: 3px solid #138808; }

        .export-btn { 
            background: transparent; border: 1px solid var(--gold); color: var(--gold); 
            font-size: 11px; font-weight: bold; padding: 6px 12px; border-radius: 4px; 
            text-decoration: none; transition: 0.3s;
        }
        .export-btn:hover { background: var(--gold); color: #000; }

        <div class="chart-container"><canvas id="barChart"></canvas></div>
    
    <div class="chart-container"><canvas id="pieChart"></canvas></div>

    <div class="margin-box">
        <small class="text-secondary">VOTE MARGIN</small>
        <div id="marginVal" class="margin-val">0</div>
        <small id="marginLead" class="text-success" style="font-size:10px;">AWAITING DATA</small>
    </div>

    <div class="margin-box" style="border-top: 3px solid var(--gold);">
        <small class="text-secondary">ACCORD TOTAL</small>
        <div id="accordTotal" class="margin-val">0</div>
    </div>
</div>

<div class="filter-bar">
    <select id="fState" onchange="filterLGA()"><option value="">SELECT STATE</option></select>
    <select id="fLGA" onchange="filterWard()"><option value="">SELECT LGA</option></select>
    <select id="fWard" onchange="applyFilters()"><option value="">SELECT WARD</option></select>
    <button class="btn btn-sm btn-outline-secondary" onclick="resetDashboard()">RESET</button>
</div>

        /* Layout */
        .main-content { display: grid; grid-template-columns: 350px 1fr 320px; height: calc(100vh - 80px); gap: 10px; padding: 10px; }
        .side-panel { background: var(--panel); border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; border: 1px solid #222; }
        .panel-header { background: #1c1c1c; padding: 10px 15px; font-size: 0.8rem; font-weight: bold; color: var(--gold); border-bottom: 1px solid #333; display: flex; justify-content: space-between; }
        
        /* Map & Feed */
        #map { height: 100%; border-radius: 12px; background: #111; }
        .feed-container { flex: 1; overflow-y: auto; padding: 10px; }
        .pu-card { background: #1e1e1e; border-radius: 8px; padding: 12px; margin-bottom: 10px; border-left: 4px solid var(--gold); cursor: pointer; transition: 0.2s; }
        .pu-card:hover { background: #252525; }
        .pu-card h6 { font-size: 0.85rem; margin-bottom: 4px; color: var(--gold); }
        .pu-card small { font-size: 0.7rem; color: #888; display: block; }
        
        .score-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 5px; margin-top: 8px; border-top: 1px solid #333; pt: 8px; }
        .grid-val { text-align: center; }
        .grid-val small { font-size: 0.6rem; color: #666; }
        .grid-val span { display: block; font-size: 0.8rem; font-weight: bold; }

        .ai-box { background: #000; color: #0f0; font-family: monospace; padding: 15px; font-size: 0.8rem; border: 1px solid #030; height: 120px; overflow-y: auto; }
    </style>
</head>
<body>

<nav class="navbar-custom">
    <div class="brand-section">
        <div class="brand-title">ACCORD ELECTION SITUATION ROOM</div>
        <div class="brand-sub">National Command & Intelligence Center</div>
        <a href="/export/csv" class="export-btn mt-2 d-inline-block">
            <i class="bi bi-download"></i> EXPORT DATABASE (CSV)
        </a>
    </div>

    <div class="nav-kpi-group">
        <div class="party-box box-accord">
            <img src="/logos/ACCORD.png">
            <div class="party-info"><label>ACCORD</label><span id="nav-ACCORD">0</span></div>
        </div>
        <div class="party-box box-apc">
            <img src="/logos/APC.png">
            <div class="party-info"><label>APC</label><span id="nav-APC">0</span></div>
        </div>
        <div class="party-box box-pdp">
            <img src="/logos/PDP.png">
            <div class="party-info"><label>PDP</label><span id="nav-PDP">0</span></div>
        </div>
        <div class="party-box box-adc">
            <img src="/logos/ADC.png">
            <div class="party-info"><label>ADC</label><span id="nav-ADC">0</span></div>
        </div>
    </div>

    <div class="filter-group d-flex gap-2">
        <select id="stateFilter" class="form-select form-select-sm bg-dark text-white border-secondary" style="width:120px;" onchange="updateLGAs()">
            <option value="">All States</option>
        </select>
        <button class="btn btn-sm btn-outline-secondary" onclick="resetFilters()"><i class="bi bi-arrow-clockwise"></i></button>
    </div>
</nav>

<div class="main-content">
    <div class="side-panel">
        <div class="panel-header"><span>LIVE PU FEED</span> <span id="pu-count" class="badge bg-warning text-dark">0</span></div>
        <div class="px-2 pt-2"><input type="text" id="puSearch" class="form-control form-control-sm bg-dark text-white border-secondary" placeholder="Search Polling Unit..." oninput="renderFeed()"></div>
        <div class="feed-container" id="feedList"></div>
    </div>

    <div id="map"></div>

    <div class="side-panel">
        <div class="panel-header">AI ANALYTICS INTERPRETATION</div>
        <div class="ai-box" id="ai_box">Awaiting data stream for statistical analysis...</div>
        
        <div class="panel-header mt-auto">SYSTEM LOGS</div>
        <div class="p-3" style="font-size:0.7rem; color:#666;">
            Database: PostgreSQL<br>
            Status: Connected<br>
            Encryption: SSL Enabled<br>
            Last Sync: <span id="sync-time">Just now</span>
        </div>
        <button class="btn btn-warning btn-sm m-3 fw-bold" onclick="runAI()">REFRESH AI AUDIT</button>
    </div>
</div>

<script>
    let map, globalData = [], markers = [];
    
    function initMap() {
        map = L.map('map', { zoomControl: false }).setView([9.082, 8.675], 6);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png').addTo(map);
    }

    async function refreshData() {
        try {
            const res = await fetch('/submissions');
            globalData = await res.json();
            
            // Calculate Global Totals
            let totals = { ACCORD: 0, APC: 0, PDP: 0, ADC: 0 };
            globalData.forEach(d => {
                totals.ACCORD += d.votes_party_ACCORD;
                totals.APC += d.votes_party_APC;
                totals.PDP += d.votes_party_PDP;
                totals.ADC += d.votes_party_ADC;
            });

            document.getElementById('nav-ACCORD').innerText = totals.ACCORD.toLocaleString();
            document.getElementById('nav-APC').innerText = totals.APC.toLocaleString();
            document.getElementById('nav-PDP').innerText = totals.PDP.toLocaleString();
            document.getElementById('nav-ADC').innerText = totals.ADC.toLocaleString();
            document.getElementById('pu-count').innerText = globalData.length;
            document.getElementById('sync-time').innerText = new Date().toLocaleTimeString();

            updateMap();
            renderFeed();
        } catch(e) { console.error("Data fetch error", e); }
    }

    function updateMap() {
        markers.forEach(m => map.removeLayer(m));
        markers = [];
        globalData.forEach(d => {
            if(d.latitude && d.longitude) {
                const m = L.circleMarker([d.latitude, d.longitude], {
                    radius: 6, color: '#ffc107', fillOpacity: 0.8
                }).addTo(map).bindPopup(`<b>${d.pu_name}</b><br>ACCORD: ${d.votes_party_ACCORD}`);
                markers.push(m);
            }
        });
    }

    function renderFeed() {
        const list = document.getElementById('feedList');
        const search = document.getElementById('puSearch').value.toLowerCase();
        list.innerHTML = "";
        
        globalData.filter(d => d.pu_name.toLowerCase().includes(search)).forEach(d => {
            const card = document.createElement('div');
            card.className = 'pu-card';
            card.innerHTML = `
                <h6>${d.pu_name}</h6>
                <small>${d.lga} | ${d.ward}</small>
                <div class="score-grid">
                    <div class="grid-val"><small>ACC</small><span class="text-warning">${d.votes_party_ACCORD}</span></div>
                    <div class="grid-val"><small>APC</small><span>${d.votes_party_APC}</span></div>
                    <div class="grid-val"><small>PDP</small><span>${d.votes_party_PDP}</span></div>
                    <div class="grid-val"><small>ADC</small><span>${d.votes_party_ADC}</span></div>
                </div>
            `;
            card.onclick = () => { if(d.latitude) map.setView([d.latitude, d.longitude], 13); };
            list.appendChild(card);
        });
    }

    async function runAI() {
        let totals = { ACCORD: 0, APC: 0, PDP: 0, ADC: 0 };
        globalData.forEach(d => {
            totals.ACCORD += d.votes_party_ACCORD;
            totals.APC += d.votes_party_APC;
            totals.PDP += d.votes_party_PDP;
            totals.ADC += d.votes_party_ADC;
        });
        const res = await fetch("/api/ai_interpret", {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(totals)
        });
        const out = await res.json();
        document.getElementById('ai_box').innerText = out.analysis;
    }

    initMap();
    refreshData();
    setInterval(refreshData, 15000);
</script>
</body>
</html>
"""
