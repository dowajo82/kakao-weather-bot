import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv
from flask import Flask, redirect, request

load_dotenv()

# -----------------------------
# Common settings
# -----------------------------
KST = ZoneInfo("Asia/Seoul")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Seoul")
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "5000"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
RUN_HOUR = int(os.getenv("RUN_HOUR", "7"))
RUN_MINUTE = int(os.getenv("RUN_MINUTE", "0"))

# -----------------------------
# Kakao settings
# -----------------------------
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "")
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET", "")
KAKAO_REDIRECT_URI = os.getenv(
    "KAKAO_REDIRECT_URI",
    "http://localhost:5000/oauth/kakao/callback",
)
KAKAO_SCOPES = os.getenv("KAKAO_SCOPES", "talk_message")

TOKENS_FILE = Path(os.getenv("TOKENS_FILE", "tokens.json"))
ENV_ACCESS_TOKEN = os.getenv("KAKAO_ACCESS_TOKEN", "")
ENV_REFRESH_TOKEN = os.getenv("KAKAO_REFRESH_TOKEN", "")

# -----------------------------
# KMA weather settings
# -----------------------------
KMA_SERVICE_KEY = os.environ["KMA_SERVICE_KEY"]
KMA_NX = os.environ["KMA_NX"]
KMA_NY = os.environ["KMA_NY"]
LOCATION_NAME = os.getenv("LOCATION_NAME", "송파구 방이동")

ULTRA_NCST_URL = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"
VILAGE_FCST_URL = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"

SKY_MAP = {
    "1": "맑음",
    "3": "구름많음",
    "4": "흐림",
}

PTY_MAP = {
    "0": "",
    "1": "비",
    "2": "비/눈",
    "3": "눈",
    "4": "소나기",
    "5": "빗방울",
    "6": "빗방울/눈날림",
    "7": "눈날림",
}

app = Flask(__name__)


# -----------------------------
# Token helpers
# -----------------------------
def load_tokens() -> dict:
    if TOKENS_FILE.exists():
        return json.loads(TOKENS_FILE.read_text(encoding="utf-8"))

    tokens = {}
    if ENV_ACCESS_TOKEN:
        tokens["access_token"] = ENV_ACCESS_TOKEN
    if ENV_REFRESH_TOKEN:
        tokens["refresh_token"] = ENV_REFRESH_TOKEN
    return tokens


