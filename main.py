import os, requests, threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CommandHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")
flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "HACKER BOT LIVE"

SYMBOLS = {"BTC":"BTCUSDT","GOLD":"PAXGUSDT","EUR":"EURUSDT"}
TIMEFRAMES = ["15m","1h","4h"]

def get_klines(symbol, interval, limit=100):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        r = requests.get(url, timeout=10).json()
        return [float(x[4]) for x in r]
    except: return None

def ema(data, p):
    k=2/(p+1); e=data[0]
    for x in data[1:]: e=x*k+e*(1-k)
    return e

def rsi_calc(c, period=14):
    g=l=0
    for i in range(1,period+1):
        d=c[-i]-c[-i-1]
        if d>0: g+=d
        else: l+=abs(d)
    if l==0: return 100
    rs=(g/period)/(l/period)
    return 100-(100/(1+rs))

def analyze_one(sym, tf):
    closes=get_klines(sym, tf)
    if not closes: return None
    price=closes[-1]; e21=ema(closes,21); e50=ema(closes,50); e200=ema(closes,200); rsi=rsi_calc(closes)
    score=0
    if price>e21>e50: score+=30
    if price>e200: score+=20
    if 40<rsi<70: score+=20
    if closes[-1]>closes[-2]: score+=10
    trend="NEUTRAL"
    if e21>e50 and price>e21: trend="BULLISH 🔥"
    elif e21<e50 and price<e21: trend="BEARISH 🔻"
    return {"price":price,"rsi":rsi,"score":score,"trend":trend}

def hacker_msg():
    msg="☠️ HACKER TERMINAL v9.0 ☠️\n```\n[SCANNING...]\n```\n\n"
    for name,sym in SYMBOLS.items():
        msg+=f"**-- {name} --**\n"
        for tf in TIMEFRAMES:
            res=analyze_one(sym,tf)
            if not res: continue
            s=res['score']
            sig="💤 WAIT"
            if s>=80: sig="🚀 BUY NOW"
            elif s<=20: sig="💀 SELL NOW"
            msg+=f"`{tf.upper():<4}` | {res['trend']:<12} | S:{s} | {sig}\n Price: ${res['price']:.2f} RSI:{res['rsi']:.0f}\n"
        msg+="\n"
    msg+="`[TIP]: 15M=Entry | 1H=Trend | 4H=Boss`"
    return msg

async def handle(update, context):
    await update.message.reply_text(hacker_msg(), parse_mode="Markdown")

def run_bot():
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=True", timeout=10)
        app=ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", handle))
        app.add_handler(CommandHandler("signal", handle))
        app.add_handler(MessageHandler(filters.TEXT & filters.Regex("(?i)signal|btc|gold|eur|hack"), handle))
        app.run_polling(drop_pending_updates=True)
    except Exception as e: print(e)

if __name__=="__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    flask_app.run(host='0.0.0.0', port=int(os.environ.get("PORT",10000)))
