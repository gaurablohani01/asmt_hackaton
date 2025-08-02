import requests
import os
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

CACHE_FILE = os.path.join(os.path.dirname(__file__), 'nepse_stocks_cache.json')
CACHE_TTL_MINUTES = 60

def fetch_nepse_stocks_and_ltp():
    """
    Fetch all NEPSE stocks and their latest LTP using NepseAPI-Unofficial (PriceVolume endpoint only).
    Returns a list of dicts: [{ 'symbol': 'NABIL', 'companyName': 'Nabil Bank Limited', 'ltp': 500 }, ...]
    Uses local cache if API is down.
    """
    url_price_volume = "https://nepseapi.surajrimal.dev/PriceVolume"
    try:
        resp_pv = requests.get(url_price_volume, timeout=10)
        resp_pv.raise_for_status()
        pv_data = resp_pv.json()
        stocks = []
        for pv in pv_data:
            symbol = pv.get('symbol')
            today_loss = None
            today_gain = None
            try:
                prev_close = float(pv.get('previousClose', 0))
                last_traded = float(pv.get('lastTradedPrice', 0))
                diff = last_traded - prev_close
                if diff < 0:
                    today_loss = diff
                elif diff > 0:
                    today_gain = diff
            except Exception:
                pass
            stocks.append({
                'symbol': symbol,
                'companyName': pv.get('securityName') or pv.get('companyName'),
                'ltp': pv.get('lastTradedPrice'),
                'change': pv.get('lastTradedPrice', 0) - pv.get('previousClose', 0) if pv.get('lastTradedPrice') and pv.get('previousClose') else None,
                'changePercent': pv.get('percentageChange'),
                'previousClose': pv.get('previousClose'),
                'close': pv.get('closePrice'),
                'volume': pv.get('totalTradeQuantity'),
                'today_loss': today_loss,
                'today_gain': today_gain,
            })
        try:
            with open(CACHE_FILE, 'w') as f:
                json.dump({'timestamp': datetime.now().isoformat(), 'stocks': stocks}, f)
        except Exception as cache_err:
            logger.warning(f"Could not write NEPSE cache: {cache_err}")
        return stocks
    except Exception as e:
        print(f"[NEPSE API] Error: {e}")
        logger.error(f"NepseAPI fetch error: {e}")
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r') as f:
                    cache = json.load(f)
                ts = datetime.fromisoformat(cache.get('timestamp', '1970-01-01T00:00:00'))
                if datetime.now() - ts < timedelta(minutes=CACHE_TTL_MINUTES):
                    logger.info("Using cached NEPSE stocks data.")
                    print(f"[NEPSE API] Using cached stocks: {len(cache.get('stocks', []))} entries.")
                    return cache.get('stocks', [])
            except Exception as cache_err:
                print(f"[NEPSE API] Cache read error: {cache_err}")
                logger.warning(f"Could not read NEPSE cache: {cache_err}")
        print("[NEPSE API] No stocks available from API or cache.")
        return []
        try:
            with open(CACHE_FILE, 'w') as f:
                json.dump({'timestamp': datetime.now().isoformat(), 'stocks': stocks}, f)
        except Exception as cache_err:
            logger.warning(f"Could not write NEPSE cache: {cache_err}")
        return stocks
    except Exception as e:
        logger.error(f"NepseAPI fetch error: {e}")
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r') as f:
                    cache = json.load(f)
                ts = datetime.fromisoformat(cache.get('timestamp', '1970-01-01T00:00:00'))
                if datetime.now() - ts < timedelta(minutes=CACHE_TTL_MINUTES):
                    logger.info("Using cached NEPSE stocks data.")
                    return cache.get('stocks', [])
            except Exception as cache_err:
                logger.warning(f"Could not read NEPSE cache: {cache_err}")
        return []
