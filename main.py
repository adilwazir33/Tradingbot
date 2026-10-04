import os, threading, time
from datetime import datetime, timedelta
from flask import Flask
import telebot
import yfinance as yf

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
@app.route('/')
def home(): return "ADIL NEWS FILTER LIVE"

PAIRS = {"GOLD":"GC=F","EURUSD.r":"EURUSD=X","BTCUSD.r":"BTC-USD"}
REAL = {"GOLD":"XAUUSD.r (GOLD)","EURUSD.r":"EURUSD.r","BTCUSD.r":"BTCUSD.r"}

def fmt(n,p):
    if p==0: return "---"
    if "GOLD" in n: return f"{p:.2f}"
    if "EUR" in n: return f"{p:.5f}"
    return f"{p:.2f}"

# --- NEWS FILTER ---
def is_news_time():
    now_dubai = datetime.utcnow() + timedelta(hours=4)
    hour = now_dubai.hour
    weekday = now_dubai.weekday() # 0=Monday

    # High Impact News Time (Dubai Time)
    # 4:30 PM - 6:30 PM Dubai = US News (CPI, NFP, FOMC) - Sabse khatarnak
    if hour >= 16 and hour <= 18:
        return True, "🔴 US High News (CPI/NFP) - 4:30PM Dubai"
    # 12:30 PM - 1:30 PM Dubai = London News
    if hour == 12 or hour == 13:
        return True, "🟡 London News Time"
    # Monday Opening + Friday Closing - Market kharab
    if weekday == 0 and hour < 10:
        return True, "Monday Opening Volatile"
    if weekday == 4 and hour >= 20:
        return True, "Friday Closing Volatile"

    return False, ""

def get_signal(ticker, tf):
    # Pehle News Check
    is_news, news_reason = is_news_time()
    if is_news and ("EUR" in ticker or "GC" in ticker):
        return "WAIT",0,0,0,0,0, news_reason

    try:
        hist = yf.Ticker(ticker).history(period="5d" if tf=="15m" else "1mo", interval=tf)
        if len(hist) < 22: return "WAIT",0,0,0,0,0,"Data Kam"
        last = float(hist['Close'].iloc[-1])
        sma = float(hist['Close'].rolling(20).mean().iloc[-1])
        diff = abs(last - sma)/sma*100
        if diff < 0.08:
            return "WAIT",last,0,0,0,0,f"Sideways {diff:.2f}%"

        sig = "BUY" if last > sma else "SELL"
        if "GC" in ticker: sl,tp1,tp2,tp3 = (0.004,0.006,0.012,0.020) if tf=="15m" else (0.006,0.008,0.015,0.025)
        elif "BTC" in ticker: sl,tp1,tp2,tp3 = (0.008,0.01,0.02,0.035) if tf=="15m" else (0.012,0.015,0.03,0.05)
        else: sl,tp1,tp2,tp3 = (0.001,0.0015,0.003,0.005) if tf=="15m" else (0.002,0.003,0.006,0.01)

        if sig=="BUY": return sig,last,last*(1-sl),last*(1+tp1),last*(1+tp2),last*(1+tp3),"Trend Strong"
        else: return sig,last,last*(1+sl),last*(1-tp1),last*(1-tp2),last*(1-tp3),"Trend Strong"
    except:
        return "WAIT",0,0,0,0,0,"Error"

@bot.message_handler(func=lambda m: m.text and "signal" in m.text.lower())
def handle(m):
    d = (datetime.utcnow()+timedelta(hours=4)).strftime("%d-%m %I:%M %p Dubai")
    msg = f"💰 ADIL PRO + NEWS FILTER\n🕐 {d}\n\n"
    for title,tf in [("1H","1h"),("15M","15m")]:
        msg+=f"====== {title} - CONFIRMED ======\n"
        for k,t in PAIRS.items():
            s,e,sl,t1,t2,t3,r = get_signal(t,tf)
            if s=="WAIT":
                msg+=f"⏳ {REAL[k]} - WAIT\n{r}\n---\n"
            else:
                i="🚀" if s=="BUY" else "🔻"
                msg+=f"{i} {REAL[k]} - {s} CONFIRMED\nEntry: {fmt(k,e)} | SL: {fmt(k,sl)}\nTP1:{fmt(k,t1)} TP2:{fmt(k,t2)} TP3:{fmt(k,t3)}\n---\n"
        msg+="\n"
    msg+="📌 WAIT = News / Sideways = Trade Mat Lo"
    bot.send_message(m.chat.id, msg)

def run():
    while True:
        try: bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except: time.sleep(5)

if __name__=="__main__":
    threading.Thread(target=run, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
