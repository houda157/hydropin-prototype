"""Board tab of the twin viewer (bench twin, math note §10).

The browser cannot run EPANET, so the twin is solved here on a grid of hand settings
(R1 = R2, V1 = V2, one leak tap with a calibrated orifice) and the page looks the state up.
Every number shown in the tab is a run_board() result; nothing is interpolated.
A 5-minute recording through the full measurement chain  is embedded for replay.
"""

from __future__ import annotations

import numpy as np
from matplotlib.colors import to_hex

from hydropin_sim.network import prototype as pb
from hydropin_sim.network.prototype import BoardSetting, board_spec
from hydropin_sim.steady.board import LPM, M_PER_BAR, run_board
from hydropin_sim.viz import style as st

R_GRID = [40, 45, 50, 55, 60, 65, 70, 75]
V_GRID = [round(v, 1) for v in np.arange(70.0, 81.51, 0.5)]
D_GRID = [0.1, 0.2, 0.3, 0.5, 0.8, 1.2]           # orifice diameters (mm)
LEAKS = ["none"] + list(pb.TAPS)
DRAW_NODES = ["IN", "T0", "E1", "R1a", "R1b", "TL1", "P1a", "P1", "P1b", "V1a", "V1b", "E3",
              "E2", "R2a", "R2b", "TL2", "P2a", "P2", "P2b", "TL3", "V2a", "V2b", "T1"]


def _key(r, v, leak, d):
    return f"{r}|{v}|{leak}|{d}"


def board_data(P, rec, quiet, change_sigma):
    """Grid of twin states + geometry + the embedded recording."""
    b = P.prototype
    spec, _ = board_spec(P, BoardSetting(theta={"R1": 65.0, "R2": 65.0, "V1": 78.0, "V2": 78.0}))
    draw = [p for p in spec.pipes if p.start in DRAW_NODES and p.end in DRAW_NODES]
    states = {}
    for r in R_GRID:
        for v in V_GRID:
            base = {"R1": float(r), "R2": float(r), "V1": v, "V2": v}
            for leak in LEAKS:
                for d in ([0] if leak == "none" else D_GRID):
                    st_ = BoardSetting(theta=dict(base), leak_d={} if leak == "none" else {leak: d * 1e-3})
                    s = run_board(P, st_)
                    row = [s.p_bar["P1"], s.p_bar["P2"], s.q_f0 * LPM, s.q_leak * LPM, s.q_out["RET"] * LPM,
                           s.p_max / M_PER_BAR]
                    row += [s.pressure.get(n, 0.0) / M_PER_BAR for n in DRAW_NODES]
                    row += [s.flow.get(p.id, 0.0) * LPM for p in draw]      # L/min, start → end
                    states[_key(r, v, leak, d)] = [round(float(x), 4) for x in row]
    pos = {n.id: (round(n.x * 100, 2), round(n.y * 100, 2)) for n in spec.nodes}
    links = [[p.start, p.end] for p in draw]
    cmap = [to_hex(st.SEQ_CMAP(x)) for x in np.linspace(0.08, 1.0, 9)]
    # recording (published values, every second); true values = mean over the same 1-s window
    p1, p2 = rec["P1"], rec["P2"]
    n = min(len(p1.value), len(p2.value))

    def true_means(raw):
        w = np.floor(raw.time / b.FW_T_AVG.v).astype(int)
        return [float(raw.meta["p_true"][w == k].mean()) / M_PER_BAR for k in np.unique(w)][:n]

    recd = dict(t=[float(x) for x in p1.time[:n]],
                p1=[round(float(x) / M_PER_BAR, 5) for x in p1.value[:n]],
                p2=[round(float(x) / M_PER_BAR, 5) for x in p2.value[:n]],
                p1t=[round(x, 5) for x in true_means(rec["P1_raw"])],
                p2t=[round(x, 5) for x in true_means(rec["P2_raw"])],
                fcal=[round(float(x) * LPM, 4) for x in rec["F0_cal"].q_hat[:n]],
                ffw=[round(float(x) * LPM, 4) for x in rec["F0_fw"].q_hat[:n]],
                ftrue=[round(float(x) * LPM, 4) for x in rec["F0_cal"].q_true[:n]])
    # detection thresholds: κ σ of the change between two consecutive 30-s windows (bench noise model)
    q1, q2 = quiet["P1"].value, quiet["P2"].value
    m = min(len(q1), len(q2))
    kap = P.decision.KAPPA.v
    thr = dict(p1=kap * change_sigma(q1, 30) / M_PER_BAR * 1e3,
               diff=kap * change_sigma(q1[:m] - q2[:m], 30) / M_PER_BAR * 1e3,
               f0=kap * change_sigma(quiet["F0_cal"].q_hat, 30) * LPM)
    return dict(link_ids=[p.id for p in draw], states=states, R=R_GRID, V=V_GRID, D=D_GRID, nodes=DRAW_NODES, pos=pos, links=links,
                xy={k: [round(x * 100, 2), round(y * 100, 2)] for k, (x, y) in pb.XY.items()},
                cmap=cmap, safe=round(b.PB_SAFE_FRAC.v * b.PS_P_MAX.v, 3), pmax_sensor=b.PS_P_MAX.v,
                theta_closed=b.THETA_CLOSED.v, rec=recd,
                thr={k: round(float(v), 4) for k, v in thr.items()})


