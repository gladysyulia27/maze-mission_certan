# Maze Mission: Deep Logic v5 — Open Logic Puzzle

## Menjalankan
    python maze_mission_deep_logic.py
Browser terbuka otomatis dan game langsung aktif.

## Yang berubah di v5
| Perubahan | Penjelasan |
|---|---|
| **Open Logic Puzzle** | Semua angka petunjuk (jumlah Trap di 8 sel sekitar) terlihat di papan sejak detik pertama, termasuk di sel yang belum diinjak. Sel Trap juga punya angka, jadi tidak ada petunjuk "angka hilang". |
| **Level berurutan** | Pemilih level dihapus. Mulai dari Level 1; Level berikutnya terbuka hanya setelah level sebelumnya dimenangkan. Dijaga di server (`/api/new` menolak lompatan level), bukan hanya di tampilan. |
| **Dataset dibangun ulang** | Karena informasi pemain bertambah, kesulitan level dihitung ulang dengan model baru. Mode mudah: semua level cukup aturan R1, Trap 3 sampai 12. |

## Struktur
| Berkas | Fungsi |
|---|---|
| `maze_mission_deep_logic.py` | Server + engine game (membaca level dari dataset) |
| `maze_dataset.py` | Generator dataset, solver logika, verifier |
| `web/index.html` | Tampilan game |
| `dataset/` | Dataset bukti: levels.json, levels.csv, cells.csv, proof_steps.csv, README.md |

## Bukti game bebas tebakan
    python maze_dataset.py verify      # ulangi pembuktian semua level (hasil: 0 tebakan)
    python maze_dataset.py generate    # bangun ulang dataset (seed tetap -> hasil sama)
Di dalam game, tombol **Dataset** menampilkan tabel bukti tiap level.

## Catatan
* Menutup atau memuat ulang halaman memulai lagi dari Level 1 (progres level tidak disimpan).
* Dataset v4 (angka hanya muncul setelah sel diinjak) tidak kompatibel dengan v5; folder `dataset/` di zip ini sudah versi v5.
