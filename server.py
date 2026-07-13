"""FastAPI app: runs the self-correction cycle and serves the review console.

Endpoints
    GET  /                 -> the agent console (Agent Flow UI)
    GET  /api/target       -> the file under review
    GET  /api/state        -> cross-cycle aggregate (KPIs, success curve, heuristics)
    POST /api/run          -> run the full self-correction cycle, return the session
    POST /api/dream        -> consolidate observations into promoted heuristics
    POST /api/apply        -> apply the approved change to the real file (with backup)
    POST /api/reject       -> discard the session
    POST /api/reset        -> clear sessions + memory
"""
from __future__ import annotations

from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from .agent import SelfCorrectingAgent, Session
from .config import Config
from .memory import AgentMemory

SESSIONS: Dict[str, Session] = {}
MEMORY = AgentMemory()


def _session_json(s: Session) -> dict:
    return {
        "id": s.id,
        "file_path": s.file_path,
        "status": s.status,
        "changed": s.changed,
        "attempts_used": s.attempts_used,
        "attempts_to_green": s.attempts_to_green,
        "final_summary": s.final_summary,
        "rationale": s.rationale,
        "original_code": s.original_code,
        "improved_code": s.improved_code,
        "tests_code": s.tests_code,
        "diff": s.unified_diff,
        "applied": s.applied,
        "backup_path": s.backup_path,
        "test_path": s.test_path,
        "diagnoses": s.diagnoses,
        "test_count": s.test_count,
        "false_incidents": s.false_incidents,
        "coverage": s.coverage,
        "final_passed": s.final_passed,
        "final_total": s.final_total,
        "steps": [
            {"name": st.name, "status": st.status, "detail": st.detail, "attempt": st.attempt}
            for st in s.steps
        ],
    }


class RunReq(BaseModel):
    path: Optional[str] = None


class SessionReq(BaseModel):
    session_id: str
    write_tests: bool = True


def create_app(target_path: str, config: Optional[Config] = None) -> FastAPI:
    config = config or Config()
    agent = SelfCorrectingAgent(config)
    app = FastAPI(title="Self-Correcting Agent")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTML_PAGE

    @app.get("/api/target")
    def target():
        return {"path": target_path, "mock": config.use_mock or not config.has_api_key,
                "model": config.model, "max_attempts": config.max_attempts}

    @app.get("/api/source")
    def source():
        try:
            from pathlib import Path
            return {"path": target_path, "source": Path(target_path).read_text(encoding="utf-8")}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")

    @app.get("/api/state")
    def state():
        return JSONResponse(MEMORY.snapshot())

    @app.post("/api/run")
    def run(req: RunReq):
        path = req.path or target_path
        try:
            session = agent.run(path)
        except Exception as e:  # surface the error to the UI rather than 500-ing silently
            raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")
        SESSIONS[session.id] = session
        snap = _session_json(session)
        MEMORY.record_cycle(snap)
        snap["state"] = MEMORY.snapshot()
        return JSONResponse(snap)

    @app.post("/api/dream")
    def dream():
        result = MEMORY.dream()
        return JSONResponse({"result": result, "state": MEMORY.snapshot()})

    @app.post("/api/apply")
    def apply(req: SessionReq):
        s = SESSIONS.get(req.session_id)
        if not s:
            raise HTTPException(status_code=404, detail="Unknown session.")
        if s.status != "ready":
            raise HTTPException(status_code=400,
                                detail="Session is not in a ready state; not applying.")
        s.apply(write_tests=req.write_tests)
        return JSONResponse(_session_json(s))

    @app.post("/api/reject")
    def reject(req: SessionReq):
        SESSIONS.pop(req.session_id, None)
        return {"ok": True}

    @app.post("/api/reset")
    def reset():
        SESSIONS.clear()
        MEMORY.reset()
        return JSONResponse({"ok": True, "state": MEMORY.snapshot()})

    return app


