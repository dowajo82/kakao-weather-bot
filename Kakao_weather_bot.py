import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv
from flask import Flask, redirect, request

load_dotenv()

# -----------------------------
# Environment variables
# -----------------------------
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "")
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET", "")
KAKAO_REDIRECT_URI = os.getenv("KAKAO_REDIRECT_URI", "http://localhost:5000/oauth/kakao/callback")
KAKAO_SCOPES = os.getenv("KAKAO_SCOPES", "talk_message")

LOCATION_QUERY = os.getenv("LOCATION_QUERY", "Sujinil-dong, Korea")
LOCATION_NAME = os.getenv("LOCATION_NAME", "")
LOCATION_LAT = os.getenv("LOCATION_LAT", "")
LOCATION_LON = os.getenv("LOCATION_LON", "")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Seoul")
RUN_HOUR = int(os.getenv("RUN_HOUR", "7"))
RUN_MINUTE = int(os.getenv("RUN_MINUTE", "0"))

APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "5000"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

TOKENS_FILE = Path(os.getenv("TOKENS_FILE", "tokens.json"))

app = Flask(__name__)


# -----------------------------
# Token helpers
# -----------------------------
def load_tokens() -> dict:
    if TOKENS_FILE.exists():
        return json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
    return {}


def save_tokens(tokens: dict) -> None:
    TOKENS_FILE.write_text(
        json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def exchange_code_for_token(code: str) -> dict:
    url = "https://kauth.kakao.com/oauth/token"
    data = {
        "grant_type": "authorization_code",
        "client_id": KAKAO_REST_API_KEY,
        "redirect_uri": KAKAO_REDIRECT_URI,
        "code": code,
        "client_secret": KAKAO_CLIENT_SECRET,
    }
    resp = requests.post(url, data=data, timeout=20)
    resp.raise_for_status()
    return resp.json()


def refresh_access_token(refresh_token: str) -> dict:
    url = "https://kauth.kakao.com/oauth/token"
    data = {
        "grant_type": "refresh_token",
        "client_id": KAKAO_REST_API_KEY,
        "refresh_token": refresh_token,
        "client_secret": KAKAO_CLIENT_SECRET,
    }
    resp = requests.post(url, data=data, timeout=20)
    resp.raise_for_status()
    return resp.json()


def get_valid_access_token() -> str:
    tokens = load_tokens()
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise RuntimeError(
            "refresh_token이 없습니다. 먼저 http://localhost:5000/login 으로 접속해서 카카오 로그인을 완료하세요."
        )

    refreshed = refresh_access_token(refresh_token)
    tokens["access_token"] = refreshed["access_token"]

    # 카카오는 리프레시 토큰 만료가 1개월 미만일 때만 새 refresh_token을 내려줄 수 있음.
    if refreshed.get("refresh_token"):
        tokens["refresh_token"] = refreshed["refresh_token"]
    if refreshed.get("refresh_token_expires_in"):
        tokens["refresh_token_expires_in"] = refreshed["refresh_token_expires_in"]

    save_tokens(tokens)
    return tokens["access_token"]


# -----------------------------
# Weather helpers
# -----------------------------
def geocode_location(name: str) -> tuple[float, float, str]:
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {
        "name": name,
        "count": 1,
        "language": "ko",
        "format": "json",
    }
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    results = data.get("results") or []
    if not results:
        raise RuntimeError(f"위치를 찾지 못했습니다: {name}")

    item = results[0]
    display_name = ", ".join(
        p for p in [item.get("name"), item.get("admin1"), item.get("country")] if p
    )
    return item["latitude"], item["longitude"], display_name


def get_weather() -> dict:
    if LOCATION_LAT and LOCATION_LON:
        lat = float(LOCATION_LAT)
        lon = float(LOCATION_LON)
        display_name = LOCATION_NAME or LOCATION_QUERY or f"{lat}, {lon}"
    else:
        lat, lon, display_name = geocode_location(LOCATION_QUERY)
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": TIMEZONE,
        "current": ",".join(
            [
                "temperature_2m",
                "apparent_temperature",
                "weather_code",
                "precipitation",
                "is_day",
            ]
        ),
        "daily": ",".join(
            [
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_probability_max",
                "weather_code",
            ]
        ),
    }
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    raw = resp.json()

    current = raw["current"]
    daily = raw["daily"]
    return {
        "location": display_name,
        "current_temp": round(current["temperature_2m"]),
        "feels_like": round(current["apparent_temperature"]),
        "weather_code": int(current["weather_code"]),
        "precipitation": current.get("precipitation", 0),
        "today_max": round(daily["temperature_2m_max"][0]),
        "today_min": round(daily["temperature_2m_min"][0]),
        "rain_prob_max": int(daily.get("precipitation_probability_max", [0])[0] or 0),
    }


