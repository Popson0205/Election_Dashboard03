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

# ─────────────────────────────────────────────────────────────────────────────
# OSUN 2026 GOVERNORSHIP — 14 ELIGIBLE PARTIES
# ─────────────────────────────────────────────────────────────────────────────
OSUN_PARTIES = ["A", "AA", "AAC", "ADC", "ADP", "APGA", "APC", "APM", "APP", "BP", "NNPP", "PRP", "YPP", "ZLP"]

# Human-readable labels for each party code
PARTY_LABELS = {
    "A":    "Accord (A)",
    "AA":   "Action Alliance (AA)",
    "AAC":  "African Action Congress (AAC)",
    "ADC":  "African Democratic Congress (ADC)",
    "ADP":  "Action Democratic Party (ADP)",
    "APGA": "All Progressives Grand Alliance (APGA)",
    "APC":  "All Progressives Congress (APC)",
    "APM":  "Allied Peoples Movement (APM)",
    "APP":  "All Peoples Party (APP)",
    "BP":   "Boot Party (BP)",
    "NNPP": "New Nigeria Peoples Party (NNPP)",
    "PRP":  "Peoples Redemption Party (PRP)",
    "YPP":  "Young Progressives Party (YPP)",
    "ZLP":  "Zenith Labour Party (ZLP)",
}

# Fixed state scope
OSUN_STATE = "Osun"

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
    # Locked to Osun only
    return [OSUN_STATE]

@app.get("/api/lgas/{state}")
def get_lgas(state: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT lg FROM polling_units WHERE state = %s ORDER BY lg",
                (OSUN_STATE,)
            )
            rows = cur.fetchall()
            return [r["lg"] for r in rows]

@app.get("/api/wards/{state}/{lg}")
def get_wards(state: str, lg: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT ward, ward_code FROM polling_units WHERE state = %s AND lg = %s ORDER BY ward",
                (OSUN_STATE, lg)
            )
            rows = cur.fetchall()
            return [{"name": r["ward"], "code": r["ward_code"]} for r in rows]

@app.get("/api/pus/{state}/{lg}/{ward}")
def get_pus(state: str, lg: str, ward: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT location, pu_code FROM polling_units WHERE state = %s AND lg = %s AND ward = %s",
                (OSUN_STATE, lg, ward)
            )
            rows = cur.fetchall()
            return [{"location": r["location"], "pu_code": r["pu_code"]} for r in rows]

@app.post("/submit")
async def submit(data: dict):
    try:
        # Force state to Osun regardless of payload
        data['state'] = OSUN_STATE
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
    # OSUN STATE ELECTORAL BASELINE (Official Stats)
    STATS = {
        "lgas": 30,
        "wards": 332,
        "pus": 3763,
        "urban_hubs": ["OSOGBO", "OLORUNDA", "ILESA EAST", "IFE CENTRAL", "IWO"]
    }

    # Extract votes for all 14 Osun parties
    votes = {p: data.get(p, 0) for p in OSUN_PARTIES}
    accord_votes = votes.get("A", 0)

    ta = data.get('total_accredited', 0)
    rv = data.get('reg_voters', 0)
    current_lg = str(data.get('lg', "")).upper()

    total_votes = sum(votes.values())
    if total_votes == 0:
        return {"analysis": "SYSTEM READY: Awaiting live feed from 3,763 Polling Units across Osun State."}

    # Statistical Calculations
    share = (accord_votes / total_votes) * 100
    rivals = {p: v for p, v in votes.items() if p != "A"}
    top_rival = max(rivals, key=rivals.get)
    margin = accord_votes - rivals[top_rival]
    turnout = (ta / rv * 100) if rv > 0 else 0

    # Intelligence Logic
    is_urban = current_lg in STATS["urban_hubs"]

    if share > 55:
        trend = "LANDSLIDE"
    elif share > 40:
        trend = "STRONG LEAD"
    else:
        trend = "BATTLEGROUND"

    location_tag = " [URBAN HUB]" if is_urban else " [RURAL SECTOR]"

    analysis = (
        f"OSUN STATISTICAL AUDIT ({current_lg}{location_tag}): "
        f"Accord is in a {trend} position with {share:.1f}% of the current tally. "
        f"Lead Margin over {top_rival}: **{margin:+,}** votes. "
    )

    if turnout > 0:
        analysis += f"Voter Productivity is at **{turnout:.1f}%**. "
        if turnout > 65:
            analysis += "⚠️ ALERT: Unusually high turnout detected; verify PU logs. "

    if is_urban and share < 45:
        analysis += "STRATEGY: Increase urban mobilization; Osogbo/Iwo volume is critical."
    elif not is_urban and share > 50:
        analysis += "STRATEGY: Rural stronghold confirmed. Protect the lead during collation."

    return {
        "analysis": analysis,
        "is_alert": turnout > 70 or margin < 100,
        "stats": {
            "turnout_gap": 100 - turnout,
            "osun_progress": f"Active in {STATS['lgas']} LGAs across Osun State"
        }
    }

