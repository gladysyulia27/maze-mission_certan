#!/usr/bin/env python3
"""
MAZE MISSION: DEEP LOGIC  (UI web lokal, tanpa library tambahan)

Cara menjalankan :  python maze_mission_deep_logic.py
Browser terbuka otomatis. Tekan Ctrl+C di terminal untuk berhenti.

Semua aturan & kondisi tersembunyi (posisi Trap) dipegang Python; browser hanya menampilkan.

ATURAN
  * Ambil semua kristal, lalu masuk ke gerbang. Gerbang terkunci sampai kristal habis.
  * Angka pada sel = jumlah Trap tersembunyi di 8 sel sekitarnya (termasuk diagonal).
    Angka 0 => 8 sel sekitarnya pasti aman.
  * 3 nyawa: menginjak Trap -1 (Trap hancur). Disarm sel yang aman juga -1.
  * Energi terbatas: langkah/Disarm -1, tiap kristal +3.
  * Disarm (sel bersebelahan), Sonar (jarak <= 2, 2x per level), Bendera (catatan di browser).
  * Skor: kristal +100 | Disarm benar +75 | Trap -50 | Disarm salah -25
          gerbang +500 | sisa nyawa x100 | sisa energi x5
"""
import json, random, threading, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# =====================================================================
# 1. LEVEL & GAME ENGINE  (ukuran, kepadatan Trap, jumlah kristal, faktor energi)
# =====================================================================
LEVELS = [(7, .15, 2, 1.0), (8, .18, 3, .95), (9, .20, 3, .90),
          (10, .22, 4, .90), (11, .24, 4, .85), (12, .26, 5, .85)]
S_CRYSTAL, S_GOAL, S_DISARM, S_TRAP, S_BAD_DISARM = 100, 500, 75, -50, -25


def E(t, r, c, m="", col="", **kw):
    """Event kecil untuk efek/log di browser."""
    return dict(t=t, r=r, c=c, m=m, col=col, **kw)


