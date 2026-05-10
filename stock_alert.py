import requests
import smtplib
import time
import zipfile
import re
import xml.etree.ElementTree as ET
from io import BytesIO
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta

# ─────────────────────────────────────────────
#  설정 (하드코딩)
# ─────────────────────────────────────────────
DART_API_KEY = "a6555fc0c8b821319ccd658d41a9572cd421e16d"
GMAIL_USER   = "yschoinet@gmail.com"
GMAIL_PASS   = "eeupngfqfkvobsij"   # Gmail 앱 비밀번호 (공백 제거)
TO_EMAIL     = "yschoinet@gmail.com"

# 관심 종목: {회사명: 종목코드(6자리)}
STOCKS = {
    "삼성전자":        "005930",
    "현대차":          "005380",
    "고영":            "098460",
    "우진":            "105840",
    "서진시스템":      "178320",
    "레인보우로보틱스": "277810",
}

# 조회 기간: 최근 몇 영업일치 공시를 볼지
DART_DAYS = 3


# ─────────────────────────────────────────────
#  영업일 기준 시작일 계산 (주말 건너뜀)
# ─────────────────────────────────────────────
def get_start_date(days: int) -> str:
    """
    오늘 기준으로 영업일(평일) days일 전 날짜 반환
    예) 월요일 실행 시 → 금요일(1영업일 전)부터 조회
    """
    target = datetime.today()
    counted = 0
    while counted < days:
        target -= timedelta(days=1)
        if target.weekday() < 5:   # 0=월 ~ 4=금
            counted += 1
    return target.strftime("%Y%m%d")


# ─────────────────────────────────────────────
#  DART corp_code 자동 조회
# ─────────────────────────────────────────────
def get_corp_code_map(stock_code_map: dict) -> dict:
    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    res = requests.get(url, params={"crtfc_key": DART_API_KEY}, timeout=30)
    res.raise_for_status()

    with zipfile.ZipFile(BytesIO(res.content)) as z:
        with z.open("CORPCODE.xml") as f:
            tree = ET.parse(f)

    root = tree.getroot()
    sc_to_cc = {}
    for item in root.findall("list"):
        sc = item.findtext("stock_code", "").strip()
        cc = item.findtext("corp_code",  "").strip()
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
    bgn_de = get_start_date(DART_DAYS)
    end_de = datetime.today().strftime("%Y%m%d")

    url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bgn_de":    bgn_de,
        "end_de":    end_de,
        "page_count": 20,
    }
    try:
        res  = requests.get(url, params=params, timeout=15)
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
        print(f"[공시 오류] corp_code={corp_code}: {e}")
        return []