SECTION = r"""
<div id="boardview" class="wrap" style="display:none">
 <div>
  <div class="card"><h2>Prototype bench twin – set the valves, open a leak</h2>
   <svg id="board" viewBox="-30 -50 108 55" width="100%"></svg>
   <div class="ctl">
    <label>R1 = R2 (restrictors) <b id="rv"></b><input id="rs" type="range" min="0" max="7" value="5"></label>
    <label>V1 = V2 (end valves) <b id="vv"></b><input id="vs" type="range" min="0" max="23" value="17"></label>
    <label>Leak tap <select id="ls"><option value="none">none</option><option>L1</option><option>L2</option><option>L3</option></select></label>
    <label>Orifice <b id="dv"></b><input id="ds" type="range" min="0" max="5" value="3"></label>
   </div>
   <p class="hint">Angles: 0° = open, __THC__° = shut. Leaks are calibrated holes at the end of the tap tube (bench-twin recommendation). All values are EPANET results of the twin, solved in advance for every setting of the sliders.</p>
  </div>
  <div class="card" style="margin-top:18px"><h2>Five minutes as the ESP32 would publish them (L1 opens at 150 s)</h2>
   <svg id="rchart" viewBox="0 0 640 300" width="100%"></svg>
   <div class="controls"><button id="rplay">▶ Play</button><input id="rt" type="range" min="0" max="299" value="299"><span id="rclock" style="min-width:70px;text-align:right;color:var(--ink2)"></span></div>
  </div>
 </div>
 <div>
  <div class="card"><h2>Readings (true values from the twin)</h2>
   <div class="kpis"><div class="kpi"><div class="v" id="bp1">–</div><div class="l">P1 (bar)</div></div>
   <div class="kpi"><div class="v" id="bp2">–</div><div class="l">P2 (bar)</div></div>
   <div class="kpi"><div class="v" id="bf0">–</div><div class="l">F0 (L/min)</div></div></div>
   <div class="kpis" style="margin-top:10px"><div class="kpi"><div class="v" id="bql">–</div><div class="l">leak (L/min)</div></div>
   <div class="kpi"><div class="v" id="bqp">–</div><div class="l">leak share</div></div>
   <div class="kpi"><div class="v" id="bpm">–</div><div class="l">highest pressure (bar)</div></div></div>
   <div id="bsafe" class="badge b-log" style="margin-top:12px"></div>
  </div>
  <div class="card" style="margin-top:18px"><h2>What the sensors see (change vs. the same setting without leak)</h2>
   <ul class="list" id="bdelta"></ul>
   <div id="bdiag" class="badge b-log" style="margin-top:12px"></div>
   <p class="hint" id="bnote"></p>
  </div>
  <div class="card" style="margin-top:18px"><h2>Branch signatures (ΔP1, ΔP2)</h2><svg id="sig" viewBox="0 0 320 240" width="100%"></svg>
   <p class="hint">Direction of the change for a 0.5 mm leak at each tap, same valve setting. L2 and L3 overlap: with P1, P2 and F0 they cannot be told apart.</p></div>
 </div>
</div>
"""

