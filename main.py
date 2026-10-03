import os, time, threading, requests, yfinance as yf
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Live")
    def log_message(self, *a):
        return

def run_s():
    p=int(os.environ.get("PORT",10000))
    HTTPServer(("0.0.0.0",p),H).serve_forever()

threading.Thread(target=run_s,daemon=True).start()

BOT_TOKEN=os.getenv("BOT_TOKEN")
CHAT_ID=os.getenv("CHAT_ID")

SYMBOLS=[("EURUSD=X","EUR/USD"),("GBPUSD=X","GBP/USD"),("USDJPY=X","USD/JPY"),("BTC-USD","BTC/USD"),("ETH-USD","ETH/USD"),("GC=F","GOLD")]

def send(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",data={"chat_id":CHAT_ID,"text":msg,"parse_mode":"Markdown"},timeout=10)
    except:
        pass

def get_rsi(s,p=14):
    d=s.diff()
    g=d.where(d>0,0).rolling(p).mean()
    l=-d.where(d<0,0).rolling(p).mean()
    rs=g/l
    return 100-(100/(1+rs))

def check(ticker):
    try:
        df15=yf.download(ticker,period="5d",interval="15m",progress=False)
        df1h=yf.download(ticker,period="1mo",interval="1h",progress=False)
        df4h=yf.download(ticker,period="3mo",interval="4h",progress=False)
        if df15.empty or df1h.empty or df4h.empty:
            return None
        rsi=float(get_rsi(df15['Close']).iloc[-1])
        e1=float(df1h['Close'].ewm(50).mean().iloc[-1])
        p1=float(df1h['Close'].iloc[-1])
        e4=float(df4h['Close'].ewm(50).mean().iloc[-1])
        p4=float(df4h['Close'].iloc[-1])
        up=p1>e1 and p4>e4
        down=p1<e1 and p4<e4
        if rsi<30 and up:
            return "BUY"
        if rsi>70 and down:
            return "SELL"
    except:
        pass
    return None

send("🏦 *TRIPLE TF BOT LIVE*\nBot started!")

while True:
    try:
        for tk,name in SYMBOLS:
            sig=check(tk)
            if sig:
                try:
                    pr=yf.download(tk,period="1d",interval="15m",progress=False)['Close'].iloc[-1]
                except:
                    pr=0
                send(f"🚨 *{sig} SIGNAL* 🚨\nPair: {name}\nPrice: {pr:.2f}\nTime: {datetime.now().strftime('%H:%M')}")
                time.sleep(2)
        time.sleep(300)
    except Exception as e:
        print(e)
        time.sleep(60)
# --- INSTANT SIGNAL COMMAND ---
async def signal_command(update, context):
    await update.message.reply_text("🔍 Market check kar raha hun... 2 sec")
    
    # Yahan bot BTC ka instant analysis karega
    # Aapke wale triple TF function ko call karega
    result = await check_market_now()  # ye aapka analysis wala function hai
    
    await update.message.reply_text(f"📊 INSTANT UPDATE:\n\n{result}")

# Neeche jahan application.add_handler hai wahan ye bhi add karo:
application.add_handler(CommandHandler("signal", signal_command))
