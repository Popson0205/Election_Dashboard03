import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json
import logging
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import io
import csv
from fastapi.responses import StreamingResponse

# --- CONFIGURATION ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Render-safe Pathing
LOGO_PATH = os.path.join(os.getcwd(), "static", "logos")
if os.path.exists(LOGO_PATH):
    app.mount("/logos", StaticFiles(directory=LOGO_PATH), name="logos")

# Ensure general static files (like /static/bg.png) are servable
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

@app.get("/api/lgas/{{state}}")
def get_lgas(state: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT lg FROM polling_units WHERE state = %s ORDER BY lg", (state,))
            rows = cur.fetchall()
            return [r["lg"] for r in rows]

@app.get("/api/wards/{{state}}/{{lg}}")
def get_wards(state: str, lg: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT ward, ward_code FROM polling_units WHERE state = %s AND lg = %s ORDER BY ward", (state, lg))
            rows = cur.fetchall()
            return [{"name": r["ward"], "code": r["ward_code"]} for r in rows]

@app.get("/api/pus/{{state}}/{{lg}}/{{ward}}")
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
    analysis = f"STATISTICAL AUDIT: Accord maintains {share:.1f}% share. Leading {top_rival} by {abs(margin):,} votes."
    return {"analysis": analysis}

@app.get("/export/csv")
async def export_csv():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM field_submissions ORDER BY timestamp DESC")
            rows = cur.fetchall()
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["Timestamp", "Officer ID", "State", "LGA", "Ward", "PU Code", "Location", "Reg Voters", "Accredited", "Total Cast", "ACCORD", "APC", "PDP", "ADC"])
            for r in rows:
                v = json.loads(r['votes_json']) if isinstance(r['votes_json'], str) else r['votes_json']
                writer.writerow([r['timestamp'], r['officer_id'], r['state'], r['lg'], r['ward'], r['pu_code'], r['location'], r['reg_voters'], r['total_accredited'], r['total_cast'], v.get("ACCORD", 0), v.get("APC", 0), v.get("PDP", 0), v.get("ADC", 0)])
            output.seek(0)
            return StreamingResponse(output, media_type="text/csv", headers={{"Content-Disposition": "attachment; filename=results.csv"}})

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
        #loginArea {{ margin-top: 100px; border: 1px solid rgba(255,255,255,0.2); }}
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
                <div class="modal-header" style="background: #008751; color: white;"><h5>Review Results Summary</h5></div>
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
            const idx = document.getElementById('p').value;
            const sel = puData[idx];
            document.getElementById('pc').value = sel.pu_code;
            document.getElementById('loc').value = sel.location.toUpperCase();
        }}

        function calculateTotals() {{
            let v = 0; document.querySelectorAll('.party-v').forEach(i => v += parseInt(i.value || 0));
            const r = parseInt(document.getElementById('rj').value || 0);
            const a = parseInt(document.getElementById('ta').value || 0);
            const c = v + r;
            document.getElementById('vv').value = v; document.getElementById('tc').value = c;
            const m = document.getElementById('auditStatus');
            if (a > 0 && c > a) {{ m.innerHTML = "⚠️ ERROR: Over-voting!"; m.className = "mt-3 p-2 bg-danger text-white rounded text-center small fw-bold d-block"; }}
            else if (c > 0 && c === a) {{ m.innerHTML = "✅ AUDIT BALANCED"; m.className = "mt-3 p-2 bg-success text-white rounded text-center small fw-bold d-block"; }}
            else {{ m.className = "d-none"; }}
        }}

        function getGPS() {{ navigator.geolocation.getCurrentPosition(p => {{ lat = p.coords.latitude; lon = p.coords.longitude; alert("GPS Fixed!"); }}); }}

        function reviewSubmission() {{
            if(!lat) return alert("Please Fix GPS first");
            document.getElementById('revPUName').innerText = document.getElementById('loc').value;
            document.getElementById('revAcc').innerText = document.getElementById('ta').value;
            document.getElementById('revCast').innerText = document.getElementById('tc').value;
            let g = ""; document.querySelectorAll('.party-v').forEach(i => {{ g += `<div class="col-4 small border p-1">${{i.dataset.p}}: <b>${{i.value}}</b></div>`; }});
            document.getElementById('revPartyGrid').innerHTML = g;
            reviewModal.show();
        }}

        async function finalSubmit() {{
            const v = {{}}; document.querySelectorAll('.party-v').forEach(i => v[i.dataset.p] = parseInt(i.value || 0));
            const p = {{ officer_id: officerId, state: document.getElementById('s').value, lg: document.getElementById('l').value, ward: document.getElementById('w').value, ward_code: document.getElementById('wc').value, pu_code: document.getElementById('pc').value, location: document.getElementById('loc').value, reg_voters: parseInt(document.getElementById('rv').value || 0), total_accredited: parseInt(document.getElementById('ta').value || 0), valid_votes: parseInt(document.getElementById('vv').value || 0), rejected_votes: parseInt(document.getElementById('rj').value || 0), total_cast: parseInt(document.getElementById('tc').value || 0), lat, lon, votes: v }};
            const res = await fetch('/submit', {{ method: 'POST', headers: {{'Content-Type':'application/json'}}, body: JSON.stringify(p)}});
            const out = await res.json(); alert(out.message); if(out.status === 'success') location.reload();
        }}
    </script>
