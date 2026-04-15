from openai import OpenAI
from middlewares.pipeline import LLMRequest, LLMResponse
import re
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

# =========================
# 설정값
# =========================
GLOBAL_BLOCK_THRESHOLD = 0.6

BAD_WORD_PATTERN = re.compile(
    r"(씨발|시발|ㅅㅂ|병신|븅신|ㅄ|개새끼|ㅈ같|좆|fuck)",
    re.IGNORECASE
)

PII_PATTERNS = {
    "PHONE": re.compile(r"\b01[0-9][-\s]?\d{3,4}[-\s]?\d{4}\b"),
    "EMAIL": re.compile(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b"),
    "CARD": re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b"),
    "RRN": re.compile(r"\b\d{6}-?[1-4]\d{6}\b"),
    "PASSPORT": re.compile(r"\b[A-Z]{1,2}\d{7,8}\b"),
    "ACCOUNT": re.compile(r"\b\d{2,4}-\d{2,6}-\d{2,6}\b"),
}

PATTERN_ORDER = ["PHONE", "EMAIL", "CARD", "RRN", "PASSPORT", "ACCOUNT"]
HIGH_RISK_TYPES = {"RRN", "CARD", "ACCOUNT"}
MEDIUM_RISK_TYPES = {"PHONE", "EMAIL", "PASSPORT"}


# =========================
# 욕설 처리
# =========================
def contains_bad_word(text: str) -> bool:
    return bool(text and BAD_WORD_PATTERN.search(text))


def check_moderation(client: OpenAI, text: str) -> Dict:
    response = client.moderations.create(
        model="omni-moderation-latest",
        input=text
    )
    result = response.results[0]
    return {
        "flagged": result.flagged,
        "categories": dict(result.categories),
        "scores": dict(result.category_scores),
    }


def should_block_by_score(category_scores: Dict[str, float]) -> bool:
    for category, score in category_scores.items():
        if score >= GLOBAL_BLOCK_THRESHOLD:
            logger.warning(
                "Moderation blocked: %s=%.4f (threshold=%.2f)",
                category, score, GLOBAL_BLOCK_THRESHOLD
            )
            return True
    return False


def should_block_profanity(client: OpenAI, text: str) -> bool:
    if contains_bad_word(text):
        logger.info("Bad word detected, moderation check continues")

    mod = check_moderation(client, text)
    logger.debug("Moderation result: %s", mod)

    return should_block_by_score(mod["scores"])


def profanity_middleware(openai_client: OpenAI):
    def middleware(request: LLMRequest, next_) -> LLMResponse:
        request.metadata = getattr(request, "metadata", {}) or {}

        user_texts = [
            m.get("content", "")
            for m in request.messages
            if m.get("role") == "user" and isinstance(m.get("content"), str)
        ]
        full_text = " ".join(user_texts)

        logger.info("Profanity middleware executed")

        if should_block_profanity(openai_client, full_text):
            raise ValueError("땃쥐가 상처받아 뒤돌았습니다.")

        profanity_detected = contains_bad_word(full_text)

        if profanity_detected:
            for msg in request.messages:
                if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                    msg["content"] = f"[주의: 과격한 표현 포함]\n{msg['content']}"

        request.metadata["profanity_detected"] = profanity_detected
        return next_(request)

    return middleware


# =========================
# PII 처리
# =========================
def detect_pii(text: str) -> List[Dict]:
    detected = []
    occupied_spans = []

    for pii_type in PATTERN_ORDER:
        pattern = PII_PATTERNS[pii_type]

        for match in pattern.finditer(text):
            start, end = match.start(), match.end()

            overlapped = any(not (end <= s or start >= e) for s, e in occupied_spans)
            if overlapped:
                continue

            detected.append({
                "type": pii_type,
                "value": match.group(),
                "start": start,
                "end": end,
                "risk": "high" if pii_type in HIGH_RISK_TYPES else "medium",
            })
            occupied_spans.append((start, end))

    return detected


def should_block_pii(detected_entities: List[Dict]) -> bool:
    return any(entity["type"] in HIGH_RISK_TYPES for entity in detected_entities)


def redact_pii(text: str, detected_entities: List[Dict]) -> str:
    for entity in sorted(detected_entities, key=lambda x: x["start"], reverse=True):
        text = text[:entity["start"]] + f"[{entity['type']}]" + text[entity["end"]:]
    return text


def sanitize_pii(text: str) -> Dict:
    detected = detect_pii(text)
    return {
        "original_text": text,
        "sanitized_text": redact_pii(text, detected),
        "detected_entities": detected,
        "blocked": should_block_pii(detected),
    }


def pii_middleware():
    def middleware(request: LLMRequest, next_) -> LLMResponse:
        request.metadata = getattr(request, "metadata", {}) or {}

        all_detected = []
        sanitized_user_texts = []

        for msg in request.messages:
            if msg.get("role") != "user" or not isinstance(msg.get("content"), str):
                continue

            result = sanitize_pii(msg["content"])

            if result["detected_entities"]:
                all_detected.extend(result["detected_entities"])
                logger.info(
                    "PII detected: %s",
                    [entity["type"] for entity in result["detected_entities"]]
                )

            msg["content"] = result["sanitized_text"]
            sanitized_user_texts.append(result["sanitized_text"])

            if result["blocked"]:
                request.metadata.update({
                    "pii_detected": True,
                    "pii_entities": all_detected,
                    "sanitized": True,
                    "sanitized_user_input": " ".join(sanitized_user_texts),
                })
                logger.warning("Blocked due to high-risk PII")
                raise ValueError("민감한 개인정보가 포함되어 있어 요청이 차단되었습니다.")

        has_pii = bool(all_detected)
        request.metadata.update({
            "pii_detected": has_pii,
            "pii_entities": all_detected if has_pii else [],
            "sanitized": has_pii,
            "sanitized_user_input": " ".join(sanitized_user_texts),
        })

        return next_(request)

    return middleware