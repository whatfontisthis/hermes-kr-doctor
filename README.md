# hermes-kr-doctor

Hermes 설치가 왜 안 되는지 한국어로 알려 주는 진단 도구.

[Hermes](https://github.com/NousResearch/hermes-agent)는 내 PC에서 도는 개인 AI 에이전트입니다.
설치는 대체로 잘 됩니다. 문제는 안 될 때인데, 윈도우에서 막히면 오류 메시지조차 안 나옵니다.
파일 작업은 조용히 실패하고, 봇은 온라인인데 대답이 없고, 로그는 글자가 깨져 읽을 수가 없습니다.

이 도구는 그 상황을 9가지 항목으로 점검하고, 각 항목마다 지금 무엇을 눌러야 하는지 한국어로 알려 줍니다.

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

## 쓰는 법

Hermes가 아직 안 깔렸어도, 깔렸는데 안 돌아도 씁니다. 파이썬 3.9 이상이면 됩니다.

```bash
git clone https://github.com/whatfontisthis/hermes-kr-doctor
cd hermes-kr-doctor
python kr_doctor.py
```

| 명령 | 하는 일 |
| --- | --- |
| `python kr_doctor.py` | 진단만 합니다. |
| `python kr_doctor.py --fix` | 안전하게 되돌릴 수 있는 것만 고칩니다. 지금은 `.env` 파일 권한 조이기 하나입니다. |
| `python kr_doctor.py --json` | 스크립트에서 쓰라고 JSON으로 뱉습니다. 조치 필요 항목이 있으면 종료 코드 1. |

### Hermes 플러그인으로 설치하면

폴더째 `~/.hermes/plugins/` 밑에 넣고 켜면 됩니다.

```bash
git clone https://github.com/whatfontisthis/hermes-kr-doctor ~/.hermes/plugins/hermes-kr-doctor
hermes plugins enable hermes-kr-doctor
```

그러면 세 군데서 같은 진단을 부를 수 있습니다.

- 터미널에서 `hermes doctor-kr`
- 텔레그램·디스코드 대화창에서 `/닥터`
- 에이전트가 스스로. "봇이 대답을 안 해" 같은 말을 들으면 `kr_doctor` 도구를 직접 호출합니다.

## 점검하는 9가지

| 항목 | 잡아내는 증상 |
| --- | --- |
| Hermes 홈 폴더 | `~/.hermes`가 없거나 `config.yaml`이 깨졌습니다. |
| hermes 명령 | 앱은 깔렸는데 터미널 명령이 없습니다. 게이트웨이 설정을 못 합니다. |
| 윈도우 제어된 폴더 액세스 | 파일 작업만 오류 없이 조용히 실패합니다. |
| 게이트웨이 | 메신저로 말을 걸어도 답이 없습니다. |
| 메신저 연결 | 플랫폼은 켜 뒀는데 봇 토큰이 없습니다. |
| 허용 사용자 잠금 | 허용 목록이 비어 있어 아무나 내 봇에게 명령할 수 있습니다. |
| 디스코드 Message Content Intent | 봇은 온라인인데 사람 말이 내용 없이 도착합니다. |
| 한글 경로·인코딩 | 코드페이지 949 때문에 로그가 깨져 읽을 수 없습니다. |
| 토큰 평문 노출 | 봇 토큰이 로그나 설정 파일에 그대로 남아 있습니다. |

### 왜 설정값을 안 읽고 직접 해보는가

윈도우 '제어된 폴더 액세스'는 레지스트리 값만 봐서는 판단이 안 됩니다. 기능이 켜져 있어도
지금 Hermes를 돌리는 그 파이썬이 허용 목록에 있으면 아무 문제가 없고, 반대로 꺼져 있다고
읽혔는데 실제로는 막히는 경우도 있습니다.

그래서 이 도구는 설정을 읽는 대신 문서 폴더에 임시 파일을 실제로 써 봅니다. `PermissionError`가
나면 그게 답입니다. 파일은 바로 지웁니다.

같은 이유로 토큰 노출 검사도 "설정이 안전한가"가 아니라 "파일 안에 토큰 모양 문자열이
실제로 있는가"를 봅니다.

### 판정 기준

- `[ X ]` 조치 필요. 이것 때문에 지금 안 돌고 있거나, 보안이 열려 있습니다.
- `[ ! ]` 확인 권장. 지금 당장 고장은 아니지만 곧 문제가 됩니다.
- `[ - ]` 해당 없음. 안 쓰는 기능이거나 확인할 방법이 없습니다.

## 어디서 나왔나

점검 항목은 제가 쓴 [Hermes 에이전트 설치 매뉴얼](https://autofrog.kr/lab)의 부록 A(트러블슈팅)와
부록 B(보안 수칙)를 코드로 옮긴 것입니다. 윈도우 PC에 직접 설치하면서 실제로 막혔던 것들이고,
매뉴얼에는 그 화면이 그대로 들어 있습니다. 각 진단 결과에 붙는 절 번호는 그 매뉴얼의 위치입니다.

매뉴얼은 사람이 읽고 고치는 것이고, 이 도구는 같은 내용을 기계가 확인해 주는 것입니다.

## 의존성

없습니다. `kr_doctor.py`는 표준 라이브러리만 씁니다. 진단이 가장 필요한 순간은 환경이
망가져 있을 때라, 그때 `pip install`이 필요하면 안 됩니다.

PyYAML이 깔려 있으면 `config.yaml`을 그걸로 읽고, 없으면 필요한 키만 읽는 간이 파서로
넘어갑니다.

## 테스트

```bash
python -m unittest discover -s tests
```

## 기여

버그 제보와 새 점검 항목 제안을 환영합니다. 특히 윈도우·맥에서 겪은 한국어 환경 문제를
이슈로 남겨 주시면 점검 항목으로 만들겠습니다. 증상, 그때 뜬 메시지, OS 버전을 같이 적어 주세요.

---

## English

A Korean-language setup doctor for [Hermes](https://github.com/NousResearch/hermes-agent).

Hermes installs cleanly most of the time. When it doesn't, Windows tends to fail quietly:
file writes silently no-op under Controlled Folder Access, the Discord bot shows as online
but receives empty message content, and console output arrives mojibaked under code page 949.
None of these produce an error a Korean beginner can act on.

This tool runs nine checks and prints what to do about each one in Korean. It ships as a
Hermes plugin (`hermes doctor-kr`, `/닥터`, and a `kr_doctor` tool the agent can call itself)
but `kr_doctor.py` also runs as a plain script with no third-party imports, because the
moment you need a diagnosis is the moment `pip install` is not an option.

Two checks reproduce the symptom instead of reading a setting. Controlled Folder Access is
detected by writing a probe file into `~/Documents` and catching `PermissionError`, since the
registry value alone does not say whether the interpreter running Hermes is on the allow list.
Token exposure is detected by scanning config and log files for credential-shaped strings
rather than by asking whether the configuration looks safe.

The checks are transcriptions of the failure modes I hit while writing a 61-page Korean
install manual for Hermes, published free at [autofrog.kr/lab](https://autofrog.kr/lab).
Each finding cites the manual section that covers it.

MIT licensed. Issues and new checks welcome, especially failures seen on Korean-locale Windows.