</body>
</html>
"""

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    return DASHBOARD_HTML

@app.get("/locations/states")
def get_dash_states():
    return get_states()

@app.get("/locations/lgas/{{state}}")
def get_dash_lgas(state: str):
    return get_lgas(state)

@app.get("/locations/wards/{{state}}/{{lga}}")
def get_dash_wards(state: str, lga: str):
    return get_wards(state, lga)

@app.get("/submissions")
async def get_dashboard_data():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM field_submissions ORDER BY timestamp DESC")
                rows = cur.fetchall()
                data = []
                for r in rows:
                    v_raw = r.get('votes_json', '{{}}')
                    v = json.loads(v_raw) if isinstance(v_raw, str) else v_raw
                    data.append({{ "pu_name": r.get('location'), "state": r.get('state'), "lga": r.get('lg'), "ward": r.get('ward'), "latitude": r.get('lat', 0.0), "longitude": r.get('lon', 0.0), "votes_party_ACCORD": v.get("ACCORD", 0), "votes_party_APC": v.get("APC", 0), "votes_party_PDP": v.get("PDP", 0), "votes_party_ADC": v.get("ADC", 0), "incident_type": None }})
                return data
    except Exception as e: return []

DASHBOARD_HTML = f"""
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
        :root {{ --bg: #0d0d0d; --panel: #161616; --gold: #ffc107; --border: #333; --text: #e0e0e0; --pdp: #d9534f; --apc: #0b3d91; --adc: #006400; }}
        body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; height: 100vh; margin: 0; overflow: hidden; display: flex; flex-direction: column; }}
        .navbar-custom {{ border-bottom: 1px solid var(--gold); padding: 0 15px; display: flex; align-items: center; background: var(--bg); height: 75px; gap: 15px; }}
        .nav-kpi-group {{ display: flex; flex: 1; align-items: center; justify-content: center; gap: 12px; }}
        .party-box {{ display: flex; align-items: center; background: rgba(255,255,255,0.05); border: 1px solid var(--border); padding: 5px 15px; min-width: 130px; height: 62px; gap: 10px; }}
        .party-box img {{ height: 35px; width: 35px; border-radius: 50%; object-fit: contain; background: white; }}
        .party-info label {{ font-size: 8px; color: #888; text-transform: uppercase; margin: 0; font-weight: bold; display: block; }}
        .party-info span {{ font-size: 16px; font-weight: 900; color: white; line-height: 1; }}
        .box-accord {{ border-top: 4px solid var(--gold); }}
        .box-apc {{ border-top: 4px solid var(--apc); }}
        .box-pdp {{ border-top: 4px solid var(--pdp); }}
        .box-adc {{ border-top: 4px solid var(--adc); }}
        .main-container {{ display: flex; flex: 1; gap: 10px; padding: 10px; overflow: hidden; height: calc(100vh - 75px); }}
        .col-side {{ width: 320px; display: flex; flex-direction: column; gap: 10px; height: 100%; }}
        .col-center {{ flex: 1; display: flex; flex-direction: column; gap: 10px; }}
        .widget {{ background: var(--panel); border: 1px solid var(--border); padding: 12px; display: flex; flex-direction: column; border-radius: 4px; position: relative; }}
        .widget-title {{ color: var(--gold); font-size: 10px; font-weight: bold; border-bottom: 1px solid var(--border); margin-bottom: 8px; padding-bottom: 4px; text-transform: uppercase; display: flex; justify-content: space-between; }}
        .map-wrapper {{ flex: 1; position: relative; background: #000; border-radius: 4px; overflow: hidden; }}
        #map {{ position: absolute; top: 0; bottom: 0; left: 0; right: 0; height: 100% !important; }}
        .pu-list {{ flex: 1; overflow-y: auto; }}
        .pu-card {{ border-bottom: 1px solid var(--border); padding: 12px 10px; cursor: pointer; transition: background 0.2s; }}
        .pu-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; background: rgba(0,0,0,0.5); padding: 8px; border-radius: 4px; pointer-events: none; }}
        .big-val {{ font-size: 28px; font-weight: 900; color: white; line-height: 1; margin: 4px 0; }}
        .box-acc-total {{ border: 1px solid var(--gold); }}
        .box-apc-total {{ border: 1px solid var(--apc); }}
        .box-pdp-total {{ border: 1px solid var(--pdp); }}
        .box-adc-total {{ border: 1px solid var(--adc); }}
    </style>
</head>
<body>
<nav class="navbar-custom">
    <div class="brand-section" style="min-width: 180px;">
        <div style="font-size: 13px; font-weight: bold; color: white;">ACCORD SITUATION ROOM</div>
        <div style="font-size: 10px; color: var(--gold); font-weight: bold;">OFFICIAL FIELD VIEW</div>
    </div>
    <div class="nav-kpi-group">
        <div class="party-box box-accord"><img src="/logos/ACCORD.png"><div class="party-info"><label>ACCORD</label><span id="nav-ACCORD">0</span></div></div>
        <div class="party-box box-apc"><img src="/logos/APC.png"><div class="party-info"><label>APC</label><span id="nav-APC">0</span></div></div>
        <div class="party-box box-pdp"><img src="/logos/PDP.png"><div class="party-info"><label>PDP</label><span id="nav-PDP">0</span></div></div>
        <div class="party-box box-adc"><img src="/logos/ADC.png"><div class="party-info"><label>ADC</label><span id="nav-ADC">0</span></div></div>
    </div>
    <div class="filter-group" style="display: flex; gap: 8px;">
        <select id="stateFilter" onchange="loadLGAsDash()"><option value="">All States</option></select>
    </div>
</nav>
<div class="main-container">
    <div class="col-side">
        <div class="widget"><input type="text" id="puSearch" placeholder="🔍 Search PU..." onkeyup="refreshData()" style="background:#222; border:none; color:white; padding:10px; width:100%;"></div>
        <div class="widget pu-list"><div class="widget-title">Live Results</div><div id="puContainer"></div></div>
    </div>
    <div class="col-center">
        <div class="widget map-wrapper"><div id="map"></div></div>
        <div class="widget" style="height: 120px;"><div class="widget-title">AI INSIGHTS</div><div id="ai_box">Analyzing...</div></div>
    </div>
    <div class="col-side">
        <div class="widget" style="height: 210px;"><canvas id="pieChart"></canvas></div>
        <div class="widget box-acc-total text-center"><label style="color:var(--gold); font-size:9px;">ACCORD</label><div id="totalAccordBig" class="big-val">0</div></div>
        <div class="widget box-apc-total text-center"><label style="color:var(--apc); font-size:9px;">APC</label><div id="totalAPCBig" class="big-val">0</div></div>
        <div class="widget box-pdp-total text-center"><label style="color:var(--pdp); font-size:9px;">PDP</label><div id="totalPDPBig" class="big-val">0</div></div>
        <div class="widget box-adc-total text-center"><label style="color:var(--adc); font-size:9px;">ADC</label><div id="totalADCBig" class="big-val">0</div></div>
    </div>
</div>
<script>
    Chart.register(ChartDataLabels);
    let map = L.map('map', {{zoomControl: false}}).setView([9.082, 8.675], 6);
    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png').addTo(map);
    let charts = {{}};
    async function initDashboard() {{
        const states = await (await fetch("/locations/states")).json();
        const s = document.getElementById("stateFilter");
        states.forEach(st => s.add(new Option(st.toUpperCase(), st)));
        refreshData();
    }}
    async function refreshData() {{
        const res = await fetch("/submissions");
        const data = await res.json();
        updateKpis(data); updateChart(data); updateList(data);
    }}
    function updateKpis(data) {{
        let t = {{ ACCORD: 0, APC: 0, PDP: 0, ADC: 0 }};
        data.forEach(d => {{ t.ACCORD += d.votes_party_ACCORD; t.APC += d.votes_party_APC; t.PDP += d.votes_party_PDP; t.ADC += d.votes_party_ADC; }});
        document.getElementById('nav-ACCORD').innerText = t.ACCORD.toLocaleString();
        document.getElementById('totalAccordBig').innerText = t.ACCORD.toLocaleString();
        // repeat for others...
    }}
    function updateChart(data) {{
        const ctx = document.getElementById('pieChart').getContext('2d');
        if(charts.pie) charts.pie.destroy();
        charts.pie = new Chart(ctx, {{ type: 'doughnut', data: {{ labels: ['ACC','APC','PDP','ADC'], datasets: [{{ data: [10,20,30,40], backgroundColor: ['#ffc107','#0b3d91','#d9534f','#006400'] }}] }}, options: {{ responsive: true, maintainAspectRatio: false }} }});
    }}
    function updateList(data) {{
        const c = document.getElementById('puContainer'); c.innerHTML = '';
        data.slice(0, 50).forEach(d => {{
            let div = document.createElement('div'); div.className = 'pu-card';
            div.innerHTML = `<b>${{d.pu_name}}</b><div class="pu-grid"><span>${{d.votes_party_ACCORD}}</span></div>`;
            c.appendChild(div);
        }});
    }}
    initDashboard();
</script>
</body>
</html>
"""
