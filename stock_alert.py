import requests
import feedparser
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from urllib.parse import quote

# ─────────────────────────────────────────────
#  설정 (하드코딩)
# ─────────────────────────────────────────────
DART_API_KEY = "a6555fc0c8b821319ccd658d41a9572cd421e16d"
GMAIL_USER   = "yschoinet@gmail.com"
GMAIL_PASS   = "eeupngfqfkvobsij"   # Gmail 앱 비밀번호 (공백 제거)
TO_EMAIL     = "yschoinet@gmail.com"

# 관심 종목: {회사명: 종목코드(6자리)}
# DART corp_code는 실행 시 자동으로 조회합니다
STOCKS = {
    "삼성전자":       "005930",
    "현대차":         "005380",
    "고영":           "098460",
    "우진":           "105840",
    "레인보우로보틱스": "277810",
}

# ─────────────────────────────────────────────
#  DART corp_code 자동 조회
# ─────────────────────────────────────────────
def get_corp_code_map(stock_code_map: dict) -> dict:
    """
    DART 전체 기업 목록을 다운로드해서
    종목코드(stock_code) → corp_code(8자리) 매핑 딕셔너리 반환
    """
    import zipfile
    from io import BytesIO
    import xml.etree.ElementTree as ET

    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    res = requests.get(url, params={"crtfc_key": DART_API_KEY}, timeout=30)

    with zipfile.ZipFile(BytesIO(res.content)) as z:
        with z.open("CORPCODE.xml") as f:
            tree = ET.parse(f)

    root = tree.getroot()
    # stock_code → corp_code 매핑
    sc_to_cc = {}
    for item in root.findall("list"):
        sc  = item.findtext("stock_code", "").strip()
        cc  = item.findtext("corp_code",  "").strip()
        if sc:
            sc_to_cc[sc] = cc

    result = {}
    for name, sc in stock_code_map.items():
        cc = sc_to_cc.get(sc, "")
        if cc:
            result[name] = {"stock_code": sc, "corp_code": cc}
        else:
            print(f"[경고] {name}({sc}) 의 corp_code 를 찾지 못했습니다.")
    return result


# ─────────────────────────────────────────────
#  DART 공시 조회
# ─────────────────────────────────────────────
def get_dart_disclosures(corp_code: str) -> list:
    """최근 1일 공시 목록 조회"""
    yesterday = (datetime.today() - timedelta(days=1)).strftime("%Y%m%d")
    today     = datetime.today().strftime("%Y%m%d")

    url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bgn_de":    yesterday,
        "end_de":    today,
        "page_count": 10,
    }
    try:
        res  = requests.get(url, params=params, timeout=10)
        data = res.json()
        items = []
        if data.get("status") == "000" and data.get("list"):
            for d in data["list"]:
                items.append({
                    "title": d["report_nm"],
                    "date":  d["rcept_dt"],
                    "url":   f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={d['rcept_no']}"
                })
        return items
    except Exception as e:
        print(f"[공시 오류] {corp_code}: {e}")
        return []


# ─────────────────────────────────────────────
#  네이버 뉴스 RSS 조회
# ─────────────────────────────────────────────
def get_naver_news(company_name: str) -> list:
    """네이버 뉴스 RSS로 최신 뉴스 5건 수집"""
    query   = quote(company_name + " 주식")
    rss_url = f"https://search.naver.com/rss?where=news&query={query}&pd=1"
    try:
        feed  = feedparser.parse(rss_url)
        items = []
        for entry in feed.entries[:5]:
            title = entry.get("title", "제목 없음")
            link  = entry.get("link",  "#")
            pub   = entry.get("published", "")
            items.append({"title": title, "link": link, "date": pub})
        return items
    except Exception as e:
        print(f"[뉴스 오류] {company_name}: {e}")
        return []


