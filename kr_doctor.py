# -*- coding: utf-8 -*-
"""hermes-kr-doctor — Hermes 설치 상태를 한국어로 진단합니다.

Standalone by design: this module imports nothing outside the standard library
so it can run BEFORE Hermes is working, which is exactly when it is needed.

    python kr_doctor.py            # 진단
    python kr_doctor.py --fix      # 자동으로 고칠 수 있는 것만 조치
    python kr_doctor.py --json     # 기계 판독용

Each check carries a `docs` link to the vendor page that explains the setting
it found, so a finding is something the reader can go verify.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

__version__ = "0.1.0"

OK = "ok"
WARN = "warn"
FAIL = "fail"
SKIP = "skip"

# Worst first, so the thing to act on is the thing you read first.
STATUS_ORDER = {FAIL: 0, WARN: 1, OK: 2, SKIP: 3}

# Token env var per platform, mirroring gateway/config.py:PLATFORM_TOKEN_ENV_NAMES.
PLATFORM_TOKEN_ENV = {
    "telegram": "TELEGRAM_BOT_TOKEN",
    "discord": "DISCORD_BOT_TOKEN",
    "slack": "SLACK_BOT_TOKEN",
    "mattermost": "MATTERMOST_TOKEN",
    "matrix": "MATRIX_ACCESS_TOKEN",
    "weixin": "WEIXIN_TOKEN",
}

PLATFORM_LABEL = {
    "telegram": "텔레그램",
    "discord": "디스코드",
    "slack": "슬랙",
    "mattermost": "Mattermost",
    "matrix": "Matrix",
    "weixin": "위챗",
}

# Shapes that identify a real credential in a haystack. Deliberately narrow:
# a false positive here tells someone to rotate a token for no reason.
SECRET_PATTERNS = [
    # Telegram's documented shape is <id>:<35 chars>; the length is widened a
    # little because missing a real leak costs more than one extra prompt to
    # rotate, and the digits-then-colon prefix already rules out prose.
    ("telegram_bot_token", re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{32,45}\b")),
    ("discord_bot_token", re.compile(r"\b[A-Za-z0-9_-]{24,28}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,40}\b")),
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("anthropic_api_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("slack_bot_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
]


# Vendor pages a finding can point at. Checked by hand; if one 404s, that is a bug.
HERMES_INSTALL = "hermes-agent.nousresearch.com"
DISCORD_INTENTS = "docs.discord.com/developers/events/gateway"
MS_CFA_OVERVIEW = "learn.microsoft.com/defender-endpoint/controlled-folder-access-overview"
MS_CFA_CONFIGURE = "learn.microsoft.com/defender-endpoint/controlled-folder-access-configure"
MS_UTF8 = "learn.microsoft.com/windows/apps/design/globalizing/use-utf8-code-page"

_HANGUL_START, _HANGUL_END = 0xAC00, 0xD7A3


def particle(word: str, pair: str = "이/가") -> str:
    """The Korean particle that agrees with `word`'s final consonant.

    `pair` is written final-consonant-first, the way the forms are conventionally
    cited: 이/가, 은/는, 을/를, 과/와. Non-Hangul endings (a bare filename, say)
    fall back to the both-forms spelling rather than guessing wrong.
    """
    with_final, without_final = pair.split("/")
    last = word[-1] if word else ""
    if _HANGUL_START <= ord(last or "\0") <= _HANGUL_END:
        return with_final if (ord(last) - _HANGUL_START) % 28 else without_final
    return f"{with_final}({without_final})"


@dataclass
class Finding:
    """One diagnosis. `detail` says what was observed, `fix` says what to do."""

    id: str
    title: str
    status: str
    detail: str
    fix: str = ""
    command: str = ""
    docs: str = ""
    auto_fixed: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "fix": self.fix,
            "command": self.command,
            "docs": self.docs,
            "auto_fixed": self.auto_fixed,
        }


@dataclass
class Env:
    """Everything the checks read, gathered once."""

    home: Path
    home_exists: bool
    config: Dict[str, Any] = field(default_factory=dict)
    config_error: str = ""
    dotenv: Dict[str, str] = field(default_factory=dict)
    is_windows: bool = field(default_factory=lambda: os.name == "nt")

    @property
    def dotenv_path(self) -> Path:
        return self.home / ".env"

    @property
    def config_path(self) -> Path:
        return self.home / "config.yaml"

    def enabled_platforms(self) -> List[str]:
        """Platforms the user actually turned on, from config.yaml or a token in .env."""
        found: List[str] = []
        platforms = self.config.get("platforms")
        if isinstance(platforms, dict):
            for name, block in platforms.items():
                if isinstance(block, dict) and block.get("enabled"):
                    found.append(str(name).lower())
        for name, env_key in PLATFORM_TOKEN_ENV.items():
            if name not in found and self.lookup(env_key):
                found.append(name)
        return found

    def lookup(self, key: str) -> str:
        """Env var value, preferring the real process env over the .env file."""
        return (os.environ.get(key) or self.dotenv.get(key) or "").strip()


# --------------------------------------------------------------------------
# environment gathering
# --------------------------------------------------------------------------


def hermes_home() -> Path:
    raw = os.environ.get("HERMES_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".hermes"


def parse_dotenv(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _shallow_yaml(text: str) -> Dict[str, Any]:
    """Enough YAML for `platforms.<name>.enabled` when PyYAML is not installed.

    Indentation-based, scalars only, no anchors or flow style. It exists so the
    doctor still says something useful on a bare Python with no site-packages.
    """
    root: Dict[str, Any] = {}
    stack: List[tuple] = [(-1, root)]
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if line.startswith("- ") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.split(" #")[0].strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else root
        if not isinstance(parent, dict):
            continue
        if value == "":
            child: Dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            parent[key] = value[1:-1]
        elif value.lower() in ("true", "false"):
            parent[key] = value.lower() == "true"
        elif value.lower() in ("null", "~"):
            parent[key] = None
        else:
            try:
                parent[key] = int(value)
            except ValueError:
                parent[key] = value
    return root


def load_config(path: Path) -> tuple:
    if not path.exists():
        return {}, ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {}, str(exc)
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
        return (data if isinstance(data, dict) else {}), ""
    except ImportError:
        return _shallow_yaml(text), ""
    except Exception as exc:  # malformed YAML is itself a finding
        return {}, str(exc)


def gather() -> Env:
    home = hermes_home()
    config, config_error = load_config(home / "config.yaml")
    return Env(
        home=home,
        home_exists=home.is_dir(),
        config=config,
        config_error=config_error,
        dotenv=parse_dotenv(home / ".env"),
    )


def _run(cmd: List[str], timeout: int = 20) -> tuple:
    """(returncode, stdout+stderr). Returns (-1, reason) when the command cannot run."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        return -1, "명령을 찾을 수 없습니다"
    except subprocess.TimeoutExpired:
        return -1, "시간 초과"
    except OSError as exc:
        return -1, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _powershell(script: str, timeout: int = 20) -> tuple:
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return -1, "PowerShell을 찾을 수 없습니다"
    return _run([exe, "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout)


def hermes_executable() -> Optional[str]:
    return shutil.which("hermes")


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------


def check_hermes_home(env: Env) -> Finding:
    if not env.home_exists:
        return Finding(
            id="hermes_home",
            title="Hermes 홈 폴더",
            status=FAIL,
            detail=f"{env.home} 폴더가 없습니다. Hermes가 아직 한 번도 실행되지 않았습니다.",
            fix="Hermes 앱을 한 번 실행하거나 터미널에서 hermes를 실행해 초기 설정을 만드세요.",
            docs=HERMES_INSTALL,
        )
    if env.config_error:
        return Finding(
            id="hermes_home",
            title="Hermes 홈 폴더",
            status=FAIL,
            detail=f"config.yaml을 읽지 못했습니다: {env.config_error}",
            fix="config.yaml의 들여쓰기가 깨졌을 가능성이 큽니다. 백업 후 hermes setup을 다시 실행하세요.",
            docs=HERMES_INSTALL,
        )
    if not env.config_path.exists():
        return Finding(
            id="hermes_home",
            title="Hermes 홈 폴더",
            status=WARN,
            detail=f"{env.home} 폴더는 있지만 config.yaml이 없습니다.",
            fix="설정이 아직 저장되지 않았습니다. 앱에서 두뇌(AI 공급자) 연결까지 마치세요.",
            docs=HERMES_INSTALL,
        )
    return Finding(
        id="hermes_home",
        title="Hermes 홈 폴더",
        status=OK,
        detail=f"{env.home} · config.yaml 읽기 성공",
    )


def check_hermes_cli(env: Env) -> Finding:
    path = hermes_executable()
    if path:
        code, out = _run([path, "--version"], timeout=30)
        version = out.strip().splitlines()[0] if code == 0 and out.strip() else "버전 확인 실패"
        return Finding(
            id="hermes_cli",
            title="hermes 명령",
            status=OK,
            detail=f"{path} · {version}",
        )
    desktop_hints = (
        [Path.home() / "AppData/Local/Programs/Hermes"]
        if env.is_windows
        else [Path("/Applications/Hermes.app"), Path.home() / ".local/share/Hermes"]
    )
    if any(p.exists() for p in desktop_hints):
        return Finding(
            id="hermes_cli",
            title="hermes 명령",
            status=WARN,
            detail="데스크톱 앱은 설치돼 있지만 터미널에서 hermes 명령을 쓸 수 없습니다.",
            fix="게이트웨이 설정·상태 확인은 터미널 명령이 필요합니다. 앱 설정에서 CLI 설치를 켜거나 아래 명령으로 설치하세요.",
            command="curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash",
            docs=HERMES_INSTALL,
        )
    return Finding(
        id="hermes_cli",
        title="hermes 명령",
        status=WARN,
        detail="hermes 명령을 찾을 수 없습니다. PATH에 없거나 설치되지 않았습니다.",
        fix="데스크톱 앱을 설치했다면 앱을 한 번 실행해 주세요. 터미널로 설치하려면 아래 명령을 쓰세요.",
        command="curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash",
        docs=HERMES_INSTALL,
    )


def _protected_folder_candidates() -> List[Path]:
    """Folders Controlled Folder Access guards by default.

    Taken from Microsoft's published list, which is Documents, Favorites, Music,
    Pictures and Videos. Desktop is NOT on it, so probing there proves nothing.
    OneDrive Known Folder Move relocates these, and CFA follows them, so the
    OneDrive copies are probed too.
    """
    names = ["Documents", "Favorites", "Music", "Pictures", "Videos"]
    roots = [Path.home()]
    try:
        roots += [p for p in Path.home().glob("OneDrive*") if p.is_dir()]
    except OSError:
        pass
    return [root / n for root in roots for n in names if (root / n).is_dir()]


def check_controlled_folder_access(env: Env) -> Finding:
    """Windows Controlled Folder Access blocking the interpreter.

    Hermes surfaces the block as a silent no-op, so we reproduce the symptom
    instead of inferring it from settings: the registry value alone does not say
    whether THIS interpreter is on the allow list, and the allow list itself is
    unreadable without administrator rights.
    """
    if not env.is_windows:
        return Finding(
            id="controlled_folder_access",
            title="윈도우 제어된 폴더 액세스",
            status=SKIP,
            detail="윈도우가 아니므로 해당 없음",
        )

    blocked: List[str] = []
    for folder in _protected_folder_candidates():
        probe = folder / f".hermes-kr-doctor-{os.getpid()}.tmp"
        try:
            probe.write_text("probe", encoding="utf-8")
        except PermissionError:
            blocked.append(folder.name)
            continue
        except OSError:
            continue
        finally:
            try:
                probe.unlink()
            except OSError:
                pass

    code, out = _powershell("(Get-MpPreference).EnableControlledFolderAccess")
    setting = out.strip() if code == 0 else ""
    enabled = setting.startswith("1")

    if blocked:
        folders = ", ".join(blocked)
        return Finding(
            id="controlled_folder_access",
            title="윈도우 제어된 폴더 액세스",
            status=FAIL,
            detail=f"지금 이 파이썬({sys.executable})이 {folders} 폴더에 파일을 쓰지 못했습니다. "
            "Hermes의 파일 작업이 오류 없이 조용히 실패하는 바로 그 증상입니다.",
            fix="Windows 보안 → 바이러스 및 위협 방지 → 랜섬웨어 방지 → 보호 기록에서 차단된 기록을 모두 "
            "'디바이스에서 허용'으로 바꾸세요. 차단 기록이 여러 건이면 전부 허용해야 합니다.",
            command=f'Add-MpPreference -ControlledFolderAccessAllowedApplication "{sys.executable}"',
            docs=MS_CFA_CONFIGURE,
        )
    if enabled:
        return Finding(
            id="controlled_folder_access",
            title="윈도우 제어된 폴더 액세스",
            status=WARN,
            detail="기능이 켜져 있지만 지금 이 파이썬은 막히지 않았습니다. "
            "Hermes가 다른 파이썬으로 돌고 있다면 그쪽은 막힐 수 있습니다.",
            fix="Hermes 파일 작업이 조용히 실패하면 보호 기록을 먼저 확인하세요.",
            docs=MS_CFA_OVERVIEW,
        )
    return Finding(
        id="controlled_folder_access",
        title="윈도우 제어된 폴더 액세스",
        status=OK,
        detail="파일 쓰기 테스트 통과" + (" · 기능 꺼짐" if setting.startswith("0") else ""),
    )


def check_gateway(env: Env) -> Finding:
    """A dead gateway: the bot is configured but nothing answers."""
    exe = hermes_executable()
    if exe:
        code, out = _run([exe, "gateway", "status"], timeout=45)
        if code == 0:
            first = next((l for l in out.splitlines() if l.strip()), "").strip()
            return Finding(
                id="gateway",
                title="게이트웨이",
                status=OK,
                detail=first or "hermes gateway status 정상",
            )
        if code > 0:
            return Finding(
                id="gateway",
                title="게이트웨이",
                status=FAIL,
                detail="hermes gateway status가 정상 응답하지 않았습니다. 메신저로 말을 걸어도 답이 없습니다.",
                fix="게이트웨이를 다시 설정하거나 PC를 재부팅하세요. 자동 시작이 등록돼 있으면 스스로 올라옵니다.",
                command="hermes gateway setup",
                docs=HERMES_INSTALL,
            )

    if env.is_windows:
        code, out = _run(["tasklist"], timeout=30)
    else:
        code, out = _run(["ps", "ax"], timeout=30)
    if code == 0 and re.search(r"hermes", out, re.IGNORECASE):
        return Finding(
            id="gateway",
            title="게이트웨이",
            status=WARN,
            detail="hermes 관련 프로세스는 떠 있지만 상태를 확인할 수 없었습니다(hermes 명령 없음).",
            fix="정확한 확인은 터미널 명령이 필요합니다.",
            command="hermes gateway status",
            docs=HERMES_INSTALL,
        )
    return Finding(
        id="gateway",
        title="게이트웨이",
        status=SKIP,
        detail="hermes 명령이 없어 확인하지 못했습니다.",
        fix="hermes 명령을 설치한 뒤 다시 진단하세요.",
        docs=HERMES_INSTALL,
    )


def check_platform_tokens(env: Env) -> Finding:
    platforms = env.enabled_platforms()
    if not platforms:
        return Finding(
            id="platform_tokens",
            title="메신저 연결",
            status=WARN,
            detail="텔레그램·디스코드 등 메신저가 하나도 연결돼 있지 않습니다.",
            fix="폰에서 비서를 부르려면 메신저를 하나 연결하세요. 텔레그램이 가장 간단합니다.",
            docs=HERMES_INSTALL,
        )
    missing = [p for p in platforms if not env.lookup(PLATFORM_TOKEN_ENV.get(p, ""))]
    labels = ", ".join(PLATFORM_LABEL.get(p, p) for p in platforms)
    if missing:
        names = ", ".join(PLATFORM_LABEL.get(p, p) for p in missing)
        return Finding(
            id="platform_tokens",
            title="메신저 연결",
            status=FAIL,
            detail=f"{names}{particle(names)} 켜져 있지만 봇 토큰이 없습니다.",
            fix="토큰을 재발급해 등록하세요. 텔레그램은 BotFather에서 /revoke, 디스코드는 개발자 포털 → 봇 → 토큰 초기화입니다.",
            docs=HERMES_INSTALL,
        )
    return Finding(
        id="platform_tokens",
        title="메신저 연결",
        status=OK,
        detail=f"연결됨: {labels}",
    )


def check_allowed_users(env: Env) -> Finding:
    """An empty allowlist leaves the bot open to anyone who finds it."""
    platforms = env.enabled_platforms()
    if not platforms:
        return Finding(
            id="allowed_users",
            title="허용 사용자 잠금",
            status=SKIP,
            detail="연결된 메신저가 없어 확인할 것이 없습니다.",
        )
    if env.lookup("GATEWAY_ALLOW_ALL_USERS").lower() in ("1", "true", "yes", "on"):
        return Finding(
            id="allowed_users",
            title="허용 사용자 잠금",
            status=FAIL,
            detail="GATEWAY_ALLOW_ALL_USERS가 켜져 있습니다. 누구나 이 봇에게 명령할 수 있습니다.",
            fix=f"{env.dotenv_path} 에서 GATEWAY_ALLOW_ALL_USERS=false 로 바꾸고, "
            "플랫폼별 허용 사용자 목록에 본인 ID만 넣으세요.",
            docs=HERMES_INSTALL,
        )
    wide_open: List[str] = []
    for name in platforms:
        prefix = name.upper()
        if env.lookup(f"{prefix}_ALLOW_ALL_USERS").lower() in ("1", "true", "yes", "on"):
            wide_open.append(name)
        elif not env.lookup(f"{prefix}_ALLOWED_USERS"):
            wide_open.append(name)
    if wide_open:
        names = ", ".join(PLATFORM_LABEL.get(p, p) for p in wide_open)
        hint = "\n".join(f"{p.upper()}_ALLOWED_USERS=<내 숫자 ID>" for p in wide_open)
        return Finding(
            id="allowed_users",
            title="허용 사용자 잠금",
            status=FAIL,
            detail=f"{names}의 허용 사용자 목록이 비어 있습니다. 봇이 나만 쓰는 상태가 아닙니다.",
            fix=f"{env.dotenv_path} 에 아래 줄을 넣고 게이트웨이를 재시작하세요. "
            "텔레그램 숫자 ID는 @userinfobot에게 아무 말이나 걸면 알려 줍니다.",
            command=hint,
            docs=HERMES_INSTALL,
        )
    return Finding(
        id="allowed_users",
        title="허용 사용자 잠금",
        status=OK,
        detail="연결된 모든 메신저에 허용 사용자 목록이 설정돼 있습니다.",
    )


def _log_files(env: Env) -> List[Path]:
    logs: List[Path] = []
    for folder in (env.home / "logs", env.home):
        if not folder.is_dir():
            continue
        try:
            logs.extend(p for p in folder.glob("*.log") if p.is_file())
        except OSError:
            continue
    return logs[:20]


def check_discord_intent(env: Env) -> Finding:
    """Bot online but silent, usually a missing Message Content intent."""
    if "discord" not in env.enabled_platforms():
        return Finding(
            id="discord_intent",
            title="디스코드 Message Content Intent",
            status=SKIP,
            detail="디스코드를 쓰지 않습니다.",
        )
    for log in _log_files(env):
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"(message content|MESSAGE_CONTENT).{0,60}(intent|disabled|privileged)", text, re.IGNORECASE):
            return Finding(
                id="discord_intent",
                title="디스코드 Message Content Intent",
                status=FAIL,
                detail=f"{log.name} 로그에 Message Content Intent 관련 경고가 있습니다. "
                "봇은 온라인이지만 사람 말이 내용 없이 도착하고 있습니다.",
                fix="디스코드 개발자 포털 → 내 앱 → Bot → Privileged Gateway Intents에서 "
                "MESSAGE CONTENT INTENT와 SERVER MEMBERS INTENT를 켜고 게이트웨이를 재시작하세요.",
                docs=DISCORD_INTENTS,
            )
    return Finding(
        id="discord_intent",
        title="디스코드 Message Content Intent",
        status=WARN,
        detail="로그에서 문제 흔적은 찾지 못했습니다. 이 설정은 디스코드 쪽에만 있어 PC에서 확인할 수 없습니다.",
        fix="봇이 온라인인데 대답이 없다면 개발자 포털 → Bot → Privileged Gateway Intents에서 "
        "MESSAGE CONTENT INTENT가 켜져 있는지 먼저 보세요. 서버 채널에서는 @봇이름 멘션이 필요합니다.",
        docs=DISCORD_INTENTS,
    )


def check_korean_path(env: Env) -> Finding:
    """Non-ASCII paths plus a cp949 console are a quiet, hard-to-read failure."""
    problems: List[str] = []
    fixes: List[str] = []

    home_str = str(env.home)
    if not home_str.isascii():
        problems.append(f"Hermes 홈 경로에 한글/비ASCII 문자가 있습니다: {home_str}")
        fixes.append("HERMES_HOME을 C:\\hermes 같은 영문 경로로 옮기면 인코딩 문제가 사라집니다.")

    if env.is_windows:
        code, out = _run(["chcp.com"], timeout=15)
        if code != 0:
            code, out = _powershell("(Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Nls\\CodePage').ACP")
        if code == 0 and re.search(r"\b949\b", out):
            problems.append("콘솔 코드페이지가 949(euc-kr)입니다. 로그와 오류 메시지가 깨져 보입니다.")
            fixes.append("설정 → 시간 및 언어 → 언어 및 지역 → 관리자 언어 설정 → 시스템 로캘 변경에서 "
                         "'베타: 세계 언어 지원을 위해 Unicode UTF-8 사용'을 켜고 재부팅하세요.")

    enc = (sys.getfilesystemencoding() or "").lower()
    if enc not in ("utf-8", "utf8", ""):
        problems.append(f"파이썬 파일시스템 인코딩이 {enc}입니다.")
        fixes.append("PYTHONUTF8=1 환경 변수를 설정하면 즉시 완화됩니다.")

    if not problems:
        return Finding(
            id="korean_path",
            title="한글 경로·인코딩",
            status=OK,
            detail=f"경로 ASCII · 파일시스템 인코딩 {enc or 'utf-8'}",
        )
    return Finding(
        id="korean_path",
        title="한글 경로·인코딩",
        status=WARN,
        detail=" / ".join(problems),
        fix=" ".join(fixes),
        docs=MS_UTF8,
    )


def _iter_scan_targets(env: Env) -> List[Path]:
    """Files worth scanning for a leaked token — small text files near the config."""
    targets: List[Path] = []
    if not env.home_exists:
        return targets
    suffixes = {".yaml", ".yml", ".json", ".txt", ".md", ".log", ".ini", ".conf"}
    try:
        for path in env.home.rglob("*"):
            if len(targets) >= 400:
                break
            if not path.is_file() or path.name == ".env":
                continue
            if path.suffix.lower() not in suffixes:
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    continue
            except OSError:
                continue
            targets.append(path)
    except OSError:
        pass
    return targets


# Well-known SIDs that mean "somebody other than me". Matched by SID rather than
# display name because those are localized ("Users" is "사용자" on Korean Windows).
_SHARED_SIDS = {
    "S-1-1-0": "Everyone",
    "S-1-5-11": "인증된 사용자",
    "S-1-5-32-545": "Users 그룹",
    "S-1-5-32-546": "Guests 그룹",
}


def _over_shared(path: Path) -> str:
    """Who besides the owner can read this file. Empty string means nobody."""
    if os.name != "nt":
        try:
            mode = path.stat().st_mode
        except OSError:
            return ""
        readers = []
        if mode & stat.S_IRGRP:
            readers.append("같은 그룹 사용자")
        if mode & stat.S_IROTH:
            readers.append("모든 사용자")
        return ", ".join(readers)

    script = (
        f"(Get-Acl -LiteralPath '{path}').Access | ForEach-Object {{ "
        "try { $_.IdentityReference.Translate("
        "[System.Security.Principal.SecurityIdentifier]).Value } catch { '' } }"
    )
    code, out = _powershell(script, timeout=25)
    if code != 0:
        return ""
    found = {_SHARED_SIDS[sid] for sid in (l.strip() for l in out.splitlines()) if sid in _SHARED_SIDS}
    return ", ".join(sorted(found))


def _tighten_permissions(path: Path) -> str:
    """Restrict the file to its owner. Returns a Korean description of what happened."""
    if os.name != "nt":
        os.chmod(path, 0o600)
        return f"{path} 권한을 600으로 좁혔습니다."
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if not user:
        raise OSError("현재 사용자 이름을 알 수 없습니다")
    code, out = _run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
        timeout=30,
    )
    if code != 0:
        raise OSError(out.strip() or "icacls 실패")
    return f"{path} 를 {user} 본인만 읽도록 좁혔습니다."


