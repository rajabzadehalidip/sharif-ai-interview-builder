# AI Interview Builder

A standalone, configurable web interviewer for research teams. This project contains no Sharif AI Index protocol, questionnaire, prompt, participant data, logo, or API key.

## What the researcher controls

Through **پنل پژوهشگر**, an administrator can create and publish a versioned protocol:

- public project title, welcome text, consent text and interview language;
- main system instruction, moderator instruction, interviewer instruction and Fast Guided instruction;
- open, single-choice and multiple-choice questions, their order, goals, probe limits and permitted branches;
- optional pre-interview questions, including conditional display;
- model ID, primary architecture and route timeouts.

The platform kernel retains consent, interruption recovery, turn idempotency, neutral interview conduct, versioned settings, secure server-side keys, exports and the Lite → Fast Guided → Rules-Based reliability path. It is intentionally separate from the study protocol.

## First-time setup

The public page is deliberately blocked until the researcher replaces the placeholder first question and publishes the first protocol version. This prevents a blank project from accidentally collecting data.

1. Create a dashboard password hash:

```bash
python scripts/create_dashboard_password.py
```

2. Run locally:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export INTERVIEW_PROVIDER=gapgpt
export GAPGPT_API_KEY='your-key'
export GAPGPT_MODEL='gpt-5-nano'
export DASHBOARD_SESSION_SECRET='at-least-32-random-characters'
export DASHBOARD_USERS_JSON='<password JSON from the helper>'
uvicorn server:app --reload
```

3. Open `http://127.0.0.1:8000/?view=team`, sign in, complete the protocol and publish it. Use **آزمون پیش‌نویس** before sharing the public URL.

## Liara deployment

Create a new Python application and a fresh persistent disk mounted as `database/`. Set the values from `liara.env.example` in Liara Variables. Use a different database, secret and API key from every other deployment. Do not place API keys in Git or in browser code. The customer enters their provider key in Liara **Variables/Secrets**, not in the public interview page or the protocol database.

The project is intended to be deployed as a separate application, for example `interview-builder.liara.run`.

## Three client-facing architectures

- **Simple Adaptive**: one constrained model call chooses whether to advance, clarify, probe or repair. It is the quickest hosted route.
- **Multi-agent Lite**: one call plans the next action and a second call writes the participant-facing message. It is the recommended default for fieldwork.
- **Conversational Lead**: a more autonomous routing prompt uses the recent transcript and research goals to choose a purposeful follow-up, while the server still enforces order, consent and safe fallback boundaries.

All three use the same editable questions, goals, pre-interview form and prompt editor. If a hosted call fails, the current answer is preserved and the next configured recovery route is attempted for that turn.
