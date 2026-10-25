import re
import json
import urllib.parse
from datetime import datetime, timedelta, timezone
import requests
from bs4 import BeautifulSoup

# 한국 시간(KST) 기준 오늘/어제 날짜 계산 (오래된 링크 필터링용)
KST = timezone(timedelta(hours=9))
now_kst = datetime.now(KST)
TODAY_STR = now_kst.strftime("%y%m%d")
YESTERDAY_STR = (now_kst - timedelta(days=1)).strftime("%y%m%d")

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
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
}

def fetch_html(url: str, encoding: str = "utf-8") -> str:
    """직접 접속 시도 후 해외 IP 차단 시 프록시로 자동 우회"""
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200 and len(res.text) > 500:
            res.encoding = encoding
            return res.text
    except Exception:
        pass

    # 해외 IP 차단 시 AllOrigins 우회 호출
    try:
        proxy_url = f"https://api.allorigins.win/raw?url={urllib.parse.quote(url)}"
        res = requests.get(proxy_url, timeout=15)
        if res.status_code == 200:
            res.encoding = encoding
            return res.text
    except Exception as e:
        print(f"[접속 실패] {url}: {e}")
    return ""

def clean_npay_url(url: str) -> str:
    """개인 트래킹 코드(request_id 등) 제거 및 표준화"""
    url = url.strip().replace("&amp;", "&")
    url = re.sub(r'[.,;)\'"\]>\\]+$', '', url)
    if "campaign2.naver.com/npay/v2/click-point" in url:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        if "eventId" in qs:
            return f"https://campaign2.naver.com/npay/v2/click-point/?eventId={qs['eventId'][0]}"
    return url

def extract_links(html_text: str) -> list:
    """본문과 댓글에서 네이버페이 적립 URL 추출"""
    pattern = r'https?://(?:campaign2\.naver\.com/npay/v2/click-point/\?[^\s"\'<>\\]+|ofw\.adison\.co/u/naverpay/ads/\d+|external-token\.pay\.naver\.com/entry/[^\s"\'<>\\]+)'
    raw_links = re.findall(pattern, html_text)
    cleaned = []
    for link in raw_links:
        c_link = clean_npay_url(link)
        # 날짜(26xxxx)가 박힌 링크 중 이틀 이상 지난 옛날 링크는 제외
        date_match = re.search(r'_(26\d{4})', c_link)
        if date_match and date_match.group(1) not in (TODAY_STR, YESTERDAY_STR):
            continue
        if c_link not in cleaned:
            cleaned.append(c_link)
    return cleaned

def scrape_clien() -> list:
    """1. 클리앙 알뜰구매 최신글 3개 스캔"""
    links = []
    list_url = "https://www.clien.net/service/board/jirum?sk=title&sv=%EB%84%A4%EC%9D%B4%EB%B2%84%ED%8E%98%EC%9D%B4"
    html = fetch_html(list_url)
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.select("a.list_subject")[:3]:
        post_url = "https://www.clien.net" + a["href"]
        print(f"[클리앙 스캔] {post_url}")
        post_html = fetch_html(post_url)
        for l in extract_links(post_html):
            if l not in links:
                links.append(l)
    return links

def scrape_etoland() -> list:
    """2. 이토랜드 핫딜 최신글 3개 스캔"""
    links = []
    list_url = "https://etoland.co.kr/b/hotdeal?sfl=wr_subject&stx=%EC%9D%BC%EC%9D%BC%EC%A0%81%EB%A6%BD"
    html = fetch_html(list_url)
    soup = BeautifulSoup(html, "html.parser")
    count = 0
    for a in soup.select("a[href*='/b/hotdeal/view/']"):
        if "일일적립" in a.get_text() or "클릭" in a.get_text():
            post_url = a["href"]
            if not post_url.startswith("http"):
                post_url = "https://etoland.co.kr" + post_url
            print(f"[이토랜드 스캔] {post_url}")
            post_html = fetch_html(post_url)
            for l in extract_links(post_html):
                if l not in links:
                    links.append(l)
            count += 1
            if count >= 3:
                break
    return links

def scrape_ppomppu() -> list:
    """3. 뽐뿌 쿠폰/이벤트 게시판 최신글 3개 스캔"""
    links = []
    list_url = "https://www.ppomppu.co.kr/zboard/zboard.php?id=coupon&search_type=subject&keyword=%B3%D7%C0%CC%B9%F6%C6%E4%C0%CC"
    html = fetch_html(list_url, encoding="euc-kr")
    soup = BeautifulSoup(html, "html.parser")
    count = 0
    for a in soup.select("a[href*='view.php?id=coupon']"):
        href = a["href"]
        post_url = "https://www.ppomppu.co.kr/zboard/" + href.lstrip("./")
        print(f"[뽐뿌 스캔] {post_url}")
        post_html = fetch_html(post_url, encoding="euc-kr")
        for l in extract_links(post_html):
            if l not in links:
                links.append(l)
        count += 1
        if count >= 3:
            break
    return links

if __name__ == "__main__":
    all_dynamic = []
    for func in (scrape_clien, scrape_etoland, scrape_ppomppu):
        try:
            for link in func():
                if link not in all_dynamic:
                    all_dynamic.append(link)
        except Exception as e:
            print(f"오류 무시하고 진행: {e}")

    final_links = all_dynamic + [f for f in FIXED_LINKS if f not in all_dynamic]

    data = {
        "updated_at": now_kst.strftime("%Y-%m-%d %H:%M:%S"),
        "dynamic_count": len(all_dynamic),
        "total_count": len(final_links),
        "links": final_links
    }

    with open("daily_links.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ 총 {len(final_links)}개 링크 저장 완료! (신규 추출: {len(all_dynamic)}개)")
