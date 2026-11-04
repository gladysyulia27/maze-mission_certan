#!/usr/bin/env python3
"""
BENCHMARK & DATASET RUNNER — MAZE MISSION: DEEP LOGIC
Mendukung:
  1. Pembacaan dataset labirin dari file .txt (easy, medium, hard, stuck)
  2. Contoh input manual (string grid / interaktif CLI)
  3. Pengujian otomatis dengan agen logika + BFS (shortest path) & pencatatan hasil uji
     (jumlah langkah, skor akhir, sisa nyawa, sisa energi, status menang/kalah/stuck)
"""
import os
import sys
from collections import deque
from maze_mission_deep_logic import Game, S_CRYSTAL, S_GOAL, S_DISARM, S_TRAP, S_BAD_DISARM


def load_maze_from_text(text: str) -> Game:
    """Membuat instance Game dari teks/string representasi grid labirin."""
    lines = [line.strip() for line in text.strip().splitlines() if line.strip() and not line.strip().startswith("//")]
    energy_override = None
    grid_lines = []
    for line in lines:
        if line.upper().startswith("ENERGY="):
            energy_override = int(line.split("=", 1)[1].strip())
        elif line.startswith("#") and len(line) > 2 and line[1] == " " and any(c.isalpha() and c.islower() for c in line):
            # Komentar jika diawali '# ' dan mengandung huruf kecil
            continue
        else:
            tokens = line.split() if " " in line else list(line)
            grid_lines.append(tokens)

    n = len(grid_lines)
    if n == 0 or any(len(row) != n for row in grid_lines):
        raise ValueError(f"Grid harus berukuran N x N (ditemukan {n} baris).")

    wall, trap, cry = set(), set(), set()
    start_pos = (0, 0)
    goal_idx = n * n - 1

    for r in range(n):
        for c in range(n):
            ch = grid_lines[r][c].upper()
            idx = r * n + c
            if ch == "S":
                start_pos = (r, c)
            elif ch == "G":
                goal_idx = idx
            elif ch == "#":
                wall.add(idx)
            elif ch == "T":
                trap.add(idx)
            elif ch == "C":
                cry.add(idx)

    # Buat objek Game tanpa memanggil generator random
    g = object.__new__(Game)
    g.n = n
    g.goal = goal_idx
    g.wall = wall
    g.trap = trap
    g.cry = set(cry)
    g.ncry = len(cry)
    g.hp = 3
    g.got = 0
    g.sonar = 2
    g.score = 0
    g.en = g.max = energy_override if energy_override is not None else n * n
    g.pos = start_pos
    start_idx = start_pos[0] * n + start_pos[1]
    g.vis = {start_idx}
    g.safe = set()
    g.clr = set()
    g.son = {}
    g.status = "run"
    g.why = ""
    g.refresh()
    return g


def load_maze_from_file(filepath: str) -> Game:
    """Membaca dataset labirin dari file .txt."""
    with open(filepath, "r", encoding="utf-8") as f:
        return load_maze_from_text(f.read())


def check_dfs_reachability(g: Game):
    """Mengecek apakah semua kristal dan goal terjangkau lewat jalur aman (DFS)."""
    n = g.n
    start = g.pos[0] * n + g.pos[1]
    seen, st = {start}, [start]
    while st:
        r, c = divmod(st.pop(), n)
        for a, b in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if 0 <= a < n and 0 <= b < n:
                j = a * n + b
                if j not in seen and j not in g.wall and j not in g.trap:
                    seen.add(j)
                    st.append(j)
    reachable_crystals = sum(1 for k in g.cry if k in seen)
    goal_reachable = g.goal in seen
    return reachable_crystals == g.ncry and goal_reachable, reachable_crystals, goal_reachable


