# uinjkt-cli

CLI baca-saja untuk portal mahasiswa UIN Syarif Hidayatullah Jakarta. Dua berkas Python 3 tanpa dependensi. Proyek pribadi, tidak berafiliasi dengan UIN Jakarta atau Pustipanda.

| Berkas | Portal | Cara kerja | Status |
|---|---|---|---|
| `akademik.py` | akademik.uinjkt.ac.id | membaca tabel HTML dengan cookie sesi | teruji |
| `lms.py` | lms.uinjkt.ac.id (Moodle) | web service resmi Moodle dengan token | belum teruji ke server |

## Pakai

```
python akademik.py login      # tempel hasil document.cookie dari tab portal yang sudah login
python akademik.py krs        # jadwal kuliah
python akademik.py khs --semester "Genap 2025"
python akademik.py --help     # semua perintah
```

Perintah `akademik.py`: `status`, `krs`, `khs`, `transkrip`, `presensi`, `tagihan`, `materi`, `tugas`, `ujian`, `pengumuman`, `info`, `ews`, `unduh`. Semua menerima `--json`. `selftest` menguji parser tanpa jaringan.

## Keamanan

- Tidak pernah meminta kata sandi. Login tetap dilakukan sendiri di browser.
- Cookie/token disimpan di `~/.lms-uinjkt/`, di luar repo, dengan izin berkas dibatasi ke akun sendiri.
- Tidak ada perintah yang mengubah data (isi KRS, presensi, kumpul tugas, bayar).
- Cookie/token hanya dikirim ke host portalnya sendiri.

## Batas

Daftar hanya halaman pertama. Kalau tata letak portal berubah, parser `akademik.py` perlu disesuaikan.
