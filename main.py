import os, requests, threading, traceback
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CommandHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")
print(f"BOOT CHECK: BOT_TOKEN exists? {bool(BOT_TOKEN)}")

flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "HACKER BOT LIVE - Token OK" if BOT_TOKEN else "TOKEN MISSING!"

SYMBOLS = {"BTC":"BTCUSDT","GOLD":"PAXGUSDT","EUR":"EURUSDT"}
TIMEFRAMES = ["15m","1h","4h"]

def get_klines(symbol, interval):
    try:
        r = requests.get(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100", timeout=10).json()
        return [float(x[4]) for x in r]
    except: return None

def ema(data, p):
    k=2/(p+1); e=data[0]
    for x in data[1:]: e=x*k+e*(1-k)
    return e

def rsi_calc(c):
    g=l=0
    for i in range(1,15):
        d=c[-i]-c[-i-1]
        if d>0: g+=d
        else: l+=abs(d)
    if l==0: return 100
    return 100-(100/(1+(g/14)/(l/14)))

def analyze_one(sym, tf):
    closes=get_klines(sym, tf)
    if not closes: return None
    price=closes[-1]; e21=ema(closes,21); e50=ema(closes,50); rsi=rsi_calc(closes)
    score=0
    if price>e21>e50: score+=60
    if 40<rsi<70: score+=20
    if closes[-1]>closes[-2]: score+=20
    trend="BULLISH 🔥" if e21>e50 else "BEARISH 🔻"
    return {"price":price,"rsi":rsi,"score":score,"trend":trend}

def hacker_msg():
    msg="☠️ HACKER TERMINAL v9.0 ☠️\n\n"
    for name,sym in SYMBOLS.items():
        msg+=f"-- {name} --\n"
        for tf in TIMEFRAMES:
            res=analyze_one(sym,tf)
            if not res: continue
            s=res['score']
            sig="WAIT 💤"
            if s>=80: sig="BUY NOW 🚀"
            elif s<=20: sig="SELL NOW 💀"
            msg+=f"{tf.upper()} | {res['trend']} | S:{s} | {sig} | ${res['price']:.2f}\n"
        msg+="\n"
    return msg

async def handle(update, context):
    await update.message.reply_text(hacker_msg())

def run_bot():
    if not BOT_TOKEN:
        print("❌ FATAL: BOT_TOKEN missing in Environment!")
        return
    try:
        print("✅ Deleting webhook...")
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=True", timeout=10)
        print("✅ Starting polling...")
        app=ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", handle))
        app.add_handler(CommandHandler("signal", handle))
        app.add_handler(MessageHandler(filters.TEXT, handle))
        print("✅ POLLING LIVE - Bot ready!")
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        print(f"❌ BOT CRASH: {e}")
        traceback.print_exc()

if __name__=="__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    flask_app.run(host='0.0.0.0', port=int(os.environ.get("PORT",10000)))
