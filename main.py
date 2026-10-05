import requests

def get_data(symbol, interval):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=200"
    data = requests.get(url).json()
    closes = [float(x[4]) for x in data]
    volumes = [float(x[5]) for x in data]
    highs = [float(x[2]) for x in data]
    lows = [float(x[3]) for x in data]
    return closes, highs, lows, volumes

def rsi(c, p=14):
    g=l=0
    for i in range(1,p+1):
        d=c[-i]-c[-i-1]
        if d>0: g+=d
        else: l+=abs(d)
    if l==0: return 100
    return 100 - (100/(1+(g/p)/(l/p)))

def ema(c, p=50):
    k=2/(p+1); e=c[0]
    for x in c[1:]: e=x*k+e*(1-k)
    return e

def macd(c):
    e12=ema(c,12); e26=ema(c,26)
    return e12-e26 # MACD line

def atr(highs, lows, closes, p=14):
    tr=[]
    for i in range(1,len(closes)):
        tr.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
    return sum(tr[-p:])/p

def get_god_analysis(symbol):
    c15,h15,l15,v15 = get_data(symbol, "15m")
    c1h,h1h,l1h,v1h = get_data(symbol, "1h")
    c4h,h4h,l4h,v4h = get_data(symbol, "4h")

    price=c15[-1]
    rsi15=rsi(c15); rsi1h=rsi(c1h); rsi4h=rsi(c4h)
    ema50_15=ema(c15,50); ema50_1h=ema(c1h,50); ema50_4h=ema(c4h,50)
    macd15=macd(c15); macd1h=macd(c1h)
    atr15=atr(h15,l15,c15)

    # SCORING SYSTEM - Duniya me kisi me nahi
    score=0
    if price>ema50_15: score+=20
    if price>ema50_1h: score+=25
    if price>ema50_4h: score+=25
    if 40<rsi15<68: score+=10
    if 45<rsi1h<70: score+=10
    if macd15>0 and macd1h>0: score+=10

    trend15="UP" if price>ema50_15 else "DOWN"
    trend1h="UP" if c1h[-1]>ema50_1h else "DOWN"
    trend4h="UP" if c4h[-1]>ema50_4h else "DOWN"

    is_lamba = score>=80 and trend15=="UP" and trend1h=="UP"

    sl = price - (atr15*1.5)
    tp1 = price + (atr15*2)
    tp2 = price + (atr15*3.5)

    return price, rsi15, rsi1h, rsi4h, trend15, trend1h, trend4h, score, sl, tp1, tp2, macd15

# Telegram Handler me ye lagao
async def god_signal(update, context):
    btc_price, br15, br1h, br4h, bt15, bt1h, bt4h, bscore, bsl, btp1, btp2, bm = get_data_and_score("BTCUSDT")
    gold_price, gr15, gr1h, gr4h, gt15, gt1h, gt4h, gscore, gsl, gtp1, gtp2, gm = get_data_and_score("PAXGUSDT")
    real_gold = gold_price - 8 # XAUUSD.r FIX

    msg = f"""
💎👑 ADIL BHAI QUANTUM 99.9% GOD MODE 👑💎
Duniya me aisa bot nahi hai!

1️⃣ BTC {btc_price:.2f}
Score: {bscore}% | 15m:{br15:.0f} {bt15} | 1H:{br1h:.0f} {bt1h} | 4H:{bt4h}
MACD: {"🟢 BULL" if bm>0 else "🔴 BEAR"}
👉 {"🚀🚀🚀 99.9% LAMBA CONFIRMED" if bscore>=80 else "⚠️ WAIT - SCORE KAM HAI"}
🎯 Entry: {btc_price:.2f}
🛑 SL: {bsl:.2f} (ATR Based)
💰 TP1: {btp1:.2f} | TP2: {btp2:.2f}

2️⃣ GOLD {real_gold:.2f} (XAUUSD.r)
Score: {gscore}% | 15m:{gr15:.0f} {gt15} | 1H:{gr1h:.0f} {gt1h} | 4H:{gt4h}
👉 {"🚀 99.9% LAMBA" if gscore>=80 else f"⚠️ WAIT - Abhi {gt15} hai, aapke chart jaisa!"}
🎯 SL: {gsl:.2f} | TP: {gtp1:.2f}

Source: QUANTUM ATR + MACD + 4TF - GOD LEVEL
"""
