import os,time,requests,yfinance as yf
from datetime import datetime
BOT_TOKEN=os.getenv("BOT_TOKEN")
CHAT_ID=os.getenv("CHAT_ID")
SYMBOLS={"GOLD":"GC=F","BTC":"BTC-USD","EURUSD":"EURUSD=X"}
def get_rsi(d,p=14):
 delta=d['Close'].diff()
 gain=(delta.where(delta>0,0)).rolling(p).mean()
 loss=(-delta.where(delta<0,0)).rolling(p).mean()
 rs=gain/loss
 return 100-(100/(1+rs))
def get_signal(n,t):
 try:
  df=yf.download(t,period="2d",interval="15m",progress=False,auto_adjust=True)
  df['EMA21']=df['Close'].ewm(span=21).mean()
  df['RSI']=get_rsi(df)
  l=df.iloc[-1]
  price=float(l['Close']);rsi=float(l['RSI']);ema=float(l['EMA21'])
  sig="WAIT";conf=5;emo="⚪"
  if rsi<35 and price>ema:sig="BUY";conf=9;emo="🟢"
  elif rsi>65 and price<ema:sig="SELL";conf=9;emo="🔴"
  if conf<7:sig="WAIT";emo="⚪"
  sl=price-10 if sig=="BUY" else price+10
  tp1=price+15 if sig=="BUY" else price-15
  tp2=price+30 if sig=="BUY" else price-30
  return f"{emo} {n} {sig} @ {price:.2f}\nSL:{sl:.2f} TP1:{tp1:.2f} TP2:{tp2:.2f}\nConf:{conf}/10 RSI:{rsi:.1f}"
 except: return f"⚪ {n} WAIT"
def send(m):
 if not BOT_TOKEN or not CHAT_ID: return
 requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",json={"chat_id":CHAT_ID,"text":m,"parse_mode":"Markdown"})
while True:
 sigs=[get_signal(n,t) for n,t in SYMBOLS.items()]
 now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
 final=f"📊 *ALL SIGNALS - BANKING GRADE*\n⏱️ M15 | {now}\n\n"+"\n\n".join(sigs)
 send(final)
 time.sleep(900)
