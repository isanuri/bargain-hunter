import os, json, time, hashlib, logging, requests
from datetime import datetime

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
MAX_PRICE = 50
MIN_PROFIT_RATIO = 2.0
SEEN_FILE = "seen_ids.json"

SEARCH_KEYWORDS = [
    "vintage clothing", "retro electronics", "vinyl records",
    "job lot", "joblot", "bundle", "clearance", "wholesale"
]

RESALE_MULTIPLIERS = {
    "vintage": 4.0, "vinyl": 5.0, "retro": 3.5,
    "brand": 3.0, "electronics": 2.5, "clothing": 2.5,
    "toy": 2.0, "book": 1.5, "default": 2.0
}

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(message); return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        log.error(f"Telegram hatası: {e}")

def format_alert(item):
    profit_emoji = "🔥" if item.get("profit_ratio", 1) >= 3 else "💰"
    p = {"ebay":"🟡","gumtree":"🟢","facebook":"🔵","lost_property":"✈️","amazon_returns":"📦"}
    pe = p.get(item.get("platform",""), "🛒")
    lines = [
        f"{profit_emoji} <b>YENİ FIRSAT!</b>",
        f"{pe} Platform: <b>{item.get('platform','?').upper()}</b>",
        f"📌 <b>{item.get('title','')}</b>",
        f"💷 Fiyat: <b>£{item.get('price','?')}</b>",
    ]
    if item.get("estimated_resale"):
        lines.append(f"📈 Tahmini Satış: <b>£{item['estimated_resale']}</b>")
    if item.get("profit_ratio"):
        lines.append(f"🎯 Kar: <b>{item['profit_ratio']:.1f}x</b>")
    if item.get("location"):
        lines.append(f"📍 {item['location']}")
    if item.get("url"):
        lines.append(f'🔗 <a href="{item["url"]}">İlana Git →</a>')
    lines.append(f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    return "\n".join(lines)

def estimate_profit(item):
    title_lower = item.get("title", "").lower()
    multiplier = RESALE_MULTIPLIERS["default"]
    for keyword, mult in RESALE_MULTIPLIERS.items():
        if keyword in title_lower:
            multiplier = mult; break
    try:
        price = float(str(item.get("price","0")).replace("£","").replace(",","").strip())
        item["estimated_resale"] = round(price * multiplier, 2)
        item["profit_ratio"] = multiplier
        item["price"] = price
    except:
        item["profit_ratio"] = 1.0
    return item

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f: return set(json.load(f))
    return set()

def save_seen(seen):
    with open(SEEN_FILE, "w") as f: json.dump(list(seen), f)

def make_id(item):
    key = f"{item.get('platform')}_{item.get('url', item.get('title',''))}"
    return hashlib.md5(key.encode()).hexdigest()

def scrape_ebay():
    items = []
    for keyword in SEARCH_KEYWORDS[:5]:
        try:
            rss_url = f"https://www.ebay.co.uk/rss/buyersseller?keyword={keyword.replace(' ','%20')}&LH_BIN=1&LH_PrefLoc=1&_sop=15"
            r = requests.get(rss_url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
            import xml.etree.ElementTree as ET, re
            root = ET.fromstring(r.content)
            channel = root.find("channel")
            for i in (channel.findall("item") if channel else [])[:8]:
                title = i.findtext("title","")
                link = i.findtext("link","")
                desc = i.findtext("description","")
                m = re.search(r"£([\d,]+\.?\d*)", desc)
                price = float(m.group(1).replace(",","")) if m else 0
                if price and price <= MAX_PRICE:
                    items.append({"title":title,"price":price,"url":link,"platform":"ebay","location":"UK","condition":"Used"})
        except Exception as e:
            log.error(f"eBay hatası: {e}")
    return items

def scrape_gumtree():
    items = []
    import re
    from bs4 import BeautifulSoup
    for keyword in SEARCH_KEYWORDS[:3]:
        try:
            url = f"https://www.gumtree.com/search?search_category=all&q={keyword.replace(' ','+')}&max_price={MAX_PRICE}&sort=date"
            r = requests.get(url, headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            for listing in soup.find_all("article")[:8]:
                title_el = listing.find(["h2","h3","a"])
                title = title_el.get_text(strip=True) if title_el else ""
                if not title: continue
                link_el = listing.find("a", href=True)
                url2 = "https://www.gumtree.com" + link_el["href"] if link_el and link_el["href"].startswith("/") else ""
                price_el = listing.find(class_=re.compile(r"price",re.I))
                price_text = price_el.get_text(strip=True) if price_el else ""
                m = re.search(r"£?([\d,]+\.?\d*)", price_text)
                price = float(m.group(1).replace(",","")) if m else None
                if price is not None and price <= MAX_PRICE:
                    items.append({"title":title,"price":price,"url":url2,"platform":"gumtree","location":"UK","condition":"Used"})
        except Exception as e:
            log.error(f"Gumtree hatası: {e}")
    return items

def scrape_freecycle():
    items = []
    import xml.etree.ElementTree as ET
    for rss_url in ["https://groups.freecycle.org/group/LondonUK/rss","https://groups.freecycle.org/group/ManchesterUK/rss"]:
        try:
            r = requests.get(rss_url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
            root = ET.fromstring(r.content)
            channel = root.find("channel")
            for i in (channel.findall("item") if channel else [])[:5]:
                title = i.findtext("title","")
                link = i.findtext("link","")
                if "OFFER" in title.upper():
                    items.append({"title":f"🆓 [BEDAVA] {title}","price":0.0,"estimated_resale":15.0,"profit_ratio":999,"url":link,"platform":"facebook","location":"UK","condition":"Free"})
        except Exception as e:
            log.error(f"Freecycle hatası: {e}")
    return items

def scrape_lost_property():
    return [
        {"title":"✈️ Heathrow Lost Property Auction - Mixed Electronics","price":25.0,"estimated_resale":80.0,"url":"https://www.bidspotter.co.uk","platform":"lost_property","location":"Heathrow Airport","condition":"Lost Property"},
        {"title":"✈️ TfL Underground Lost Property - Clothing Bundle","price":0.0,"estimated_resale":30.0,"url":"https://www.tfl.gov.uk/travel-information/lost-property","platform":"lost_property","location":"London Underground","condition":"Lost Property"},
    ]

def scrape_amazon_returns():
    return [
        {"title":"📦 B-Stock Amazon UK - Returns Pallet","price":80.0,"estimated_resale":300.0,"url":"https://bstock.com/amazon/","platform":"amazon_returns","location":"UK Warehouse","condition":"Amazon Returns"},
        {"title":"📦 TopDown Trading - Fashion Returns Lot","price":30.0,"estimated_resale":120.0,"url":"https://www.topdowntrading.co.uk","platform":"amazon_returns","location":"UK","condition":"Grade A/B Returns"},
    ]

def run():
    log.info("🚀 Bargain Hunter başlatıldı...")
    seen = load_seen()
    all_items = []
    all_items.extend(scrape_ebay())
    all_items.extend(scrape_gumtree())
    all_items.extend(scrape_freecycle())
    all_items.extend(scrape_lost_property())
    all_items.extend(scrape_amazon_returns())

    new_count = 0
    for item in all_items:
        item = estimate_profit(item)
        item_id = make_id(item)
        if item_id in seen: continue
        price = item.get("price", 999)
        if isinstance(price, (int,float)) and price > MAX_PRICE: continue
        if item.get("profit_ratio", 1.0) < MIN_PROFIT_RATIO: continue
        send_telegram(format_alert(item))
        seen.add(item_id)
        new_count += 1
        time.sleep(1)

    save_seen(seen)
    log.info(f"✅ {new_count} yeni ilan bildirildi.")
    if new_count == 0:
        send_telegram("✅ Tarama tamamlandı. Şu an yeni uygun ilan bulunamadı.")

if __name__ == "__main__":
    run()
