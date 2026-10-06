import os, threading, time, requests
import pandas as pd
import numpy as np
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")

SYMBOLS = {
    "XAUUSD.r": {"name": "GOLD", "td": "XAU/USD"},
    "EURUSD.r": {"name": "EURUSD", "td": "EUR/USD"},
    "BTCUSD.r": {"name": "BTC", "td": "BTC/USD"},
}

app_flask = Flask(__name__)
@app_flask.route("/")
def home(): return "ADIL PRO TREND PULLBACK v16 LIVE"
@app_flask.route("/health")
def health(): return "OK"

def fmt(symbol, p):
    return f"{p:.2f}" if "XAU" in symbol or "BTC" in symbol else f"{p:.5f}"

def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def rsi(s):
    d=s.diff(); g=d.clip(lower=0); l=-d.clip(upper=0)
    ag=g.ewm(alpha=1/14, adjust=False).mean()
    al=l.ewm(alpha=1/14, adjust=False).mean()
    rs=ag/al.replace(0,np.nan)
    return (100-(100/(1+rs))).fillna(50)

def get_data(symbol, interval, size=300):
    url="https://api.twelvedata.com/time_series"
    params={"symbol":SYMBOLS[symbol]["td"],"interval":interval,"outputsize":size,"apikey":TWELVE_DATA_API_KEY,"format":"JSON"}
    try:
        d=requests.get(url,params=params,timeout=30).json()
        if "values" not in d: return None
        df=pd.DataFrame(d["values"])
        df["datetime"]=pd.to_datetime(df["datetime"])
        for c in ["open","high","low","close"]: df[c]=pd.to_numeric(df[c],errors="coerce")
        df=df.dropna().sort_values("datetime").reset_index(drop=True)
        if len(df)>2: df=df.iloc[:-1] # remove forming candle
        return df
    except: return None

def indicators(df):
    if df is None or len(df)<210: return None
    df=df.copy()
    df["ema50"]=ema(df["close"],50)
    df["ema200"]=ema(df["close"],200)
    df["rsi"]=rsi(df["close"])
    tr=pd.concat([df["high"]-df["low"],(df["high"]-df["close"].shift()).abs(),(df["low"]-df["close"].shift()).abs()],axis=1).max(axis=1)
    df["atr"]=tr.rolling(14).mean()
    df["mom"]=df["close"]-df["close"].shift(10)
    return df.dropna().reset_index(drop=True)

def structure(df):
    if len(df)<20: return "NEUTRAL"
    recent=df.iloc[-12:]
    h1=recent["high"].iloc[:6].max(); h2=recent["high"].iloc[6:].max()
    l1=recent["low"].iloc[:6].min(); l2=recent["low"].iloc[6:].min()
    if h2>h1 and l2>l1: return "BULLISH"
    if h2<h1 and l2<l1: return "BEARISH"
    return "NEUTRAL"

def get_trend(df):
    last=df.iloc[-1]; st=structure(df)
    if last["close"]>last["ema200"] and last["ema50"]>last["ema200"] and st=="BULLISH": return "BUY"
    if last["close"]<last["ema200"] and last["ema50"]<last["ema200"] and st=="BEARISH": return "SELL"
    return "WAIT"

