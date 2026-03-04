import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json
import logging
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import io
import csv

app = FastAPI()

# --- DATABASE CONNECTION ---
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://election_v3_db_user:KHjYceeGY0OL5w1RMhVFM18AyRipv9Tl@dpg-d6gnomfkijhs73f1cfe0-a.oregon-postgres.render.com/election_v3_db")

def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# --- API ENDPOINTS ---

@app.get("/api/states")
def get_states():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT state FROM polling_units ORDER BY state")
            return [r["state"] for r in cur.fetchall()]

@app.get("/api/lgas/{{state}}")
def get_lgas(state: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT lg FROM polling_units WHERE state = %s ORDER BY lg", (state,))
            return [r["lg"] for r in cur.fetchall()]

@app.get("/api/wards/{{state}}/{{lg}}")
def get_wards(state: str, lg: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT ward, ward_code FROM polling_units WHERE state = %s AND lg = %s ORDER BY ward", (state, lg))
            return [{"name": r["ward"], "code": r["ward_code"]} for r in cur.fetchall()]

@app.get("/api/pus/{{state}}/{{lg}}/{{ward}}")
def get_pus(state: str, lg: str, ward: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT location, pu_code FROM polling_units WHERE state = %s AND lg = %s AND ward = %s", (state, lg, ward))
            return [{"location": r["location"], "pu_code": r["pu_code"]} for r in cur.fetchall()]

@app.get("/api/dashboard_filters")
def get_dashboard_filters():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT state, lg, ward FROM polling_units ORDER BY state, lg, ward")
            return cur.fetchall()

@app.get("/submissions")
async def get_submissions():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM field_submissions ORDER BY timestamp DESC")
                rows = cur.fetchall()
                data = []
                for r in rows:
                    v_raw = r.get('votes_json', '{{}}')
                    v = json.loads(v_raw) if isinstance(v_raw, str) else v_raw
                    data.append({{
                        "pu_name": r.get('location'), "state": r.get('state'), "lga": r.get('lg'), "ward": r.get('ward'),
                        "latitude": r.get('lat', 0.0), "longitude": r.get('lon', 0.0),
                        "votes_party_ACCORD": v.get("ACCORD", 0), "votes_party_APC": v.get("APC", 0),
                        "votes_party_PDP": v.get("PDP", 0), "votes_party_ADC": v.get("ADC", 0)
                    }})
                return data
    except Exception as e:
        return []

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
        return {{"status": "success", "message": "Result Uploaded Successfully"}}
    except Exception as e:
        return {{"status": "error", "message": str(e)}}

@app.get("/export/csv")
async def export_csv():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM field_submissions ORDER BY timestamp DESC")
            rows = cur.fetchall()
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["Timestamp", "Officer ID", "State", "LGA", "Ward", "PU Code", "Location", "ACCORD", "APC", "PDP", "ADC"])
            for r in rows:
                v = json.loads(r['votes_json']) if isinstance(r['votes_json'], str) else r['votes_json']
                writer.writerow([r['timestamp'], r['officer_id'], r['state'], r['lg'], r['ward'], r['pu_code'], r['location'], v.get("ACCORD", 0), v.get("APC", 0), v.get("PDP", 0), v.get("ADC", 0)])
            output.seek(0)
            return StreamingResponse(output, media_type="text/csv", headers={{"Content-Disposition": "attachment; filename=results.csv"}})

# --- HTML RENDERING ---

@app.get("/", response_class=HTMLResponse)
async def index():
    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>ACCORD FIELD ENTRY</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {{ background: #f8f9fa; font-family: sans-serif; }}
        .navbar {{ background: #008751; color: white; border-bottom: 4px solid #ffc107; }}
        .card {{ border: none; box-shadow: 0 4px 12px rgba(0,0,0,0.1); border-radius: 12px; margin-bottom: 20px; }}
        .section-label {{ font-size: 0.75rem; font-weight: bold; color: #008751; text-transform: uppercase; border-left: 3px solid #ffc107; padding-left: 10px; }}
    </style>
</head>
<body>
    <nav class="navbar py-2 mb-4 text-center"><h5>OFFICIAL FIELD COLLATION</h5></nav>
    <div class="container" style="max-width: 500px;">
        <div id="loginArea" class="card p-4 text-center">
            <h6 class="mb-3">Enter Officer Credentials</h6>
            <input type="text" id="oid" class="form-control mb-3" placeholder="Officer ID">
            <button class="btn btn-success w-100" onclick="start()">Access Portal</button>
        </div>
        <div id="formArea" class="d-none">
            <div class="card p-3">
                <span class="section-label">1. Location Details</span>
                <select id="s" class="form-select mt-2" onchange="loadLGAs()"><option value="">STATE</option></select>
                <select id="l" class="form-select mt-2" onchange="loadWards()"><option value="">LGA</option></select>
                <select id="w" class="form-select mt-2" onchange="loadPUs()"><option value="">WARD</option></select>
                <select id="p" class="form-select mt-2" onchange="fillPU()"><option value="">SELECT POLLING UNIT</option></select>
                <div class="row mt-2 g-2">
                    <div class="col-6"><input type="text" id="pc" class="form-control" placeholder="PU Code" readonly></div>
                    <div class="col-6"><input type="text" id="wc" class="form-control" placeholder="Ward Code" readonly></div>
                </div>
                <input type="hidden" id="loc">
            </div>
            <div class="card p-3">
                <span class="section-label">2. Party Scores</span>
                <div class="row g-2 mt-1">
                    <div class="col-6">ACCORD <input type="number" class="form-control party-v" data-p="ACCORD" value="0" oninput="calc()"></div>
                    <div class="col-6">APC <input type="number" class="form-control party-v" data-p="APC" value="0" oninput="calc()"></div>
                    <div class="col-6">PDP <input type="number" class="form-control party-v" data-p="PDP" value="0" oninput="calc()"></div>
                    <div class="col-6">ADC <input type="number" class="form-control party-v" data-p="ADC" value="0" oninput="calc()"></div>
                </div>
            </div>
            <div class="card p-3">
                <span class="section-label">3. Audit</span>
                <div class="row g-2 mt-1">
                    <div class="col-6">Accredited <input type="number" id="ta" class="form-control" oninput="calc()"></div>
                    <div class="col-6">Total Cast <input type="number" id="tc" class="form-control" readonly></div>
                </div>
            </div>
            <button class="btn btn-outline-dark w-100 mb-2" onclick="getGPS()">Fix GPS Location</button>
            <button class="btn btn-success w-100 py-3 fw-bold" onclick="submit()">UPLOAD RESULT</button>
        </div>
    </div>
    <script>
        let lat, lon, officerId, puData = [], wardData = [];
        function start() {{
            officerId = document.getElementById('oid').value;
            if(!officerId) return alert("Enter ID");
            document.getElementById('loginArea').classList.add('d-none');
            document.getElementById('formArea').classList.remove('d-none');
            fetch('/api/states').then(r=>r.json()).then(data=>{{
                const s = document.getElementById('s');
                data.forEach(item => s.add(new Option(item, item)));
            }});
        }}
        function loadLGAs() {{
            fetch('/api/lgas/'+document.getElementById('s').value).then(r=>r.json()).then(data=>{{
                const l = document.getElementById('l'); l.innerHTML = '<option value="">LGA</option>';
                data.forEach(item => l.add(new Option(item, item)));
            }});
        }}
        function loadWards() {{
            fetch(`/api/wards/${{document.getElementById('s').value}}/${{document.getElementById('l').value}}`).then(r=>r.json()).then(data=>{{
                wardData = data;
                const w = document.getElementById('w'); w.innerHTML = '<option value="">WARD</option>';
                data.forEach(item => w.add(new Option(item.name, item.name)));
            }});
        }}
        function loadPUs() {{
            const wVal = document.getElementById('w').value;
            const wObj = wardData.find(x => x.name === wVal);
            document.getElementById('wc').value = wObj ? wObj.code : '';
            fetch(`/api/pus/${{document.getElementById('s').value}}/${{document.getElementById('l').value}}/${{wVal}}`).then(r=>r.json()).then(data=>{{
                puData = data;
                const p = document.getElementById('p'); p.innerHTML = '<option value="">PU</option>';
                data.forEach((item, idx) => p.add(new Option(item.location, idx)));
            }});
        }}
        function fillPU() {{
            const sel = puData[document.getElementById('p').value];
            if(!sel) return;
            document.getElementById('pc').value = sel.pu_code;
            document.getElementById('loc').value = sel.location;
        }}
        function calc() {{
            let v = 0; document.querySelectorAll('.party-v').forEach(i => v += parseInt(i.value || 0));
            document.getElementById('tc').value = v;
        }}
        function getGPS() {{ navigator.geolocation.getCurrentPosition(p => {{ lat=p.coords.latitude; lon=p.coords.longitude; alert("GPS Fixed: " + lat + "," + lon); }}, e => alert("Enable GPS")); }}
        async function submit() {{
            if(!lat) return alert("Please Fix GPS first");
            const v = {{}}; document.querySelectorAll('.party-v').forEach(i => v[i.dataset.p] = parseInt(i.value || 0));
            const p = {{ officer_id: officerId, state: document.getElementById('s').value, lg: document.getElementById('l').value, ward: document.getElementById('w').value, ward_code: document.getElementById('wc').value, pu_code: document.getElementById('pc').value, location: document.getElementById('loc').value, reg_voters: 0, total_accredited: parseInt(document.getElementById('ta').value || 0), valid_votes: parseInt(document.getElementById('tc').value), rejected_votes: 0, total_cast: parseInt(document.getElementById('tc').value), lat, lon, votes: v }};
            const res = await fetch('/submit', {{ method: 'POST', headers: {{'Content-Type':'application/json'}}, body: JSON.stringify(p)}});
            const out = await res.json(); alert(out.message); if(out.status==='success') location.reload();
        }}
    </script>
</body>
</html>
"""

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Accord Situation Room - LIVE</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{ --gold: #ffc107; --green: #008751; --dark: #0a0a0a; --panel: #141414; }}
        body {{ background-color: var(--dark); color: #fff; font-family: 'Segoe UI', sans-serif; overflow: hidden; height: 100vh; margin: 0; }}
        .navbar-custom {{ background: #000; border-bottom: 2px solid var(--gold); padding: 10px 20px; display: flex; align-items: center; justify-content: space-between; }}
        .nav-kpi-group {{ display: flex; gap: 10px; }}
        .party-box {{ background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 5px 12px; display: flex; align-items: center; gap: 8px; min-width: 125px; }}
        .party-box img {{ height: 30px; width: 30px; object-fit: contain; background: white; border-radius: 50%; }}
        .party-info label {{ display: block; font-size: 0.6rem; color: #aaa; margin: 0; }}
        .party-info span {{ font-size: 1rem; font-weight: bold; }}
        .box-accord {{ border-top: 3px solid var(--gold); }}
        .margin-box {{ background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 5px 15px; text-align: center; min-width: 150px; border-top: 3px solid #fff; }}
        .margin-val {{ font-size: 1.2rem; font-weight: 900; color: var(--gold); display: block; }}
        .main-content {{ display: grid; grid-template-columns: 320px 1fr 320px; height: calc(100vh - 85px); gap: 10px; padding: 10px; }}
        .side-panel {{ background: var(--panel); border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; border: 1px solid #222; }}
        .panel-header {{ background: #1c1c1c; padding: 10px; font-size: 0.75rem; font-weight: bold; color: var(--gold); border-bottom: 1px solid #333; text-transform: uppercase; }}
        #map {{ height: 45%; border-radius: 12px; margin: 5px; background: #111; }}
        .chart-container {{ height: 200px; padding: 10px; }}
        .feed-container {{ flex: 1; overflow-y: auto; padding: 10px; }}
        .pu-card {{ background: #1e1e1e; border-radius: 8px; padding: 10px; margin-bottom: 8px; border-left: 4px solid var(--gold); cursor: pointer; }}
        .score-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 5px; margin-top: 5px; }}
        .grid-val {{ text-align: center; font-size: 0.7rem; }}
        .export-btn {{ background: transparent; border: 1px solid var(--gold); color: var(--gold); font-size: 10px; padding: 5px 10px; text-decoration: none; border-radius: 4px; }}
    </style>
</head>
<body>
<nav class="navbar-custom">
    <div class="brand-section">
        <div style="font-weight:bold;">ACCORD HQ</div>
        <a href="/export/csv" class="export-btn">EXPORT CSV</a>
    </div>
    <div class="d-flex gap-2">
        <select id="fState" class="form-select form-select-sm bg-dark text-white border-secondary" style="width:120px;" onchange="filterLGA()"><option value="">STATE</option></select>
        <select id="fLGA" class="form-select form-select-sm bg-dark text-white border-secondary" style="width:120px;" onchange="filterWard()"><option value="">LGA</option></select>
        <select id="fWard" class="form-select form-select-sm bg-dark text-white border-secondary" style="width:120px;" onchange="applyFilters()"><option value="">WARD</option></select>
    </div>
    <div class="margin-box">
        <small style="font-size:9px; color:#888;">MARGIN</small>
        <span id="marginVal" class="margin-val">0</span>
        <small id="marginLead" style="font-size:9px;">AWAITING</small>
    </div>
    <div class="nav-kpi-group">
        <div class="party-box box-accord"><div class="party-info"><label>ACCORD</label><span id="nav-ACCORD">0</span></div></div>
        <div class="party-box" style="border-top:3px solid #0b3d91"><div class="party-info"><label>APC</label><span id="nav-APC">0</span></div></div>
        <div class="party-box" style="border-top:3px solid #d9534f"><div class="party-info"><label>PDP</label><span id="nav-PDP">0</span></div></div>
        <div class="party-box" style="border-top:3px solid #138808"><div class="party-info"><label>ADC</label><span id="nav-ADC">0</span></div></div>
    </div>
</nav>
<div class="main-content">
    <div class="side-panel">
        <div class="panel-header">LIVE FIELD FEED</div>
        <div class="px-2 pt-2"><input type="text" id="puSearch" class="form-control form-control-sm bg-dark text-white border-secondary" placeholder="Search PU..." oninput="applyFilters()"></div>
        <div class="feed-container" id="feedList"></div>
    </div>
    <div class="d-flex flex-column" style="gap:10px;">
        <div id="map"></div>
        <div class="d-flex" style="gap:10px; height: 50%;">
            <div class="side-panel flex-fill">
                <div class="panel-header">DISTRIBUTION</div>
                <div class="chart-container"><canvas id="pieChart"></canvas></div>
            </div>
            <div class="side-panel flex-fill">
                <div class="panel-header">PERFORMANCE</div>
                <div class="chart-container"><canvas id="barChart"></canvas></div>
            </div>
        </div>
    </div>
    <div class="side-panel">
        <div class="panel-header">AI INTERPRETATION</div>
        <div class="ai-box p-3" id="ai_box" style="font-size:0.8rem; font-family:monospace; color:#0f0;">Analyzing stream...</div>
        <div class="panel-header mt-auto">SYSTEM STATUS</div>
        <div class="p-3 small text-secondary">
            Sync: <span id="sync-time">--</span><br>
            Count: <span id="pu-count">0</span>
        </div>
        <button class="btn btn-warning btn-sm m-3 fw-bold" onclick="refreshData()">REFRESH</button>
    </div>
</div>
<script>
    let map, globalData = [], filterLookup = [], markers = [], barChart, pieChart;
    function initMap() {{
        map = L.map('map', {{ zoomControl: false }}).setView([9.082, 8.675], 6);
        L.tileLayer('https://{{{{s}}}}.basemaps.cartocdn.com/dark_all/{{{{z}}}}/{{{{x}}}}/{{{{y}}}}{{{{r}}}}.png').addTo(map);
    }}
    async function loadFilters() {{
        const res = await fetch('/api/dashboard_filters');
        filterLookup = await res.json();
        const states = [...new Set(filterLookup.map(x => x.state))];
        const sEl = document.getElementById('fState');
        states.forEach(s => sEl.add(new Option(s.toUpperCase(), s)));
    }}
    function filterLGA() {{
        const s = document.getElementById('fState').value;
        const lEl = document.getElementById('fLGA'); lEl.innerHTML = '<option value="">LGA</option>';
        const lgAs = [...new Set(filterLookup.filter(x => x.state === s).map(x => x.lg))];
        lgAs.forEach(l => lEl.add(new Option(l.toUpperCase(), l)));
        applyFilters();
    }}
    function filterWard() {{
        const s = document.getElementById('fState').value;
        const l = document.getElementById('fLGA').value;
        const wEl = document.getElementById('fWard'); wEl.innerHTML = '<option value="">WARD</option>';
        const wards = [...new Set(filterLookup.filter(x => x.state === s && x.lg === l).map(x => x.ward))];
        wards.forEach(w => wEl.add(new Option(w.toUpperCase(), w)));
        applyFilters();
    }}
    async function refreshData() {{
        const res = await fetch('/submissions');
        globalData = await res.json();
        applyFilters();
    }}
    function applyFilters() {{
        const s = document.getElementById('fState').value;
        const l = document.getElementById('fLGA').value;
        const w = document.getElementById('fWard').value;
        const q = document.getElementById('puSearch').value.toLowerCase();
        let filtered = globalData;
        if(s) filtered = filtered.filter(x => x.state === s);
        if(l) filtered = filtered.filter(x => x.lga === l);
        if(w) filtered = filtered.filter(x => x.ward === w);
        if(q) filtered = filtered.filter(x => x.pu_name.toLowerCase().includes(q));
        updateUI(filtered);
    }}
    function updateUI(data) {{
        let totals = {{ ACCORD: 0, APC: 0, PDP: 0, ADC: 0 }};
        const list = document.getElementById('feedList'); list.innerHTML = "";
        markers.forEach(m => map.removeLayer(m));
        data.forEach(d => {{
            totals.ACCORD += d.votes_party_ACCORD;
            totals.APC += d.votes_party_APC;
            totals.PDP += d.votes_party_PDP;
            totals.ADC += d.votes_party_ADC;
            const card = document.createElement('div');
            card.className = 'pu-card';
            card.innerHTML = `<h6>${{d.pu_name}}</h6><div class="score-grid">
                <div class="grid-val text-warning">A: ${{d.votes_party_ACCORD}}</div>
                <div class="grid-val">P: ${{d.votes_party_APC}}</div>
                <div class="grid-val">D: ${{d.votes_party_PDP}}</div>
                <div class="grid-val">C: ${{d.votes_party_ADC}}</div>
            </div>`;
            card.onclick = () => {{ if(d.latitude) map.setView([d.latitude, d.longitude], 14); }};
            list.appendChild(card);
            if(d.latitude) {{
                const m = L.circleMarker([d.latitude, d.longitude], {{ radius: 6, color: '#ffc107', fillOpacity: 0.8 }}).addTo(map);
                markers.push(m);
            }}
        }});
        document.getElementById('nav-ACCORD').innerText = totals.ACCORD.toLocaleString();
        document.getElementById('nav-APC').innerText = totals.APC.toLocaleString();
        document.getElementById('nav-PDP').innerText = totals.PDP.toLocaleString();
        document.getElementById('nav-ADC').innerText = totals.ADC.toLocaleString();
        document.getElementById('pu-count').innerText = data.length;
        document.getElementById('sync-time').innerText = new Date().toLocaleTimeString();

        const rivals = {{ "APC": totals.APC, "PDP": totals.PDP, "ADC": totals.ADC }};
        const topRival = Object.keys(rivals).reduce((a, b) => rivals[a] > rivals[b] ? a : b);
        const margin = totals.ACCORD - rivals[topRival];
        document.getElementById('marginVal').innerText = Math.abs(margin).toLocaleString();
        document.getElementById('marginLead').innerText = margin >= 0 ? `LEAD OVER ${{topRival}}` : `BEHIND ${{topRival}}`;
        document.getElementById('marginLead').className = margin >= 0 ? "text-success" : "text-danger";
        updateCharts(totals);
    }}
    function updateCharts(s) {{
        const cData = {{ labels: ['ACCORD', 'APC', 'PDP', 'ADC'], datasets: [{{ data: [s.ACCORD, s.APC, s.PDP, s.ADC], backgroundColor: ['#ffc107', '#0b3d91', '#d9534f', '#138808'], borderWidth: 0 }}] }};
        if(barChart) barChart.destroy();
        barChart = new Chart(document.getElementById('barChart'), {{ type: 'bar', data: cData, options: {{ maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }} }});
        if(pieChart) pieChart.destroy();
        pieChart = new Chart(document.getElementById('pieChart'), {{ type: 'doughnut', data: cData, options: {{ maintainAspectRatio: false, plugins: {{ legend: {{ position: 'bottom', labels: {{ color: '#fff' }} }} }} }} }});
    }}
    initMap(); loadFilters(); refreshData();
    setInterval(refreshData, 20000);
</script>
</body>
</html>
"""