def check_token_exposure(env: Env) -> Finding:
    """Look for credential-shaped strings where they should never be."""
    leaks: List[str] = []
    for path in _iter_scan_targets(env):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for kind, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                leaks.append(f"{path.relative_to(env.home)} ({kind})")
                break

    dotenv = env.dotenv_path
    shared_with = _over_shared(dotenv) if dotenv.exists() else ""

    if leaks:
        return Finding(
            id="token_exposure",
            title="토큰 평문 노출",
            status=FAIL,
            detail="설정·로그 파일에서 토큰으로 보이는 문자열을 찾았습니다: " + ", ".join(leaks[:5]),
            fix="망설이지 말고 지금 재발급하세요. 재발급하는 순간 이전 토큰은 무효가 됩니다. "
            "텔레그램은 BotFather에서 /revoke, 디스코드는 개발자 포털 → 봇 → 토큰 초기화입니다. "
            "토큰은 .env에만 두고, 로그·문서·채팅창에는 절대 남기지 마세요.",
            docs=HERMES_INSTALL,
        )
    if shared_with:
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "내계정"
        command = (
            f'icacls "{dotenv}" /inheritance:r /grant:r "{user}:F"'
            if env.is_windows
            else f"chmod 600 {dotenv}"
        )
        return Finding(
            id="token_exposure",
            title="토큰 평문 노출",
            status=WARN,
            detail=f"{dotenv} 파일을 {shared_with}도 읽을 수 있습니다. 이 파일 안에 봇 토큰이 들어 있습니다.",
            fix="파일 권한을 본인만 읽도록 좁히세요. --fix 옵션을 붙이면 자동으로 조치합니다.",
            command=command,
            docs=HERMES_INSTALL,
        )
    if not dotenv.exists():
        return Finding(
            id="token_exposure",
            title="토큰 평문 노출",
            status=SKIP,
            detail=".env 파일이 없어 검사할 것이 없습니다.",
        )
    return Finding(
        id="token_exposure",
        title="토큰 평문 노출",
        status=OK,
        detail="설정·로그 파일에서 평문 토큰을 찾지 못했습니다.",
    )


