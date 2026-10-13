"""Trusted, immutable per-call experience settings; never mutate process env for a caller."""
from __future__ import annotations
import json
import os
from pathlib import Path

# Intersection of documented GPT-Live and gpt-4o-mini-tts voices, checked 2026-10-12.
# This is API compatibility, NOT an acoustic match to ChatGPT Spruce or an entitlement check.
VOICES = ("cedar", "ash", "marin")
SCENARIOS = ("new_order", "late_delivery", "missing_item", "wrong_item")
ROOT = Path(__file__).resolve().parents[1]


def profile():
    return json.loads((ROOT / "data/hospitality-profile.json").read_text(encoding="utf8"))


def available_experiences():
    return {
        "version": "v3-candidate",
        "default_voice": "cedar",
        "voices": [{"id": name, "label": name.title()} for name in VOICES],
        "voice_change": "between_calls",
        "spruce_available": False,
        "voice_verified": False,
        "scenarios": [
            {"id": "new_order", "label": "مكالمة جديدة", "brief": "اطلب أو اسأل بطريقتك."},
            {"id": "late_delivery", "label": "طلب متأخر", "brief": "طلبك S-DEMO7001 تأخر. اسأل عنه أو قدم شكوى."},
            {"id": "missing_item", "label": "صنف ناقص", "brief": "طلبك S-DEMO7001 وصل، لكن الشكشوكة ناقصة."},
            {"id": "wrong_item", "label": "صنف غير صحيح", "brief": "طلبك S-DEMO7001 وصل، لكن الصنف غير المطلوب."},
        ],
        "disclosure": "تجربة بصوت مولد بالذكاء الاصطناعي. الطلبات والدفع والاسترجاع والموظفون محاكاة، ولا تتحرك أموال حقيقية. تُسجل المكالمة للمراجعة.",
    }


def validate_experience(voice=None, scenario="new_order", version="v3"):
    if version not in ("v2", "v3"):
        raise ValueError("Unknown experience version")
    selected = voice or ("cedar" if version == "v3" else os.getenv("SAWT_VOICE", "marin"))
    if selected not in VOICES:
        raise ValueError("Unsupported voice; choose Cedar, Ash or Marin")
    if scenario not in SCENARIOS or (version == "v2" and scenario != "new_order"):
        raise ValueError("Unknown scenario")
    return {"version": version, "voice": selected, "scenario": scenario,
            "profile_version": "saudi-host-1", "simulation": True}


def call_experience(state):
    saved = state.get("experience")
    if not saved:
        return validate_experience(version="v2")
    return validate_experience(saved.get("voice"), saved.get("scenario", "new_order"), saved.get("version", "v2"))


def voice_instructions():
    p = profile()
    return p["voice_instructions"] + "\nالافتتاحية مرة واحدة: " + p["greeting"]
