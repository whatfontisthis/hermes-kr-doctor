# -*- coding: utf-8 -*-
"""Hermes plugin entry point for hermes-kr-doctor.

Registers three ways into the same diagnosis:

- ``hermes doctor-kr``    — terminal, for when the agent itself will not start
- ``/닥터`` / ``/doctor`` — inside a Telegram or Discord chat
- ``kr_doctor`` tool      — so the agent can diagnose itself when a user says
                            "봇이 대답을 안 해"

All the logic lives in ``kr_doctor.py``, which imports nothing outside the
standard library so it also runs as a plain script before Hermes works.
"""

from __future__ import annotations

import json
from typing import Any

from . import kr_doctor

__version__ = kr_doctor.__version__

KR_DOCTOR_SCHEMA = {
    "name": "kr_doctor",
    "description": (
        "Diagnose this machine's Hermes installation and report problems in Korean. "
        "Use when the user says the bot does not answer, file operations silently fail, "
        "the gateway seems dead, tokens may have leaked, or log output is garbled. "
        "Returns findings with a status of fail/warn/ok/skip and a Korean fix for each."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "fix": {
                "type": "boolean",
                "description": (
                    "Apply the safe, reversible fixes (currently: tighten .env file "
                    "permissions) instead of only reporting them. Default false."
                ),
            }
        },
        "required": [],
    },
}


def _diagnose(fix: bool = False) -> dict:
    env = kr_doctor.gather()
    findings = kr_doctor.run_checks(env)
    if fix:
        findings = kr_doctor.apply_fixes(env, findings)
    findings.sort(key=lambda f: kr_doctor.STATUS_ORDER[f.status])
    return {
        "hermes_home": str(env.home),
        "action_required": sum(1 for f in findings if f.status == kr_doctor.FAIL),
        "findings": [f.to_dict() for f in findings],
    }


def _tool_handler(args: dict, **_kwargs: Any) -> str:
    """Always returns a JSON string, never raises — the plugin tool contract."""
    try:
        return json.dumps(_diagnose(fix=bool(args.get("fix"))), ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 - a crashed tool is worse than a reported one
        return json.dumps({"error": f"진단 중 오류가 발생했습니다: {exc}"}, ensure_ascii=False)


def _slash_handler(raw_args: str) -> str:
    try:
        env = kr_doctor.gather()
        findings = kr_doctor.run_checks(env)
        if raw_args.strip() in ("fix", "--fix", "고쳐"):
            findings = kr_doctor.apply_fixes(env, findings)
        findings.sort(key=lambda f: kr_doctor.STATUS_ORDER[f.status])
        return kr_doctor.render(findings, env.home)
    except Exception as exc:  # noqa: BLE001
        return f"진단 중 오류가 발생했습니다: {exc}"


def _setup_cli(parser: Any) -> None:
    parser.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    parser.add_argument("--fix", action="store_true", help="자동으로 고칠 수 있는 항목을 조치")


def _cli_handler(args: Any) -> int:
    argv = []
    if getattr(args, "json", False):
        argv.append("--json")
    if getattr(args, "fix", False):
        argv.append("--fix")
    return kr_doctor.main(argv)


def register(ctx: Any) -> None:
    ctx.register_tool(
        name="kr_doctor",
        toolset="kr_doctor",
        schema=KR_DOCTOR_SCHEMA,
        handler=_tool_handler,
    )

    for name in ("doctor-kr", "닥터"):
        ctx.register_command(
            name,
            handler=_slash_handler,
            description="Hermes 설치 상태를 한국어로 진단합니다 (fix: 자동 조치)",
        )

    ctx.register_cli_command(
        name="doctor-kr",
        help="Hermes 설치 상태를 한국어로 진단합니다",
        setup_fn=_setup_cli,
        handler_fn=_cli_handler,
    )
