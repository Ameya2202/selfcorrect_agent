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

from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from .agent import SelfCorrectingAgent, Session
from .config import Config
from .memory import AgentMemory

_LOGO_PATH = Path(__file__).resolve().parent / "bitwise-logo.png"
_FAVICON_PNG = Path(__file__).resolve().parent / "favicon.png"
_FAVICON_SVG = Path(__file__).resolve().parent / "favicon.svg"

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

    @app.get("/bitwise-logo.png")
    def bitwise_logo():
        if not _LOGO_PATH.is_file():
            raise HTTPException(status_code=404, detail="Logo not found.")
        return FileResponse(_LOGO_PATH, media_type="image/png")

    @app.get("/favicon.svg")
    def favicon_svg():
        if not _FAVICON_SVG.is_file():
            raise HTTPException(status_code=404, detail="Favicon not found.")
        return FileResponse(
            _FAVICON_SVG,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=0, must-revalidate"},
        )

    @app.get("/favicon.png")
    @app.get("/favicon.ico")
    def favicon():
        if not _FAVICON_PNG.is_file():
            raise HTTPException(status_code=404, detail="Favicon not found.")
        return FileResponse(
            _FAVICON_PNG,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=0, must-revalidate"},
        )

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
# Single-file console UI (Bitwise light theme — Linear/Notion restraint)
# --------------------------------------------------------------------------- #
HTML_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Self-Correcting Agent</title>
<link rel="icon" href="/favicon.svg?v=3" type="image/svg+xml"/>
<link rel="icon" href="/favicon.png?v=3" type="image/png"/>
<link rel="apple-touch-icon" href="/favicon.png?v=3"/>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet"/>
<style>
  :root{
    --canvas:#FAFAFA; --surface:#FFFFFF;
    --ink:#111111; --mute:#5C5C5C; --faint:#8A8A8A;
    --border:#E8E8E8; --border-h:#D0D0D0;
    --red:#B11226; --red-h:#7A0C1A; --red-tint:#FDF1F2; --red-ring:rgba(177,18,38,.3);
    --ok:#1A7F37; --ok-tint:#EAF7EE;
    --warn:#9A6700; --warn-tint:#FFF8C5;
    --info:#0969DA; --info-tint:#DDF4FF;
    --danger-tint:#FDF1F2;
    --add:#EAF7EE; --del:#FDF1F2;
    --radius:12px;
    --ease:cubic-bezier(0.2, 0, 0, 1);
    --font:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
    --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box}
  html,body{height:100%}
  body{margin:0;background:var(--canvas);color:var(--ink);font:400 14px/1.5 var(--font);
    -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
  code,pre,.mono{font-family:var(--mono)}
  button,a,.tab,.btn,.act{transition:color 150ms var(--ease),background 150ms var(--ease),
    border-color 150ms var(--ease),box-shadow 150ms var(--ease),transform 150ms var(--ease),opacity 150ms var(--ease)}
  button:focus-visible,.btn:focus-visible,.act:focus-visible,.tab:focus-visible,.nav-toggle:focus-visible{
    outline:none;box-shadow:0 0 0 2px var(--red-ring)}
  .btn.primary:focus-visible,.act.primary:focus-visible{box-shadow:0 0 0 2px #fff,0 0 0 4px var(--red-ring)}

  .app{display:grid;grid-template-columns:var(--side-w,260px) 1fr;min-height:100vh;
    transition:grid-template-columns 200ms var(--ease)}
  .app.nav-collapsed{--side-w:72px}

  /* ---- sidebar ---- */
  .sidebar{background:var(--canvas);border-right:1px solid var(--border);padding:16px 14px;
    display:flex;flex-direction:column;gap:18px;position:sticky;top:0;height:100vh;overflow:auto;z-index:20;
    transition:padding 200ms var(--ease)}
  .brand-row{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}
  .brand{display:flex;flex-direction:column;gap:6px;min-width:0;text-decoration:none;color:inherit}
  .brand .logo-img{display:block;height:28px;width:auto;max-width:140px;object-fit:contain}
  .brand .name{font-size:13px;font-weight:600;color:var(--ink);line-height:1.25}
  .side-collapse{flex:0 0 auto;width:28px;height:28px;border-radius:6px;border:1px solid var(--border);
    background:#fff;color:var(--mute);display:inline-flex;align-items:center;justify-content:center;cursor:pointer;padding:0}
  .side-collapse:hover{background:#F5F5F5;border-color:var(--border-h);color:var(--ink)}
  .side-collapse svg{width:14px;height:14px;transition:transform 200ms var(--ease)}
  .app.nav-collapsed .side-collapse svg{transform:rotate(180deg)}
  .app.nav-collapsed .sidebar{padding:14px 10px;align-items:center}
  .app.nav-collapsed .brand-row{flex-direction:column;align-items:center;width:100%}
  .app.nav-collapsed .brand{align-items:center}
  .app.nav-collapsed .brand .logo-img{height:22px;max-width:48px;object-position:left}
  .app.nav-collapsed .brand .name,
  .app.nav-collapsed .side-h .t,
  .app.nav-collapsed .runs,
  .app.nav-collapsed .fstep .lbl,
  .app.nav-collapsed .btn .btn-label{display:none}
  .app.nav-collapsed .side-h{justify-content:center;margin:0}
  .app.nav-collapsed .flow{width:100%;align-items:center}
  .app.nav-collapsed .fstep{justify-content:center;padding:8px 0;border-left-color:transparent}
  .app.nav-collapsed .fstep.active{background:transparent}
  .app.nav-collapsed .fstep::after{left:50%;transform:translateX(-50%)}
  .app.nav-collapsed .side-btns{width:100%}
  .app.nav-collapsed .btn{padding:10px;justify-content:center}
  .side-h{display:flex;align-items:center;justify-content:space-between;margin-top:4px}
  .side-h .t{font-size:11px;letter-spacing:.08em;color:var(--mute);font-weight:600;text-transform:uppercase}
  .runs{font-size:12px;color:var(--faint);font-variant-numeric:tabular-nums}
  .flow{display:flex;flex-direction:column;gap:0;position:relative}
  .fstep{display:flex;gap:12px;padding:10px 8px 10px 10px;border-radius:8px;position:relative;
    border-left:2px solid transparent}
  .fstep .num{flex:0 0 auto;width:24px;height:24px;border-radius:50%;display:grid;place-items:center;
    font-size:11px;font-weight:600;color:var(--faint);border:1.5px solid var(--border-h);
    background:var(--surface);position:relative;z-index:1}
  .fstep .lbl .n{font-weight:500;font-size:13px;color:var(--mute);line-height:1.2}
  .fstep .lbl .s{font-size:12px;color:var(--faint);margin-top:2px}
  .fstep.active{border-left-color:var(--red);background:#fff}
  .fstep.active .num{background:var(--red);border-color:var(--red);color:#fff}
  .fstep.active .lbl .n{color:var(--ink);font-weight:600}
  .fstep.active .num.spinning::before{content:"";position:absolute;inset:-3px;border-radius:50%;
    border:1.5px solid transparent;border-top-color:#fff;animation:arc 0.9s linear infinite}
  .fstep.done .num{background:var(--ok);border-color:var(--ok);color:transparent}
  .fstep.done .num::after{content:"";position:absolute;width:10px;height:6px;border-left:1.5px solid #fff;
    border-bottom:1.5px solid #fff;transform:rotate(-45deg) translateY(-1px);
    animation:checkDraw 200ms var(--ease) both}
  .fstep.done .lbl .n{color:var(--ink)}
  .fstep::after{content:"";position:absolute;left:21px;top:34px;width:1px;height:calc(100% - 20px);
    background:var(--border);z-index:0}
  .fstep:last-child::after{display:none}

  .side-btns{display:flex;flex-direction:column;gap:8px;margin-top:auto}
  .btn{font:inherit;border:1px solid transparent;border-radius:8px;padding:10px 14px;cursor:pointer;
    display:flex;align-items:center;gap:8px;font-weight:600;font-size:13px;justify-content:center;
    background:var(--surface);color:var(--ink)}
  .btn svg{width:16px;height:16px;flex:0 0 auto}
  .btn.primary{background:var(--red);border-color:var(--red);color:#fff}
  .btn.primary:hover:not(:disabled){background:var(--red-h);border-color:var(--red-h)}
  .btn.primary:active:not(:disabled){transform:scale(0.98)}
  .btn.secondary{background:#fff;border-color:var(--border);color:var(--ink)}
  .btn.secondary:hover:not(:disabled){background:#F5F5F5;border-color:var(--border-h)}
  .btn.ghost{background:transparent;border-color:transparent;color:var(--mute);font-weight:500}
  .btn.ghost:hover:not(:disabled){color:var(--ink);background:#F5F5F5}
  .btn:disabled{opacity:.45;cursor:not-allowed}

  .nav-toggle{display:none;position:fixed;top:12px;left:12px;z-index:40;width:40px;height:40px;
    border-radius:8px;border:1px solid var(--border);background:#fff;align-items:center;justify-content:center;cursor:pointer}
  .nav-toggle svg{width:18px;height:18px}
  .scrim{display:none;position:fixed;inset:0;background:rgba(17,17,17,.28);z-index:15}

  /* ---- main ---- */
  main{padding:32px;max-width:1120px;width:100%;margin:0 auto;overflow:auto}
  .rise{animation:rise 300ms var(--ease) both}
  .rise:nth-child(1){animation-delay:0ms}
  .rise:nth-child(2){animation-delay:60ms}
  .rise:nth-child(3){animation-delay:120ms}
  .rise:nth-child(4){animation-delay:180ms}
  .rise:nth-child(5){animation-delay:240ms}
  .rise:nth-child(6){animation-delay:300ms}
  .rise:nth-child(7){animation-delay:360ms}

  .topbar{display:flex;align-items:flex-start;gap:16px;margin-bottom:20px}
  .topbar h1{font-size:20px;margin:0;font-weight:600;line-height:1.2;letter-spacing:-.01em}
  .topbar .path{color:var(--mute);font-size:12px;margin-top:6px;word-break:break-all}

  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
  .kpi{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px;
    transition:border-color 150ms var(--ease)}
  .kpi:hover{border-color:var(--border-h)}
  .kpi .k{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--mute);font-weight:600;line-height:1.2}
  .kpi .v{font-size:28px;font-weight:650;margin-top:10px;letter-spacing:-.02em;line-height:1.2;
    font-variant-numeric:tabular-nums;border-radius:6px}
  .kpi .v.empty{color:#C4C4C4;font-weight:500}
  .kpi .v.flash{animation:kpiFlash 400ms var(--ease)}
  .kpi .sub{font-size:12px;color:var(--faint);margin-top:4px}
  .v.g{color:var(--ok)} .v.b{color:var(--red)} .v.w{color:var(--warn)} .v.p{color:var(--ink)}

  .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);margin-top:16px;
    transition:border-color 150ms var(--ease);overflow:hidden}
  .card:hover{border-color:var(--border-h)}
  .card .hd{display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--border)}
  .card .hd h2{font-size:13px;margin:0;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--mute)}
  .card .hd .rt{margin-left:auto;font-size:12px;color:var(--faint);font-variant-numeric:tabular-nums}
  .card .bd{padding:16px 18px}
  .badge-pill{font-size:11px;color:var(--mute);background:var(--canvas);border:1px solid var(--border);
    padding:3px 8px;border-radius:999px;font-weight:600}

  .chart{width:100%;height:160px;display:block}
  .chart .draw{stroke-dasharray:1200;stroke-dashoffset:1200;animation:drawLine 600ms var(--ease) forwards}
  .chart-empty{color:var(--mute);font-size:13px;min-height:140px;display:flex;flex-direction:column;
    align-items:center;justify-content:center;gap:10px;text-align:center}
  .chart-empty .ghost-link{background:none;border:none;color:var(--red);font:600 13px var(--font);
    cursor:pointer;padding:4px 8px;border-radius:6px}
  .chart-empty .ghost-link:hover{background:var(--red-tint)}

  .pipe{display:flex;align-items:stretch;gap:0;flex-wrap:wrap}
  .pstate{flex:1;min-width:110px;background:#fff;border:1px solid var(--border);
    border-radius:10px;padding:14px 10px;text-align:center;position:relative}
  .pipe .conn{align-self:center;color:var(--faint);padding:0 4px;font-size:14px;line-height:1}
  .pstate .ic{width:28px;height:28px;margin:0 auto 8px;border-radius:8px;display:grid;place-items:center;
    background:var(--canvas);border:1px solid var(--border);color:var(--mute)}
  .pstate .ic svg{width:15px;height:15px}
  .pstate .nm{font-weight:600;font-size:13px;color:var(--mute)}
  .pstate .dt{font-size:11px;color:var(--faint);margin-top:3px;min-height:14px}
  .pstate.on-ok{background:var(--ok-tint);border-color:#B4E0C0}
  .pstate.on-ok .ic{background:#fff;border-color:#B4E0C0;color:var(--ok)}
  .pstate.on-ok .nm{color:var(--ok)}
  .pstate.on-fail{background:var(--danger-tint);border-color:#F0C4C8}
  .pstate.on-fail .ic{background:#fff;border-color:#F0C4C8;color:var(--red)}
  .pstate.on-fail .nm{color:var(--red)}
  .pstate.on-warn{background:var(--warn-tint);border-color:#E8D48A}
  .pstate.on-warn .ic{background:#fff;border-color:#E8D48A;color:var(--warn)}
  .pstate.on-warn .nm{color:var(--warn)}
  .pstate.on-info,.pstate.on-run{border-color:var(--red);color:var(--red)}
  .pstate.on-info .ic,.pstate.on-run .ic{border-color:var(--red);color:var(--red);background:var(--red-tint)}
  .pstate.on-info .nm,.pstate.on-run .nm{color:var(--red)}
  .pstate.on-run{animation:chipPulse 1.2s ease-in-out infinite}

  .step{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--border)}
  .step:last-child{border-bottom:0}
  .sbadge{flex:0 0 auto;width:22px;height:22px;border-radius:6px;display:grid;place-items:center;
    font-size:11px;font-weight:700}
  .b-ok{background:var(--ok-tint);color:var(--ok)} .b-fail{background:var(--danger-tint);color:var(--red)}
  .b-warn{background:var(--warn-tint);color:var(--warn)} .b-info{background:var(--info-tint);color:var(--info)}
  .step .n{font-weight:600;font-size:13px} .step .d{color:var(--mute);font-size:13px;white-space:pre-wrap}
  .step .a{margin-left:auto;color:var(--faint);font-size:11px;white-space:nowrap;font-variant-numeric:tabular-nums}

  .tabs{display:flex;gap:0;padding:0 8px;overflow:auto}
  .tab{padding:12px 14px;cursor:pointer;color:var(--mute);border-bottom:2px solid transparent;font-size:13px;
    font-weight:500;background:none;border-top:0;border-left:0;border-right:0;font-family:inherit}
  .tab.active{color:var(--ink);border-bottom-color:var(--red);font-weight:600}
  .tab:hover{color:var(--ink)}
  #pane{position:relative}
  #pane::after{content:"";pointer-events:none;position:absolute;left:0;right:0;bottom:0;height:28px;
    background:linear-gradient(transparent, #fff);opacity:.9}
  pre{margin:0;padding:14px 16px;overflow:auto;max-height:420px;font-size:12.5px;line-height:1.55;color:var(--ink)}
  .diff .ln{display:block;white-space:pre;border-left:2px solid transparent;padding-left:8px;margin-left:-2px}
  .diff .add{background:var(--add);border-left-color:var(--ok)}
  .diff .del{background:var(--del);border-left-color:var(--red)}
  .diff .hdr{color:var(--info)} .diff .meta{color:var(--faint)}

  .heur{display:flex;gap:12px;padding:12px 0;border-bottom:1px solid var(--border)}
  .heur:last-child{border-bottom:0}
  .heur .hid{flex:0 0 auto;font-family:var(--mono);font-size:11px;color:var(--red);
    background:var(--red-tint);border:1px solid #F0C4C8;border-radius:6px;padding:3px 7px;height:fit-content;font-weight:600}
  .heur .ht{font-size:13px;color:var(--ink)}
  .heur .hs{font-size:12px;color:var(--faint);margin-top:3px}

  .bar{display:flex;gap:10px;align-items:center;padding:14px 18px;flex-wrap:wrap}
  .act{font:inherit;border:1px solid var(--border);background:#fff;color:var(--ink);
    padding:9px 14px;border-radius:8px;cursor:pointer;font-weight:600;font-size:13px}
  .act:hover{border-color:var(--border-h);background:#F5F5F5}
  .act.primary{background:var(--red);border-color:var(--red);color:#fff}
  .act.primary:hover{background:var(--red-h);border-color:var(--red-h)}
  .act.primary:active{transform:scale(0.98)}
  .act:disabled{opacity:.5;cursor:not-allowed}
  label.chk{display:flex;gap:8px;align-items:center;color:var(--mute);font-size:12.5px}
  .banner{padding:12px 14px;border-radius:10px;margin-top:12px;font-size:13px;display:flex;gap:10px;align-items:flex-start;
    animation:bannerIn 240ms var(--ease)}
  .banner.ok{background:var(--ok-tint);border:1px solid #B4E0C0;color:var(--ok)}
  .banner.warn{background:var(--warn-tint);border:1px solid #E8D48A;color:var(--warn)}
  .banner.err{background:var(--danger-tint);border:1px solid #F0C4C8;color:var(--red)}
  .banner.info{background:var(--info-tint);border:1px solid #B6E0FE;color:var(--info)}
  .banner .bico{flex:0 0 auto;margin-top:1px}
  .spin{width:14px;height:14px;border:2px solid var(--border);border-top-color:var(--red);
    border-radius:50%;display:inline-block;animation:s .8s linear infinite;vertical-align:-2px;margin-right:6px}
  .muted{color:var(--mute)}
  .rationale{color:var(--mute);font-size:13px;margin:0;padding:0 18px 16px}
  .skel{display:inline-block;height:1.1em;width:3.2em;border-radius:4px;
    background:linear-gradient(90deg,#F0F0F0 0%,#E4E4E4 40%,#F0F0F0 80%);
    background-size:200% 100%;animation:shimmer 1.4s linear infinite}
  .loading-kpis .kpi .v{color:transparent!important}
  .loading-kpis .kpi .v::after{content:"";display:block;height:28px;width:56%;border-radius:4px;
    background:linear-gradient(90deg,#F0F0F0 0%,#E4E4E4 40%,#F0F0F0 80%);background-size:200% 100%;
    animation:shimmer 1.4s linear infinite}

  @keyframes s{to{transform:rotate(360deg)}}
  @keyframes arc{to{transform:rotate(360deg)}}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(26,127,55,.4)}70%{box-shadow:0 0 0 6px rgba(26,127,55,0)}100%{box-shadow:0 0 0 0 rgba(26,127,55,0)}}
  @keyframes checkDraw{from{opacity:0;transform:rotate(-45deg) scale(.6) translateY(-1px)}to{opacity:1;transform:rotate(-45deg) scale(1) translateY(-1px)}}
  @keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
  @keyframes kpiFlash{0%{background:var(--red-tint)}100%{background:transparent}}
  @keyframes drawLine{to{stroke-dashoffset:0}}
  @keyframes chipPulse{0%,100%{box-shadow:0 0 0 0 rgba(177,18,38,.0)}50%{box-shadow:0 0 0 3px rgba(177,18,38,.12)}}
  @keyframes bannerIn{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:translateY(0)}}
  @keyframes shimmer{0%{background-position:100% 0}100%{background-position:-100% 0}}

  @media(max-width:1024px){.kpis{grid-template-columns:repeat(2,1fr)}}
  @media(max-width:880px){
    .app,.app.nav-collapsed{grid-template-columns:1fr;--side-w:260px}
    .nav-toggle{display:inline-flex}
    .side-collapse{display:none}
    .sidebar{position:fixed;left:0;top:0;transform:translateX(-105%);width:min(280px,86vw);
      transition:transform 200ms var(--ease);box-shadow:none;align-items:stretch!important;padding:20px 16px!important}
    .sidebar.open{transform:translateX(0)}
    .app.nav-collapsed .brand .logo-img{height:28px;max-width:140px}
    .app.nav-collapsed .brand .name,
    .app.nav-collapsed .side-h .t,
    .app.nav-collapsed .runs,
    .app.nav-collapsed .fstep .lbl,
    .app.nav-collapsed .btn .btn-label{display:revert}
    .app.nav-collapsed .fstep{justify-content:flex-start;padding:10px 8px 10px 10px}
    .app.nav-collapsed .btn{padding:10px 14px;justify-content:center}
    .scrim.show{display:block}
    main{padding:64px 16px 32px}
  }
  @media(max-width:520px){.kpis{grid-template-columns:1fr}}

  @media(prefers-reduced-motion:reduce){
    *,*::before,*::after{animation:none!important;transition:none!important}
  }
</style>
</head>
<body>
<button class="nav-toggle" id="navToggle" aria-label="Open navigation" aria-controls="sidebar" aria-expanded="false">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>
</button>
<div class="scrim" id="scrim" hidden></div>
<div class="app" id="appShell">
  <nav class="sidebar" id="sidebar" aria-label="Agent flow">
    <div class="brand-row">
      <div class="brand">
        <img class="logo-img" src="/bitwise-logo.png" width="140" height="44" alt="bitwise"/>
        <div class="name">Self-Correcting Agent</div>
      </div>
      <button class="side-collapse" id="sideCollapse" type="button" aria-label="Collapse navigation" aria-controls="sidebar" aria-expanded="true" title="Collapse navigation">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6 9 12l6 6"/></svg>
      </button>
    </div>
    <div class="side-h">
      <span class="t">Agent Flow</span>
      <span class="runs" id="runs">0 runs</span>
    </div>
    <div class="flow" id="flow" role="list">
      <div class="fstep" data-step="1" role="listitem"><div class="num">1</div>
        <div class="lbl"><div class="n">Load Input</div><div class="s">Read target file</div></div></div>
      <div class="fstep" data-step="2" role="listitem"><div class="num">2</div>
        <div class="lbl"><div class="n">Run Session</div><div class="s">Execute correction loop</div></div></div>
      <div class="fstep" data-step="3" role="listitem"><div class="num">3</div>
        <div class="lbl"><div class="n">Dreaming Cycle</div><div class="s">Consolidate memory</div></div></div>
      <div class="fstep" data-step="4" role="listitem"><div class="num">4</div>
        <div class="lbl"><div class="n">Review Results</div><div class="s">Inspect heuristics</div></div></div>
    </div>
    <div class="side-btns">
      <button class="btn secondary" id="bLoad" type="button" title="Load Input">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7h5l2 2h11v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/></svg>
        <span class="btn-label">Load Input</span></button>
      <button class="btn primary" id="bRun" type="button" disabled title="Run Session">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M8 5v14l11-7z"/></svg>
        <span class="btn-label">Run Session</span></button>
      <button class="btn secondary" id="bDream" type="button" disabled title="Run Dreaming">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/><path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/><path d="M17.599 6.5a3 3 0 0 0 .399-1.375"/><path d="M6.003 5.125A3 3 0 0 0 6.401 6.5"/><path d="M3.477 10.896a4 4 0 0 1 .585-.396"/><path d="M19.938 10.5a4 4 0 0 1 .585.396"/><path d="M6 18a4 4 0 0 1-1.967-.516"/><path d="M19.967 17.484A4 4 0 0 1 18 18"/></svg>
        <span class="btn-label">Run Dreaming</span></button>
      <button class="btn ghost" id="bReset" type="button" title="Reset">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>
        <span class="btn-label">Reset</span></button>
    </div>
  </nav>

  <main>
    <div class="topbar rise">
      <div>
        <h1>Self-Correcting Agent</h1>
        <div class="path mono" id="path">loading…</div>
      </div>
    </div>

    <div id="status" class="rise" aria-live="polite"></div>

    <div class="kpis rise" id="kpiRow" aria-live="polite">
      <div class="kpi"><div class="k">Coverage</div><div class="v empty" id="kCov">—</div><div class="sub">final green suite</div></div>
      <div class="kpi"><div class="k">Attempts to Green</div><div class="v empty" id="kAtt">—</div><div class="sub">last session</div></div>
      <div class="kpi"><div class="k">False Incidents</div><div class="v" id="kFalse">0</div><div class="sub">bad-test diagnoses</div></div>
      <div class="kpi"><div class="k">Heuristics Promoted</div><div class="v p" id="kHeur">0</div><div class="sub">durable memory</div></div>
    </div>

    <div class="card rise">
      <div class="hd"><h2>Success Rate Across Cycles</h2><span class="rt" id="chartRt">—</span></div>
      <div class="bd" id="chartWrap">
        <div class="chart-empty">
          <span>No cycles yet — run a session to populate.</span>
          <button type="button" class="ghost-link" id="chartRunLink">Run Session</button>
        </div>
      </div>
    </div>

    <div class="card rise">
      <div class="hd"><h2>Agent Pipeline</h2></div>
      <div class="bd">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap">
          <strong style="font-size:13px;font-weight:600;color:var(--ink)">In-Session Self-Correction Loop</strong>
          <span class="badge-pill">6 States</span>
        </div>
        <div class="pipe" id="pipe"></div>
      </div>
    </div>

    <div class="card rise">
      <div class="hd"><h2>Cycle Log</h2><span class="rt" id="outcome"></span></div>
      <div class="bd" id="steps"><span class="muted">Run a session to see the Generate → Run → Diagnose → Correct → Verify → Stop trace.</span></div>
      <p class="rationale" id="rationale"></p>
    </div>

    <div class="card rise">
      <div class="hd" style="padding:0"><div class="tabs" role="tablist">
        <button type="button" class="tab active" data-t="diff" role="tab" aria-selected="true">Proposed change</button>
        <button type="button" class="tab" data-t="tests" role="tab" aria-selected="false">Generated tests</button>
        <button type="button" class="tab" data-t="full" role="tab" aria-selected="false">Improved file</button>
        <button type="button" class="tab" data-t="input" role="tab" aria-selected="false">Input</button>
      </div></div>
      <div id="pane"><pre class="muted">—</pre></div>
      <div class="bar" id="bar" style="display:none;border-top:1px solid var(--border)">
        <label class="chk"><input type="checkbox" id="wt" checked/> also save the test file</label>
        <span style="flex:1"></span>
        <button class="act" id="reject" type="button">Reject</button>
        <button class="act primary" id="apply" type="button">Apply to file</button>
      </div>
      <div id="ack" style="padding:0 18px 16px" aria-live="polite"></div>
    </div>

    <div class="card rise">
      <div class="hd"><h2>Promoted Heuristics</h2><span class="rt" id="heurRt">memory</span></div>
      <div class="bd" id="heur"><span class="muted">None yet. Run a session, then Run Dreaming to consolidate what was learned.</span></div>
    </div>
  </main>
</div>

<script>
const $=s=>document.querySelector(s);
const esc=t=>(t==null?"":String(t)).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
let SESSION=null, STATE=null, TARGET=null, loaded=false;
const REDUCE=window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const EMPTY="—";

/* ---- mobile nav + desktop collapse ---- */
const appShell=$("#appShell"), sidebar=$("#sidebar"), scrim=$("#scrim"), navToggle=$("#navToggle"), sideCollapse=$("#sideCollapse");
function closeNav(){sidebar.classList.remove("open");scrim.classList.remove("show");scrim.hidden=true;navToggle.setAttribute("aria-expanded","false")}
function openNav(){sidebar.classList.add("open");scrim.classList.add("show");scrim.hidden=false;navToggle.setAttribute("aria-expanded","true")}
navToggle.onclick=()=>sidebar.classList.contains("open")?closeNav():openNav();
scrim.onclick=closeNav;
function setCollapsed(on){
  appShell.classList.toggle("nav-collapsed", !!on);
  sideCollapse.setAttribute("aria-expanded", on?"false":"true");
  sideCollapse.setAttribute("aria-label", on?"Expand navigation":"Collapse navigation");
  sideCollapse.title = on?"Expand navigation":"Collapse navigation";
  try{localStorage.setItem("sc-nav-collapsed", on?"1":"0")}catch(_){}
}
sideCollapse.onclick=()=>setCollapsed(!appShell.classList.contains("nav-collapsed"));
try{ if(localStorage.getItem("sc-nav-collapsed")==="1") setCollapsed(true); }catch(_){}

/* ---- pipeline states ---- */
const STATES=[
  ["Generate","M13 2 4 14h6l-1 8 9-12h-6z"],
  ["Run","M8 5v14l11-7z"],
  ["Diagnose","M11 4a7 7 0 1 0 4.2 12.6l4.1 4.1 1.4-1.4-4.1-4.1A7 7 0 0 0 11 4z"],
  ["Correct","M14 6l4 4-8 8H6v-4z M17 3l4 4"],
  ["Verify","M20 6 9 17l-5-5"],
  ["Stop","M6 6h12v12H6z"],
];
function buildPipe(){
  const p=$("#pipe"); p.innerHTML="";
  STATES.forEach(([nm,d],i)=>{
    const el=document.createElement("div"); el.className="pstate"; el.id="ps-"+nm;
    el.innerHTML=`<div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg></div>
      <div class="nm">${nm}</div><div class="dt" id="dt-${nm}"></div>`;
    p.appendChild(el);
    if(i<STATES.length-1){const c=document.createElement("div");c.className="conn";c.setAttribute("aria-hidden","true");c.textContent="→";p.appendChild(c);}
  });
}
function resetPipe(){STATES.forEach(([nm])=>{const e=$("#ps-"+nm);if(e)e.className="pstate";const d=$("#dt-"+nm);if(d)d.textContent="";});}
const CLS={ok:"on-ok",fail:"on-fail",warn:"on-warn",info:"on-info"};
function litePipe(steps){
  resetPipe();
  const last={};
  steps.forEach(s=>{last[s.name]=s;});
  STATES.forEach(([nm],i)=>{
    const s=last[nm]; if(!s)return;
    const apply=()=>{
      const e=$("#ps-"+nm); if(e)e.classList.add(CLS[s.status]||"on-info");
      const d=$("#dt-"+nm); if(d)d.textContent="try "+s.attempt;
    };
    if(REDUCE) apply(); else setTimeout(apply, i*150);
  });
}

/* ---- flow stepper ---- */
function setFlow(step, done){
  document.querySelectorAll(".fstep").forEach(f=>{
    const n=+f.dataset.step;
    const active=n===step;
    f.classList.toggle("active",active);
    f.classList.toggle("done", done.includes(n));
    if(active) f.setAttribute("aria-current","step"); else f.removeAttribute("aria-current");
    const num=f.querySelector(".num");
    if(num) num.classList.toggle("spinning", active && $("#kpiRow")?.classList.contains("loading-kpis"));
  });
}
let DONE=[];
function advance(step){ if(!DONE.includes(step))DONE.push(step); setFlow(step, DONE); }

/* ---- KPIs + chart ---- */
function kpi(id,val,cls){
  const e=$("#"+id); if(!e)return;
  const empty=val===EMPTY||val==="--"||val===""||val==null;
  const next=empty?EMPTY:String(val);
  const changed=e.textContent!==next;
  e.textContent=next;
  e.className="v"+(empty?" empty":"")+(cls?" "+cls:"");
  if(changed && !empty && !REDUCE){
    e.classList.remove("flash"); void e.offsetWidth; e.classList.add("flash");
  }
}
function renderState(st){
  STATE=st;
  $("#runs").textContent=st.cycle_count+" run"+(st.cycle_count===1?"":"s");
  kpi("kFalse", st.false_incidents_total, st.false_incidents_total?"b":"");
  kpi("kHeur", st.heuristics_promoted, "p");
  renderChart(st.success_curve);
  renderHeur(st.heuristics);
}
function renderSession(d){
  kpi("kCov", d.final_total? d.coverage+"%" : EMPTY, d.coverage>=100?"g":(d.coverage>0?"w":""));
  kpi("kAtt", d.attempts_to_green!=null? d.attempts_to_green : EMPTY,
      d.attempts_to_green===1?"g":(d.attempts_to_green?"w":""));
}
function chartEmptyHtml(){
  return `<div class="chart-empty"><span>No cycles yet — run a session to populate.</span>
    <button type="button" class="ghost-link" id="chartRunLink">Run Session</button></div>`;
}
function wireChartLink(){
  const a=$("#chartRunLink"); if(!a)return;
  a.onclick=()=>{ if(!$("#bRun").disabled) $("#bRun").click(); else if(!$("#bLoad").disabled) $("#bLoad").click(); };
}
function renderChart(curve){
  const wrap=$("#chartWrap");
  if(!curve||!curve.length){wrap.innerHTML=chartEmptyHtml();$("#chartRt").textContent=EMPTY;wireChartLink();return;}
  $("#chartRt").textContent=curve[curve.length-1]+"% overall";
  const W=760,H=160,pad=28, n=curve.length;
  const x=i=> n===1? W/2 : pad + i*(W-2*pad)/(n-1);
  const y=v=> H-pad - (v/100)*(H-2*pad);
  let dots="",line="";
  curve.forEach((v,i)=>{line+=(i?"L":"M")+x(i).toFixed(1)+" "+y(v).toFixed(1)+" ";
    dots+=`<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="3" fill="#B11226"/>`;});
  const area="M"+x(0).toFixed(1)+" "+(H-pad)+" "+line.replace(/^M/,"L")+"L"+x(n-1).toFixed(1)+" "+(H-pad)+" Z";
  const grid=[0,25,50,75,100].map(g=>`<line x1="${pad}" y1="${y(g)}" x2="${W-pad}" y2="${y(g)}" stroke="#E8E8E8" stroke-dasharray="2 4"/><text x="2" y="${y(g)+3}" fill="#5C5C5C" font-size="11" font-family="Inter,sans-serif">${g}%</text>`).join("");
  wrap.innerHTML=`<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Success rate across cycles">
    ${grid}<path d="${area}" fill="rgba(177,18,38,.06)"/>
    <path class="draw" d="${line}" fill="none" stroke="#B11226" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>${dots}</svg>`;
}
function renderHeur(hs){
  const box=$("#heur");
  if(!hs||!hs.length){box.innerHTML='<span class="muted">None yet. Run a session, then Run Dreaming to consolidate what was learned.</span>';$("#heurRt").textContent="0 promoted";return;}
  $("#heurRt").textContent=hs.length+" promoted";
  box.innerHTML=hs.map(h=>`<div class="heur"><span class="hid">${esc(h.id)}</span>
    <div><div class="ht">${esc(h.text)}</div><div class="hs">from ${esc(h.source)} · reinforced ${h.observations}×</div></div></div>`).join("");
}

/* ---- cycle log ---- */
function badge(s){const m={ok:["b-ok","✓"],fail:["b-fail","✕"],warn:["b-warn","!"],info:["b-info","i"]};const [c,ch]=m[s]||m.info;return `<span class="sbadge ${c}" aria-hidden="true">${ch}</span>`;}
function renderSteps(steps){
  $("#steps").innerHTML=steps.map(s=>`<div class="step">${badge(s.status)}
    <div><div class="n">${esc(s.name)}</div><div class="d">${esc(s.detail)}</div></div>
    <div class="a">try ${s.attempt}</div></div>`).join("");
}
function renderOutcome(d){
  const st=d.status==="ready"?'<span style="color:var(--ok)">READY</span>'
    :d.status==="escalate"?'<span style="color:var(--warn)">ESCALATED</span>'
    :'<span style="color:var(--red)">ERROR</span>';
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
  document.querySelectorAll(".tab").forEach(t=>{
    const on=t.dataset.t===w; t.classList.toggle("active",on); t.setAttribute("aria-selected",on?"true":"false");
  });
  const p=$("#pane");
  if(w==="input"){p.innerHTML=`<pre class="mono">${esc(TARGET&&TARGET._src||"")||"(load input first)"}</pre>`;return;}
  if(!SESSION){p.innerHTML='<pre class="muted">—</pre>';return;}
  if(w==="diff")p.innerHTML=diffHtml(SESSION.diff);
  else if(w==="tests")p.innerHTML=`<pre class="mono">${esc(SESSION.tests_code)}</pre>`;
  else p.innerHTML=`<pre class="mono">${esc(SESSION.improved_code)}</pre>`;
}
document.querySelectorAll(".tab").forEach(t=>t.onclick=()=>showPane(t.dataset.t));

function bannerHtml(cls, html){
  const icons={ok:'<svg class="bico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M20 6 9 17l-5-5"/></svg>',
    warn:'<svg class="bico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 9v4M12 17h.01"/><path d="M10.3 4.3 2.5 18a2 2 0 0 0 1.7 3h16a2 2 0 0 0 1.7-3L13.7 4.3a2 2 0 0 0-3.4 0z"/></svg>',
    err:'<svg class="bico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M18 6 6 18M6 6l12 12"/></svg>',
    info:'<svg class="bico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v4h1"/></svg>'};
  return `<div class="banner ${cls}">${icons[cls]||icons.info}<div>${html}</div></div>`;
}
let bannerTimer=null;
function showStatus(cls, html, autoDismiss){
  $("#status").innerHTML=bannerHtml(cls, html);
  if(bannerTimer) clearTimeout(bannerTimer);
  if(autoDismiss){bannerTimer=setTimeout(()=>{const b=$("#status .banner");if(b){b.style.opacity="0";setTimeout(()=>{$("#status").innerHTML=""},200)}}, autoDismiss)}
}

/* ---- actions ---- */
async function jpost(url,body){const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body||{})});
  if(!r.ok){let e={};try{e=await r.json()}catch(_){}throw new Error(e.detail||r.statusText);}return r.json();}

$("#bLoad").onclick=async()=>{
  $("#status").innerHTML=""; closeNav();
  try{
    const t=await (await fetch("/api/target")).json(); TARGET=t;
    const src=await (await fetch("/api/source")).json().catch(()=>null);
    TARGET._src = src&&src.source || "";
    showPane("input");
    loaded=true; $("#bRun").disabled=false; advance(1); setFlow(2,DONE);
    showStatus("info",'Loaded <span class="mono">'+esc(t.path)+'</span>. Ready to run a session.');
  }catch(err){showStatus("err","Load failed: "+esc(err.message));}
};

$("#bRun").onclick=async()=>{
  $("#status").innerHTML="";$("#ack").innerHTML="";$("#bar").style.display="none"; closeNav();
  $("#steps").innerHTML='<span class="spin"></span> running the self-correction cycle…';
  $("#kpiRow").classList.add("loading-kpis");
  setFlow(2,DONE);
  try{
    const d=await jpost("/api/run",{}); SESSION=d;
    $("#kpiRow").classList.remove("loading-kpis");
    renderSteps(d.steps); litePipe(d.steps); renderOutcome(d); renderSession(d);
    if(d.state)renderState(d.state);
    showPane("diff"); advance(1); advance(2); $("#bDream").disabled=false;
    if(d.status==="ready"&&d.changed){$("#bar").style.display="flex"; showStatus("ok","Session ready — review the proposed change and apply when satisfied.",5000);}
    else if(d.status==="ready")showStatus("warn","File already passes its generated tests — no change needed.");
    else if(d.status==="escalate")showStatus("warn","Could not reach a trustworthy green state within the attempt budget. Escalated for review.");
  }catch(err){$("#kpiRow").classList.remove("loading-kpis");$("#steps").innerHTML="";showStatus("err","Run failed: "+esc(err.message));}
};

$("#bDream").onclick=async()=>{
  $("#status").innerHTML=""; setFlow(3,DONE); closeNav();
  try{
    const d=await jpost("/api/dream",{}); renderState(d.state); advance(3); advance(4); setFlow(4,DONE);
    const n=d.result.promoted_now;
    showStatus(n?"ok":"info","Dreaming complete — reviewed "+d.result.observations_reviewed+" observation(s), promoted "+n+" new heuristic(s).", n?5000:0);
  }catch(err){showStatus("err","Dreaming failed: "+esc(err.message));}
};

$("#bReset").onclick=async()=>{
  closeNav();
  try{const d=await jpost("/api/reset",{});
    SESSION=null;DONE=[];loaded=false;
    $("#bRun").disabled=true;$("#bDream").disabled=true;
    renderState(d.state); resetPipe(); setFlow(1,[]);
    kpi("kCov",EMPTY,"");kpi("kAtt",EMPTY,"");
    $("#steps").innerHTML='<span class="muted">Run a session to see the trace.</span>';
    $("#outcome").innerHTML="";$("#rationale").textContent="";$("#pane").innerHTML='<pre class="muted">—</pre>';
    $("#bar").style.display="none";$("#ack").innerHTML="";
    showStatus("info","Reset — sessions and memory cleared.");
  }catch(err){showStatus("err","Reset failed: "+esc(err.message));}
};

$("#apply").onclick=async()=>{
  $("#apply").disabled=true;$("#reject").disabled=true;
  try{const d=await jpost("/api/apply",{session_id:SESSION.id,write_tests:$("#wt").checked});
    SESSION=d;$("#bar").style.display="none";
    let m='<strong>Applied to '+esc(d.file_path)+'.</strong><br/>Backup saved at <span class="mono">'+esc(d.backup_path)+'</span>.';
    if(d.test_path)m+='<br/>Tests written to <span class="mono">'+esc(d.test_path)+'</span>.';
    $("#ack").innerHTML=bannerHtml("ok", m);
    showStatus("ok","Change applied successfully.",5000);
  }catch(err){$("#ack").innerHTML=bannerHtml("err",esc(err.message));$("#apply").disabled=false;$("#reject").disabled=false;}
};
$("#reject").onclick=async()=>{
  await jpost("/api/reject",{session_id:SESSION.id});
  $("#bar").style.display="none";
  $("#ack").innerHTML=bannerHtml("warn","Change rejected. Your file was not modified.");
};

/* ---- boot ---- */
buildPipe();
wireChartLink();
(async()=>{
  const t=await (await fetch("/api/target")).json(); TARGET=t;
  $("#path").textContent=t.path;
  const st=await (await fetch("/api/state")).json(); renderState(st);
  setFlow(1,DONE);
})();
</script>
</body>
</html>
"""
