#!/usr/bin/env python3
"""CLI baca-saja untuk Portal Akademik UIN Jakarta (akademik.uinjkt.ac.id).

Portal ini tidak punya API: halamannya HTML biasa, jadi CLI ini membaca tabelnya.
Masuk memakai cookie sesi (PHPSESSID) yang disimpan di ~/.lms-uinjkt/akademik-cookie.
Tidak ada perintah yang mengubah data (KRS, presensi, kumpul tugas, bayar).
"""
import argparse, getpass, json, os, re, subprocess, sys
import urllib.error, urllib.parse, urllib.request
from html.parser import HTMLParser

BASE = "https://akademik.uinjkt.ac.id"
COOKIE_FILE = os.path.join(os.path.expanduser("~"), ".lms-uinjkt", "akademik-cookie")
RELOGIN = "Sesi portal akademik tidak ada atau sudah habis. Login ulang: python akademik.py login"

# nama perintah -> (query halaman, {field form: nama argumen}, field form tetap)
PAGES = {
    "status": ("pModule=ydKhmA==&pSub=ydKhmA==&pAct=18yZqg==", {}, {}),
    "krs": ("pModule=wsaVl5yfncmQptGaoA==&pSub=wsaVl5yfncmQptGaoA==&pAct=18yZqg==", {}, {}),
    "khs": ("pModule=wsaVl5yfncmQqMqpoaal&pSub=wsaVl5yfncmQqMqpoaal&pAct=18yZqg==",
            {"lstSemester": "semester"}, {"btnLihat": "Lihat"}),
    "transkrip": ("pModule=wsaVl5yfncmQqMqpoaal&pSub=wsaVl5yfncmQqteaoKeU1qKppA==&pAct=18yZqg==", {}, {}),
    "presensi": ("pModule=xsKkpZylmdSknw==&pSub=zcynp5afn8WhqMqsl6KkzQ==&pAct=18yZqg==", {}, {}),
    "tagihan": ("pModule=1cSbnJ+TosWhm9Kbk62S1pqn&pSub=1cSbnJ+TosWhm9Kbk62S1pqn&pAct=18yZqg==",
                {"lstSemester": "semester"}, {"btnLihat": "Lihat"}),
    "materi": ("pModule=xsKhlKuXps8=&pSub=zsSomKmb&pAct=18yZqg==",
               {"semId": "semester", "klsId": "kelas"}, {"hdnSmt": "", "judul": "", "cari": "Tampilkan"}),
    "tugas": ("pModule=xsKoqJ6Tpw==&pSub=1diblKqRoceZl9iipauS&pAct=18yZqg==", {}, {}),
    "ujian": ("pModule=xsKpnaCTog==&pSub=1s2dlKWRoceZl9iipauS&pAct=18yZqg==", {}, {}),
    "pengumuman": ("pModule=xsKkmKWZqdOmo8an&pSub=0ciimqyfqdOSpA==&pAct=18yZqg==&act=z8ir", {}, {}),
    "info": ("pModule=wtGioqygl8uem9Ot&pSub=wsaVl5yfncmQl9Onoamfx56mlaKm&pAct=18yZqg==", {}, {}),
    "ews": ("pModule=xtqn&pSub=xtqn&pAct=18yZqg==", {}, {}),
}
HELP = {
    "status": "ringkasan: status akademik/bayar, dosen PA, SKS, IPK, pengumuman",
    "krs": "kartu rencana studi dan jadwal kuliah", "khs": "nilai per semester",
    "transkrip": "transkrip nilai", "presensi": "rekap kehadiran", "tagihan": "tagihan dan pembayaran",
    "materi": "materi kuliah satu kelas (tanpa --kelas: daftar kelas)", "tugas": "tugas kuliah",
    "ujian": "ujian kelas", "pengumuman": "pengumuman kelas", "info": "informasi akademik kampus",
    "ews": "status studi (EWS)",
}


def clean(s):
    return re.sub(r"\s+", " ", s).strip()