CHECKS: List[Callable[[Env], Finding]] = [
    check_hermes_home,
    check_hermes_cli,
    check_controlled_folder_access,
    check_gateway,
    check_platform_tokens,
    check_allowed_users,
    check_discord_intent,
    check_korean_path,
    check_token_exposure,
]


def run_checks(env: Optional[Env] = None) -> List[Finding]:
    env = env or gather()
    findings: List[Finding] = []
    for check in CHECKS:
        try:
            findings.append(check(env))
        except Exception as exc:  # a broken check must not hide the other eight
            findings.append(
                Finding(
                    id=getattr(check, "__name__", "unknown"),
                    title="진단 항목 오류",
                    status=WARN,
                    detail=f"{check.__name__} 검사 중 오류: {exc}",
                )
            )
    return findings


# --------------------------------------------------------------------------
# auto-fix
# --------------------------------------------------------------------------


def apply_fixes(env: Env, findings: List[Finding]) -> List[Finding]:
    """Only touches things that are safe and reversible. Everything else stays advice."""
    for finding in findings:
        if finding.id == "token_exposure" and finding.status == WARN:
            try:
                finding.auto_fixed = _tighten_permissions(env.dotenv_path)
                finding.status = OK
            except OSError as exc:
                finding.auto_fixed = f"권한 변경 실패: {exc}"
    return findings


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

