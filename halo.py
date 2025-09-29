#!/usr/bin/env python3
# OmniTool God Mode v4.4 — JEMBER EDITION
# Fitur baru: HTTP/2, Cuaca API Publik (ADM4 35.09.19.1006), Notif hujan ≤3 jam, Gempa khusus Jember, Diagnostics, Export CSV
import os
import sys
import time
import json
import csv
import random
import shutil
import psutil
import shlex
import httpx
from math import radians, sin, cos, asin, sqrt
from datetime import datetime, timedelta
from collections import defaultdict
from dotenv import load_dotenv

# Optional lxml (untuk XML yang kadang rusak)
try:
    from lxml import etree
    HAS_LXML = True
except Exception:
    HAS_LXML = False

# --- PATHS ---
LOG_PATH = "omnitool_logs/"
BACKUP_PATH = "backup_files/"
TRASH_PATH = "omnitool_trash/"
MUSIC_PATH = "music/"
DATA_DIR = "data"
os.makedirs(LOG_PATH, exist_ok=True)
os.makedirs(BACKUP_PATH, exist_ok=True)
os.makedirs(TRASH_PATH, exist_ok=True)
os.makedirs(MUSIC_PATH, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# --- LOGGING ---
def log_activity(activity):
    filename = f"{LOG_PATH}log_{datetime.now().strftime('%Y%m%d')}.txt"
    with open(filename, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {activity}\n")

# --- KONFIGURASI / KONST ---
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
AI_HISTORY_PATH = os.path.join(DATA_DIR, "ai_history.json")
LAST_QUAKE_FILE = os.path.join(DATA_DIR, "last_quake.txt")
NOTIFIED_RAIN_FILE = os.path.join(DATA_DIR, "notified_rain.json")

# HTTP default headers
HTTP_HEADERS = {
    "User-Agent": "OmniTool/4.4 (Termux)",
    "Accept": "application/json, text/json, application/xml, text/xml, */*",
}

# BMKG API
BMKG_PUBLIK_URL_TMPL = "https://api.bmkg.go.id/publik/prakiraan-cuaca?adm4={adm4}"  # JSON
BMKG_GEMPA_URL = "https://data.bmkg.go.id/DataMKG/TEWS/autogempa.xml"               # XML terakhir
BMKG_GEMPA_LIST_URL = "https://data.bmkg.go.id/DataMKG/TEWS/gempaterkini.xml"       # XML daftar

# Lokasi default (ADM4 Jember — dari kamu)
DEFAULT_ADM4 = "35.09.19.1006"
# Koordinat kota Jember (perkiraan)
JEMBER_COORD = (-8.172, 113.702)

# Kode cuaca BMKG ke teks
BMKG_WEATHER_MAP = {
    "0": "Cerah",
    "1": "Cerah Berawan",
    "2": "Cerah Berawan",
    "3": "Berawan",
    "4": "Berawan Tebal",
    "5": "Udara Kabut",
    "10": "Asap",
    "45": "Kabut",
    "60": "Hujan Ringan",
    "61": "Hujan Sedang",
    "63": "Hujan Lebat",
    "80": "Hujan Lokal",
    "95": "Hujan Petir",
    "97": "Hujan Petir",
}
RAIN_CODES = {"60", "61", "63", "80", "95", "97"}

# --- HTTP/2 Client ---
def make_http_client():
    try:
        return httpx.Client(http2=True, headers=HTTP_HEADERS, timeout=20, follow_redirects=True)
    except Exception:
        return httpx.Client(http2=False, headers=HTTP_HEADERS, timeout=20, follow_redirects=True)

HTTP = make_http_client()

# --- UTIL CONFIG ---
def load_config():
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log_activity(f"load_config err: {e}")
    return {}

def save_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log_activity(f"save_config err: {e}")
        return False

def ensure_default_adm4():
    cfg = load_config()
    if "adm4_default" not in cfg:
        cfg["adm4_default"] = DEFAULT_ADM4
        save_config(cfg)
        log_activity(f"ADM4 default di-set ke {DEFAULT_ADM4}")
    return cfg["adm4_default"]

# --- UTIL NOTIF & GEO ---
def notify(title, text):
    text = text.strip().replace("\n", " ")[:1000]
    title_q = shlex.quote(title)
    text_q = shlex.quote(text)
    if shutil.which("termux-notification"):
        os.system(f"termux-notification --title {title_q} --content {text_q}")
        if shutil.which("termux-vibrate"):
            os.system("termux-vibrate -d 200")
    else:
        print(f"🔔 {title}: {text}")

def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = radians(lat2 - lat1); dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 2 * R * asin(min(1, sqrt(a)))

def _parse_coord(text):
    text = (text or "").strip().upper()
    import re
    m = re.search(r"([-+]?\d+(?:\.\d+)?)", text)
    if not m: return None
    val = float(m.group(1))
    if "LS" in text: val = -abs(val)
    if "LU" in text: val = abs(val)
    if "BB" in text: val = -abs(val)
    if "BT" in text: val = abs(val)
    return val

def _parse_iso_dt(s):
    try:
        if isinstance(s, str) and s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.fromisoformat(s)
    except Exception:
        return None

# --- FILE STATE ---
def _load_last_quake_id():
    try:
        if os.path.exists(LAST_QUAKE_FILE):
            with open(LAST_QUAKE_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
    except:
        pass
    return ""

def _save_last_quake_id(qid):
    try:
        with open(LAST_QUAKE_FILE, "w", encoding="utf-8") as f:
            f.write(qid)
    except Exception as e:
        log_activity(f"Save last quake id fail: {e}")

def _load_notified_rain():
    try:
        if os.path.exists(NOTIFIED_RAIN_FILE):
            with open(NOTIFIED_RAIN_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
    except Exception:
        pass
    return set()

def _save_notified_rain(keys: set):
    try:
        with open(NOTIFIED_RAIN_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(keys)), f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_activity(f"save notified rain err: {e}")

# --- CUACA (API Publik, ADM4) ---
def _collect_forecasts(node, out, seen):
    # Rekursif ambil item prakiraan; robust variasi struktur JSON
    if isinstance(node, dict):
        time_keys = ["datetime", "time", "waktu", "jam", "jamCuaca"]
        wx_keys = ["weather", "cuaca", "kodeCuaca", "code"]

        ts = next((str(node[k]) for k in time_keys if k in node and node[k]), None)

        code = None; desc = None
        for k in wx_keys:
            if k in node:
                w = node[k]
                if isinstance(w, dict):
                    code = str(w.get("code") or w.get("id") or w.get("value") or w.get("kode") or "").strip()
                    desc = w.get("desc") or w.get("description") or w.get("text")
                else:
                    code = str(w).strip()
                break

        t = node.get("t") or node.get("temp") or node.get("tempC") or node.get("temperature")
        hu = node.get("hu") or node.get("rh") or node.get("humidity")

        if ts and (code or desc):
            key = (ts, code or desc)
            if key not in seen:
                seen.add(key)
                out.append({
                    "datetime": ts,
                    "dt": _parse_iso_dt(ts),
                    "kode": code,
                    "teks": desc or BMKG_WEATHER_MAP.get(code or "", f"Kode {code}"),
                    "t": t,
                    "hu": hu,
                })

        for v in node.values():
            _collect_forecasts(v, out, seen)

    elif isinstance(node, list):
        for item in node:
            _collect_forecasts(item, out, seen)

def fetch_weather_publik_rows(adm4=None, limit=24):
    adm4 = adm4 or ensure_default_adm4()
    url = BMKG_PUBLIK_URL_TMPL.format(adm4=adm4)
    resp = HTTP.get(url)
    print(f"[{resp.http_version}] {resp.status_code} {url}")
    resp.raise_for_status()
    data = resp.json()
    out, seen = [], set()
    _collect_forecasts(data, out, seen)
    if not out:
        raise ValueError("Tidak ada entri prakiraan pada respons.")
    out.sort(key=lambda r: r["dt"] or r["datetime"])
    return out[:limit]

def get_weather():
    # Menu cepat: ambil cuaca untuk ADM4 default
    adm4 = ensure_default_adm4()
    try:
        rows = fetch_weather_publik_rows(adm4=adm4, limit=12)
        print(f"🌤️ Prakiraan Cuaca (API Publik) adm4={adm4}")
        for r in rows:
            ts = r["dt"].strftime("%d-%m-%Y %H:%M") if r["dt"] else r["datetime"]
            extra = []
            if r["t"] is not None: extra.append(f"{r['t']}°C")
            if r["hu"] is not None: extra.append(f"RH {r['hu']}%")
            e = f" ({', '.join(extra)})" if extra else ""
            print(f"- {ts} → {r['teks']}{e} [kode {r['kode']}]")
        log_activity(f"BMKG Publik OK adm4={adm4} items={len(rows)}")
    except Exception as e:
        print(f"❌ Gagal ambil API Publik BMKG ({adm4}): {e}")
        log_activity(f"BMKG Publik FAIL adm4={adm4}: {e}")

def watch_rain_3h_api_publik(interval_sec=600):
    """
    Pantau API Publik (ADM4 default) dan kirim notifikasi jika ada prakiraan
    hujan/petir yang waktunya ≤ 3 jam dari sekarang (belum pernah dinotifikasi).
    """
    adm4 = ensure_default_adm4()
    notified = _load_notified_rain()
    print(f"👀 Pantau hujan/petir ≤3 jam (adm4={adm4}), interval {interval_sec}s. Ctrl+C untuk stop.")
    try:
        while True:
            try:
                rows = fetch_weather_publik_rows(adm4=adm4, limit=40)
                now = datetime.now()
                soon = now + timedelta(hours=3)
                count_new = 0
                for r in rows:
                    if r["kode"] not in RAIN_CODES:
                        continue
                    dt = r["dt"]
                    if not dt:
                        continue
                    # asumsikan local time jika naive
                    if now <= dt <= soon:
                        key = f"{adm4}|{r['datetime']}|{r['kode']}"
                        if key not in notified:
                            notify("BMKG: Hujan/Petir ≤3 jam", f"{dt.strftime('%d-%m %H:%M')} • {r['teks']} • adm4={adm4}")
                            log_activity(f"Rain alert {key}")
                            notified.add(key)
                            count_new += 1
                if count_new:
                    _save_notified_rain(notified)
                if not count_new:
                    print(".", end="", flush=True)
            except Exception as e:
                print(f"\n⚠️ Watch hujan: {e}")
                log_activity(f"Watch rain warn: {e}")
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        print("\n✅ Pemantauan hujan dihentikan.")
        log_activity("Watch rain stopped")

def export_weather_csv(adm4=None, hours=24):
    adm4 = adm4 or ensure_default_adm4()
    try:
        rows = fetch_weather_publik_rows(adm4=adm4, limit=hours*2)
        fname = os.path.join(DATA_DIR, f"weather_{adm4}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
        with open(fname, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["datetime", "text", "code", "tempC", "RH"])
            for r in rows:
                ts = r["dt"].strftime("%Y-%m-%d %H:%M") if r["dt"] else r["datetime"]
                w.writerow([ts, r["teks"], r["kode"], r["t"] or "", r["hu"] or ""])
        print(f"✅ Export cuaca → {fname}")
        log_activity(f"Export weather CSV: {fname}")
    except Exception as e:
        print(f"❌ Gagal export cuaca: {e}")
        log_activity(f"Export weather err: {e}")

# --- GEMPA (khusus Jember) ---
def show_bmkg_gempa_nasional():
    """
    Tampilkan gempa terakhir nasional dari autogempa.xml (HTTP/2)
    """
    try:
        r = HTTP.get(BMKG_GEMPA_URL)
        print(f"[{r.http_version}] {r.status_code} {BMKG_GEMPA_URL}")
        r.raise_for_status()
        content = r.content
        import xml.etree.ElementTree as ET
        root = ET.fromstring(content)
        g = root.find("gempa")
        if g is None:
            raise ValueError("Tag <gempa> tidak ditemukan.")
        data = {
            "Tanggal": g.findtext("Tanggal"),
            "Jam": g.findtext("Jam"),
            "Lintang": g.findtext("Lintang"),
            "Bujur": g.findtext("Bujur"),
            "Magnitude": g.findtext("Magnitude"),
            "Kedalaman": g.findtext("Kedalaman"),
            "Wilayah": g.findtext("Wilayah"),
            "Potensi": g.findtext("Potensi"),
            "Dirasakan": g.findtext("Dirasakan"),
        }
        print("===== GEMPA TERKINI (BMKG Nasional) =====")
        for k, v in data.items():
            print(f"{k}: {v}")
        if "JEMBER" not in (data.get("Wilayah") or "").upper() and "JEMBER" not in (data.get("Dirasakan") or "").upper():
            print("\nℹ️ Gempa terakhir bukan di wilayah Jember.")
        log_activity(f"BMKG Gempa Nasional OK: {data.get('Wilayah')}")
    except Exception as e:
        print(f"❌ Gagal ambil gempa nasional: {e}")
        log_activity(f"BMKG Gempa nasional gagal: {e}")

def show_gempa_jember_latest(radius_km=300):
    """
    Ambil gempaterkini.xml dan cari kejadian yang paling dekat dengan Jember
    atau menyebut 'Jember', dalam radius_km.
    """
    try:
        r = HTTP.get(BMKG_GEMPA_LIST_URL)
        print(f"[{r.http_version}] {r.status_code} {BMKG_GEMPA_LIST_URL}")
        r.raise_for_status()
        content = r.content

        root = None
        if HAS_LXML:
            parser = etree.XMLParser(recover=True)
            root = etree.fromstring(content, parser=parser)
        else:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(content)

        items = root.findall(".//gempa")
        best = None
        best_dist = 1e9
        for g in items:
            tanggal = g.findtext("Tanggal") or ""
            jam = g.findtext("Jam") or ""
            lintang = g.findtext("Lintang")
            bujur = g.findtext("Bujur")
            wilayah = g.findtext("Wilayah") or ""
            dirasakan = g.findtext("Dirasakan") or ""
            lat = _parse_coord(lintang); lon = _parse_coord(bujur)

            mention = ("JEMBER" in wilayah.upper()) or ("JEMBER" in dirasakan.upper())
            dist = None
            if lat is not None and lon is not None:
                dist = _haversine_km(JEMBER_COORD[0], JEMBER_COORD[1], lat, lon)

            if mention or (dist is not None and dist <= radius_km):
                if dist is None: dist = best_dist - 1
                if dist < best_dist:
                    best = {
                        "Tanggal": tanggal, "Jam": jam, "Wilayah": wilayah,
                        "Magnitude": g.findtext("Magnitude") or "?",
                        "Kedalaman": g.findtext("Kedalaman") or "?",
                        "Dirasakan": dirasakan, "dist": dist
                    }
                    best_dist = dist

        if not best:
            print(f"ℹ️ Tidak ada gempa di/near Jember (≤ {radius_km} km) pada daftar terakhir.")
            return

        print("===== GEMPA TERBARU (KHUSUS JEMBER) =====")
        print(f"Tanggal:   {best['Tanggal']}")
        print(f"Jam:       {best['Jam']}")
        print(f"Wilayah:   {best['Wilayah']}")
        print(f"Magnitudo: {best['Magnitude']} | Kedalaman: {best['Kedalaman']}")
        print(f"Perkiraan jarak dari Jember: ~{best['dist']:.0f} km")
        if best["Dirasakan"]:
            print(f"Dirasakan: {best['Dirasakan']}")
        log_activity(f"Gempa Jember latest: {best['Wilayah']} ~{best['dist']:.0f}km")
    except Exception as e:
        print(f"❌ Gagal ambil gempa Jember: {e}")
        log_activity(f"Gempa Jember gagal: {e}")

def watch_quake_jember(radius_km=300, interval_sec=60):
    """
    Pantau autogempa (terakhir). Notify hanya jika dekat Jember (≤ radius_km)
    atau disebut di teks Wilayah/Dirasakan.
    """
    print(f"👀 Pantau gempa khusus Jember (radius {radius_km} km). Ctrl+C untuk stop.")
    last_id = _load_last_quake_id()
    try:
        while True:
            try:
                r = HTTP.get(BMKG_GEMPA_URL)
                print(f"[{r.http_version}] {r.status_code} (gempa)")
                r.raise_for_status()
                content = r.content
                import xml.etree.ElementTree as ET
                root = ET.fromstring(content)
                g = root.find("gempa")
                if g is None:
                    raise ValueError("Tag <gempa> tidak ditemukan.")

                tanggal = g.findtext("Tanggal") or ""
                jam = g.findtext("Jam") or ""
                lintang = g.findtext("Lintang")
                bujur = g.findtext("Bujur")
                wilayah = g.findtext("Wilayah") or ""
                magnit = g.findtext("Magnitude") or "?"
                dirasakan = g.findtext("Dirasakan") or ""
                qid = f"{tanggal} {jam}"

                if qid != last_id:
                    lat = _parse_coord(lintang); lon = _parse_coord(bujur)
                    dist = None
                    if lat is not None and lon is not None:
                        dist = _haversine_km(JEMBER_COORD[0], JEMBER_COORD[1], lat, lon)
                    near = dist is not None and dist <= radius_km
                    mention = ("JEMBER" in wilayah.upper()) or ("JEMBER" in dirasakan.upper())

                    if near or mention:
                        info_dist = f" ~{dist:.0f} km" if dist is not None else ""
                        notify(f"BMKG Gempa M{magnit}", f"{tanggal} {jam} • {wilayah}{info_dist}")
                        log_activity(f"Quake alert Jember: M{magnit} {wilayah}{info_dist}")
                    else:
                        print(f"ℹ️ Gempa baru: {tanggal} {jam} • {wilayah}")
                        log_activity(f"Quake not near Jember: {wilayah}")

                    _save_last_quake_id(qid)
                    last_id = qid
                else:
                    print(".", end="", flush=True)
            except Exception as e:
                print(f"\n⚠️ Watch gempa: {e}")
                log_activity(f"Watch gempa warn: {e}")
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        print("\n✅ Pemantauan gempa dihentikan.")
        log_activity("Watch gempa stopped")

# --- DIAGNOSTICS ---
def diagnostics_bmkg():
    adm4 = ensure_default_adm4()
    print("🔎 Diagnostics BMKG (HTTP/2)")
    try:
        r1 = HTTP.get(BMKG_PUBLIK_URL_TMPL.format(adm4=adm4))
        ct = r1.headers.get("content-type", "?")
        print(f"- Cuaca ADM4 {adm4}: [{r1.http_version}] {r1.status_code} • {ct}")
    except Exception as e:
        print(f"- Cuaca ADM4 {adm4}: ERROR {e}")

    try:
        r2 = HTTP.get(BMKG_GEMPA_URL)
        ct = r2.headers.get("content-type", "?")
        print(f"- Autogempa: [{r2.http_version}] {r2.status_code} • {ct}")
    except Exception as e:
        print(f"- Autogempa: ERROR {e}")

    try:
        r3 = HTTP.get(BMKG_GEMPA_LIST_URL)
        ct = r3.headers.get("content-type", "?")
        print(f"- Gempaterkini: [{r3.http_version}] {r3.status_code} • {ct}")
    except Exception as e:
        print(f"- Gempaterkini: ERROR {e}")

# --- FITUR UTAMA LAINNYA (dari OmniTool lama) ---
def backup_files(source_folder, backup_name=None):
    if not os.path.exists(source_folder):
        print(f"❌ Folder tidak ditemukan: {source_folder}")
        return
    if not backup_name:
        backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    dest = os.path.join(BACKUP_PATH, backup_name)
    try:
        shutil.copytree(source_folder, dest)
        msg = f"✅ Backup: {source_folder} → {dest}"
        print(msg); log_activity(msg)
    except Exception as e:
        msg = f"❌ Gagal backup: {e}"
        print(msg); log_activity(msg)

def move_to_trash(file_path):
    try:
        trash_name = f"{int(time.time())}_{os.path.basename(file_path)}"
        trash_dest = os.path.join(TRASH_PATH, trash_name)
        shutil.move(file_path, trash_dest)
        log_activity(f"🗑️ Dipindah ke Trash: {file_path} → {trash_dest}")
        return True
    except Exception as e:
        log_activity(f"❌ Gagal pindah ke Trash: {file_path} — {e}")
  
