# Dataset Maze Mission: Deep Logic — Bukti Game Bebas Tebakan

Semua angka petunjuk terlihat sejak awal. Setiap level terbukti solvable oleh solver logika tanpa satu pun tebakan (guesses=0). Semua level cukup aturan R1 (mode mudah).

* Jumlah level : **10**
* Aturan trap  : Level k memiliki 2+k trap (3, 4, 5, ... 12)
* Seed dasar   : `20261104` (generator deterministik → hasil selalu sama)
* Hash dataset : `5dec5baf0006651650ca2857b23b19f4352b4628a312ea1f9f08afb3bae0957c`

| Level | Papan | Trap | Dinding | Kristal 💎 | Kunci 🔑 | Energi maks | Deduksi solver | Tebakan | SHA-256 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 7×7 | 3 | 2 | 2 | 1 | 25 | 5 (R1:5 R2:0 R3:0) | **0** | `fa188260a5bf…` |
| 2 | 7×7 | 4 | 4 | 2 | 1 | 35 | 6 (R1:6 R2:0 R3:0) | **0** | `dbd21644d718…` |
| 3 | 8×8 | 5 | 4 | 3 | 1 | 29 | 8 (R1:8 R2:0 R3:0) | **0** | `5ff94b8c90fc…` |
| 4 | 8×8 | 6 | 8 | 3 | 1 | 34 | 8 (R1:8 R2:0 R3:0) | **0** | `87cab2293b43…` |
| 5 | 9×9 | 7 | 7 | 4 | 1 | 53 | 10 (R1:10 R2:0 R3:0) | **0** | `5adacd234991…` |
| 6 | 9×9 | 8 | 4 | 4 | 1 | 44 | 10 (R1:10 R2:0 R3:0) | **0** | `a346fc1d20a6…` |
| 7 | 10×10 | 9 | 9 | 5 | 1 | 65 | 11 (R1:11 R2:0 R3:0) | **0** | `30702b7f3699…` |
| 8 | 10×10 | 10 | 6 | 5 | 1 | 65 | 15 (R1:15 R2:0 R3:0) | **0** | `993458122691…` |
| 9 | 11×11 | 11 | 18 | 6 | 1 | 77 | 15 (R1:15 R2:0 R3:0) | **0** | `25fa8c4aca98…` |
| 10 | 11×11 | 12 | 12 | 6 | 1 | 55 | 23 (R1:23 R2:0 R3:0) | **0** | `e325e699962d…` |

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