# --------------------------------------------------------------------------- #
# Single-file console UI (dark "Agent Flow" aesthetic, no external assets)
# --------------------------------------------------------------------------- #
HTML_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Self-Correcting Agent</title>
<style>
  :root{
    --bg:#0a0d14; --bg2:#0d1117; --panel:#121722; --panel2:#171d2b; --panel3:#1b2333;
    --border:#242c3d; --border2:#2f3a50;
    --ink:#e6edf3; --ink2:#c3ccd9; --mute:#7d8797; --faint:#5b6472;
    --blue:#3b82f6; --blue2:#2563eb; --purple:#7c5ce0; --purple2:#6d4fd6;
    --ok:#22c55e; --okd:#16351f; --warn:#eab308; --warnd:#3a2f0e;
    --bad:#ef4444; --badd:#3a1618; --info:#38bdf8; --add:#123322; --del:#3a161a;
  }
  *{box-sizing:border-box}
  html,body{height:100%}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Arial}
  code,pre,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
  .app{display:grid;grid-template-columns:248px 1fr;min-height:100vh}
  @media(max-width:820px){.app{grid-template-columns:1fr}}

  /* ---- sidebar ---- */
  aside{background:linear-gradient(180deg,#0c111b,#0a0d14);border-right:1px solid var(--border);
    padding:18px 16px;display:flex;flex-direction:column;gap:18px;position:sticky;top:0;
    height:100vh;overflow:auto}
  .side-h{display:flex;align-items:center;justify-content:space-between}
  .side-h .t{font-size:12px;letter-spacing:1.4px;color:var(--mute);font-weight:700}
  .runs{font-size:11px;color:var(--faint)}
  .flow{display:flex;flex-direction:column;gap:2px}
  .fstep{display:flex;gap:11px;padding:9px 6px;border-radius:9px;position:relative}
  .fstep .num{flex:0 0 auto;width:22px;height:22px;border-radius:50%;display:grid;place-items:center;
    font-size:11px;font-weight:700;color:var(--faint);border:1.5px solid var(--border2);
    background:var(--panel)}
  .fstep .lbl .n{font-weight:600;font-size:13px;color:var(--ink2)}
  .fstep .lbl .s{font-size:11px;color:var(--faint)}
  .fstep.active .num{background:var(--ok);border-color:var(--ok);color:#05210f}
  .fstep.active .lbl .n{color:#fff}
  .fstep.done .num{background:#12351f;border-color:var(--ok);color:var(--ok)}
  .fstep.done .lbl .n{color:var(--ink2)}
  .fstep::after{content:"";position:absolute;left:16px;top:31px;width:1.5px;height:14px;
    background:var(--border2)}
  .fstep:last-child::after{display:none}
  .side-btns{display:flex;flex-direction:column;gap:9px;margin-top:2px}
  .btn{font:inherit;border:1px solid transparent;border-radius:10px;padding:11px 14px;cursor:pointer;
    display:flex;align-items:center;gap:9px;font-weight:600;color:#fff;transition:.15s;justify-content:center}
  .btn svg{width:15px;height:15px}
  .btn.blue{background:linear-gradient(180deg,var(--blue),var(--blue2))}
  .btn.blue:hover{filter:brightness(1.08)}
  .btn.purple{background:linear-gradient(180deg,var(--purple),var(--purple2))}
  .btn.purple:hover{filter:brightness(1.08)}
  .btn.ghost{background:var(--panel2);border-color:var(--border);color:var(--ink2)}
  .btn.ghost:hover{border-color:var(--border2)}
  .btn:disabled{opacity:.45;cursor:not-allowed;filter:none}
  .side-foot{margin-top:auto;font-size:11px;color:var(--faint);border-top:1px solid var(--border);
    padding-top:12px}
  .side-foot .dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--ok);
    margin-right:6px;vertical-align:1px}

  /* ---- main ---- */
  main{padding:22px 26px 40px;overflow:auto}
  .topbar{display:flex;align-items:center;gap:12px;margin-bottom:20px}
  .topbar h1{font-size:17px;margin:0;font-weight:650}
  .topbar .path{color:var(--mute);font-size:12px}
  .pill{margin-left:auto;font-size:11px;color:var(--ink2);border:1px solid var(--border2);
    padding:4px 10px;border-radius:99px;background:var(--panel2)}

  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
  @media(max-width:900px){.kpis{grid-template-columns:repeat(2,1fr)}}
  .kpi{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:16px 18px}
  .kpi .k{font-size:10.5px;letter-spacing:.7px;text-transform:uppercase;color:var(--mute)}
  .kpi .v{font-size:30px;font-weight:750;margin-top:8px;letter-spacing:.5px}
  .kpi .sub{font-size:11px;color:var(--faint);margin-top:2px}
  .v.g{color:var(--ok)} .v.b{color:var(--bad)} .v.w{color:var(--warn)} .v.p{color:#a78bfa}

  .card{background:var(--panel);border:1px solid var(--border);border-radius:12px;margin-top:16px}
  .card .hd{display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--border)}
  .card .hd h2{font-size:13px;margin:0;font-weight:650}
  .card .hd .rt{margin-left:auto;font-size:11px;color:var(--mute)}
  .card .bd{padding:16px 18px}
  .badge-pill{font-size:11px;color:#bcd0ff;background:#16244a;border:1px solid #24386b;
    padding:3px 9px;border-radius:99px;font-weight:600}

  /* success chart */
  .chart{width:100%;height:150px;display:block}
  .chart-empty{color:var(--faint);font-size:12.5px;height:150px;display:grid;place-items:center}

  /* pipeline */
  .pipe{display:flex;align-items:stretch;gap:0;flex-wrap:wrap}
  .pstate{flex:1;min-width:120px;background:var(--panel2);border:1px solid var(--border);
    border-radius:11px;padding:14px 12px;text-align:center;position:relative;transition:.25s}
  .pipe .conn{align-self:center;color:var(--faint);padding:0 4px;font-size:16px}
  .pstate .ic{width:30px;height:30px;margin:0 auto 8px;border-radius:8px;display:grid;place-items:center;
    background:var(--panel3);border:1px solid var(--border2);color:var(--mute)}
  .pstate .ic svg{width:16px;height:16px}
  .pstate .nm{font-weight:650;font-size:13px}
  .pstate .dt{font-size:11px;color:var(--faint);margin-top:3px;min-height:14px}
  .pstate.on-ok{border-color:var(--ok);box-shadow:0 0 0 1px var(--ok) inset}
  .pstate.on-ok .ic{background:var(--okd);border-color:var(--ok);color:var(--ok)}
  .pstate.on-fail{border-color:var(--bad)}
  .pstate.on-fail .ic{background:var(--badd);border-color:var(--bad);color:var(--bad)}
  .pstate.on-warn{border-color:var(--warn)}
  .pstate.on-warn .ic{background:var(--warnd);border-color:var(--warn);color:var(--warn)}
  .pstate.on-info{border-color:var(--info)}
  .pstate.on-info .ic{background:#0c2a3a;border-color:var(--info);color:var(--info)}

  /* cycle log */
  .step{display:flex;gap:11px;padding:9px 0;border-bottom:1px dashed var(--border)}
  .step:last-child{border-bottom:0}
  .sbadge{flex:0 0 auto;width:22px;height:22px;border-radius:6px;display:grid;place-items:center;
    font-size:12px;font-weight:800;color:#08110a}
  .b-ok{background:var(--ok)} .b-fail{background:var(--bad);color:#fff}
  .b-warn{background:var(--warn)} .b-info{background:var(--info)}
  .step .n{font-weight:600} .step .d{color:var(--mute);font-size:13px}
  .step .a{margin-left:auto;color:var(--faint);font-size:11px;white-space:nowrap}

  /* review tabs + diff */
  .tabs{display:flex;gap:4px;padding:0 8px}
  .tab{padding:10px 14px;cursor:pointer;color:var(--mute);border-bottom:2px solid transparent;font-size:13px}
  .tab.active{color:var(--ink);border-bottom-color:var(--blue)}
  pre{margin:0;padding:14px 16px;overflow:auto;max-height:420px;font-size:12.5px}
  .diff .ln{display:block;white-space:pre}
  .diff .add{background:var(--add)} .diff .del{background:var(--del)}
  .diff .hdr{color:var(--info)} .diff .meta{color:var(--faint)}

  /* heuristics */
  .heur{display:flex;gap:11px;padding:11px 0;border-bottom:1px dashed var(--border)}
  .heur:last-child{border-bottom:0}
  .heur .hid{flex:0 0 auto;font-family:ui-monospace,monospace;font-size:11px;color:#a78bfa;
    background:#1c1636;border:1px solid #2e2358;border-radius:6px;padding:3px 7px;height:fit-content}
  .heur .ht{font-size:13px;color:var(--ink2)}
  .heur .hs{font-size:11px;color:var(--faint);margin-top:3px}

  .bar{display:flex;gap:10px;align-items:center;padding:14px 18px}
  button.act{font:inherit;border:1px solid var(--border2);background:var(--panel2);color:var(--ink);
    padding:9px 16px;border-radius:8px;cursor:pointer;font-weight:600}
  button.act:hover{border-color:#3a4456}
  button.act.primary{background:var(--ok);border-color:var(--ok);color:#052210}
  button.act:disabled{opacity:.5;cursor:not-allowed}
  label.chk{display:flex;gap:7px;align-items:center;color:var(--mute);font-size:12.5px}
  .banner{padding:12px 16px;border-radius:10px;margin-top:14px;font-size:13px}
  .banner.ok{background:var(--add);border:1px solid var(--ok)}
  .banner.warn{background:var(--warnd);border:1px solid var(--warn)}
  .banner.err{background:var(--del);border:1px solid var(--bad)}
  .banner.info{background:#0c2233;border:1px solid var(--info)}
  .spin{width:15px;height:15px;border:2px solid var(--border2);border-top-color:var(--blue);
    border-radius:50%;display:inline-block;animation:s .8s linear infinite;vertical-align:-3px}
  @keyframes s{to{transform:rotate(360deg)}}
  .muted{color:var(--faint)}
  .rationale{color:var(--ink2);font-size:13px;margin:12px 0 0}
</style>
</head>
<body>
<div class="app">
  <!-- ============ SIDEBAR ============ -->
  <aside>
    <div class="side-h">
      <span class="t">AGENT FLOW</span>
      <span class="runs" id="runs">0 runs</span>
    </div>
    <div class="flow" id="flow">
      <div class="fstep" data-step="1"><div class="num">1</div>
        <div class="lbl"><div class="n">Load Input</div><div class="s">Read target file</div></div></div>
      <div class="fstep" data-step="2"><div class="num">2</div>
        <div class="lbl"><div class="n">Run Session</div><div class="s">Execute correction loop</div></div></div>
      <div class="fstep" data-step="3"><div class="num">3</div>
        <div class="lbl"><div class="n">Dreaming Cycle</div><div class="s">Consolidate memory</div></div></div>
      <div class="fstep" data-step="4"><div class="num">4</div>
        <div class="lbl"><div class="n">Review Results</div><div class="s">Inspect heuristics</div></div></div>
    </div>
    <div class="side-btns">
      <button class="btn blue" id="bLoad">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7h5l2 2h11v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/></svg>
        Load Input</button>
      <button class="btn blue" id="bRun" disabled>
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
        Run Session</button>
      <button class="btn purple" id="bDream" disabled>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
        Run Dreaming</button>
      <button class="btn ghost" id="bReset">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>
        Reset</button>
    </div>
    <div class="side-foot"><span class="dot"></span><span id="modeFoot">offline</span></div>
  </aside>

  <!-- ============ MAIN ============ -->
  <main>
    <div class="topbar">
      <div>
        <h1>Self-Correcting Agent</h1>
        <div class="path mono" id="path">loading…</div>
      </div>
      <span class="pill" id="modePill"></span>
    </div>

    <div id="status"></div>

    <!-- KPIs -->
    <div class="kpis">
      <div class="kpi"><div class="k">Coverage</div><div class="v" id="kCov">--</div><div class="sub">final green suite</div></div>
      <div class="kpi"><div class="k">Attempts to Green</div><div class="v" id="kAtt">--</div><div class="sub">last session</div></div>
      <div class="kpi"><div class="k">False Incidents</div><div class="v" id="kFalse">0</div><div class="sub">bad-test diagnoses</div></div>
      <div class="kpi"><div class="k">Heuristics Promoted</div><div class="v p" id="kHeur">0</div><div class="sub">durable memory</div></div>
    </div>

    <!-- success chart -->
    <div class="card">
      <div class="hd"><h2>Success Rate Across Cycles</h2><span class="rt" id="chartRt">--</span></div>
      <div class="bd" id="chartWrap"><div class="chart-empty">No cycles yet — run a session to populate.</div></div>
    </div>

    <!-- pipeline -->
    <div class="card">
      <div class="hd"><h2>Agent Pipeline</h2></div>
      <div class="bd">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
          <strong style="font-size:13px">In-Session Self-Correction Loop</strong>
          <span class="badge-pill">6 States</span>
        </div>
        <div class="pipe" id="pipe"></div>
      </div>
    </div>

    <!-- cycle log + outcome -->
    <div class="card">
      <div class="hd"><h2>Cycle Log</h2><span class="rt" id="outcome"></span></div>
      <div class="bd" id="steps"><span class="muted">Run a session to see the Generate → Run → Diagnose → Correct → Verify → Stop trace.</span></div>
      <p class="rationale" id="rationale" style="padding:0 18px 16px"></p>
    </div>

    <!-- review -->
    <div class="card">
      <div class="hd" style="padding:0"><div class="tabs">
        <div class="tab active" data-t="diff">Proposed change</div>
        <div class="tab" data-t="tests">Generated tests</div>
        <div class="tab" data-t="full">Improved file</div>
        <div class="tab" data-t="input">Input</div>
      </div></div>
      <div id="pane"><pre class="muted">—</pre></div>
      <div class="bar" id="bar" style="display:none;border-top:1px solid var(--border)">
        <label class="chk"><input type="checkbox" id="wt" checked/> also save the test file</label>
        <span style="flex:1"></span>
        <button class="act" id="reject">Reject</button>
        <button class="act primary" id="apply">Apply to file</button>
      </div>
      <div id="ack" style="padding:0 18px 16px"></div>
    </div>

    <!-- heuristics -->
    <div class="card">
      <div class="hd"><h2>Promoted Heuristics</h2><span class="rt" id="heurRt">memory</span></div>
      <div class="bd" id="heur"><span class="muted">None yet. Run a session, then Run Dreaming to consolidate what was learned.</span></div>
    </div>
  </main>
</div>

<script>
const $=s=>document.querySelector(s);
const esc=t=>(t==null?"":String(t)).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
let SESSION=null, STATE=null, TARGET=null, loaded=false;

/* ---- pipeline states ---- */
const STATES=[
  ["Generate","M13 2 4 14h6l-1 8 9-12h-6z"],           // spark
  ["Run","M8 5v14l11-7z"],                              // play
  ["Diagnose","M11 4a7 7 0 1 0 4.2 12.6l4.1 4.1 1.4-1.4-4.1-4.1A7 7 0 0 0 11 4z"], // search
  ["Correct","M14 6l4 4-8 8H6v-4z M17 3l4 4"],          // wrench-ish
  ["Verify","M20 6 9 17l-5-5"],                          // check
  ["Stop","M6 6h12v12H6z"],                              // square
];
function buildPipe(){
  const p=$("#pipe"); p.innerHTML="";
  STATES.forEach(([nm,d],i)=>{
    const el=document.createElement("div"); el.className="pstate"; el.id="ps-"+nm;
    el.innerHTML=`<div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg></div>
      <div class="nm">${nm}</div><div class="dt" id="dt-${nm}"></div>`;
    p.appendChild(el);
    if(i<STATES.length-1){const c=document.createElement("div");c.className="conn";c.textContent="→";p.appendChild(c);}
  });
}
function resetPipe(){STATES.forEach(([nm])=>{const e=$("#ps-"+nm);if(e)e.className="pstate";const d=$("#dt-"+nm);if(d)d.textContent="";});}
const CLS={ok:"on-ok",fail:"on-fail",warn:"on-warn",info:"on-info"};
function litePipe(steps){
  resetPipe();
  // last status per state name
  const last={};
  steps.forEach(s=>{last[s.name]=s;});
  STATES.forEach(([nm],i)=>{
    const s=last[nm]; if(!s)return;
    setTimeout(()=>{
      const e=$("#ps-"+nm); if(e)e.classList.add(CLS[s.status]||"on-info");
      const d=$("#dt-"+nm); if(d)d.textContent="try "+s.attempt;
    }, i*120);
  });
}

/* ---- flow stepper ---- */
function setFlow(step, done){
  document.querySelectorAll(".fstep").forEach(f=>{
    const n=+f.dataset.step; f.classList.toggle("active",n===step);
    f.classList.toggle("done", done.includes(n));
  });
}
let DONE=[];
function advance(step){ if(!DONE.includes(step))DONE.push(step); setFlow(step, DONE); }

/* ---- KPIs + chart ---- */
function kpi(id,val,cls){const e=$("#"+id);e.textContent=val;e.className="v"+(cls?" "+cls:"");}
function renderState(st){
  STATE=st;
  $("#runs").textContent=st.cycle_count+" run"+(st.cycle_count===1?"":"s");
  kpi("kFalse", st.false_incidents_total, st.false_incidents_total?"b":"");
  kpi("kHeur", st.heuristics_promoted, "p");
  renderChart(st.success_curve);
  renderHeur(st.heuristics);
}
function renderSession(d){
  kpi("kCov", d.final_total? d.coverage+"%" : "--", d.coverage>=100?"g":(d.coverage>0?"w":""));
  kpi("kAtt", d.attempts_to_green!=null? d.attempts_to_green : "--",
      d.attempts_to_green===1?"g":(d.attempts_to_green?"w":""));
}
function renderChart(curve){
  const wrap=$("#chartWrap");
  if(!curve||!curve.length){wrap.innerHTML='<div class="chart-empty">No cycles yet — run a session to populate.</div>';$("#chartRt").textContent="--";return;}
  $("#chartRt").textContent=curve[curve.length-1]+"% overall";
  const W=760,H=150,pad=26, n=curve.length;
  const x=i=> n===1? W/2 : pad + i*(W-2*pad)/(n-1);
  const y=v=> H-pad - (v/100)*(H-2*pad);
  let dots="",area="",line="";
  curve.forEach((v,i)=>{line+=(i?"L":"M")+x(i).toFixed(1)+" "+y(v).toFixed(1)+" ";
    dots+=`<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="3.5" fill="#22c55e"/>`;});
  area="M"+x(0).toFixed(1)+" "+(H-pad)+" "+line.replace(/^M/,"L")+"L"+x(n-1).toFixed(1)+" "+(H-pad)+" Z";
  const grid=[0,25,50,75,100].map(g=>`<line x1="${pad}" y1="${y(g)}" x2="${W-pad}" y2="${y(g)}" stroke="#242c3d"/><text x="4" y="${y(g)+3}" fill="#5b6472" font-size="9">${g}</text>`).join("");
  wrap.innerHTML=`<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    ${grid}<path d="${area}" fill="rgba(34,197,94,.12)"/>
    <path d="${line}" fill="none" stroke="#22c55e" stroke-width="2"/>${dots}</svg>`;
}
function renderHeur(hs){
  const box=$("#heur");
  if(!hs||!hs.length){box.innerHTML='<span class="muted">None yet. Run a session, then Run Dreaming to consolidate what was learned.</span>';$("#heurRt").textContent="0 promoted";return;}
  $("#heurRt").textContent=hs.length+" promoted";
  box.innerHTML=hs.map(h=>`<div class="heur"><span class="hid">${esc(h.id)}</span>
    <div><div class="ht">${esc(h.text)}</div><div class="hs">from ${esc(h.source)} · reinforced ${h.observations}×</div></div></div>`).join("");
}

/* ---- cycle log ---- */
function badge(s){const m={ok:["b-ok","✓"],fail:["b-fail","✕"],warn:["b-warn","!"],info:["b-info","i"]};const [c,ch]=m[s]||m.info;return `<span class="sbadge ${c}">${ch}</span>`;}
function renderSteps(steps){
  $("#steps").innerHTML=steps.map(s=>`<div class="step">${badge(s.status)}
    <div><div class="n">${esc(s.name)}</div><div class="d">${esc(s.detail)}</div></div>
    <div class="a">try ${s.attempt}</div></div>`).join("");
}
function renderOutcome(d){
  const st=d.status==="ready"?'<span style="color:var(--ok)">READY</span>'
    :d.status==="escalate"?'<span style="color:var(--warn)">ESCALATED</span>'
    :'<span style="color:var(--bad)">ERROR</span>';
  $("#outcome").innerHTML=st+' · '+esc(d.final_summary)+' · '+(d.changed?"changed":"no change");
  $("#rationale").textContent=d.rationale||"";
}

/* ---- review panes ---- */
function diffHtml(diff){
  if(!diff||!diff.trim())return '<pre class="muted">No change proposed.</pre>';
  const lines=diff.split("\n").map(l=>{let c="";
    if(l.startsWith("+++")||l.startsWith("---"))c="meta";
    else if(l.startsWith("@@"))c="hdr";else if(l.startsWith("+"))c="add";else if(l.startsWith("-"))c="del";
    return `<span class="ln ${c}">${esc(l)||"&nbsp;"}</span>`;}).join("");
  return `<pre class="diff">${lines}</pre>`;
}
function showPane(w){
  document.querySelectorAll(".tab").forEach(t=>t.classList.toggle("active",t.dataset.t===w));
  const p=$("#pane");
  if(w==="input"){p.innerHTML=`<pre class="mono">${esc(TARGET&&TARGET._src||"")||"(load input first)"}</pre>`;return;}
  if(!SESSION){p.innerHTML='<pre class="muted">—</pre>';return;}
  if(w==="diff")p.innerHTML=diffHtml(SESSION.diff);
  else if(w==="tests")p.innerHTML=`<pre class="mono">${esc(SESSION.tests_code)}</pre>`;
  else p.innerHTML=`<pre class="mono">${esc(SESSION.improved_code)}</pre>`;
}
document.querySelectorAll(".tab").forEach(t=>t.onclick=()=>showPane(t.dataset.t));

/* ---- actions ---- */
async function jpost(url,body){const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body||{})});
  if(!r.ok){let e={};try{e=await r.json()}catch(_){}throw new Error(e.detail||r.statusText);}return r.json();}

$("#bLoad").onclick=async()=>{
  $("#status").innerHTML="";
  try{
    const t=await (await fetch("/api/target")).json(); TARGET=t;
    const src=await (await fetch("/api/source")).json().catch(()=>null);
    TARGET._src = src&&src.source || "";
    showPane("input");
    loaded=true; $("#bRun").disabled=false; advance(1); setFlow(2,DONE);
    $("#status").innerHTML='<div class="banner info">Loaded <span class="mono">'+esc(t.path)+'</span>. Ready to run a session.</div>';
  }catch(err){$("#status").innerHTML='<div class="banner err">Load failed: '+esc(err.message)+'</div>';}
};

$("#bRun").onclick=async()=>{
  $("#status").innerHTML="";$("#ack").innerHTML="";$("#bar").style.display="none";
  $("#steps").innerHTML='<span class="spin"></span> running the self-correction cycle…';
  setFlow(2,DONE);
  try{
    const d=await jpost("/api/run",{}); SESSION=d;
    renderSteps(d.steps); litePipe(d.steps); renderOutcome(d); renderSession(d);
    if(d.state)renderState(d.state);
    showPane("diff"); advance(1); advance(2); $("#bDream").disabled=false;
    if(d.status==="ready"&&d.changed)$("#bar").style.display="flex";
    else if(d.status==="ready")$("#status").innerHTML='<div class="banner warn">File already passes its generated tests — no change needed.</div>';
    else if(d.status==="escalate")$("#status").innerHTML='<div class="banner warn">Could not reach a trustworthy green state within the attempt budget. Escalated for review.</div>';
  }catch(err){$("#steps").innerHTML="";$("#status").innerHTML='<div class="banner err">Run failed: '+esc(err.message)+'</div>';}
};

$("#bDream").onclick=async()=>{
  $("#status").innerHTML=""; setFlow(3,DONE);
  try{
    const d=await jpost("/api/dream",{}); renderState(d.state); advance(3); advance(4); setFlow(4,DONE);
    const n=d.result.promoted_now;
    $("#status").innerHTML='<div class="banner '+(n?"ok":"info")+'">Dreaming complete — reviewed '+d.result.observations_reviewed+' observation(s), promoted '+n+' new heuristic(s).</div>';
  }catch(err){$("#status").innerHTML='<div class="banner err">Dreaming failed: '+esc(err.message)+'</div>';}
};

$("#bReset").onclick=async()=>{
  try{const d=await jpost("/api/reset",{});
    SESSION=null;DONE=[];loaded=false;
    $("#bRun").disabled=true;$("#bDream").disabled=true;
    renderState(d.state); resetPipe(); setFlow(1,[]);
    kpi("kCov","--","");kpi("kAtt","--","");
    $("#steps").innerHTML='<span class="muted">Run a session to see the trace.</span>';
    $("#outcome").innerHTML="";$("#rationale").textContent="";$("#pane").innerHTML='<pre class="muted">—</pre>';
    $("#bar").style.display="none";$("#ack").innerHTML="";
    $("#status").innerHTML='<div class="banner info">Reset — sessions and memory cleared.</div>';
  }catch(err){$("#status").innerHTML='<div class="banner err">Reset failed: '+esc(err.message)+'</div>';}
};

$("#apply").onclick=async()=>{
  $("#apply").disabled=true;$("#reject").disabled=true;
  try{const d=await jpost("/api/apply",{session_id:SESSION.id,write_tests:$("#wt").checked});
    SESSION=d;$("#bar").style.display="none";
    let m='<div class="banner ok"><strong>Applied to '+esc(d.file_path)+'.</strong><br/>Backup saved at <span class="mono">'+esc(d.backup_path)+'</span>.';
    if(d.test_path)m+='<br/>Tests written to <span class="mono">'+esc(d.test_path)+'</span>.';
    $("#ack").innerHTML=m+"</div>";
  }catch(err){$("#ack").innerHTML='<div class="banner err">'+esc(err.message)+'</div>';$("#apply").disabled=false;$("#reject").disabled=false;}
};
$("#reject").onclick=async()=>{
  await jpost("/api/reject",{session_id:SESSION.id});
  $("#bar").style.display="none";
  $("#ack").innerHTML='<div class="banner warn">Change rejected. Your file was not modified.</div>';
};

/* ---- boot ---- */
buildPipe();
(async()=>{
  const t=await (await fetch("/api/target")).json(); TARGET=t;
  $("#path").textContent=t.path;
  const mode=t.mock?"offline mock provider":("model: "+t.model);
  $("#modePill").textContent=mode; $("#modeFoot").textContent=t.mock?"offline mock":"live model";
  const st=await (await fetch("/api/state")).json(); renderState(st);
  setFlow(1,DONE);
})();
</script>
</body>
</html>"""