SECTION3D = r"""
<div id="view3d" class="wrap" style="display:none">
 <div>
  <div class="card"><h2>The prototype in 3D – drag to turn, scroll to zoom, right-drag to move</h2>
   <div id="host3d" style="position:relative;height:620px;border-radius:10px;overflow:hidden;background:#f4f3ef"></div>
   <div class="ctl" style="grid-template-columns:1fr 1fr 1fr 1fr">
    <label>R1 = R2 <b id="rv3"></b><input id="rs3" type="range" min="0" max="7" value="5"></label>
    <label>V1 = V2 <b id="vv3"></b><input id="vs3" type="range" min="0" max="23" value="16"></label>
    <label>Leak tap <select id="ls3"><option value="none">none</option><option>L1</option><option>L2</option><option>L3</option></select></label>
    <label>Hole <b id="dv3"></b><input id="ds3" type="range" min="0" max="5" value="3"></label>
   </div>
   <div class="controls" style="flex-wrap:wrap">
    <label class="chk"><input type="checkbox" id="c3col" checked> pipes coloured by pressure</label>
    <label class="chk"><input type="checkbox" id="c3lab" checked> labels</label>
    <label class="chk"><input type="checkbox" id="c3rot"> turn slowly</label>
    <span style="flex:1"></span>
    <button data-view="home">Whole bench</button><button data-view="board">Board</button><button data-view="top">From above</button><button data-view="bucket">Pump + bucket</button>
   </div>
  </div>
  <div class="card" style="margin-top:18px"><h2>Pressure waves – slow motion</h2>
   <div class="controls" style="flex-wrap:wrap;margin-top:0">
    <label class="chk">Event <select id="wev"><option value="">none (steady view)</option></select></label>
    <button id="wplay">▶ Play</button>
    <label class="chk">Speed <select id="wspd"><option value="50">50× slower</option><option value="200" selected>200× slower</option><option value="1000">1000× slower</option></select></label>
    <label class="chk"><input type="checkbox" id="wads" checked> ADS1115 samples (860 SPS)</label>
   </div>
   <div class="controls"><input id="wt" type="range" min="0" max="1" value="0"><span id="wclock" style="min-width:110px;text-align:right;color:var(--ink2)"></span></div>
   <p class="hint" id="wscale" style="margin:4px 0 0"></p>
   <svg id="wchart" viewBox="0 0 640 230" width="100%"></svg>
   <p class="hint" id="wnote">Pick an event: the pipes turn red where the pressure rises and blue where it falls, at the speed of the wave (≈ 150 m/s in the PE pipes, 58 m/s in the soft hose), slowed down so the eye can follow. Computed by the transient solver at R1 = R2 = __WR__°, V1 = V2 = __WV__° without leak; the valve sliders above do not apply while a wave plays.</p>
  </div>
 </div>
 <div>
  <div class="card"><h2>What you are looking at</h2>
   <ul class="list" id="r3"></ul>
   <p class="hint">Stripes in the pipes move at the real water speed from the twin (a few cm/s). Drops fall from the open tap and from the return pipe at a rate that follows their flow. The laptop shows what the dashboard would display.</p>
  </div>
  <div class="card" style="margin-top:18px"><h2>Built from</h2>
   <ul class="plain">
    <li>Parts and connections: hardware list + sketch of 18 Nov 2026 (same geometry file as the simulation).</li>
    <li>Pipe colours, flows, readings: the bench twin, solved for every slider position.</li>
   </ul>
   <h2 style="margin-top:14px">Guessed (to replace with photos / measurements)</h2>
   <ul class="plain">
    <li>Board flat on a 75 cm table (confirmed); bucket on the floor under the front edge, pump beside it.</li>
    <li>Positions on the board read off the sketch (± 2 cm).</li>
    <li>Shapes of the R365, Swagelok sensors, flow sensor and valves: typical dimensions, no photos yet.</li>
    <li>Electronics box, adapters and laptop placement, cable routes.</li>
    <li>On a flat board, L1's tube needs ~45 cm to reach the bucket (the list says 20–30 cm).</li>
   </ul>
  </div>
 </div>
</div>
"""

CSS = r"""
.tabs{display:flex;gap:8px;padding:0 28px}.tab{border:1px solid var(--grid);background:#fff;border-radius:999px;padding:6px 14px;cursor:pointer;font:inherit;color:var(--ink2)}
.tab.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.ctl{display:grid;grid-template-columns:1fr 1fr;gap:10px 22px;margin-top:10px}.ctl label{display:flex;flex-direction:column;gap:4px;color:var(--ink2);font-size:12.5px}
.ctl b{color:var(--ink);font-weight:650}.ctl select{font:inherit;padding:4px 6px;border:1px solid var(--grid);border-radius:8px;background:#fff}
.hint{margin:8px 0 0;color:var(--ink2);font-size:12.5px}.b-good{background:#e3f5e3;color:#0a5c0a}
.lab3d-layer{position:absolute;inset:0;pointer-events:none;overflow:hidden}
.lab3d{position:absolute;left:0;top:0;white-space:nowrap;font-size:11.5px;padding:2px 7px;border-radius:6px;background:rgba(255,255,255,.88);color:var(--ink2);border:1px solid var(--grid)}
.lab3d.strong{color:var(--ink);font-weight:650}.lab3d.alert{background:#fbe1e1;color:#8f1d1d;border-color:#f0b9b9;font-weight:600}
.chk{display:flex;align-items:center;gap:6px;color:var(--ink2);font-size:12.5px}.plain{margin:6px 0 0;padding-left:18px;color:var(--ink2);font-size:12.5px}.plain li{margin:3px 0}
"""