# ─────────────────────────────────────────────
#  HTML 이메일 본문 생성
# ─────────────────────────────────────────────
def build_html(data: dict) -> str:
    today = datetime.today().strftime("%Y년 %m월 %d일 (%A)")
    # 요일 한글 변환
    day_map = {
        "Monday": "월요일", "Tuesday": "화요일", "Wednesday": "수요일",
        "Thursday": "목요일", "Friday": "금요일", "Saturday": "토요일", "Sunday": "일요일"
    }
    for en, ko in day_map.items():
        today = today.replace(en, ko)

    html = f"""
<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:'Malgun Gothic',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f8;padding:24px 0;">
  <tr><td align="center">
  <table width="680" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">

    <!-- 헤더 -->
    <tr>
      <td style="background:linear-gradient(135deg,#1565c0,#1976d2);padding:28px 32px;">
        <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;">
          📈 주식 알리미
        </h1>
        <p style="margin:6px 0 0;color:#bbdefb;font-size:14px;">{today} · 오전 10시 자동 발송</p>
      </td>
    </tr>

    <!-- 본문 -->
    <tr><td style="padding:24px 32px;">
"""

    for corp_name, info in data.items():
        disclosures = info.get("disclosures", [])
        news        = info.get("news", [])
        stock_code  = info.get("stock_code", "")
        naver_url   = f"https://finance.naver.com/item/main.naver?code={stock_code}"

        html += f"""
      <!-- 종목 섹션: {corp_name} -->
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:28px;border:1px solid #e3e8ee;border-radius:10px;overflow:hidden;">
        <tr>
          <td style="background:#f0f4ff;padding:14px 20px;border-bottom:1px solid #e3e8ee;">
            <a href="{naver_url}" style="text-decoration:none;">
              <span style="font-size:17px;font-weight:700;color:#1565c0;">{corp_name}</span>
              <span style="font-size:12px;color:#888;margin-left:8px;">{stock_code} · 네이버 증권 ↗</span>
            </a>
          </td>
        </tr>
        <tr><td style="padding:16px 20px;">

          <!-- 공시 -->
          <p style="margin:0 0 8px;font-size:13px;font-weight:700;color:#333;border-left:3px solid #1976d2;padding-left:8px;">
            📋 공시 ({len(disclosures)}건)
          </p>
"""
        if disclosures:
            html += '<ul style="margin:0 0 16px 16px;padding:0;">'
            for d in disclosures:
                html += f"""
            <li style="margin-bottom:6px;font-size:13px;color:#333;">
              <a href="{d['url']}" style="color:#1565c0;text-decoration:none;">{d['title']}</a>
              <span style="color:#999;font-size:11px;margin-left:6px;">{d['date']}</span>
            </li>"""
            html += '</ul>'
        else:
            html += '<p style="margin:0 0 16px;font-size:13px;color:#999;padding-left:4px;">전일 공시 없음</p>'

        # 뉴스
        html += f"""
          <!-- 뉴스 -->
          <p style="margin:0 0 8px;font-size:13px;font-weight:700;color:#333;border-left:3px solid #43a047;padding-left:8px;">
            📰 관련 뉴스 ({len(news)}건)
          </p>
"""
        if news:
            html += '<ul style="margin:0 0 4px 16px;padding:0;">'
            for n in news:
                html += f"""
            <li style="margin-bottom:6px;font-size:13px;color:#333;">
              <a href="{n['link']}" style="color:#1565c0;text-decoration:none;">{n['title']}</a>
            </li>"""
            html += '</ul>'
        else:
            html += '<p style="margin:0;font-size:13px;color:#999;padding-left:4px;">관련 뉴스 없음</p>'

        html += """
        </td></tr>
      </table>
"""

    # 푸터
    html += """
    </td></tr>

    <!-- 푸터 -->
    <tr>
      <td style="background:#f8f9fa;padding:16px 32px;border-top:1px solid #e3e8ee;text-align:center;">
        <p style="margin:0;font-size:11px;color:#aaa;">
          본 메일은 DART 공시 API 및 네이버 뉴스 RSS를 기반으로 자동 발송됩니다.<br>
          투자 판단은 본인 책임이며, 참고 자료로만 활용하시기 바랍니다.
        </p>
      </td>
    </tr>

  </table>
  </td></tr>
</table>
</body>
</html>
"""
    return html


# ─────────────────────────────────────────────
#  Gmail 발송
# ─────────────────────────────────────────────
def send_email(html_body: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📈 주식 알리미 | {datetime.today().strftime('%Y-%m-%d')}"
    msg["From"]    = GMAIL_USER
    msg["To"]      = TO_EMAIL
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASS)
            server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ 이메일 발송 완료")
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ 이메일 발송 실패: {e}")
        raise


# ─────────────────────────────────────────────
#  메인 실행
# ─────────────────────────────────────────────
def job():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🔄 수집 시작...")

    # 1. DART corp_code 조회
    print("  DART corp_code 조회 중...")
    corp_map = get_corp_code_map(STOCKS)

    # 2. 각 종목별 공시 + 뉴스 수집
    data = {}
    for corp_name, info in corp_map.items():
        print(f"  [{corp_name}] 공시 조회 중...")
        disclosures = get_dart_disclosures(info["corp_code"])
        time.sleep(0.3)  # API 부하 방지

        print(f"  [{corp_name}] 뉴스 조회 중...")
        news = get_naver_news(corp_name)

        data[corp_name] = {
            "stock_code":   info["stock_code"],
            "disclosures":  disclosures,
            "news":         news,
        }

    # 3. HTML 생성 및 발송
    html = build_html(data)
    send_email(html)


if __name__ == "__main__":
    job()
