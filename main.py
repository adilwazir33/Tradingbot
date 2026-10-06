import os
import time
import threading
import queue
import requests
import sqlite3
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
import pandas as pd
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# FIXED FOR RENDER - pyquotex support
try:
    from quotexapi.stable_api import Quotex
except ModuleNotFoundError:
    from pyquotex.stable_api import Quotex

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
QUOTEX_EMAIL = os.getenv("QUOTEX_EMAIL")
QUOTEX_PASS = os.getenv("QUOTEX_PASS")

BASE_PAIRS = ["EURUSD", "GBPUSD", "EURJPY"]
OTC_MAP = {"EURUSD": "EURUSD_otc", "GBPUSD": "GBPUSD_otc", "EURJPY": "EURJPY_otc"}

app = Flask(__name__)
@app.route("/")
def home():
    return "QUOTEX v10.4 FINAL - FIXED"
@app.route("/health")
def health():
    return "OK"

qx_lock = threading.RLock()
outcome_qx_lock = threading.Lock()
sent_cache = OrderedDict()
outcome_queue = queue.Queue()
outcome_qx = None
DB_PATH = os.getenv("DB_PATH", "/tmp/quotex_v10.db")

def normalize_qx_ts(ts):
    ts = int(ts)
    if ts > 1e12:
        ts = ts // 1000
    return ts

def get_draw_threshold(asset, price):
    return 0.005 if "JPY" in asset else 0.00002

