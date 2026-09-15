"""Explainable configuration and heuristics, not measured capability or price claims."""

import re
from typing import Literal

from pydantic import Field

from .models import Record
from .runner import Blocked

Mode = Literal["engineering", "hackathon", "economy"]
Level = Literal["low", "medium", "high"]
Difficulty = Literal["trivial", "low", "medium", "high", "frontier"]
Verification = Literal["strong", "partial", "weak"]
Cost = Literal["very_low", "low", "medium", "high", "premium"]
ALIASES = {"dev": "engineering", "hack": "hackathon"}
WEIGHTS = {
    "engineering": {"quality": 4, "reliability": 3, "latency": 2, "cost": 2},
    "economy": {"quality": 1, "reliability": 2, "latency": 2, "cost": 12},
    "hackathon": {"quality": 5, "reliability": 4, "latency": 6, "cost": 0},
}
MODE_TEXT = {
    "engineering": "Ship the smallest correct implementation. Correctness, reliability, working result and maintainability; no speculative refactoring.",
    "economy": "Use the cheapest sufficient reasoning. Prefer deterministic evidence, small scope and executable tests. No optional analysis or features.",
    "hackathon": "Maximise a winning working demo before the supplied deadline. Prioritise rubric, visible value, reliability, comprehension and sponsor requirements. Choose ONE demo moment; return pitch and fallback. Monetary routing weight is zero. Freeze stable code.",
}


class TaskProfile(Record):
    domain_tags: list[str]
    difficulty: Literal["trivial", "low", "medium", "high", "frontier"]
    ambiguity: Level
    consequence_of_failure: Level
    verification_strength: Literal["strong", "partial", "weak"]
    latency_sensitivity: Literal["low", "medium", "high", "critical"]
    context_size: Literal["small", "medium", "large"]
    reasoning_types: list[str]
    parallel_value: Level
    explanation: list[str]
    deterministic_action: Literal["test"] | None = None


class Specialist(Record):
    role: str
    jurisdiction: str
    question: str


# Lenses are deliberately distinct; selection uses only relevant matched domains.
LENSES = {
    "Physicist": (
        "physics",
        "State variables, dynamics, conservation, dimensional consistency, symmetry and controlled approximations",
        "Which physical constraints or approximations determine the implementation's validity?",
    ),
    "Mathematician": (
        "mathematics",
        "Formal structure, invariants, optimisation, counterexamples, numerical stability and edge cases",
        "Which invariant, algorithm or numerical stability bound must the implementation preserve?",
    ),
    "Statistician": (
        "statistics",
        "Sampling, bias, variance, uncertainty, leakage, calibration and experimental design",
        "Does the evidence support the claimed improvement, and what test could falsify it?",
    ),
    "Data Scientist": (
        "data",
        "Data generation, features, baselines, metrics, validation, distribution shift and prediction versus inference",
        "Which data process, baseline and validation split make this result meaningful?",
    ),
    "Software Engineer": (
        "software",
        "Smallest correct implementation, interfaces, tests, failure handling and integration",
        "What is the smallest implementable change and its executable failure test?",
    ),
    "Systems Engineer": (
        "systems",
        "Component interfaces, throughput, latency, concurrency, resource bounds and failure propagation",
        "Which component interaction or resource/concurrency invariant causes the failure?",
    ),
    "Product Engineer": (
        "product",
        "Actual user objective, visible value, scope and product acceptance",
        "What observable user outcome matters and what should stay out of scope?",
    ),
    "UX / Human Factors": (
        "ux",
        "Friction, comprehension, accessibility and human error",
        "Where will users misunderstand or fail this interaction, and how can we verify clarity?",
    ),
    "Security / Reliability": (
        "security",
        "Trust boundaries, adversarial inputs, failure containment and recovery",
        "Which concrete misuse or failure scenario must the delivered implementation survive?",
    ),
    "Hackathon Strategist / Judge": (
        "hackathon",
        "Judging rubric, sponsor requirements, wow per minute, deadline and demo reliability",
        "Which one demo moment wins the most rubric value without risking completion?",
    ),
}
PATTERNS = {
    "physics": r"\b(physics|physical|relativistic|doppler|aberration|starfield|gravity|orbital|fluid|energy|dynamics|simulation)\b",
    "mathematics": r"\b(mathematical|mathematics|numerical|solver|optimisation|optimization|proof|invariant|relativistic|stability|integrator)\b",
    "statistics": r"\b(statistical|statistics|classifier|sampling|bias|significance|genuine|causal|confidence interval|hypothesis|a/b)\b",
    "data": r"\b(data|classifier|machine learning|feature engineering|feature selection|dataset|prediction|distribution shift|ml)\b",
    "systems": r"\b(distributed|queue|concurrency|deadlock|throughput|latency|race condition|backpressure)\b",
    "ux": r"\b(responsive|landing.page|waitlist|accessibility|ux|user interface|form)\b",
    "security": r"\b(security|authentication|authorisation|authorization|exploit|untrusted|unstable|distributed|unsafe)\b",
}


