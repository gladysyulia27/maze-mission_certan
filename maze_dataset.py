#!/usr/bin/env python3
"""
MAZE MISSION: DEEP LOGIC — DATASET, SOLVER LOGIKA & VERIFIER   (v5: Open Logic Puzzle)
===================================================================================
Modul ini adalah BUKTI (evidence) bahwa game bukan tebak-tebakan acak.

MODE "OPEN LOGIC PUZZLE": semua angka petunjuk (jumlah trap di 8 sel sekitar) TERLIHAT di papan sejak
detik pertama. Solver memakai seluruh angka itu sejak awal, jadi pembuktian & tingkat kesulitan level
dihitung dengan model informasi yang sama dengan yang dilihat pemain.

  * Semua level disimpan sebagai DATASET tetap di folder  dataset/
        levels.json      data lengkap tiap level + bukti solver
        levels.csv       ringkasan 1 baris per level
        cells.csv        data per-sel (tipe sel + angka petunjuk)  -> dataset "mentah"
        proof_steps.csv  langkah deduksi logika yang membuktikan level bisa diselesaikan
        README.md        laporan otomatis
  * Setiap level DIBUKTIKAN solvable tanpa menebak oleh SOLVER LOGIKA (di bawah) yang
    hanya memakai aturan deduksi (R1 dasar, R2 irisan-himpunan, R3 enumerasi kemungkinan).
    Solver tidak pernah melangkah ke sel yang belum terbukti aman  =>  tebakan = 0.
    Kesulitan level: MODE MUDAH — semua level cukup aturan R1 (angka vs sisa sel), jumlah Trap sedikit & naik pelan.
  * Level generator memakai seed tetap => dataset 100% reproducible.

Perintah:
    python maze_dataset.py generate   # bangun ulang dataset (seed tetap, hasil sama)
    python maze_dataset.py verify     # cek ulang integritas + jalankan solver di tiap level
    python maze_dataset.py report     # cetak tabel ringkasan
"""
import csv
import hashlib
import heapq
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "dataset")
JSON_PATH = os.path.join(DATA_DIR, "levels.json")

# ---------------------------------------------------------------- spesifikasi level
SIZES = [7, 7, 8, 8, 9, 9, 10, 10, 11, 11]          # ukuran papan per level
N_LEVELS = len(SIZES)                                # 10 level
WALL_P = 0.10                                        # kepadatan dinding labirin
BASE_SEED = 20261104
OPEN_CLUES = True                                    # semua angka petunjuk terlihat sejak awal
MAX_RULE_BY_LEVEL = [1] * 10                         # mode mudah: semua level cukup R1
MIN_RULE2_BY_LEVEL = [0] * 10                        # tidak ada kewajiban R2


def trap_count(level):          # Level 1 = 3, lalu +1 setiap level (3, 4, 5, ... 12)
    return 2 + level


def crystal_count(level):
    return 2 + (level - 1) // 2


# ---------------------------------------------------------------- util papan
class Board:
    def __init__(self, n):
        self.n = n
        self.nb8 = []
        self.nb4 = []
        for k in range(n * n):
            r, c = divmod(k, n)
            self.nb8.append([(r + a) * n + c + b for a in (-1, 0, 1) for b in (-1, 0, 1)
                             if (a or b) and 0 <= r + a < n and 0 <= c + b < n])
            self.nb4.append([(r + a) * n + c + b for a, b in ((-1, 0), (1, 0), (0, -1), (0, 1))
                             if 0 <= r + a < n and 0 <= c + b < n])


_BOARDS = {}


def board(n):
    if n not in _BOARDS:
        _BOARDS[n] = Board(n)
    return _BOARDS[n]


def start_zone(n):
    return {0, 1, n, n + 1}      # area start 2x2 (dijamin bersih & diumumkan ke pemain)


def level_hash(lv):
    core = dict(n=lv["n"], start=lv["start"], gate=lv["gate"], key=lv["key"],
                crystals=sorted(lv["crystals"]), wall=sorted(lv["wall"]), trap=sorted(lv["trap"]))
    return hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def clue_of(lv, k):
    trap = set(lv["trap"])
    return sum(1 for u in board(lv["n"]).nb8[k] if u in trap)


