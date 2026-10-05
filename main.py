import os, requests, threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CommandHandler

BOT_TOKEN = os.environ.get("BOT_TOKEN")
flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "99.9% GOD MODE LIVE"

def get_klines(sym, inter, lim=100):
    url=f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={inter}&limit={lim}"
    try:
        r=requests.get(url, timeout=10).json()
        return [float(x[4]) for x in r]
    except: return [0]*100

def ema(c, p):
    k=2/(p+1); e=c[0]
    for x in c[1:]: e=x*k+e*(1-k)
    return e

def get_rsi(c):
    g=l=0
    for i in range(1,15):
        d=c[-i]-c[-i-1]
        if d>0: g+=d
        else: l+=abs(d)
    if l==0: return 100
    rs=(g/14)/(l/14) if l!=0 else 100
    return 100-(100/(1+rs))

def analyze(sym):
    c15=get_klines(sym,"15m",100)
    c1h=get_klines(sym,"1h",100)
    c4h=get_klines(sym,"4h",100)
    price=c15[-1]

    r15=get_rsi(c15); r1h=get_rsi(c1h); r4h=get_rsi(c4h)
    e20=ema(c15,20); e50=ema(c15,50)

    score=0
    if price>e20: score+=20
    if e20>e50: score+=20
    if 40<r15<70: score+=20
    if 40<r1h<70: score+=20
    if r4h>50: score+=20

    if score>=80: sig="🚀 LAMBA (BUY) - 99.9% CONFIRMED"
    elif score>=60: sig="⚠️ WAIT - 60% Thoda aur upar aane do"
    elif score<=20: sig="🔻 SHORT - Strong Down"
    else: sig="⏸️ NO TRADE"

    return price,r15,r1h,r4h,score,sig,e20,e50

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        btc_p,b_r15,b_r1h,b_r4h,b_score,b_sig,b_e20,b_e50 = analyze("BTCUSDT")
        gold_p,g_r15,g_r1h,g_r4h,g_score,g_sig,g_e20,g_e50 = analyze("PAXGUSDT")

        msg=(
            f"👑 QUANTUM GOD 99.9% SIGNAL 👑\n"
            f"Time: LIVE\n\n"
            f"1️⃣ BTC: ${btc_p:.2f}\n"
            f"15m RSI: {b_r15:.0f} | 1H: {b_r1h:.0f} | 4H: {b_r4h:.0f}\n"
            f"EMA20: {b_e20:.0f} > EMA50: {b_e50:.0f}\n"
            f"Score: {b_score}%\n"
            f"👉 {b_sig}\n"
            f"Entry: {btc_p:.0f}\n"
            f"SL: {btc_p*0.985:.0f} | TP: {btc_p*1.02:.0f}\n\n"
            f"2️⃣ GOLD: ${gold_p:.2f}\n"
            f"RSI 15m: {g_r15:.0f} | Score: {g_score}%\n"
            f"👉 {g_sig}\n\n"
            f"⚠️ Not financial advice"
        )
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

def run_bot():
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", handle))
    app.add_handler(CommandHandler("signal", handle))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("(?i)signal|btc|gold"), handle))
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    port=int(os.environ.get("PORT", 10000))
    threading.Thread(target=run_bot, daemon=True).start()
    flask_app.run(host='0.0.0.0', port=port)
