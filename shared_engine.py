"""Shared, provider-agnostic interview engine for the macOS and web pilots."""
import json
import os
import time
import uuid
import hashlib
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any

import requests

DEFAULT_QUESTIONS = [
    ("Q1", "[پرسش نخست پژوهش را در پنل وارد کنید]", 1),
    ("Q2", "آیا نکتهٔ دیگری هست که در پرسش‌ها مطرح نشد و مایل باشید بیان کنید؟", 0),
]
DEFAULT_GOALS = {
    "Q1": "هدف، مفهوم و نوع پاسخ موردنیاز این پرسش را در پنل توضیح دهید.",
    "Q2": "دعوت اختیاری پایانی است؛ پاسخ مثبت یعنی فرد می‌خواهد نکته‌اش را بنویسد، نه این‌که گفت‌وگو تمام شود.",
}
PROTOCOL_VERSION = "2.0-semantic-interview-builder"
SEMANTIC_PROTOCOL_VERSION = "2.0-semantic-interview"
SEMANTIC_INTENTS = {
    "social_greeting", "process_question", "role_boundary_question",
    "research_answer", "clarification_request", "example_request",
    "options_request", "opinion_request", "refusal", "continuation",
    "backtrack", "disengagement", "termination",
}

# This protocol, planner contract, and interviewer contract intentionally mirror
# the Android Pilot.  The web app must not call a single model to both reason
# about a response and improvise the visible Persian turn.
BASE_PROTOCOL = """You are a professional research interviewer. Follow the published study protocol, question order, language, tone, and consent text. Protect participant autonomy: answer brief process questions honestly, never expose internal reasoning, accept a clear request to pause or stop, and never end after a clear willingness to continue. Remain neutral: do not praise, agree with, teach, diagnose, or introduce personal opinions. Interpret the meaning of an answer before deciding whether to probe, simplify, advance, or close. Probe only for a necessary gap stated in the question goal, and never repeat a question already answered. Keep one visible purpose per message and at most one question."""

PLANNER_SYSTEM = BASE_PROTOCOL + """\n\nYou are the silent conversation moderator. Return only valid JSON: {"action":"advance|probe|simplify|repeat|repair|close","focus":"brief necessary gap or empty","terminationIntent":"none|explicit","engagement":"engaged|possible_mocking|disengaged","reason":"brief label"}. Treat short but meaningful answers as valid. A hostile tone alone is not a withdrawal. For repeated deliberate derailment, offer one gentle repair; close only after explicit withdrawal, continued disengagement after repair, or the final invitation."""

INTERVIEWER_SYSTEM = BASE_PROTOCOL + """\n\nWrite only the participant-facing message in the study language and tone. For a probe, ask about one necessary ambiguity using the participant's own wording. For simplify, rephrase rather than repeat. For repair, be brief, respectful and offer the choice to skip or stop. Do not ask a research question in repair. Do not output JSON, headings, analysis or internal labels."""

FAST_GUIDED_SYSTEM = BASE_PROTOCOL + """\n\nAct as moderator and interviewer. Return only valid JSON: {"action":"advance|probe|simplify|repeat|repair|close","message":"participant-facing text only when needed","terminationIntent":"none|explicit","engagement":"engaged|possible_mocking|disengaged","reason":"brief label"}. Use the configured study language."""

SEMANTIC_CONTROLLER_CONTRACT = """\n\nSemantic controller v2. Before routing every message, classify one intent: social_greeting, process_question, role_boundary_question, research_answer, clarification_request, example_request, options_request, opinion_request, refusal, continuation, backtrack, disengagement, termination. Return a short meaning_summary, is_research_evidence, evidence_quotes, current_question_open, next_action, and confidence in addition to action. Social, process, role-boundary, clarification, example, options, opinion, and continuation turns are not research evidence and keep the current question open. Answer process questions only from STUDY METADATA. If asked for your personal view, state that you are the interviewer and have no independent personal position, then return control to the participant. Short meaningful answers are evidence. Offer genuinely different simplifications, up to three meaningful attempts and one skip offer. Do not expose reasoning or internal labels."""
PLANNER_SYSTEM += SEMANTIC_CONTROLLER_CONTRACT
FAST_GUIDED_SYSTEM += SEMANTIC_CONTROLLER_CONTRACT

# The autonomous option uses the same provider-neutral engine but gives the
# model more room to use recent context when selecting one purposeful probe.
# Question order, consent, and participant-safety boundaries remain enforced
# by the server rather than delegated to the model.
CONVERSATIONAL_LEAD_SYSTEM = BASE_PROTOCOL + """\n\nAct as a conversational research lead. Return only valid JSON: {"action":"advance|probe|simplify|repeat|repair|close","focus":"brief necessary gap or empty","terminationIntent":"none|explicit","engagement":"engaged|possible_mocking|disengaged","reason":"brief label"}. Preserve the client's question order and goals. Use the recent transcript and prior answers to avoid repetition, respond to greetings or clarification requests naturally, and ask a purposeful follow-up only when it adds evidence. A clear answer advances; a request for simplification receives a genuinely different rephrasing; an explicit refusal skips without probing. Do not reveal reasoning or invent participant meaning."""
CONVERSATIONAL_LEAD_SYSTEM += SEMANTIC_CONTROLLER_CONTRACT

ALLOWED_ACTIONS = {"advance", "probe", "simplify", "repeat", "repair", "close"}
ACTIVE_SETTINGS = ContextVar("interview_settings", default={})
ACTIVE_SESSION = ContextVar("active_interview", default=None)

def default_questionnaire():
    return [{"id": qid, "text": text, "goal": DEFAULT_GOALS[qid], "kind": "open", "options": [], "probe_limit": limit, "probe_hints": [], "branches": {}} for qid, text, limit in DEFAULT_QUESTIONS]


def default_pre_interview_form():
    """A new project begins with no personal-data collection fields."""
    return []

def questionnaire(settings=None):
    return (settings if settings is not None else ACTIVE_SETTINGS.get()).get("questionnaire") or default_questionnaire()

def questions():
    return [(q["id"], q["text"], q["probe_limit"]) for q in questionnaire()]

def question_goals():
    return {q["id"]: q["goal"] for q in questionnaire()}


def question_probe_hints(question_id: str) -> list[str]:
    item = next((q for q in questionnaire() if q["id"] == question_id), {})
    return [str(hint).strip() for hint in item.get("probe_hints", []) if str(hint).strip()]

