#!/usr/bin/env python3
"""CLI baca-saja untuk LMS UIN Jakarta (lms.uinjkt.ac.id, Moodle 5.0).

Memakai web service resmi Moodle (layanan aplikasi mobile). Tidak ada perintah
yang mengubah data di portal. Token disimpan di ~/.lms-uinjkt/token, bukan di sini.
"""
import argparse, base64, datetime, getpass, html, json, os, re, subprocess, sys
import urllib.error, urllib.parse, urllib.request

BASE = "https://lms.uinjkt.ac.id"
TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".lms-uinjkt", "token")
LOGIN_URL = (BASE + "/admin/tool/mobile/launch.php?service=moodle_mobile_app"
             "&passport=1&urlscheme=moodlemobile&confirmed=1")
RELOGIN = "Token tidak ada atau kedaluwarsa. Login ulang: python lms.py login"


def parse_token(s):
    """Terima tautan moodlemobile://token=..., base64-nya saja, atau token mentah."""
    s = s.strip().strip('"')
    if "token=" in s:
        s = s.split("token=", 1)[1]
    if re.fullmatch(r"[0-9a-f]{32}", s):
        return s
    try:
        parts = base64.b64decode(s + "=" * (-len(s) % 4)).decode().split(":::")
    except Exception:
        parts = []
    if len(parts) >= 2 and re.fullmatch(r"[0-9a-f]{32}", parts[1]):
        return parts[1]
    sys.exit("Itu bukan tautan token. Yang disalin harus berawalan moodlemobile://token=")


def flat(key, v, out):
    """Moodle REST minta parameter bersarang dalam bentuk a[0][b]=..."""
    if isinstance(v, dict):
        for k, x in v.items():
            flat(f"{key}[{k}]", x, out)
    elif isinstance(v, (list, tuple)):
        for i, x in enumerate(v):
            flat(f"{key}[{i}]", x, out)
    else:
        out[key] = int(v) if isinstance(v, bool) else v


def read_token():
    try:
        with open(TOKEN_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        sys.exit(RELOGIN)


def call(fn, **params):
    data = {"wstoken": read_token(), "wsfunction": fn, "moodlewsrestformat": "json"}
    for k, v in params.items():
        flat(k, v, data)
    body = urllib.parse.urlencode(data).encode()
    with urllib.request.urlopen(BASE + "/webservice/rest/server.php", body, timeout=60) as r:
        res = json.load(r)
    if isinstance(res, dict) and res.get("exception"):
        if res.get("errorcode") == "invalidtoken":
            sys.exit(RELOGIN)
        sys.exit(f"Moodle menolak {fn}: {res.get('errorcode')}: {res.get('message')}")
    return res


def text(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h or ""))).strip()


def ts(t):
    return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else None


def userid():
    return call("core_webservice_get_site_info")["userid"]


# --- perintah (semuanya hanya membaca) ---

def cmd_login(a):
    print("1. Buka tautan ini di browser yang sudah login ke LMS:\n   " + LOGIN_URL)
    print("2. Kalau muncul dialog 'buka aplikasi', batalkan.")
    print("3. Klik kanan tautan 'launch the app' di halaman itu > Copy link address.")
    tok = parse_token(getpass.getpass("4. Tempel di sini (tidak ditampilkan), lalu Enter: "))
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    open(TOKEN_FILE, "w").close()
    if os.name == "nt":  # batasi ke akun ini saja sebelum token ditulis
        subprocess.run(["icacls", TOKEN_FILE, "/inheritance:r", "/grant:r",
                        f"{getpass.getuser()}:F"], capture_output=True)
    else:
        os.chmod(TOKEN_FILE, 0o600)
    with open(TOKEN_FILE, "w") as f:
        f.write(tok)
    return [{"status": "login ok", "nama": call("core_webservice_get_site_info")["fullname"]}]


def cmd_courses(a):
    return [{"id": c["id"], "kode": c["shortname"], "nama": c["fullname"],
             "progres": c.get("progress")}
            for c in call("core_enrol_get_users_courses", userid=userid())]


def cmd_tugas(a):
    p = {"courseids": [a.course]} if a.course else {}
    rows = [{"matkul": c["shortname"], "tugas": x["name"], "tenggat": ts(x["duedate"]),
             "url": f"{BASE}/mod/assign/view.php?id={x['cmid']}", "deskripsi": text(x.get("intro"))}
            for c in call("mod_assign_get_assignments", **p)["courses"] for x in c["assignments"]]
    return sorted(rows, key=lambda r: r["tenggat"] or "9")


