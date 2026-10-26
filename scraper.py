import re
import json
import urllib.parse
from datetime import datetime, timedelta, timezone
import requests
from bs4 import BeautifulSoup

# 한국 시간(KST) 기준 오늘/어제 날짜 패턴 생성
KST = timezone(timedelta(hours=9))
now_kst = datetime.now(KST)
yesterday_kst = now_kst - timedelta(days=1)

# 제목에서 오늘/어제 글인지 판별할 날짜 문자열들 (예: 10/27, 10.27, 10월 27일, 27일, 261027)
VALID_DATE_TOKENS = []
for dt in (now_kst, yesterday_kst):
    m, d = dt.month, dt.day
    VALID_DATE_TOKENS.extend([
        f"{m}/{d}", f"{m:02d}/{d:02d}",
        f"{m}.{d}", f"{m:02d}.{d:02d}",
        f"{m}-{d}", f"{m:02d}-{d:02d}",
        f"{m}월 {d}일", f"{m}월{d}일",
        f"{d}일", dt.strftime("%y%m%d")
    ])

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

def decode_content(content: bytes, default_encoding: str = "utf-8") -> str:
    for enc in [default_encoding, "utf-8", "cp949", "euc-kr"]:
        try:
            return content.decode(enc)
        except Exception:
            continue
    return content.decode(default_encoding, errors="ignore")

def fetch_html(url: str, encoding: str = "utf-8") -> str:
    # 캐시 오염이 심한 Codetabs를 제외하고 직접 접속 및 신뢰도 높은 프록시만 사용
    proxies = [
        ("Direct", url),
        ("AllOrigins", f"https://api.allorigins.win/raw?url={urllib.parse.quote(url, safe='')}"),
        ("CorsProxy", f"https://corsproxy.io/?url={urllib.parse.quote(url, safe='')}")
    ]
    
    for name, target_url in proxies:
        try:
            res = requests.get(target_url, headers=HEADERS, timeout=15)
            if res.status_code == 200 and len(res.content) > 500:
                text = decode_content(res.content, encoding)
                if "Just a moment..." not in text and "Attention Required!" not in text:
                    return text
        except Exception as e:
            print(f"  [{name} 실패] {url} -> {e}")
            
    print(f"❌ [최종 접속 실패] {url}")
    return ""

def clean_npay_url(url: str) -> str:
    url = url.strip().replace("&amp;", "&")
    url = re.sub(r'[.,;)\'"\]>\\]+$', '', url)
    
    if "campaign2.naver.com/npay/v2/click-point" in url:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        if "eventId" in qs:
            return f"https://campaign2.naver.com/npay/v2/click-point/?eventId={qs['eventId'][0]}"
    return url

def extract_links_from_post(html_text: str, content_selectors: list) -> list:
    if not html_text:
        return []
        
    soup = BeautifulSoup(html_text, "html.parser")
    
    # 사이드바, 인기글, 추천글, 목록 테이블 등 본문 외 영역 강력 제거
    for junk in soup.select("aside, footer, nav, header, .sidebar, .rank, .popular, .hot_list, #bo_v_other, .List_table"):
        junk.decompose()

    target_chunks = []
    for sel in content_selectors:
        for el in soup.select(sel):
            target_chunks.append(str(el))
            target_chunks.append(el.get_text(" "))
            
    # 본문 영역을 전혀 못 찾았으면 오염 방지를 위해 빈 리스트 반환 (절대 body 전체를 긁지 않음)
    if not target_chunks:
        print("   ⚠️ 본문 영역 선택자 매칭 실패 (오염 방지를 위해 스킵)")
        return []

    clean_html = "\n".join(target_chunks).replace("&amp;", "&").replace("\\/", "/")
    
    pattern = r'https?://(?:campaign2\.naver\.com/npay/v2/click-point/\?[^\s"\'<>\\]+|ofw\.adison\.co/u/naverpay/ads/\d+|external-token\.pay\.naver\.com/entry/[^\s"\'<>\\]+)'
    
    raw_links = re.findall(pattern, clean_html)
    cleaned = []
    for link in raw_links:
        c_link = clean_npay_url(link)
        if c_link not in cleaned:
            cleaned.append(c_link)
            
    # 안전장치: 한 게시글에서 30개 이상 나오면 옛날 누적 모음글이거나 페이지 오염이므로 폐기
    if len(cleaned) >= 30:
        print(f"   ⚠️ 비정상 과다 링크({len(cleaned)}개) 감지 -> 누적 모음글/위젯 오염으로 판단하여 제외")
        return []
        
    return cleaned

def is_today_npay_title(title: str, require_date: bool = False) -> bool:
    """진짜 오늘/어제 올라온 네이버페이 적립글인지 엄격 판별"""
    t = title.strip()
    if any(bad in t for bad in ["무료배송", "원)", "할인", "세일", "특가", "옥션", "지마켓", "11번가", "멤버쉽", "멤버십", "페이왕"]):
        return False
        
    has_naver = any(k in t for k in ["네이버", "네페", "N페이", "폐지"])
    has_reward = any(k in t for k in ["적립", "포인트", "클릭", "줍기", "일일", "모음"])
    
    if not ((has_naver and has_reward) or "일일적립" in t or "클릭적립" in t or "클릭 적립" in t):
        return False
        
    # 이토랜드처럼 옛날 종합글이 섞이는 곳은 제목에 오늘/어제 날짜(예: 10/27, 27일)가 있는지 확인
    if require_date:
        if not any(dt_token in t for dt_token in VALID_DATE_TOKENS):
            return False
            
    return True

