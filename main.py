import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json
import logging
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# --- CONFIGURATION ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Render-safe Pathing
LOGO_PATH = os.path.join(os.getcwd(), "static", "logos")
if os.path.exists(LOGO_PATH):
    app.mount("/logos", StaticFiles(directory=LOGO_PATH), name="logos")

# --- DATABASE CONNECTION ---
# This grabs the URL from Render's Environment Variables
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://election_v3_db_user:KHjYceeGY0OL5w1RMhVFM18AyRipv9Tl@dpg-d6gnomfkijhs73f1cfe0-a.oregon-postgres.render.com/election_v3_db")

def get_db():
    # Use sslmode=require if connecting from local, Render handles it internally usually
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# --- DATABASE INITIALIZATION (CAUTION) ---
def init_db():
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # We use SERIAL instead of AUTOINCREMENT for Postgres
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

# IMPORTANT: Ensure this is called
init_db()

# init_db() # <--- COMMENTED OUT to protect your migrated 25MB data!

# --- UPDATED API ENDPOINTS FOR POSTGRES ---

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

# --- NEW: PROFESSIONAL STATISTICAL AI INTERPRETATION ---
@app.post("/api/ai_interpret")
async def ai_interpret(data: dict):
    acc = data.get('ACCORD', 0)
    apc = data.get('APC', 0)
    pdp = data.get('PDP', 0)
    adc = data.get('ADC', 0)
    
    total = acc + apc + pdp + adc
    if total == 0:
        return {"analysis": "SYSTEM STATUS: Awaiting live data stream for comparative trend analysis."}
    
    # Statistical Calcs
    share = (acc / total) * 100
    competitors = {"APC": apc, "PDP": pdp, "ADC": adc}
    top_rival = max(competitors, key=competitors.get)
    rival_val = competitors[top_rival]
    margin = acc - rival_val
    
    # Pro Interpretation logic
    trend = "Dominant" if share > 50 else "Competitive"
    performance = "Leading" if margin > 0 else "Trailing"
    
    analysis = (
        f"STATISTICAL AUDIT: Accord currently maintains a {share:.1f}% vote share across reported units. "
        f"In direct comparison with {top_rival} (Primary Rival), the party is {performance} by a margin of {abs(margin):,} votes. "
        f"Performance metrics indicate a '{trend}' trajectory. Strategy: Consolidate presence in high-density wards "
        f"to neutralize {top_rival}'s gains in peripheral LGAs."
    )
    return {"analysis": analysis}

