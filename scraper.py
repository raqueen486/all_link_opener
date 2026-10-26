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

def decode_content(content: bytes, default_encoding: str = "utf-8") -> str:
    """바이트 데이터를 한글 깨짐 없이 디코딩 (UTF-8 및 CP949/EUC-KR 자동 판별)"""
    for enc in [default_encoding, "utf-8", "cp949", "euc-kr"]:
        try:
            return content.decode(enc)
        except Exception:
            continue
    return content.decode(default_encoding, errors="ignore")

def fetch_html(url: str, encoding: str = "utf-8") -> str:
    """직접 접속 시도 후 차단 시 글로벌 프록시 서버 순차 우회 (캐시 오염 방지 포함)"""
    proxies = [
        ("Direct", url),
        ("AllOrigins", f"https://api.allorigins.win/raw?url={urllib.parse.quote(url, safe='')}"),
        ("CorsProxy", f"https://corsproxy.io/?url={urllib.parse.quote(url, safe='')}"),
        ("Codetabs", f"https://api.codetabs.com/v1/proxy?quest={urllib.parse.quote(url, safe='')}")
    ]
    
    for name, target_url in proxies:
        try:
            res = requests.get(target_url, headers=HEADERS, timeout=15)
            if res.status_code == 200 and len(res.content) > 500:
                text = decode_content(res.content, encoding)
                # 클라우드플레어 및 봇 차단 페이지 필터링
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

def extract_links_from_post(html_text: str, content_selectors: list) -> list:
    """사이드바/인기글 허수를 막기 위해 지정된 '본문 및 댓글 영역' 내부에서만 적립 링크 추출"""
    if not html_text:
        return []
        
    soup = BeautifulSoup(html_text, "html.parser")
    
    # 불필요한 추천글/사이드바/푸터 영역 강제 제거
    for junk in soup.select("aside, footer, nav, .sidebar, .rank, .popular, .hot_list"):
        junk.decompose()

    target_chunks = []
    for sel in content_selectors:
        for el in soup.select(sel):
            target_chunks.append(str(el))
            target_chunks.append(el.get_text(" "))
            
    # 만약 선택자로 본문을 못 찾았을 때만 예외적으로 body 전체 사용
    raw_target = "\n".join(target_chunks) if target_chunks else str(soup.body or html_text)
    clean_html = raw_target.replace("&amp;", "&").replace("\\/", "/")
    
    pattern = r'https?://(?:campaign2\.naver\.com/npay/v2/click-point/\?[^\s"\'<>\\]+|ofw\.adison\.co/u/naverpay/ads/\d+|external-token\.pay\.naver\.com/entry/[^\s"\'<>\\]+)'
    
    raw_links = re.findall(pattern, clean_html)
    cleaned = []
    for link in raw_links:
        c_link = clean_npay_url(link)
        if c_link not in cleaned:
            cleaned.append(c_link)
    return cleaned

def is_npay_reward_title(title: str) -> bool:
    """일반 네이버 쇼핑 핫딜을 걸러내고 진짜 '적립/포인트/폐지' 글만 통과"""
    t = title.strip()
    # 쇼핑 핫딜 키워드가 있으면 즉시 제외
    if any(bad in t for bad in ["무료배송", "원)", "할인", "세일", "특가", "옥션", "지마켓", "11번가"]):
        return False
    # 핵심 키워드 조합 확인
    has_naver = any(k in t for k in ["네이버", "네페", "N페이", "폐지"])
    has_reward = any(k in t for k in ["적립", "포인트", "클릭", "줍기", "일일", "모음", "받아가세요"])
    return (has_naver and has_reward) or ("일일적립" in t) or ("클릭적립" in t) or ("클릭 적립" in t)