# ─────────────────────────────────────────────
#  네이버 금융 뉴스 조회
# ─────────────────────────────────────────────
def get_stock_news(stock_code: str, company_name: str) -> list:
    """네이버 금융 종목 뉴스 페이지에서 최신 5건 수집"""
    url = "https://finance.naver.com/item/news_news.naver"
    params = {"code": stock_code, "page": 1}
    headers = {
        "User-Agent":      ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Safari/537.36"),
        "Referer":         f"https://finance.naver.com/item/main.naver?code={stock_code}",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    try:
        res = requests.get(url, params=params, headers=headers, timeout=15)
        res.encoding = "euc-kr"
        html = res.text

        # <td class="title"><a href="...">제목</a> 패턴 파싱
        pattern = r'<td\s+class="title">\s*<a\s+href="([^"]+)"[^>]*>(.*?)</a>'
        matches = re.findall(pattern, html, re.DOTALL)

        items = []
        for href, title in matches[:5]:
            title = re.sub(r'<[^>]+>', '', title).strip()
            if not title:
                continue
            if href.startswith("/"):
                href = "https://finance.naver.com" + href
            items.append({"title": title, "link": href})
        return items
    except Exception as e:
        print(f"[뉴스 오류] {company_name}({stock_code}): {e}")
        return []


# ─────────────────────────────────────────────
#  HTML 이메일 본문 생성
# ─────────────────────────────────────────────
def build_html(data: dict) -> str:
    today = datetime.today().strftime("%Y년 %m월 %d일 (%A)")
    day_map = {
        "Monday": "월요일", "Tuesday": "화요일", "Wednesday": "수요일",
        "Thursday": "목요일", "Friday": "금요일", "Saturday": "토요일", "Sunday": "일요일"
    }
    for en, ko in day_map.items():
        today = today.replace(en, ko)

    bgn_str   = get_start_date(DART_DAYS)
    bgn_fmt   = f"{bgn_str[4:6]}/{bgn_str[6:8]}"
    today_fmt = datetime.today().strftime("%m/%d")

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:'Malgun Gothic',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f8;padding:24px 0;">
  <tr><td align="center">
  <table width="680" cellpadding="0" cellspacing="0"
    style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">

    <!-- 헤더 -->
    <tr>
      <td style="background:linear-gradient(135deg,#1565c0,#1976d2);padding:28px 32px;">
        <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;">📈 주식 알리미</h1>
        <p style="margin:6px 0 0;color:#bbdefb;font-size:13px;">{today} · 오전 10시 자동 발송</p>
        <p style="margin:4px 0 0;color:#90caf9;font-size:12px;">
          공시 조회 기간: {bgn_fmt} ~ {today_fmt} (최근 {DART_DAYS}영업일)
        </p>
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
        dart_url    = f"https://dart.fss.or.kr/dsab007/searchSub.ax?textCrpNm={stock_code}"

        disc_cnt  = len(disclosures)
        has_disc  = disc_cnt > 0
        header_bg = "#fff3e0" if has_disc else "#f0f4ff"
        name_color= "#e65100" if has_disc else "#1565c0"
        badge     = ("&nbsp;<span style='background:#e65100;color:#fff;"
                     "font-size:11px;padding:2px 8px;border-radius:10px;"
                     "vertical-align:middle;'>📢 공시 있음</span>"
                     if has_disc else "")

        html += f"""
      <table width="100%" cellpadding="0" cellspacing="0"
        style="margin-bottom:24px;border:1px solid #e3e8ee;border-radius:10px;overflow:hidden;">
        <tr>
          <td style="background:{header_bg};padding:13px 20px;border-bottom:1px solid #e3e8ee;">
            <a href="{naver_url}" style="text-decoration:none;">
              <span style="font-size:16px;font-weight:700;color:{name_color};">{corp_name}</span>
              <span style="font-size:12px;color:#888;margin-left:6px;">{stock_code}</span>
            </a>
            {badge}
            <a href="{naver_url}" style="font-size:11px;color:#1976d2;text-decoration:none;margin-left:10px;">
              네이버증권 ↗
            </a>
          </td>
        </tr>
        <tr><td style="padding:16px 20px;">

          <!-- 공시 -->
          <p style="margin:0 0 8px;font-size:13px;font-weight:700;color:#333;
                    border-left:3px solid #1976d2;padding-left:8px;">
            📋 공시 ({disc_cnt}건)
          </p>
"""
        if disclosures:
            html += '<ul style="margin:0 0 16px 0;padding:0;list-style:none;">'
            for d in disclosures:
                date_fmt = f"{d['date'][0:4]}/{d['date'][4:6]}/{d['date'][6:8]}"
                html += f"""
            <li style="margin-bottom:8px;padding:9px 12px;background:#fff8f0;
                        border:1px solid #ffe0b2;border-radius:6px;font-size:13px;">
              <a href="{d['url']}" style="color:#bf360c;text-decoration:none;font-weight:600;">
                {d['title']}
              </a>
              <span style="color:#999;font-size:11px;margin-left:8px;">{date_fmt}</span>
            </li>"""
            html += "</ul>"
        else:
            html += f'<p style="margin:0 0 16px;font-size:13px;color:#bbb;padding-left:4px;">최근 {DART_DAYS}영업일 공시 없음</p>'

        # 뉴스
        news_cnt = len(news)
        html += f"""
          <!-- 뉴스 -->
          <p style="margin:0 0 8px;font-size:13px;font-weight:700;color:#333;
                    border-left:3px solid #43a047;padding-left:8px;">
            📰 관련 뉴스 ({news_cnt}건)
          </p>
"""
        if news:
            html += '<ul style="margin:0 0 4px 0;padding:0;list-style:none;">'
            for n in news:
                html += f"""
            <li style="margin-bottom:7px;padding:8px 12px;background:#f1f8f1;
                        border:1px solid #c8e6c9;border-radius:6px;font-size:13px;">
              <a href="{n['link']}" style="color:#1b5e20;text-decoration:none;">
                {n['title']}
              </a>
            </li>"""
            html += "</ul>"
        else:
            html += '<p style="margin:0;font-size:13px;color:#bbb;padding-left:4px;">관련 뉴스 없음</p>'

        html += """
        </td></tr>
      </table>
"""

    html += """
    </td></tr>
    <tr>
      <td style="background:#f8f9fa;padding:14px 32px;border-top:1px solid #e3e8ee;text-align:center;">
        <p style="margin:0;font-size:11px;color:#aaa;">
          DART 공시 API + 네이버 금융 뉴스 기반 자동 발송 ·
          투자 판단은 본인 책임이며 참고 자료로만 활용하세요.
        </p>
      </td>
    </tr>
  </table>
  </td></tr>
</table>
</body>
</html>"""
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

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ 이메일 발송 완료")


# ─────────────────────────────────────────────
#  메인 실행
# ─────────────────────────────────────────────
def job():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🔄 수집 시작...")

    print("  DART corp_code 조회 중...")
    corp_map = get_corp_code_map(STOCKS)

    data = {}
    for corp_name, info in corp_map.items():
        bgn = get_start_date(DART_DAYS)
        end = datetime.today().strftime("%Y%m%d")
        print(f"  [{corp_name}] 공시 조회 중... ({bgn} ~ {end})")
        disclosures = get_dart_disclosures(info["corp_code"])
        print(f"    → 공시 {len(disclosures)}건")
        time.sleep(0.5)

        print(f"  [{corp_name}] 뉴스 조회 중...")
        news = get_stock_news(info["stock_code"], corp_name)
        print(f"    → 뉴스 {len(news)}건")
        time.sleep(0.3)

        data[corp_name] = {
            "stock_code":  info["stock_code"],
            "disclosures": disclosures,
            "news":        news,
        }

    print("  이메일 발송 중...")
    html = build_html(data)
    send_email(html)


if __name__ == "__main__":
    job()
