import psycopg2
import shutil
import uuid
from psycopg2.extras import RealDictCursor
import os
import json
import logging
import io
import csv
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, Form
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
EC8E_PATH = os.path.join(os.getcwd(), "static", "ec8e")
os.makedirs(EC8E_PATH, exist_ok=True)
if os.path.exists(STATIC_PATH):
    app.mount("/static", StaticFiles(directory=STATIC_PATH), name="static")

# --- DATABASE CONNECTION ---
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://election_v3_db_user:KHjYceeGY0OL5w1RMhVFM18AyRipv9Tl@dpg-d6gnomfkijhs73f1cfe0-a.oregon-postgres.render.com/election_v3_db")

def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, sslmode='require')

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
@app.get("/api/validate_officer/{officer_id}")
def validate_officer(officer_id: str):
    """
    Officer ID format: {ward_code}-{pu_code}
    Validates the ID exists in the polling_units table for Osun State.
    Returns officer details on success, error on failure.
    """
    try:
        parts = officer_id.split("-", 1)
        if len(parts) != 2:
            return {"valid": False, "message": "Invalid ID format. Expected: WARDCODE-PUCODE"}
        ward_code, pu_code = parts[0].strip(), parts[1].strip()
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT ward, lg, location, pu_code, ward_code 
                       FROM polling_units 
                       WHERE state = 'osun' AND ward_code = %s AND pu_code = %s""",
                    (ward_code, pu_code)
                )
                row = cur.fetchone()
                if row:
                    return {
                        "valid": True,
                        "message": f"Access Granted: {row['location']}",
                        "ward": row["ward"],
                        "lg": row["lg"],
                        "location": row["location"],
                        "pu_code": row["pu_code"],
                        "ward_code": row["ward_code"]
                    }
                else:
                    return {"valid": False, "message": "Officer ID not found. Access Denied."}
    except Exception as e:
        return {"valid": False, "message": f"Validation error: {str(e)}"}



@app.get("/api/states")
def get_states():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT state FROM polling_units WHERE state = 'osun' ORDER BY state")
            rows = cur.fetchall()
            return [r["state"] for r in rows]

@app.get("/api/lgas/{state}")
def get_lgas(state: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT lg FROM polling_units WHERE state = 'osun' ORDER BY lg")
            rows = cur.fetchall()
            return [r["lg"] for r in rows]

@app.get("/api/wards/{state}/{lg}")
def get_wards(state: str, lg: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT ward, ward_code FROM polling_units WHERE state = 'osun' AND lg = %s ORDER BY ward", (lg,))
            rows = cur.fetchall()
            return [{"name": r["ward"], "code": r["ward_code"]} for r in rows]

@app.get("/api/pus/{state}/{lg}/{ward}")
def get_pus(state: str, lg: str, ward: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT location, pu_code FROM polling_units WHERE state = 'osun' AND lg = %s AND ward = %s", (lg, ward))
            rows = cur.fetchall()
            return [{"location": r["location"], "pu_code": r["pu_code"]} for r in rows]

@app.post("/submit")
async def submit(
    data: str = Form(...),
    ec8e_image: UploadFile = File(None)
):
    try:
        payload = json.loads(data)
        votes_json = json.dumps(payload.get("votes", {}))
        ec8e_filename = None
        if ec8e_image and ec8e_image.filename:
            ext = os.path.splitext(ec8e_image.filename)[1].lower()
            safe_pu = str(payload.get("pu_code", "unk")).replace("/", "_").replace(" ", "_")
            ec8e_filename = f"{safe_pu}_{uuid.uuid4().hex[:8]}{ext}"
            with open(os.path.join(EC8E_PATH, ec8e_filename), "wb") as img_f:
                shutil.copyfileobj(ec8e_image.file, img_f)
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO field_submissions (
                    officer_id, state, lg, ward, ward_code, pu_code, location,
                    reg_voters, total_accredited, valid_votes, rejected_votes, total_cast,
                    lat, lon, timestamp, votes_json, ec8e_image
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (
                    payload.get("officer_id"), payload.get("state"), payload.get("lg"),
                    payload.get("ward"), payload.get("ward_code"), payload.get("pu_code"),
                    payload.get("location"), payload.get("reg_voters"), payload.get("total_accredited"),
                    payload.get("valid_votes"), payload.get("rejected_votes"), payload.get("total_cast"),
                    payload.get("lat"), payload.get("lon"),
                    datetime.now().isoformat(), votes_json, ec8e_filename
                ))
                conn.commit()
        return {"status": "success", "message": "Result Uploaded Successfully"}
    except psycopg2.IntegrityError:
        return {"status": "error", "message": "REJECTED: A submission for this Polling Unit already exists."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
@app.post("/api/ai_interpret")
async def ai_interpret(data: dict):
    # 1. OSUN STATE ELECTORAL BASELINE (Official Stats)
    STATS = {
        "lgas": 30,
        "wards": 332,
        "pus": 3763,
        "urban_hubs": ["OSOGBO", "OLORUNDA", "ILESA EAST", "IFE CENTRAL", "IWO"]
    }

    # 2. Extract Data from Dashboard — 14 Osun parties
    OSUN_PARTIES_AI = ["ACCORD", "AA", "AAC", "ADC", "ADP", "APGA", "APC", "APM", "APP", "BP", "NNPP", "PRP", "YPP", "ZLP"]
    party_votes = {p: data.get(p, 0) for p in OSUN_PARTIES_AI}
    acc = party_votes["ACCORD"]
    rivals = {p: v for p, v in party_votes.items() if p != "ACCORD"}

    ta = data.get('total_accredited', 0)
    rv = data.get('reg_voters', 0)
    current_lg = str(data.get('lg', "")).upper()

    total_votes = sum(party_votes.values())
    if total_votes == 0:
        return {"analysis": "SYSTEM READY: Awaiting live feed from 3,763 Polling Units across Osun State."}

    # 3. Statistical Calculations
    share = (acc / total_votes) * 100
    top_rival = max(rivals, key=rivals.get)
    margin = acc - rivals[top_rival]
    turnout = (ta / rv * 100) if rv > 0 else 0
    
    # 4. Intelligence Logic
    is_urban = current_lg in STATS["urban_hubs"]
    
    # Determine the "Trend"
    if share > 55:
        trend = "LANDSLIDE"
    elif share > 40:
        trend = "STRONG LEAD"
    else:
        trend = "BATTLEGROUND"

    # 5. Generate Advanced Analysis String
    location_tag = " [URBAN HUB]" if is_urban else " [RURAL SECTOR]"
    
    analysis = (
        f"OSUN STATISTICAL AUDIT ({current_lg}{location_tag}): "
        f"Accord is in a {trend} position with {share:.1f}% of the current tally. "
        f"Lead Margin over {top_rival}: **{margin:+,}** votes. "
    )

    # Add Turnout Analytics
    if turnout > 0:
        analysis += f"Voter Productivity is at **{turnout:.1f}%**. "
        if turnout > 65:
            analysis += "⚠️ ALERT: Unusually high turnout detected; verify PU logs. "

    # Add Strategic Guidance
    if is_urban and share < 45:
        analysis += "STRATEGY: Increase urban mobilization; Osogbo/Iwo volume is critical."
    elif not is_urban and share > 50:
        analysis += "STRATEGY: Rural stronghold confirmed. Protect the lead during collation."

    return {
        "analysis": analysis,
        "is_alert": turnout > 70 or margin < 100,
        "stats": {
            "turnout_gap": 100 - turnout,
            "osun_progress": f"Active in {STATS['lgas']} LGAs"
        }
    }

@app.get("/api/dashboard_filters")
def get_dash_filters():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT state, lg, ward FROM polling_units WHERE state = 'osun' ORDER BY lg, ward")
            return cur.fetchall()

@app.get("/export/csv")
async def export_csv():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM field_submissions WHERE state = 'osun' ORDER BY timestamp DESC")
            rows = cur.fetchall()
            output = io.StringIO()
            writer = csv.writer(output)
            parties = ["ACCORD", "AA", "AAC", "ADC", "ADP", "APGA", "APC", "APM", "APP", "BP", "NNPP", "PRP", "YPP", "ZLP"]
            header = ["Timestamp", "Officer ID", "State", "LGA", "Ward", "PU Code", "Location", "Accredited", "Total Cast"] + parties
            writer.writerow(header)
            for r in rows:
                v = json.loads(r['votes_json']) if isinstance(r['votes_json'], str) else r['votes_json']
                row_data = [r['timestamp'], r['officer_id'], r['state'], r['lg'], r['ward'], r['pu_code'], r['location'], r['total_accredited'], r['total_cast']]
                for p in parties:
                    row_data.append(v.get(p, 0))
                writer.writerow(row_data)
            output.seek(0)
            return StreamingResponse(output, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=election_audit_full.csv"})

@app.get("/submissions")
async def get_dashboard_data():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM field_submissions WHERE state = 'osun' ORDER BY timestamp DESC")
            rows = cur.fetchall()
            data = []
            for r in rows:
                v = json.loads(r['votes_json']) if isinstance(r['votes_json'], str) else r['votes_json']
                ec8e_url = f"/static/ec8e/{r['ec8e_image']}" if r.get('ec8e_image') else None
                entry = {
                    "pu_name": r['location'], "state": r['state'], "lga": r['lg'], "ward": r['ward'],
                    "latitude": r['lat'], "longitude": r['lon'],
                    "ec8e_image": ec8e_url
                }
                for p in ["ACCORD","AA","AAC","ADC","ADP","APGA","APC","APM","APP","BP","NNPP","PRP","YPP","ZLP"]:
                    entry[f"votes_party_{p}"] = v.get(p, 0)
                data.append(entry)
            return data
@app.get("/", response_class=HTMLResponse)
async def index():
    parties = ["ACCORD", "AA", "AAC", "ADC", "ADP", "APGA", "APC", "APM", "APP", "BP", "NNPP", "PRP", "YPP", "ZLP"]
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
                <span class="section-label">2. Official 14-Party Scorecard — 2026 Ọàsun Governorship</span>
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
            <div class="card mb-3">
                <div class="card-body p-3">
                    <span class="section-label">4. EC 8E FORM IMAGE UPLOAD</span>
                    <div class="mt-2">
                        <label class="form-label small text-muted mb-1">Attach a clear photo of the signed EC 8E form (optional)</label>
                        <input type="file" id="ec8eFile" accept="image/*" capture="environment" class="form-control form-control-sm bg-dark text-white border-secondary">
                        <div id="ec8ePreview" class="mt-2 text-center d-none">
                            <img id="ec8eImg" src="#" alt="EC8E Preview" style="max-width:100%;max-height:200px;border-radius:8px;border:1px solid #ffc107;">
                        </div>
                    </div>
                </div>
            </div>
            <button class="btn btn-success btn-lg w-100 py-3 fw-bold" onclick="reviewSubmission()">UPLOAD PU RESULT</button>
        </div>
    </div>

    <!-- Confirmation Modal -->
    <div class="modal fade" id="confirmModal" tabindex="-1">
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content" style="background:#1a1a1a;color:#fff;border:1px solid #ffc107;">
          <div class="modal-header" style="border-bottom:1px solid #333;">
            <h6 class="modal-title text-warning fw-bold">⚠️ CONFIRM RESULT SUBMISSION</h6>
          </div>
          <div class="modal-body">
            <div id="confirmPUInfo" class="mb-3 p-2 rounded" style="background:#111;font-size:0.8rem;"></div>
            <table class="table table-sm table-dark table-bordered mb-2" style="font-size:0.8rem;">
              <thead><tr><th>Party</th><th class="text-end">Votes</th></tr></thead>
              <tbody id="confirmPartyRows"></tbody>
            </table>
            <div id="confirmAuditRows" class="p-2 rounded" style="background:#111;font-size:0.8rem;"></div>
          </div>
          <div class="modal-footer" style="border-top:1px solid #333;">
            <button type="button" class="btn btn-outline-secondary btn-sm" data-bs-dismiss="modal">← EDIT</button>
            <button type="button" class="btn btn-success btn-sm fw-bold" onclick="confirmAndSubmit()">✅ CONFIRM & SUBMIT</button>
          </div>
        </div>
      </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>

    <script>
        let lat, lon, officerId, puData = [], wardData = [], pendingPayload = null;
        async function start() {{
            const rawId = document.getElementById('oid').value.trim();
            if(!rawId) return;
            const btn = document.querySelector('#loginArea button');
            btn.disabled = true; btn.innerText = 'Validating...';
            try {{
                const res = await fetch('/api/validate_officer/' + encodeURIComponent(rawId));
                const out = await res.json();
                if(!out.valid) {{
                    document.getElementById('loginError').innerText = out.message;
                    document.getElementById('loginError').classList.remove('d-none');
                    btn.disabled = false; btn.innerText = 'Validate Access';
                    return;
                }}
                officerId = rawId;
                document.getElementById('loginArea').classList.add('d-none');
                document.getElementById('formArea').classList.remove('d-none');
                fetch('/api/states').then(r=>r.json()).then(data=>{{
                    const s = document.getElementById('s');
                    data.forEach(item => s.add(new Option(item.toUpperCase(), item)));
                }});
            }} catch(e) {{
                document.getElementById('loginError').innerText = 'Server error. Try again.';
                document.getElementById('loginError').classList.remove('d-none');
                btn.disabled = false; btn.innerText = 'Validate Access';
            }}
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
        document.getElementById('ec8eFile').addEventListener('change', function() {{
            const file = this.files[0];
            if (file) {{
                const reader = new FileReader();
                reader.onload = e => {{
                    document.getElementById('ec8eImg').src = e.target.result;
                    document.getElementById('ec8ePreview').classList.remove('d-none');
                }};
                reader.readAsDataURL(file);
            }}
        }});

        async function reviewSubmission() {{
            if(!lat) return alert("Please Fix GPS first");
            const v = {{}};
            document.querySelectorAll('.party-v').forEach(i => v[i.dataset.p] = parseInt(i.value || 0));
            pendingPayload = {{
                officer_id: officerId, state: document.getElementById('s').value, lg: document.getElementById('l').value,
                ward: document.getElementById('w').value, ward_code: document.getElementById('wc').value,
                pu_code: document.getElementById('pc').value, location: document.getElementById('loc').value,
                reg_voters: parseInt(document.getElementById('rv').value || 0), total_accredited: parseInt(document.getElementById('ta').value || 0),
                valid_votes: parseInt(document.getElementById('vv').value || 0), rejected_votes: parseInt(document.getElementById('rj').value || 0),
                total_cast: parseInt(document.getElementById('tc').value || 0), lat, lon, votes: v
            }};
            // Build confirmation modal content
            document.getElementById('confirmPUInfo').innerHTML =
                `<b>📍 PU:</b> ${{pendingPayload.location}}<br>` +
                `<b>🗳 Ward:</b> ${{pendingPayload.ward}} &nbsp;|&nbsp; <b>LGA:</b> ${{pendingPayload.lg}}<br>` +
                `<b>🔑 PU Code:</b> ${{pendingPayload.pu_code}} &nbsp;|&nbsp; <b>Officer:</b> ${{pendingPayload.officer_id}}`;
            const tbody = document.getElementById('confirmPartyRows');
            tbody.innerHTML = '';
            Object.entries(v).forEach(([p, score]) => {{
                const tr = document.createElement('tr');
                tr.innerHTML = `<td>${{p}}</td><td class="text-end fw-bold ${{score > 0 ? 'text-warning' : 'text-secondary'}}">${{score}}</td>`;
                tbody.appendChild(tr);
            }});
            document.getElementById('confirmAuditRows').innerHTML =
                `<b>Registered:</b> ${{pendingPayload.reg_voters}} &nbsp;|&nbsp; ` +
                `<b>Accredited:</b> ${{pendingPayload.total_accredited}} &nbsp;|&nbsp; ` +
                `<b>Valid:</b> ${{pendingPayload.valid_votes}} &nbsp;|&nbsp; ` +
                `<b>Rejected:</b> ${{pendingPayload.rejected_votes}} &nbsp;|&nbsp; ` +
                `<b>Total Cast:</b> ${{pendingPayload.total_cast}}`;
            new bootstrap.Modal(document.getElementById('confirmModal')).show();
        }}

        async function confirmAndSubmit() {{
            const btn = document.querySelector('#confirmModal .btn-success');
            btn.disabled = true; btn.innerText = 'Submitting...';
            const fd = new FormData();
            fd.append('data', JSON.stringify(pendingPayload));
            const ec8eInput = document.getElementById('ec8eFile');
            if (ec8eInput && ec8eInput.files[0]) {{ fd.append('ec8e_image', ec8eInput.files[0]); }}
            const res = await fetch('/submit', {{ method: 'POST', body: fd }});
            const out = await res.json();
            bootstrap.Modal.getInstance(document.getElementById('confirmModal')).hide();
            alert(out.message);
            if(out.status === 'success') location.reload();
            else {{ btn.disabled = false; btn.innerText = '✅ CONFIRM & SUBMIT'; }}
        }}
    </script>
</body>
</html>
"""
# --- DASHBOARD PAGE ---
# --- DASHBOARD PAGE ---

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    return DASHBOARD_HTML

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Accord Situation Room — Osun 2026 LIVE</title>
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
        
        .nav-kpi-group { display: flex; gap: 10px; }
        .party-box { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 5px 12px; display: flex; align-items: center; gap: 8px; min-width: 120px; }
        .party-box img { height: 30px; width: 30px; object-fit: contain; }
        .party-info label { display: block; font-size: 0.6rem; color: #aaa; margin: 0; }
        .party-info span { font-size: 1rem; font-weight: bold; color: #fff; }
        
        .box-accord { border-top: 3px solid var(--gold); }
        .box-apc { border-top: 3px solid #0b3d91; }
        .box-pdp { border-top: 3px solid #d9534f; }
        .box-adc { border-top: 3px solid #138808; }

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
        .score-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 5px; margin-top: 8px; font-size: 0.75rem; text-align: center; }

        .ai-box { background: #000; color: #0f0; font-family: monospace; padding: 12px; font-size: 0.75rem; border: 1px solid #030; flex: 1; margin: 10px; overflow-y: auto; }
    </style>
</head>
<body>

<nav class="navbar-custom">
    <div class="brand-section">
        <div class="brand-title">ACCORD SITUATION ROOM — OSUN 2026</div>
        <div class="d-flex gap-2 mt-1">
            <select id="fState" class="form-select form-select-sm bg-dark text-white border-secondary" style="width:105px;" onchange="updateLGAs()"><option value="">STATE</option></select>
            <select id="fLGA" class="form-select form-select-sm bg-dark text-white border-secondary" style="width:105px;" onchange="updateWards()"><option value="">LGA</option></select>
            <select id="fWard" class="form-select form-select-sm bg-dark text-white border-secondary" style="width:105px;" onchange="applyFilters()"><option value="">WARD</option></select>
        </div>
    </div>

    <div class="nav-kpi-group">
        <div class="party-box box-accord"><img src="/logos/ACCORD.png"><div class="party-info"><label>ACCORD</label><span id="nav-ACCORD">0</span></div></div>
        <div class="party-box box-apc"><img src="/logos/APC.png"><div class="party-info"><label>APC</label><span id="nav-APC">0</span></div></div>
        <div class="party-box box-adc"><img src="/logos/ADC.png"><div class="party-info"><label>ADC</label><span id="nav-ADC">0</span></div></div>
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
        <div class="ai-box" id="ai_box">System ready. Waiting for live polling unit synchronization...</div>
        
        <div class="mt-auto p-3 border-top border-secondary">
            <button class="btn btn-warning btn-sm w-100 fw-bold" onclick="refreshData()">REFRESH ALL DATA</button>
        </div>
    </div>
</div>

<script>
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
            const states = [...new Set(filterLookup.map(x => x.state))];
            const sEl = document.getElementById('fState');
            states.forEach(s => sEl.add(new Option(s.toUpperCase(), s)));
        } catch(e) { console.error("Filter load error", e); }
    }

    function updateLGAs() {
        const s = document.getElementById('fState').value;
        const lEl = document.getElementById('fLGA'); lEl.innerHTML = '<option value="">LGA</option>';
        const lgas = [...new Set(filterLookup.filter(x => x.state === s).map(x => x.lg))];
        lgas.forEach(l => lEl.add(new Option(l.toUpperCase(), l)));
        applyFilters();
    }

    function updateWards() {
        const s = document.getElementById('fState').value;
        const l = document.getElementById('fLGA').value;
        const wEl = document.getElementById('fWard'); wEl.innerHTML = '<option value="">WARD</option>';
        const wards = [...new Set(filterLookup.filter(x => x.state === s && x.lg === l).map(x => x.ward))];
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
        const s = document.getElementById('fState').value;
        const l = document.getElementById('fLGA').value;
        const w = document.getElementById('fWard').value;
        let filtered = globalData;
        if(s) filtered = filtered.filter(x => x.state === s);
        if(l) filtered = filtered.filter(x => x.lga === l);
        if(w) filtered = filtered.filter(x => x.ward === w);
        updateUI(filtered);
    }

    function updateUI(data) {
        const PARTIES = ['ACCORD','AA','AAC','ADC','ADP','APGA','APC','APM','APP','BP','NNPP','PRP','YPP','ZLP'];
        let t = {};
        PARTIES.forEach(p => t[p] = 0);
        const list = document.getElementById('feedList'); list.innerHTML = "";
        markers.forEach(m => map.removeLayer(m));
        markers = [];

        data.forEach(d => {
            PARTIES.forEach(p => { t[p] += (d['votes_party_'+p] || 0); });

            const card = document.createElement('div');
            card.className = 'pu-card';
            card.innerHTML = `<h6 style="font-size:0.8rem;margin:0 0 4px">${d.pu_name}</h6>
                <div style="font-size:0.72rem;color:#aaa">${d.lga} &rsaquo; ${d.ward}</div>
                <div class="score-grid">
                    <div>ACCORD: <b style="color:#ffc107">${d.votes_party_ACCORD||0}</b></div>
                    <div>APC: ${d.votes_party_APC||0}</div>
                    <div>NNPP: ${d.votes_party_NNPP||0}</div>
                    <div>ADC: ${d.votes_party_ADC||0}</div>
                </div>`;
            card.onclick = () => { if(d.latitude) map.setView([d.latitude, d.longitude], 14); };
            list.appendChild(card);

            if(d.latitude) {
                const m = L.circleMarker([d.latitude, d.longitude], { radius: 6, color: '#ffc107', fillOpacity: 0.8 }).addTo(map);
                markers.push(m);
            }
        });

        ['ACCORD', 'APC', 'ADC'].forEach(p => {
            const el = document.getElementById('nav-'+p);
            if(el) el.innerText = t[p].toLocaleString();
        });
        
        const rivals = {};
        PARTIES.filter(p => p !== 'ACCORD').forEach(p => rivals[p] = t[p]);
        const topRival = Object.keys(rivals).reduce((a, b) => rivals[a] > rivals[b] ? a : b);
        const margin = t.ACCORD - rivals[topRival];
        
        const mValEl = document.getElementById('marginVal');
        if(mValEl) {
            mValEl.innerText = Math.abs(margin).toLocaleString();
            mValEl.style.color = margin >= 0 ? "#00ff00" : "#ff4444";
        }
        const mLeadEl = document.getElementById('marginLead');
        if(mLeadEl) mLeadEl.innerText = margin >= 0 ? `LEAD OVER ${topRival}` : `TRAILING ${topRival}`;
        
        const pCountEl = document.getElementById('pu-count');
        if(pCountEl) pCountEl.innerText = data.length;

        updateCharts(t);
        runAI(t);
    }

    function updateCharts(t) {
        const labels = ['ACCORD', 'APC', 'ADC'];
        const vals = labels.map(p => t[p] || 0);
        const colors = ['#ffc107','#0b3d91','#138808'];
        const total = vals.reduce((a, b) => a + b, 0);

        if(pie) pie.destroy();
        pie = new Chart(document.getElementById('pieChart'), {
            type: 'doughnut',
            data: { labels, datasets: [{ data: vals, backgroundColor: colors, borderWidth: 0 }] },
            options: {
                maintainAspectRatio: false,
                layout: { padding: { bottom: 20 } },
                plugins: {
                    legend: { 
                        position: 'bottom', 
                        labels: { color: '#fff', font: { size: 10 }, padding: 10 } 
                    },
                    datalabels: {
                        color: '#fff',
                        font: { weight: 'bold', size: 11 },
                        formatter: (val) => {
                            if (total === 0) return '';
                            return val > 0 ? ((val/total)*100).toFixed(1) + '%' : '';
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
                        color: '#fff',
                        anchor: 'end',
                        align: 'top',
                        font: { weight: 'bold' },
                        formatter: (val) => val > 0 ? val.toLocaleString() : ''
                    }
                },
                scales: {
                    y: { beginAtZero: true, ticks: { color: '#fff', font: { size: 9 } }, grid: { color: '#222' } },
                    x: { ticks: { color: '#fff', font: { size: 10 } } }
                }
            }
        });
    }

    async function runAI(totals) {
        try {
            const s = document.getElementById('fState').value;
            const l = document.getElementById('fLGA').value;
            const payload = Object.assign({}, totals, { lg: l || 'ALL', state: s || 'Osun' });
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

<!-- ── EC8E Lightbox ── -->
<div id="ec8eLightbox" style="display:none;position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,0.96);align-items:center;justify-content:center;" onclick="this.style.display='none'">
  <img id="ec8eLightboxImg" src="#" style="max-width:95vw;max-height:95vh;border-radius:8px;border:2px solid #ffc107;">
</div>

<!-- ── Maximize Overlays ── -->
<style>
.ov-overlay{display:none;position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.92);align-items:center;justify-content:center;}
.ov-overlay.active{display:flex;}
.ov-inner{background:#1a1a1a;border:1px solid #ffc107;border-radius:12px;padding:20px;width:95vw;max-height:92vh;overflow-y:auto;position:relative;}
.ov-close{position:absolute;top:10px;right:14px;background:none;border:none;color:#ffc107;font-size:1.4rem;cursor:pointer;}
.ov-btn{background:rgba(255,193,7,0.15);border:1px solid #ffc107;color:#ffc107;border-radius:4px;padding:1px 6px;font-size:0.75rem;cursor:pointer;margin-left:6px;}
.ov-btn:hover{background:rgba(255,193,7,0.35);}
</style>

<div id="ov-feed"   class="ov-overlay"><div class="ov-inner"><button class="ov-close" onclick="closeOverlay('ov-feed')">✕</button><h5 style="color:#ffc107">LIVE PU FEED</h5><div id="ov-feed-inner"></div></div></div>
<div id="ov-map"    class="ov-overlay"><div class="ov-inner" style="height:88vh;"><button class="ov-close" onclick="closeOverlay('ov-map')">✕</button><h5 style="color:#ffc107">MAP</h5><div id="ov-map-inner" style="height:80vh;border-radius:8px;overflow:hidden;"></div></div></div>
<div id="ov-bar"    class="ov-overlay"><div class="ov-inner"><button class="ov-close" onclick="closeOverlay('ov-bar')">✕</button><h5 style="color:#ffc107">BAR CHART</h5><canvas id="ov-barChart" height="300"></canvas></div></div>
<div id="ov-pie"    class="ov-overlay"><div class="ov-inner"><button class="ov-close" onclick="closeOverlay('ov-pie')">✕</button><h5 style="color:#ffc107">PIE CHART</h5><canvas id="ov-pieChart" height="300"></canvas></div></div>
<div id="ov-margin" class="ov-overlay"><div class="ov-inner"><button class="ov-close" onclick="closeOverlay('ov-margin')">✕</button><h5 style="color:#ffc107">VOTE MARGIN</h5><div style="font-size:2rem;color:#ffc107;text-align:center;padding:30px 0;" id="ov-marginVal">—</div><div style="text-align:center;color:#aaa;" id="ov-marginLead"></div></div></div>
<div id="ov-ai"     class="ov-overlay"><div class="ov-inner"><button class="ov-close" onclick="closeOverlay('ov-ai')">✕</button><h5 style="color:#ffc107">AI ANALYTICS LOG</h5><pre id="ov-ai-inner" style="color:#ccc;white-space:pre-wrap;font-size:0.82rem;"></pre></div></div>
<div id="ov-ec8e"   class="ov-overlay"><div class="ov-inner" style="text-align:center;"><button class="ov-close" onclick="closeOverlay('ov-ec8e')">✕</button><h5 style="color:#ffc107">EC 8E FORM VIEWER</h5><div id="ov-ec8e-inner"></div></div></div>

<script>
function openOverlay(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.add("active");

    if (id === "ov-feed") {
        const src = document.getElementById("feedList");
        const dst = document.getElementById("ov-feed-inner");
        if (src && dst) dst.innerHTML = src.innerHTML;
    }
    if (id === "ov-map") {
        const dst = document.getElementById("ov-map-inner");
        if (dst && !dst._ovMap) {
            dst._ovMap = L.map(dst, { zoomControl: true }).setView([7.56, 4.52], 9);
            L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png").addTo(dst._ovMap);
            window._ovMapInst = dst._ovMap;
        }
        setTimeout(() => { if (dst._ovMap) dst._ovMap.invalidateSize(); }, 200);
    }
    if (id === "ov-bar" || id === "ov-pie") {
        const PARTIES = ["ACCORD","AA","AAC","ADC","ADP","APGA","APC","APM","APP","BP","NNPP","PRP","YPP","ZLP"];
        const colors  = ["#ffc107","#6c757d","#17a2b8","#138808","#fd7e14","#6f42c1","#0b3d91","#20c997","#e83e8c","#dc3545","#0dcaf0","#198754","#ffc0cb","#ff6b35"];
        const vals    = PARTIES.map(p => { const el = document.getElementById("nav-"+p); return el ? parseInt(el.innerText.replace(/,/g,""))||0 : 0; });
        if (id === "ov-bar") {
            if (window._ovBar) window._ovBar.destroy();
            window._ovBar = new Chart(document.getElementById("ov-barChart"), {
                type: "bar",
                data: { labels: PARTIES, datasets: [{ data: vals, backgroundColor: colors }] },
                options: { maintainAspectRatio: false, plugins: { legend: { display: false }, datalabels: { color: "#fff", anchor: "end", align: "top", formatter: v => v > 0 ? v.toLocaleString() : "" } }, scales: { y: { beginAtZero: true, ticks: { color: "#fff" }, grid: { color: "#222" } }, x: { ticks: { color: "#fff", font: { size: 9 } } } } }
            });
        }
        if (id === "ov-pie") {
            const total = vals.reduce((a,b)=>a+b,0);
            if (window._ovPie) window._ovPie.destroy();
            window._ovPie = new Chart(document.getElementById("ov-pieChart"), {
                type: "doughnut",
                data: { labels: PARTIES, datasets: [{ data: vals, backgroundColor: colors, borderWidth: 0 }] },
                options: { maintainAspectRatio: false, plugins: { legend: { position: "bottom", labels: { color: "#fff", font: { size: 10 } } }, datalabels: { color: "#fff", font: { weight: "bold" }, formatter: v => total > 0 && v > 0 ? ((v/total)*100).toFixed(1)+"%" : "" } } }
            });
        }
    }
    if (id === "ov-margin") {
        const v = document.getElementById("marginVal");
        const l = document.getElementById("marginLead");
        if (v) { document.getElementById("ov-marginVal").innerText = v.innerText; document.getElementById("ov-marginVal").style.color = v.style.color; }
        if (l) document.getElementById("ov-marginLead").innerText = l.innerText;
    }
    if (id === "ov-ai") {
        const src = document.getElementById("ai_box");
        if (src) document.getElementById("ov-ai-inner").innerText = src.innerText;
    }
    if (id === "ov-ec8e") {
        const src = document.getElementById("ec8eViewerPanel");
        if (src) document.getElementById("ov-ec8e-inner").innerHTML = src.innerHTML;
    }
}

function closeOverlay(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove("active");
}

function openEc8eLightbox(url) {
    document.getElementById("ec8eLightboxImg").src = url;
    document.getElementById("ec8eLightbox").style.display = "flex";
}

function showEc8e(url, puName) {
    const panel = document.getElementById("ec8eViewerPanel");
    if (!panel) return;
    if (url) {
        panel.innerHTML = "<div style=\"font-size:0.75rem;color:#aaa;margin-bottom:6px;\">" + puName + "</div><img src=\"" + url + "\" style=\"max-width:100%;border-radius:6px;border:1px solid #ffc107;cursor:pointer;\" onclick=\"openEc8eLightbox(this.src)\">";
    } else {
        panel.innerHTML = "<span style=\"color:#555;font-size:0.75rem;font-style:italic;\">No EC 8E image for this polling unit</span>";
    }
}

// Inject ⛶ buttons and EC8E panel after DOM loads
document.addEventListener("DOMContentLoaded", function() {
    // EC8E viewer panel in right sidebar
    const rightPanel = document.querySelector(".side-panel:last-of-type");
    if (rightPanel) {
        const refreshBtn = rightPanel.querySelector(".mt-auto");
        const ec8eDiv = document.createElement("div");
        ec8eDiv.innerHTML = "<div class=\"panel-header\">EC 8E FORM VIEWER <button class=\"ov-btn\" onclick=\"openOverlay('ov-ec8e')\">⛶</button></div><div id=\"ec8eViewerPanel\" style=\"background:#111;border-radius:8px;padding:10px;margin:8px;border:1px solid #333;text-align:center;min-height:60px;\"><span style=\"color:#555;font-size:0.75rem;font-style:italic;\">Click a polling unit to view its EC 8E form</span></div>";
        rightPanel.insertBefore(ec8eDiv, refreshBtn || null);
    }
    // ⛶ buttons on panel headers
    [["LIVE PU FEED","ov-feed"],["VOTE MARGIN","ov-margin"],["AI ANALYTICS","ov-ai"]].forEach(function(pair) {
        document.querySelectorAll(".panel-header").forEach(function(h) {
            if (h.textContent.includes(pair[0]) && !h.querySelector(".ov-btn")) {
                const b = document.createElement("button"); b.className = "ov-btn"; b.innerText = "⛶"; b.onclick = function(){ openOverlay(pair[1]); }; h.appendChild(b);
            }
        });
    });
    // ⛶ on chart boxes
    document.querySelectorAll(".chart-box").forEach(function(box, i) {
        const ids = ["ov-bar","ov-pie"];
        if (!ids[i]) return;
        const b = document.createElement("button"); b.className = "ov-btn"; b.style.cssText = "position:absolute;top:6px;right:8px;z-index:10;"; b.innerText = "⛶"; b.onclick = function(){ openOverlay(ids[i]); }; box.style.position = "relative"; box.appendChild(b);
    });
    // ⛶ on map
    const mapEl = document.getElementById("map");
    if (mapEl) {
        const b = document.createElement("button"); b.className = "ov-btn"; b.style.cssText = "position:absolute;top:8px;right:8px;z-index:1000;"; b.innerText = "⛶"; b.onclick = function(){ openOverlay("ov-map"); }; mapEl.style.position = "relative"; mapEl.appendChild(b);
    }
});

// Esc key closes all overlays
document.addEventListener("keydown", function(e) {
    if (e.key === "Escape") {
        ["ov-bar","ov-pie","ov-map","ov-feed","ov-margin","ov-ai","ov-ec8e"].forEach(function(id){ closeOverlay(id); });
        document.getElementById("ec8eLightbox").style.display = "none";
    }
});
</script>

</body>
</html>
"""