def bfs_shortest_path(g: Game, start_idx: int, targets: set, passable: set):
    """
    Mencari jalur terpendek (BFS) dari start_idx ke salah satu sel di `targets`
    hanya melewati sel yang ada di `passable`.
    Mengembalikan list indeks sel [langkah_1, langkah_2, ..., target] atau None.
    """
    q = deque([start_idx])
    prev = {start_idx: -1}
    while q:
        curr = q.popleft()
        if curr in targets and curr != start_idx:
            path = []
            k = curr
            while k != start_idx:
                path.append(k)
                k = prev[k]
            path.reverse()
            return path
        r, c = divmod(curr, g.n)
        for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if 0 <= nr < g.n and 0 <= nc < g.n:
                nxt = nr * g.n + nc
                if nxt not in prev and nxt in passable:
                    prev[nxt] = curr
                    q.append(nxt)
    return None


def deduce_logic(g: Game):
    """
    Inferensi logika proposisional & subset constraint (CSP) dari angka clue:
    - Aturan Dasar 1: rem == 0 -> semua unknown adalah SAFE
    - Aturan Dasar 2: rem == len(unknowns) -> semua unknown adalah TRAP
    - Aturan Subset: jika U1 subset dari U2 dan rem1 == rem2 -> (U2 - U1) pasti SAFE;
      jika len(U2 - U1) == rem2 - rem1 -> (U2 - U1) pasti TRAP.
    """
    n = g.n
    known_traps = {k for k, v in g.son.items() if v == "T"}
    known_safe = set(g.vis) | set(g.safe) | set(g.clr) | {k for k, v in g.son.items() if v == "S"}

    changed = True
    while changed:
        changed = False
        constraints = []
        for k in list(g.vis):
            r, c = divmod(k, n)
            active_clue = g.clue(r, c)
            unknowns = set()
            flagged_traps = 0
            for nr, nc in g.nb8(r, c):
                nk = nr * n + nc
                if nk in g.wall or nk in g.clr:
                    continue
                if nk in known_traps:
                    flagged_traps += 1
                elif nk not in known_safe:
                    unknowns.add(nk)
            rem = active_clue - flagged_traps
            if unknowns:
                if rem == 0:
                    for u in unknowns:
                        known_safe.add(u)
                        g.safe.add(u)
                        changed = True
                elif rem == len(unknowns):
                    for u in unknowns:
                        known_traps.add(u)
                        changed = True
                else:
                    constraints.append((unknowns, rem))

        # Subset elimination antar pasangan constraint
        for i in range(len(constraints)):
            u1, r1 = constraints[i]
            for j in range(len(constraints)):
                if i == j:
                    continue
                u2, r2 = constraints[j]
                if u1 and u1.issubset(u2) and u1 != u2:
                    diff = u2 - u1
                    dr = r2 - r1
                    if dr == 0:
                        for u in diff:
                            if u not in known_safe:
                                known_safe.add(u)
                                g.safe.add(u)
                                changed = True
                    elif dr == len(diff):
                        for u in diff:
                            if u not in known_traps:
                                known_traps.add(u)
                                changed = True
    return known_safe, known_traps