def cmd_tenggat(a):
    now = int(datetime.datetime.now().timestamp())
    ev = call("core_calendar_get_action_events_by_timerange", timesortfrom=now,
              timesortto=now + a.hari * 86400, limitnum=50)["events"]
    return [{"matkul": (e.get("course") or {}).get("shortname"), "jenis": e.get("modulename"),
             "nama": e["name"], "tenggat": ts(e["timesort"]), "url": e.get("url")} for e in ev]


def cmd_materi(a):
    return [{"bagian": s["name"], "jenis": m["modname"], "nama": m["name"], "url": m.get("url"),
             "berkas": [f["fileurl"] for f in m.get("contents", []) if f.get("fileurl")]}
            for s in call("core_course_get_contents", courseid=a.course) for m in s["modules"]]


def cmd_pengumuman(a):
    p = {"courseids": [a.course]} if a.course else {}
    rows = []
    for f in call("mod_forum_get_forums_by_courses", **p):
        if f["type"] != "news":
            continue
        for d in call("mod_forum_get_forum_discussions", forumid=f["id"])["discussions"]:
            rows.append({"courseid": f["course"], "judul": d["name"], "oleh": d["userfullname"],
                         "waktu": ts(d["timemodified"]), "isi": text(d["message"])})
    return sorted(rows, key=lambda r: r["waktu"] or "", reverse=True)


def cmd_nilai(a):
    if not a.course:
        return [{"courseid": g["courseid"], "nilai": g["grade"]}
                for g in call("gradereport_overview_get_course_grades")["grades"]]
    ug = call("gradereport_user_get_grade_items", courseid=a.course, userid=userid())["usergrades"]
    return [{"item": i.get("itemname") or i.get("itemtype"), "nilai": i.get("gradeformatted"),
             "maks": i.get("grademax"), "umpan_balik": text(i.get("feedback"))}
            for u in ug for i in u["gradeitems"]]


def cmd_unduh(a):
    if not a.url.startswith(BASE + "/"):  # token tidak boleh terkirim ke host lain
        sys.exit("URL harus dari " + BASE)
    url = a.url + ("&" if "?" in a.url else "?") + "token=" + read_token()
    name = os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(a.url).path)) or "berkas"
    dest = os.path.join(a.out, name)
    with urllib.request.urlopen(url, timeout=120) as r:
        data = r.read()
    if data[:13] == b'{"error":"Inv':  # pluginfile membalas JSON kalau token ditolak
        sys.exit(RELOGIN)
    with open(dest, "wb") as f:
        f.write(data)
    return [{"tersimpan": os.path.abspath(dest), "byte": len(data)}]


def cmd_selftest(a):
    tok = "0123456789abcdef" * 2
    b64 = base64.b64encode(f"sig:::{tok}:::priv".encode()).decode()
    assert parse_token("moodlemobile://token=" + b64) == tok
    assert parse_token(b64.rstrip("=")) == tok and parse_token(f' "{tok}"\n') == tok
    out = {}
    flat("courseids", [5, 7], out)
    flat("o", {"a": True}, out)
    assert out == {"courseids[0]": 5, "courseids[1]": 7, "o[a]": 1}, out
    assert text("<p>Halo&nbsp;<b>dunia</b></p>\n") == "Halo dunia" and text(None) == ""
    assert ts(0) is None and len(ts(1700000000)) == 16
    return [{"selftest": "ok"}]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="keluaran JSON")
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help):
        p = sub.add_parser(name, parents=[common], help=help)
        p.set_defaults(fn=fn)
        return p

    add("login", cmd_login, "simpan token (dijalankan pengguna sendiri)")
    add("courses", cmd_courses, "daftar mata kuliah")
    add("tugas", cmd_tugas, "tugas (assignment) dan tenggatnya").add_argument("--course", type=int)
    add("tenggat", cmd_tenggat, "semua aktivitas bertenggat ke depan").add_argument("--hari", type=int, default=14)
    add("materi", cmd_materi, "isi/berkas satu mata kuliah").add_argument("course", type=int)
    add("pengumuman", cmd_pengumuman, "pengumuman dosen").add_argument("course", type=int, nargs="?")
    add("nilai", cmd_nilai, "nilai (tanpa id: ringkasan semua)").add_argument("course", type=int, nargs="?")
    p = add("unduh", cmd_unduh, "unduh satu berkas dari URL keluaran `materi`")
    p.add_argument("url")
    p.add_argument("-o", "--out", default=".")
    add("selftest", cmd_selftest, "uji parser tanpa jaringan")

    a = ap.parse_args()
    try:
        rows = a.fn(a)
    except urllib.error.URLError as e:
        sys.exit(f"Tidak bisa menghubungi {BASE}: {e}")
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        for r in rows:
            print(" | ".join(f"{k}: {v}" for k, v in r.items() if v not in (None, "", [])))
        if not rows:
            print("(kosong)")


if __name__ == "__main__":
    main()
