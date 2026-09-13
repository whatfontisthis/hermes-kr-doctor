# hermes-kr-doctor

Hermes 설치가 왜 안 되는지 한국어로 알려 주는 진단 도구.

[Hermes](https://github.com/NousResearch/hermes-agent)는 내 PC 안에서 도는 개인 AI 비서입니다.
설치는 보통 잘 됩니다. 문제는 안 될 때예요.

한국어 윈도우에서 Hermes가 막히면 오류창이 안 뜹니다. 파일 저장이 그냥 안 됩니다.
봇은 온라인이라고 떠 있는데 말을 걸어도 조용합니다. 로그를 열어 보면 글자가 깨져 있어서
무슨 오류인지 읽을 수도 없습니다. 셋 다 초보자가 손댈 수 있는 모양의 오류가 아닙니다.

이 도구는 그 상황에서 9가지를 점검하고, 항목마다 지금 무엇을 눌러야 하는지 한국어로 알려 줍니다.

```
  [ X  ] 허용 사용자 잠금  (2-4절 · 부록 B)
       텔레그램, 디스코드의 허용 사용자 목록이 비어 있습니다. 봇이 나만 쓰는 상태가 아닙니다.
       → .env 에 아래 줄을 넣고 게이트웨이를 재시작하세요.
         텔레그램 숫자 ID는 @userinfobot에게 아무 말이나 걸면 알려 줍니다.
         $ TELEGRAM_ALLOWED_USERS=<내 숫자 ID>

  [ X  ] 토큰 평문 노출  (부록 B)
       설정·로그 파일에서 토큰으로 보이는 문자열을 찾았습니다: gateway.log (telegram_bot_token)
       → 망설이지 말고 지금 재발급하세요. 재발급하는 순간 이전 토큰은 무효가 됩니다.
```

## 써 보기

Hermes가 아직 안 깔렸어도 돌아갑니다. 파이썬 3.9 이상이면 됩니다.

```bash
git clone https://github.com/whatfontisthis/hermes-kr-doctor
cd hermes-kr-doctor
python kr_doctor.py
```

| 명령 | 하는 일 |
| --- | --- |
| `python kr_doctor.py` | 진단만 합니다. |
| `python kr_doctor.py --fix` | 되돌릴 수 있는 것만 고칩니다. 지금은 `.env` 파일 권한 조이기 하나뿐입니다. |
| `python kr_doctor.py --json` | JSON으로 뱉습니다. 조치 필요 항목이 있으면 종료 코드 1. |

### Hermes 플러그인으로 붙이기

폴더째 `~/.hermes/plugins/` 밑에 넣고 켜면 됩니다.

```bash
git clone https://github.com/whatfontisthis/hermes-kr-doctor ~/.hermes/plugins/hermes-kr-doctor
hermes plugins enable hermes-kr-doctor
```

이제 세 군데서 같은 진단을 부를 수 있습니다.

- 터미널에서 `hermes doctor-kr`
- 텔레그램·디스코드 대화창에서 `/닥터`
- 에이전트가 알아서. "봇이 대답을 안 해" 같은 말을 들으면 `kr_doctor` 도구를 직접 부릅니다.

세 번째가 원래 노리던 그림입니다. 고장 났을 때 사람이 명령어를 찾아 헤매는 대신,
비서한테 그냥 물어보면 자기가 어디가 아픈지 알아보고 답합니다.

## 점검하는 9가지

| 항목 | 잡아내는 증상 |
| --- | --- |
| Hermes 홈 폴더 | `~/.hermes`가 없거나 `config.yaml`이 깨졌습니다. |
| hermes 명령 | 앱은 깔렸는데 터미널 명령이 없어서 게이트웨이 설정을 못 합니다. |
| 윈도우 제어된 폴더 액세스 | 파일 작업만 오류 없이 조용히 실패합니다. |
| 게이트웨이 | 메신저로 말을 걸어도 답이 없습니다. |
| 메신저 연결 | 플랫폼은 켜 뒀는데 봇 토큰이 없습니다. |
| 허용 사용자 잠금 | 허용 목록이 비어 있어서 아무나 내 봇에게 명령할 수 있습니다. |
| 디스코드 Message Content Intent | 봇은 온라인인데 사람 말이 내용 없이 도착합니다. |
| 한글 경로·인코딩 | 코드페이지 949 때문에 로그가 깨져서 못 읽습니다. |
| 토큰 평문 노출 | 봇 토큰이 로그나 설정 파일에 그대로 남아 있습니다. |

판정은 세 단계입니다. `[ X ]`는 지금 이것 때문에 안 돌고 있거나 보안이 열려 있다는 뜻이고,
`[ ! ]`는 당장 고장은 아니지만 곧 문제가 된다는 뜻입니다. `[ - ]`는 안 쓰는 기능이라
확인할 게 없다는 뜻이니 넘어가면 됩니다.

## 설정을 읽는 대신 직접 해봅니다

윈도우 '제어된 폴더 액세스' 차단을 잡아내는 게 이 도구에서 제일 까다로웠습니다.

처음엔 레지스트리 값을 읽어서 켜졌는지 보려고 했습니다. 그런데 이 방식은 답을 못 냅니다.
기능이 켜져 있어도 지금 Hermes를 돌리는 그 파이썬이 허용 목록에 있으면 아무 문제가 없거든요.
그리고 그 허용 목록은 관리자 권한 없이는 읽히지도 않습니다. 설정값만 봐서는
"이 사용자가 지금 막혀 있는가"에 답할 수 없다는 뜻입니다.

그래서 방향을 바꿨습니다. 문서 폴더에 임시 파일을 실제로 써 봅니다. `PermissionError`가 나면
그게 답입니다. 파일은 바로 지웁니다. 판정 기준이 "설정이 이렇더라"에서
"방금 해 봤는데 안 되더라"로 바뀌니 오진이 사라졌습니다.

토큰 노출 검사도 같은 원칙입니다. "설정이 안전한가"를 묻지 않고, 설정·로그 파일 안에
토큰 모양 문자열이 실제로 들어 있는지 봅니다.

## 어디서 나왔나

점검 항목 9가지는 제가 쓴 [Hermes 설치 매뉴얼](https://autofrog.kr/lab)의 부록 A(트러블슈팅)와
부록 B(보안 수칙)를 코드로 옮긴 것입니다. 윈도우 PC에 직접 깔면서 실제로 막혔던 것들이라
없는 문제를 상상해서 만든 항목은 하나도 없습니다.

매뉴얼은 사람이 읽고 스스로 고치는 것이고, 이 도구는 같은 내용을 기계가 확인해 주는 것입니다.
그래서 진단 결과마다 매뉴얼 절 번호가 붙습니다. 더 알고 싶으면 그 쪽을 펴면 됩니다.

## 의존성

없습니다. `kr_doctor.py`는 표준 라이브러리만 씁니다.

일부러 그렇게 했습니다. 진단이 제일 필요한 순간은 환경이 이미 망가진 순간인데,
그때 `pip install`부터 해야 한다면 도구로서 실패니까요.

PyYAML이 깔려 있으면 `config.yaml`을 그걸로 읽고, 없으면 필요한 키만 훑는 간이 파서로 넘어갑니다.

## 테스트

```bash
python -m unittest discover -s tests
```

## 기여

버그 제보와 새 점검 항목 제안을 환영합니다. 특히 윈도우나 맥에서 겪으신 한국어 환경 문제를
이슈로 남겨 주시면 점검 항목으로 만들겠습니다. 증상과 그때 뜬 메시지, OS 버전을 같이 적어 주세요.

---

## English

A Korean-language setup doctor for [Hermes](https://github.com/NousResearch/hermes-agent).

Hermes installs cleanly most of the time. When it doesn't, Windows fails quietly.
Controlled Folder Access makes file writes no-op with no error at all. A Discord bot
missing the message content intent shows as online but receives empty text. Code page 949
turns log output into mojibake, so you can't even read what broke. None of it produces
a message a Korean beginner can act on.

This tool runs nine checks and prints what to press next, in Korean. It installs as a
Hermes plugin and exposes the same diagnosis three ways: `hermes doctor-kr` in a terminal,
`/닥터` in a chat, and a `kr_doctor` tool the agent calls on its own when someone says the
bot stopped answering. `kr_doctor.py` also runs as a plain script with zero third-party
imports, because the moment you need a diagnosis is the moment `pip install` is not an option.

Two of the checks reproduce the symptom instead of reading a setting. Controlled Folder
Access is detected by writing a probe file into `~/Documents` and catching `PermissionError`,
since the registry value alone never says whether the interpreter actually running Hermes is
on the allow list. Token exposure is detected by scanning config and log files for
credential-shaped strings, not by asking whether the configuration looks safe.

Every check comes from a failure I hit while writing a 61-page Korean install manual for
Hermes, published free at [autofrog.kr/lab](https://autofrog.kr/lab). Each finding cites the
manual section that covers it.

MIT licensed. Issues and new checks welcome, especially failures you've seen on Korean-locale Windows.
