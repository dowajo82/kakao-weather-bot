# 카카오톡 날씨 알림 봇 사용법

## 1) 준비물
- Python 3.10 이상
- 카카오디벨로퍼스 앱 1개
- 카카오 로그인 활성화
- 동의항목에 `카카오톡 메시지 전송(talk_message)` 추가
- Redirect URI: `http://localhost:5000/oauth/kakao/callback`

## 2) 파일 준비
- `kakao_weather_bot.py`
- `.env.example`
- `requirements.txt`

`.env.example` 파일 이름을 `.env` 로 바꾸고 값을 입력하세요.

## 3) 라이브러리 설치
```bash
pip install -r requirements.txt
```

## 4) 카카오 로그인 1회 수행
```bash
python kakao_weather_bot.py server
```
브라우저에서 아래 주소 접속
```text
http://localhost:5000/login
```
로그인과 동의를 완료하면 `tokens.json` 이 생성됩니다.

## 5) 즉시 테스트 발송
```bash
python kakao_weather_bot.py send-now
```
또는 브라우저에서
```text
http://localhost:5000/send-now
```

## 6) 매일 오전 7시 자동 발송
```bash
python kakao_weather_bot.py scheduler
```
이 상태로 켜 두면 매일 07:00(Asia/Seoul)에 발송됩니다.

## 7) 윈도우에서 자동 시작
작업 스케줄러에 아래 명령을 등록하세요.

프로그램:
```text
python
```
인수:
```text
C:\경로\kakao_weather_bot.py scheduler
```
시작 위치:
```text
C:\경로
```

주의: PC가 꺼져 있으면 알림이 가지 않습니다. 항상 보내려면 Render, Railway, VPS 같은 항상 켜져 있는 서버에 올리는 편이 좋습니다.

## 8) 지인에게 보내기
이 코드는 현재 `나에게 보내기` 전용입니다.
지인에게 보내려면 카카오톡 친구 메시지 API 권한 신청과 수신자 UUID 처리 로직을 추가해야 합니다.