class Game:
    def __init__(self, level):
        n, tp0, nc, ef = LEVELS[level]
        self.n, self.goal = n, n * n - 1
        for tr in range(3000):                       # buat level yang punya jalur aman
            tp = tp0 * (1 - min(.4, tr / 2500))
            wall, trap = set(), set()
            for r in range(n):
                for c in range(n):
                    if (r < 2 and c < 2) or (r == n - 1 and c == n - 1):
                        continue                     # area start & goal bersih
                    x = random.random()
                    if x < tp: trap.add(r * n + c)
                    elif x < tp + .09: wall.add(r * n + c)
            free = [k for k in range(1, n * n - 1)
                    if k not in wall and k not in trap and k // n + k % n >= 3]
            if len(free) < nc: continue
            random.shuffle(free)
            cry = set(free[:nc])
            seen, st = {0}, [0]                      # DFS: semua kristal & goal harus terjangkau
            while st:
                r, c = divmod(st.pop(), n)
                for a, b in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                    if 0 <= a < n and 0 <= b < n:
                        j = a * n + b
                        if j not in seen and j not in wall and j not in trap:
                            seen.add(j); st.append(j)
            if self.goal not in seen or any(k not in seen for k in cry): continue
            break
        else:
            raise RuntimeError("Gagal membuat level.")
        self.wall, self.trap, self.cry, self.ncry = wall, trap, cry, nc
        self.hp, self.got, self.sonar, self.score = 3, 0, 2, 0
        self.en = self.max = int(n * n * ef + .5)
        self.pos = (0, 0)
        self.vis, self.safe, self.clr, self.son = {0}, set(), set(), {}
        self.status, self.why = "run", ""
        self.refresh()

    # ---- pengetahuan agen/pemain
    def nb8(self, r, c):
        return [(r + a, c + b) for a in (-1, 0, 1) for b in (-1, 0, 1)
                if (a or b) and 0 <= r + a < self.n and 0 <= c + b < self.n]

    def clue(self, r, c):
        n = self.n
        return sum(1 for a, b in self.nb8(r, c) if a * n + b in self.trap and a * n + b not in self.clr)

    def refresh(self):                               # angka 0 => 8 tetangga pasti aman
        n = self.n
        for k in list(self.vis):
            r, c = divmod(k, n)
            if self.clue(r, c) == 0:
                for a, b in self.nb8(r, c):
                    if a * n + b not in self.wall: self.safe.add(a * n + b)

    # ---- aksi
    def _need_run(self):
        if self.status != "run": raise ValueError("Permainan sudah berakhir.")

    def _end(self, win, why):
        self.status, self.why = ("win" if win else "lose"), why
        if win: self.score += S_GOAL + self.hp * 100 + self.en * 5

    def _after(self, ev):
        self.refresh()
        r, c = self.pos
        if self.hp <= 0:
            self._end(False, "Nyawamu habis.")
        elif r * self.n + c == self.goal and self.got == self.ncry:
            self._end(True, "")
        else:
            if r * self.n + c == self.goal:
                ev.append(E("info", r, c, "🔒 Gerbang terkunci — ambil semua 💎 dulu.", "var(--warn)"))
            if self.en <= 0: self._end(False, "Energi habis sebelum sampai gerbang.")
        return ev

    def move(self, r, c):
        self._need_run()
        pr, pc = self.pos
        if not (0 <= r < self.n and 0 <= c < self.n) or abs(pr - r) + abs(pc - c) != 1:
            raise ValueError("Hanya boleh melangkah ke sel bersebelahan.")
        k = r * self.n + c
        if k in self.wall: raise ValueError("Itu dinding.")
        ev = []
        self.en -= 1; self.pos = (r, c); self.vis.add(k)
        if k in self.trap and k not in self.clr:
            self.clr.add(k); self.hp -= 1; self.score += S_TRAP
            ev.append(E("boom", r, c, "💥 Menginjak Trap! −1 nyawa, Trap hancur.", "var(--bad)"))
        else:
            ev.append(E("step", r, c))
        if k in self.cry:
            self.cry.discard(k); self.got += 1; self.en += 3; self.score += S_CRYSTAL
            ev.append(E("gem", r, c, f"💎 Kristal {self.got}/{self.ncry}! Energi +3", "var(--acc2)"))
        return self._after(ev)

    def disarm(self, r, c):
        self._need_run()
        pr, pc = self.pos
        if not (0 <= r < self.n and 0 <= c < self.n) or abs(pr - r) + abs(pc - c) != 1:
            raise ValueError("Disarm hanya untuk sel bersebelahan.")
        k = r * self.n + c
        if k in self.wall: raise ValueError("Itu dinding.")
        if k in self.vis or k in self.clr: raise ValueError("Sel itu sudah beres.")
        self.en -= 1
        if k in self.trap:
            self.clr.add(k); self.score += S_DISARM
            ev = [E("disarm", r, c, "🔧 Disarm berhasil! Trap dijinakkan.", "var(--ok)")]
        else:
            self.hp -= 1; self.score += S_BAD_DISARM
            ev = [E("alarm", r, c, "🚨 Salah! Sel itu aman — alarm berbunyi.", "var(--bad)")]
        return self._after(ev)

    def sonar_scan(self, r, c):
        self._need_run()
        pr, pc = self.pos
        if not (0 <= r < self.n and 0 <= c < self.n) or max(abs(pr - r), abs(pc - c)) > 2:
            raise ValueError("Jangkauan Sonar maksimal 2 sel.")
        if self.sonar <= 0: raise ValueError("Sonar habis.")
        k = r * self.n + c
        if k in self.wall: raise ValueError("Itu dinding.")
        if k in self.vis or k in self.clr or k in self.safe or k in self.son:
            raise ValueError("Sel itu sudah diketahui.")
        self.sonar -= 1
        t = k in self.trap
        self.son[k] = "T" if t else "S"
        self.refresh()
        return [E("sonar", r, c, f"📡 Sonar: ({r},{c}) adalah TRAP ☠" if t else f"📡 Sonar: ({r},{c}) AMAN ✓",
                  "var(--bad)" if t else "var(--ok)", trap=t)]

    def state(self):
        """Hanya info yang boleh diketahui pemain. Posisi Trap baru dibuka saat kalah."""
        n = self.n
        return dict(n=n, wall=sorted(self.wall), cry=sorted(self.cry), ncry=self.ncry, hp=self.hp,
                    en=self.en, max=self.max, got=self.got, sonar=self.sonar, pos=list(self.pos),
                    vis=sorted(self.vis), safe=sorted(self.safe), clr=sorted(self.clr),
                    son={str(k): v for k, v in self.son.items()}, score=self.score,
                    status=self.status, why=self.why,
                    clues={str(k): self.clue(k // n, k % n) for k in self.vis},
                    trap=sorted(self.trap) if self.status == "lose" else [])


# =====================================================================
# 2. TAMPILAN (HTML/CSS/JS) — dilayani server lokal ke browser
# =====================================================================
HTML = r"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Maze Mission: Deep Logic</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Baloo+2:wght@500;600;700;800&display=swap">
<style>
:root{color-scheme:light dark;box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px);
--font:"Baloo 2","Trebuchet MS","Segoe UI",system-ui,sans-serif;
--scene:radial-gradient(circle at 86% 12%,#fff6a8 0 34px,#ffe066 35px 52px,transparent 53px),radial-gradient(120% 38% at 15% 104%,#58c878 0 60%,transparent 61%),radial-gradient(100% 34% at 95% 104%,#3aa862 0 60%,transparent 61%),linear-gradient(#9fe0ff,#e6f8da 62%,#c8f0b0);
--card:#fffdf4;--ink:#23304d;--txt:#23304d;--mut:#5f6f8f;--line:rgba(35,48,77,.14);
--leaf:#5fd37c;--leaf2:#2e9f57;--sand:#fff1c9;--sand2:#e4c987;--mint:#c9f6dd;--mint2:#7bd9a3;--rock:#bcc3d2;--rock2:#7d869b;--coal:#6a5668;--pit1:#2aa59a;--pit2:#1b7c8c;
--coral:#ff5a5f;--coral2:#c92f45;--sun:#ffc83d;--sun2:#d99a0b;--brass:#ffb400;--rust:#e8384f;--moss:#2e9e5b;--blue:#1596c8;--ok:#2e9e5b;--bad:#e8384f;--warn:#e07a10;--acc2:#1596c8;
--n1:#1d6ff2;--n2:#1fa24a;--n3:#e8384f;--n4:#7a3fd1;--n5:#e07a10}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){--scene:radial-gradient(circle at 86% 12%,#fffbe0 0 34px,#e8ecff 35px 52px,transparent 53px),radial-gradient(120% 38% at 15% 104%,#1f6b4a 0 60%,transparent 61%),radial-gradient(100% 34% at 95% 104%,#134b38 0 60%,transparent 61%),linear-gradient(#0e1838,#1d3560 65%,#245a63);--card:#1d2a47;--ink:#0a1226;--txt:#eaf2ff;--mut:#9fb3d6;--line:rgba(234,242,255,.16);--leaf:#34a862;--leaf2:#1c6b3c;--sand:#7a6d52;--sand2:#4d4331;--mint:#2f7a55;--mint2:#1d4f36;--rock:#6b7490;--rock2:#3e455e;--coal:#3a2d3f;--pit1:#12455a;--pit2:#0a2a3d;--n1:#7db4ff;--n2:#6fe08a;--n3:#ff8a95;--n4:#c9a2ff;--n5:#ffb266}}
:root[data-theme="dark"]{--scene:radial-gradient(circle at 86% 12%,#fffbe0 0 34px,#e8ecff 35px 52px,transparent 53px),radial-gradient(120% 38% at 15% 104%,#1f6b4a 0 60%,transparent 61%),radial-gradient(100% 34% at 95% 104%,#134b38 0 60%,transparent 61%),linear-gradient(#0e1838,#1d3560 65%,#245a63);--card:#1d2a47;--ink:#0a1226;--txt:#eaf2ff;--mut:#9fb3d6;--line:rgba(234,242,255,.16);--leaf:#34a862;--leaf2:#1c6b3c;--sand:#7a6d52;--sand2:#4d4331;--mint:#2f7a55;--mint2:#1d4f36;--rock:#6b7490;--rock2:#3e455e;--coal:#3a2d3f;--pit1:#12455a;--pit2:#0a2a3d;--n1:#7db4ff;--n2:#6fe08a;--n3:#ff8a95;--n4:#c9a2ff;--n5:#ffb266}
*{box-sizing:border-box}
html{height:100%}
body{margin:0;min-height:100%;background:var(--scene) fixed;color:var(--txt);font:500 16px/1.4 var(--font)}
header{max-width:1100px;margin:0 auto;padding:18px 22px 8px;display:flex;flex-wrap:wrap;align-items:center;gap:12px}
.logo{width:58px;height:58px;border-radius:18px;background:var(--sun);border:3px solid var(--ink);box-shadow:0 5px 0 var(--ink);display:grid;place-items:center;transform:rotate(-6deg)}
h1{margin:0;font:800 40px/1 var(--font);color:#ffd23f;-webkit-text-stroke:7px var(--ink);paint-order:stroke fill;text-shadow:0 5px 0 var(--ink);letter-spacing:.5px}
.tag{display:inline-block;margin-top:8px;background:var(--coral);color:#fff;font-weight:800;font-size:13px;letter-spacing:2px;text-transform:uppercase;padding:1px 12px;border:2.5px solid var(--ink);border-radius:999px;transform:rotate(-2deg);box-shadow:0 3px 0 var(--ink)}
.sp{flex:1}
.chip{display:inline-flex;align-items:center;gap:6px;background:var(--card);border:2.5px solid var(--ink);border-radius:999px;padding:1px 13px;font-weight:700;font-size:14px;box-shadow:0 3px 0 var(--ink)}
.ic{flex:none;display:block}
main{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:22px;max-width:1100px;margin:0 auto;padding:10px 22px 40px}
@media(max-width:860px){main{grid-template-columns:minmax(0,1fr);padding:8px 12px 30px}header{padding:12px}h1{font-size:30px;-webkit-text-stroke:6px var(--ink)}.logo{width:48px;height:48px}}
.card{background:var(--card);border:3px solid var(--ink);border-radius:22px;box-shadow:0 6px 0 var(--ink);padding:14px 16px}
.side{display:flex;flex-direction:column;gap:18px;min-width:0}
h3{margin:0 0 10px;font:800 15px var(--font);letter-spacing:1.5px;text-transform:uppercase;color:var(--mut)}
#bw{position:relative;width:100%;max-width:720px;margin:0 auto;aspect-ratio:1;border:4px solid var(--ink);border-radius:28px;box-shadow:0 8px 0 var(--ink),0 0 0 8px rgba(255,255,255,.5);background:var(--pit1);overflow:hidden}
canvas{width:100%;height:100%;display:block;touch-action:manipulation}
#hint{width:max-content;max-width:100%;margin:22px auto 0;text-align:center;background:var(--card);border:2.5px solid var(--ink);border-radius:999px;padding:3px 18px;font-weight:600;font-size:14px;box-shadow:0 3px 0 var(--ink);display:block}
.hud{display:grid;gap:14px}
.hrow{display:flex;justify-content:space-between;align-items:center;gap:8px;font-weight:700}
.hrow>span{display:inline-flex;align-items:center;gap:6px}
#hp{display:flex;gap:3px}
#sc{font:800 32px/1 var(--font);color:var(--coral2)}
.bar{position:relative;height:22px;border:3px solid var(--ink);border-radius:999px;background:var(--line);overflow:hidden;margin-top:6px}
.bar>i{display:block;height:100%;width:100%;background:linear-gradient(#ffe066,#ffb400);border-radius:999px;transition:width .35s}
.bar>i::after{content:"";display:block;margin:3px 8px 0;height:4px;border-radius:9px;background:rgba(255,255,255,.65)}
.bar.low>i{background:linear-gradient(#ff8a8f,#e8384f)}
.pill{display:inline-flex;align-items:center;gap:6px;background:var(--line);border-radius:999px;padding:2px 12px 2px 6px;font-weight:800}
.tools{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.tb{display:flex;align-items:center;gap:9px;border:3px solid var(--ink);background:var(--card);color:var(--txt);border-radius:16px;padding:7px 10px 7px 7px;font:700 15px/1.1 var(--font);cursor:pointer;text-align:left;box-shadow:0 5px 0 var(--ink);transition:transform .1s,box-shadow .1s,background .15s}
.tb .ib{width:36px;height:36px;border-radius:50%;background:#fff;border:2.5px solid var(--ink);display:grid;place-items:center;flex:none}
.tb small{display:block;font-weight:600;color:var(--mut);font-size:11px;margin-top:2px}
.tb:hover{transform:translateY(-2px);box-shadow:0 7px 0 var(--ink)}
.tb.on{background:var(--c,var(--blue));color:#fff;transform:translateY(4px);box-shadow:0 1px 0 var(--ink)}
.tb.on small{color:#fff;opacity:.85}
.tb.sm{padding:5px 16px;border-radius:999px}
.btn{border:3px solid var(--ink);border-radius:16px;padding:8px 22px;font:800 16px var(--font);color:var(--ink);background:var(--sun);cursor:pointer;box-shadow:0 5px 0 var(--ink);transition:transform .1s,box-shadow .1s}
.btn:hover{transform:translateY(-2px);box-shadow:0 7px 0 var(--ink)}
.btn:active{transform:translateY(4px);box-shadow:0 1px 0 var(--ink)}
.btn.go{background:#4cd964}
.btn.ghost{background:#fff}
.tb:focus-visible,.btn:focus-visible{outline:3px solid var(--blue);outline-offset:3px}
#log{display:flex;flex-direction:column;gap:7px;font-size:14px;min-height:120px}
#log div{padding:5px 11px;border-radius:12px;background:var(--line);border-left:6px solid var(--mut);font-weight:600;animation:in .3s}
@keyframes in{from{opacity:0;transform:translateX(10px)}}
.row{display:flex;gap:14px;flex-wrap:wrap;justify-content:center}
.chips{display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin-bottom:18px}
#ov{position:fixed;inset:0;z-index:20;display:none;place-items:center;background:rgba(15,25,55,.62);padding:16px;overflow:auto}
#ov.on{display:grid;animation:in .25s}
#ovb{background:var(--card);border:4px solid var(--ink);border-radius:28px;padding:28px 26px 24px;max-width:520px;width:100%;text-align:center;box-shadow:0 10px 0 var(--ink);animation:pop .4s cubic-bezier(.2,1.5,.4,1)}
@keyframes pop{from{transform:scale(.8);opacity:0}}
.stamp{display:inline-block;font:800 28px var(--font);padding:2px 28px;background:var(--rib,var(--coral));color:#fff;border:3px solid var(--ink);border-radius:16px;box-shadow:0 5px 0 var(--ink);transform:rotate(-2deg);letter-spacing:.5px;text-shadow:0 2px 0 rgba(0,0,0,.25)}
#ovb ul{text-align:left;margin:0 0 18px;padding:0;list-style:none;font-size:15px;font-weight:600}
#ovb li{margin:10px 0;padding-left:32px;position:relative}
#ovb li .ic{position:absolute;left:0;top:2px;display:block}
@media(prefers-reduced-motion:reduce){*{animation-duration:.01ms!important;transition-duration:.01ms!important}}
</style>
</head>
<body>
<header>
  <div class="logo" id="logo"></div>
  <div><h1>Maze Mission</h1><div class="tag">Deep Logic · v3</div></div>
  <div class="sp"></div>
  <span class="chip" id="cLv">Level 1</span><span class="chip" id="cTot">Total 0</span><span class="chip" id="cBest">Rekor 0</span>
  <button class="tb sm" id="helpB">Aturan main</button>
</header>
<main>
  <section>
    <div id="bw"><canvas id="cv"></canvas></div>
    <div id="hint"></div>
  </section>
  <aside class="side">
    <div class="card hud">
      <div class="hrow"><span id="hp"></span><span id="sc">0</span></div>
      <div><div class="hrow"><span id="enL"></span><b id="enT"></b></div><div class="bar" id="enBar"><i id="en"></i></div></div>
      <div class="hrow"><span class="pill" id="cr"></span><span class="pill" id="so"></span></div>
    </div>
    <div class="card"><h3>Peralatan</h3><div class="tools" id="tools"></div></div>
    <div class="card"><h3>Catatan perjalanan</h3><div id="log"></div></div>
  </aside>
</main>
<div id="ov"><div id="ovb"></div></div>
<script>
"use strict";
const $=s=>document.querySelector(s);
const NLV=__NLV__;
const IC={
 heart:`<path d="M12 21s-8-4.8-8-11a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 10c0 6.2-8 11-8 11z" fill="#ef4f5f" stroke="#a82a3a" stroke-width="1.6" stroke-linejoin="round"/><path d="M7.4 8.6a2.2 2.2 0 0 1 2.1-1.7" stroke="#fff" stroke-width="1.7" stroke-linecap="round" fill="none" opacity=".85"/>`,
 heartoff:`<path d="M12 21s-8-4.8-8-11a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 10c0 6.2-8 11-8 11z" fill="#d5dbe0" stroke="#8d98a5" stroke-width="1.6" stroke-linejoin="round"/>`,
 flame:`<path d="M12 2.5c.6 3.8 6 6 6 11.2a6 6 0 0 1-12 0c0-2.6 1.2-4.2 2.6-5.4.3 1.8 1 2.8 2 3.1C10.2 8.8 10.6 5.5 12 2.5z" fill="#ff9f1c" stroke="#c2570a" stroke-width="1.6" stroke-linejoin="round"/><path d="M12 21.2a3 3 0 0 1-3-3c0-1.6 1.2-2.4 2-3.4.4 1 1 1.4 1.6 1.7.9.7 1.4 1.5 1.4 2.7a3 3 0 0 1-2 2z" fill="#ffe066"/>`,
 gem:`<path d="M7 3.5h10l4.5 5.5L12 21 2.5 9z" fill="#35c8f0" stroke="#127a9c" stroke-width="1.6" stroke-linejoin="round"/><path d="M7.5 9 9.5 3.5h5L16.5 9z" fill="#a8ecff"/><path d="M2.5 9h19M7.5 9 12 21l4.5-12" fill="none" stroke="#127a9c" stroke-width="1.2" stroke-linejoin="round"/>`,
 sonar:`<circle cx="12" cy="12" r="9" fill="#efe3ff" stroke="#6b3fc4" stroke-width="1.7"/><circle cx="12" cy="12" r="5" fill="none" stroke="#6b3fc4" stroke-width="1.6"/><circle cx="12" cy="12" r="1.8" fill="#6b3fc4"/><path d="M12 12 18.5 5.8" stroke="#6b3fc4" stroke-width="1.9" stroke-linecap="round"/>`,
 flag:`<path d="M6 21V3" stroke="#6b4a2b" stroke-width="2.2" stroke-linecap="round"/><path d="M6.5 4h12l-3 4.2 3 4.2h-12z" fill="#ef4f5f" stroke="#a82a3a" stroke-width="1.6" stroke-linejoin="round"/>`,
 wrench:`<path d="M15 3.5a5 5 0 0 0-4.6 6.8L3.5 17.2a2 2 0 0 0 0 2.8l.5.5a2 2 0 0 0 2.8 0l6.9-6.9A5 5 0 0 0 20.5 9l-3 3-2.8-.7L14 8.5l3-3z" fill="#7ad36b" stroke="#2c7a22" stroke-width="1.7" stroke-linejoin="round"/>`,
 arrow:`<circle cx="12" cy="12" r="9" fill="#dff1ff" stroke="#2f7de1" stroke-width="1.7"/><path d="M12 5l3.2 7L12 11l-3.2 1z" fill="#ef4f5f" stroke="#a82a3a" stroke-width="1.2" stroke-linejoin="round"/><path d="M12 19l-3.2-7L12 13l3.2-1z" fill="#fff" stroke="#6a7f93" stroke-width="1.2" stroke-linejoin="round"/>`,
 skull:`<path d="M12 3a8 8 0 0 0-5 14.2V21h10v-3.8A8 8 0 0 0 12 3z" fill="#f6f1e4" stroke="#4a4036" stroke-width="1.7" stroke-linejoin="round"/><circle cx="9" cy="12" r="2" fill="#4a4036"/><circle cx="15" cy="12" r="2" fill="#4a4036"/><path d="M10.5 21v-2.5M13.5 21v-2.5" stroke="#4a4036" stroke-width="1.5"/>`,
 lock:`<rect x="5" y="10.5" width="14" height="10.5" rx="2.5" fill="#ffc83d" stroke="#a8740a" stroke-width="1.7"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" fill="none" stroke="#a8740a" stroke-width="1.9"/><circle cx="12" cy="15.5" r="1.6" fill="#a8740a"/>`,
 star:`<path d="M12 2.8l2.8 5.9 6.4.8-4.7 4.4 1.2 6.4L12 17.2 6.3 20.3l1.2-6.4L2.8 9.5l6.4-.8z" fill="#ffd23f" stroke="#c78a00" stroke-width="1.7" stroke-linejoin="round"/>`,
 check:`<path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="#2e9e5b" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>`,
 cross:`<path d="M7 7l10 10M17 7 7 17" stroke="#ff8a3d" stroke-width="3.2" stroke-linecap="round"/>`,
 cup:`<path d="M7 3.5h10v6a5 5 0 0 1-10 0z" fill="#ffd23f" stroke="#c78a00" stroke-width="1.7" stroke-linejoin="round"/><path d="M7 5.5H3.5v2.2A3.5 3.5 0 0 0 7 11M17 5.5h3.5v2.2A3.5 3.5 0 0 1 17 11" fill="none" stroke="#c78a00" stroke-width="1.7"/><path d="M12 14.5v3.5M8 21h8M9.5 18h5" stroke="#c78a00" stroke-width="1.9" stroke-linecap="round"/>`
};
const ic=(n,s=18)=>`<svg class="ic" width="${s}" height="${s}" viewBox="0 0 24 24">${IC[n]}</svg>`;
const TOOLS={move:["Jalan","Klik sel di sebelahmu untuk melangkah. Klik sel yang pasti aman untuk berjalan otomatis.","#2f7de1","arrow","melangkah"],
 flag:["Bendera","Tandai sel yang kamu curigai sebagai jebakan. Gratis, hanya catatan.","#ef4f5f","flag","catatan"],
 disarm:["Jinakkan","Jinakkan sel di sebelahmu: jebakan benar +75, sel aman = alarm −1 nyawa. Biaya 1 energi.","#2e9e5b","wrench","−1 energi"],
 sonar:["Sonar","Cek PASTI satu sel dalam jarak 2 (jebakan atau aman). Hanya 2 kali per level.","#7a4fd6","sonar","2× per level"]};
let G=null,lv=0,total=0,tool="move",hover=null,parts=[],floats=[],shake=0,dp=[0,0],trail=[],busy=false,best=0,face=[0,1];
try{best=+localStorage.getItem("mmdl_best")||0}catch(e){}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const inb=(r,c)=>G&&r>=0&&c>=0&&r<G.n&&c<G.n;
const K=(r,c)=>r*G.n+c;
const N8=(r,c)=>{const o=[];for(let a=-1;a<=1;a++)for(let b=-1;b<=1;b++)if((a||b)&&inb(r+a,c+b))o.push([r+a,c+b]);return o};
const N4=(r,c)=>[[r-1,c],[r+1,c],[r,c-1],[r,c+1]].filter(p=>inb(p[0],p[1]));

// ---------- suara
let AC=null;
function tone(f,d=.1,type="sine",v=.05,slide=0,when=0){try{AC=AC||new(window.AudioContext||window.webkitAudioContext)();const o=AC.createOscillator(),g=AC.createGain(),t=AC.currentTime+when;o.type=type;o.frequency.setValueAtTime(f,t);if(slide)o.frequency.exponentialRampToValueAtTime(Math.max(30,f+slide),t+d);g.gain.setValueAtTime(v,t);g.gain.exponentialRampToValueAtTime(.0001,t+d);o.connect(g);g.connect(AC.destination);o.start(t);o.stop(t+d+.03)}catch(e){}}

// ---------- komunikasi dengan server Python (semua aturan & Trap tersembunyi ada di Python)
async function api(path,body){
  const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body||{})});
  const j=await r.json();if(!r.ok)throw new Error(j.error||"Kesalahan server");return j;
}
let ended=false;
const st=k=>G.wall.has(k)?"wall":G.vis.has(k)?"vis":G.clr.has(k)?"crater":G.son[k]==="T"?"sonT":(G.safe.has(k)||G.son[k]==="S")?"safe":"hid";
const ok=k=>!G.wall.has(k)&&(G.vis.has(k)||G.safe.has(k)||G.clr.has(k)||G.son[k]==="S");
const clue=(r,c)=>G.clues[K(r,c)]||0;
const clean=s=>String(s).replace(/[\u{1F000}-\u{1FFFF}\u2600-\u27BF\uFE0F]/gu,"").replace(/\s+/g," ").trim();
function lg(t,col){G.log.unshift([t,col]);G.log.length=Math.min(G.log.length,6);$("#log").innerHTML=G.log.map(([a,c])=>`<div style="${c?"border-left-color:"+c:""}">${clean(a)}</div>`).join("")}
const cxy=(r,c)=>[geo.ox+c*geo.cell+geo.cell/2,geo.oy+r*geo.cell+geo.cell/2];
function spark(r,c,cols,n=26,sp=4){const[x,y]=cxy(r,c);for(let i=0;i<n;i++){const a=Math.random()*6.283,s=sp*(.3+Math.random());parts.push({x,y,vx:Math.cos(a)*s,vy:Math.sin(a)*s,g:.05,l:1,d:.014+Math.random()*.012,col:cols[(Math.random()*cols.length)|0],sz:2.5+Math.random()*4})}}
function flt(r,c,s,col){floats.push({r,c,s,col,t0:performance.now()})}
function fx(e){
  const{t,r,c}=e;if(e.m)lg(e.m,e.col);
  if(t==="boom"){shake=1;spark(r,c,["#ff5a5f","#ff9f1c","#ffd23f"],50,6);flt(r,c,"−1 nyawa","#e8384f");tone(300,.5,"sawtooth",.08,-240)}
  else if(t==="step")tone(300,.07,"triangle",.04,120);
  else if(t==="gem"){spark(r,c,["#35c8f0","#9ee9ff","#ffffff"],30,4);flt(r,c,"+100","#1596c8");tone(880,.12,"sine",.05);tone(1320,.14,"sine",.04,0,.08)}
  else if(t==="disarm"){spark(r,c,["#4cd964","#ffffff"]);flt(r,c,"+75","#2e9e5b");tone(660,.1);tone(990,.14,"sine",.04,0,.08)}
  else if(t==="alarm"){shake=.6;flt(r,c,"Alarm! −1","#e8384f");tone(160,.3,"square",.06,-60)}
  else if(t==="sonar"){spark(r,c,e.trap?["#ff5a5f"]:["#4cd964"],18,3);tone(520,.25,"sine",.05,300)}
}
function apply(res){
  const s=res.state,old=G;
  G={n:s.n,wall:new Set(s.wall),cry:new Set(s.cry),ncry:s.ncry,hp:s.hp,en:s.en,max:s.max,got:s.got,sonar:s.sonar,pos:s.pos,
     vis:new Set(s.vis),safe:new Set(s.safe),clr:new Set(s.clr),son:s.son,clues:s.clues,score:s.score,status:s.status,why:s.why,
     reveal:s.status==="lose",trap:new Set(s.trap),flag:old?old.flag:new Set(),log:old?old.log:[]};
  if(old&&(old.pos[0]!==G.pos[0]||old.pos[1]!==G.pos[1])){face=[G.pos[0]-old.pos[0],G.pos[1]-old.pos[1]];trail.push(G.pos.slice())}
  for(const e of res.events||[])fx(e);
  ui();
  if(G.status!=="run"&&!ended){ended=true;end(G.status==="win",G.why)}
}
async function raw(path,body){try{apply(await api(path,body));return true}catch(e){lg("⚠ "+e.message,"var(--warn)");return false}}
async function call(path,body){if(busy||!G||G.status!=="run")return;busy=true;await raw(path,body);busy=false}
const move=(r,c)=>call("/api/move",{r,c});
function act(r,c){
  const k=K(r,c),[pr,pc]=G.pos,d=Math.abs(pr-r)+Math.abs(pc-c),ch=Math.max(Math.abs(pr-r),Math.abs(pc-c));
  if(tool==="flag"){if(G.vis.has(k)||G.wall.has(k))return;G.flag.has(k)?G.flag.delete(k):G.flag.add(k);tone(700,.06,"triangle",.04);return}
  if(G.wall.has(k))return lg("🧱 Itu dinding.");
  if(tool==="move"){if(d===1)return move(r,c);if(d>0&&ok(k))return walk(r,c);return lg("Pilih sel bersebelahan atau sel yang pasti aman.","var(--warn)")}
  if(tool==="disarm"){if(d!==1)return lg("Disarm hanya untuk sel bersebelahan.","var(--warn)");if(G.vis.has(k)||G.clr.has(k))return lg("Sel itu sudah beres.");G.flag.delete(k);return call("/api/disarm",{r,c})}
  if(tool==="sonar"){if(ch>2)return lg("Jangkauan Sonar maksimal 2 sel.","var(--warn)");if(G.sonar<=0)return lg("Sonar habis.","var(--warn)");if(ok(k)||k in G.son)return lg("Sel itu sudah diketahui.");return call("/api/sonar",{r,c})}
}
async function walk(r,c){
  const n=G.n,s=G.pos[0]*n+G.pos[1],t=K(r,c),prev=new Map([[s,-1]]),q=[s];
  for(let i=0;i<q.length;i++){const k=q[i];for(const[u,v]of N4((k/n)|0,k%n)){const j=K(u,v);if(!prev.has(j)&&ok(j)){prev.set(j,k);q.push(j)}}}
  if(!prev.has(t))return lg("Belum ada jalur aman ke sana.","var(--warn)");
  const path=[];for(let k=t;k!==s;k=prev.get(k))path.unshift(k);
  busy=true;for(const k of path){if(G.status!=="run")break;if(!(await raw("/api/move",{r:(k/n)|0,c:k%n})))break;await sleep(110)}busy=false;
}

// ---------- akhir level
function end(win,why){
  G.status=win?"win":"lose";G.reveal=!win;
  if(win){total+=G.score;if(total>best){best=total;try{localStorage.setItem("mmdl_best",best)}catch(e){}}
    for(let i=0;i<110;i++)parts.push({x:Math.random()*geo.W,y:-10-Math.random()*geo.W*.3,vx:(Math.random()-.5)*2,vy:2+Math.random()*3,g:.03,l:1,d:.004,col:["#ffc83d","#35c8f0","#4cd964","#ff5a5f","#a56cff"][i%5],sz:5+Math.random()*5});
    [523,659,784,1047].forEach((f,i)=>tone(f,.25,"triangle",.06,0,i*.12))}
  else{shake=1;tone(200,.7,"sawtooth",.07,-150)}
  ui();
  const chips=`<span class="chip">Skor <b>${G.score}</b></span><span class="chip">${ic("heart",14)} ${Math.max(0,G.hp)}</span><span class="chip">${ic("flame",14)} ${Math.max(0,G.en)}</span><span class="chip">${ic("gem",14)} ${G.got}/${G.ncry}</span><span class="chip">Total <b>${total}</b></span>`;
  const again=()=>{lv=0;total=0;start()};
  setTimeout(()=>win?(lv<NLV-1?ov("cup","Level selesai","Bonus nyawa dan energi sudah dihitung.",chips,[["Level berikutnya","go",()=>{lv++;start()}],["Lihat papan","ghost",()=>{}]],"var(--moss)")
    :ov("cup","Ekspedisi tamat",`Total skor akhirmu ${total}. Rekor: ${best}.`,chips,[["Main lagi dari awal","go",again]],"var(--moss)"))
   :ov("skull","Gagal",why,chips,[["Coba level ini lagi","go",()=>start()],["Mulai dari awal","ghost",again],["Lihat papan","ghost",()=>{}]],"var(--rust)"),win?900:1100);
}
function ov(icon,title,sub,chips,btns,col="var(--brass)"){
  $("#ovb").innerHTML=`<div style="color:${col};margin-bottom:10px">${ic(icon,44)}</div><div class="stamp" style="--rib:${col}">${title}</div><div style="color:var(--mut);margin:14px 0">${sub}</div>${chips?`<div class="chips">${chips}</div>`:""}<div class="row">${btns.map((b,i)=>`<button class="btn ${b[1]}" data-i="${i}">${b[0]}</button>`).join("")}</div>`;
  $("#ov").classList.add("on");
  $("#ovb").querySelectorAll("button").forEach(b=>b.onclick=()=>{$("#ov").classList.remove("on");btns[b.dataset.i][2]()});
}
function help(first){
  ov("arrow","Aturan main",`<ul>
  <li>${ic("gem",18,"var(--blue)")}<b>Misi:</b> ambil semua permata, lalu masuk ke gerbang ${ic("star",14,"var(--brass)")}. Gerbang terkunci ${ic("lock",14)} sampai permata habis.</li>
  <li><b>Angka</b> di sel = jumlah jebakan di <b>8 sel sekitarnya</b> (diagonal ikut). Angka <b>0</b> berarti 8 sel itu pasti aman. Angka ikut turun saat jebakan dijinakkan.</li>
  <li>${ic("heart",18,"var(--rust)")}<b>3 nyawa.</b> Menginjak jebakan −1 (jebakannya hancur). Menjinakkan sel yang ternyata aman juga −1.</li>
  <li>${ic("flame",18,"var(--brass)")}<b>Energi terbatas.</b> Tiap langkah atau penjinakan −1, tiap permata +3.</li>
  <li>${ic("wrench",18,"var(--moss)")}<b>Jinakkan</b> sel di sebelahmu (+75). ${ic("sonar",14,"var(--blue)")}<b>Sonar</b> memeriksa pasti satu sel dalam jarak 2 (2× per level). ${ic("flag",14,"var(--rust)")}<b>Bendera</b> hanya catatan.</li>
  <li><b>Skor:</b> permata +100, gerbang +500, sisa nyawa ×100, sisa energi ×5. Ada 6 level, makin besar dan padat.</li></ul>`,"",[[first?"Mulai ekspedisi":"Lanjut","go",()=>{if(first)start()}]]);
}

// ---------- UI
function ui(){
  $("#hp").innerHTML=[0,1,2].map(i=>ic(i<G.hp?"heart":"heartoff",30)).join("");
  const pc=Math.max(0,Math.min(100,Math.round(100*G.en/G.max)));
  $("#en").style.width=pc+"%";$("#enBar").classList.toggle("low",pc<=25);
  $("#enL").innerHTML=ic("flame",18,"var(--brass)")+"Energi";$("#enT").textContent=Math.max(0,G.en);
  $("#cr").innerHTML=ic("gem",20,"var(--blue)")+`<b>${G.got}</b>/${G.ncry}`;
  $("#so").innerHTML=ic("sonar",20,"var(--blue)")+`<b>${G.sonar}</b>`;$("#sc").textContent=G.score;
  $("#cLv").textContent=`Level ${lv+1} dari ${NLV} · ${G.n}×${G.n}`;$("#cTot").textContent="Total "+total;$("#cBest").textContent="Rekor "+best;
  document.querySelectorAll(".tb[data-t]").forEach(b=>b.classList.toggle("on",b.dataset.t===tool));
  $("#hint").textContent=TOOLS[tool][1];
}
function setTool(t){tool=t;if(G)ui()}
$("#tools").innerHTML=Object.entries(TOOLS).map(([k,v],i)=>`<button class="tb" data-t="${k}" style="--c:${v[2]}"><span class="ib">${ic(v[3],22)}</span><span>${v[0]}<small>${v[4]} · ${i+1}</small></span></button>`).join("");$("#logo").innerHTML=ic("gem",34);
document.querySelectorAll(".tb[data-t]").forEach(b=>b.onclick=()=>setTool(b.dataset.t));
$("#helpB").onclick=()=>help(false);
async function start(){
  G=null;tool="move";trail=[[0,0]];dp=[0,0];parts=[];floats=[];face=[0,1];busy=false;ended=false;
  try{apply(await api("/api/new",{level:lv}))}catch(e){alert("Gagal memulai: "+e.message);return}
  setup();lg(`Level ${lv+1}: ${G.n}×${G.n}, ${G.ncry} kristal. Angka = Trap di 8 sel sekitar.`,"var(--acc2)");
}

// ---------- input
const cv=$("#cv"),x=cv.getContext("2d");let geo={W:600,dpr:1,cell:80,ox:0,oy:0};
function setup(){const dpr=devicePixelRatio||1,W=Math.floor($("#bw").clientWidth)||600,n=G?G.n:7,cell=(W-28)/n;cv.width=cv.height=Math.floor(W*dpr);geo={W,dpr,cell,ox:(W-cell*n)/2,oy:(W-cell*n)/2}}
addEventListener("resize",setup);
function cellAt(ev){const b=cv.getBoundingClientRect(),px=(ev.clientX-b.left)*(geo.W/b.width),py=(ev.clientY-b.top)*(geo.W/b.height),c=Math.floor((px-geo.ox)/geo.cell),r=Math.floor((py-geo.oy)/geo.cell);return inb(r,c)?[r,c]:null}
cv.addEventListener("mousemove",ev=>hover=cellAt(ev));cv.addEventListener("mouseleave",()=>hover=null);
cv.addEventListener("click",ev=>{const p=cellAt(ev);if(p&&G&&G.status==="run"&&!busy)act(p[0],p[1])});
cv.addEventListener("contextmenu",ev=>{ev.preventDefault();const p=cellAt(ev);if(p&&G&&G.status==="run"){const k=K(p[0],p[1]);if(!G.vis.has(k)&&!G.wall.has(k))G.flag.has(k)?G.flag.delete(k):G.flag.add(k)}});
addEventListener("keydown",ev=>{
  if(!G||$("#ov").classList.contains("on"))return;
  const k=ev.key.toLowerCase(),m={arrowup:[-1,0],w:[-1,0],arrowdown:[1,0],s:[1,0],arrowleft:[0,-1],a:[0,-1],arrowright:[0,1],d:[0,1]}[k];
  if(m||k===" ")ev.preventDefault();
  if(m&&!busy)return move(G.pos[0]+m[0],G.pos[1]+m[1]);
  const t={1:"move",2:"flag",3:"disarm",4:"sonar"}[k];if(t)setTool(t);
  if(k==="f"&&hover&&G.status==="run"){const q=K(hover[0],hover[1]);if(!G.vis.has(q)&&!G.wall.has(q))G.flag.has(q)?G.flag.delete(q):G.flag.add(q)}
});

// ---------- render
const IM={};
const pal=()=>{const s=getComputedStyle(document.documentElement),g=n=>s.getPropertyValue(n).trim(),o={};for(const k of["leaf","leaf2","sand","sand2","mint","mint2","rock","rock2","coal","coral","coral2","sun","sun2","pit1","pit2","ink","card"])o[k]=g("--"+k);o.num=[1,2,3,4,5].map(i=>g("--n"+i));return o};
function rr(a,b,w,h,r){x.beginPath();x.roundRect?x.roundRect(a,b,w,h,r):x.rect(a,b,w,h)}
const hash=(k,i)=>{let h=(k*374761393+i*668265263)>>>0;h=((h^(h>>>13))*1274126177)>>>0;return((h^(h>>>16))>>>0)/4294967295};
function ico(n,cx,cy,s){const m=IM[n]||(IM[n]=Object.assign(new Image(),{src:"data:image/svg+xml;charset=utf-8,"+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="96" height="96">${IC[n]}</svg>`)}));if(m.complete&&m.naturalWidth)x.drawImage(m,cx-s/2,cy-s/2,s,s)}
function block(X,Y,w,top,side,d,hi){
  const r=geo.cell*.17;rr(X,Y+d,w,w,r);x.fillStyle=side;x.fill();rr(X,Y,w,w,r);x.fillStyle=top;x.fill();
  if(hi){x.save();rr(X,Y,w,w,r);x.clip();const g=x.createLinearGradient(0,Y,0,Y+w);g.addColorStop(0,"rgba(255,255,255,.38)");g.addColorStop(.55,"rgba(255,255,255,0)");x.fillStyle=g;x.fillRect(X,Y,w,w);x.restore()}
  rr(X,Y,w,w+d,r);x.lineWidth=Math.max(1.5,geo.cell*.03);x.strokeStyle="rgba(20,30,55,.55)";x.stroke();
}
function tx(s,cx,cy,sz,col,out){x.font=`800 ${sz}px "Baloo 2","Trebuchet MS",system-ui,sans-serif`;x.textAlign="center";x.textBaseline="middle";if(out){x.lineWidth=sz*.22;x.lineJoin="round";x.strokeStyle=out;x.strokeText(s,cx,cy+sz*.05)}x.fillStyle=col;x.fillText(s,cx,cy+sz*.05)}
function twinkle(cx,cy,s,a){x.save();x.translate(cx,cy);x.globalAlpha=a;x.fillStyle="#fff";x.beginPath();for(let i=0;i<8;i++){const r=i%2?s*.22:s,g=i*Math.PI/4;x.lineTo(Math.cos(g)*r,Math.sin(g)*r)}x.closePath();x.fill();x.restore()}
let P=null;
function draw(t){
  requestAnimationFrame(draw);if(!G)return;
  P=pal();const{W,dpr,cell,ox,oy}=geo,n=G.n,gap=cell*.05,d1=cell*.1,d0=cell*.035,fs=cell*.46;
  x.setTransform(dpr,0,0,dpr,0,0);x.clearRect(0,0,W,W);
  const bg=x.createLinearGradient(0,0,0,W);bg.addColorStop(0,P.pit1);bg.addColorStop(1,P.pit2);x.fillStyle=bg;x.fillRect(0,0,W,W);
  x.save();x.fillStyle="#fff";for(let i=0;i<16;i++){x.globalAlpha=.06+.05*Math.sin(t/900+i);x.beginPath();x.arc(hash(i,1)*W,hash(i,2)*W,3+hash(i,3)*10,0,7);x.fill()}x.restore();
  x.save();if(shake>0){x.translate((Math.random()-.5)*shake*10,(Math.random()-.5)*shake*10);shake=Math.max(0,shake-.03)}
  const near=new Set(G.status==="run"?N4(G.pos[0],G.pos[1]).map(([a,b])=>K(a,b)):[]);
  for(let r=0;r<n;r++)for(let c=0;c<n;c++){
    const k=K(r,c),s=st(k),X=ox+c*cell+gap,Y=oy+r*cell+gap,w=cell-2*gap,cx=X+w/2,cy=Y+w/2,hv=hover&&hover[0]===r&&hover[1]===c&&G.status==="run";
    if(s==="wall"){block(X,Y,w,P.rock,P.rock2,d1,true);x.strokeStyle=P.rock2;x.lineWidth=2;x.lineCap="round";x.beginPath();x.moveTo(X+w*.3,Y+w*.25);x.lineTo(X+w*.45,Y+w*.45);x.lineTo(X+w*.38,Y+w*.62);x.moveTo(X+w*.7,Y+w*.55);x.lineTo(X+w*.58,Y+w*.78);x.stroke()}
    else if(s==="vis"){block(X,Y+d1-d0,w,P.sand,P.sand2,d0,false);const q=clue(r,c);if(q>0)tx(q,cx,cy+d1-d0,fs*1.25,P.num[(q-1)%5],P.sand);else{x.globalAlpha=.5;x.fillStyle=P.sand2;x.beginPath();x.arc(cx,cy+d1-d0,cell*.05,0,7);x.fill();x.globalAlpha=1}}
    else if(s==="crater"){block(X,Y+d1-d0,w,P.coal,P.coal,d0,false);ico("cross",cx,cy+d1-d0,cell*.45)}
    else if(s==="sonT"){block(X,Y,w,P.coral,P.coral2,d1,true);ico("skull",cx,cy,cell*.58)}
    else if(s==="safe"){block(X,Y+d1-d0,w,P.mint,P.mint2,d0,false);ico("check",cx,cy+d1-d0,cell*.5)}
    else{const lf=hv?cell*.05:0;block(X,Y-lf,w,P.leaf,P.leaf2,d1,true);x.save();x.fillStyle="#fff";x.globalAlpha=.3;for(let i=0;i<2;i++){x.beginPath();x.ellipse(X+w*(.25+hash(k,i)*.5),Y-lf+w*(.25+hash(k,i+5)*.5),w*.12,w*.06,hash(k,i+9)*3,0,7);x.fill()}x.restore();
      if(G.reveal&&G.trap.has(k))ico("skull",cx,cy,cell*.5)}
    if(near.has(k)&&s!=="wall"){x.save();x.setLineDash([6,5]);x.lineDashOffset=-t/50;x.strokeStyle="#fff";x.lineWidth=3.5;rr(X-1,Y-1,w+2,w+d1+2,cell*.18);x.stroke();x.setLineDash([6,5]);x.lineDashOffset=-t/50+5.5;x.strokeStyle=TOOLS[tool][2];x.lineWidth=3.5;x.stroke();x.restore()}
    if(G.flag.has(k))ico("flag",X+w*.7,Y+w*.3,cell*.42);
  }
  for(const k of G.cry){const r=(k/n)|0,c=k%n,[cx,cy0]=cxy(r,c),bob=Math.sin(t/420+k)*cell*.035;
    x.fillStyle="rgba(0,0,0,.25)";x.beginPath();x.ellipse(cx,cy0+cell*.3,cell*.2,cell*.06,0,0,7);x.fill();
    ico("gem",cx,cy0+bob-cell*.02,cell*.66);twinkle(cx+cell*.18,cy0-cell*.2+bob,cell*.12,.5+.5*Math.sin(t/260+k))}
  {const X=ox+(n-1)*cell+gap,Y=oy+(n-1)*cell+gap,w=cell-2*gap,cx=X+w/2,cy=Y+w/2,open=G.got===G.ncry;
   if(open){const p=.5+.5*Math.sin(t/260);x.save();x.shadowColor="#ffd23f";x.shadowBlur=10+14*p;block(X,Y,w,P.sun,P.sun2,d1,true);x.restore();ico("star",cx,cy,cell*.6+p*cell*.05);twinkle(X+w*.8,Y+w*.2,cell*.13,p)}
   else{block(X,Y,w,P.rock,P.rock2,d1,true);ico("lock",cx,cy,cell*.5)}}
  tx("S",ox+cell*.22,oy+cell*.25,Math.max(10,cell*.22),"#fff",P.ink);
  if(trail.length>1){x.save();x.setLineDash([1,cell*.12]);x.lineCap="round";x.lineJoin="round";x.lineWidth=cell*.08;x.strokeStyle=P.ink;x.globalAlpha=.4;x.beginPath();trail.forEach((p,i)=>{const q=cxy(...p);i?x.lineTo(...q):x.moveTo(...q)});x.stroke();x.restore()}
  if(hover&&G.status==="run"){
    if(tool==="sonar"){x.save();x.setLineDash([8,7]);x.strokeStyle="#fff";x.lineWidth=3;rr(ox+(G.pos[1]-2)*cell,oy+(G.pos[0]-2)*cell,cell*5,cell*5,cell*.2);x.stroke();x.restore()}
    x.save();x.strokeStyle=TOOLS[tool][2];x.lineWidth=4;rr(ox+hover[1]*cell+2,oy+hover[0]*cell+2,cell-4,cell-4,cell*.2);x.stroke();x.restore()}
  player(t);
  parts=parts.filter(p=>p.l>0&&p.y<geo.W+30);
  for(const p of parts){p.x+=p.vx;p.y+=p.vy;p.vy+=p.g;p.l-=p.d;x.globalAlpha=Math.max(0,Math.min(1,p.l*1.6));x.fillStyle=p.col;if(p.g===.03)x.fillRect(p.x,p.y,p.sz,p.sz*.6);else{x.beginPath();x.arc(p.x,p.y,p.sz*p.l+1,0,7);x.fill()}}
  x.globalAlpha=1;
  floats=floats.filter(f=>t-f.t0<1200);
  for(const f of floats){const a=(t-f.t0)/1200,[cx,cy]=cxy(f.r,f.c);x.globalAlpha=1-a*a;tx(f.s,cx,cy-cell*.25-a*cell*.7,Math.max(14,cell*.3),f.col,"#fff")}
  x.globalAlpha=1;x.restore();
}
function player(t){
  const{cell,ox,oy}=geo,dead=G.hp<=0,mv=Math.hypot(G.pos[0]-dp[0],G.pos[1]-dp[1]);
  dp[0]+=(G.pos[0]-dp[0])*.3;dp[1]+=(G.pos[1]-dp[1])*.3;
  const bx=ox+dp[1]*cell+cell/2,by=oy+dp[0]*cell+cell/2,hop=mv>.03?Math.abs(Math.sin(t/85))*cell*.14:Math.sin(t/400)*cell*.012,cx=bx,cy=by-hop,R=cell*.26,fx=face[1],fy=face[0],ink=P.ink;
  x.fillStyle="rgba(0,0,0,.3)";x.beginPath();x.ellipse(bx,by+R*1.15,R*(.95-hop/cell*.8),R*.3,0,0,7);x.fill();
  x.lineWidth=Math.max(2,cell*.035);x.strokeStyle=ink;x.lineJoin="round";
  x.fillStyle=dead?"#b9c7b0":"#ffcfa3";x.beginPath();x.arc(cx,cy,R,0,7);x.fill();x.stroke();
  x.fillStyle="#d9902b";x.beginPath();x.ellipse(cx,cy-R*.4,R*1.3,R*.3,0,0,7);x.fill();x.stroke();
  x.fillStyle="#ffc83d";x.beginPath();x.arc(cx,cy-R*.4,R*.85,Math.PI,0);x.closePath();x.fill();x.save();x.clip();x.fillStyle="#ff5a5f";x.fillRect(cx-R,cy-R*.62,R*2,R*.2);x.restore();x.beginPath();x.arc(cx,cy-R*.4,R*.85,Math.PI,0);x.closePath();x.stroke();
  const ex=R*.38,ey=cy+R*.12+fy*R*.08;
  for(const s of[-1,1]){const px=cx+s*ex+fx*R*.12;
    if(dead){const q=R*.14;x.strokeStyle=ink;x.lineWidth=2.2;x.beginPath();x.moveTo(px-q,ey-q);x.lineTo(px+q,ey+q);x.moveTo(px+q,ey-q);x.lineTo(px-q,ey+q);x.stroke()}
    else{x.fillStyle="#fff";x.beginPath();x.arc(px,ey,R*.2,0,7);x.fill();x.lineWidth=1.5;x.strokeStyle=ink;x.stroke();x.fillStyle=ink;x.beginPath();x.arc(px+fx*R*.07,ey+fy*R*.07,R*.1,0,7);x.fill()}}
  if(!dead){x.fillStyle="rgba(255,90,95,.45)";for(const s of[-1,1]){x.beginPath();x.arc(cx+s*R*.62,ey+R*.3,R*.14,0,7);x.fill()}x.strokeStyle=ink;x.lineWidth=2;x.beginPath();x.arc(cx+fx*R*.08,cy+R*.38,R*.2,.15*Math.PI,.85*Math.PI);x.stroke()}
}
setup();requestAnimationFrame(draw);
help(true);
</script>
</body>
</html>
"""

# =====================================================================
# 3. SERVER LOKAL (stdlib)
# =====================================================================
class Session:
    lock = threading.Lock()
    game = None

S = Session()


def _pack(ev):
    return dict(state=S.game.state(), events=ev)


def api_new(b):
    S.game = Game(max(0, min(len(LEVELS) - 1, int(b.get("level", 0)))))
    return _pack([])


def _need_game():
    if S.game is None: raise ValueError("Mulai level dulu.")


def api_move(b):
    _need_game(); return _pack(S.game.move(int(b["r"]), int(b["c"])))


def api_disarm(b):
    _need_game(); return _pack(S.game.disarm(int(b["r"]), int(b["c"])))


def api_sonar(b):
    _need_game(); return _pack(S.game.sonar_scan(int(b["r"]), int(b["c"])))


ROUTES = {"/api/new": api_new, "/api/move": api_move, "/api/disarm": api_disarm, "/api/sonar": api_sonar}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store"); self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html"):
            self._send(200, HTML.replace("__NLV__", str(len(LEVELS))), "text/html; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        fn = ROUTES.get(self.path)
        if not fn: return self._send(404, json.dumps({"error": "not found"}), "application/json")
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            with S.lock:
                out = fn(body)
            self._send(200, json.dumps(out, ensure_ascii=False), "application/json; charset=utf-8")
        except Exception as e:
            self._send(400, json.dumps({"error": str(e)}, ensure_ascii=False), "application/json; charset=utf-8")


def main():
    server = None
    for port in (8801, 0):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler); break
        except OSError:
            continue
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    if server.server_address[1] != 8801:
        print("  (Port 8801 sedang dipakai program lain, jadi dipakai port otomatis di bawah.)")
    print(f"\n  MAZE MISSION: DEEP LOGIC berjalan di  {url}\n  (browser terbuka otomatis; Ctrl+C untuk berhenti)\n")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("Server dihentikan. Sampai jumpa!")


if __name__ == "__main__":
    main()