def simulate_agent(g: Game, max_steps: int = 500):
    """
    Menjalankan agen otomatis berbasis Deduksi Logika + BFS (Shortest Path).
    Mengembalikan dict berisi hasil uji: langkah, skor, status (MENANG / STUCK / KALAH), dll.
    """
    n = g.n
    steps = 0
    disarms = 0
    sonars_used = 0
    trace = []

    while g.status == "run" and steps < max_steps:
        known_safe, known_traps = deduce_logic(g)
        curr_idx = g.pos[0] * n + g.pos[1]

        # 1. Tentukan target prioritas:
        #    - Jika ada kristal yang sudah diketahui lokasi pastinya di known_safe, tuju kristal terdekat (BFS)
        #    - Jika semua kristal sudah diambil dan goal ada di known_safe, langsung tuju goal (BFS)
        #    - Jika belum semua kristal ditemukan, hanya eksplorasi frontier (sel safe yang bertetangga
        #      dengan minimal satu sel unknown) agar tidak membuang energi di ruang kosong
        safe_crystals = {c for c in g.cry if c in known_safe}
        frontier_safe = set()
        for k in known_safe:
            if k not in g.vis:
                r, c = divmod(k, n)
                has_unknown_nb = any(
                    (nr * n + nc) not in g.wall
                    and (nr * n + nc) not in known_safe
                    and (nr * n + nc) not in known_traps
                    for nr, nc in g.nb8(r, c)
                )
                if has_unknown_nb:
                    frontier_safe.add(k)
        unvisited_safe = frontier_safe or {k for k in known_safe if k not in g.vis}

        target_path = None
        if safe_crystals:
            target_path = bfs_shortest_path(g, curr_idx, safe_crystals, known_safe)
        if not target_path and g.got == g.ncry and g.goal in known_safe:
            target_path = bfs_shortest_path(g, curr_idx, {g.goal}, known_safe)
        if not target_path and unvisited_safe:
            target_path = bfs_shortest_path(g, curr_idx, unvisited_safe, known_safe)

        if target_path:
            nxt = target_path[0]
            nr, nc = divmod(nxt, n)
            g.move(nr, nc)
            steps += 1
            trace.append(f"Move({nr},{nc})")
            continue

        # 2. Jika tidak ada sel safe baru yang bisa dijangkau, coba Disarm trap yang sudah terdeduksi di sebelah kita
        adj_traps = []
        for nr, nc in ((g.pos[0] - 1, g.pos[1]), (g.pos[0] + 1, g.pos[1]),
                       (g.pos[0], g.pos[1] - 1), (g.pos[0], g.pos[1] + 1)):
            if 0 <= nr < n and 0 <= nc < n:
                nk = nr * n + nc
                if nk in known_traps and nk not in g.clr:
                    adj_traps.append(nk)

        if not adj_traps and known_traps:
            # Cari jalur BFS ke tetangga dari known_trap agar bisa di-disarm
            trap_neighbors = set()
            for tk in known_traps:
                if tk in g.clr:
                    continue
                tr, tc = divmod(tk, n)
                for nr, nc in ((tr - 1, tc), (tr + 1, tc), (tr, tc - 1), (tr, tc + 1)):
                    if 0 <= nr < n and 0 <= nc < n and (nr * n + nc) in known_safe:
                        trap_neighbors.add(nr * n + nc)
            path_to_trap_nb = bfs_shortest_path(g, curr_idx, trap_neighbors, known_safe)
            if path_to_trap_nb:
                nxt = path_to_trap_nb[0]
                nr, nc = divmod(nxt, n)
                g.move(nr, nc)
                steps += 1
                trace.append(f"Move({nr},{nc})")
                continue

        if adj_traps:
            tk = adj_traps[0]
            tr, tc = divmod(tk, n)
            g.disarm(tr, tc)
            disarms += 1
            trace.append(f"Disarm({tr},{tc})")
            continue

        # 3. Jika masih buntu dan Sonar masih tersedia, gunakan Sonar pada sel unknown yang bersebelahan (4-arah) dengan area vis
        if g.sonar > 0:
            adj_unknowns = []
            other_unknowns = []
            pr, pc = g.pos
            for r in range(max(0, pr - 2), min(n, pr + 3)):
                for c in range(max(0, pc - 2), min(n, pc + 3)):
                    k = r * n + c
                    if k not in g.wall and k not in known_safe and k not in known_traps and k not in g.son:
                        is_adj = any(
                            0 <= r + dr < n and 0 <= c + dc < n and ((r + dr) * n + (c + dc)) in known_safe
                            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
                        )
                        if is_adj:
                            adj_unknowns.append((r, c))
                        else:
                            other_unknowns.append((r, c))
            candidates = adj_unknowns or other_unknowns
            if candidates:
                sr, sc = candidates[0]
                g.sonar_scan(sr, sc)
                sonars_used += 1
                trace.append(f"Sonar({sr},{sc})")
                continue

        # 4. Tidak ada langkah aman maupun informasi baru -> Agen STUCK
        break

    if g.status == "win":
        outcome = "MENANG"
    elif g.status == "lose":
        outcome = f"KALAH ({g.why})"
    else:
        outcome = "STUCK (Jalur tertutup Wall/Trap)"

    return {
        "size": f"{n}x{n}",
        "steps": steps,
        "disarms": disarms,
        "sonars": sonars_used,
        "crystals": f"{g.got}/{g.ncry}",
        "hp_left": g.hp,
        "energy_left": f"{g.en}/{g.max}",
        "score": g.score,
        "outcome": outcome,
        "trace": trace,
    }