def scrape_clien() -> list:
    """1. 클리앙 알뜰구매 '네이버페이' 검색 결과 최신글 2개 스캔"""
    print("\n--- [1. 클리앙 스캔 시작] ---")
    links = []
    # 클리앙은 UTF-8 검색이 완벽 작동하며 Direct 접속이 가능함
    search_urls = [
        "https://www.clien.net/service/board/jirum?sk=title&sv=%EB%84%A4%EC%9D%B4%EB%B2%84%ED%8E%98%EC%9D%B4",
        "https://www.clien.net/service/board/jirum?sk=title&sv=%EC%A0%81%EB%A6%BD"
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
            if not href or not is_npay_reward_title(title):
                continue
                
            post_url = ("https://www.clien.net" + href if href.startswith("/") else href).split("?")[0]
            if post_url in checked_urls:
                continue
            checked_urls.add(post_url)
            
            print(f"👉 [클리앙 글 발견] {title} ({post_url})")
            post_html = fetch_html(post_url, "utf-8")
            # 클리앙 본문(.post_article)과 댓글(.post_comment)만 타겟팅
            extracted = extract_links_from_post(post_html, [".post_article", ".post_content", ".post_comment"])
            print(f"   ↳ 추출된 링크: {len(extracted)}개")
            
            for l in extracted:
                if l not in links:
                    links.append(l)
            if len(checked_urls) >= 2:
                return links
    return links

def scrape_etoland() -> list:
    """2. 이토랜드 핫딜 게시판 상세글(/b/hotdeal/view/) 중 최신 적립글 2개 스캔"""
    print("\n--- [2. 이토랜드 스캔 시작] ---")
    links = []
    # 이토랜드 모바일/PC 핫딜 목록
    list_urls = [
        "https://m.etoland.co.kr/b/hotdeal",
        "https://etoland.co.kr/b/hotdeal"
    ]
    
    checked_urls = set()
    for list_url in list_urls:
        html = fetch_html(list_url, "utf-8")
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        
        # 반드시 상세 게시글(/b/hotdeal/view/) 링크만 선택 (검색 목록 URL 배제)
        for a in soup.select("a[href*='/b/hotdeal/view/']"):
            # 제목 텍스트만 깔끔하게 추출 (댓글수 등 부가 정보 제외를 위해)
            title = a.get_text(" ", strip=True)
            href = a.get("href", "")
            if not title or not is_npay_reward_title(title):
                continue
                
            post_url = ("https://etoland.co.kr" + href if href.startswith("/") else href).split("?")[0]
            if post_url in checked_urls:
                continue
            checked_urls.add(post_url)
            
            print(f"👉 [이토랜드 글 발견] {title[:40]}... ({post_url})")
            post_html = fetch_html(post_url, "utf-8")
            # 이토랜드 본문(#bo_v_con, .view_content)과 댓글(#bo_vc, .comment_list)만 타겟팅
            extracted = extract_links_from_post(post_html, ["#bo_v_con", ".view_content", ".board_contents", "#bo_vc", ".comment_area"])
            print(f"   ↳ 추출된 링크: {len(extracted)}개")
            
            for l in extracted:
                if l not in links:
                    links.append(l)
            if len(checked_urls) >= 2:
                return links
    return links

def scrape_ppomppu() -> list:
    """3. 뽐뿌 모바일 쿠폰/이벤트 게시판 스캔 (타임아웃 및 인코딩 문제 해결)"""
    print("\n--- [3. 뽐뿌 모바일 스캔 시작] ---")
    links = []
    # 가볍고 빠른 모바일 게시판 1~2페이지 스캔
    board_urls = [
        "https://m.ppomppu.co.kr/new/bbs_list.php?id=coupon",
        "https://m.ppomppu.co.kr/new/bbs_list.php?id=event",
        "https://www.ppomppu.co.kr/zboard/zboard.php?id=coupon"
    ]
    
    checked_urls = set()
    for list_url in board_urls:
        enc = "cp949"
        html = fetch_html(list_url, enc)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        
        for a in soup.select("a[href*='bbs_view.php'], a[href*='view.php']"):
            title = a.get_text(" ", strip=True)
            href = a.get("href", "")
            if not title or not is_npay_reward_title(title):
                continue
                
            if "m.ppomppu.co.kr" in list_url:
                post_url = "https://m.ppomppu.co.kr/new/" + href.lstrip("./") if not href.startswith("http") else href
            else:
                post_url = "https://www.ppomppu.co.kr/zboard/" + href.lstrip("./") if not href.startswith("http") else href
                
            if post_url in checked_urls:
                continue
            checked_urls.add(post_url)
            
            print(f"👉 [뽐뿌 글 발견] {title} ({post_url})")
            post_html = fetch_html(post_url, enc)
            # 뽐뿌 모바일(.cont, #bbs_view_content) 및 PC(.board-contents) 본문만 타겟팅
            extracted = extract_links_from_post(post_html, [".cont", "#bbs_view_content", ".board-contents", "td.board-contents", ".comment_wrapper"])
            print(f"   ↳ 추출된 링크: {len(extracted)}개")
            
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

    print(f"\n==========================================")
    print(f"✅ 총 {len(final_links)}개 링크 저장 완료! (신규 추출: {len(all_dynamic)}개 + 고정 6개)")
    print(f"==========================================")