def configure_session(session, settings, version=0):
    session.settings_snapshot = {**settings, "questionnaire": questionnaire(settings)}
    session.settings_version = version
    session.architecture = settings["architecture"]
    session.instrument_sha256 = hashlib.sha256(json.dumps(session.settings_snapshot["questionnaire"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    first = session.settings_snapshot["questionnaire"][0]
    session.messages[0]["content"] = "سلام. من مصاحبه‌گر هوش مصنوعی این پژوهش هستم. پاسخ درست یا غلطی وجود ندارد و هر زمان بخواهید می‌توانید مکث یا پایان دهید. " + first["text"]
    session.messages[0]["question_id"] = first["id"]
    return session

def default_settings():
    return {"project_title": "مصاحبه پژوهشی",
            "study_metadata": {"title": "مصاحبه پژوهشی", "purpose": "این گفت‌وگو برای فهم دیدگاه و تجربهٔ شما انجام می‌شود.", "interviewer_role": "مصاحبه‌گر این پژوهش", "duration": "مدت زمان اعلام‌شده در پروتکل", "storage_statement": "پاسخ‌ها برای تحلیل همین مطالعه ثبت می‌شوند."},
            "welcome_text": "این گفت‌وگو بر اساس پروتکلی انجام می‌شود که پژوهشگر منتشر کرده است.",
            "consent_text": "شرکت در این گفت‌وگو داوطلبانه است. می‌توانید از هر پرسش بگذرید یا هر زمان گفت‌وگو را پایان دهید.",
            "participant_language": "فارسی",
            "model": _model(), "architecture": _architecture(),
            "base_prompt": BASE_PROTOCOL,
            "planner_prompt": PLANNER_SYSTEM[len(BASE_PROTOCOL):].strip(),
            "interviewer_prompt": INTERVIEWER_SYSTEM[len(BASE_PROTOCOL):].strip(),
            "fast_prompt": FAST_GUIDED_SYSTEM[len(BASE_PROTOCOL):].strip(),
            "lead_prompt": CONVERSATIONAL_LEAD_SYSTEM[len(BASE_PROTOCOL):].strip(),
            "lite_timeout": 12, "fast_timeout": 10, "questionnaire": default_questionnaire(),
            "pre_interview_form": default_pre_interview_form()}

def configured_prompt(original):
    cfg = ACTIVE_SETTINGS.get()
    key = {PLANNER_SYSTEM: "planner_prompt", INTERVIEWER_SYSTEM: "interviewer_prompt", FAST_GUIDED_SYSTEM: "fast_prompt", CONVERSATIONAL_LEAD_SYSTEM: "lead_prompt"}.get(original)
    if not key or not cfg:
        return original
    return cfg["base_prompt"] + "\n\n" + cfg[key] + "\n\nPROTECTED CORE (not editable in the panel):\n" + BASE_PROTOCOL + SEMANTIC_CONTROLLER_CONTRACT

def _architecture() -> str:
    value = os.getenv("INTERVIEW_ARCHITECTURE", "multi_agent_lite").strip().lower()
    return value.replace("-", "_").replace(" ", "_")


@dataclass
class InterviewSession:
    metadata_schema_version: str | None = None
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    turn_metrics: list[dict[str, Any]] = field(default_factory=list)
    # One audit event per execution route.  This is intentionally separate
    # from model_calls: a turn may take a deterministic route, or move from
    # Lite to Fast Guided before a participant-facing message is produced.
    architecture_trace: list[dict[str, Any]] = field(default_factory=list)
    completed_at: str | None = None
    completion_reason: str | None = None
    instrument_sha256: str | None = None
    settings_snapshot: dict[str, Any] = field(default_factory=dict)
    settings_version: int = 0
    is_test: bool = False
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    architecture: str = field(default_factory=_architecture)
    protocol_version: str = PROTOCOL_VERSION
    pre_interview: dict[str, str] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    question_index: int = 0
    probe_count: int = 0
    status: str = "active"
    usage: list[dict[str, Any]] = field(default_factory=list)
    # Audit labels are deliberately compact. They make later quality review
    # possible without storing a model's private rationale.
    decision_log: list[dict[str, Any]] = field(default_factory=list)
    # A request id prevents accidental duplicate turns after browser retries.
    processed_turn_ids: list[str] = field(default_factory=list)
    # The API stores this before a provider call, so a failed request can be
    # retried without asking the participant to type the answer again.
    pending_turn: dict[str, Any] | None = None
    # Persist delivery state with the session so Streamlit reruns do not send
    # the same completed transcript repeatedly.
    result_email_status: str = "not_requested"
    result_email_error: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error_message: str = ""
    # Behavioural continuity: one gentle boundary is offered before an
    # agent-classified pattern of disengagement can end the interview.
    disengagement_notices: int = 0
    # The final open invitation is conversational, not a yes/no terminator.
    final_invitation_stage: int = 0
    semantic_state: dict[str, Any] = field(default_factory=dict)
    semantic_ledger: dict[str, dict[str, Any]] = field(default_factory=dict)
    context_summary: str = ""
    context_summary_version: str = SEMANTIC_PROTOCOL_VERSION
    semantic_turn_count: int = 0
    social_turn_count: int = 0
    non_evidence_turn_count: int = 0

    def public(self) -> dict[str, Any]:
        result = asdict(self)
        items = questionnaire(self.settings_snapshot)
        current = items[min(max(self.question_index, 0), len(items) - 1)]
        result["current_question"] = current["text"]
        result["current_question_id"] = current["id"]
        result["current_choices"] = current["options"] if current["kind"] != "open" else []
        result["current_response_kind"] = current["kind"]
        result["total_questions"] = len(items)
        calls = self.model_calls
        trace = self.architecture_trace
        successful_trace = [item for item in trace if item.get("outcome") in {"success", "fallback"}]
        architectures_used = list(dict.fromkeys(
            str(item.get("architecture")) for item in successful_trace if item.get("architecture")
        ))
        fallback_trace = [item for item in trace if item.get("fallback_from")]
        usage = [c["usage"] for c in calls if isinstance(c.get("usage"), dict)] if calls else self.usage
        def total(key):
            values = [u[key] for u in usage if isinstance(u.get(key), (int, float))]
            return sum(values) if values else None
        end = self.completed_at or self.updated_at
        result["analysis_metadata"] = {
            "schema_version": self.metadata_schema_version,
            "language": self.settings_snapshot.get('participant_language', 'فارسی'), "timestamp_timezone": "UTC",
            "source": "interview_builder_web", "project_title": self.settings_snapshot.get('project_title'), "is_test": self.is_test,
            "settings_version": self.settings_version,
            "configured_model": self.settings_snapshot.get('model'),
            "architecture": self.architecture, "protocol_version": self.protocol_version,
            "settings_sha256": hashlib.sha256(json.dumps(self.settings_snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest() if self.settings_snapshot else None,
            "requested_models": sorted({c['requested_model'] for c in calls if c.get('requested_model')}),
            "returned_models": sorted({c['returned_model'] for c in calls if c.get('returned_model')}),
            "providers": sorted({c['provider'] for c in calls if c.get('provider')}),
            "elapsed_seconds": round((datetime.fromisoformat(end) - datetime.fromisoformat(self.started_at)).total_seconds(), 3),
            "elapsed_includes_participant_time_and_pauses": True,
            "participant_turns": sum(m.get('role') == 'user' for m in self.messages),
            "assistant_messages": sum(m.get('role') == 'assistant' for m in self.messages),
            "participant_characters": sum(len(m.get('content', '')) for m in self.messages if m.get('role') == 'user'),
            "assistant_characters": sum(len(m.get('content', '')) for m in self.messages if m.get('role') == 'assistant'),
            "mean_turn_latency_ms": round(sum(t['duration_ms'] for t in self.turn_metrics) / len(self.turn_metrics), 2) if self.turn_metrics else None,
            "max_turn_latency_ms": max((t['duration_ms'] for t in self.turn_metrics), default=None),
            "questions_with_responses": sorted({m['question_id'] for m in self.messages if m.get('role') == 'user' and m.get('question_id')}),
            "recorded_model_calls": len(calls),
            "failed_model_calls": sum(c.get('status') == 'error' for c in calls),
            "semantic_protocol_version": SEMANTIC_PROTOCOL_VERSION,
            "context_summary_version": self.context_summary_version,
            "semantic_turn_count": self.semantic_turn_count,
            "social_turn_count": self.social_turn_count,
            "non_evidence_turn_count": self.non_evidence_turn_count,
            "fallback_turns": sum(bool(d.get('recovered')) for d in self.decision_log),
            "architecture_execution": {
                "telemetry_schema_version": "1.0",
                "configured_architecture": self.architecture,
                "architectures_used": architectures_used,
                "last_effective_architecture": architectures_used[-1] if architectures_used else None,
                "recorded_execution_attempts": len(trace),
                "failed_execution_attempts": sum(item.get("outcome") == "failure" for item in trace),
                "fallback_occurred": bool(fallback_trace),
                "fallback_count": len(fallback_trace),
                "fallback_paths": list(dict.fromkeys(
                    f"{item.get('fallback_from')} → {item.get('architecture')}" for item in fallback_trace
                )),
                "note": "A fallback is recorded only when the next reliability route actually produced the turn. Legacy records may have no trace.",
            },
            "prompt_tokens": total('prompt_tokens'), "completion_tokens": total('completion_tokens'),
            "total_tokens": total('total_tokens'),
            "provider_reported_cost": total('cost'),
            "cost_currency": "USD" if usage and all(c.get('provider') == 'openrouter' for c in calls) and calls and total('cost') is not None else None,
            "calls_with_usage": len(usage),
            "cost_note": "Provider-reported only; missing charges and failed calls may be unreported. Not an invoice or complete cost guarantee.",
            "capture_note": "Per-call capture available only from metadata schema 1.0; older timestamps and model versions are not reconstructed. Returned model IDs may be aliases, not immutable versions.",
            "context_summary": self.context_summary,
            "semantic_state": self.semantic_state,
            "semantic_ledger": self.semantic_ledger,
        }
        return result

def _tracked_request(session, endpoint, *, headers, json, timeout, role, architecture=None, stage=None):
    started = time.perf_counter()
    event = {"id": str(uuid.uuid4()), "turn_id": session.pending_turn.get('id') if session.pending_turn else None,
             "question_id": questions()[session.question_index][0], "role": role,
             "architecture": architecture or session.architecture, "stage": stage or role,
             "started_at": datetime.now(timezone.utc).isoformat(), "provider": _provider(),
             "requested_model": json['model'], "returned_model": None,
             "temperature": json.get('temperature'), "max_output_tokens": json.get('max_tokens'),
             "timeout_seconds": timeout, "status": "error", "usage": None}
    try:
        response = requests.post(endpoint, headers=headers, json=json, timeout=timeout)
        event['http_status'] = response.status_code
        response.raise_for_status()
        data = response.json()
        event.update(status='success', returned_model=data.get('model'), response_id=data.get('id'),
                     upstream_provider=data.get('provider'), system_fingerprint=data.get('system_fingerprint'),
                     provider_created_at=data.get('created'), usage=data.get('usage'),
                     finish_reason=(data.get('choices') or [{}])[0].get('finish_reason'))
        return response
    except Exception as exc:
        # Class only: exception strings can contain credentials or response bodies.
        event['error_type'] = type(exc).__name__
        raise
    finally:
        event['ended_at'] = datetime.now(timezone.utc).isoformat()
        event['duration_ms'] = round((time.perf_counter() - started) * 1000, 2)
        session.model_calls.append(event)

def _provider() -> str:
    """Return the configured hosted provider without exposing credentials."""
    # GapGPT is the default hosted route for the Iranian field deployment.
    # OpenRouter remains fully supported by setting INTERVIEW_PROVIDER.
    return os.getenv("INTERVIEW_PROVIDER", "gapgpt").strip().lower()


def _key() -> str:
    provider = _provider()
    # INTERVIEW_API_KEY is a convenient provider-neutral name. The provider-
    # specific names keep existing OpenRouter deployments compatible and make
    # it possible to store both providers in the same Streamlit/VPS instance.
    if provider in {"gapgpt", "gap-gpt", "gap_gpt"}:
        return os.getenv("INTERVIEW_API_KEY", "") or os.getenv("GAPGPT_API_KEY", "")
    return os.getenv("INTERVIEW_API_KEY", "") or os.getenv("OPENROUTER_API_KEY", "")


def _endpoint() -> str:
    provider = _provider()
    if provider in {"gapgpt", "gap-gpt", "gap_gpt"}:
        # GapGPT documents an OpenAI-compatible API base of
        # https://api.gapgpt.app/v1. This engine posts directly to the chat
        # completions resource, so retain an explicit override but provide the
        # complete documented path by default.
        return (os.getenv("INTERVIEW_ENDPOINT", "").strip()
                or os.getenv("GAPGPT_ENDPOINT", "").strip()
                or "https://api.gapgpt.app/v1/chat/completions")
    return os.getenv("INTERVIEW_ENDPOINT", "").strip() or "https://openrouter.ai/api/v1/chat/completions"

def _model() -> str:
    if ACTIVE_SETTINGS.get().get("model"):
        return ACTIVE_SETTINGS.get()["model"]
    provider = _provider()
    if provider in {"gapgpt", "gap-gpt", "gap_gpt"}:
        # A researcher can override this with any model available in their
        # GapGPT account. Nano is a cost-conscious default for fieldwork.
        return os.getenv("INTERVIEW_MODEL", "").strip() or os.getenv("GAPGPT_MODEL", "").strip() or "gpt-5-nano"
    return os.getenv("INTERVIEW_MODEL", "openai/gpt-5-nano")


def _generation_options(max_tokens: int, *, participant_text: bool = False) -> dict[str, Any]:
    """Return provider-safe generation settings for reasoning models.

    GPT-5 models exposed through OpenAI-compatible gateways may spend the
    entire small ``max_tokens`` budget on hidden reasoning.  The gateway then
    returns a successful HTTP response with an empty ``message.content`` and
    ``finish_reason=length``.  That used to look like a provider outage and
    incorrectly sent a live interview to the final recovery route.  Keep the
    normal budget for other models, but ask GPT-5 for low reasoning effort and
    enough completion headroom for the visible JSON/Persian turn.

    The option is deliberately model-gated: many third-party models reject
    ``reasoning_effort`` as an unknown request field.
    """
    model = _model().strip().lower()
    is_gpt5_reasoning = "gpt-5" in model or model.startswith(("o1", "o3", "o4"))
    if not is_gpt5_reasoning:
        return {"max_tokens": max_tokens}
    floor = 700 if participant_text else 900
    return {"reasoning_effort": "low", "max_tokens": max(max_tokens, floor)}

def _meaningful_q1(text: str) -> bool:
    low = text.strip().lower()
    if len(low) < 2 or low in {"بله", "خیر", "نه", "نمی‌دانم", "نمیدانم", "سلام", "آماده"}:
        return False
    return any(x in low for x in ["هوش", "کامپیوتر", "ماشین", "ربات", "gpt", "چت", "داده", "فناوری", "سیستم", "ابزار"])


def _normalize(text: str) -> str:
    return text.strip().lower().replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه")


def _clear_no_delegation_boundary(text: str) -> bool:
    normalized = _normalize(text)
    no_boundary = any(term in normalized for term in ("کاری نیست", "هیچ کاری نیست", "کار نامناسبی نیست", "نامناسب نمی"))
    suitable = any(term in normalized for term in ("مناسب", "می‌شود سپرد", "میشه سپرد", "سپردن کارها", "همه کارها"))
    return no_boundary and suitable


def _concrete_uses_named(text: str) -> bool:
    normalized = _normalize(text)
    generic = ("کارهای خودم", "کارای خودم", "کارهای مختلف", "برای کار")
    concrete = ("نوشت", "ترجم", "خلاصه", "تحلیل", "تصویر", "کد", "برنامه", "پژوهش", "مقاله", "درس", "طراحی", "پاسخ")
    return not any(term in normalized for term in generic) and any(term in normalized for term in concrete)


def _exact_participant_quote(quote: str, session: InterviewSession) -> bool:
    needle = _normalize(quote)
    if len(needle) < 2:
        return False
    return any(needle in _normalize(str(message.get("content", ""))) for message in session.messages if message.get("role") == "user")


def _evidence_ledger(session: InterviewSession) -> str:
    """Compact, provenance-preserving memory for long interviews."""
    latest_by_question: dict[str, str] = {}
    for message in session.messages:
        if message.get("role") == "user" and message.get("question_id"):
            latest_by_question[str(message["question_id"])] = str(message.get("content", ""))[:360]
    if not latest_by_question:
        return "هنوز شاهدی ثبت نشده است."
    return "\n".join(f"- {qid}: {text}" for qid, text in latest_by_question.items())

def _semantic_ledger_text(session: InterviewSession) -> str:
    if not session.semantic_ledger:
        return "none"
    return "\n".join(
        f"- {qid}: state={item.get('state','unknown')}; intent={item.get('intent','research_answer')}; "
        f"meaning={str(item.get('meaning_summary',''))[:180]}; missing={str(item.get('missing_evidence',''))[:140]}; "
        f"follow_ups={item.get('follow_up_count', 0)}"
        for qid, item in list(session.semantic_ledger.items())[-24:]
    )


def _model_context(session: InterviewSession) -> list[str]:
    pre = [f"{key}: {value}" for key, value in session.pre_interview.items()]
    recent = session.messages[-8:]
    conversation = [f"{message['role']}: {message['content']}" for message in recent]
    return [
        "شناسه دعوت پایانی در نسخه فعلی: " + questions()[-1][0] + " (هر اشاره قدیمی به Q13 به همین دعوت پایانی اشاره دارد).",
        "کنترل صریح کاربر: " + str((session.pending_turn or {}).get('control', 'answer')) + ". اگر clarify است فقط همان سؤال را ساده‌تر کن؛ پیشروی یا پایان نده.",
        "وضع مشارکت: " + ("یک یادآوری محترمانهٔ مرتبط‌ماندن با گفت‌وگو قبلاً داده شده است." if session.disengagement_notices else "یادآوری مرتبط‌ماندن هنوز داده نشده است."),
        "STUDY METADATA (only source for process answers):\n" + json.dumps(session.settings_snapshot.get("study_metadata", {}), ensure_ascii=False),
        "پیش‌مصاحبه:\n" + ("\n".join(pre) or "ثبت نشده"),
        "دفتر معنایی فشرده:\n" + _semantic_ledger_text(session),
        "دفتر شواهدِ پاسخ‌های پیشین (هر مورد از متن خود فرد است):\n" + _evidence_ledger(session),
        "خلاصهٔ دوره‌ای زمینه:\n" + (session.context_summary or "none"),
        "بخش اخیر گفت‌وگو:\n" + "\n".join(conversation),
    ]

def _fallback(text: str, index: int, probes: int) -> dict[str, Any]:
    low = text.strip().lower()
    if any(x in low for x in ["توقف", "تمام", "خداحافظ", "دیگه نمی", "نمی‌خوام ادامه"]):
        return {"action":"finish", "question_index":index, "participant_turn":"از وقتی که گذاشتید سپاسگزارم. مصاحبه در همین‌جا پایان می‌یابد.", "reason":"stop", "probe_type":"none"}
    if index == 0 and low in {"سلام", "درود", "خوبم", "مرسی", "ممنون", "آماده", "بله"}:
        return {"action":"pause", "question_index":0, "participant_turn":"سلام، خوش آمدید. " + questions()[0][1], "reason":"social opening", "probe_type":"none"}
    if "نمی‌دانم" in low or "نمیدانم" in low:
        return {"action":"simplify", "question_index":index, "participant_turn":"اگر ممکن است، پاسخ را با یک تجربه یا مثال کوتاه بیان کنید.", "reason":"simplify", "probe_type":"clarify"}
    if any(x in low for x in ["کارهای خودم", "کارای خودم", "کارهای مختلف"]):
        return {"action":"probe", "question_index":index, "participant_turn":"بیشتر در کدام کار مشخص از آن استفاده می‌کنید؟", "reason":"generic task", "probe_type":"clarify"}
    if any(x in low for x in ["متحول", "دگرگون", "همه چیز", "همه‌چیز"]):
        return {"action":"probe", "question_index":index, "participant_turn":"منظورتان بیشتر کدام بخش از کار است که تغییر می‌کند؟", "reason":"abstract impact", "probe_type":"clarify"}
    if low in {"نه", "خیر", "نمیشه", "نمی‌تونم", "نمی‌توانم"} and probes > 0:
        nxt = min(index + 1, len(questions())-1)
        return {"action":"skip", "question_index":nxt, "participant_turn":questions()[nxt][1], "reason":"declined probe", "probe_type":"none"}
    if index >= len(questions())-1:
        return {"action":"finish", "question_index":index, "participant_turn":"از زمانی که برای این گفت‌وگو گذاشتید سپاسگزارم. پاسخ‌های شما ثبت شد.", "reason":"complete", "probe_type":"none"}
    nxt = index + 1
    return {"action":"advance", "question_index":nxt, "participant_turn":questions()[nxt][1], "reason":"safe advance", "probe_type":"none"}


def _safe_final_close(index: int, reason: str) -> dict[str, Any]:
    """The deterministic final stage after both hosted routes are unavailable."""
    return {
        "action": "finish",
        "question_index": index,
        "participant_turn": "ارتباط با مصاحبه‌گر برقرار نشد. پاسخ شما محفوظ است؛ با گزینه بازیابی می‌توانید همین گفت‌وگو را ادامه دهید.",
        "reason": reason,
        "probe_type": "none",
        "_final_close": True,
    }

def _observed_gap_override(text: str, index: int, probes: int) -> dict[str, Any] | None:
    """Project-specific follow-up rules belong to the published protocol, not the platform kernel."""
    return None

def _parse(raw: str) -> dict[str, Any]:
    raw = raw.strip().replace("```json", "").replace("```", "").strip()
    decoder = json.JSONDecoder()
    for position, char in enumerate(raw):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(raw[position:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("پاسخ ساختاریافته دریافت نشد")

def _wait_seconds(name: str, default: float) -> float:
    key = {"INTERVIEW_LITE_WAIT_SECONDS": "lite_timeout", "INTERVIEW_FAST_GUIDED_WAIT_SECONDS": "fast_timeout"}.get(name)
    if key and key in ACTIVE_SETTINGS.get():
        return float(ACTIVE_SETTINGS.get()[key])
    try:
        return min(max(float(os.getenv(name, str(default))), 6), 30)
    except ValueError:
        return default


def _model_decision(
    session: InterviewSession,
    answer: str,
    mode: str | None = None,
    attempts: int = 1,
    timeout_seconds: float | None = None,
    system_override: str | None = None,
    prompt_override: str | None = None,
    max_tokens: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not _key():
        provider_name = "GAPGPT_API_KEY/INTERVIEW_API_KEY" if _provider() in {"gapgpt", "gap-gpt", "gap_gpt"} else "OPENROUTER_API_KEY/INTERVIEW_API_KEY"
        raise RuntimeError(f"{provider_name} is not configured")
    endpoint = _endpoint()
    if not endpoint:
        raise RuntimeError("GAPGPT_ENDPOINT or INTERVIEW_ENDPOINT is not configured")
    context = _model_context(session)
    qid, qtext, limit = questions()[session.question_index]
    hints = question_probe_hints(qid)
    context += [f"\nپرسش جاری: {qid} — «{qtext}»", f"هدف پژوهشی همین پرسش: {question_goals()[qid]}", f"پیگیری این آیتم: {session.probe_count} از {limit}", f"پاسخ آخر فرد: «{answer}»"]
    if hints:
        context.append("پیشنهادهای پژوهشگر برای پیگیری (اختیاری‌اند؛ فقط در صورت شکاف ضروری و بدون تکرار استفاده کن):\n- " + "\n- ".join(hints))
    if prompt_override:
        context.append(prompt_override)
    active_mode = (mode or session.architecture or _architecture()).replace("-", "_").lower()
    is_fast_guided = active_mode in {"fast_guided", "fastguided"}
    system = system_override or (FAST_GUIDED_SYSTEM if is_fast_guided else PLANNER_SYSTEM)
    system = configured_prompt(system)
    payload = {"model": _model(), "messages": [{"role":"system", "content":system}, {"role":"user", "content":"\n\n".join(context)}], "temperature":0.25 if is_fast_guided else 0.35}
    payload.update(_generation_options(max_tokens or (320 if is_fast_guided else 420)))
    last = None
    timeout = timeout_seconds if timeout_seconds is not None else _wait_seconds("INTERVIEW_TURN_TIMEOUT", 22)
    request_id = session.pending_turn.get("id") if session.pending_turn else str(uuid.uuid4())
    for attempt in range(max(1, attempts)):
        try:
            headers = {"Authorization":f"Bearer {_key()}", "Content-Type":"application/json"}
            headers["X-Client-Request-ID"] = request_id
            if _provider() == "openrouter":
                headers["X-Title"] = "AI Interview Builder"
            response = _tracked_request(session, endpoint, headers=headers, json=payload, timeout=timeout,
                                        role='fast_guided' if is_fast_guided else 'moderator',
                                        architecture=active_mode, stage='decision')
            response.raise_for_status()
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
            if content and content.strip():
                return _parse(content), data.get("usage", {})
            raise ValueError("empty model response")
        except Exception as exc:
            last = exc
            if session.model_calls and session.model_calls[-1].get('status') == 'success':
                session.model_calls[-1].update(status='error', error_type=type(exc).__name__, error_stage='response_validation')
            if attempt < max(1, attempts) - 1:
                time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(str(last))


def _model_text(session: InterviewSession, answer: str, *, system: str, prompt: str, mode: str, timeout_seconds: float) -> tuple[str, dict[str, Any]]:
    """Call the same provider for a participant-facing turn, without JSON parsing."""
    system = configured_prompt(system)
    if not _key():
        raise RuntimeError("provider API key is not configured")
    qid, qtext, limit = questions()[session.question_index]
    hints = question_probe_hints(qid)
    context = _model_context(session) + [
        f"پرسش جاری: {qid} — «{qtext}»",
        f"هدف پژوهشی همین پرسش: {question_goals()[qid]}",
        f"پیگیری این آیتم: {session.probe_count} از {limit}",
        f"پاسخ آخر فرد: «{answer}»",
        prompt,
    ]
    if hints:
        context.append("پیشنهادهای پیگیری پژوهشگر (در صورت ضرورت، نه به‌صورت اجباری):\n- " + "\n- ".join(hints))
    headers = {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json", "X-Client-Request-ID": str(uuid.uuid4())}
    if _provider() == "openrouter":
        headers["X-Title"] = "AI Interview Builder"
    response = _tracked_request(
        session, _endpoint(), headers=headers, role='interviewer', architecture=mode, stage='participant_wording',
        json={"model": _model(), "messages": [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(context)}], "temperature": 0.35, **_generation_options(260, participant_text=True)},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content")
    if not content or not content.strip():
        session.model_calls[-1].update(status='error', error_type='EmptyResponse', error_stage='response_validation')
        raise RuntimeError("empty interviewer response")
    return content.strip(), data.get("usage", {})

def _maybe_refresh_context_summary(session: InterviewSession) -> None:
    if not _key() or session.semantic_turn_count < 4 or session.semantic_turn_count % 4 != 0:
        return
    try:
        response = _tracked_request(
            session, _endpoint(),
            headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json", "X-Client-Request-ID": str(uuid.uuid4())},
            json={"model": _model(), "messages": [{"role": "system", "content": "Summarize the structured interview ledger in concise factual Persian. Do not infer or add opinions."}, {"role": "user", "content": _semantic_ledger_text(session)}], "temperature": 0.1, "max_tokens": 180},
            timeout=min(8, _wait_seconds("INTERVIEW_FAST_GUIDED_WAIT_SECONDS", 8)), role="memory", architecture=session.architecture, stage="context_summary"
        )
        text = response.json().get("choices", [{}])[0].get("message", {}).get("content")
        if text and text.strip():
            session.context_summary = text.strip()[:1200]
            session.context_summary_version = SEMANTIC_PROTOCOL_VERSION
    except Exception:
        return

def new_session(pre_interview: dict[str, str] | None = None) -> InterviewSession:
    session = InterviewSession(pre_interview=pre_interview or {}, architecture=_architecture())
    session.metadata_schema_version = '1.0'
    session.instrument_sha256 = hashlib.sha256(json.dumps([questions(), question_goals()], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    session.messages = [{"role":"assistant", "content":"سلام. من مصاحبه‌گر هوش مصنوعی این پژوهش هستم. پاسخ درست یا غلطی وجود ندارد و هر زمان بخواهید می‌توانید مکث یا پایان دهید. " + questions()[0][1]}]
    session.messages[0].update(timestamp=session.started_at, message_id=str(uuid.uuid4()), question_id='Q1')
    return session

def _validated_decision(session: InterviewSession, answer: str, index: int, decision: dict[str, Any]) -> dict[str, Any]:
    """Validate model routing against participant meaning and protocol order."""
    action = str(decision.get("action", "")).lower()
    try:
        target = int(decision.get("question_index", index))
    except (TypeError, ValueError):
        target = index
    text = str(decision.get("participant_turn", "")).strip()
    if action not in ALLOWED_ACTIONS or not text:
        return _fallback(answer, index, session.probe_count)

    quotes = decision.get("source_evidence_quotes", [])
    if not isinstance(quotes, list):
        quotes = []
    needs_quote = action in {"probe", "simplify"}
    if needs_quote and quotes and not all(_exact_participant_quote(str(quote), session) for quote in quotes):
        return _fallback(answer, index, session.probe_count)

    # These are semantic protections for recurring pilot failures. They do not
    # replace the LLM's normal judgment; they only prevent it from reversing a
    # participant's clear position or demanding a duplicate explanation.
    if questions()[index][0] == "Q8" and _clear_no_delegation_boundary(answer):
        return {"action": "advance", "question_index": index + 1, "participant_turn": questions()[index + 1][1], "reason": "clear no-boundary position", "stance": "no_boundary", "answer_adequacy": "adequate", "missing_slot": "none", "confidence": 0.95, "probe_type": "none"}
    if questions()[index][0] == "Q3" and _concrete_uses_named(answer):
        return {"action": "advance", "question_index": index + 1, "participant_turn": questions()[index + 1][1], "reason": "concrete uses already named", "stance": "uses_ai", "answer_adequacy": "adequate", "missing_slot": "none", "confidence": 0.92, "probe_type": "none"}
    if session.probe_count > 0 and _normalize(answer) in {"نه", "خیر", "نمیشه", "نمی‌تونم", "نمی‌توانم"}:
        return {"action": "skip", "question_index": min(index + 1, len(questions()) - 1), "participant_turn": questions()[min(index + 1, len(questions()) - 1)][1], "reason": "participant declined follow-up", "stance": "declined_follow_up", "answer_adequacy": "partial", "missing_slot": "declined", "confidence": 0.95, "probe_type": "none"}
    if index == len(questions()) - 1:
        return {"action": "finish", "question_index": index, "participant_turn": "از مشارکت شما سپاسگزارم. پاسخ‌های شما ثبت شدند.", "reason": "final invitation completed", "probe_type": "none"}
    if action in {"advance", "skip"}:
        target = index + 1
        text = questions()[target][1]
    elif action == "finish" and not decision.get("_final_close"):
        action, target, text = "advance", index + 1, questions()[index + 1][1]
    else:
        target = index
    return {**decision, "action": action, "question_index": target, "participant_turn": text, "source_evidence_quotes": quotes}


def _record_decision(session: InterviewSession, turn_id: str, question_id: str, decision: dict[str, Any], recovered: bool) -> None:
    session.decision_log.append({
        "turn_id": turn_id,
        "question_id": question_id,
        "action": decision.get("action"),
        "reason": decision.get("reason"),
        "stance": decision.get("stance"),
        "answer_adequacy": decision.get("answer_adequacy"),
        "missing_slot": decision.get("missing_slot"),
        "confidence": decision.get("confidence"),
        "evidence_present": decision.get("evidence_present"),
        "evidence_gap": decision.get("evidence_gap"),
        "engagement": decision.get("engagement", "engaged"),
        "intent": _semantic_intent(decision),
        "is_research_evidence": bool(decision.get("is_research_evidence", _semantic_intent(decision) == "research_answer")),
        "meaning_summary": decision.get("meaning_summary"),
        "current_question_open": decision.get("current_question_open"),
        "next_action": decision.get("next_action", decision.get("action")),
        "confidence": decision.get("confidence"),
        "evidence_quotes": decision.get("evidence_quotes", []),
        "execution_mode": decision.get("_execution_mode", session.architecture),
        "recovered": recovered,
        "at": datetime.now(timezone.utc).isoformat(),
    })

def _semantic_intent(decision: dict[str, Any], default: str = "research_answer") -> str:
    value = str(decision.get("intent", default)).strip().lower()
    return value if value in SEMANTIC_INTENTS else default

def _normalize_semantic_decision(decision: dict[str, Any], answer: str, session: InterviewSession) -> dict[str, Any]:
    if not decision.get("intent") and decision.get("control_turn"):
        reason = _normalize(str(decision.get("reason", "")))
        inferred = "clarification_request"
        if "social" in reason or _social_opening(answer): inferred = "social_greeting"
        elif "role" in reason: inferred = "role_boundary_question"
        elif "example" in reason: inferred = "example_request"
        elif "recall" in reason or "backtrack" in reason: inferred = "backtrack"
        elif "interview" in reason or "date" in reason or "process" in reason: inferred = "process_question"
        decision["intent"] = inferred
    intent = _semantic_intent(decision)
    decision["intent"] = intent
    decision["is_research_evidence"] = bool(decision.get("is_research_evidence", intent == "research_answer"))
    decision["meaning_summary"] = str(decision.get("meaning_summary", ""))[:300]
    quotes = decision.get("evidence_quotes", decision.get("source_evidence_quotes", decision.get("evidence_used", [])))
    decision["evidence_quotes"] = [str(q)[:180] for q in quotes[:3]] if isinstance(quotes, list) else []
    decision["current_question_open"] = bool(decision.get("current_question_open", intent != "termination"))
    if intent in {"social_greeting", "process_question", "role_boundary_question", "clarification_request", "example_request", "options_request", "opinion_request", "continuation"}:
        decision["is_research_evidence"] = False
        decision["current_question_open"] = True
        if str(decision.get("action", "")).lower() in {"advance", "skip", "close"}:
            decision["action"] = "repair"
    if intent == "termination":
        decision["terminationIntent"] = "explicit"
    if intent == "refusal":
        decision["is_research_evidence"] = False
        decision["action"] = "advance"
    try:
        decision["confidence"] = min(1.0, max(0.0, float(decision.get("confidence", 0.5))))
    except (TypeError, ValueError):
        decision["confidence"] = 0.5
    return decision

def _update_semantic_state(session: InterviewSession, question_id: str, answer: str, decision: dict[str, Any]) -> None:
    intent = _semantic_intent(decision)
    is_evidence = bool(decision.get("is_research_evidence", intent == "research_answer"))
    item = session.semantic_ledger.setdefault(question_id, {"state": "unanswered", "meaning_summary": "", "missing_evidence": "", "follow_up_count": 0, "intents": [], "evidence_quotes": []})
    item["intent"] = intent
    item["state"] = "answered" if str(decision.get("action")) in {"advance", "skip"} and is_evidence else ("declined" if intent == "refusal" else str(decision.get("current_question_state", "continue")))
    item["meaning_summary"] = str(decision.get("meaning_summary") or item.get("meaning_summary") or answer[:240])[:300]
    item["missing_evidence"] = str(decision.get("evidence_gap") or decision.get("missing_slot") or "")[:180]
    item["follow_up_count"] = int(decision.get("follow_up_count", item.get("follow_up_count", 0)) or 0)
    item["intents"] = list(dict.fromkeys([*(item.get("intents") or []), intent]))[-8:]
    item["evidence_quotes"] = list(dict.fromkeys([*(item.get("evidence_quotes") or []), *decision.get("evidence_quotes", [])]))[-6:]
    session.semantic_state = {"intent": intent, "meaning_summary": item["meaning_summary"], "is_research_evidence": is_evidence, "current_question_open": bool(decision.get("current_question_open", True)), "next_action": decision.get("next_action", decision.get("action")), "confidence": decision.get("confidence"), "evidence_quotes": decision.get("evidence_quotes", []), "question_id": question_id}
    session.semantic_turn_count += 1
    if not is_evidence: session.non_evidence_turn_count += 1
    if intent == "social_greeting": session.social_turn_count += 1
    for message in reversed(session.messages):
        if message.get("role") == "user" and message.get("content") == answer:
            message["semantic_intent"] = intent
            message["is_research_evidence"] = is_evidence
            message["meaning_summary"] = item["meaning_summary"]
            break


def _failure_code(error: Exception) -> str:
    """Keep exportable failure reasons useful without storing raw provider text."""
    name = type(error).__name__
    lower = name.lower()
    if "timeout" in lower:
        return "timeout"
    if "connection" in lower or "request" in lower:
        return "provider_request_error"
    if "json" in lower or "value" in lower:
        return "invalid_or_unreadable_response"
    if "runtime" in lower:
        return "provider_or_configuration_error"
    return f"{name}"


def _record_architecture_attempt(
    session: InterviewSession, *, turn_id: str, question_id: str, architecture: str,
    execution_mode: str, outcome: str, started_at: str, started_perf: float,
    call_offset: int, reason: str | None = None, fallback_from: str | None = None,
) -> None:
    """Append a compact, non-sensitive route audit record for one turn attempt."""
    calls = session.model_calls[call_offset:]
    session.architecture_trace.append({
        "id": str(uuid.uuid4()), "turn_id": turn_id, "question_id": question_id,
        "configured_architecture": session.architecture, "architecture": architecture,
        "execution_mode": execution_mode, "outcome": outcome,
        "fallback_from": fallback_from, "reason_code": reason,
        "started_at": started_at, "ended_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": round((time.perf_counter() - started_perf) * 1000, 2),
        "model_call_ids": [call.get("id") for call in calls if call.get("id")],
        "model_call_count": len(calls),
        "failed_model_call_count": sum(call.get("status") == "error" for call in calls),
    })


def _explicit_termination(text: str) -> bool:
    low = _normalize(text)
    return any(phrase in low for phrase in ("مصاحبه رو تمام کن", "مصاحبه را تمام کن", "گفتگو رو تمام کن", "گفت‌وگو رو تمام کن", "دیگه نمی‌خوام ادامه", "دیگه نمیخوام ادامه", "نمی‌خواهم ادامه", "نمیخوام ادامه", "لطفاً تمام کن")) or low in {"تمام کن", "توقف", "خداحافظ"}


def _wants_next_question(text: str) -> bool:
    low = _normalize(text)
    return any(phrase in low for phrase in ("برو سوال بعدی", "برو سؤال بعدی", "سوال بعدی", "سؤال بعدی", "رد شو", "از این بگذر"))


def _asks_for_today(text: str) -> bool:
    low = _normalize(text)
    return any(phrase in low for phrase in ("امروز چند شنبه", "امروز چه روزی", "امروز چندمه", "امروز چه تاریخه", "امروز چه تاریخ"))

def _asks_for_role_boundary(text: str) -> bool:
    low = _normalize(text)
    return any(marker in low for marker in ("نظر خودت", "نظر شما چیه", "تو چی فکر", "خودت موافقی", "به نظرت", "توصیه میکنی", "پیشنهادت چیه"))


def _asks_for_recall(text: str) -> bool:
    low = _normalize(text)
    return any(phrase in low for phrase in (
        "یادت هست", "یادته", "یادم هست", "از اول تا حالا چی گفتم",
        "چی گفتم", "حرفایی که زدم", "حرف هایی که زدم", "حرف‌هایی که زدم",
    ))

def _asks_for_process(text: str) -> bool:
    """Recognize study-process questions without guessing project facts."""
    low = _normalize(text)
    return any(marker in low for marker in (
        "این مصاحبه", "هدف این", "چقدر طول", "چند دقیقه", "پاسخ ها کجا",
        "پاسخ‌ها کجا", "جواب ها کجا", "جواب‌ها کجا", "ذخیره", "محرمانه",
        "چه کسی هستی", "شما کی هستید", "برای چیست", "برای چیه",
    ))


def _asks_for_neutral_example(text: str, index: int) -> bool:
    if index != 2:
        return False
    low = _normalize(text)
    return any(phrase in low for phrase in (
        "چه کاری مثلا", "چه کاری مثلاً", "مثلا چی", "مثلاً چی", "خودت چی فکر میکنی", "خودت چی فکر می‌کنی",
    ))


def _recall_reply(session: InterviewSession) -> str:
    """Answer an explicit memory check with only prior substantive chat turns."""
    ignored = (_asks_for_today, _asks_for_recall, _explicit_termination, _wants_next_question)
    evidence = []
    for message in session.messages:
        if message.get("role") != "user":
            continue
        content = str(message.get("content", "")).strip()
        # Do not quote a participant's earlier question back to them. Apart
        # from sounding odd, a quoted question mark is correctly rejected by
        # the participant-safety guard for a non-question repair turn.
        if not content or "؟" in content or "?" in content or any(check(content) for check in ignored):
            continue
        if len(content) > 72:
            content = content[:69].rstrip() + "…"
        evidence.append(content)
    if not evidence:
        return "بله. تا اینجا گفت‌وگو را دنبال کرده‌ام؛ هر زمان مایل بودید، پاسخ به همین پرسش را ادامه دهید."
    recent = "، ".join(f"«{item}»" for item in evidence[-3:])
    return f"بله. تا اینجا از جمله گفتید {recent}. هر زمان مایل بودید، پاسخ به همین پرسش را ادامه دهید."


def _participant_control_turn(session: InterviewSession, answer: str, index: int) -> dict[str, str] | None:
    """Short deterministic replies for ordinary chat intents, before any survey routing.

    This guard is deliberately limited to explicit conversational requests. It
    prevents a degraded route from mistaking a real user question for absent
    interview evidence, while leaving substantive answers to the LLM.
    """
    if _asks_for_today(answer):
        now = datetime.now(ZoneInfo("Asia/Tehran"))
        weekdays = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه"]
        return {
            "action": "repair",
            "participant_turn": f"امروز {weekdays[now.weekday()]} است. هر زمان آماده بودید، پاسخ به همین پرسش را ادامه دهید.",
            "reason": "participant asked for current date",
        }
    if _social_opening(answer):
        if session.social_turn_count >= 2:
            return {"action": "repair", "participant_turn": f"برای ادامهٔ مصاحبه، لطفاً به این پرسش پاسخ دهید: {questions()[index][1]}", "reason": "social exchange limit reached", "control_turn": True}
        return {"action": "repair", "participant_turn": "سلام، خوش آمدید. هر وقت آماده بودید، به پرسش جاری برگردیم.", "reason": "social opening", "control_turn": True}
    if _asks_for_process(answer):
        metadata = session.settings_snapshot.get("study_metadata", {}) or {}
        low = _normalize(answer)
        if "چقدر طول" in low or "چند دقیقه" in low:
            detail = metadata.get("duration", "مدت زمان در توضیحات مطالعه اعلام شده است")
        elif "ذخیره" in low or "محرمانه" in low or "پاسخ" in low or "جواب" in low:
            detail = metadata.get("storage_statement", "پاسخ‌ها برای تحلیل همین مطالعه ثبت می‌شوند")
        else:
            detail = metadata.get("purpose", "این گفت‌وگو برای فهم دیدگاه و تجربهٔ شما انجام می‌شود")
        return {"action": "repair", "participant_turn": f"{detail} هر وقت آماده بودید، به پرسش جاری برگردیم.", "reason": "participant asked about interview process"}
    if _asks_for_role_boundary(answer):
        role = (session.settings_snapshot.get("study_metadata", {}) or {}).get("interviewer_role", "مصاحبه‌گر این پژوهش")
        return {"action": "repair", "participant_turn": f"من {role} هستم و نظر شخصی یا موضع مستقلی ندارم؛ هدفم شنیدن دیدگاه شماست. اگر مایلید، به پرسش جاری پاسخ دهید یا از آن بگذرید.", "reason": "role boundary question"}
    if _asks_for_recall(answer):
        return {"action": "repair", "participant_turn": _recall_reply(session), "reason": "participant requested conversation recall"}
    if _asks_for_neutral_example(answer, index):
        return {
            "action": "simplify",
            "participant_turn": "مثلاً نوشتن، ترجمه، خلاصه‌کردن متن، جست‌وجو یا آماده‌کردن مطلب. شما بیشتر برای کدام کار از آن استفاده می‌کنید؟",
            "reason": "participant requested a neutral example for Q3",
        }
    return None


def _social_opening(text: str) -> bool:
    return _normalize(text) in {"سلام", "درود", "hi", "hello", "خوبی", "خوب هستی", "مرسی", "ممنون", "آماده"}


def _next_question(index: int) -> tuple[int, str]:
    target = min(index + 1, len(questions()) - 1)
    session = ACTIVE_SESSION.get()
    if session and session.pending_turn:
        answer = session.pending_turn["text"]
        dest = questionnaire()[index].get("branches", {}).get(answer)
        if dest:
            target = next(i for i, q in enumerate(questionnaire()) if q["id"] == dest)
    return target, questions()[target][1]


def _fallback_participant_turn(action: str, qtext: str, focus: str = "") -> str:
    if action == "repair":
        if focus == "interview_relevance":
            return "برای اینکه گفت‌وگو برای پژوهش قابل استفاده بماند، لطفاً پاسخ را به همین موضوع مرتبط کنید. اگر مایل به ادامه نیستید، می‌توانیم گفت‌وگو را پایان دهیم."
        return "پاسخ‌دادن به این پرسش اختیاری است؛ اگر مایل باشید می‌توانیم از همین پرسش بگذریم یا ادامه دهیم."
    if action == "repeat":
        return qtext
    if action == "simplify":
        return f"اگر بخواهیم ساده‌تر بگوییم، {qtext}"
    if action == "probe":
        return "اگر ممکن است، کمی بیشتر توضیح می‌دهید؟"
    return qtext


def _participant_safe(candidate: str, fallback: str, action: str, answer: str) -> str:
    """APK-equivalent guard: never expose a raw planning artifact or an echo."""
    text = candidate.strip().replace("```", "")
    normalized = _normalize(text)
    answer_normalized = _normalize(answer)
    unsafe = (
        len(normalized) < 2
        or "json" in normalized
        or "{\"action\"" in normalized
        or normalized == answer_normalized
        or (len(answer_normalized) >= 8 and answer_normalized in normalized)
        or text.count("؟") > 1
    )
    if action in {"probe", "simplify", "repeat"} and "؟" not in text:
        unsafe = True
    if action == "repair" and "؟" in text:
        unsafe = True
    return fallback if unsafe else text


def _planner_prompt(qid: str, qtext: str, answer: str) -> str:
    return f"نقش شما فقط مدیر گفت‌وگو است؛ پیام روبه‌پاسخ‌دهنده ننویسید. پرسش جاری {qid}: «{qtext}». هدف: {question_goals()[qid]}. پاسخ آخر: «{answer}»."


def _interviewer_prompt(qid: str, qtext: str, answer: str, action: str, focus: str) -> str:
    return f"پرسش جاری {qid}: «{qtext}». پاسخ آخر: «{answer}». مدیر گفت‌وگو فقط این اقدام کمینه را تأیید کرده است: {action}؛ تمرکز: {focus or 'بدون تمرکز اضافی'}. فقط پیام فارسی روبه‌پاسخ‌دهنده را بنویسید."


def _close_message() -> str:
    return "از وقتی که برای این گفت‌وگو گذاشتید سپاسگزارم. پاسخ‌های شما ثبت شدند."


def _disengagement_close_message() -> str:
    return "به نظر می‌رسد ادامهٔ گفت‌وگو برایتان مناسب نیست. از زمانی که گذاشتید سپاسگزارم؛ پاسخ‌های ثبت‌شده محفوظ می‌مانند."


def _short_affirmative(text: str) -> bool:
    return _normalize(text).strip(" .!؟") in {"بله", "آره", "اره", "آری", "yes", "y"}


def _short_negative(text: str) -> bool:
    return _normalize(text).strip(" .!؟") in {"نه", "خیر", "نه ممنون", "خیر ممنون", "no", "n"}


def _final_prompt_request(text: str) -> bool:
    """Recognize natural willingness to continue without confusing it with content."""
    low = _normalize(text)
    return _short_affirmative(text) or any(phrase in low for phrase in (
        "بیا ادامه بدیم", "ادامه بدیم", "ادامه دهیم", "بپرس", "سؤال بپرس", "سوال بپرس", "بگو",
    ))


def _final_invitation_turn(session: InterviewSession, answer: str) -> dict[str, Any]:
    """Give Q13 a genuine, bounded conversational closing opportunity."""
    stage = session.final_invitation_stage
    if stage == 0 and _final_prompt_request(answer):
        session.final_invitation_stage = 1
        return {"action": "repair", "participant_turn": "حتماً. لطفاً مهم‌ترین نکته، تجربه، نگرانی یا امیدی را که درباره هوش مصنوعی دارید و هنوز مطرح نشده، بنویسید.", "reason": "final invitation accepted"}
    if stage == 0 and _short_negative(answer):
        return {"action": "close", "participant_turn": _close_message(), "reason": "final invitation declined"}
    if stage == 1 and _final_prompt_request(answer):
        return {"action": "repair", "participant_turn": "حتماً. همان نکته‌ای را که مایلید مطرح کنید، بنویسید.", "reason": "final invitation participant requested a prompt"}
    if stage <= 1:
        session.final_invitation_stage = 2
        return {"action": "repair", "participant_turn": "اگر نکتهٔ دیگری هم هست که مایلید اضافه کنید، لطفاً بنویسید؛ در غیر این صورت می‌توانیم گفت‌وگو را تمام کنیم.", "reason": "one final additional opportunity"}
    if stage == 2 and _final_prompt_request(answer):
        session.final_invitation_stage = 3
        return {"action": "repair", "participant_turn": "حتماً. آن نکته را هم با زبان خودتان بنویسید.", "reason": "final additional point accepted"}
    return {"action": "close", "participant_turn": _close_message(), "reason": "final invitation complete"}


def _close_is_permitted(session: InterviewSession, decision: dict[str, Any]) -> bool:
    return bool(
        session.question_index == len(questions()) - 1
        or decision.get("terminationIntent") == "explicit"
        or (decision.get("engagement") == "disengaged" and session.disengagement_notices > 0)
        or decision.get("_final_close")
    )


def _apply_lite_decision(session: InterviewSession, answer: str, decision: dict[str, Any], *, mode: str, timeout: float) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Run the Android Lite contract: route first, then independently word it."""
    index = session.question_index
    qid, qtext, _ = questions()[index]
    decision = _normalize_semantic_decision(decision, answer, session)
    action = str(decision.get("action", "")).lower()
    if action == "pause":
        action = "repair"  # compatibility with transcripts from protocol 3.x
    if action not in ALLOWED_ACTIONS:
        raise ValueError("invalid planner action")
    engagement = str(decision.get("engagement", "engaged")).lower()
    if engagement == "possible_mocking":
        action = "close" if session.disengagement_notices else "repair"
        decision["focus"] = "interview_relevance"
        decision["engagement"] = "disengaged" if session.disengagement_notices else "possible_mocking"
    if action == "close" and not _close_is_permitted(session, decision):
        action = "repair"
    result = {"action": action, "reason": str(decision.get("reason", "model route")), "focus": str(decision.get("focus", "")), "terminationIntent": decision.get("terminationIntent", "none"), "engagement": decision.get("engagement", "engaged"), "intent": decision.get("intent"), "is_research_evidence": decision.get("is_research_evidence"), "meaning_summary": decision.get("meaning_summary"), "current_question_open": decision.get("current_question_open"), "next_action": decision.get("next_action", action), "confidence": decision.get("confidence"), "evidence_quotes": decision.get("evidence_quotes", [])}
    if action in {"advance", "close"}:
        return result, None
    fallback = _fallback_participant_turn(action, qtext, result["focus"])
    if action == "repair" and result["focus"] == "interview_relevance":
        # Classification is model-led; this one visible boundary is authored
        # so the participant always receives the same calm, non-accusatory
        # invitation rather than a speculative model explanation.
        result["participant_turn"] = fallback
        return result, None
    draft, usage = _model_text(
        session, answer, system=INTERVIEWER_SYSTEM,
        prompt=_interviewer_prompt(qid, qtext, answer, action, result["focus"]),
        mode=mode, timeout_seconds=timeout,
    )
    result["participant_turn"] = _participant_safe(draft, fallback, action, answer)
    return result, usage


def next_turn(session: InterviewSession, answer: str, turn_id: str | None = None) -> InterviewSession:
    token = ACTIVE_SETTINGS.set(session.settings_snapshot)
    session_token = ACTIVE_SESSION.set(session)
    before = len(session.messages)
    started = time.perf_counter()
    received = datetime.now(timezone.utc).isoformat()
    index = session.question_index
    try:
        result = _next_turn(session, answer, turn_id)
        ended = datetime.now(timezone.utc).isoformat()
        if len(session.messages) > before:
            for message in session.messages[before:]:
                message.setdefault('timestamp', received if message.get('role') == 'user' else ended)
                message.setdefault('message_id', str(uuid.uuid4()))
                message.setdefault('turn_id', turn_id or session.processed_turn_ids[-1])
            session.turn_metrics.append({'turn_id': turn_id or session.processed_turn_ids[-1], 'question_id': questions()[index][0], 'received_at': received, 'responded_at': ended, 'duration_ms': round((time.perf_counter() - started) * 1000, 2)})
            if session.status == 'completed':
                session.completed_at = ended
                latest = session.decision_log[-1] if session.decision_log else {}
                session.completion_reason = (
                    'technical_failure' if latest.get('execution_mode') == 'safe_final_close' else
                    'participant_disengaged' if latest.get('engagement') == 'disengaged' else
                    'participant_requested_end' if _explicit_termination(answer) else
                    'final_question_answered' if index == len(questions()) - 1 else
                    'participant_requested_end'
                )
                session.status = {'technical_failure': 'interrupted', 'participant_requested_end': 'withdrawn', 'participant_disengaged': 'withdrawn'}.get(session.completion_reason, 'completed')
        return result
    finally:
        ACTIVE_SETTINGS.reset(token)
        ACTIVE_SESSION.reset(session_token)

def _next_turn(session: InterviewSession, answer: str, turn_id: str | None = None) -> InterviewSession:
    answer = answer.strip()
    if not answer:
        return session
    turn_id = turn_id or str(uuid.uuid4())
    if turn_id in session.processed_turn_ids:
        return session
    if session.pending_turn and session.pending_turn.get("id") != turn_id:
        raise RuntimeError("نوبت قبلی هنوز در حال بازیابی است؛ ابتدا همان نوبت را ادامه دهید.")
    session.error_message = ""
    index = session.question_index
    if not session.pending_turn:
        session.pending_turn = {"id": turn_id, "text": answer, "question_id": questions()[index][0], "started_at": datetime.now(timezone.utc).isoformat()}
    if not any(message.get("turn_id") == turn_id for message in session.messages):
        session.messages.append({"role":"user", "content":answer, "question_id":questions()[index][0], "turn_id":turn_id, "control":session.pending_turn.get('control','answer')})
    if session.architecture in {"rules_based_simple", "rulesbasedsimple"}:
        trace_started_at, trace_started_perf, trace_call_offset = datetime.now(timezone.utc).isoformat(), time.perf_counter(), len(session.model_calls)
        session = _rules_based_turn(session, answer, index)
        fallback_intent = "termination" if _explicit_termination(answer) else ("social_greeting" if _social_opening(answer) else ("process_question" if _asks_for_process(answer) else ("role_boundary_question" if _asks_for_role_boundary(answer) else ("refusal" if _normalize(answer) in {"نه", "خیر"} else "research_answer"))))
        fallback_action = "close" if fallback_intent == "termination" else ("advance" if fallback_intent in {"research_answer", "refusal"} else "repair")
        _update_semantic_state(session, questions()[index][0], answer, {"intent": fallback_intent, "action": fallback_action, "next_action": fallback_action, "is_research_evidence": fallback_intent == "research_answer", "meaning_summary": answer[:240], "current_question_open": fallback_intent not in {"termination", "refusal"}})
        _record_architecture_attempt(session, turn_id=turn_id, question_id=questions()[index][0],
                                     architecture="rules_based_simple", execution_mode="rules_based_simple",
                                     outcome="success", started_at=trace_started_at, started_perf=trace_started_perf,
                                     call_offset=trace_call_offset, reason="configured_rules_based")
        session.processed_turn_ids.append(turn_id)
        session.pending_turn = None
        return session

    qid, qtext, probe_limit = questions()[index]
    recovered = False
    execution_mode = session.architecture
    trace_architecture = session.architecture
    trace_outcome = "success"
    trace_fallback_from = None
    trace_reason = None
    trace_started_at, trace_started_perf, trace_call_offset = datetime.now(timezone.utc).isoformat(), time.perf_counter(), len(session.model_calls)

    # These participant-control intents have strict precedence over research
    # probes. This is the missing protection that let protocol 3.9 ask Q9
    # after the participant had explicitly said «تمام کن».
    if _explicit_termination(answer):
        execution_mode = "participant_control"
        decision = {"action": "close", "reason": "explicit termination", "terminationIntent": "explicit"}
    elif (control_turn := _participant_control_turn(session, answer, index)):
        # Explicit conversational requests are handled before both Lite and
        # Fast Guided. This keeps a temporary model fallback from treating a
        # date, memory check, or request for an example as a missing answer.
        execution_mode = "participant_control"
        decision = control_turn
    elif session.question_index == len(questions()) - 1 and session.pending_turn.get('control') != 'clarify':
        execution_mode = "final_invitation_protocol"
        # The final invitation is deliberately handled without a provider
        # call. A bare «بله» is consent to add a point, not an answer that
        # closes the interview.
        decision = _final_invitation_turn(session, answer)
    elif questionnaire()[index]["kind"] != "open" and session.pending_turn.get('control') != 'clarify':
        execution_mode = "closed_item_protocol"
        decision = {"action": "advance", "reason": "closed item"}
    elif _wants_next_question(answer):
        execution_mode = "participant_control"
        decision = {"action": "advance", "reason": "participant requested next question"}
    elif index == 0 and _social_opening(answer):
        execution_mode = "social_opening_protocol"
        decision = {"action": "repeat", "reason": "social opening", "focus": "پرسش اول را کوتاه و طبیعی بازگو کن"}
    else:
        try:
            if session.architecture == "simple_adaptive":
                raw, usage = _model_decision(
                    session, answer, mode="simple_adaptive", attempts=1,
                    timeout_seconds=_wait_seconds("INTERVIEW_FAST_GUIDED_WAIT_SECONDS", 10),
                    system_override=FAST_GUIDED_SYSTEM,
                    prompt_override=_planner_prompt(qid, qtext, answer), max_tokens=420,
                )
                session.usage.append(usage)
                decision = raw
                action = str(decision.get("action", "")).lower()
                if action not in ALLOWED_ACTIONS:
                    raise ValueError("invalid fast-guided action")
                engagement = str(decision.get("engagement", "engaged")).lower()
                if engagement == "possible_mocking":
                    action = "close" if session.disengagement_notices else "repair"
                    decision.update(action=action, focus="interview_relevance", engagement="disengaged" if session.disengagement_notices else "possible_mocking")
                if action == "close" and not _close_is_permitted(session, decision):
                    action = "repair"
                    decision["action"] = action
                if action not in {"advance", "close"}:
                    decision["participant_turn"] = _participant_safe(
                        str(decision.get("message", "")),
                        _fallback_participant_turn(action, qtext, str(decision.get("focus", ""))), action, answer,
                    )
            else:
                # Lite and Lead both separate routing from participant-facing
                # wording. Lead gets a more autonomous routing contract while
                # retaining the same safe two-call boundary.
                lead_mode = session.architecture == "conversational_lead"
                route_mode = "conversational_lead" if lead_mode else "multi_agent_lite"
                route_system = CONVERSATIONAL_LEAD_SYSTEM if lead_mode else PLANNER_SYSTEM
                decision, usage = _model_decision(
                    session, answer, mode=route_mode, attempts=1,
                    timeout_seconds=_wait_seconds("INTERVIEW_LITE_WAIT_SECONDS", 12),
                    system_override=route_system,
                    prompt_override=_planner_prompt(qid, qtext, answer), max_tokens=600,
                )
                session.usage.append(usage)
                decision, wording_usage = _apply_lite_decision(
                    session, answer, decision, mode=route_mode,
                    timeout=_wait_seconds("INTERVIEW_LITE_WAIT_SECONDS", 12),
                )
                if wording_usage:
                    session.usage.append(wording_usage)
        except Exception as exc:
            if session.architecture in {"multi_agent_lite", "conversational_lead", "simple_adaptive"}:
                _record_architecture_attempt(session, turn_id=turn_id, question_id=qid,
                                             architecture=session.architecture, execution_mode=session.architecture,
                                             outcome="failure", started_at=trace_started_at, started_perf=trace_started_perf,
                                             call_offset=trace_call_offset, reason=_failure_code(exc))
                recovery_started_at, recovery_started_perf, recovery_call_offset = datetime.now(timezone.utc).isoformat(), time.perf_counter(), len(session.model_calls)
                try:
                    decision, usage = _model_decision(
                        session, answer, mode="fast_guided", attempts=1,
                        timeout_seconds=_wait_seconds("INTERVIEW_FAST_GUIDED_WAIT_SECONDS", 10),
                        system_override=FAST_GUIDED_SYSTEM,
                        prompt_override=_planner_prompt(qid, qtext, answer), max_tokens=420,
                    )
                    session.usage.append(usage)
                    action = str(decision.get("action", "")).lower()
                    if action not in ALLOWED_ACTIONS:
                        raise ValueError("invalid recovery action")
                    engagement = str(decision.get("engagement", "engaged")).lower()
                    if engagement == "possible_mocking":
                        action = "close" if session.disengagement_notices else "repair"
                        decision.update(action=action, focus="interview_relevance", engagement="disengaged" if session.disengagement_notices else "possible_mocking")
                    if action == "close" and not _close_is_permitted(session, decision):
                        action = "repair"
                        decision["action"] = action
                    if action not in {"advance", "close"}:
                        decision["participant_turn"] = _participant_safe(
                            str(decision.get("message", "")),
                            _fallback_participant_turn(action, qtext, str(decision.get("focus", ""))), action, answer,
                        )
                    execution_mode = "fast_guided_recovery"
                    recovered = True
                    trace_architecture, trace_outcome = "fast_guided", "fallback"
                    trace_fallback_from, trace_reason = session.architecture, "primary_hosted_route_failed"
                    trace_started_at, trace_started_perf, trace_call_offset = recovery_started_at, recovery_started_perf, recovery_call_offset
                except Exception as recovery_error:
                    _record_architecture_attempt(session, turn_id=turn_id, question_id=qid,
                                                 architecture="fast_guided", execution_mode="fast_guided_recovery",
                                                 outcome="failure", started_at=recovery_started_at, started_perf=recovery_started_perf,
                                                 call_offset=recovery_call_offset, reason=_failure_code(recovery_error),
                                                 fallback_from=session.architecture)
                    session.error_message = f"Primary route: {exc}; Fast Guided: {recovery_error}"
                    decision = _safe_final_close(index, "primary and Fast Guided routes unavailable")
                    execution_mode, recovered = "safe_final_close", True
                    trace_architecture, trace_outcome = "rules_based_simple", "fallback"
                    trace_fallback_from, trace_reason = "fast_guided", "primary_and_fast_failed"
                    trace_started_at, trace_started_perf, trace_call_offset = datetime.now(timezone.utc).isoformat(), time.perf_counter(), len(session.model_calls)
            else:
                _record_architecture_attempt(session, turn_id=turn_id, question_id=qid,
                                             architecture=session.architecture, execution_mode=session.architecture,
                                             outcome="failure", started_at=trace_started_at, started_perf=trace_started_perf,
                                             call_offset=trace_call_offset, reason=_failure_code(exc))
                session.error_message = str(exc)
                decision = _safe_final_close(index, "hosted route unavailable")
                execution_mode, recovered = "safe_final_close", True
                trace_architecture, trace_outcome = "rules_based_simple", "fallback"
                trace_fallback_from, trace_reason = session.architecture, "hosted_route_failed"
                trace_started_at, trace_started_perf, trace_call_offset = datetime.now(timezone.utc).isoformat(), time.perf_counter(), len(session.model_calls)

    decision = _normalize_semantic_decision(decision, answer, session)
    action = str(decision.get("action", "advance")).lower()
    if action == "pause":
        action = "repair"
    if action == "finish":
        action = "close"
    if action == "close" and not _close_is_permitted(session, decision):
        action = "repair"
    if action == "repair" and decision.get("focus") == "interview_relevance":
        decision["participant_turn"] = _fallback_participant_turn("repair", qtext, "interview_relevance")
    if action == "close":
        close_text = str(decision.get("participant_turn") or (_disengagement_close_message() if decision.get("engagement") == "disengaged" else _close_message()))
        session.messages.append({"role": "assistant", "content": close_text})
        session.status = "completed"
        session.question_index = index
    elif action == "advance":
        target, text = _next_question(index)
        session.question_index, session.probe_count = target, 0
        session.messages.append({"role": "assistant", "content": text})
    else:
        if action not in {"probe", "simplify", "repeat", "repair"}:
            action = "repair"
        text = _participant_safe(
            str(decision.get("participant_turn", "")),
            _fallback_participant_turn(action, qtext, str(decision.get("focus", ""))), action, answer,
        )
        if action == "probe":
            session.probe_count += 1
            if session.probe_count > probe_limit:
                target, text = _next_question(index)
                session.question_index, session.probe_count, action = target, 0, "advance"
        elif action == "simplify":
            session.probe_count += 1
        if action == "repair" and decision.get("engagement") == "possible_mocking":
            session.disengagement_notices += 1
        session.messages.append({"role": "assistant", "content": text})

    decision["action"] = action
    decision["_execution_mode"] = execution_mode
    _record_architecture_attempt(session, turn_id=turn_id, question_id=qid,
                                 architecture=trace_architecture, execution_mode=execution_mode,
                                 outcome=trace_outcome, started_at=trace_started_at, started_perf=trace_started_perf,
                                 call_offset=trace_call_offset, reason=trace_reason,
                                 fallback_from=trace_fallback_from)
    _record_decision(session, turn_id, qid, decision, recovered)
    _update_semantic_state(session, qid, answer, decision)
    _maybe_refresh_context_summary(session)
    session.processed_turn_ids.append(turn_id)
    session.pending_turn = None
    session.updated_at = datetime.now(timezone.utc).isoformat()
    return session


def _rules_based_turn(session: InterviewSession, answer: str, index: int) -> InterviewSession:
    """Advance through authored questions with zero model/network calls."""
    low = answer.strip().lower()
    if (session.pending_turn or {}).get('control') == 'clarify':
        session.messages.append({'role':'assistant', 'content':questions()[index][1]})
        return session
    if any(token in low for token in ("توقف", "تمام", "خداحافظ", "دیگه نمی", "نمی‌خوام ادامه")):
        session.messages.append({"role":"assistant", "content":"از وقتی که گذاشتید سپاسگزارم. مصاحبه در همین‌جا پایان می‌یابد."})
        session.status = "completed"
        session.updated_at = datetime.now(timezone.utc).isoformat()
        return session
    # The reliability fallback is intentionally simple, but it must still
    # recognise explicit ordinary conversation.  Otherwise a date request or
    # a request for an example would be silently recorded as an answer.
    if control_turn := _participant_control_turn(session, answer, index):
        session.messages.append({"role": "assistant", "content": control_turn["participant_turn"]})
        session.updated_at = datetime.now(timezone.utc).isoformat()
        return session
    if index == 0 and any(token in low for token in ("سلام", "درود", "خوبم", "مرسی", "ممنون", "آماده")):
        session.messages.append({"role":"assistant", "content":"سلام، خوش آمدید. " + questions()[0][1]})
        session.updated_at = datetime.now(timezone.utc).isoformat()
        return session
    if "سوال اول" in low or "سؤال اول" in low:
        session.question_index = 0
        session.messages.append({"role":"assistant", "content":questions()[0][1]})
        session.updated_at = datetime.now(timezone.utc).isoformat()
        return session
    if "سوال قبلی" in low or "سؤال قبلی" in low or "برگرد" in low:
        target = max(0, index - 1)
        session.question_index = target
        session.messages.append({"role":"assistant", "content":questions()[target][1]})
        session.updated_at = datetime.now(timezone.utc).isoformat()
        return session
    if index >= len(questions()) - 1:
        decision = _final_invitation_turn(session, answer)
        session.messages.append({"role":"assistant", "content":decision["participant_turn"]})
        if decision["action"] == "close":
            session.status = "completed"
        session.updated_at = datetime.now(timezone.utc).isoformat()
        return session
    target, _ = _next_question(index)
    session.question_index = target
    session.probe_count = 0
    session.messages.append({"role":"assistant", "content":questions()[target][1]})
    session.updated_at = datetime.now(timezone.utc).isoformat()
    return session