def profile_task(
    objective: str,
    mode: Mode,
    *,
    context_chars: int = 0,
    has_tests: bool = False,
    remaining_seconds: float = 900,
) -> TaskProfile:
    text = objective.lower().strip().rstrip(".! ")
    tags = [tag for tag, pattern in PATTERNS.items() if re.search(pattern, text)]
    tags.append("software")
    if "ux" in tags or len(tags) == 1:
        tags.append("product")
    if mode == "hackathon":
        tags.append("hackathon")
    deterministic: Literal["test"] | None = (
        "test" if re.fullmatch(r"(run|verify)( the)?( existing)? tests", text) else None
    )
    simple = bool(re.search(r"\b(rename|format|typo|literal|health endpoint)\b", text))
    hard = any(tag in tags for tag in ("physics", "mathematics", "systems", "statistics"))
    difficulty: Difficulty = (
        "trivial"
        if deterministic
        else "frontier"
        if "frontier" in text
        else "low"
        if simple and not hard
        else "high"
        if hard
        else "medium"
    )
    ambiguity: Level = (
        "high"
        if re.search(r"\b(best|strongest|genuine|novel|research|unclear)\b", text)
        else "low"
        if simple or deterministic
        else "medium"
    )
    consequence: Level = (
        "high"
        if re.search(r"\b(safety|payment|medical|security|catastrophic|production outage)\b", text)
        else "medium"
        if hard
        else "low"
    )
    verification: Verification = (
        "weak"
        if "statistics" in tags or "research" in text
        else "strong"
        if has_tests
        else "partial"
    )
    return TaskProfile(
        domain_tags=tags,
        difficulty=difficulty,
        ambiguity=ambiguity,
        consequence_of_failure=consequence,
        verification_strength=verification,
        latency_sensitivity="critical"
        if remaining_seconds < 180 or "minutes left" in text
        else "high"
        if mode == "hackathon"
        else "medium",
        context_size="small"
        if context_chars < 20000
        else "medium"
        if context_chars < 80000
        else "large",
        reasoning_types=[
            {
                "software": "implementation",
                "physics": "physical",
                "mathematics": "mathematical",
                "statistics": "statistical",
                "systems": "architectural",
                "security": "adversarial",
            }.get(tag, tag)
            for tag in tags
        ],
        parallel_value="high" if hard or mode == "hackathon" else "low",
        explanation=[
            f"Matched domains: {', '.join(tags)}",
            f"Difficulty {difficulty}: explicit task keywords; not a learned estimate",
            f"Verification {verification}: {'test command available' if has_tests else 'no verified test command yet'}; inference claims remain weakly verified",
        ],
        deterministic_action=deterministic,
    )


def select_specialists(profile: TaskProfile, mode: Mode, *, maximum: int = 4) -> list[Specialist]:
    if not 1 <= maximum <= 4:
        raise ValueError("specialist maximum must be 1–4")
    if profile.deterministic_action or (
        mode == "economy"
        and profile.difficulty in {"trivial", "low"}
        and profile.verification_strength == "strong"
    ):
        return []
    priority = ["Software Engineer"]
    if mode == "hackathon":
        priority.append("Hackathon Strategist / Judge")
    priority += [
        role
        for role, (tag, _, _) in LENSES.items()
        if tag in profile.domain_tags and role not in priority
    ]
    if mode == "hackathon":
        maximum = min(
            maximum,
            2
            if profile.difficulty in {"trivial", "low"}
            else 4
            if profile.difficulty in {"high", "frontier"}
            else 3,
        )
        domain_roles = [
            role
            for role in priority
            if LENSES[role][0]
            in {"physics", "mathematics", "statistics", "data", "systems", "security"}
        ]
        priority = domain_roles + [role for role in priority if role not in domain_roles]
    if len(priority) < 2:
        priority.append("Product Engineer")
    return [
        Specialist(role=role, jurisdiction=LENSES[role][1], question=LENSES[role][2])
        for role in priority[:maximum]
    ]


