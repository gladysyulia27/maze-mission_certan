#!/usr/bin/env python3
"""
MAZE MISSION: DEEP LOGIC  v5  "OPEN LOGIC PUZZLE"  (UI web lokal, tanpa library tambahan)

Cara menjalankan :  python maze_mission_deep_logic.py
Browser terbuka otomatis dan game LANGSUNG bisa dimainkan. Ctrl+C di terminal untuk berhenti.

PUZZLE LOGIKA MURNI (no-guess) — OPEN LOGIC PUZZLE
  * SEMUA angka petunjuk (jumlah Trap di 8 sel sekitar) TERLIHAT di papan sejak detik pertama.
    Pemain tidak perlu membuka/menginjak sel dulu untuk melihat angkanya: tinggal bernalar, baru melangkah.
  * Level TIDAK bisa dipilih. Harus mulai dari Level 1; Level berikutnya baru terbuka setelah level sebelumnya
    dimenangkan (dijaga di server, bukan hanya di tampilan).
  * Semua level dibaca dari DATASET tetap (folder dataset/), bukan diacak saat bermain.
  * Setiap level sudah DIBUKTIKAN bisa diselesaikan tanpa menebak oleh solver logika
    (maze_dataset.py). Saat start, game memverifikasi ulang dataset itu (hash + solver).

ATURAN
  * 10 level. Jumlah Trap pasti: Level 1 = 3, lalu +1 tiap level (4, 5, 6, ... 12).
  * Ambil Kunci Emas (key) -> baru gerbang bisa dilewati. Kristal hanya memberi Skor & Koin.
  * Angka pada setiap sel = jumlah Trap di 8 sel sekitarnya (termasuk diagonal; sel itu sendiri tidak dihitung).
    Angka 0 => 8 sel itu pasti aman. Sel Trap pun menampilkan angka, jadi tidak ada petunjuk "angka hilang".
  * 3 nyawa: menginjak Trap -1 (Trap hancur).
  * Energi terbatas: langkah -1 | Disarm -1 | Bendera -1.
    Disarm sel yang ternyata AMAN: alarm berbunyi -> energi -3 ekstra (nyawa tidak berkurang).
  * Sonar (jarak <= 2, 2x per level) memberi kepastian satu sel.
  * Skor: kristal +100 (+5 koin) | Disarm benar +75 | Trap -50 | Disarm salah -25
          gerbang +500 | sisa nyawa x100 | sisa energi x5
"""
import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import maze_dataset as DS

HERE = os.path.dirname(os.path.abspath(__file__))
S_CRYSTAL, S_GOAL, S_DISARM, S_TRAP, S_BAD_DISARM = 100, 500, 75, -50, -25
COIN_PER_CRYSTAL = 5
ALARM_ENERGY = 3        # penalti energi ekstra bila Disarm salah (di luar biaya 1 energi aksi)
HINT_COST = 1            # petunjuk langkah pasti dari angka clue: −1 energi
FLAG_COST = 1           # memasang bendera mengurangi 1 energi


def E(t, r, c, m="", col="", **kw):
    """Event kecil untuk efek/log di browser."""
    return dict(t=t, r=r, c=c, m=m, col=col, **kw)