# ---------------------------------------------------------------- SOLVER LOGIKA
class Stuck(Exception):
    pass


class Solver:
    """
    Meniru pemain yang HANYA memakai logika:
      - Pengetahuan awal  : dinding, area start 2x2, gerbang, kunci, kristal (semua tampak & pasti bukan trap).
      - Angka SEMUA sel (non-dinding) terlihat sejak awal = jumlah trap di 8 sel sekitar (statis).
      - Angka 0 membuka 8 tetangganya sebagai aman (otomatis oleh game).
      - Deduksi:  R1 basis | R2 irisan dua angka | R3 enumerasi semua konfigurasi yang konsisten.
      - Melangkah hanya ke sel yang SUDAH terbukti aman; trap yang terbukti & menghalangi jalan dijinakkan dulu.
    """

    def __init__(self, lv, all_crystals=True, max_rule=3, hw=1.0):
        self.lv = lv
        self.n = lv["n"]
        self.B = board(self.n)
        self.wall = set(lv["wall"])
        self.trap = set(lv["trap"])               # kebenaran tersembunyi: HANYA untuk memberi angka & cek soundness
        self.key = lv["key"]
        self.cry = set(lv["crystals"])
        self.gate = lv["gate"]
        self.start = lv["start"]
        self.all_crystals = all_crystals
        self.max_rule = max_rule
        self.hw = hw
        self.clue = [sum(1 for u in self.B.nb8[k] if u in self.trap) for k in range(self.n * self.n)]

        self.safe = set(self.cry) | {self.key, self.gate} | start_zone(self.n)
        self.ktrap, self.cleared, self.vis = set(), set(), set()
        self.pos, self.has_key, self.got = self.start, False, set()
        if OPEN_CLUES:
            self.open_zero()
        self.cost = 0
        self.steps, self.route = [], []
        self.rule_counts = {1: 0, 2: 0, 3: 0}
        self.rule_used_max = 0
        self.sound = True
        self.visit(self.start)

    # ---- pengetahuan
    def open_zero(self):
        """Mode terbuka: semua angka tampak, jadi setiap sel berangka 0 langsung membuka 8 tetangganya."""
        for k in range(self.n * self.n):
            if k not in self.wall and self.clue[k] == 0:
                for u in self.B.nb8[k]:
                    if u not in self.wall:
                        self.safe.add(u)

    def visit(self, k):
        self.vis.add(k)
        self.safe.add(k)
        if self.clue[k] == 0:
            for u in self.B.nb8[k]:
                if u not in self.wall:
                    self.safe.add(u)

    def _fact(self, k, verdict, rule, basis):
        if verdict == "safe":
            if k in self.ktrap:
                raise RuntimeError("kontradiksi")
            if k in self.safe:
                return False
            self.safe.add(k)
            if k in self.trap:
                self.sound = False
        else:
            if k in self.safe:
                raise RuntimeError("kontradiksi")
            if k in self.ktrap:
                return False
            self.ktrap.add(k)
            if k not in self.trap:
                self.sound = False
        self.rule_counts[rule] += 1
        self.rule_used_max = max(self.rule_used_max, rule)
        self.steps.append(dict(i=len(self.steps) + 1, rule=rule, cell=k, verdict=verdict, basis=list(basis)[:6]))
        return True

    def constraints(self):
        out = []
        src = [k for k in range(self.n * self.n) if k not in self.wall] if OPEN_CLUES else self.vis
        for v in src:
            U = frozenset(u for u in self.B.nb8[v] if u not in self.wall and u not in self.safe and u not in self.ktrap)
            if U:
                need = self.clue[v] - sum(1 for u in self.B.nb8[v] if u in self.ktrap)
                out.append((v, U, need))
        return out

    def rule1(self):
        ch = 0
        for v, U, need in self.constraints():
            if need == 0:
                for u in U:
                    ch += self._fact(u, "safe", 1, [v])
            elif need == len(U):
                for u in U:
                    ch += self._fact(u, "trap", 1, [v])
        return ch

    def rule2(self):
        ch = 0
        cons = self.constraints()
        for v1, U1, n1 in cons:
            for v2, U2, n2 in cons:
                if v1 != v2 and U1 < U2:
                    D, nd = U2 - U1, n2 - n1
                    if nd == 0:
                        for u in D:
                            ch += self._fact(u, "safe", 2, [v1, v2])
                    elif nd == len(D):
                        for u in D:
                            ch += self._fact(u, "trap", 2, [v1, v2])
        return ch

    def rule3(self, node_cap=400000):
        ch = 0
        cons = self.constraints()
        if not cons:
            return 0
        # komponen konstrain yang saling berbagi variabel
        parent = {}

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        for v, U, _ in cons:
            for u in U:
                parent.setdefault(u, u)
        for v, U, _ in cons:
            L = list(U)
            for u in L[1:]:
                parent[find(u)] = find(L[0])
        comps = {}
        for v, U, need in cons:
            comps.setdefault(find(next(iter(U))), []).append((v, U, need))
        for comp in comps.values():
            vars_ = sorted({u for _, U, _ in comp for u in U})
            if len(vars_) > 30:
                continue
            idx = {u: i for i, u in enumerate(vars_)}
            cl = [([idx[u] for u in U], need) for _, U, need in comp]
            by_var = [[] for _ in vars_]
            for ci, (vs, _) in enumerate(cl):
                for x in vs:
                    by_var[x].append(ci)
            assigned = [0] * len(cl)
            unassigned = [len(vs) for vs, _ in cl]
            can_t, can_s = [False] * len(vars_), [False] * len(vars_)
            order = sorted(range(len(vars_)), key=lambda x: -len(by_var[x]))
            assign = [None] * len(vars_)
            nodes = [0]
            found = [0]

            def dfs(pos):
                nodes[0] += 1
                if nodes[0] > node_cap:
                    raise Stuck("terlalu besar")
                if pos == len(order):
                    found[0] += 1
                    for x, a in enumerate(assign):
                        if a:
                            can_t[x] = True
                        else:
                            can_s[x] = True
                    return
                x = order[pos]
                for val in (0, 1):
                    ok = True
                    for ci in by_var[x]:
                        assigned[ci] += val
                        unassigned[ci] -= 1
                    for ci in by_var[x]:
                        need = cl[ci][1]
                        if assigned[ci] > need or assigned[ci] + unassigned[ci] < need:
                            ok = False
                            break
                    if ok:
                        assign[x] = val
                        dfs(pos + 1)
                        assign[x] = None
                    for ci in by_var[x]:
                        assigned[ci] -= val
                        unassigned[ci] += 1
            try:
                dfs(0)
            except Stuck:
                continue
            if not found[0]:
                raise RuntimeError("tidak ada solusi konsisten")
            basis = [v for v, _, _ in comp]
            for x, u in enumerate(vars_):
                if not can_t[x] and can_s[x]:
                    ch += self._fact(u, "safe", 3, basis)
                elif can_t[x] and not can_s[x]:
                    ch += self._fact(u, "trap", 3, basis)
        return ch

    def deduce_cheap(self):
        while True:
            if self.rule1():
                continue
            if self.max_rule >= 2 and self.rule2():
                continue
            break

    # ---- pergerakan
    def passable(self, k):
        if k in self.wall:
            return False
        if k == self.gate and not self.has_key:
            return False
        return k in self.vis or k in self.safe or k in self.ktrap

    def dijkstra(self):
        dist, prev = {self.pos: 0}, {}
        pq = [(0, self.pos)]
        while pq:
            d, k = heapq.heappop(pq)
            if d > dist[k]:
                continue
            for u in self.B.nb4[k]:
                if not self.passable(u):
                    continue
                w = 2 if (u in self.ktrap and u not in self.cleared) else 1
                if d + w < dist.get(u, 1 << 30):
                    dist[u] = d + w
                    prev[u] = k
                    heapq.heappush(pq, (d + w, u))
        return dist, prev

    def walk(self, target, prev):
        path = []
        k = target
        while k != self.pos:
            path.append(k)
            k = prev[k]
        for k in reversed(path):
            if k in self.ktrap and k not in self.cleared:
                self.cleared.add(k)
                self.cost += 1
                self.route.append(["d", k])
            self.cost += 1
            self.route.append(["m", k])
            if k in self.trap and k not in self.cleared:
                raise RuntimeError("melangkah ke trap = tebakan!")
            self.pos = k
            self.visit(k)
            if k == self.key:
                self.has_key = True
            if k in self.cry:
                self.got.add(k)

    def remaining(self):
        rem = []
        if not self.has_key:
            rem.append(self.key)
        if self.all_crystals:
            rem += [c for c in self.cry if c not in self.got]
        if self.has_key and not rem:
            rem.append(self.gate)
        return rem

    def run(self):
        for _ in range(4000):
            self.deduce_cheap()
            if self.pos == self.gate:
                return True
            rem = self.remaining()
            dist, prev = self.dijkstra()
            reach = [t for t in rem if t in dist]
            if reach:
                self.walk(min(reach, key=lambda t: dist[t]), prev)
                continue
            cands = [k for k in dist if k in self.safe and k not in self.vis and k != self.pos]
            if cands:
                n = self.n

                def h(k):
                    r, c = divmod(k, n)
                    return min(abs(r - t // n) + abs(c - t % n) for t in rem)
                self.walk(min(cands, key=lambda k: dist[k] + self.hw * h(k)), prev)
                continue
            if self.max_rule >= 3 and self.rule3():
                continue
            raise Stuck("buntu: tidak ada langkah yang terbukti aman")
        raise Stuck("batas iterasi")


def solve(lv, all_crystals=True, max_rule=3):
    """Coba beberapa bobot heuristik eksplorasi; ambil rencana dengan energi paling hemat."""
    best = None
    for hw in (0.5, 1.0, 2.0, 3.0, 5.0):
        s = Solver(lv, all_crystals, max_rule, hw)
        try:
            s.run()
        except Stuck:
            continue
        if best is None or s.cost < best.cost:
            best = s
    if best is None:
        raise Stuck("tidak ada rencana tanpa tebakan")
    return best


def analyze(lv, max_rule=3):
    """Jalankan solver (kumpulkan semua kristal) + (hanya kunci+gerbang). None bila ada langkah yang butuh tebakan."""
    try:
        full = solve(lv, True, max_rule)
        mini = solve(lv, False, max_rule)
    except (Stuck, RuntimeError):
        return None
    if not (full.sound and mini.sound):
        return None
    energy = int(max(full.cost, mini.cost) * 1.30 + 0.999) + 6
    return dict(
        guesses=0, sound=True, solved=True,
        deductions=len(full.steps), rule1=full.rule_counts[1], rule2=full.rule_counts[2], rule3=full.rule_counts[3],
        max_rule=full.rule_used_max, plan_cost_full=full.cost, plan_cost_min=mini.cost, energy=energy,
        steps=full.steps, route=full.route)


# ---------------------------------------------------------------- GENERATOR (seed tetap)
def connected(n, wall, a, b):
    B, seen, st = board(n), {a}, [a]
    while st:
        k = st.pop()
        for u in B.nb4[k]:
            if u not in wall and u not in seen:
                seen.add(u)
                st.append(u)
    return b in seen


def candidate(level, seed):
    rng = random.Random(seed)
    n = SIZES[level - 1]
    N, gate, zone = n * n, n * n - 1, start_zone(n)
    wall = {k for k in range(N) if k not in zone and k != gate and rng.random() < WALL_P}
    if not connected(n, wall, 0, gate):
        return None
    free = [k for k in range(N) if k not in wall and k not in zone and k != gate]
    T, C = trap_count(level), crystal_count(level)
    if len(free) < T + C + 6:
        return None
    trap = set(rng.sample(free, T))
    rest = [k for k in free if k not in trap]
    far = [k for k in rest if k // n + k % n >= n]
    if not far:
        return None
    key = rng.choice(far)
    pool = [k for k in rest if k != key and k // n + k % n >= 3]
    if len(pool) < C:
        return None
    crystals = sorted(rng.sample(pool, C))
    return dict(id=level, n=n, seed=seed, start=0, gate=gate, key=key, crystals=crystals,
                wall=sorted(wall), trap=sorted(trap))


def difficulty_ok(level, pr, mr, r1_enough):
    """Kurva kesulitan (mode terbuka): Level 1-2 cukup R1. Level 3-10 WAJIB memakai R2 (R1 saja buntu),
    dan jumlah deduksi R2 yang dibutuhkan naik tiap level. Rute makin panjang di level tinggi."""
    if pr["rule3"]:
        return False
    if pr["deductions"] < trap_count(level) + 2 or pr["plan_cost_full"] < 10 + 2 * level:
        return False
    n = SIZES[level - 1]
    if max(pr["plan_cost_full"], pr["plan_cost_min"]) > 5 * n:      # energi tidak boleh absurd
        return False
    return r1_enough and pr["rule1"] > 0 and pr["rule2"] == 0     # mode mudah: hanya R1


def build_level(level, tries=400000):
    mr = MAX_RULE_BY_LEVEL[level - 1]
    for a in range(tries):
        seed = BASE_SEED + level * 100000 + a
        lv = candidate(level, seed)
        if not lv:
            continue
        pr = analyze(lv, mr)
        if not pr:
            continue
        r1_enough = True if mr == 1 else analyze(lv, 1) is not None
        if difficulty_ok(level, pr, mr, r1_enough):
            lv["attempts"] = a + 1
            lv["energy"] = pr.pop("energy")
            lv["proof"] = pr
            lv["sha256"] = level_hash(lv)
            return lv
    raise RuntimeError(f"gagal membuat level {level}")


def build_dataset(log=print):
    levels = []
    for L in range(1, N_LEVELS + 1):
        lv = build_level(L)
        log(f"  Level {L:>2}: {lv['n']}x{lv['n']}  trap={len(lv['trap']):>2}  kristal={len(lv['crystals'])}  "
            f"seed={lv['seed']}  percobaan={lv['attempts']}  deduksi={lv['proof']['deductions']}  "
            f"max_rule=R{lv['proof']['max_rule']}  energi={lv['energy']}")
        levels.append(lv)
    meta = dict(
        name="Maze Mission: Deep Logic — Level Dataset (Open Logic Puzzle)", version=2, mode="open",
        levels=N_LEVELS, base_seed=BASE_SEED,
        trap_rule="Level k memiliki 2+k trap (3, 4, 5, ... 12)", wall_probability=WALL_P,
        guarantee="Semua angka petunjuk terlihat sejak awal. Setiap level terbukti solvable oleh solver logika "
                  "tanpa satu pun tebakan (guesses=0). Semua level cukup aturan R1 (mode mudah).",
        dataset_sha256=hashlib.sha256("".join(l["sha256"] for l in levels).encode()).hexdigest())
    return dict(meta=meta, levels=levels)


# ---------------------------------------------------------------- ekspor
def cell_type(lv, k):
    if k == lv["start"]:
        return "start"
    if k == lv["gate"]:
        return "gate"
    if k == lv["key"]:
        return "key"
    if k in lv["crystals"]:
        return "crystal"
    if k in lv["trap"]:
        return "trap"
    if k in lv["wall"]:
        return "wall"
    return "empty"


def export(ds):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(ds, f, ensure_ascii=False, indent=1)
    with open(os.path.join(DATA_DIR, "levels.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["level", "size", "traps", "walls", "crystals", "keys", "energy_max", "seed", "deductions",
                    "rule1_basic", "rule2_subset", "rule3_enumeration", "max_rule", "guesses_needed",
                    "solver_sound", "plan_cost_key_gate", "plan_cost_all", "sha256"])
        for lv in ds["levels"]:
            p = lv["proof"]
            w.writerow([lv["id"], f"{lv['n']}x{lv['n']}", len(lv["trap"]), len(lv["wall"]), len(lv["crystals"]), 1,
                        lv["energy"], lv["seed"], p["deductions"], p["rule1"], p["rule2"], p["rule3"], p["max_rule"],
                        p["guesses"], p["sound"], p["plan_cost_min"], p["plan_cost_full"], lv["sha256"]])
    with open(os.path.join(DATA_DIR, "cells.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["level", "row", "col", "cell_type", "adjacent_traps"])
        for lv in ds["levels"]:
            n = lv["n"]
            for k in range(n * n):
                w.writerow([lv["id"], k // n, k % n, cell_type(lv, k), clue_of(lv, k)])
    with open(os.path.join(DATA_DIR, "proof_steps.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["level", "step", "rule", "row", "col", "conclusion", "based_on_clue_cells(row;col)"])
        for lv in ds["levels"]:
            n = lv["n"]
            for s in lv["proof"]["steps"]:
                w.writerow([lv["id"], s["i"], f"R{s['rule']}", s["cell"] // n, s["cell"] % n, s["verdict"],
                            " ".join(f"{b // n};{b % n}" for b in s["basis"])])
    with open(os.path.join(DATA_DIR, "README.md"), "w", encoding="utf-8") as f:
        f.write(report_md(ds))


def report_md(ds):
    m = ds["meta"]
    rows = "\n".join(
        f"| {l['id']} | {l['n']}×{l['n']} | {len(l['trap'])} | {len(l['wall'])} | {len(l['crystals'])} | 1 | "
        f"{l['energy']} | {l['proof']['deductions']} (R1:{l['proof']['rule1']} R2:{l['proof']['rule2']} "
        f"R3:{l['proof']['rule3']}) | **{l['proof']['guesses']}** | `{l['sha256'][:12]}…` |" for l in ds["levels"])
    return f"""# Dataset Maze Mission: Deep Logic — Bukti Game Bebas Tebakan

{m['guarantee']}

* Jumlah level : **{m['levels']}**
* Aturan trap  : {m['trap_rule']}
* Seed dasar   : `{m['base_seed']}` (generator deterministik → hasil selalu sama)
* Hash dataset : `{m['dataset_sha256']}`

| Level | Papan | Trap | Dinding | Kristal 💎 | Kunci 🔑 | Energi maks | Deduksi solver | Tebakan | SHA-256 |
|---|---|---|---|---|---|---|---|---|---|
{rows}

## Isi folder `dataset/`
| File | Isi |
|---|---|
| `levels.json` | Data lengkap tiap level (posisi dinding, trap, kunci, kristal, gerbang) + bukti solver + rute solusi |
| `levels.csv` | Ringkasan 1 baris per level |
| `cells.csv` | Dataset per-sel: level, baris, kolom, tipe sel, angka petunjuk (jumlah trap di 8 tetangga) |
| `proof_steps.csv` | Setiap langkah deduksi (aturan R1/R2/R3, sel, kesimpulan aman/trap, sel angka yang jadi dasar) |

## Cara pembuktian
1. **Generator** membuat papan dengan seed tetap, jumlah trap persis `2 + level`.
2. **Solver logika** memainkan papan itu seperti pemain yang hanya boleh bernalar (semua angka sudah terlihat):
   * **R1** — angka = 0 ⇒ semua tetangga aman; angka = jumlah sel tertutup ⇒ semuanya trap.
   * **R2** — dua angka yang sel tertutupnya saling mencakup ⇒ selisihnya bisa disimpulkan.
   * **R3** — enumerasi semua konfigurasi trap yang konsisten dengan seluruh angka; sel yang aman/trap di *semua* konfigurasi dipastikan.
3. Solver hanya melangkah ke sel yang **sudah terbukti aman**; trap terbukti yang menghalangi jalan dijinakkan dulu.
   Bila suatu saat tidak ada langkah terbukti, level **ditolak** dan diganti seed berikutnya.
4. Setiap kesimpulan dicocokkan dengan posisi trap sebenarnya (*soundness check*): semua harus benar.
5. `python maze_dataset.py verify` mengulang seluruh pembuktian dari nol dan membandingkan hash.

**Mode Open Logic Puzzle**: semua angka petunjuk terlihat sejak awal, jadi solver memakai seluruh angka itu dari langkah pertama.
Mode mudah: **semua level** cukup aturan R1 (angka vs sisa sel), dengan jumlah Trap sedikit (3 → 12).
Level tidak bisa dipilih bebas: pemain harus menyelesaikan Level 1 lebih dulu, lalu Level 2, dan seterusnya.
"""


# ---------------------------------------------------------------- muat & verifikasi
def load_or_build(log=print):
    if os.path.exists(JSON_PATH):
        with open(JSON_PATH, encoding="utf-8") as f:
            return json.load(f)
    log("Dataset belum ada — membangun dataset (sekali saja, ±beberapa detik)...")
    ds = build_dataset(log)
    export(ds)
    return ds


def verify(ds, log=print):
    ok_all, m = True, ds["meta"]
    log(f"Verifikasi dataset  ({m['levels']} level, seed dasar {m['base_seed']})")
    log(f"{'Lv':>3} {'papan':>6} {'trap':>5} {'kunci':>5} {'kristal':>7} {'hash':>5} {'solver':>7} {'tebakan':>8} {'sound':>6}")
    if len(ds["levels"]) < 8 or m.get("mode") != "open":
        ok_all = False
        log("  (dataset bukan mode 'open' — jalankan: python maze_dataset.py generate)")
    for lv in ds["levels"]:
        L, n = lv["id"], lv["n"]
        wall, trap, cry = set(lv["wall"]), set(lv["trap"]), set(lv["crystals"])
        zone = start_zone(n)
        checks = dict(
            trap=len(trap) == trap_count(L),
            struct=(not (wall & trap) and lv["key"] not in trap | wall and not (cry & (trap | wall)) and
                    lv["key"] not in cry and lv["gate"] not in trap | wall | cry and not (zone & (trap | wall))),
            hash=level_hash(lv) == lv["sha256"])
        res = analyze(lv, MAX_RULE_BY_LEVEL[L - 1])
        solver = bool(res) and res["guesses"] == 0
        sound = bool(res) and res["sound"]
        same = bool(res) and res["deductions"] == lv["proof"]["deductions"] and res["energy"] == lv["energy"]
        ok = all(checks.values()) and solver and sound and same
        ok_all &= ok
        log(f"{L:>3} {n:>2}x{n:<3} {len(trap):>5} {1:>5} {len(cry):>7} {'OK' if checks['hash'] else 'GAGAL':>5} "
            f"{'OK' if solver else 'GAGAL':>7} {0 if solver else '-':>8} {'OK' if sound else 'GAGAL':>6}"
            + ("" if ok else "   <-- " + ",".join(k for k, v in checks.items() if not v)))
    got = hashlib.sha256("".join(l["sha256"] for l in ds["levels"]).encode()).hexdigest()
    ok_all &= got == m["dataset_sha256"]
    log("HASIL: " + ("SEMUA LEVEL TERVERIFIKASI — 0 tebakan." if ok_all else "ADA YANG GAGAL!"))
    return ok_all


def public_summary(ds):
    """Ringkasan aman untuk browser: TANPA posisi trap/kunci (supaya tidak jadi contekan)."""
    out = []
    for lv in ds["levels"]:
        p = lv["proof"]
        out.append(dict(id=lv["id"], n=lv["n"], traps=len(lv["trap"]), walls=len(lv["wall"]),
                        crystals=len(lv["crystals"]), energy=lv["energy"], seed=lv["seed"],
                        deductions=p["deductions"], r1=p["rule1"], r2=p["rule2"], r3=p["rule3"],
                        max_rule=p["max_rule"], guesses=p["guesses"], sound=p["sound"], sha=lv["sha256"][:16]))
    return dict(meta=ds["meta"], levels=out)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "verify"
    if cmd == "generate":
        print("Membangun dataset...")
        ds = build_dataset()
        export(ds)
        print(f"Tersimpan di {DATA_DIR}")
        return 0 if verify(ds) else 1
    if cmd == "verify":
        return 0 if verify(load_or_build()) else 1
    if cmd == "report":
        print(report_md(load_or_build()))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
