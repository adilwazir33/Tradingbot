import os, requests, threading, sys
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CommandHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")
print(f"BOOT CHECK: TOKEN={bool(BOT_TOKEN)}", flush=True)

flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "HACKER BOT LIVE - OK" if BOT_TOKEN else "TOKEN MISSING!"

SYMBOLS = {"BTC":"BTCUSDT","GOLD":"PAXGUSDT","EUR":"EURUSDT"}
TIMEFRAMES = ["15m","1h","4h"]

def get_klines(s,i):
    try:
        r=requests.get(f"https://api.binance.com/api/v3/klines?symbol={s}&interval={i}&limit=100",timeout=10).json()
        return [float(x[4]) for x in r]
    except: return None

def ema(d,p):
    k=2/(p+1); e=d[0]
    for x in d[1:]: e=x*k+e*(1-k)
    return e

def rsi_calc(c):
    g=l=0
    for i in range(1,15):
        d=c[-i]-c[-i-1]
        g+=d if d>0 else 0
        l+=abs(d) if d<0 else 0
    return 100 if l==0 else 100-(100/(1+(g/14)/(l/14)))

def analyze_one(sym,tf):
    closes=get_klines(sym,tf)
    if not closes: return None
    price=closes[-1]; e21=ema(closes,21); e50=ema(closes,50); rsi=rsi_calc(closes)
    score=60 if price>e21>e50 else 20
    if 40<rsi<70: score+=20
    trend="BULLISH 🔥" if e21>e50 else "BEARISH 🔻"
    return {"price":price,"rsi":rsi,"score":score,"trend":trend}

def hacker_msg():
    msg="☠️ HACKER TERMINAL v9.0 ☠️\n\n"
    for n,s in SYMBOLS.items():
        msg+=f"-- {n} --\n"
        for tf in TIMEFRAMES:
            r=analyze_one(s,tf)
            if not r: continue
            sig="WAIT 💤" if r['score']<80 else "BUY NOW 🚀"
            if r['score']<=20: sig="SELL NOW 💀"
            msg+=f"{tf} | {r['trend']} | S:{r['score']} | {sig} ${r['price']:.2f}\n"
        msg+="\n"
    return msg

async def handle(u,c): await u.message.reply_text(hacker_msg())

def run_bot():
    if not BOT_TOKEN:
        print("TOKEN MISSING!", flush=True); return
    print("Deleting webhook...", flush=True)
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=True", timeout=10)
    print("Starting polling...", flush=True)
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", handle))
    app.add_handler(CommandHandler("signal", handle))
    app.add_handler(MessageHandler(filters.TEXT, handle))
    print("POLLING LIVE!", flush=True)
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    flask_app.run(host='0.0.0.0', port=int(os.environ.get("PORT",10000)))