class Page(HTMLParser):
    """Kumpulkan tabel, pilihan <select>, dan teks di dalam #k-body (area isi)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.selects, self.text = [], {}, []
        self.seen_body = self.inbody = False
        self.skip = 0
        self.table = self.row = self.cell = self.sel = self.opt = None

    def end_option(self):
        if self.opt:
            self.opt[1] = clean(self.opt[1])
            self.sel.append(tuple(self.opt))
            if self.opt[2] and self.cell is not None:
                self.cell.append(self.opt[1])
        self.opt = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id") == "k-body":
            self.seen_body = self.inbody = True
        elif a.get("id") == "k-subfooter":
            self.inbody = False
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "table":
            self.table = {"cls": a.get("class") or "", "rows": []}
        elif tag == "tr" and self.table is not None:
            self.row = {"cells": [], "links": []}
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag == "a" and self.row is not None and (a.get("href") or "#")[0] not in "#j":
            self.row["links"].append(urllib.parse.urljoin(BASE + "/", a["href"]))
        elif tag == "select":
            self.sel = self.selects.setdefault(a.get("name"), [])
        elif tag == "option" and self.sel is not None:
            self.end_option()
            self.opt = [a.get("value") or "", "", "selected" in a]
        if tag in ("br", "a") and self.cell is not None:  # pisahkan teks tautan/baris yang berdempetan
            self.cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("option", "select"):
            self.end_option()
            if tag == "select":
                self.sel = None
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row["cells"].append(clean("".join(self.cell)))
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            self.table["rows"].append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None

    def handle_data(self, d):
        if self.skip:
            return
        if self.opt is not None:
            self.opt[1] += d
        elif self.cell is not None:
            self.cell.append(d)
        elif self.inbody and self.table is None and d.strip():
            self.text.append(clean(d))


def extract(p):
    """Tabel bergaris (table-stripped) -> baris data; tabel lain -> pasangan kunci/nilai."""
    info, rows = {}, []
    for t in p.tables:
        rs = [r for r in t["rows"] if r["cells"]]
        if "paging" in t["cls"] or not rs:
            continue  # shortcut: hanya halaman pertama daftar, tambah paging kalau daftar mulai terpotong
        if "table-stripped" in t["cls"]:
            head = rs[0]["cells"]
            for r in rs[1:]:
                if len(r["cells"]) < 2:  # baris "data tidak tersedia"
                    continue
                cells = r["cells"]
                while len(cells) > len(head) and not cells[0]:  # tabel materi punya sel kosong ekstra di depan
                    cells = cells[1:]
                row = dict(zip(head, cells))
                if r["links"]:
                    row["tautan"] = r["links"]
                rows.append(row)
        else:
            for r in rs:
                c = r["cells"]
                if len(c) == 1 and c[0]:
                    info.setdefault("catatan", []).append(c[0])
                for k, v in zip(c[::2], c[1::2]):
                    if k and v:
                        info[k.rstrip(" :")] = v.lstrip(": ")
    return info, rows


def choose(options, want, field):
    """Pilih nilai <option>: bawaan = yang terpilih di halaman; selain itu cocokkan id atau potongan label."""
    if not options:
        sys.exit(f"Pilihan {field} tidak ditemukan di halaman (tata letak portal mungkin berubah).")
    if want is None:
        return next((v for v, _, sel in options if sel), options[0][0])
    hit = [v for v, label, _ in options if want == v or want.lower() in label.lower()]
    if len(hit) != 1:
        sys.exit(f"'{want}' cocok dengan {len(hit)} pilihan {field}. Pilihan: "
                 + "; ".join(f"{v} = {label}" for v, label, _ in options))
    return hit[0]


def parse_cookie(s):
    s = s.strip().strip("'\"")
    m = re.search(r"PHPSESSID=([^;\s'\"]+)", s)
    v = m.group(1) if m else s
    if not re.fullmatch(r"[A-Za-z0-9,-]{10,}", v):
        sys.exit("Itu bukan cookie PHPSESSID. Salin hasil `document.cookie` dari tab portal akademik.")
    return v


def request(url, data=None):
    try:
        with open(COOKIE_FILE) as f:
            sid = f.read().strip()
    except FileNotFoundError:
        sys.exit(RELOGIN)
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, body, {"Cookie": "PHPSESSID=" + sid, "User-Agent": "lms-uinjkt-cli"})
    return urllib.request.urlopen(req, timeout=60)


def fetch(query, data=None):
    with request(BASE + "/index.php?" + query, data) as r:
        p = Page()
        p.feed(r.read().decode("utf-8", "replace"))
    if not p.seen_body:  # tanpa sesi, portal hanya membalas halaman "tidak diijinkan"
        sys.exit(RELOGIN)
    return p


def cmd_page(a):
    query, fields, fixed = PAGES[a.cmd]
    p = fetch(query)
    if fields:
        if a.cmd == "materi" and a.kelas is None:
            return {"info": {"petunjuk": "pilih kelas dengan --kelas <id atau potongan nama>"},
                    "rows": [{"id": v, "kelas": label} for v, label, _ in p.selects.get("klsId", []) if v]}
        data = dict(fixed)
        for field, arg in fields.items():
            data[field] = choose(p.selects.get(field), getattr(a, arg), field)
        p = fetch(query, data)
    info, rows = extract(p)
    # halaman tanpa tabel (status, ews) dikembalikan sebagai teks; daftar kosong tetap rows: []
    return {"info": info, "rows": rows} if p.tables and a.cmd != "status" else {"teks": p.text}


def cmd_unduh(a):
    if not a.url.startswith(BASE + "/"):  # cookie tidak boleh terkirim ke host lain
        sys.exit("URL harus dari " + BASE)
    with request(a.url) as r:
        data, ctype = r.read(), r.headers.get("Content-Type", "")
        m = re.search(r'filename="?([^";]+)', r.headers.get("Content-Disposition", ""))
    if "text/html" in ctype:
        sys.exit("Portal membalas halaman, bukan berkas. " + RELOGIN)
    dest = os.path.join(a.out, os.path.basename(m.group(1).strip()) if m else "berkas")
    with open(dest, "wb") as f:
        f.write(data)
    return {"info": {"tersimpan": os.path.abspath(dest), "byte": len(data)}}


def cmd_login(a):
    print("1. Buka https://akademik.uinjkt.ac.id di browser dan pastikan sudah login.")
    print("2. Tekan F12 > tab Console, ketik  document.cookie  lalu Enter.")
    print("3. Salin teks hasilnya (berisi PHPSESSID=...).")
    sid = parse_cookie(getpass.getpass("4. Tempel di sini (tidak ditampilkan), lalu Enter: "))
    os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)
    open(COOKIE_FILE, "w").close()
    if os.name == "nt":  # batasi ke akun ini saja sebelum cookie ditulis
        subprocess.run(["icacls", COOKIE_FILE, "/inheritance:r", "/grant:r",
                        f"{getpass.getuser()}:F"], capture_output=True)
    else:
        os.chmod(COOKIE_FILE, 0o600)
    with open(COOKIE_FILE, "w") as f:
        f.write(sid)
    fetch(PAGES["status"][0])
    return {"info": {"status": "login ok"}}


def cmd_selftest(a):
    p = Page()
    p.feed("""<table class="table"><tr><th>X</th><td>di luar</td></tr></table>
      <div id="k-body"><h4>Judul &amp; isi</h4><script>var x = "<td>";</script>
      <table class="table"><tr><th>Semester</th><td><select name="lstSemester">
        <option value="7" selected>Ganjil 2026/2027<option value="5">Genap 2025/2026</select></td></tr>
        <tr><td>Jumlah SKS</td><td>: 23</td></tr></table>
      <table class="table table-stripped"><thead><tr><th>No.</th><th>Mata Kuliah</th><th>File</th></tr></thead>
        <tr><td></td><td>1</td><td>Basis<br>Data</td><td><a href="/index.php?file=a">unduh</a><a href="#">x</a></td></tr>
        <tr><td colspan="3">Data tidak tersedia</td></tr></table>
      <table class="paging"><tr><td>Halaman : 1</td></tr></table></div>
      <div id="k-subfooter">kaki</div>""")
    info, rows = extract(p)
    assert p.seen_body and p.text == ["Judul & isi"], p.text
    assert p.selects["lstSemester"] == [("7", "Ganjil 2026/2027", True), ("5", "Genap 2025/2026", False)]
    assert info == {"X": "di luar", "Semester": "Ganjil 2026/2027", "Jumlah SKS": "23"}, info
    assert rows == [{"No.": "1", "Mata Kuliah": "Basis Data", "File": "unduh x",
                     "tautan": [BASE + "/index.php?file=a"]}], rows
    opts = p.selects["lstSemester"]
    assert choose(opts, None, "s") == "7" and choose(opts, "genap", "s") == "5" and choose(opts, "5", "s") == "5"
    assert parse_cookie("a=1; PHPSESSID=abc123def456; b=2") == "abc123def456"
    assert parse_cookie("'abc123def456'") == "abc123def456"
    return {"info": {"selftest": "ok"}}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="keluaran JSON")
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, (_, fields, _) in PAGES.items():
        sp = sub.add_parser(name, parents=[common], help=HELP[name])
        sp.set_defaults(fn=cmd_page)
        for arg in fields.values():
            sp.add_argument("--" + arg, help="id atau potongan nama, mis. \"Genap 2025\"")
    sp = sub.add_parser("unduh", parents=[common], help="unduh berkas dari kolom `tautan`")
    sp.set_defaults(fn=cmd_unduh)
    sp.add_argument("url")
    sp.add_argument("-o", "--out", default=".")
    sub.add_parser("login", parents=[common], help="simpan cookie sesi (dijalankan pengguna sendiri)").set_defaults(fn=cmd_login)
    sub.add_parser("selftest", parents=[common], help="uji parser tanpa jaringan").set_defaults(fn=cmd_selftest)

    a = ap.parse_args()
    try:
        res = a.fn(a)
    except urllib.error.URLError as e:
        sys.exit(f"Tidak bisa menghubungi {BASE}: {e}")
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return
    for k, v in res.get("info", {}).items():
        print(f"{k}: {v}")
    for r in res.get("rows", []):
        print(" | ".join(f"{k}: {v}" for k, v in r.items() if v not in (None, "", [])))
    for line in res.get("teks", []):
        print(line)
    if not any(res.values()):
        print("(kosong)")


if __name__ == "__main__":
    main()
