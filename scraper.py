import re
import json
import urllib.parse
from datetime import datetime, timedelta, timezone
import requests
from bs4 import BeautifulSoup

# 한국 시간(KST) 설정
KST = timezone(timedelta(hours=9))
now_kst = datetime.now(KST)

# 365일 고정 일일적립 링크
FIXED_LINKS = [
    "https://home.pay.naver.com",
    "https://new-m.pay.naver.com/historybenefit/home",
    "https://point.pay.naver.com/pc/main?category=quickreward",
    "https://insurance.pay.naver.com/?inflow=point_category",
    "https://campaign2.naver.com/npay/branddraw/?from=pointtab",
    "https://mycar.naver.com/"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
}

# 게시글 제목 필터링 키워드
KEYWORDS = ["네이버", "네페", "일일적립", "클릭", "적립", "폐지", "포인트"]

def decode_content(content: bytes, default_encoding: str = "utf-8") -> str:
    """바이트 데이터를 한글 깨짐 없이 디코딩 (UTF-8 및 EUC-KR/CP949 자동 대응)"""
    encodings = [default_encoding, "utf-8", "cp949", "euc-kr"]
    for enc in encodings:
        try:
            return content.decode(enc)
        except Exception:
            continue
    return content.decode(default_encoding, errors="ignore")

def fetch_html(url: str, encoding: str = "utf-8") -> str:
    """직접 접속 후 차단 시 3개의 프록시 서버로 자동 우회"""
    proxies = [
        ("Direct", url),
        ("Codetabs", f"https://api.codetabs.com/v1/proxy?quest={urllib.parse.quote(url, safe='')}"),
        ("AllOrigins", f"https://api.allorigins.win/raw?url={urllib.parse.quote(url, safe='')}"),
        ("CorsProxy", f"https://corsproxy.io/?{urllib.parse.quote(url, safe='')}")
    ]
    
    for name, target_url in proxies:
        try:
            res = requests.get(target_url, headers=HEADERS, timeout=12)
            if res.status_code == 200 and len(res.content) > 500:
                text = decode_content(res.content, encoding)
                # 클라우드플레어 차단 페이지가 아닌 정상 페이지인지 확인
                if "Just a moment..." not in text and "Attention Required!" not in text:
                    return text
        except Exception as e:
            print(f"  [{name} 실패] {url} -> {e}")
            
    print(f"❌ [최종 접속 실패] {url}")
    return ""

def clean_npay_url(url: str) -> str:
    """개인 트래킹 코드(request_id 등) 제거 및 URL 표준화"""
    url = url.strip().replace("&amp;", "&")
    url = re.sub(r'[.,;)\'"\]>\\]+$', '', url)
    
    if "campaign2.naver.com/npay/v2/click-point" in url:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        if "eventId" in qs:
            return f"https://campaign2.naver.com/npay/v2/click-point/?eventId={qs['eventId'][0]}"
    return url

def extract_links(html_text: str) -> list:
    """HTML 원문 및 텍스트에서 네이버페이 관련 적립 링크를 모두 추출 (날짜 강제 삭제 없음)"""
    if not html_text:
        return []
    
    # HTML 엔티티 및 이스케이프 문자 정리
    clean_html = html_text.replace("&amp;", "&").replace("\\/", "/")
    
    # 네이버페이 클릭포인트, 애디슨 오퍼월, 외부 토큰(핀크럭스 등) 정규식
    pattern = r'https?://(?:campaign2\.naver\.com/npay/v2/click-point/\?[^\s"\'<>\\]+|ofw\.adison\.co/u/naverpay/ads/\d+|external-token\.pay\.naver\.com/entry/[^\s"\'<>\\]+)'
    
    raw_links = re.findall(pattern, clean_html)
    cleaned = []
    for link in raw_links:
        c_link = clean_npay_url(link)
        if c_link not in cleaned:
            cleaned.append(c_link)
    return cleaned

def is_target_title(title: str) -> bool:
    """제목에 네이버페이/적립 관련 키워드가 있는지 확인"""
    title_clean = title.strip()
    if any(k in title_clean for k in ["네이버", "네페", "일일적립", "폐지"]):
        return True
    if "클릭" in title_clean and "적립" in title_clean:
        return True
    return False