def scrape_clien() -> list:
    print("\n--- [1. 클리앙 스캔 시작] ---")
    links = []
    search_urls = [
        "https://www.clien.net/service/board/jirum?sk=title&sv=%EB%84%A4%EC%9D%B4%EB%B2%84%ED%8E%98%EC%9D%B4",
        "https://www.clien.net/service/board/jirum?sk=title&sv=%EC%9D%BC%EC%9D%BC%EC%A0%81%EB%A6%BD"
    ]
    
    checked_urls = set()
    for list_url in search_urls:
        html = fetch_html(list_url, "utf-8")
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        
        for a in soup.select("a.list_subject, span.list_subject a"):
            title = a.get_text(" ", strip=True)
            href = a.get("href", "")
            if not href or not is_today_npay_title(title, require_date=False):
                continue
                
            post_url = ("https://www.clien.net" + href if href.startswith("/") else href).split("?")[0]
            if post_url in checked_urls:
                continue
            checked_urls.add(post_url)
            
            print(f"👉 [클리앙 글 발견] {title} ({post_url})")
            post_html = fetch_html(post_url, "utf-8")
            extracted = extract_links_from_post(post_html, [".post_article", ".post_content", ".post_comment"])
            print(f"   ↳ 추출된 정상 링크: {len(extracted)}개")
            
            for l in extracted:
                if l not in links:
                    links.append(l)
            if len(checked_urls) >= 2:
                return links
    return links

def scrape_etoland() -> list:
    print("\n--- [2. 이토랜드 스캔 시작] ---")
    links = []
    # 이토랜드 '일일적립' 제목 검색 URL 직접 타겟팅
    list_urls = [
        "https://etoland.co.kr/b/hotdeal?sfl=wr_subject&stx=%EC%9D%BC%EC%9D%BC%EC%A0%81%EB%A6%BD",
        "https://etoland.co.kr/b/hotdeal"
    ]
    
    checked_urls = set()
    for list_url in list_urls:
        html = fetch_html(list_url, "utf-8")
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        
        for a in soup.select("a[href*='/b/hotdeal/view/']"):
            title = a.get_text(" ", strip=True)
            href = a.get("href", "")
            # 이토랜드는 옛날 정보글(52개짜리) 방지를 위해 제목 조건 엄격 적용
            if not title or not is_today_npay_title(title, require_date=False):
                continue
            if "받아가세요" in title:  # 52개짜리 옛날 누적글 제외
                continue
                
            post_url = ("https://etoland.co.kr" + href if href.startswith("/") else href).split("?")[0]
            if post_url in checked_urls:
                continue
            checked_urls.add(post_url)
            
            print(f"👉 [이토랜드 글 발견] {title[:45]} ({post_url})")
            post_html = fetch_html(post_url, "utf-8")
            extracted = extract_links_from_post(
                post_html, 
                ["#bo_v_con", ".view_content", ".board_contents", "article", "#bo_vc"]
            )
            print(f"   ↳ 추출된 정상 링크: {len(extracted)}개")
            
            for l in extracted:
                if l not in links:
                    links.append(l)
            if len(checked_urls) >= 2:
                return links
    return links

def scrape_ppomppu() -> list:
    print("\n--- [3. 뽐뿌 모바일 스캔 시작] ---")
    links = []
    board_urls = [
        "https://m.ppomppu.co.kr/new/bbs_list.php?id=coupon",
        "https://m.ppomppu.co.kr/new/bbs_list.php?id=event"
    ]
    
    checked_urls = set()
    for list_url in board_urls:
        html = fetch_html(list_url, "cp949")
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        
        for a in soup.select("a[href*='bbs_view.php']"):
            title = a.get_text(" ", strip=True)
            href = a.get("href", "")
            if not title or not is_today_npay_title(title, require_date=False):
                continue
                
            post_url = "https://m.ppomppu.co.kr/new/" + href.lstrip("./") if not href.startswith("http") else href
            if post_url in checked_urls:
                continue
            checked_urls.add(post_url)
            
            print(f"👉 [뽐뿌 글 발견] {title} ({post_url})")
            post_html = fetch_html(post_url, "cp949")
            extracted = extract_links_from_post(
                post_html, 
                [".cont", "#bbs_view_content", ".view_content", ".bbs_view", ".comment_wrapper"]
            )
            print(f"   ↳ 추출된 정상 링크: {len(extracted)}개")
            
            for l in extracted:
                if l not in links:
                    links.append(l)
            if len(checked_urls) >= 2:
                return links
    return links

if __name__ == "__main__":
    all_dynamic = []
    
    for func in (scrape_clien, scrape_etoland, scrape_ppomppu):
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

    print("\n==========================================")
    print(f"✅ 총 {len(final_links)}개 링크 저장 완료! (신규 추출: {len(all_dynamic)}개 + 고정 6개)")
    print("==========================================")