def save_tokens(tokens: dict) -> None:
    TOKENS_FILE.write_text(
        json.dumps(tokens, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def exchange_code_for_token(code: str) -> dict:
    url = "https://kauth.kakao.com/oauth/token"
    data = {
        "grant_type": "authorization_code",
        "client_id": KAKAO_REST_API_KEY,
        "redirect_uri": KAKAO_REDIRECT_URI,
        "code": code,
    }
    if KAKAO_CLIENT_SECRET:
        data["client_secret"] = KAKAO_CLIENT_SECRET

    resp = requests.post(url, data=data, timeout=20)
    resp.raise_for_status()
    return resp.json()


def refresh_access_token(refresh_token: str) -> dict:
    url = "https://kauth.kakao.com/oauth/token"
    data = {
        "grant_type": "refresh_token",
        "client_id": KAKAO_REST_API_KEY,
        "refresh_token": refresh_token,
    }
    if KAKAO_CLIENT_SECRET:
        data["client_secret"] = KAKAO_CLIENT_SECRET

    resp = requests.post(url, data=data, timeout=20)
    resp.raise_for_status()
    return resp.json()


def get_valid_access_token() -> str:
    tokens = load_tokens()

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise RuntimeError(
            "refresh_token이 없습니다. 먼저 /login 으로 카카오 로그인을 완료하거나 "
            "KAKAO_REFRESH_TOKEN 환경변수를 설정하세요."
        )

    refreshed = refresh_access_token(refresh_token)
    tokens["access_token"] = refreshed["access_token"]

    if refreshed.get("refresh_token"):
        tokens["refresh_token"] = refreshed["refresh_token"]
    if refreshed.get("refresh_token_expires_in"):
        tokens["refresh_token_expires_in"] = refreshed["refresh_token_expires_in"]

    save_tokens(tokens)
    return tokens["access_token"]


# -----------------------------
# Weather helpers (KMA)
# -----------------------------
def fetch_kma(url: str, base_date: str, base_time: str, nx: str, ny: str) -> list[dict]:
    params = {
        "serviceKey": KMA_SERVICE_KEY,
        "pageNo": "1",
        "numOfRows": "1000",
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": str(nx),
        "ny": str(ny),
    }

    res = requests.get(url, params=params, timeout=20)
    res.raise_for_status()
    data = res.json()

    header = data["response"]["header"]
    if header["resultCode"] != "00":
        raise RuntimeError(f'KMA API 오류: {header["resultCode"]} {header["resultMsg"]}')

    return data["response"]["body"]["items"]["item"]


def get_latest_ncst_base(now: datetime) -> tuple[str, str]:
    base = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    return base.strftime("%Y%m%d"), base.strftime("%H00")


def get_latest_vilage_base(now: datetime) -> tuple[str, str]:
    candidates = [2, 5, 8, 11, 14, 17, 20, 23]
    today_candidates = [h for h in candidates if h <= now.hour]

    if today_candidates:
        h = today_candidates[-1]
        base = now.replace(hour=h, minute=0, second=0, microsecond=0)
    else:
        yesterday = now - timedelta(days=1)
        base = yesterday.replace(hour=23, minute=0, second=0, microsecond=0)

    return base.strftime("%Y%m%d"), base.strftime("%H00")


def recommend_outfit(current_temp, tmx, pop, pty, wind):
    try:
        current_temp = float(current_temp)
    except:
        current_temp = None

    try:
        tmx = float(tmx)
    except:
        tmx = None

    try:
        pop = float(pop)
    except:
        pop = 0

    try:
        wind = float(wind)
    except:
        wind = 0

    base_temp = current_temp if current_temp is not None else tmx

    if base_temp is None:
        outfit = "가벼운 겉옷을 챙기는 무난한 옷차림이 좋아요."
    elif base_temp <= 5:
        outfit = "패딩이나 두꺼운 코트, 목도리까지 챙기세요."
    elif base_temp <= 10:
        outfit = "코트나 두꺼운 가디건, 니트가 잘 맞아요."
    elif base_temp <= 16:
        outfit = "얇은 니트, 맨투맨, 가벼운 자켓이 좋아요."
    elif base_temp <= 22:
        outfit = "긴팔 티나 셔츠 정도가 적당해요."
    elif base_temp <= 27:
        outfit = "얇은 옷차림이 좋아요. 반팔도 괜찮아요."
    else:
        outfit = "많이 더울 수 있어요. 반팔, 시원한 옷차림이 좋아요."

    extras = []

    if pty != "0" or pop >= 60:
        extras.append("우산 챙기세요.")
    elif pop >= 30:
        extras.append("접이식 우산이 있으면 좋아요.")

    if wind >= 7:
        extras.append("바람이 강하니 겉옷을 하나 더 챙기세요.")

    if current_temp is not None and tmx is not None and (tmx - current_temp) >= 8:
        extras.append("낮과의 기온 차가 커서 벗기 쉬운 겉옷이 좋아요.")

    if extras:
        return outfit + " " + " ".join(extras)
    return outfit


def build_weather_message() -> str:
    now = datetime.now(KST)

    ncst_date, ncst_time = get_latest_ncst_base(now)
    ncst_items = fetch_kma(ULTRA_NCST_URL, ncst_date, ncst_time, KMA_NX, KMA_NY)
    ncst = {item["category"]: item["obsrValue"] for item in ncst_items}

    current_temp = ncst.get("T1H", "-")
    current_humidity = ncst.get("REH", "-")
    current_wind = ncst.get("WSD", "-")

    fcst_date, fcst_time = get_latest_vilage_base(now)
    fcst_items = fetch_kma(VILAGE_FCST_URL, fcst_date, fcst_time, KMA_NX, KMA_NY)

    grouped: dict[tuple[str, str], dict[str, str]] = {}
    for item in fcst_items:
        key = (item["fcstDate"], item["fcstTime"])
        grouped.setdefault(key, {})
        grouped[key][item["category"]] = item["fcstValue"]

    today = now.strftime("%Y%m%d")
    today_rows = [v for (d, _), v in grouped.items() if d == today]

    tmn = next((row["TMN"] for row in today_rows if "TMN" in row), "-")
    tmx = next((row["TMX"] for row in today_rows if "TMX" in row), "-")

    future_keys = []
    for d, t in grouped.keys():
        dt = datetime.strptime(d + t, "%Y%m%d%H%M").replace(tzinfo=KST)
        if dt >= now:
            future_keys.append((dt, d, t))

    if future_keys:
        future_keys.sort()
        _, next_date, next_time = future_keys[0]
        next_fcst = grouped[(next_date, next_time)]

        tmp = next_fcst.get("TMP", "-")
        pop = next_fcst.get("POP", "-")
        sky = next_fcst.get("SKY", "")
        pty = next_fcst.get("PTY", "0")

        if pty != "0":
            weather_text = PTY_MAP.get(pty, "강수")
        else:
            weather_text = SKY_MAP.get(sky, "정보없음")

        next_time_text = f"{next_time[:2]}:{next_time[2:]}"
    else:
        tmp = "-"
        pop = "-"
        pty = "0"
        weather_text = "정보없음"
        next_time_text = "-"

    outfit_text = recommend_outfit(current_temp, tmx, pop, pty, current_wind)

    today_text = now.strftime("%Y-%m-%d")
    return (
        f"[{today_text} 오늘의 날씨]\n"
        f"지역: {LOCATION_NAME}\n"
        f"현재 기온: {current_temp}°C\n"
        f"습도: {current_humidity}%\n"
        f"풍속: {current_wind}m/s\n"
        f"오늘 최저/최고: {tmn}°C / {tmx}°C\n"
        f"다음 예보({next_time_text}): {weather_text}, {tmp}°C, 강수확률 {pop}%\n\n"
        f"[옷차림 추천]\n"
        f"{outfit_text}"
    )


# -----------------------------
# Kakao message
# -----------------------------
def send_kakao_memo(text: str) -> dict:
    access_token = get_valid_access_token()
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
    }
    template_object = {
        "object_type": "text",
        "text": text[:200],
        "link": {
            "web_url": "https://www.weather.go.kr",
            "mobile_web_url": "https://www.weather.go.kr",
        },
    }
    resp = requests.post(
        url,
        headers=headers,
        data={"template_object": json.dumps(template_object, ensure_ascii=False)},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


# -----------------------------
# Main job
# -----------------------------
def send_today_weather() -> None:
    message = build_weather_message()
    result = send_kakao_memo(message)
    print(f"[{datetime.now(KST).isoformat()}] sent: {result}")
    print(message)


# -----------------------------
# OAuth routes
# -----------------------------
@app.route("/")
def home():
    return (
        "<h2>Kakao Weather Bot</h2>"
        "<p><a href='/login'>카카오 로그인 시작</a></p>"
        "<p><a href='/send-now'>지금 테스트 발송</a></p>"
    )


@app.route("/login")
def login():
    query = urlencode(
        {
            "response_type": "code",
            "client_id": KAKAO_REST_API_KEY,
            "redirect_uri": KAKAO_REDIRECT_URI,
            "scope": KAKAO_SCOPES,
        }
    )
    return redirect(f"https://kauth.kakao.com/oauth/authorize?{query}")


@app.route("/oauth/kakao/callback")
def kakao_callback():
    code = request.args.get("code")
    if not code:
        return "인가 코드가 없습니다.", 400

    token_data = exchange_code_for_token(code)
    save_tokens(token_data)
    return (
        "카카오 로그인 완료. refresh_token 저장됨.<br>"
        "이제 <a href='/send-now'>/send-now</a> 로 테스트할 수 있습니다."
    )


@app.route("/send-now")
def send_now_route():
    try:
        send_today_weather()
        return "카카오톡으로 테스트 발송 완료"
    except Exception as e:
        return f"오류: {e}", 500


# -----------------------------
# Scheduler
# -----------------------------
def start_scheduler():
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        send_today_weather,
        trigger="cron",
        hour=RUN_HOUR,
        minute=RUN_MINUTE,
        id="daily_weather_kakao",
        replace_existing=True,
    )
    print(f"Scheduler started: every day {RUN_HOUR:02d}:{RUN_MINUTE:02d} ({TIMEZONE})")
    scheduler.start()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=["server", "send-now", "scheduler"],
        help="server: 로그인용 웹서버, send-now: 즉시 발송, scheduler: 매일 자동 발송",
    )
    args = parser.parse_args()

    if args.mode == "server":
        app.run(host=APP_HOST, port=APP_PORT, debug=DEBUG)
    elif args.mode == "send-now":
        send_today_weather()
    elif args.mode == "scheduler":
        start_scheduler()