def scrape_clien() -> list:
    """1. 클리앙 알뜰구매 게시판 1~2페이지 스캔"""
    print("\n--- [1. 클리앙 스캔 시작] ---")
    links = []
    posts_checked = 0
    
    for page in range(0, 2):
        list_url = f"https://www.clien.net/service/board/jirum?&od=T31&category=0&po={page}"
        html = fetch_html(list_url, "utf-8")
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        
        for a in soup.select("a.list_subject, span.list_subject a"):
            title = a.get_text(" ", strip=True)
            href = a.get("href", "")
            if not href or not is_target_title(title):
                continue
                
            post_url = "https://www.clien.net" + href if href.startswith("/") else href
            print(f"👉 [클리앙 글 발견] {title} ({post_url})")
            post_html = fetch_html(post_url, "utf-8")
            extracted = extract_links(post_html)
            print(f"   ↳ 추출된 링크: {len(extracted)}개")
            
            for l in extracted:
                if l not in links:
                    links.append(l)
            posts_checked += 1
            if posts_checked >= 4:
                return links
    return links

def scrape_ppomppu() -> list:
    """2. 뽐뿌 쿠폰 및 이벤트 게시판 스캔 (인코딩 깨짐 방지용 직접 목록 스캔)"""
    print("\n--- [2. 뽐뿌 스캔 시작] ---")
    links = []
    posts_checked = 0
    
    board_urls = [
        "https://www.ppomppu.co.kr/zboard/zboard.php?id=coupon",
        "https://www.ppomppu.co.kr/zboard/zboard.php?id=event"
    ]
    
    for list_url in board_urls:
        html = fetch_html(list_url, "cp949")
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        
        for a in soup.select("a[href*='view.php?id=']"):
            title = a.get_text(" ", strip=True)
            href = a.get("href", "")
            if not title or not is_target_title(title):
                continue
                
            post_url = "https://www.ppomppu.co.kr/zboard/" + href.lstrip("./") if not href.startswith("http") else href
            print(f"👉 [뽐뿌 글 발견] {title} ({post_url})")
            post_html = fetch_html(post_url, "cp949")
            extracted = extract_links(post_html)
            print(f"   ↳ 추출된 링크: {len(extracted)}개")
            
            for l in extracted:
                if l not in links:
                    links.append(l)
            posts_checked += 1
            if posts_checked >= 4:
                return links
    return links

def scrape_etoland() -> list:
    """3. 이토랜드 핫딜 게시판 스캔"""
    print("\n--- [3. 이토랜드 스캔 시작] ---")
    links = []
    posts_checked = 0
    
    list_urls = [
        "https://etoland.co.kr/b/hotdeal",
        "https://m.etoland.co.kr/b/hotdeal"
    ]
    
    for list_url in list_urls:
        html = fetch_html(list_url, "utf-8")
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        
        for a in soup.select("a[href*='/b/hotdeal/'], a[href*='bbs/board.php']"):
            title = a.get_text(" ", strip=True)
            href = a.get("href", "")
            if not title or not is_target_title(title):
                continue
                
            post_url = "https://etoland.co.kr" + href if href.startswith("/") else href
            print(f"👉 [이토랜드 글 발견] {title} ({post_url})")
            post_html = fetch_html(post_url, "utf-8")
            extracted = extract_links(post_html)
            print(f"   ↳ 추출된 링크: {len(extracted)}개")
            
            for l in extracted:
                if l not in links:
                    links.append(l)
            posts_checked += 1
            if posts_checked >= 3:
                return links
        if posts_checked > 0:
            break
    return links

if __name__ == "__main__":
    all_dynamic = []
    
    for func in (scrape_clien, scrape_ppomppu, scrape_etoland):
        try:
            found = func()
            for link in found:
                if link not in all_dynamic:
                    all_dynamic.append(link)
        except Exception as e:
            print(f"오류 무시하고 다음 사이트 진행: {e}")

    final_links = all_dynamic + [f for f in FIXED_LINKS if f not in all_dynamic]

    data = {
        "updated_at": now_kst.strftime("%Y-%m-%d %H:%M:%S"),
        "dynamic_count": len(all_dynamic),
        "total_count": len(final_links),
        "links": final_links
    }

    with open("daily_links.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n==========================================")
    print(f"✅ 총 {len(final_links)}개 링크 저장 완료! (신규 추출: {len(all_dynamic)}개 + 고정 6개)")
    print(f"==========================================")