_MARK = {OK: "[ OK ]", WARN: "[ !  ]", FAIL: "[ X  ]", SKIP: "[ -  ]"}
_COLOR = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m", SKIP: "\033[90m"}
_RESET = "\033[0m"


def _use_color() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _wrap(text: str, width: int = 76, indent: str = "       ") -> str:
    """Wrap on spaces without splitting Korean words awkwardly."""
    out: List[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            if line and len(line) + len(word) + 1 > width:
                out.append(indent + line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            out.append(indent + line)
    return "\n".join(out)


def render(findings: List[Finding], home: Path) -> str:
    color = _use_color()
    lines = [
        "",
        "  Hermes 설치 진단 (hermes-kr-doctor v%s)" % __version__,
        "  홈: %s" % home,
        "  " + "-" * 74,
        "",
    ]
    for finding in findings:
        mark = _MARK[finding.status]
        if color:
            mark = f"{_COLOR[finding.status]}{mark}{_RESET}"
        suffix = f"  ({finding.docs})" if finding.docs else ""
        lines.append(f"  {mark} {finding.title}{suffix}")
        lines.append(_wrap(finding.detail))
        if finding.auto_fixed:
            lines.append(_wrap("고침: " + finding.auto_fixed))
        elif finding.status in (FAIL, WARN) and finding.fix:
            lines.append(_wrap("→ " + finding.fix))
        if finding.command and finding.status in (FAIL, WARN):
            for cmd in finding.command.split("\n"):
                lines.append(f"         $ {cmd}")
        lines.append("")

    counts = {s: sum(1 for f in findings if f.status == s) for s in (FAIL, WARN, OK, SKIP)}
    lines.append("  " + "-" * 74)
    lines.append(
        "  조치 필요 %d건 · 확인 권장 %d건 · 정상 %d건 · 해당 없음 %d건"
        % (counts[FAIL], counts[WARN], counts[OK], counts[SKIP])
    )
    if counts[FAIL] == 0 and counts[WARN] == 0:
        lines.append("  문제 없습니다. 메신저에서 봇에게 말을 걸어 보세요.")
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hermes-kr-doctor",
        description="Hermes 설치 상태를 한국어로 진단합니다.",
    )
    parser.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    parser.add_argument("--fix", action="store_true", help="자동으로 고칠 수 있는 항목을 조치")
    parser.add_argument("--version", action="version", version=f"hermes-kr-doctor {__version__}")
    args = parser.parse_args(argv)

    env = gather()
    findings = run_checks(env)
    if args.fix:
        findings = apply_fixes(env, findings)
    findings.sort(key=lambda f: STATUS_ORDER[f.status])

    if args.json:
        payload = {
            "version": __version__,
            "hermes_home": str(env.home),
            "findings": [f.to_dict() for f in findings],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render(findings, env.home))

    return 1 if any(f.status == FAIL for f in findings) else 0


if __name__ == "__main__":
    # Korean Windows consoles still default to cp949; the doctor's own output
    # must not be the first thing that breaks.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if os.name == "nt" and callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass
    sys.exit(main())