class ModelProfile(Record):
    provider: Literal["claude", "codex"]
    model: str
    tier: int = Field(ge=1, le=4)
    capability_tags: list[str] = Field(default_factory=lambda: ["implementation", "reasoning"])
    quality_class: int = Field(ge=1, le=4)
    speed_class: int = Field(
        ge=1, le=3
    )  # 3 is fastest: configured priors, not latency measurements.
    cost_class: Literal["very_low", "low", "medium", "high", "premium"]
    context_class: Literal["small", "medium", "large"] = "large"
    reasoning_strength: int = Field(ge=1, le=4)
    coding_strength: int = Field(ge=1, le=4)
    maths_strength: int = Field(ge=1, le=4)
    statistical_strength: int = Field(ge=1, le=4)
    tool_strength: int = Field(default=2, ge=1, le=4)
    reliability_prior: float = Field(default=0.85, ge=0, le=1)
    enabled: bool = True


def model_registry() -> list[ModelProfile]:
    # These are relative policy assumptions. Availability is subject to local CLI/account access.
    rows: list[tuple[Literal["claude", "codex"], str, int, int, Cost]] = [
        ("claude", "haiku", 1, 3, "low"),
        ("claude", "sonnet", 2, 2, "medium"),
        ("claude", "opus", 3, 1, "high"),
        ("codex", "gpt-5.6-luna", 1, 3, "low"),
        ("codex", "gpt-5.6-terra", 2, 2, "medium"),
        ("codex", "gpt-5.6-sol", 3, 2, "high"),
        ("codex", "gpt-6-astra", 4, 1, "premium"),
    ]
    return [
        ModelProfile(
            provider=provider,
            model=model,
            tier=tier,
            quality_class=tier,
            speed_class=speed,
            cost_class=cost,
            reasoning_strength=tier,
            coding_strength=tier,
            maths_strength=tier,
            statistical_strength=tier,
        )
        for provider, model, tier, speed, cost in rows
    ]


class RoutingDecision(Record):
    task_or_phase: str
    specialist_role: str
    task_profile: TaskProfile
    selected_provider: str
    selected_model: str
    selected_tier: int | None
    relative_cost_class: str
    mode: Mode
    rationale: str
    alternatives_considered: list[str]
    escalation_allowed: bool
    expected_verification: str
    escalation_from: str | None = None
    escalation_trigger: str | None = None


def hackathon_required_tier(profile: TaskProfile, phase: str, role: str) -> int:
    """Per-call sufficiency policy; ordinal priors, not benchmark measurements."""
    phase, role = phase.upper(), role.lower()
    check = any(label in phase for label in ("INSPECT", "CHECK", "QA", "RED TEAM"))
    if (
        profile.verification_strength == "strong"
        and profile.consequence_of_failure != "high"
        and (check or profile.difficulty in {"trivial", "low"})
    ):
        return 1
    domain_reasoning = (
        ("mathematics" in profile.domain_tags and "mathematic" in role)
        or ("physics" in profile.domain_tags and "physic" in role)
        or ("systems" in profile.domain_tags and ("system" in role or "architect" in role))
    )
    critical_decision = "DECIDE" in phase and profile.consequence_of_failure == "high"
    if (domain_reasoning or critical_decision) and (
        profile.difficulty == "frontier"
        or (profile.difficulty == "high" and profile.ambiguity == "high")
    ):
        return 4
    return 3  # Normal specialist reasoning and meaningful builds require strong capability.