# --- FRONTEND (RETAINED EXACTLY) ---
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
    <title>INEC Field Portal</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {{ background: #f4f7f6; }}
        .navbar {{ background: #008751; color: white; border-bottom: 4px solid #ffc107; }}
        .card {{ border-radius: 12px; border: none; box-shadow: 0 4px 10px rgba(0,0,0,0.05); margin-bottom: 20px; }}
        .section-label {{ font-size: 0.75rem; font-weight: bold; color: #008751; text-transform: uppercase; border-left: 3px solid #ffc107; padding-left: 10px; margin-bottom: 15px; display: block; }}
        input[readonly] {{ background-color: #e9ecef !important; font-weight: bold; }}
        .modal-header {{ background: #008751; color: white; }}
    </style>
</head>
<body>
    <nav class="navbar py-2 mb-4 text-center"><h5>ACCORD PARTY OFFICIAL FIELD COLLATION</h5></nav>
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
                <span class="section-label">3. Accreditation & Results Audit</span>
                <div class="row g-3">
                    <div class="col-4"><label class="small">Registered Voters</label><input type="number" id="rv" class="form-control" value="0"></div>
                    <div class="col-4"><label class="small">Accredited Voters</label><input type="number" id="ta" class="form-control" oninput="calculateTotals()"></div>
                    <div class="col-4"><label class="small">Rejected Ballots</label><input type="number" id="rj" class="form-control" value="0" oninput="calculateTotals()"></div>
                    <div class="col-6"><label class="small text-success fw-bold">Valid Votes</label><input type="number" id="vv" class="form-control" readonly></div>
                    <div class="col-6"><label class="small text-primary fw-bold">Total Cast</label><input type="number" id="tc" class="form-control" readonly></div>
                </div>
                <div id="auditStatus" class="mt-3 p-2 rounded text-center d-none small fw-bold"></div>
            </div>

            <button class="btn btn-outline-dark w-100 mb-3" onclick="getGPS()">Fix GPS Location</button>
            <button class="btn btn-success btn-lg w-100 py-3 fw-bold" onclick="reviewSubmission()">REVIEW & UPLOAD PU RESULT</button>
        </div>
    </div>

    <div class="modal fade" id="reviewModal" tabindex="-1">
        <div class="modal-dialog modal-lg">
            <div class="modal-content">
                <div class="modal-header"><h5>Review Results Summary</h5></div>
                <div class="modal-body">
                    <div class="row mb-3 border-bottom pb-2">
                        <div class="col-6"><small>PU:</small> <div id="revPUName" class="fw-bold text-success"></div></div>
                        <div class="col-3"><small>Accredited:</small> <div id="revAcc" class="fw-bold"></div></div>
                        <div class="col-3"><small>Total Cast:</small> <div id="revCast" class="fw-bold"></div></div>
                    </div>
                    <h6 class="fw-bold">Party Scores:</h6>
                    <div class="row g-1" id="revPartyGrid"></div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" data-bs-dismiss="modal">Go Back</button>
                    <button class="btn btn-success fw-bold" onclick="finalSubmit()">Confirm and Submit</button>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        let lat, lon, officerId, puData = [], wardData = [];
        const reviewModal = new bootstrap.Modal(document.getElementById('reviewModal'));

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
            const s = document.getElementById('s').value;
            fetch('/api/lgas/'+encodeURIComponent(s)).then(r=>r.json()).then(data=>{{
                const l = document.getElementById('l'); l.innerHTML = '<option value="">LGA</option>';
                data.forEach(item => l.add(new Option(item.toUpperCase(), item)));
            }});
        }}

        function loadWards() {{
            const s = document.getElementById('s').value;
            const lg = document.getElementById('l').value;
            fetch(`/api/wards/${{encodeURIComponent(s)}}/${{encodeURIComponent(lg)}}`).then(r=>r.json()).then(data=>{{
                wardData = data;
                const w = document.getElementById('w'); w.innerHTML = '<option value="">WARD</option>';
                data.forEach(item => w.add(new Option(item.name.toUpperCase(), item.name)));
            }});
        }}

        function loadPUs() {{
            const s = document.getElementById('s').value;
            const lg = document.getElementById('l').value;
            const w = document.getElementById('w').value;
            const wardObj = wardData.find(x => x.name === w);
            document.getElementById('wc').value = wardObj ? wardObj.code : '';
            fetch(`/api/pus/${{encodeURIComponent(s)}}/${{encodeURIComponent(lg)}}/${{encodeURIComponent(w)}}`).then(r=>r.json()).then(data=>{{
                puData = data;
                const p = document.getElementById('p'); p.innerHTML = '<option value="">SELECT PU</option>';
                data.forEach((item, idx) => p.add(new Option(item.location.toUpperCase(), idx)));
            }});
        }}

        function fillPU() {{
            const idx = document.getElementById('p').value;
            const sel = puData[idx];
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
            msg.classList.remove('d-none');
            if (acc > 0 && cast > acc) {{
                msg.innerHTML = "⚠️ ERROR: Over-voting detected!";
                msg.className = "mt-3 p-2 bg-danger text-white rounded text-center small fw-bold";
            }} else if (cast > 0 && cast === acc) {{
                msg.innerHTML = "✅ AUDIT BALANCED";
                msg.className = "mt-3 p-2 bg-success text-white rounded text-center small fw-bold";
            }} else {{ msg.classList.add('d-none'); }}
        }}

        function getGPS() {{
            navigator.geolocation.getCurrentPosition(pos => {{
                lat = pos.coords.latitude; lon = pos.coords.longitude;
                alert("GPS Fixed!");
            }});
        }}

        function reviewSubmission() {{
            if(!lat) return alert("Please Fix GPS first");
            document.getElementById('revPUName').innerText = document.getElementById('loc').value;
            document.getElementById('revAcc').innerText = document.getElementById('ta').value;
            document.getElementById('revCast').innerText = document.getElementById('tc').value;
            
            let grid = "";
            document.querySelectorAll('.party-v').forEach(i => {{
                grid += `<div class="col-4 small border p-1">${{i.dataset.p}}: <b>${{i.value}}</b></div>`;
            }});
            document.getElementById('revPartyGrid').innerHTML = grid;
            reviewModal.show();
        }}

        async function finalSubmit() {{
            const v = {{}};
            document.querySelectorAll('.party-v').forEach(i => v[i.dataset.p] = parseInt(i.value || 0));
            const payload = {{
                officer_id: officerId, 
                state: document.getElementById('s').value, 
                lg: document.getElementById('l').value,
                ward: document.getElementById('w').value, 
                ward_code: document.getElementById('wc').value,
                pu_code: document.getElementById('pc').value, 
                location: document.getElementById('loc').value,
                reg_voters: parseInt(document.getElementById('rv').value || 0), 
                total_accredited: parseInt(document.getElementById('ta').value || 0),
                valid_votes: parseInt(document.getElementById('vv').value || 0),
                rejected_votes: parseInt(document.getElementById('rj').value || 0),
                total_cast: parseInt(document.getElementById('tc').value || 0),
                lat, lon, votes: v
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

# --- DASHBOARD BACKEND LOGIC ---

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    return DASHBOARD_HTML

@app.get("/locations/states")
def get_dash_states():
    return get_states()

@app.get("/locations/lgas/{state}")
def get_dash_lgas(state: str):
    return get_lgas(state)

@app.get("/locations/wards/{state}/{lga}")
def get_dash_wards(state: str, lga: str):
    return get_wards(state, lga)

@app.get("/submissions")
async def get_dashboard_data():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # 1. Correct way to execute in Psycopg2
                cur.execute("SELECT * FROM field_submissions ORDER BY timestamp DESC")
                rows = cur.fetchall()
                
                data = []
                for r in rows:
                    # 2. Handle votes_json (Postgres might store it as a string)
                    votes_raw = r.get('votes_json', '{}')
                    votes = json.loads(votes_raw) if isinstance(votes_raw, str) else votes_raw
                    
                    data.append({
                        "pu_name": r.get('location'),
                        "state": r.get('state'),
                        "lga": r.get('lg'),
                        "ward": r.get('ward'),
                        "latitude": r.get('lat', 0.0),
                        "longitude": r.get('lon', 0.0),
                        "votes_party_ACCORD": votes.get("ACCORD", 0), 
                        "votes_party_APC": votes.get("APC", 0),
                        "votes_party_PDP": votes.get("PDP", 0),
                        "votes_party_ADC": votes.get("ADC", 0),
                        "incident_type": None 
                    })
                return data
    except Exception as e:
        print(f"DASHBOARD DATA ERROR: {e}")
        return []
# --- DASHBOARD HTML (FULL UPDATE) ---
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
    <script src="https://leaflet.github.io/Leaflet.heat/dist/leaflet-heat.js"></script>
    <style>
        :root { --bg: #0d0d0d; --panel: #161616; --gold: #ffc107; --border: #333; --text: #e0e0e0; --pdp: #d9534f; --apc: #0b3d91; --adc: #006400; }
        body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; height: 100vh; margin: 0; overflow: hidden; display: flex; flex-direction: column; }
        select option { background-color: #161616 !important; color: white !important; }
        .navbar-custom { border-bottom: 1px solid var(--gold); padding: 0 15px; display: flex; align-items: center; background: var(--bg); height: 75px; gap: 15px; }
        .brand-section { min-width: 180px; }
        .brand-title { font-size: 13px; font-weight: bold; color: white; letter-spacing: 1px; }
        .brand-sub { font-size: 10px; color: var(--gold); font-weight: bold; }
        .nav-kpi-group { display: flex; flex: 1; align-items: center; justify-content: center; gap: 12px; }
        .party-box { display: flex; align-items: center; background: rgba(255,255,255,0.05); border: 1px solid var(--border); padding: 5px 15px; min-width: 130px; height: 62px; gap: 10px; }
        .party-box img { height: 35px; width: 35px; border-radius: 50%; object-fit: contain; background: white; }
        .party-info label { font-size: 8px; color: #888; text-transform: uppercase; margin: 0; font-weight: bold; display: block; }
        .party-info span { font-size: 16px; font-weight: 900; color: white; line-height: 1; }
        .box-accord { border-top: 4px solid var(--gold); }
        .box-apc { border-top: 4px solid var(--apc); }
        .box-pdp { border-top: 4px solid var(--pdp); }
        .box-adc { border-top: 4px solid var(--adc); }
        .box-margin { border-top: 4px solid #555; }
        .filter-group { display: flex; align-items: center; gap: 8px; }
        .filter-item { border-left: 1px solid var(--border); padding-left: 10px; }
        .filter-item label { color: var(--gold); font-size: 9px; text-transform: uppercase; display: block; font-weight: bold; }
        .filter-item select { background: transparent; color: #fff; border: none; font-size: 12px; outline: none; cursor: pointer; font-weight: bold; }
        .main-container { display: flex; flex: 1; gap: 10px; padding: 10px; overflow: hidden; height: calc(100vh - 75px); }
        .col-side { width: 320px; display: flex; flex-direction: column; gap: 10px; height: 100%; }
        .col-center { flex: 1; display: flex; flex-direction: column; gap: 10px; }
        .widget { background: var(--panel); border: 1px solid var(--border); padding: 12px; display: flex; flex-direction: column; border-radius: 4px; position: relative; }
        .widget-title { color: var(--gold); font-size: 10px; font-weight: bold; border-bottom: 1px solid var(--border); margin-bottom: 8px; padding-bottom: 4px; text-transform: uppercase; display: flex; justify-content: space-between; }
        .map-wrapper { flex: 1; position: relative; background: #000; border-radius: 4px; overflow: hidden; }
        #map { position: absolute; top: 0; bottom: 0; left: 0; right: 0; height: 100% !important; }
        .pu-list { flex: 1; overflow-y: auto; }
        .pu-card { border-bottom: 1px solid var(--border); padding: 12px 10px; cursor: pointer; transition: background 0.2s; }
        .pu-card:hover { background: rgba(255, 193, 7, 0.05); }
        .pu-card b { color: var(--gold); font-size: 13px; display: block; margin-bottom: 4px; }
        .pu-loc { font-size: 10px; color: #bbb; display: block; margin-bottom: 8px; }
        .pu-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; background: rgba(0,0,0,0.5); padding: 8px; border-radius: 4px; pointer-events: none; }
        .grid-val { text-align: center; }
        .grid-val small { font-size: 8px; color: #888; display: block; text-transform: uppercase; }
        .grid-val span { font-size: 11px; font-weight: bold; }
        
        /* Fixed Chart and Sidebar Alignment */
        .chart-wrapper { height: 210px; position: relative; margin-bottom: 5px; }
        .totals-container { flex: 1; display: flex; flex-direction: column; gap: 8px; overflow: hidden; }
        .big-total-box { text-align: center; padding: 8px; flex: 1; display: flex; flex-direction: column; justify-content: center; }
        .big-val { font-size: 28px; font-weight: 900; color: white; line-height: 1; margin: 4px 0; }
        .box-acc-total { border: 1px solid var(--gold); }
        .box-apc-total { border: 1px solid var(--apc); }
        .box-pdp-total { border: 1px solid var(--pdp); }
        .box-adc-total { border: 1px solid var(--adc); }
        
        .ts-box { font-size: 9px; color: #888; text-transform: uppercase; margin-top: 4px; letter-spacing: 1px; }
        #ai_box { background: #1a1a00; border: 1px solid #333300; padding: 10px; font-size: 11px; color: #ffc107; border-radius: 4px; min-height: 50px; overflow-y: auto;}
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
            <img src="/logos/ACCORD.png" onerror="this.src='https://via.placeholder.com/42?text=ACC'">
            <div class="party-info"><label>ACCORD</label><span id="nav-ACCORD">0</span></div>
        </div>
        <div class="party-box box-apc">
            <img src="/logos/APC.png" onerror="this.src='https://via.placeholder.com/42?text=APC'">
            <div class="party-info"><label>APC</label><span id="nav-APC">0</span></div>
        </div>
        <div class="party-box box-pdp">
            <img src="/logos/PDP.png" onerror="this.src='https://via.placeholder.com/42?text=PDP'">
            <div class="party-info"><label>PDP</label><span id="nav-PDP">0</span></div>
        </div>
        <div class="party-box box-adc">
            <img src="/logos/ADC.png" onerror="this.src='https://via.placeholder.com/42?text=ADC'">
            <div class="party-info"><label>ADC</label><span id="nav-ADC">0</span></div>
        </div>
        <div class="party-box box-margin">
            <div class="party-info" style="text-align:center; width:100%"><label>LEAD MARGIN</label><span id="nav-Margin" style="color:var(--gold)">0</span></div>
        </div>
    </div>
    <div class="filter-group">
        <div class="filter-item"><label>State</label><select id="stateFilter" onchange="loadLGAsDash()"><option value="">All States</option></select></div>
        <div class="filter-item"><label>LGA</label><select id="lgaFilter" onchange="loadWardsDash()"><option value="">All LGAs</option></select></div>
        <div class="filter-item"><label>Ward</label><select id="wardFilter" onchange="refreshData()"><option value="">All Wards</option></select></div>
    </div>
</nav>

<div class="main-container">
    <div class="col-side">
        <div class="widget" style="padding: 8px;">
            <input type="text" id="puSearch" placeholder="🔍 Search Polling Units..." onkeyup="refreshData()" 
                   style="background:#222; border:none; color:white; padding:10px; font-size:12px; width:100%; border-radius:4px;">
        </div>
        <div class="widget pu-list">
            <div class="widget-title">Live Result Feed <span onclick="resetFilters()" style="color:var(--gold); cursor:pointer;">RESET</span></div>
            <div id="puContainer"></div>
        </div>
    </div>
    <div class="col-center">
        <div class="widget map-wrapper"><div id="map"></div></div>
        <div class="widget" style="height: 120px;">
            <div class="widget-title">AI STATISTICAL INTERPRETATION</div>
            <div id="ai_box">Loading high-level insights...</div>
            <button onclick="runAI()" class="btn btn-sm btn-outline-warning mt-2">GENERATE STRATEGIC ANALYSIS</button>
        </div>
    </div>
    <div class="col-side">
        <div class="widget chart-wrapper">
            <div class="widget-title" id="chartLabel">Vote Distribution %</div>
            <canvas id="pieChart"></canvas>
        </div>
        
        <div class="totals-container">
            <div class="widget big-total-box box-acc-total">
                <div style="color:var(--gold); font-size:9px; font-weight:bold; text-transform:uppercase;">Accord Total</div>
                <div id="totalAccordBig" class="big-val">0</div>
            </div>
            <div class="widget big-total-box box-apc-total">
                <div style="color:var(--apc); font-size:9px; font-weight:bold; text-transform:uppercase;">APC Total</div>
                <div id="totalAPCBig" class="big-val">0</div>
            </div>
            <div class="widget big-total-box box-pdp-total">
                <div style="color:var(--pdp); font-size:9px; font-weight:bold; text-transform:uppercase;">PDP Total</div>
                <div id="totalPDPBig" class="big-val">0</div>
            </div>
            <div class="widget big-total-box box-adc-total">
                <div style="color:var(--adc); font-size:9px; font-weight:bold; text-transform:uppercase;">ADC Total</div>
                <div id="totalADCBig" class="big-val">0</div>
            </div>
        </div>
        
        <div class="ts-box text-center" id="lastUpdateTS" style="margin-top:5px;">Last Updated: --:--:--</div>
    </div>
</div>

<script>
Chart.register(ChartDataLabels);

// Plugin to draw total in center
const centerTextPlugin = {
    id: 'centerText',
    afterDraw: (chart) => {
        if (chart.config.type !== 'doughnut') return;
        const { ctx, chartArea: { top, bottom, left, right, width, height } } = chart;
        ctx.save();
        const total = chart.data.datasets[0].data.reduce((a, b) => a + b, 0);
        
        ctx.font = 'bold 12px Segoe UI';
        ctx.fillStyle = '#888';
        ctx.textAlign = 'center';
        ctx.fillText('TOTAL VOTES', width / 2, height / 2 + top - 10);
        
        ctx.font = '900 18px Segoe UI';
        ctx.fillStyle = '#fff';
        ctx.fillText(total.toLocaleString(), width / 2, height / 2 + top + 15);
        ctx.restore();
    }
};
Chart.register(centerTextPlugin);

let map = L.map('map', {zoomControl: false, attributionControl: false}).setView([9.082, 8.675], 6);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png').addTo(map);
let markers = [], heatLayer = null, charts = {}, globalData = [];

async function initDashboard() {
    try {
        const states = await (await fetch("/locations/states")).json();
        const sS = document.getElementById("stateFilter");
        states.forEach(s => sS.add(new Option(s.toUpperCase(), s)));
    } catch(e) { console.error(e); }
    refreshData();
}

async function loadLGAsDash() {
    const s = document.getElementById("stateFilter").value;
    const lS = document.getElementById("lgaFilter");
    lS.innerHTML = '<option value="">All LGAs</option>';
    if(!s) return refreshData();
    const lgas = await (await fetch("/locations/lgas/"+encodeURIComponent(s))).json();
    lgas.forEach(l => lS.add(new Option(l.toUpperCase(), l)));
    refreshData();
}

async function loadWardsDash() {
    const s = document.getElementById("stateFilter").value;
    const l = document.getElementById("lgaFilter").value;
    const wS = document.getElementById("wardFilter");
    wS.innerHTML = '<option value="">All Wards</option>';
    if(!l) return refreshData();
    const wards = await (await fetch(`/locations/wards/${encodeURIComponent(s)}/${encodeURIComponent(l)}`)).json();
    wards.forEach(w => wS.add(new Option(w.name.toUpperCase(), w.name)));
    refreshData();
}

function resetFilters() {
    document.getElementById("stateFilter").value = "";
    document.getElementById("lgaFilter").innerHTML = '<option value="">All LGAs</option>';
    document.getElementById("wardFilter").innerHTML = '<option value="">All Wards</option>';
    refreshData();
}

async function refreshData() {
    try {
        const res = await fetch("/submissions");
        let data = await res.json();
        const sf = document.getElementById("stateFilter").value;
        const lf = document.getElementById("lgaFilter").value;
        const wf = document.getElementById("wardFilter").value;
        const search = document.getElementById("puSearch").value.toLowerCase();
        
        if(sf) data = data.filter(d => d.state === sf);
        if(lf) data = data.filter(d => d.lga === lf);
        if(wf) data = data.filter(d => d.ward === wf);
        if(search) data = data.filter(d => d.pu_name.toLowerCase().includes(search));

        globalData = data; 
        updateUI(data);
    } catch(e) { console.error(e); }
}

async function runAI() {
    const data = {
        ACCORD: parseInt(document.getElementById("nav-ACCORD").innerText.replace(/,/g, '')),
        APC: parseInt(document.getElementById("nav-APC").innerText.replace(/,/g, '')),
        PDP: parseInt(document.getElementById("nav-PDP").innerText.replace(/,/g, '')),
        ADC: parseInt(document.getElementById("nav-ADC").innerText.replace(/,/g, '')),
    };
    const res = await fetch("/api/ai_interpret", {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    });
    const out = await res.json();
    document.getElementById("ai_box").innerText = out.analysis;
}

function updateUI(data) {
    let tACCORD = 0, tAPC = 0, tPDP = 0, tADC = 0, listHtml = "", heatPoints = [];
    markers.forEach(m => map.removeLayer(m));
    if(heatLayer) map.removeLayer(heatLayer);
    markers = [];
    
    data.forEach(d => {
        tACCORD += d.votes_party_ACCORD; tAPC += d.votes_party_APC; tPDP += d.votes_party_PDP; tADC += d.votes_party_ADC;
        
        listHtml += `<div class="pu-card"><b>${d.pu_name}</b><small class="pu-loc">${d.lga}, ${d.ward}</small>
        <div class="pu-grid">
            <div class="grid-val"><small>ACC</small><span>${d.votes_party_ACCORD}</span></div>
            <div class="grid-val"><small>APC</small><span>${d.votes_party_APC}</span></div>
            <div class="grid-val"><small>PDP</small><span>${d.votes_party_PDP}</span></div>
            <div class="grid-val"><small>ADC</small><span>${d.votes_party_ADC}</span></div>
        </div></div>`;

        if(d.latitude && d.longitude) {
            markers.push(L.circleMarker([d.latitude, d.longitude], {radius: 4, color: '#ffc107'}).addTo(map));
            heatPoints.push([d.latitude, d.longitude, d.votes_party_ACCORD / 100]);
        }
    });

    heatLayer = L.heatLayer(heatPoints, {radius: 25, blur: 15, maxZoom: 10}).addTo(map);

    document.getElementById("nav-ACCORD").innerText = tACCORD.toLocaleString();
    document.getElementById("totalAccordBig").innerText = tACCORD.toLocaleString();
    document.getElementById("nav-APC").innerText = tAPC.toLocaleString();
    document.getElementById("totalAPCBig").innerText = tAPC.toLocaleString();
    document.getElementById("nav-PDP").innerText = tPDP.toLocaleString();
    document.getElementById("totalPDPBig").innerText = tPDP.toLocaleString();
    document.getElementById("nav-ADC").innerText = tADC.toLocaleString();
    document.getElementById("totalADCBig").innerText = tADC.toLocaleString();
    
    document.getElementById("nav-Margin").innerText = (tACCORD - Math.max(tAPC, tPDP)).toLocaleString();
    document.getElementById("puContainer").innerHTML = listHtml;
    document.getElementById("lastUpdateTS").innerText = "Last Updated: " + new Date().toLocaleTimeString();
    
    updateCharts(tACCORD, tAPC, tPDP, tADC);
}

function updateCharts(acc, apc, pdp, adc) {
    const ctx = document.getElementById('pieChart');
    if(charts.pie) charts.pie.destroy();
    charts.pie = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['ACCORD', 'APC', 'PDP', 'ADC'],
            datasets: [{ 
                data: [acc, apc, pdp, adc], 
                backgroundColor: ['#ffc107', '#0b3d91', '#d9534f', '#006400'],
                borderWidth: 1,
                borderColor: '#161616'
            }]
        },
        options: { 
            maintainAspectRatio: false, 
            cutout: '70%',
            plugins: { 
                legend: { display: false },
                datalabels: {
                    color: '#fff',
                    font: { weight: 'bold', size: 10 },
                    formatter: (value, context) => {
                        const total = context.dataset.data.reduce((a, b) => a + b, 0);
                        return total > 0 ? Math.round((value / total) * 100) + '%' : '';
                    }
                }
            } 
        }
    });
}

initDashboard();
setInterval(refreshData, 30000);
</script>
</body></html>
"""