JS = r"""
(function(){
const BD=__BOARD__;window.BD=BD;window.WAVES=__WAVES__;
const sv=document.getElementById('board');
const pcol=p=>{const c=BD.cmap,u=Math.max(0,Math.min(1,p/1.2))*(c.length-1),i=Math.min(c.length-2,Math.floor(u));return mix(c[i],c[i+1],u-i)};
function mix(a,b,t){const h=x=>[1,3,5].map(k=>parseInt(x.substr(k,2),16));const A=h(a),B=h(b);return 'rgb('+A.map((v,k)=>Math.round(v+(B[k]-v)*t)).join(',')+')'}
const Y=y=>-y;
el('rect',{x:0,y:-40,width:60,height:40,rx:1.2,fill:'#f3ece0',stroke:'#e2d6c1','stroke-width':.25},sv);
// pump + hose (schematic, off board)
const IN=BD.xy.IN;
el('line',{x1:-14,y1:Y(IN[1]),x2:IN[0],y2:Y(IN[1]),stroke:css('--ink2'),'stroke-width':.6,'stroke-dasharray':'1 .8'},sv);
el('rect',{x:-27.5,y:Y(IN[1])-3,width:13.5,height:6,rx:1,fill:'#fff',stroke:css('--ink2'),'stroke-width':.3},sv);
const pt=el('text',{x:-20.5,y:Y(IN[1])+.9,'font-size':2.1,'text-anchor':'middle',fill:css('--ink')},sv);pt.textContent='R365 12 V';
const bk=el('text',{x:-20.5,y:Y(IN[1])+6.5,'font-size':2,'text-anchor':'middle',fill:css('--ink2')},sv);bk.textContent='bucket 20 L';
const pipes=BD.links.map(([a,b])=>el('line',{x1:BD.pos[a][0],y1:Y(BD.pos[a][1]),x2:BD.pos[b][0],y2:Y(BD.pos[b][1]),'stroke-width':2.4,'stroke-linecap':'round'},sv));
// flow sensor body
const fm=el('rect',{x:IN[0]+2.5,y:Y(IN[1])-1.8,width:6,height:3.6,rx:.8,fill:'#c99a2e'},sv);
const fl=el('text',{x:IN[0]+5.5,y:Y(IN[1])-3,'font-size':2.2,'text-anchor':'middle',fill:css('--ink'),'font-weight':650},sv);
// return stub
const T1=BD.xy.T1;el('line',{x1:T1[0],y1:Y(T1[1]),x2:T1[0],y2:Y(1.5),stroke:css('--ink2'),'stroke-width':1.2,'stroke-dasharray':'1 .6'},sv);
const rl=el('text',{x:T1[0]+1.6,y:Y(2.5),'font-size':2,fill:css('--ink2')},sv);
// taps
const taps={};['L1','L2','L3'].forEach(t=>{const p=BD.xy['T'+t];
 const ln=el('line',{x1:p[0],y1:Y(p[1]),x2:p[0],y2:Y(p[1]-5.5),stroke:css('--muted'),'stroke-width':1.1},sv);
 const c=el('circle',{cx:p[0],cy:Y(p[1]-5.5),r:1.1,fill:css('--muted')},sv);
 const tx=el('text',{x:p[0],y:Y(p[1]-9.2),'font-size':2.1,'text-anchor':'middle',fill:css('--muted')},sv);taps[t]=[ln,c,tx]});
// valves
const vl={};['R1','R2','V1','V2'].forEach(v=>{const p=BD.xy[v];el('rect',{x:p[0]-1.1,y:Y(p[1])-1.1,width:2.2,height:2.2,transform:'rotate(45 '+p[0]+' '+Y(p[1])+')',fill:css('--ink2'),stroke:'#fff','stroke-width':.35},sv);
 vl[v]=el('text',{x:p[0],y:Y(p[1])-2.6,'font-size':2.1,'text-anchor':'middle',fill:css('--ink2')},sv)});
// sensors
const sl={};['P1','P2'].forEach(s=>{const p=BD.xy[s];el('line',{x1:p[0],y1:Y(p[1]),x2:p[0],y2:Y(p[1]+6),stroke:'#b9c3cc','stroke-width':1.2},sv);
 el('rect',{x:p[0]-1.4,y:Y(p[1]+6)-1.4,width:2.8,height:2.8,rx:.4,fill:css('--ink')},sv);
 sl[s]=el('text',{x:p[0]+2.2,y:Y(p[1]+6)+.8,'font-size':2.4,fill:css('--ink'),'font-weight':650},sv)});
// colour legend
const lg=el('g',{},sv);for(let i=0;i<24;i++){el('rect',{x:-26+i*.9,y:-47,width:.95,height:1.6,fill:pcol(i/23*1.2)},lg)}
el('text',{x:-26,y:-43.2,'font-size':1.9,fill:css('--ink2')},lg).textContent='0';el('text',{x:-5.3,y:-43.2,'font-size':1.9,fill:css('--ink2'),'text-anchor':'end'},lg).textContent='1.2 bar';
el('text',{x:-26,y:-48.2,'font-size':1.9,fill:css('--ink2')},lg).textContent='pipe pressure';
// signature chart
const sg=document.getElementById('sig');
// controls
const rs=document.getElementById('rs'),vs=document.getElementById('vs'),ls=document.getElementById('ls'),ds=document.getElementById('ds');
const S=(r,v,l,d)=>BD.states[r+'|'+(Number.isInteger(v)?v.toFixed(1):v)+'|'+l+'|'+d];
const f=(x,n)=>x.toFixed(n);
function bupd(){const r=BD.R[+rs.value],v=BD.V[+vs.value],l=ls.value,d=BD.D[+ds.value];
 document.getElementById('rv').textContent=r+'°';document.getElementById('vv').textContent=v.toFixed(1)+'°';document.getElementById('dv').textContent=d+' mm';
 ds.disabled=(l==='none');
 const s=S(r,v,l,l==='none'?0:d),h=S(r,v,'none',0);
pipes.forEach((ln,k)=>{const [a,b]=BD.links[k];const ia=BD.nodes.indexOf(a),ib=BD.nodes.indexOf(b);ln.setAttribute('stroke',pcol((s[6+ia]+s[6+ib])/2))});
 fl.textContent='F0 '+f(s[2],2)+' L/min';rl.textContent='return '+f(s[4],2)+' L/min';
 vl.R1.textContent='R1 '+r+'°';vl.R2.textContent='R2 '+r+'°';vl.V1.textContent='V1 '+v.toFixed(1)+'°';vl.V2.textContent='V2 '+v.toFixed(1)+'°';
 sl.P1.textContent='P1 '+f(s[0],3)+' bar';sl.P2.textContent='P2 '+f(s[1],3)+' bar';
 ['L1','L2','L3'].forEach(t=>{const on=(t===l),[ln,c,tx]=taps[t];const col=on?css('--crit'):css('--muted');ln.setAttribute('stroke',col);c.setAttribute('fill',col);c.setAttribute('r',on?1.6:1.1);tx.setAttribute('fill',col);tx.textContent=on?t+': '+f(s[3],3)+' L/min':t});
 document.getElementById('bp1').textContent=f(s[0],3);document.getElementById('bp2').textContent=f(s[1],3);document.getElementById('bf0').textContent=f(s[2],2);
 document.getElementById('bql').textContent=f(s[3],3);document.getElementById('bqp').textContent=f(100*s[3]/h[2],1)+' %';document.getElementById('bpm').textContent=f(s[5],2);
 const sb=document.getElementById('bsafe');if(s[5]>BD.safe){sb.className='badge b-alert';sb.textContent='■ above '+BD.safe+' bar – risk for the 1.6 bar sensors'}else{sb.className='badge b-good';sb.textContent='● safe for the sensors (≤ '+BD.safe+' bar)'}
 // deltas, noise from the bench twin (1-s published values, 30-s windows)
 const d1=(s[0]-h[0])*1000,d2=(s[1]-h[1])*1000,dd=d1-d2,df=s[2]-h[2];
 const ul=document.getElementById('bdelta');ul.innerHTML='';
 [['ΔP1',f(d1,1)+' mbar'],['ΔP2',f(d2,1)+' mbar'],['Δ(P1 − P2)',f(dd,1)+' mbar'],['ΔF0 (true)',f(df,3)+' L/min'],['ΔF0 / leak flow',l==='none'?'–':f(100*df/Math.max(s[3],1e-9),0)+' %']].forEach(([k,v])=>{const li=document.createElement('li');li.innerHTML='<span>'+k+'</span><span>'+v+'</span>';ul.appendChild(li)});
 const dg=document.getElementById('bdiag'),nt=document.getElementById('bnote');
 if(l==='none'){dg.className='badge b-log';dg.textContent='● no leak';nt.textContent='Open a tap to see its signature.'}
 else{const a=S(r,v,'L1',0.5),bb=S(r,v,'L2',0.5);const u=[d1,d2],ua=[(a[0]-h[0])*1000,(a[1]-h[1])*1000],ub=[(bb[0]-h[0])*1000,(bb[1]-h[1])*1000];
  const cos=(p,q)=>(p[0]*q[0]+p[1]*q[1])/Math.hypot(...p)/Math.hypot(...q);const ca=cos(u,ua),cb=cos(u,ub);
  const det=Math.abs(d1)>BD.thr.p1||Math.abs(dd)>BD.thr.diff;const detF=Math.abs(df)>BD.thr.f0;
  if(!det){dg.className='badge b-watch';dg.textContent='▲ below the noise – not detected'}
  else{dg.className='badge b-alert';dg.textContent='■ leak detected – '+(ca>cb?'branch A (L1)':'branch B (L2 or L3)')}
  nt.textContent='Branch from the direction of (ΔP1, ΔP2): match with L1 '+f(ca,4)+', with L2/L3 '+f(cb,4)+'. Detected if |ΔP1| > '+f(BD.thr.p1,2)+' mbar or |Δ(P1 − P2)| > '+f(BD.thr.diff,2)+' mbar (3σ, 30-s windows, bench noise model). F0 alone: '+(detF?'also sees it':'does not see it')+' (needs |ΔF0| > '+f(BD.thr.f0,3)+' L/min).'}
 // signature plot
 sg.innerHTML='';const W=320,H=240,cx=W/2,cy=H/2;const sigs={L1:S(r,v,'L1',0.5),L2:S(r,v,'L2',0.5),L3:S(r,v,'L3',0.5)};
 let m=1;Object.values(sigs).forEach(q=>{m=Math.max(m,Math.abs(q[0]-h[0])*1000,Math.abs(q[1]-h[1])*1000)});if(l!=='none')m=Math.max(m,Math.abs(d1),Math.abs(d2));const k=(Math.min(W,H)/2-26)/m;
 el('line',{x1:20,x2:W-20,y1:cy,y2:cy,stroke:css('--grid')},sg);el('line',{x1:cx,x2:cx,y1:14,y2:H-14,stroke:css('--grid')},sg);
 el('text',{x:W-20,y:cy-5,'font-size':10.5,'text-anchor':'end',fill:css('--ink2')},sg).textContent='ΔP1 +';el('text',{x:cx+5,y:22,'font-size':10.5,fill:css('--ink2')},sg).textContent='ΔP2 +';
 const pc={L1:css('--s1'),L2:css('--s2'),L3:css('--s3')};
 Object.entries(sigs).forEach(([t,q])=>{const x=cx+(q[0]-h[0])*1000*k,y=cy-(q[1]-h[1])*1000*k;el('line',{x1:cx,y1:cy,x2:x,y2:y,stroke:pc[t],'stroke-width':t==='L3'?2:2.6,'stroke-dasharray':t==='L3'?'5 4':''},sg);
  el('text',{x:x+(t==='L3'?-30:6),y:y+(t==='L1'?4:t==='L2'?-6:14),'font-size':11,fill:pc[t],'font-weight':650},sg).textContent=t+' (0.5 mm)'});
 if(l!=='none'){el('circle',{cx:cx+d1*k,cy:cy-d2*k,r:5,fill:css('--crit'),stroke:'#fff','stroke-width':2},sg);el('circle',{cx:26,cy:24,r:5,fill:css('--crit')},sg);el('text',{x:36,y:28,'font-size':10.5,fill:css('--crit')},sg).textContent='now: '+l+', '+d+' mm'}
}
[rs,vs,ls,ds].forEach(c=>c.addEventListener('input',bupd));bupd();
// recording chart
const R2=BD.rec,rc=document.getElementById('rchart'),W=640;const L=48,RR=60;
const tx=t=>L+t/300*(W-L-RR);
function box(y0,y1,lo,hi,ticks,fmt,lab){const y=v=>y0+(1-(v-lo)/(hi-lo))*(y1-y0);ticks.forEach(v=>{el('line',{x1:L,x2:W-RR,y1:y(v),y2:y(v),stroke:css('--grid')},rc);el('text',{x:L-6,y:y(v)+4,'font-size':10.5,'text-anchor':'end',fill:css('--ink2')},rc).textContent=fmt(v)});
 el('text',{x:L,y:y0-6,'font-size':11,fill:css('--ink2')},rc).textContent=lab;return y}
const allp=R2.p1.concat(R2.p2,R2.p1t,R2.p2t),plo=Math.min(...allp)-0.003,phi=Math.max(...allp)+0.003;
const yp=box(18,150,plo,phi,[0.72,0.74,0.76,0.78,0.80,0.82].filter(v=>v>plo&&v<phi),v=>v.toFixed(2),'pressure (bar): published 1-s means, dashed = true');
const allf=R2.fcal.concat(R2.ffw,R2.ftrue),flo=Math.min(...allf)-0.05,fhi=Math.max(...allf)+0.05;
const yf=box(182,280,flo,fhi,[0.6,0.8,1.0,1.2,1.4].filter(v=>v>flo&&v<fhi),v=>v.toFixed(1),'F0 (L/min): calibrated (green), firmware K = 7.5 (yellow), true (dashed)');
el('line',{x1:tx(150),x2:tx(150),y1:12,y2:282,stroke:css('--crit'),'stroke-width':1},rc);
[0,60,120,180,240,300].forEach(t=>{el('text',{x:tx(t),y:296,'font-size':10.5,'text-anchor':'middle',fill:css('--ink2')},rc).textContent=t+' s'});
const lines=[['p1',yp,css('--s1'),''],['p2',yp,css('--s2'),''],['p1t',yp,css('--ink'),'3 3'],['p2t',yp,css('--ink'),'3 3'],['fcal',yf,css('--s3'),''],['ffw',yf,'#eda100',''],['ftrue',yf,css('--ink'),'3 3']].map(([k,y,c,da])=>[k,y,el('path',{fill:'none',stroke:c,'stroke-width':k.endsWith('t')||k==='ftrue'?1:1.4,'stroke-dasharray':da},rc)]);
const lp1=el('text',{'font-size':10.5,fill:css('--s1'),'font-weight':650},rc),lp2=el('text',{'font-size':10.5,fill:css('--s2'),'font-weight':650},rc);lp1.textContent='P1';lp2.textContent='P2';
const rcur=el('line',{y1:12,y2:282,stroke:css('--ink'),'stroke-width':1},rc);
const rt=document.getElementById('rt'),rclk=document.getElementById('rclock');
function rupd(i){i=+i;lines.forEach(([k,y,p])=>{let d='';R2[k].slice(0,i+1).forEach((v,j)=>d+=(j?'L':'M')+tx(R2.t[j])+','+y(v));p.setAttribute('d',d)});
 rcur.setAttribute('x1',tx(R2.t[i]));rcur.setAttribute('x2',tx(R2.t[i]));rclk.textContent=Math.round(R2.t[i])+' s';
 const a=yp(R2.p1[i]),b=yp(R2.p2[i]);lp1.setAttribute('x',tx(R2.t[i])+5);lp2.setAttribute('x',tx(R2.t[i])+5);lp1.setAttribute('y',a<b?a-2:a+10);lp2.setAttribute('y',a<b?b+10:b-2)}
rt.max=R2.t.length-1;rt.value=R2.t.length-1;rt.addEventListener('input',e=>rupd(e.target.value));rupd(rt.value);let rtm=null;
document.getElementById('rplay').onclick=function(){if(rtm){clearInterval(rtm);rtm=null;this.textContent='▶ Play';return}
 if(+rt.value>=+rt.max)rt.value=0;this.textContent='❚❚ Pause';rtm=setInterval(()=>{rt.value=+rt.value+1;rupd(rt.value);if(+rt.value>=+rt.max){clearInterval(rtm);rtm=null;document.getElementById('rplay').textContent='▶ Play'}},40)};
})();
// tabs
const VIEWS={farm:['farmview','farmintro'],board:['boardview','boardintro'],'3d':['view3d','intro3d']};let H3=null;
document.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===b));
 for(const [k,[v,i]] of Object.entries(VIEWS)){document.getElementById(v).style.display=b.dataset.v===k?'grid':'none';document.getElementById(i).style.display=b.dataset.v===k?'block':'none'}
 if(b.dataset.v==='3d'){if(!H3)H3=start3d();else H3.pause(false)}else if(H3)H3.pause(true)}));
function start3d(){const BD=window.BD,q=id=>document.getElementById(id);
 const ui={colours:()=>q('c3col').checked,labels:()=>q('c3lab').checked,rotate:()=>q('c3rot').checked};
 const h=HP3D.init(BD,q('host3d'),ui);
 const S=(r,v,l,d)=>BD.states[r+'|'+(Number.isInteger(v)?v.toFixed(1):v)+'|'+l+'|'+d];
 function u(){const r=BD.R[+q('rs3').value],v=BD.V[+q('vs3').value],l=q('ls3').value,d=BD.D[+q('ds3').value];
  q('rv3').textContent=r+'°';q('vv3').textContent=v.toFixed(1)+'°';q('dv3').textContent=d+' mm';q('ds3').disabled=(l==='none');
  const s=S(r,v,l,l==='none'?0:d),hh=S(r,v,'none',0);h.setState(s,hh,{r,v,leak:l,d});
  const ul=q('r3');ul.innerHTML='';[['P1',s[0].toFixed(3)+' bar'],['P2',s[1].toFixed(3)+' bar'],['F0 (pump flow)',s[2].toFixed(2)+' L/min'],['Return to the bucket',s[4].toFixed(2)+' L/min'],['Leak',l==='none'?'none':s[3].toFixed(3)+' L/min ('+(100*s[3]/hh[2]).toFixed(1)+' %)'],['Highest pressure',s[5].toFixed(2)+' bar'+(s[5]>BD.safe?' ⚠':'')]]
   .forEach(([k,x])=>{const li=document.createElement('li');li.innerHTML='<span>'+k+'</span><span>'+x+'</span>';ul.appendChild(li)})}
 ['rs3','vs3','ls3','ds3','c3col'].forEach(id=>q(id).addEventListener('input',u));
 // ── pressure waves ──
 const WD=window.WAVES;h.initWaves(WD);const wev=q('wev'),wt=q('wt'),wc=q('wchart');
 Object.entries(WD.events).forEach(([k,e])=>{const o=document.createElement('option');o.value=k;o.textContent=e.label;wev.appendChild(o)});
 let EV=null,tw=0,wplay=false,wlast=0;
 function wdraw(){wc.innerHTML='';if(!EV)return;const W=640,H=230,L=52,R=14,T=14,Bm=30;const t=EV.t_ms,n=t.length;
  const i1=WD.nodes.indexOf('P1'),i2=WD.nodes.indexOf('P2');const s1=EV.dh[i1].map(v=>v/10.197),s2=EV.dh[i2].map(v=>v/10.197);
  const all=s1.concat(s2);let lo=Math.min(0,...all),hi=Math.max(0,...all);const pad=(hi-lo)*0.08||1;lo-=pad;hi+=pad;
  const x=v=>L+(v-t[0])/(t[n-1]-t[0])*(W-L-R),y=v=>T+(1-(v-lo)/(hi-lo))*(H-T-Bm);
  const step=Math.pow(10,Math.floor(Math.log10((hi-lo)/4)));const ticks=[];for(let v=Math.ceil(lo/step)*step;v<=hi;v+=step)ticks.push(v);
  (ticks.length>7?ticks.filter((_,k)=>k%2===0):ticks).forEach(v=>{el('line',{x1:L,x2:W-R,y1:y(v),y2:y(v),stroke:css('--grid')},wc);el('text',{x:L-6,y:y(v)+4,'font-size':10.5,'text-anchor':'end',fill:css('--ink2')},wc).textContent=(+v.toFixed(3))+''});
  el('text',{x:L,y:10,'font-size':10.5,fill:css('--ink2')},wc).textContent='pressure change (mbar)';
  const tstep=t[n-1]>200?50:t[n-1]>80?20:10;for(let v=0;v<=t[n-1];v+=tstep)el('text',{x:x(v),y:H-10,'font-size':10.5,'text-anchor':'middle',fill:css('--ink2')},wc).textContent=v+' ms';
  el('line',{x1:x(EV.t_event),x2:x(EV.t_event),y1:T,y2:H-Bm,stroke:css('--crit'),'stroke-dasharray':'3 3'},wc);
  [[s1,css('--s1'),'P1'],[s2,css('--s2'),'P2']].forEach(([s,c,lab])=>{let d='';s.forEach((v,k)=>d+=(k?'L':'M')+x(t[k])+','+y(v));el('path',{d,fill:'none',stroke:c,'stroke-width':1.6},wc);
   el('text',{x:W-R-2,y:y(s[n-1])+(lab==='P1'?-5:12),'font-size':10.5,'text-anchor':'end',fill:c,'font-weight':650},wc).textContent=lab});
  if(q('wads').checked){[['860_0',css('--s1')],['860_1',css('--s2')]].forEach(([k,c])=>{const [te,va]=EV.ads[k];te.forEach((tt,j)=>{if(tt<=t[n-1])el('circle',{cx:x(tt),cy:y(va[j]),r:te.length>120?1.6:2.6,fill:'#fff',stroke:c,'stroke-width':1.3},wc)})})}
  wc._cur=el('line',{y1:T,y2:H-Bm,stroke:css('--ink'),'stroke-width':1},wc);wc._x=x}
 function wset(fi){if(!EV)return;fi=Math.max(0,Math.min(EV.t_ms.length-1,fi));wt.value=fi;const sc=Math.max(EV._cm[fi],5);h.setWave(EV,fi,sc);const tm=EV.t_ms[fi];
  q('wclock').textContent=(tm-EV.t_event).toFixed(2)+' ms after';q('wscale').textContent='Colours: blue = pressure falls, red = rises, grey = unchanged; full colour = ±'+(sc/10.197).toFixed(1)+' mbar (largest change so far).';if(wc._cur){wc._cur.setAttribute('x1',wc._x(tm));wc._cur.setAttribute('x2',wc._x(tm))}}
 Object.values(WD.events).forEach(e=>{const n=e.t_ms.length;e._cm=new Float32Array(n);let m=0;for(let f=0;f<n;f++){for(const s of e.dh){const a=Math.abs(s[f]);if(a>m)m=a}e._cm[f]=m}});
 wev.addEventListener('input',()=>{EV=wev.value?WD.events[wev.value]:null;wplay=false;q('wplay').textContent='▶ Play';
  if(!EV){h.setWave(null);wdraw();q('wclock').textContent='';q('wscale').textContent='';return}wt.max=EV.t_ms.length-1;tw=0;wdraw();wset(0)});
 wt.addEventListener('input',()=>{wplay=false;q('wplay').textContent='▶ Play';wset(+wt.value);tw=EV?EV.t_ms[+wt.value]-EV.t_ms[0]:0});
 q('wads').addEventListener('input',()=>{wdraw();wset(+wt.value)});
 q('wplay').onclick=function(){if(!EV){wev.value=Object.keys(WD.events)[0];wev.dispatchEvent(new Event('input'))}
  wplay=!wplay;this.textContent=wplay?'❚❚ Pause':'▶ Play';if(wplay&&+wt.value>=EV.t_ms.length-1){tw=0}wlast=performance.now();requestAnimationFrame(wloop)};
 function wloop(now){if(!wplay||!EV)return;const spd=+q('wspd').value;tw+=(now-wlast)/spd;wlast=now;const ft=EV.t_ms[1]-EV.t_ms[0];
  const fi=Math.round(tw/ft);wset(fi);if(fi>=EV.t_ms.length-1){wplay=false;q('wplay').textContent='▶ Play';return}requestAnimationFrame(wloop)}
 document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>b.dataset.view==='home'?h.home():h.view(b.dataset.view)));
 u();return h}
"""