def analyze(symbol):
    df4=get_data(symbol,"4h"); df1=get_data(symbol,"1h"); df15=get_data(symbol,"15min")
    if df4 is None or df1 is None or df15 is None: return {"signal":"WAIT","reason":"DATA_ERROR"}
    df4=indicators(df4); df1=indicators(df1); df15=indicators(df15)
    if df4 is None or df1 is None or df15 is None: return {"signal":"WAIT","reason":"NOT_ENOUGH_DATA"}
    t4=get_trend(df4); t1=get_trend(df1)
    if t4=="WAIT": return {"signal":"WAIT","reason":"4H trend unclear","t4":t4,"t1":t1}
    if t1!=t4: return {"signal":"WAIT","reason":"4H/1H conflict","t4":t4,"t1":t1}
    # 1H pullback check
    r1=df1.iloc[-1]; near=abs(r1["close"]-r1["ema50"])<=r1["atr"]*1.5
    if not near: return {"signal":"WAIT","reason":"1H pullback not ready","t4":t4,"t1":t1}
    # 15M BOS
    r15=df15.iloc[-1]; prev=df15.iloc[-2]; lb=df15.iloc[-8:-2]
    rh=lb["high"].max(); rl=lb["low"].min()
    entry_ok=False
    if t4=="BUY" and r15["close"]>rh and r15["rsi"]>=50 and r15["mom"]>0: entry_ok=True
    if t4=="SELL" and r15["close"]<rl and r15["rsi"]<=50 and r15["mom"]<0: entry_ok=True
    if not entry_ok: return {"signal":"WAIT","reason":"15M BOS missing","t4":t4,"t1":t1}
    atr=r15["atr"]; entry=float(r15["close"])
    if t4=="BUY":
        sl=min(float(df15.iloc[-8:]["low"].min())-atr*0.25, entry-atr*1.2)
        risk=entry-sl
        tp1, tp2, tp3 = entry+risk, entry+2*risk, entry+3*risk
    else:
        sl=max(float(df15.iloc[-8:]["high"].max())+atr*0.25, entry+atr*1.2)
        risk=sl-entry
        tp1, tp2, tp3 = entry-risk, entry-2*risk, entry-3*risk
    return {"signal":t4,"reason":"4H Trend + 1H Pullback + 15M BOS","t4":t4,"t1":t1,"rsi":float(r15["rsi"]),"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"candle":str(r15["datetime"])}

def format_signal(sym,res):
    if res["signal"]=="WAIT": return None
    emoji="🟢" if res["signal"]=="BUY" else "🔴"
    return f"{emoji} {res['signal']} {SYMBOLS[sym]['name']}\nEntry: {fmt(sym,res['entry'])}\nSL: {fmt(sym,res['sl'])}\nTP1: {fmt(sym,res['tp1'])} | TP2: {fmt(sym,res['tp2'])} | TP3: {fmt(sym,res['tp3'])}\n4H:{res['t4']} 1H:{res['t1']} RSI:{res['rsi']:.1f}\n{res['reason']}"

def send_tg(text):
    if not BOT_TOKEN or not CHAT_ID: return False
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",json={"chat_id":CHAT_ID,"text":text},timeout=20)
        return True
    except: return False

async def start(update, _): await update.message.reply_text(f"🟢 PRO BOT LIVE\nID: {update.effective_chat.id}\n/market /signal /status")
async def status(update, _): await update.message.reply_text("🟢 ONLINE\nStrategy: Trend + Pullback + BOS\nSL: Structure+ATR | TP: 1R/2R/3R")
async def market(update, _):
    lines=["📊 MARKET CHECK"]
    for s in SYMBOLS:
        r=analyze(s)
        icon="🟢" if r["signal"]=="BUY" else "🔴" if r["signal"]=="SELL" else "⚪"
        lines.append(f"{icon} {SYMBOLS[s]['name']}: {r['signal']} | {r['reason']}")
        time.sleep(1)
    await update.message.reply_text("\n".join(lines))
async def signal_cmd(update, _):
    found=False
    for s in SYMBOLS:
        r=analyze(s)
        msg=format_signal(s,r)
        if msg:
            await update.message.reply_text(msg); found=True
        time.sleep(1)
    if not found: await update.message.reply_text("⚪ No A+ setup now\nWaiting for 4H→1H Pullback→15M BOS")

sent=set()
def scanner():
    print("PRO SCANNER STARTED")
    while True:
        try:
            for s in SYMBOLS:
                r=analyze(s)
                if r["signal"] in ("BUY","SELL"):
                    key=(s,r["signal"],r["candle"])
                    if key not in sent:
                        m=format_signal(s,r)
                        if m: send_tg(m); sent.add(key)
                time.sleep(3)
        except Exception as e: print(e)
        time.sleep(300)

def run_bot():
    application=ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start",start))
    application.add_handler(CommandHandler("status",status))
    application.add_handler(CommandHandler("market",market))
    application.add_handler(CommandHandler("signal",signal_cmd))
    application.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    threading.Thread(target=scanner,daemon=True).start()
    threading.Thread(target=run_bot,daemon=True).start()
    app_flask.run(host="0.0.0.0",port=int(os.getenv("PORT",10000)))
