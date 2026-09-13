# -*- coding: utf-8 -*-
"""Tests for hermes-kr-doctor. Standard library only, like the module itself."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import kr_doctor  # noqa: E402


def make_env(tmp: Path, config: str = "", dotenv: str = "") -> kr_doctor.Env:
    home = tmp / ".hermes"
    home.mkdir(exist_ok=True)
    if config:
        (home / "config.yaml").write_text(config, encoding="utf-8")
    if dotenv:
        (home / ".env").write_text(dotenv, encoding="utf-8")
    parsed, error = kr_doctor.load_config(home / "config.yaml")
    return kr_doctor.Env(
        home=home,
        home_exists=True,
        config=parsed,
        config_error=error,
        dotenv=kr_doctor.parse_dotenv(home / ".env"),
    )


class ParsingTests(unittest.TestCase):
    def test_dotenv_strips_quotes_and_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                '# comment\nTELEGRAM_BOT_TOKEN="abc123"\nEMPTY=\nDISCORD_BOT_TOKEN=plain\n',
                encoding="utf-8",
            )
            values = kr_doctor.parse_dotenv(path)
        self.assertEqual(values["TELEGRAM_BOT_TOKEN"], "abc123")
        self.assertEqual(values["DISCORD_BOT_TOKEN"], "plain")
        self.assertEqual(values["EMPTY"], "")
        self.assertNotIn("# comment", values)

    def test_shallow_yaml_reads_nested_enabled_flag(self):
        data = kr_doctor._shallow_yaml(
            "platforms:\n"
            "  telegram:\n"
            "    enabled: true\n"
            "  discord:\n"
            "    enabled: false\n"
            "gateway:\n"
            "  port: 8080\n"
        )
        self.assertTrue(data["platforms"]["telegram"]["enabled"])
        self.assertFalse(data["platforms"]["discord"]["enabled"])
        self.assertEqual(data["gateway"]["port"], 8080)

    def test_enabled_platforms_from_config_and_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = make_env(
                Path(tmp),
                config="platforms:\n  telegram:\n    enabled: true\n",
                dotenv="DISCORD_BOT_TOKEN=abc\n",
            )
            platforms = env.enabled_platforms()
        self.assertIn("telegram", platforms)
        self.assertIn("discord", platforms)


# Structurally valid shapes, built rather than typed so the lengths cannot drift.
FAKE_TELEGRAM_TOKEN = "123456789:" + "A" * 35
FAKE_OPENAI_KEY = "sk-" + "a" * 32


class ParticleTests(unittest.TestCase):
    def test_agrees_with_final_consonant(self):
        self.assertEqual(kr_doctor.particle("디스코드"), "가")
        self.assertEqual(kr_doctor.particle("텔레그램"), "이")
        self.assertEqual(kr_doctor.particle("슬랙", "은/는"), "은")
        self.assertEqual(kr_doctor.particle("위챗", "을/를"), "을")

    def test_non_hangul_falls_back_to_both_forms(self):
        self.assertEqual(kr_doctor.particle("Matrix"), "이(가)")
        self.assertEqual(kr_doctor.particle(""), "이(가)")

    def test_joined_list_uses_the_last_word(self):
        self.assertEqual(kr_doctor.particle("텔레그램, 디스코드"), "가")


class SecretPatternTests(unittest.TestCase):
    def test_detects_telegram_and_openai_shapes(self):
        haystack = f"bot={FAKE_TELEGRAM_TOKEN} key={FAKE_OPENAI_KEY}"
        hits = {name for name, pattern in kr_doctor.SECRET_PATTERNS if pattern.search(haystack)}
        self.assertIn("telegram_bot_token", hits)
        self.assertIn("openai_api_key", hits)

    def test_ignores_ordinary_prose(self):
        haystack = "토큰은 채팅창에 붙여넣지 않는다. 재발급은 BotFather에서 /revoke."
        hits = [name for name, pattern in kr_doctor.SECRET_PATTERNS if pattern.search(haystack)]
        self.assertEqual(hits, [])


class CheckTests(unittest.TestCase):
    def test_missing_home_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = kr_doctor.Env(home=Path(tmp) / "nope", home_exists=False)
            finding = kr_doctor.check_hermes_home(env)
        self.assertEqual(finding.status, kr_doctor.FAIL)

    def test_empty_allowlist_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = make_env(
                Path(tmp),
                config="platforms:\n  telegram:\n    enabled: true\n",
                dotenv="TELEGRAM_BOT_TOKEN=abc\n",
            )
            os.environ.pop("TELEGRAM_ALLOWED_USERS", None)
            finding = kr_doctor.check_allowed_users(env)
        self.assertEqual(finding.status, kr_doctor.FAIL)
        self.assertIn("TELEGRAM_ALLOWED_USERS", finding.command)

    def test_populated_allowlist_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = make_env(
                Path(tmp),
                config="platforms:\n  telegram:\n    enabled: true\n",
                dotenv="TELEGRAM_BOT_TOKEN=abc\nTELEGRAM_ALLOWED_USERS=12345\n",
            )
            finding = kr_doctor.check_allowed_users(env)
        self.assertEqual(finding.status, kr_doctor.OK)

    def test_allow_all_users_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = make_env(
                Path(tmp),
                config="platforms:\n  telegram:\n    enabled: true\n",
                dotenv="TELEGRAM_BOT_TOKEN=abc\nTELEGRAM_ALLOWED_USERS=1\nGATEWAY_ALLOW_ALL_USERS=true\n",
            )
            finding = kr_doctor.check_allowed_users(env)
        self.assertEqual(finding.status, kr_doctor.FAIL)

    def test_enabled_platform_without_token_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = make_env(Path(tmp), config="platforms:\n  telegram:\n    enabled: true\n")
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            finding = kr_doctor.check_platform_tokens(env)
        self.assertEqual(finding.status, kr_doctor.FAIL)

    def test_token_in_a_log_file_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = make_env(Path(tmp), dotenv="TELEGRAM_BOT_TOKEN=x\n")
            (env.home / "gateway.log").write_text(
                f"connected with {FAKE_TELEGRAM_TOKEN}\n", encoding="utf-8"
            )
            finding = kr_doctor.check_token_exposure(env)
        self.assertEqual(finding.status, kr_doctor.FAIL)
        self.assertIn("gateway.log", finding.detail)

    def test_clean_home_passes_token_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = make_env(Path(tmp), dotenv="TELEGRAM_BOT_TOKEN=x\n")
            (env.home / "notes.md").write_text("토큰은 .env에만 둡니다.\n", encoding="utf-8")
            finding = kr_doctor.check_token_exposure(env)
        self.assertIn(finding.status, (kr_doctor.OK, kr_doctor.WARN))

    def test_discord_check_skips_when_discord_unused(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = make_env(Path(tmp))
            os.environ.pop("DISCORD_BOT_TOKEN", None)
            finding = kr_doctor.check_discord_intent(env)
        self.assertEqual(finding.status, kr_doctor.SKIP)


class RunAndRenderTests(unittest.TestCase):
    def test_every_check_returns_a_known_status(self):
        findings = kr_doctor.run_checks()
        self.assertEqual(len(findings), len(kr_doctor.CHECKS))
        for finding in findings:
            self.assertIn(finding.status, kr_doctor.STATUS_ORDER)
            self.assertTrue(finding.detail, f"{finding.id} has no detail")

    def test_render_produces_korean_summary(self):
        findings = kr_doctor.run_checks()
        text = kr_doctor.render(findings, Path("/tmp/.hermes"))
        self.assertIn("Hermes 설치 진단", text)
        self.assertIn("조치 필요", text)

    def test_json_output_is_valid(self):
        findings = kr_doctor.run_checks()
        payload = json.dumps({"findings": [f.to_dict() for f in findings]}, ensure_ascii=False)
        self.assertEqual(len(json.loads(payload)["findings"]), len(kr_doctor.CHECKS))

class ExitCodeTests(unittest.TestCase):
    """The exit code is the contract scripts depend on: 0 clean, 1 needs action."""

    @staticmethod
    def _run_main(home: Path, *argv: str) -> int:
        previous = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = str(home)
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                return kr_doctor.main(list(argv))
        finally:
            if previous is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = previous

    def test_healthy_install_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".hermes"
            home.mkdir()
            (home / "config.yaml").write_text(
                "platforms:\n  telegram:\n    enabled: true\n", encoding="utf-8"
            )
            (home / ".env").write_text(
                "TELEGRAM_BOT_TOKEN=placeholder\nTELEGRAM_ALLOWED_USERS=12345\n",
                encoding="utf-8",
            )
            for key in ("TELEGRAM_ALLOWED_USERS", "GATEWAY_ALLOW_ALL_USERS"):
                os.environ.pop(key, None)
            self.assertEqual(self._run_main(home, "--json"), 0)

    def test_missing_home_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._run_main(Path(tmp) / "absent", "--json"), 1)

    def test_unlocked_bot_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".hermes"
            home.mkdir()
            (home / "config.yaml").write_text(
                "platforms:\n  telegram:\n    enabled: true\n", encoding="utf-8"
            )
            (home / ".env").write_text("TELEGRAM_BOT_TOKEN=placeholder\n", encoding="utf-8")
            os.environ.pop("TELEGRAM_ALLOWED_USERS", None)
            self.assertEqual(self._run_main(home, "--json"), 1)


if __name__ == "__main__":
    unittest.main()