class Router:
    def __init__(
        self,
        mode: Mode,
        registry: list[ModelProfile] | None = None,
        overrides: dict[str, str] | None = None,
    ):
        self.mode = mode
        self.registry = model_registry() if registry is None else registry
        self.overrides = overrides or {}

    def choose(
        self,
        profile: TaskProfile,
        phase: str,
        role: str,
        *,
        preferred: str | None = None,
        pinned_provider: str | None = None,
        previous: RoutingDecision | None = None,
        trigger: str | None = None,
        model_failure: bool = False,
    ) -> RoutingDecision:
        required = (
            4
            if profile.difficulty == "frontier"
            else 3
            if profile.difficulty == "high" or profile.consequence_of_failure == "high"
            else 1
            if profile.difficulty in {"trivial", "low"}
            and profile.verification_strength == "strong"
            else 2
        )
        if self.mode == "hackathon":
            required = hackathon_required_tier(profile, phase, role)
        candidates = [
            m
            for m in self.registry
            if m.enabled and (not pinned_provider or m.provider == pinned_provider)
        ]
        if previous:
            if (
                self.mode == "hackathon"
                and not model_failure
                and (
                    not trigger
                    or not re.search(
                        r"executable|test.*fail|critical decision|difficulty", trigger.lower()
                    )
                    or previous.escalation_from is not None
                )
            ):
                raise Blocked("Hackathon escalation requires evidence and permits only one step")
            if not previous.escalation_allowed or previous.selected_tier is None:
                raise Blocked("This route cannot escalate")
            levels = [m.tier for m in candidates if m.tier > previous.selected_tier]
            if not levels:
                raise Blocked("No higher configured tier; escalation stops")
            required = min(levels)  # Exactly one configured level, never a jump or a cycle.
            candidates = [m for m in candidates if m.tier == required]
        else:
            candidates = [m for m in candidates if m.tier >= required]
        if not candidates:
            raise Blocked(f"No enabled model meets required tier {required}")
        weight = WEIGHTS[self.mode]

        def score(model: ModelProfile) -> float:
            strength = (
                model.maths_strength
                if "mathematical" in profile.reasoning_types
                else model.statistical_strength
                if "statistical" in profile.reasoning_types
                else model.coding_strength
            )
            cost = {"very_low": 0, "low": 1, "medium": 2, "high": 3, "premium": 4}[model.cost_class]
            latency = weight["latency"] * (2 if profile.latency_sensitivity == "critical" else 1)
            return (
                weight["quality"] * (model.quality_class + strength) / 2
                + weight["reliability"] * model.reliability_prior
                + latency * model.speed_class
                - weight["cost"] * cost
                + (0.5 if model.provider == preferred else 0)
            )

        # Do not buy intelligence above sufficiency for trivial/low-risk labour.
        if self.mode != "hackathon" and not previous and profile.difficulty in {"trivial", "low"}:
            candidates = [m for m in candidates if m.tier == min(x.tier for x in candidates)]
        elif not previous and self.mode == "engineering" and profile.ambiguity != "high":
            candidates = [m for m in candidates if m.tier == min(x.tier for x in candidates)]
        if self.mode == "hackathon":
            # Capability first, then fastest reliable sufficient model. No cost/diversity term.
            candidates = [
                m
                for m in candidates
                if min(m.quality_class, m.reasoning_strength, m.coding_strength) >= required
                and (
                    not ("mathematic" in role.lower() or "physic" in role.lower())
                    or m.maths_strength >= required
                )
                and (
                    not ("statistic" in role.lower() or "data scientist" in role.lower())
                    or m.statistical_strength >= required
                )
            ]
            if not candidates:
                raise Blocked(f"No enabled model meets role capability floor {required}")
            selected = max(
                candidates,
                key=lambda m: (m.speed_class, m.reliability_prior, m.quality_class),
            )
        else:
            selected = max(candidates, key=score)
        manual_model = self.overrides.get(selected.provider)
        if manual_model and previous:
            raise Blocked("Explicit model selection disables automatic escalation")
        return RoutingDecision(
            task_or_phase=phase,
            specialist_role=role,
            task_profile=profile,
            selected_provider=selected.provider,
            selected_model=manual_model or selected.model,
            selected_tier=None if manual_model else selected.tier,
            relative_cost_class="unknown" if manual_model else selected.cost_class,
            mode=self.mode,
            rationale=(f"Manual model override {manual_model}. " if manual_model else "")
            + (
                f"Required tier {required} for {role}/{phase}; eligible models ranked by speed, "
                "reliability, then quality; monetary cost weight exactly zero; no diversity bonus. "
                if self.mode == "hackathon"
                else f"Required tier {required}; weights {weight}; highest configured score {score(selected):.2f}. "
            )
            + (
                f"Provider pinned to {pinned_provider}. "
                if pinned_provider
                else ""
                if self.mode == "hackathon"
                else f"Soft diversity preference {preferred}; never required. "
            )
            + "Capabilities, speed and cost are ordinal priors, not measured success probabilities or prices.",
            alternatives_considered=[
                (
                    f"{m.provider}/{m.model}: speed={m.speed_class}, reliability={m.reliability_prior}"
                    if self.mode == "hackathon"
                    else f"{m.provider}/{m.model}: {score(m):.2f}"
                )
                for m in candidates
                if m != selected
            ],
            escalation_allowed=not manual_model
            and any(
                m.enabled
                and m.tier > selected.tier
                and (not pinned_provider or m.provider == pinned_provider)
                for m in self.registry
            ),
            expected_verification=profile.verification_strength,
            escalation_from=f"{previous.selected_provider}/{previous.selected_model}"
            if previous
            else None,
            escalation_trigger=trigger,
        )