@app.get("/api/dashboard_filters")
def get_dash_filters():
    with get_db() as conn:
        with conn.cursor() as cur:
            # Locked to Osun only
            cur.execute(
                "SELECT DISTINCT state, lg, ward FROM polling_units WHERE state = %s ORDER BY lg, ward",
                (OSUN_STATE,)
            )
            return cur.fetchall()

@app.get("/export/csv")
async def export_csv():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM field_submissions WHERE state = %s ORDER BY timestamp DESC",
                (OSUN_STATE,)
            )
            rows = cur.fetchall()
            output = io.StringIO()
            writer = csv.writer(output)
            header = ["Timestamp", "Officer ID", "State", "LGA", "Ward", "PU Code", "Location",
                      "Accredited", "Total Cast"] + OSUN_PARTIES
            writer.writerow(header)
            for r in rows:
                v = json.loads(r['votes_json']) if isinstance(r['votes_json'], str) else r['votes_json']
                row_data = [
                    r['timestamp'], r['officer_id'], r['state'], r['lg'], r['ward'],
                    r['pu_code'], r['location'], r['total_accredited'], r['total_cast']
                ]
                for p in OSUN_PARTIES:
                    row_data.append(v.get(p, 0))
                writer.writerow(row_data)
            output.seek(0)
            return StreamingResponse(
                output, media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=osun_election_audit.csv"}
            )

@app.get("/submissions")
async def get_dashboard_data():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM field_submissions WHERE state = %s ORDER BY timestamp DESC",
                (OSUN_STATE,)
            )
            rows = cur.fetchall()
            data = []
            for r in rows:
                v = json.loads(r['votes_json']) if isinstance(r['votes_json'], str) else r['votes_json']
                entry = {
                    "pu_name": r['location'], "state": r['state'],
                    "lga": r['lg'], "ward": r['ward'],
                    "latitude": r['lat'], "longitude": r['lon'],
                }
                for p in OSUN_PARTIES:
                    entry[f"votes_party_{p}"] = v.get(p, 0)
                data.append(entry)
            return data