def get_next_candle_times():
    now = time.time()
    entry_ts = (int(now) // 60 - 1) * 60
    expiry_ts = entry_ts + 60
    expiry_close_ts = expiry_ts + 60
    scan_ts = entry_ts + 60 + 2
    sleep_sec = max(0, scan_ts - now)
    entry_dt = datetime.fromtimestamp(entry_ts, tz=timezone.utc)
    expiry_dt = datetime.fromtimestamp(expiry_ts, tz=timezone.utc)
    expiry_close_dt = datetime.fromtimestamp(expiry_close_ts, tz=timezone.utc)
    return entry_dt, expiry_dt, expiry_close_dt, sleep_sec, entry_ts, expiry_ts, expiry_close_ts

def cache_add(k):
    if k in sent_cache:
        return False
    sent_cache[k] = True
    if len(sent_cache) > 200:
        sent_cache.popitem(last=False)
    return True

def send_tg(t):
    for attempt in range(2):
        try:
            r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": t}, timeout=15)
            if r.status_code == 200:
                return True
            print(f"TG fail {r.status_code} {r.text} attempt {attempt+1}")
        except Exception as e:
            print(f"TG err {e} attempt {attempt+1}")
        time.sleep(1)
    print(f"TG FAILED: {t[:100]}")
    return False

def get_db_conn():
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        import psycopg2
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        return conn, "postgres"
    else:
        conn = sqlite3.connect(DB_PATH)
        return conn, "sqlite"

def init_db():
    conn, db_type = get_db_conn()
    cur = conn.cursor()
    if db_type == "postgres":
        cur.execute("""CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY, timestamp TEXT, asset TEXT, base_asset TEXT,
            is_otc INTEGER, signal TEXT, entry_price DOUBLE PRECISION,
            entry_candle_time BIGINT, expiry_candle_time BIGINT,
            expiry_close DOUBLE PRECISION, outcome TEXT, rsi DOUBLE PRECISION, confidence TEXT)""")
    else:
        cur.execute("""CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY, timestamp TEXT, asset TEXT, base_asset TEXT,
            is_otc INTEGER, signal TEXT, entry_price REAL,
            entry_candle_time INTEGER, expiry_candle_time INTEGER,
            expiry_close REAL, outcome TEXT, rsi REAL, confidence TEXT)""")
        conn.commit()
    conn.close()

def db_insert(d):
    conn, db_type = get_db_conn()
    cur = conn.cursor()
    if db_type == "postgres":
        cur.execute("""INSERT INTO signals (id, timestamp, asset, base_asset, is_otc, signal, entry_price, entry_candle_time, expiry_candle_time, expiry_close, outcome, rsi, confidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
            (d["id"], d["timestamp"], d["asset"], d["base_asset"], d["is_otc"], d["signal"], d["entry_price"], d["entry_candle_time"], d["expiry_candle_time"], d["expiry_close"], d["outcome"], d["rsi"], d["confidence"]))
    else:
        cur.execute("""INSERT OR IGNORE INTO signals VALUES (:id,:timestamp,:asset,:base_asset,:is_otc,:signal,:entry_price,:entry_candle_time,:expiry_candle_time,:expiry_close,:outcome,:rsi,:confidence)""", d)
        conn.commit()
    conn.close()

def db_update(sid, ec, out):
    conn, db_type = get_db_conn()
    cur = conn.cursor()
    if db_type == "postgres":
        cur.execute("UPDATE signals SET expiry_close=%s, outcome=%s WHERE id=%s", (ec, out, sid))
    else:
        cur.execute("UPDATE signals SET expiry_close=?, outcome=? WHERE id=?", (ec, out, sid))
        conn.commit()
    conn.close()

def db_stats():
    conn, db_type = get_db_conn()
    cur = conn.cursor()
    def wr(q=""):
        cur.execute(f"SELECT COUNT(*), SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) FROM signals WHERE outcome IN ('WIN','LOSS') {q}")
        t, w = cur.fetchone()
        t = t or 0; w = w or 0
        return t, w, w / t * 100 if t else 0
    s = {}
    s["ALL"] = wr()
    for b in BASE_PAIRS:
        s[b] = wr(f"AND base_asset='{b}'")
    s["OTC"] = wr("AND is_otc=1"); s["NORMAL"] = wr("AND is_otc=0")
    s["CALL"] = wr("AND signal='CALL'"); s["PUT"] = wr("AND signal='PUT'")
    s["HIGH"] = wr("AND confidence='HIGH'"); s["MEDIUM"] = wr("AND confidence='MEDIUM'")
    conn.close()
    return s

init_db()

def login_qx_safe(old=None):
    if old:
        try: old.close()
        except: pass
        time.sleep(2)
    for _ in range(3):
        try:
            qx = Quotex(email=QUOTEX_EMAIL, password=QUOTEX_PASS)
            qx.connect()
            for _ in range(15):
                if qx.check_connect():
                    return qx
                time.sleep(1)
        except Exception as e:
            print(f"Login fail {e}")
        time.sleep(5)
    return None

def ema(s, p):
    return s.ewm(span=p, adjust=False).mean()

def rsi_calc(s, p=14):
    d = s.diff(); g = d.clip(lower=0); l = -d.clip(upper=0)
    ag = g.ewm(alpha=1 / p, adjust=False).mean()
    al = l.ewm(alpha=1 / p, adjust=False).mean()
    return 100 - (100 / (1 + (ag / al.replace(0, float('nan')))))

def analyze_pair(qx, asset, entry_ts):
    with qx_lock:
        candles = qx.get_candles(asset, 60, 100)
    if not candles or len(candles) < 60:
        return None
    df = pd.DataFrame(candles)
    df["time"] = df["time"].apply(normalize_qx_ts)
    df = df.sort_values("time").reset_index(drop=True)
    df = df[df["time"] <= entry_ts].copy()
    if len(df) < 50:
        return None
    df["ema14"] = ema(df["close"], 14); df["ema50"] = ema(df["close"], 50)
    df["rsi"] = rsi_calc(df["close"]); df["mom"] = df["close"] - df["close"].shift(10)
    last = df.iloc[-1]
    if int(last["time"])!= int(entry_ts):
        return None
    dist = abs(last["ema14"] - last["ema50"])
    atr = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]
    conf = "HIGH" if dist > atr * 0.3 and 40 < last["rsi"] < 60 else "MEDIUM" if dist > atr * 0.15 else "LOW"
    if conf == "LOW":
        return None
    rh = df.iloc[-12:-2]["high"].max(); rl = df.iloc[-12:-2]["low"].min()
    sig = None
    if last["close"] > last["ema14"] > last["ema50"] and last["rsi"] > 50 and last["mom"] > 0 and last["close"] > rh:
        sig = "CALL"
    elif last["close"] < last["ema14"] < last["ema50"] and last["rsi"] < 50 and last["mom"] < 0 and last["close"] < rl:
        sig = "PUT"
    if sig:
        return {"signal": sig, "close": last["close"], "time": last["time"], "rsi": last["rsi"], "conf": conf}
    return None

def fetch_candles_with_retry(qx, asset, target_ts=None, retries=5):
    for attempt in range(retries):
        try:
            with outcome_qx_lock:
                candles = qx.get_candles(asset, 60, 15)
            if candles:
                if target_ts is not None:
                    times = []
                    for c in candles:
                        t = c.get("time", c.get("timestamp"))
                        if t is None:
                            continue
                        times.append(normalize_qx_ts(t))
                    if target_ts in times:
                        return candles
                    print(f"Retry {attempt+1}/{retries} - target {target_ts} missing, got {times[-3:]}")
                else:
                    return candles
            else:
                print(f"Retry {attempt+1}/{retries} - empty {asset}")
        except Exception as e:
            print(f"Retry {attempt+1}/{retries} err {e}")
        if attempt < retries - 1:
            time.sleep(2 + attempt * 2)
    return None

def outcome_worker_loop():
    global outcome_qx
    print("Outcome worker v10.4 started")
    outcome_qx = login_qx_safe(None)
    while True:
        job = None
        try:
            job = outcome_queue.get(timeout=10)
            asset, res, sig_id, entry_ts, expiry_ts, expiry_close_ts = job
            wait_until = expiry_close_ts + 6
            sleep_needed = wait_until - time.time()
            if sleep_needed > 0:
                time.sleep(sleep_needed)
            need_reconnect = False
            with outcome_qx_lock:
                if not outcome_qx or not outcome_qx.check_connect():
                    need_reconnect = True
            if need_reconnect:
                new_qx = login_qx_safe(outcome_qx)
                with outcome_qx_lock:
                    outcome_qx = new_qx
                if not outcome_qx:
                    db_update(sig_id, None, "LOGIN_FAIL")
                    continue
            candles = fetch_candles_with_retry(outcome_qx, asset, target_ts=expiry_ts, retries=5)
            expiry_close = None
            outcome = "UNKNOWN"
            if candles:
                df = pd.DataFrame(candles)
                df["time"] = df["time"].apply(normalize_qx_ts)
                df = df.sort_values("time")
                row = df[df["time"] == expiry_ts]
                if not row.empty:
                    expiry_close = float(row.iloc[0]["close"])
                    draw_thr = get_draw_threshold(asset, res["close"])
                    diff = abs(expiry_close - res["close"])
                    if diff <= draw_thr:
                        outcome = "DRAW"
                    elif (res["signal"] == "CALL" and expiry_close > res["close"]) or (res["signal"] == "PUT" and expiry_close < res["close"]):
                        outcome = "WIN"
                    else:
                        outcome = "LOSS"
                else:
                    outcome = "UNKNOWN_CANDLE"
            else:
                outcome = "FETCH_FAIL"
            db_update(sig_id, expiry_close, outcome)
            emoji = "✅" if outcome == "WIN" else "❌" if outcome == "LOSS" else "➖" if outcome == "DRAW" else "❓"
            send_tg(f"{emoji} RESULT {asset} {res['signal']} ID:{sig_id[:8]}\nEntry {res['close']:.5f} → Exp {expiry_close} = {outcome}")
        except queue.Empty:
            continue
        except Exception as e:
            print(f"Outcome worker err {e}")
            if job:
                try: db_update(job[2], None, f"ERROR:{str(e)[:50]}")
                except: pass
            time.sleep(2)
        finally:
            if job is not None:
                try: outcome_queue.task_done()
                except: pass

def track_exact_expiry(asset, res, sig_id, entry_ts, expiry_ts, expiry_close_ts):
    outcome_queue.put((asset, res, sig_id, entry_ts, expiry_ts, expiry_close_ts))

def scanner_loop():
    qx = login_qx_safe()
    if not qx:
        return
    print("v10.4 LIVE smart reconnect")
    consecutive_errors = 0
    while True:
        try:
            entry_dt, expiry_dt, expiry_close_dt, sleep_sec, entry_ts, expiry_ts, expiry_close_ts = get_next_candle_times()
            print(f"Sleep {sleep_sec:.1f}s -> Entry {entry_dt.strftime('%H:%M:%S')} Exp {expiry_close_dt.strftime('%H:%M:%S')} UTC")
            if sleep_sec > 0:
                time.sleep(sleep_sec)
            need_reconnect = False
            with qx_lock:
                if not qx.check_connect():
                    need_reconnect = True
            if need_reconnect:
                new_qx = login_qx_safe(qx)
                with qx_lock:
                    qx = new_qx
                if not qx:
                    time.sleep(30)
                    continue
            for base in BASE_PAIRS:
                try:
                    asset = base; is_otc = 0
                    with qx_lock:
                        if not qx.check_asset_open(base):
                            if qx.check_asset_open(OTC_MAP[base]):
                                asset = OTC_MAP[base]; is_otc = 1
                            else:
                                continue
                    res = analyze_pair(qx, asset, entry_ts)
                    if res:
                        key = (asset, res["signal"], entry_ts)
                        if key in sent_cache:
                            continue
                        cache_add(key)
                        sig_id = str(uuid.uuid4())
                        db_insert({"id": sig_id, "timestamp": datetime.now(timezone.utc).isoformat(), "asset": asset, "base_asset": base, "is_otc": is_otc, "signal": res["signal"], "entry_price": res["close"], "entry_candle_time": entry_ts, "expiry_candle_time": expiry_ts, "expiry_close": None, "outcome": None, "rsi": res["rsi"], "confidence": res["conf"]})
                        send_tg(f"{'🟢' if res['signal']=='CALL' else '🔴'} {res['signal']} {asset} ID:{sig_id[:8]}\nEntry OPEN {entry_dt.strftime('%H:%M:%S')} @ {res['close']:.5f} RSI {res['rsi']:.1f} [{res['conf']}]\nExpiry CLOSE {expiry_close_dt.strftime('%H:%M:%S')} UTC")
                        track_exact_expiry(asset, res, sig_id, entry_ts, expiry_ts, expiry_close_ts)
                    time.sleep(0.3)
                except Exception as pair_e:
                    print(f"Pair {base} error {pair_e} - skipping")
                    continue
            consecutive_errors = 0
        except Exception as e:
            consecutive_errors += 1
            print(f"Scanner err {e} count {consecutive_errors}")
            is_conn_error = False
            with qx_lock:
                if not qx or not qx.check_connect():
                    is_conn_error = True
            if is_conn_error or consecutive_errors >= 3:
                new_qx = login_qx_safe(qx)
                with qx_lock:
                    qx = new_qx
                consecutive_errors = 0
                if not qx:
                    time.sleep(30)
            else:
                time.sleep(5)

async def start(update: Update, _):
    await update.message.reply_text("🟢 v10.4 FINAL\n/stats /market /status")
async def status(update: Update, _):
    await update.message.reply_text(f"🟢 v10.4 ONLINE\nQueue: {outcome_queue.qsize()}")
async def market(update: Update, _):
    await update.message.reply_text("⏳ Checking...")
    entry_dt, expiry_dt, expiry_close_dt, _, entry_ts, expiry_ts, expiry_close_ts = get_next_candle_times()
    qx = login_qx_safe()
    if not qx:
        await update.message.reply_text("❌ Login fail")
        return
    lines = [f"📊 v10.4 MARKET\nCandle: {entry_dt.strftime('%H:%M:%S')} UTC"]
    for base in BASE_PAIRS:
        asset = base; note = ""
        if not qx.check_asset_open(base):
            if qx.check_asset_open(OTC_MAP[base]):
                asset = OTC_MAP[base]; note = "(OTC)"
            else:
                lines.append(f"⚪ {base}: CLOSED"); continue
        res = analyze_pair(qx, asset, entry_ts)
        if res:
            lines.append(f"{'🟢' if res['signal']=='CALL' else '🔴'} {asset}{note}: {res['signal']} [{res['conf']}]")
        else:
            lines.append(f"⚪ {asset}{note}: WAIT")
    await update.message.reply_text("\n".join(lines))
    try: qx.close()
    except: pass
async def stats_cmd(update: Update, _):
    s = db_stats()
    if s["ALL"][0] == 0:
        await update.message.reply_text("📊 No outcomes yet")
        return
    m = f"📊 v10.4 STATS\nOverall: {s['ALL'][1]}/{s['ALL'][0]} = {s['ALL'][2]:.1f}%\n"
    for b in BASE_PAIRS:
        m += f"{b}: {s[b][1]}/{s[b][0]}={s[b][2]:.1f}%\n"
    m += f"NORMAL:{s['NORMAL'][1]}/{s['NORMAL'][0]}={s['NORMAL'][2]:.1f}% OTC:{s['OTC'][1]}/{s['OTC'][0]}={s['OTC'][2]:.1f}%\nCALL:{s['CALL'][1]}/{s['CALL'][0]}={s['CALL'][2]:.1f}% PUT:{s['PUT'][1]}/{s['PUT'][0]}={s['PUT'][2]:.1f}%\nHIGH:{s['HIGH'][1]}/{s['HIGH'][0]}={s['HIGH'][2]:.1f}% MED:{s['MEDIUM'][1]}/{s['MEDIUM'][0]}={s['MEDIUM'][2]:.1f}%"
    await update.message.reply_text(m)

def run_bot():
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("market", market))
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    threading.Thread(target=scanner_loop, daemon=True).start()
    threading.Thread(target=outcome_worker_loop, daemon=True).start()
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
