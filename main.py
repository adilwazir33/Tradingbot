import os, threading, time
from datetime import datetime, timedelta
from flask import Flask
import telebot
import yfinance as yf

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
@app.route('/')
def home(): return "ADIL FINAL FIXED LIVE"

PAIRS = {"GOLD":"GC=F","EURUSD.r":"EURUSD=X","BTCUSD.r":"BTC-USD"}
REAL = {"GOLD":"GOLD","EURUSD.r":"EURUSD.r","BTCUSD.r":"BTCUSD.r"}

def fmt(n,p):
    if p==0: return "---"
    if "GOLD" in n: return f"{p:.2f}"
    if "EUR" in n: return f"{p:.5f}"
    return f"{p:.2f}"

def is_news_time():
    now = datetime.utcnow() + timedelta(hours=4)
    h = now.hour
    if 16 <= h <= 18: return True, "US News Time - WAIT"
    if 12 <= h <= 13: return True, "London News"
    return False, ""

def get_signal(ticker, tf):
    is_news, reason = is_news_time()
    if is_news and ("EUR" in ticker or "GC" in ticker):
        return "WAIT",0,0,0,0,0,reason
    try:
        hist = yf.Ticker(ticker).history(period="5d" if tf=="15m" else "1mo", interval=tf)
        if len(hist) < 22: return "WAIT",0,0,0,0,0,"Data Kam"
        last = float(hist['Close'].iloc[-1])
        sma = float(hist['Close'].rolling(20).mean().iloc[-1])
        diff = abs(last - sma)/sma*100
        if "EUR" in ticker: limit = 0.02
        else: limit = 0.08
        if diff < 0.0001: diff = 0.1
        if diff < limit:
            return "WAIT",last,0,0,0,0,f"Sideways {diff:.3f}%"
        sig = "BUY" if last > sma else "SELL"
        if "GC" in ticker: sl,tp1,tp2,tp3 = (0.004,0.006,0.012,0.020) if tf=="15m" else (0.006,0.008,0.015,0.025)
        elif "BTC" in ticker: sl,tp1,tp2,tp3 = (0.008,0.01,0.02,0.035) if tf=="15m" else (0.012,0.015,0.03,0.05)
        else: sl,tp1,tp2,tp3 = (0.001,0.0015,0.003,0.005) if tf=="15m" else (0.002,0.003,0.006,0.01)
        if sig=="BUY": return sig,last,last*(1-sl),last*(1+tp1),last*(1+tp2),last*(1+tp3),"Strong Trend"
        else: return sig,last,last*(1+sl),last*(1-tp1),last*(1-tp2),last*(1-tp3),"Strong Trend"
    except:
        return "WAIT",0,0,0,0,0,"Error"

@bot.message_handler(func=lambda m: m.text and "signal" in m.text.lower())
def handle(m):
    d = (datetime.utcnow()+timedelta(hours=4)).strftime("%d-%m %I:%M %p")
    msg = f"💰 ADIL PRO FIXED\n🕐 {d} Dubai\n\n"
    for title,tf in [("1H","1h"),("15M","15m")]:
        msg+=f"===== {title} =====\n"
        for k,t in PAIRS.items():
            s,e,sl,t1,t2,t3,r = get_signal(t,tf)
            if s=="WAIT":
                msg+=f"⏳ {REAL[k]} - WAIT\n{r}\n---\n"
            else:
                i="🚀" if s=="BUY" else "🔻"
                msg+=f"{i} {REAL[k]} - {s} CONFIRMED\nEntry:{fmt(k,e)} SL:{fmt(k,sl)}\nTP1:{fmt(k,t1)} TP2:{fmt(k,t2)} TP3:{fmt(k,t3)}\n---\n"
        msg+="\n"
    bot.send_message(m.chat.id, msg)

def run():
    while True:
        try: bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except: time.sleep(5)

if __name__=="__main__":
    threading.Thread(target=run, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
