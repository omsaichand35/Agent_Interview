from app.stages.stage4_interview.reasoning.llm_reasoner import (
    LLMInterviewReasoner,
)
from app.stages.stage4_interview.questions.llm_question_generator import (
    LLMQuestionGenerator,
)
from app.stages.stage4_interview.questions.question_generator import (
    generate_criterion_question,
    generate_recovery_question,
)
from app.stages.stage4_interview.reasoning.signal_extractor import (
    SignalExtractor,
)
from app.stages.stage4_interview.evaluation.evaluator import (
    InterviewEvaluator,
)
from app.stages.stage4_interview.evaluation.evidence_aggregator import (
    EvidenceAggregator,
)
from app.stages.stage4_interview.graph.completion import (
    should_conclude,
)
from app.stages.stage4_interview.graph.coverage import criterion_label
from app.stages.stage4_interview.identity_checkpoint import (
    apply_identity_result,
)

from app.stages.stage4_interview.evaluation.evidence import build_evidence
from app.stages.stage4_interview.evaluation.competency_scorer import (
    CompetencyScorer,
)

_signal_extractor = SignalExtractor()


def extract_signals(state):

    answer = state.get("candidate_answer") or ""
    known = state.get("target_competencies") or []

    signals = _signal_extractor.extract(
        answer=answer,
        known_competencies=known,
    )

    existing = state.get("extracted_signals") or []
    for s in signals:
        if s not in existing:
            existing.append(s)

    state["extracted_signals"] = existing

    return state


def check_completion(state):

    if state.get("interview_complete") or state.get("decision") == "conclude":
        state["decision"] = "conclude"
        state["interview_complete"] = True
        state["next_question"] = None
        return state

    if should_conclude(state):

        state["decision"] = "conclude"
        state["interview_complete"] = True
        state["next_question"] = None

        return state

    return state


def create_identity_node(identity_monitor):

    def verify_identity(state):

        live_frame = (
            state.get("current_live_frame")
            or state.get("candidate", {}).get("current_live_frame")
            or state.get("candidate", {}).get("live_image_path")
        )

        reference_image = (
            state.get("candidate", {}).get("photo_path")
        )

        result = identity_monitor.verify(
            reference_image=reference_image,
            live_image=live_frame,
            session_id=state["session_id"],
        )

        return apply_identity_result(state, result)

    return verify_identity

def create_identity_checkpoint_node(identity_checkpoint):

    def identity_checkpoint_node(state):

        result = identity_checkpoint.check(
            candidate_id=state["candidate_id"],
            session_id=state["session_id"],
        )

        state["identity_verified"] = result.verified
        state["last_identity_confidence"] = result.confidence
        state["identity_check_count"] += 1

        state["identity_checks"].extend(
            [
                check.model_dump()
                if hasattr(check, "model_dump")
                else check
                for check in result.checks
            ]
        )

        if not result.verified:
            state["identity_failure_reason"] = (
                result.failure_reason
            )

        return state

    return identity_checkpoint_node