# =====================================================================
# 1. GAME ENGINE  (level berasal dari DATASET, bukan acak)
# =====================================================================
class Game:
    def __init__(self, lv):
        self.lv = lv
        n = self.n = lv["n"]
        self.goal, self.key = lv["gate"], lv["key"]
        self.wall, self.trap = set(lv["wall"]), set(lv["trap"])
        self.cry, self.ncry = set(lv["crystals"]), len(lv["crystals"])
        self.total_traps = len(self.trap)
        self.B = DS.board(n)
        self.clue_tbl = [sum(1 for u in self.B.nb8[k] if u in self.trap) for k in range(n * n)]
        self.hp, self.got, self.sonar, self.score, self.coins = 3, 0, 2, 0, 0
        self.has_key = False
        self.en = self.max = lv["energy"]
        self.pos = (0, 0)
        # pengetahuan awal pemain: area start 2x2, gerbang, kunci & kristal (semua tampak di papan) pasti bukan Trap.
        # Semua angka petunjuk juga tampak sejak awal (Open Logic Puzzle).
        self.safe = DS.start_zone(n) | {self.goal, self.key} | set(self.cry)
        self.vis, self.clr, self.son, self.flags = {0}, set(), {}, set()
        self.status, self.why = "run", ""
        self.refresh()

    def clue(self, k):
        return self.clue_tbl[k]

    def refresh(self):
        """Mode terbuka: semua angka tampak, jadi setiap sel berangka 0 (bukan hanya yang sudah diinjak)
        langsung menandai 8 tetangganya sebagai pasti aman."""
        for k in range(self.n * self.n):
            if k not in self.wall and self.clue_tbl[k] == 0:
                for u in self.B.nb8[k]:
                    if u not in self.wall:
                        self.safe.add(u)

    def _need_run(self):
        if self.status != "run":
            raise ValueError("Permainan sudah berakhir.")

    def _cell(self, r, c):
        if not (0 <= r < self.n and 0 <= c < self.n):
            raise ValueError("Di luar papan.")
        return r * self.n + c

    def _end(self, win, why):
        self.status, self.why = ("win" if win else "lose"), why
        if win:
            self.score += S_GOAL + self.hp * 100 + self.en * 5

    def _after(self, ev):
        self.refresh()
        r, c = self.pos
        if self.hp <= 0:
            self._end(False, "Nyawamu habis.")
        elif r * self.n + c == self.goal:
            self._end(True, "")
        elif self.en <= 0:
            self._end(False, "Energi habis sebelum sampai gerbang.")
        return ev

    # ---- aksi
    def move(self, r, c):
        self._need_run()
        pr, pc = self.pos
        k = self._cell(r, c)
        if abs(pr - r) + abs(pc - c) != 1:
            raise ValueError("Hanya boleh melangkah ke sel bersebelahan.")
        if k in self.wall:
            raise ValueError("Itu dinding.")
        if k == self.goal and not self.has_key:
            raise ValueError("🔒 Gerbang terkunci — temukan Kunci Emas 🔑 dulu!")
        ev = []
        self.en -= 1
        self.pos = (r, c)
        self.vis.add(k)
        self.flags.discard(k)
        if k in self.trap and k not in self.clr:
            self.clr.add(k)
            self.hp -= 1
            self.score += S_TRAP
            ev.append(E("boom", r, c, "💥 Menginjak Trap! −1 nyawa, Trap hancur.", "var(--bad)"))
        else:
            ev.append(E("step", r, c))
        if k == self.key and not self.has_key:
            self.has_key = True
            ev.append(E("key", r, c, "🔑 Kunci Emas didapat! Gerbang kini bisa dilewati.", "var(--brass)"))
        if k in self.cry:
            self.cry.discard(k)
            self.got += 1
            self.coins += COIN_PER_CRYSTAL
            self.score += S_CRYSTAL
            ev.append(E("gem", r, c, f"💎 Kristal {self.got}/{self.ncry}! +{S_CRYSTAL} poin, +{COIN_PER_CRYSTAL} koin",
                        "var(--acc2)"))
        return self._after(ev)

    def disarm(self, r, c):
        self._need_run()
        pr, pc = self.pos
        k = self._cell(r, c)
        if abs(pr - r) + abs(pc - c) != 1:
            raise ValueError("Disarm hanya untuk sel bersebelahan.")
        if k in self.wall:
            raise ValueError("Itu dinding.")
        if k in self.vis or k in self.clr:
            raise ValueError("Sel itu sudah beres.")
        if k in self.safe:
            raise ValueError("Sel itu sudah pasti aman — tidak perlu dijinakkan.")
        self.en -= 1
        self.flags.discard(k)
        if k in self.trap:
            self.clr.add(k)
            self.score += S_DISARM
            ev = [E("disarm", r, c, "🔧 Disarm berhasil! Trap dijinakkan.", "var(--ok)")]
        else:
            self.en = max(0, self.en - ALARM_ENERGY)
            self.score += S_BAD_DISARM
            self.safe.add(k)                          # alarm membuktikan sel itu aman
            ev = [E("alarm", r, c, f"🚨 Salah! Sel itu aman — alarm berbunyi, energi −{1 + ALARM_ENERGY} (nyawa utuh).",
                    "var(--bad)")]
        return self._after(ev)

    def hint(self):
        """Petunjuk LOGIKA PASTI: hanya memakai angka clue + pengetahuan sah pemain (sel aman yang diumumkan,
        Trap yang sudah dijinakkan / terdeteksi sonar). Bendera pemain TIDAK dipercaya (bisa salah).
        Deduksi: R1 (angka vs sisa sel tak diketahui) dan R2 (selisih dua angka). Tidak pernah menebak."""
        self._need_run()
        if self.en <= HINT_COST:
            raise ValueError("Energi terlalu tipis untuk meminta petunjuk.")
        n, B = self.n, self.B
        base_safe = set(self.safe) | set(self.vis) | set(self.clr) | {k for k, v in self.son.items() if v == "S"}
        base_trap = set(self.clr) | {k for k, v in self.son.items() if v == "T"}
        safe, trap, why = set(base_safe), set(base_trap), {}
        cells = [k for k in range(n * n) if k not in self.wall]
        pos = lambda k: (k // n + 1, k % n + 1)
        changed = True
        while changed:
            changed = False
            cons = []
            for k in cells:
                U = frozenset(u for u in B.nb8[k] if u not in self.wall and u not in safe and u not in trap)
                if U:
                    cons.append((k, U, self.clue_tbl[k] - sum(1 for u in B.nb8[k] if u in trap)))
            for k, U, rem in cons:
                r_, c_ = pos(k)
                if rem == 0:
                    for u in U:
                        safe.add(u); changed = True
                        why[u] = ("safe", [k], f"Angka {self.clue_tbl[k]} di baris {r_}, kolom {c_}: Trap yang tersisa di sekelilingnya "
                                  f"sudah bisa dipastikan dari angka lain, jadi sel ini pasti AMAN.")
                elif rem == len(U):
                    for u in U:
                        trap.add(u); changed = True
                        why[u] = ("trap", [k], f"Angka {self.clue_tbl[k]} di baris {r_}, kolom {c_}: sisa sel yang belum "
                                  f"terbukti di sekelilingnya tepat sebanyak Trap yang masih dibutuhkan, jadi sel ini pasti TRAP.")
            if changed:
                continue
            for a, Ua, ra in cons:
                for b, Ub, rb in cons:
                    if a != b and Ua < Ub:
                        diff = Ub - Ua
                        ra_, ca_ = pos(a); rb_, cb_ = pos(b)
                        if rb == ra:
                            for u in diff:
                                if u not in safe:
                                    safe.add(u); changed = True
                                    why[u] = ("safe", [a, b], f"Angka di baris {ra_}, kolom {ca_} dan angka di baris {rb_}, kolom {cb_} "
                                              f"menuntut jumlah Trap yang sama, padahal yang kedua punya sel ekstra, jadi sel ekstra ini pasti AMAN.")
                        elif rb - ra == len(diff):
                            for u in diff:
                                if u not in trap:
                                    trap.add(u); changed = True
                                    why[u] = ("trap", [a, b], f"Angka di baris {rb_}, kolom {cb_} butuh {rb - ra} Trap lebih banyak daripada "
                                              f"angka di baris {ra_}, kolom {ca_}, dan sel ekstra tepat sebanyak itu, jadi semuanya pasti TRAP.")
        # sel yang bisa dijangkau pemain lewat sel yang sudah pasti aman
        passable = lambda k: k not in self.wall and (k not in trap or k in self.clr) and not (k == self.goal and not self.has_key)
        start = self.pos[0] * n + self.pos[1]
        reach, q = {start}, [start]
        while q:
            u = q.pop(0)
            for v in B.nb4[u]:
                if v not in reach and v in base_safe and passable(v):
                    reach.add(v); q.append(v)
        # tujuan: kunci -> kristal terdekat -> gerbang
        goals = [self.key] if not self.has_key else (sorted(self.cry) or [self.goal])
        dist, q = {g: 0 for g in goals}, list(goals)
        while q:
            u = q.pop(0)
            for v in B.nb4[u]:
                if v not in dist and v not in self.wall and (v not in trap or v in self.clr):
                    dist[v] = dist[u] + 1; q.append(v)
        front = lambda k: any(v in reach for v in B.nb4[k])
        new_safe = [u for u in safe - base_safe if u not in self.wall and front(u)]
        new_trap = [u for u in trap - base_trap if front(u)]
        self.en -= HINT_COST
        if new_safe:
            u = min(new_safe, key=lambda k: (dist.get(k, 999), k))
            kind, msg = "safe", why[u][2]
        elif new_trap:
            u = min(new_trap, key=lambda k: (dist.get(k, 999), k))
            kind, msg = "trap", why[u][2] + " Jinakkan atau lewati; jangan diinjak."
        else:
            u = None
            cand = [v for v in B.nb4[start] if v in reach and v in dist]
            if cand:
                u = min(cand, key=lambda k: dist[k])
                kind, msg = "step", "Jalur ke tujuan sudah pasti aman — lanjutkan melangkah ke sel ini."
            else:
                return [E("hint", self.pos[0], self.pos[1], "Tidak ada deduksi baru dari angka yang tersedia saat ini.", "var(--warn)",
                          kind="none", basis=[])]
        r, c = divmod(u, n)
        basis = [list(divmod(b, n)) for b in why[u][1]] if u in why else []
        return [E("hint", r, c, f"💡 Petunjuk (−{HINT_COST} energi): {msg}", "var(--acc2)", kind=kind, basis=basis)]

    def flag(self, r, c):
        self._need_run()
        k = self._cell(r, c)
        if k in self.wall or k in self.vis or k in self.clr or k == self.goal:
            raise ValueError("Sel ini tidak bisa diberi bendera.")
        if k in self.flags:                           # mencabut bendera gratis (tanpa refund)
            self.flags.discard(k)
            return [E("unflag", r, c, "🚩 Bendera dicabut.", "")]
        if k in self.safe:
            raise ValueError("Sel itu sudah pasti aman — tidak perlu bendera.")
        if self.en <= FLAG_COST:
            raise ValueError("Energi terlalu tipis untuk memasang bendera.")
        self.en -= FLAG_COST
        self.flags.add(k)
        return [E("flag", r, c, f"🚩 Bendera dipasang — energi −{FLAG_COST}.", "var(--warn)")]

    def sonar_scan(self, r, c):
        self._need_run()
        pr, pc = self.pos
        k = self._cell(r, c)
        if max(abs(pr - r), abs(pc - c)) > 2:
            raise ValueError("Jangkauan Sonar maksimal 2 sel.")
        if self.sonar <= 0:
            raise ValueError("Sonar habis.")
        if k in self.wall:
            raise ValueError("Itu dinding.")
        if k in self.vis or k in self.clr or k in self.safe or k in self.son:
            raise ValueError("Sel itu sudah diketahui.")
        self.sonar -= 1
        t = k in self.trap
        self.son[k] = "T" if t else "S"
        self.flags.discard(k)
        self.refresh()
        return [E("sonar", r, c, f"📡 Sonar: ({r},{c}) adalah TRAP ☠" if t else f"📡 Sonar: ({r},{c}) AMAN ✓",
                  "var(--bad)" if t else "var(--ok)", trap=t)]

    def state(self):
        """Hanya info yang boleh diketahui pemain. Posisi Trap baru dibuka saat kalah.
        Angka petunjuk SEMUA sel (non-dinding) dikirim sejak awal; letak Trap tidak."""
        n = self.n
        return dict(n=self.n, level=self.lv["id"], wall=sorted(self.wall), cry=sorted(self.cry), ncry=self.ncry,
                    key=(-1 if self.has_key else self.key), has_key=self.has_key, gate=self.goal,
                    hp=self.hp, en=self.en, max=self.max, got=self.got, coins=self.coins, sonar=self.sonar,
                    pos=list(self.pos), vis=sorted(self.vis), safe=sorted(self.safe), clr=sorted(self.clr),
                    flags=sorted(self.flags), traps_total=self.total_traps,
                    son={str(k): v for k, v in self.son.items()}, score=self.score,
                    status=self.status, why=self.why, sha=self.lv["sha256"][:12],
                    clues={str(k): self.clue_tbl[k] for k in range(n * n) if k not in self.wall},   # SEMUA angka terlihat
                    unlocked=S.unlocked, open_clues=True,
                    trap=sorted(self.trap) if self.status == "lose" else [])


# =====================================================================
# 2. DATASET (dimuat + diverifikasi saat start)
# =====================================================================
DATASET = DS.load_or_build()
LEVELS = DATASET["levels"]
DATASET_OK = DS.verify(DATASET, log=lambda *_: None)
SUMMARY = DS.public_summary(DATASET)
SUMMARY["verified"] = DATASET_OK


def load_html():
    with open(os.path.join(HERE, "web", "index.html"), encoding="utf-8") as f:
        return f.read().replace("__NLV__", str(len(LEVELS)))


# =====================================================================
# 3. SERVER LOKAL (stdlib)
# =====================================================================
class Session:
    lock = threading.Lock()
    game = None
    unlocked = 0        # indeks level tertinggi yang boleh dimainkan (0 = baru Level 1)


S = Session()


def _pack(ev):
    g = S.game
    if g.status == "win":                                   # menang -> level berikutnya terbuka
        S.unlocked = max(S.unlocked, min(len(LEVELS) - 1, g.lv["id"]))   # id = indeks+1 = indeks level berikutnya
    return dict(state=g.state(), events=ev)


def api_new(b):
    """Mulai/ulang level. Level tidak bisa dipilih bebas:
       * Level 1 selalu boleh (dan memulai ulang seluruh progres),
       * mengulang level yang sedang dimainkan boleh,
       * Level k+1 hanya boleh setelah Level k dimenangkan (S.unlocked)."""
    want = int(b.get("level", 0))
    if want < 0 or want >= len(LEVELS):
        raise ValueError("Level tidak ada.")
    if want > S.unlocked:
        raise ValueError(f"Level {want + 1} masih terkunci. Selesaikan Level {S.unlocked + 1} dulu.")
    if want == 0:
        S.unlocked = 0                                       # mulai dari awal = progres direset
    S.game = Game(LEVELS[want])
    return _pack([])


def _need_game():
    if S.game is None:
        raise ValueError("Mulai level dulu.")


def api_move(b):
    _need_game()
    return _pack(S.game.move(int(b["r"]), int(b["c"])))


def api_disarm(b):
    _need_game()
    return _pack(S.game.disarm(int(b["r"]), int(b["c"])))


def api_sonar(b):
    _need_game()
    return _pack(S.game.sonar_scan(int(b["r"]), int(b["c"])))


def api_hint(b):
    _need_game()
    return _pack(S.game.hint())


def api_flag(b):
    _need_game()
    return _pack(S.game.flag(int(b["r"]), int(b["c"])))


ROUTES = {"/api/new": api_new, "/api/move": api_move, "/api/disarm": api_disarm,
          "/api/sonar": api_sonar, "/api/flag": api_flag, "/api/hint": api_hint}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send(200, load_html(), "text/html; charset=utf-8")
        elif path == "/api/dataset":
            self._send(200, json.dumps(SUMMARY, ensure_ascii=False), "application/json; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        fn = ROUTES.get(self.path)
        if not fn:
            return self._send(404, json.dumps({"error": "not found"}), "application/json")
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
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    if server.server_address[1] != 8801:
        print("  (Port 8801 sedang dipakai program lain, jadi dipakai port otomatis di bawah.)")
    print(f"\n  Dataset: {len(LEVELS)} level — " +
          ("TERVERIFIKASI, setiap level solvable tanpa tebakan (0 tebakan)." if DATASET_OK
           else "PERINGATAN: verifikasi gagal! Jalankan: python maze_dataset.py generate"))
    print(f"  MAZE MISSION: DEEP LOGIC berjalan di  {url}\n  (browser terbuka otomatis; Ctrl+C untuk berhenti)\n")
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