# =====================================================================
# CONTOH INPUT MANUAL (STRING)
# =====================================================================
MANUAL_INPUT_EXAMPLE = """
# Contoh Input Manual Labirin 7x7
ENERGY=49
S . . # . . .
. . . # . C .
. T . . . # .
. . # . . . .
C . # . T . .
. . . . # . .
. . T . # . G
"""


def run_all_tests():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dataset_dir = os.path.join(base_dir, "datasets")

    datasets = [
        ("Easy (datasets/easy.txt)", os.path.join(dataset_dir, "easy.txt"), "file"),
        ("Medium (datasets/medium.txt)", os.path.join(dataset_dir, "medium.txt"), "file"),
        ("Hard (datasets/hard.txt)", os.path.join(dataset_dir, "hard.txt"), "file"),
        ("Stuck (datasets/stuck.txt)", os.path.join(dataset_dir, "stuck.txt"), "file"),
        ("Manual Input (String Grid)", MANUAL_INPUT_EXAMPLE, "manual"),
    ]

    results = []
    report_lines = []
    header = (
        "=" * 95 + "\n"
        + "LAPORAN HASIL UJI DATASET LABIRIN - MAZE MISSION: DEEP LOGIC\n"
        + "=" * 95
    )
    print(header)
    report_lines.append(header)

    for name, src, mode in datasets:
        g = load_maze_from_file(src) if mode == "file" else load_maze_from_text(src)
        dfs_ok, reach_cry, reach_goal = check_dfs_reachability(g)
        res = simulate_agent(g)
        res["name"] = name
        res["dfs_valid"] = "Valid (Reachable)" if dfs_ok else f"Tidak Valid (Kristal:{reach_cry}/{g.ncry}, Goal:{reach_goal})"
        results.append(res)

        block = (
            f"\n[{name}]\n"
            f"  - Ukuran Grid      : {res['size']}\n"
            f"  - Validasi DFS     : {res['dfs_valid']}\n"
            f"  - Jumlah Langkah   : {res['steps']} langkah (Disarm: {res['disarms']}, Sonar: {res['sonars']})\n"
            f"  - Kristal Terambil : {res['crystals']}\n"
            f"  - Sisa Nyawa / En  : HP {res['hp_left']} | Energi {res['energy_left']}\n"
            f"  - Skor Akhir       : {res['score']}\n"
            f"  - Status Akhir     : {res['outcome']}\n"
            f"  - Jejak Aksi       : {' -> '.join(res['trace'][:10])}"
            + (f" ... (+{len(res['trace']) - 10} aksi lainnya)" if len(res["trace"]) > 10 else "")
        )
        print(block)
        report_lines.append(block)

    # Tabel Ringkasan
    table_header = (
        "\n" + "=" * 95 + "\n"
        f"{'Dataset':<30} | {'Grid':<6} | {'Langkah':<7} | {'Kristal':<7} | {'Sisa En':<8} | {'Skor':<6} | {'Status Akhir'}\n"
        + "-" * 95
    )
    print(table_header)
    report_lines.append(table_header)

    for r in results:
        row = f"{r['name']:<30} | {r['size']:<6} | {r['steps']:<7} | {r['crystals']:<7} | {r['energy_left']:<8} | {r['score']:<6} | {r['outcome']}"
        print(row)
        report_lines.append(row)

    footer = "=" * 95 + "\n"
    print(footer)
    report_lines.append(footer)

    # Simpan hasil uji ke file hasil_uji.txt
    out_path = os.path.join(base_dir, "hasil_uji.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"Catatan hasil uji telah disimpan ke: {out_path}")


if __name__ == "__main__":
    run_all_tests()