def create_nodes(llm_client):

    reasoner = LLMInterviewReasoner(llm_client)
    question_generator = LLMQuestionGenerator(llm_client)
    evaluator = InterviewEvaluator(llm_client)
    aggregator = EvidenceAggregator()

    def reason_about_answer(state):

        # An evaluation belongs only to the current answer. Without clearing it,
        # recovery/introduction turns could expose a prior answer's score.
        state.pop("evaluation", None)
        state["answered_competency"] = state.get("current_competency")
        state["answered_coverage_phase"] = state.get("coverage_phase", "horizontal")

        if state.get("coverage_phase") == "introduction":
            answer = (state.get("candidate_answer") or "").strip()
            unusable = answer.casefold() in {"i don't know", "no idea", "pass", "skip", "idk"} or len(answer) < 20
            state.setdefault("extracted_signals", [])
            state.setdefault("discovered_competencies", [])
            state.setdefault("explored_competencies", [])
            if unusable:
                state["bad_answer_count"] = state.get("bad_answer_count", 0) + 1
                if state["bad_answer_count"] >= 2:
                    state["decision"] = "conclude"
                    state["interview_complete"] = True
                    state["next_question"] = None
                else:
                    state["decision"] = "recover"
                    state["recovery_attempted"] = True
                state["reasoning"] = "The introduction needs a little more detail."
                state["reasoning_confidence"] = 1.0
            else:
                state["bad_answer_count"] = 0
                state["decision"] = "next_competency"
                state["reasoning"] = "Introduction complete; begin the configured evaluation criteria."
                state["reasoning_confidence"] = 1.0
            return state

        result = reasoner.analyze(
            candidate_answer=state.get("candidate_answer", ""),
            current_competency=state.get("current_competency"),
            target_competencies=state.get("target_competencies", []),
            explored_competencies=state.get("explored_competencies", []),
            conversation_history=state.get("conversation_history", []),
        )

        state.setdefault("extracted_signals", [])
        state.setdefault("discovered_competencies", [])
        state.setdefault("explored_competencies", [])
        state.setdefault("evidence", {})

        state["trigger_phrase"] = (
            result.trigger_phrase
        )

        state["extracted_signals"] = (
            result.extracted_signals or state["extracted_signals"]
        )

        decision = (result.decision or "deepen").lower()

        # Catch obvious uncooperative or non-responsive answers if LLM missed it
        raw_ans = (state.get("candidate_answer") or "").strip().lower()
        bad_phrases = [
            "i don't know",
            "i don't know.",
            "no idea",
            "no idea.",
            "pass",
            "fuck off",
            "fuck off.",
            "refuse",
            "skip",
            "whatever",
            "idk",
        ]
        if raw_ans in bad_phrases:
            decision = "recover"

        if decision == "recover":
            state["bad_answer_count"] = state.get("bad_answer_count", 0) + 1
            if state["bad_answer_count"] >= 2:
                state["decision"] = "conclude"
                state["interview_complete"] = True
                state["next_question"] = None
            else:
                state["decision"] = "recover"
                state["recovery_attempted"] = True
        else:
            state["bad_answer_count"] = 0
            state["decision"] = decision

        state["reasoning"] = result.rationale

        state["reasoning_confidence"] = (
            result.confidence
        )

        # Never let the generic skills taxonomy expand this program's rubric.
        # A pivot is valid only when the reasoner names another configured item.
        targets = [
            str(item).strip()
            for item in (state.get("target_competencies") or [])
            if str(item).strip()
        ]
        allowed_targets = {item.casefold(): item for item in targets}
        requested_target = str(result.target_competency or "").strip()
        if decision == "pivot":
            configured_target = allowed_targets.get(requested_target.casefold())
            if (
                not configured_target
                or configured_target == state.get("current_competency")
                or configured_target in state.get("explored_competencies", [])
            ):
                decision = "deepen"
                state["discovered_competencies"] = []
            else:
                state["discovered_competencies"] = [configured_target]
        else:
            state["discovered_competencies"] = []

        state["decision"] = decision

        return state

    def generate_next_question(state):

        if state.get("interview_complete") or state.get("decision") == "conclude":
            state["next_question"] = None
            state["interview_complete"] = True
            return state

        if state.get("decision") == "recover":
            competency = state.get("current_competency")
            if not competency and state.get("coverage_phase") != "introduction":
                competency = "technical_skills"
            recovery_q = generate_recovery_question(
                competency,
                phase=state.get("coverage_phase", "horizontal"),
                answer=state.get("candidate_answer", ""),
            )
            state["next_question"] = recovery_q
            state["current_question"] = recovery_q
            return state

        competency = state.get("current_competency")

        if state.get("decision") == "pivot":
            discovered = state.get("discovered_competencies", [])
            allowed = {
                str(item).strip().casefold(): str(item).strip()
                for item in (state.get("target_competencies") or [])
                if str(item).strip()
            }
            if discovered and str(discovered[-1]).strip().casefold() in allowed:
                competency = discovered[-1]

        try:
            display_competency = criterion_label(str(competency or ""))
            history = [
                str(turn.get("question", "")).strip()
                for turn in (state.get("conversation_history") or [])
                if isinstance(turn, dict) and turn.get("question")
            ]
            result = question_generator.generate(
                competency=display_competency,
                decision=state.get("decision", ""),
                intent=(
                    "Ask one simple question about a key idea in this criterion."
                    if state.get("coverage_phase") == "horizontal"
                    else "Ask one simple follow-up that asks the candidate to explain one idea in this criterion a little more."
                ),
                answer=state.get("candidate_answer", ""),
                previous_question=state.get("current_question", ""),
                phase=state.get("coverage_phase", "horizontal"),
                question_history=history,
            )
        except Exception:
            result = None
        generic_markers = (
            "describe one specific example",
            "tell me about your experience",
            "what experience do you have",
            "walk me through a project",
            "tell me about a project",
            "walk me through a problem you solved with code",
            "a problem you solved with code that you're particularly proud",
            "in your experience",
            "from your coursework",
            "on your resume",
        )
        question_text = str(getattr(result, "question", "") or "").strip()
        is_generic = any(marker in question_text.casefold() for marker in generic_markers)
        leaks_weight = "%" in question_text
        if (
            not result
            or criterion_label(str(result.competency)).casefold() != display_competency.casefold()
            or not question_text
            or is_generic
            or leaks_weight
        ):
            state["next_question"] = generate_criterion_question(
                competency,
                state.get("coverage_phase", "horizontal"),
                state.get("candidate_answer", ""),
            )
        else:
            state["next_question"] = result.question

        return state

    def evaluate_answer(state):

        if state.get("coverage_phase") == "introduction" or state.get("decision") == "recover" or state.get("interview_complete"):
            return state

        competency = state.get("current_competency")
        result = evaluator.evaluate(
            competency=competency,
            question=state.get("current_question", ""),
            answer=state.get("candidate_answer", ""),
        )

        evaluation = result.model_dump()
        # Keep evaluator output attached to the planned criterion even if the
        # model responds with a different label.
        evaluation["competency"] = competency
        state["answered_competency"] = competency

        state["evaluation"] = evaluation

        state["evidence"].setdefault(
            competency,
            [],
        )

        state["evidence"][competency].append(
            evaluation
        )

        state["competency_scores"] = (
            aggregator.aggregate(
                state["evidence"]
            )
        )

        return state

    return (
        reason_about_answer,
        evaluate_answer,
        generate_next_question,
    )