# -----------------------------
# Message helpers
# -----------------------------
def weather_code_to_korean(code: int) -> str:
    mapping = {
        0: "맑음",
        1: "대체로 맑음",
        2: "부분적으로 흐림",
        3: "흐림",
        45: "안개",
        48: "서리 안개",
        51: "약한 이슬비",
        53: "이슬비",
        55: "강한 이슬비",
        56: "약한 어는 이슬비",
        57: "강한 어는 이슬비",
        61: "약한 비",
        63: "비",
        65: "강한 비",
        66: "약한 어는 비",
        67: "강한 어는 비",
        71: "약한 눈",
        73: "눈",
        75: "강한 눈",
        77: "싸락눈",
        80: "약한 소나기",
        81: "소나기",
        82: "강한 소나기",
        85: "약한 눈 소나기",
        86: "강한 눈 소나기",
        95: "뇌우",
        96: "약한 우박 동반 뇌우",
        99: "강한 우박 동반 뇌우",
    }
    return mapping.get(code, f"날씨 코드 {code}")


def outfit_recommendation(weather: dict) -> str:
    now = weather["current_temp"]
    low = weather["today_min"]
    high = weather["today_max"]
    rain = weather["rain_prob_max"]

    lines = []
    if now >= 28:
        lines.append("반팔, 얇은 바지나 반바지로 충분해요.")
        lines.append("햇빛이 강하면 모자나 선글라스도 좋아요.")
    elif now >= 23:
        lines.append("반팔이나 얇은 셔츠가 잘 맞아요.")
        lines.append("실내 냉방이 강하면 얇은 겉옷 하나 챙기세요.")
    elif now >= 17:
        lines.append("긴팔 티나 셔츠에 가벼운 아우터가 좋아요.")
    elif now >= 10:
        lines.append("가디건, 얇은 니트, 자켓이 잘 맞아요.")
    elif now >= 3:
        lines.append("코트나 두꺼운 점퍼를 추천해요.")
        lines.append("아침저녁은 꽤 쌀쌀할 수 있어요.")
    else:
        lines.append("패딩이나 두꺼운 외투가 필요해요.")
        lines.append("목도리나 장갑도 고려해 보세요.")

    if high - low >= 10:
        lines.append("일교차가 커서 벗고 입기 쉬운 겉옷이 있으면 좋아요.")
    if rain >= 50:
        lines.append("비 가능성이 높으니 우산을 챙기세요.")
    elif rain >= 30:
        lines.append("혹시 모르니 작은 우산이 있으면 안심돼요.")

    return " ".join(lines)


def build_message(weather: dict) -> str:
    condition = weather_code_to_korean(weather["weather_code"])
    outfit = outfit_recommendation(weather)
    today = datetime.now().strftime("%Y-%m-%d")
    return (
        f"[{today} 오늘의 날씨]\n"
        f"지역: {weather['location']}\n"
        f"현재: {weather['current_temp']}°C (체감 {weather['feels_like']}°C), {condition}\n"
        f"오늘: 최저 {weather['today_min']}°C / 최고 {weather['today_max']}°C\n"
        f"강수확률: {weather['rain_prob_max']}%\n\n"
        f"[옷 추천]\n{outfit}"
    )


def send_kakao_memo(text: str) -> dict:
    access_token = get_valid_access_token()
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
    }
    template_object = {
        "object_type": "text",
        "text": text[:200],  # 카카오 텍스트형은 200자 표시
        "link": {
            "web_url": "https://open-meteo.com",
            "mobile_web_url": "https://open-meteo.com",
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
    weather = get_weather()
    message = build_message(weather)
    result = send_kakao_memo(message)
    print(f"[{datetime.now().isoformat()}] sent: {result}")
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
    import threading

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
        # 스케줄러만 실행. 서버가 필요 없으면 이 모드 사용.
        start_scheduler()
