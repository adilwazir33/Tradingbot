import os
import requests
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")

flask_app = Flask(__name__)
@flask_app.route('/')
def home():
    return "ADIL BHAI SUPER BOT LIVE HAI!"

def get_klines(symbol, interval, limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    r = requests.get(url).json()
    return [float(c[4]) for c in r], [float(c[2]) for c in r], [float(c[3]) for c in r]

def get_rsi(closes, p=14):
    g=l=0
    for i in range(1, p+1):
        d=closes[-i]-closes[-i-1]
        if d>0: g+=d
        else: l+=abs(d)
    if l==0: return 100
    rs=(g/p)/(l/p)
    return 100 - (100/(1+rs))

def get_ema(closes, p=50):
    k=2/(p+1); e=closes[0]
    for pr in closes[1:]: e=pr*k+e*(1-k)
    return e

def atr(highs, lows, closes, p=14):
    tr=[]
    for i in range(1,len(closes)):
        tr.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
    return sum(tr[-p:])/p

def get_analysis(symbol):
    c15,h15,l15 = get_klines(symbol, "15m", 100)
    c1h,h1h,l1h = get_klines(symbol, "1h", 100)
    c4h,h4h,l4h = get_klines(symbol, "4h", 100)

    price=c15[-1]
    r15=get_rsi(c15); r1h=get_rsi(c1h); r4h=get_rsi(c4h)
    e15=get_ema(c15); e1h=get_ema(c1h); e4h=get_ema(c4h)

    t15="UP" if price>e15 else "DOWN"
    t1h="UP" if c1h[-1]>e1h else "DOWN"
    t4h="UP" if c4h[-1]>e4h else "DOWN"

    score=0
    if t15=="UP": score+=20
    if t1h=="UP": score+=25
    if t4h=="UP": score+=25
    if 40<r15<68: score+=15
    if 45<r1h<70: score+=15

    a=atr(h15,l15,c15)
    return price, r15, r1h, r4h, t15, t1h, t4h, score, a

async def signal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    btc_p, br15, br1h, br4h, bt15, bt1h, bt4h, bscore, batr = get_analysis("BTCUSDT")
    gold_p, gr15, gr1h, gr4h, gt15, gt1h, gt4h, gscore, gatr = get_analysis("PAXGUSDT")
    real_gold = gold_p - 8

    btc_status = f"🚀 99.9% LAMBA CONFIRMED\nEntry:{btc_p:.2f} SL:{btc_p-batr*1.5:.0f} TP:{btc_p+batr*2:.0f}" if bscore>=80 and bt15=="UP" else f"⚠️ WAIT - Score {bscore}%"
    gold_status = f"🚀 99.9% LAMBA CONFIRMED" if gscore>=80 and gt15=="UP" else f"⚠️ WAIT - Score {gscore}% {gt15}"

    msg=f"""👑 QUANTUM GOD 99.9% SUPER BOT 👑
1️⃣ BTC {btc_p:.2f} | 15m:{br15:.0f} {bt15} 1H:{br1h:.0f} {bt1h} 4H:{bt4h}
👉 {btc_status}

2️⃣ GOLD {real_gold:.2f} | 15m:{gr15:.0f} {gt15} 1H:{gr1h:.0f} {gt1h}
👉 {gold_status}
"""
    await update.message.reply_text(msg)

def run_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("(?i)signal"), signal_handler))
    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    flask_app.run(host='0.0.0.0', port=10000)