# ─────────────────────────────────────────────────────────────────────────────
# FIELD FORM — 14-PARTY SCORECARD, STATE LOCKED TO OSUN
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    party_cards = "".join([f'''
        <div class="col-4 col-md-2 mb-2">
            <div class="p-2 border rounded text-center bg-white shadow-sm">
                <img src="/logos/{p}.png" onerror="this.src='https://via.placeholder.com/30?text={p}'" style="height:30px">
                <small class="d-block fw-bold">{p}</small>
                <input type="number" class="form-control form-control-sm party-v text-center" data-p="{p}" value="0" oninput="calculateTotals()">
            </div>
        </div>''' for p in OSUN_PARTIES])

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
        .state-badge {{ background: #ffc107; color: #000; font-weight: bold; font-size: 0.7rem; padding: 2px 8px; border-radius: 4px; }}
    </style>
</head>
<body>
    <nav class="navbar py-2 mb-4 text-center"><h5>IMOLE YOUTH ACCORD MOBILIZATION — OFFICIAL FIELD COLLATION <span class="state-badge ms-2">OSUN STATE</span></h5></nav>
    <div class="container pb-5" style="max-width: 850px;">
        <div id="loginArea" class="card p-5 text-center mx-auto" style="max-width: 400px;">
            <h6>Enter Officer ID</h6>
            <input type="text" id="oid" class="form-control mb-3 text-center">
            <button class="btn btn-success w-100" onclick="start()">Validate Access</button>
        </div>

        <div id="formArea" class="d-none">
            <div class="card p-4">
                <span class="section-label">1. Polling Unit Selection — <span class="text-success">Osun State</span></span>
                <div class="row g-2">
                    <!-- State is locked: hidden field, no dropdown shown -->
                    <div class="col-6"><select id="l" class="form-select" onchange="loadWards()"><option value="">LGA</option></select></div>
                    <div class="col-6"><select id="w" class="form-select" onchange="loadPUs()"><option value="">WARD</option></select></div>
                    <div class="col-12 mt-2"><select id="p" class="form-select" onchange="fillPU()"><option value="">SELECT POLLING UNIT</option></select></div>
                </div>
                <div class="row mt-3 g-2">
                    <div class="col-4"><small>Ward Code</small><input type="text" id="wc" class="form-control" readonly></div>
                    <div class="col-4"><small>PU Code</small><input type="text" id="pc" class="form-control" readonly></div>
                    <div class="col-4"><small>Location</small><input type="text" id="loc" class="form-control" readonly></div>
                </div>
            </div>

            <div class="card p-4">
                <span class="section-label">2. Official 14-Party Scorecard — 2026 Ọ̀sun Governorship</span>
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
        const FIXED_STATE = "Osun";
        let lat, lon, officerId, puData = [], wardData = [];

        function start() {{
            officerId = document.getElementById('oid').value;
            if(!officerId) return;
            document.getElementById('loginArea').classList.add('d-none');
            document.getElementById('formArea').classList.remove('d-none');
            // State is locked — load LGAs for Osun immediately
            loadLGAs();
        }}

        function loadLGAs() {{
            fetch('/api/lgas/' + encodeURIComponent(FIXED_STATE)).then(r=>r.json()).then(data=>{{
                const l = document.getElementById('l'); l.innerHTML = '<option value="">LGA</option>';
                data.forEach(item => l.add(new Option(item.toUpperCase(), item)));
            }});
        }}

        function loadWards() {{
            fetch(`/api/wards/${{encodeURIComponent(FIXED_STATE)}}/${{encodeURIComponent(document.getElementById('l').value)}}`).then(r=>r.json()).then(data=>{{
                wardData = data;
                const w = document.getElementById('w'); w.innerHTML = '<option value="">WARD</option>';
                data.forEach(item => w.add(new Option(item.name.toUpperCase(), item.name)));
            }});
        }}

        function loadPUs() {{
            const w = document.getElementById('w').value;
            const wardObj = wardData.find(x => x.name === w);
            document.getElementById('wc').value = wardObj ? wardObj.code : '';
            fetch(`/api/pus/${{encodeURIComponent(FIXED_STATE)}}/${{encodeURIComponent(document.getElementById('l').value)}}/${{encodeURIComponent(w)}}`).then(r=>r.json()).then(data=>{{
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
                officer_id: officerId, state: FIXED_STATE,
                lg: document.getElementById('l').value,
                ward: document.getElementById('w').value, ward_code: document.getElementById('wc').value,
                pu_code: document.getElementById('pc').value, location: document.getElementById('loc').value,
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

# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD — LOCKED TO OSUN, ALL 14 PARTIES
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    return DASHBOARD_HTML

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Accord Situation Room — Osun 2026</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css">
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.0.0"></script>
    
    <style>
        :root { --gold: #ffc107; --dark: #0a0a0a; --panel: #141414; }
        body { background-color: var(--dark); color: #fff; font-family: 'Segoe UI', sans-serif; overflow: hidden; height: 100vh; margin: 0; }
        
        .navbar-custom { background: #000; border-bottom: 2px solid var(--gold); padding: 10px 20px; display: flex; align-items: center; justify-content: space-between; }
        .brand-title { color: var(--gold); font-weight: 900; font-size: 1.1rem; letter-spacing: 1px; }
        .state-lock { color: #aaa; font-size: 0.65rem; margin-top: 2px; }
        
        .nav-kpi-group { display: flex; gap: 8px; flex-wrap: wrap; }
        .party-box { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 5px 10px; display: flex; align-items: center; gap: 6px; min-width: 100px; }
        .party-box img { height: 26px; width: 26px; object-fit: contain; }
        .party-info label { display: block; font-size: 0.58rem; color: #aaa; margin: 0; }
        .party-info span { font-size: 0.95rem; font-weight: bold; color: #fff; }
        
        /* Top-border colors for key parties */
        .box-A    { border-top: 3px solid #ffc107; }
        .box-APC  { border-top: 3px solid #0b3d91; }
        .box-NNPP { border-top: 3px solid #e65c00; }
        .box-ADC  { border-top: 3px solid #138808; }
        .box-PRP  { border-top: 3px solid #9b59b6; }
        .box-YPP  { border-top: 3px solid #e74c3c; }

        .main-content { display: grid; grid-template-columns: 320px 1fr 300px; height: calc(100vh - 80px); gap: 10px; padding: 10px; }
        .side-panel { background: var(--panel); border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; border: 1px solid #222; }
        .panel-header { background: #1c1c1c; padding: 10px 15px; font-size: 0.75rem; font-weight: bold; color: var(--gold); border-bottom: 1px solid #333; text-transform: uppercase; }
        
        .margin-card { background: #1e1e1e; border-radius: 8px; padding: 15px; text-align: center; margin: 10px; border: 1px solid #333; }
        .margin-val { font-size: 1.8rem; font-weight: 900; display: block; color: var(--gold); line-height: 1.2; }
        
        #map { height: 45%; border-radius: 12px; background: #111; margin-bottom: 10px; }
        .chart-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; flex: 1; min-height: 0; }
        .chart-box { background: #1a1a1a; border-radius: 12px; padding: 15px; border: 1px solid #222; position: relative; height: 100%; min-height: 300px; }

        .feed-container { flex: 1; overflow-y: auto; padding: 10px; }
        .pu-card { background: #1e1e1e; border-radius: 8px; padding: 10px; margin-bottom: 8px; border-left: 4px solid var(--gold); cursor: pointer; }
        .score-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; margin-top: 8px; font-size: 0.7rem; text-align: center; }

        .ai-box { background: #000; color: #0f0; font-family: monospace; padding: 12px; font-size: 0.75rem; border: 1px solid #030; flex: 1; margin: 10px; overflow-y: auto; }
        .filter-badge { background: #ffc10722; border: 1px solid #ffc107; color: #ffc107; font-size: 0.65rem; padding: 1px 6px; border-radius: 4px; }
    </style>
</head>
<body>

<nav class="navbar-custom">
    <div class="brand-section">
        <div class="brand-title">ACCORD SITUATION ROOM — OSUN 2026</div>
        <div class="d-flex align-items-center gap-2 mt-1">
            <span class="filter-badge">📍 OSUN STATE</span>
            <select id="fLGA" class="form-select form-select-sm bg-dark text-white border-secondary" style="width:120px;" onchange="updateWards()"><option value="">ALL LGAs</option></select>
            <select id="fWard" class="form-select form-select-sm bg-dark text-white border-secondary" style="width:120px;" onchange="applyFilters()"><option value="">ALL WARDS</option></select>
        </div>
    </div>

    <div class="nav-kpi-group">
        <div class="party-box box-A"><img src="/logos/A.png" onerror="this.style.display='none'"><div class="party-info"><label>ACCORD</label><span id="nav-A">0</span></div></div>
        <div class="party-box box-APC"><img src="/logos/APC.png" onerror="this.style.display='none'"><div class="party-info"><label>APC</label><span id="nav-APC">0</span></div></div>
        <div class="party-box box-NNPP"><img src="/logos/NNPP.png" onerror="this.style.display='none'"><div class="party-info"><label>NNPP</label><span id="nav-NNPP">0</span></div></div>
        <div class="party-box box-ADC"><img src="/logos/ADC.png" onerror="this.style.display='none'"><div class="party-info"><label>ADC</label><span id="nav-ADC">0</span></div></div>
        <div class="party-box box-PRP"><img src="/logos/PRP.png" onerror="this.style.display='none'"><div class="party-info"><label>PRP</label><span id="nav-PRP">0</span></div></div>
        <div class="party-box box-YPP"><img src="/logos/YPP.png" onerror="this.style.display='none'"><div class="party-info"><label>YPP</label><span id="nav-YPP">0</span></div></div>
    </div>

    <div>
        <a href="/export/csv" class="btn btn-sm btn-outline-warning py-1 px-3" style="font-size: 11px;">
            <i class="bi bi-download"></i> EXPORT CSV
        </a>
    </div>
</nav>

<div class="main-content">
    <div class="side-panel">
        <div class="panel-header">LIVE PU FEED <span id="pu-count" class="badge bg-warning text-dark ms-2">0</span></div>
        <div class="p-2"><input type="text" id="puSearch" class="form-control form-control-sm bg-dark text-white border-secondary" placeholder="Search PU..." oninput="renderFeed()"></div>
        <div class="feed-container" id="feedList"></div>
    </div>

    <div class="d-flex flex-column" style="min-height: 0;">
        <div id="map"></div>
        <div class="chart-row">
            <div class="chart-box"><canvas id="barChart"></canvas></div>
            <div class="chart-box"><canvas id="pieChart"></canvas></div>
        </div>
    </div>

    <div class="side-panel">
        <div class="panel-header">VOTE MARGIN ANALYSIS</div>
        <div class="margin-card">
            <small class="text-secondary">ACCORD LEAD/LAG</small>
            <span id="marginVal" class="margin-val">0</span>
            <small id="marginLead" class="fw-bold">AWAITING DATA</small>
        </div>
        
        <div class="panel-header">AI ANALYTICS LOG</div>
        <div class="ai-box" id="ai_box">System ready. Osun State locked. Waiting for live polling unit synchronization...</div>
        
        <div class="mt-auto p-3 border-top border-secondary">
            <button class="btn btn-warning btn-sm w-100 fw-bold" onclick="refreshData()">REFRESH ALL DATA</button>
        </div>
    </div>
</div>

<script>
    const OSUN_PARTIES = ["A","AA","AAC","ADC","ADP","APGA","APC","APM","APP","BP","NNPP","PRP","YPP","ZLP"];
    const PARTY_COLORS = {
        "A":"#ffc107","AA":"#e67e22","AAC":"#1abc9c","ADC":"#138808",
        "ADP":"#3498db","APGA":"#27ae60","APC":"#0b3d91","APM":"#8e44ad",
        "APP":"#c0392b","BP":"#16a085","NNPP":"#e65c00","PRP":"#9b59b6",
        "YPP":"#e74c3c","ZLP":"#2c3e50"
    };
    // KPI nav boxes shown on navbar
    const NAV_PARTIES = ["A","APC","NNPP","ADC","PRP","YPP"];

    let map, globalData = [], filterLookup = [], markers = [], pie, bar;
    Chart.register(ChartDataLabels);

    function init() {
        map = L.map('map', { zoomControl: false }).setView([7.56, 4.52], 9);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png').addTo(map);
        loadFilters();
        refreshData();
        setInterval(refreshData, 30000);
    }

    async function loadFilters() {
        try {
            const res = await fetch('/api/dashboard_filters');
            filterLookup = await res.json();
            // Only LGA and Ward filters (state is locked to Osun)
            const lgas = [...new Set(filterLookup.map(x => x.lg))].sort();
            const lEl = document.getElementById('fLGA');
            lgas.forEach(l => lEl.add(new Option(l.toUpperCase(), l)));
        } catch(e) { console.error("Filter load error", e); }
    }

    function updateWards() {
        const l = document.getElementById('fLGA').value;
        const wEl = document.getElementById('fWard'); wEl.innerHTML = '<option value="">ALL WARDS</option>';
        const wards = [...new Set(filterLookup.filter(x => x.lg === l).map(x => x.ward))].sort();
        wards.forEach(w => wEl.add(new Option(w.toUpperCase(), w)));
        applyFilters();
    }

    async function refreshData() {
        try {
            const res = await fetch('/submissions');
            globalData = await res.json();
            applyFilters();
        } catch(e) { console.error("Data refresh error", e); }
    }

    function applyFilters() {
        const l = document.getElementById('fLGA').value;
        const w = document.getElementById('fWard').value;
        let filtered = globalData;
        if(l) filtered = filtered.filter(x => x.lga === l);
        if(w) filtered = filtered.filter(x => x.ward === w);
        updateUI(filtered);
    }

    function updateUI(data) {
        // Tally all 14 parties
        let totals = {};
        OSUN_PARTIES.forEach(p => totals[p] = 0);

        const list = document.getElementById('feedList'); list.innerHTML = "";
        markers.forEach(m => map.removeLayer(m));
        markers = [];
        const searchVal = (document.getElementById('puSearch').value || "").toLowerCase();

        data.forEach(d => {
            OSUN_PARTIES.forEach(p => { totals[p] += (d[`votes_party_${p}`] || 0); });

            if(searchVal && !d.pu_name.toLowerCase().includes(searchVal)) return;

            const card = document.createElement('div');
            card.className = 'pu-card';
            const top4 = OSUN_PARTIES.slice(0,4);
            card.innerHTML = `<h6 style="font-size:0.78rem;margin:0">${d.pu_name}</h6>
                <div class="score-grid">${top4.map(p => `<div>${p}: <b>${d['votes_party_'+p]||0}</b></div>`).join('')}</div>`;
            card.onclick = () => { if(d.latitude) map.setView([d.latitude, d.longitude], 14); };
            list.appendChild(card);

            if(d.latitude) {
                const m = L.circleMarker([d.latitude, d.longitude], { radius: 6, color: '#ffc107', fillOpacity: 0.8 }).addTo(map);
                markers.push(m);
            }
        });

        // Update navbar KPI boxes
        NAV_PARTIES.forEach(p => {
            const el = document.getElementById('nav-'+p);
            if(el) el.innerText = (totals[p]||0).toLocaleString();
        });

        // Margin: Accord vs top rival
        const rivals = Object.fromEntries(OSUN_PARTIES.filter(p => p !== "A").map(p => [p, totals[p]]));
        const topRival = Object.keys(rivals).reduce((a, b) => rivals[a] > rivals[b] ? a : b);
        const margin = totals["A"] - rivals[topRival];

        const mValEl = document.getElementById('marginVal');
        if(mValEl) {
            mValEl.innerText = Math.abs(margin).toLocaleString();
            mValEl.style.color = margin >= 0 ? "#00ff00" : "#ff4444";
        }
        const mLeadEl = document.getElementById('marginLead');
        if(mLeadEl) mLeadEl.innerText = margin >= 0 ? `LEAD OVER ${topRival}` : `TRAILING ${topRival}`;

        document.getElementById('pu-count').innerText = data.length;

        updateCharts(totals);
        runAI(totals);
    }

    function updateCharts(totals) {
        const labels = OSUN_PARTIES;
        const vals = OSUN_PARTIES.map(p => totals[p]);
        const colors = OSUN_PARTIES.map(p => PARTY_COLORS[p]);
        const total = vals.reduce((a, b) => a + b, 0);

        if(pie) pie.destroy();
        pie = new Chart(document.getElementById('pieChart'), {
            type: 'doughnut',
            data: { labels, datasets: [{ data: vals, backgroundColor: colors, borderWidth: 0 }] },
            options: {
                maintainAspectRatio: false,
                layout: { padding: { bottom: 20 } },
                plugins: {
                    legend: { position: 'bottom', labels: { color: '#fff', font: { size: 9 }, padding: 8 } },
                    datalabels: {
                        color: '#fff',
                        font: { weight: 'bold', size: 10 },
                        formatter: (val) => {
                            if (total === 0 || val === 0) return '';
                            return ((val/total)*100).toFixed(1) + '%';
                        }
                    }
                }
            }
        });

        if(bar) bar.destroy();
        bar = new Chart(document.getElementById('barChart'), {
            type: 'bar',
            data: { labels, datasets: [{ data: vals, backgroundColor: colors }] },
            options: {
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    datalabels: {
                        color: '#fff', anchor: 'end', align: 'top',
                        font: { weight: 'bold', size: 9 },
                        formatter: (val) => val > 0 ? val.toLocaleString() : ''
                    }
                },
                scales: {
                    y: { beginAtZero: true, ticks: { color: '#fff', font: { size: 9 } }, grid: { color: '#222' } },
                    x: { ticks: { color: '#fff', font: { size: 9 } } }
                }
            }
        });
    }

    async function runAI(totals) {
        try {
            const payload = { ...totals, lg: document.getElementById('fLGA').value };
            const res = await fetch("/api/ai_interpret", {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const out = await res.json();
            const aiEl = document.getElementById('ai_box');
            if(aiEl) aiEl.innerText = out.analysis;
        } catch(e) {}
    }

    document.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>
"""
