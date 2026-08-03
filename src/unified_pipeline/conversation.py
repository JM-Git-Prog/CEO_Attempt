"""Conversation Engine — Ollama-backed conversational agent for Brief generation.

Transforms natural-language conversation into a structured Brief by:
1. Generating an inviting opening prompt
2. Interpreting user responses
3. Proposing art direction, GAME concepts, REAL capabilities
4. Running a steering loop until user intent stabilizes
5. Extracting a validated Brief with provenance

Requirements: 1.1, 1.2, 1.3, 1.4, 1.7, 1.8, 2.1, 2.2, 2.3
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from src.orchestrator.llm import generate_json, LLMError
from src.unified_pipeline.models import (
    Atmosphere,
    Brief,
    Era,
    GameConcept,
    ManifestObject,
    Palette,
    RealCapability,
)


# ─── Constants ─────────────────────────────────────────────────────────────────

CONVERSATION_DEADLINE_SECONDS = 30.0
MAX_STEERING_TURNS = 10

# ─── Confirmation detection ────────────────────────────────────────────────────

_CONFIRM_PHRASES = (
    "lock it in", "build it", "go with it", "let's do it",
    "let's go", "perfect", "approved", "looks good", "sounds good",
    "sounds great", "that's great", "love it", "ship it",
    "yes please", "go ahead", "proceed", "start building", "begin building",
    "confirmed", "i'm happy", "all good", "nail it",
)


def _user_confirms_stable(message: str) -> bool:
    """Detect explicit user confirmation that steering is done.

    The LLM sometimes fails to set steering_stable=true even when the user
    clearly signals approval. This heuristic catches common confirmation
    patterns to prevent the UI from stalling.
    """
    lower = message.lower().strip()
    # Short affirmative messages (< 30 chars) starting with "yes" are confirmations
    if lower.startswith("yes") and len(lower) < 30:
        return True
    return any(phrase in lower for phrase in _CONFIRM_PHRASES)


# ─── System prompts ────────────────────────────────────────────────────────────

OPENING_SYSTEM = """\
You are a creative interior-design AI that leads conversations about room creation.
You propose ideas — you never ask the user to fill in blanks.

Your job: greet the user warmly, ask what kind of space they'd like to build,
and immediately propose an art direction (era, mood, palette, key objects, spatial character).
Be vivid and specific. Suggest 4-6 key objects that would make the room feel alive.

Respond in JSON with these fields:
{
  "greeting": "your warm opening message proposing a direction",
  "proposed_era": "a specific era/style like '1950s diner' or 'modern minimalist'",
  "proposed_mood": "atmospheric description",
  "proposed_palette": "2-3 colors and material finishes",
  "proposed_objects": ["list", "of", "4-6", "key", "objects"]
}
"""

INTERPRET_SYSTEM = """\
You are a creative interior-design AI interpreting user feedback about a room design.
The user has responded to your proposal. Extract their intent and propose refinements.

You MUST propose (not just acknowledge):
- Updated art direction if they redirected style
- GAME concept (theme, mechanics, scoring, win_condition) tailored to the space
- REAL capabilities (which tools could wire to which surfaces)
- Any objects they want added or removed

Respond in JSON:
{
  "interpretation": "your understanding of what they want changed or confirmed",
  "room_purpose": "primary purpose of the space",
  "atmosphere": {
    "mood": "updated mood description",
    "lighting_direction": "warm/cool/mixed direction",
    "time_of_day": "morning/afternoon/evening/night"
  },
  "era": {
    "period": "specific era/style",
    "style_exclusions": ["things that don't belong in this era"]
  },
  "palette": {
    "primary": "main color",
    "accent": "accent color",
    "material_finishes": ["finish1", "finish2"]
  },
  "objects": [
    {"name": "object name", "role": "functional role", "count": 1, "material_hint": "material", "is_architectural": false}
  ],
  "game_concept": {
    "theme": "game theme fitting the room",
    "mechanics": "how it plays",
    "scoring": "how points are earned",
    "win_condition": "how to win"
  },
  "real_capabilities": [
    {"tool_type": "tool category", "surface_binding": "which surface", "read_only_v1": true}
  ],
  "steering_stable": false,
  "response_to_user": "your creative response proposing the next refinement"
}

Set steering_stable=true ONLY when the user has clearly confirmed or expressed satisfaction.
Always propose — never just ask questions.
"""

BRIEF_EXTRACTION_SYSTEM = """\
You are extracting a final structured Brief from a completed conversation.
The conversation has stabilized. Produce the definitive structured Brief.

Return ONLY valid JSON matching this exact schema:
{
  "room_purpose": "string — primary purpose",
  "atmosphere": {
    "mood": "string",
    "lighting_direction": "string",
    "time_of_day": "string"
  },
  "era": {
    "period": "string",
    "style_exclusions": ["string"]
  },
  "palette": {
    "primary": "string",
    "accent": "string",
    "material_finishes": ["string"]
  },
  "object_manifest": [
    {"name": "string", "role": "string", "count": 1, "material_hint": "string", "is_architectural": false}
  ],
  "game_concept": {
    "theme": "string",
    "mechanics": "string",
    "scoring": "string",
    "win_condition": "string"
  },
  "real_capabilities": [
    {"tool_type": "string", "surface_binding": "string", "read_only_v1": true}
  ],
  "success_criteria": "string — user's stated done-check or inferred quality bar"
}

Every field is required. Use sensible defaults if conversation did not specify a field.
"""


# ─── Data structures ───────────────────────────────────────────────────────────


@dataclass
class ConversationTurn:
    """One exchange in the conversation history."""

    role: str  # "system", "assistant", "user"
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConversationState:
    """Mutable state tracking conversation progress."""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    turns: list[ConversationTurn] = field(default_factory=list)
    proposed_brief: dict[str, Any] = field(default_factory=dict)
    steering_stable: bool = False
    turn_count: int = 0
    started_at: float = field(default_factory=time.time)


# ─── Default Brief (fallback on timeout) ───────────────────────────────────────


def _default_brief() -> Brief:
    """Schema-correct fallback Brief when conversation times out or LLM fails."""
    return Brief(
        room_purpose="cozy living space",
        atmosphere=Atmosphere(
            mood="warm and inviting",
            lighting_direction="warm ambient",
            time_of_day="evening",
        ),
        era=Era(
            period="contemporary",
            style_exclusions=(),
        ),
        palette=Palette(
            primary="warm white",
            accent="natural wood",
            material_finishes=("matte paint", "natural wood grain"),
        ),
        object_manifest=(
            ManifestObject(name="sofa", role="seating", count=1, material_hint="fabric"),
            ManifestObject(name="coffee table", role="surface", count=1, material_hint="wood"),
            ManifestObject(name="floor lamp", role="lighting", count=1, material_hint="metal"),
            ManifestObject(name="bookshelf", role="storage", count=1, material_hint="wood"),
        ),
        game_concept=GameConcept(
            theme="discovery",
            mechanics="find hidden items",
            scoring="items found",
            win_condition="all items discovered",
        ),
        real_capabilities=(
            RealCapability(
                tool_type="reading",
                surface_binding="bookshelf",
                read_only_v1=True,
            ),
        ),
        success_criteria="A cozy, walkable room that feels like home.",
        provenance={"source": "default_fallback"},
    )


# ─── ConversationEngine ───────────────────────────────────────────────────────


class ConversationEngine:
    """Ollama-backed conversational agent that produces a structured Brief.

    The engine leads the conversation — it proposes art direction, GAME concepts,
    and REAL capabilities rather than waiting for the user to specify everything.
    Includes a 30-second total deadline with schema-correct fallback.
    """

    def __init__(self, model: Optional[str] = None, deadline: float = CONVERSATION_DEADLINE_SECONDS):
        self._model = model
        self._deadline = deadline
        self._state = ConversationState()

    @property
    def state(self) -> ConversationState:
        return self._state

    @property
    def is_stable(self) -> bool:
        return self._state.steering_stable

    def reset(self) -> None:
        """Start a fresh conversation."""
        self._state = ConversationState()

    # ─── Opening ───────────────────────────────────────────────────────────

    async def generate_opening(self) -> str:
        """Generate the opening conversational prompt.

        Requirement 1.1: present a conversational prompt, never a form.
        Returns the AI's opening greeting and proposal.

        Includes a session-unique seed in the system prompt to invalidate
        any cached Ollama KV context from prior sessions (prevents persona bleed).
        """
        # Fix #1: Prepend a session-unique seed to bust Ollama KV cache
        session_seed = f"[session:{self._state.session_id}:{time.time()}]\n"
        system_prompt = session_seed + OPENING_SYSTEM

        try:
            result = await generate_json(
                system=system_prompt,
                user="Generate an opening greeting for a new room design session. Be warm, creative, and immediately propose a direction.",
                model=self._model,
                timeout_seconds=self._deadline,
            )
            greeting = result.get("greeting", "")
            # Store the opening proposal in state for later reference
            self._state.proposed_brief = {
                "proposed_era": result.get("proposed_era", ""),
                "proposed_mood": result.get("proposed_mood", ""),
                "proposed_palette": result.get("proposed_palette", ""),
                "proposed_objects": result.get("proposed_objects", []),
            }
            self._state.turns.append(ConversationTurn(role="assistant", content=greeting))
            return greeting
        except (LLMError, TimeoutError):
            fallback = (
                "Welcome! Let's design a space together. I'm imagining a warm, "
                "cozy room — maybe something with natural wood, soft lighting, "
                "and a lived-in feel. What kind of space are you thinking of?"
            )
            self._state.turns.append(ConversationTurn(role="assistant", content=fallback))
            return fallback

    # ─── User Response Interpretation ──────────────────────────────────────

    async def interpret_response(self, user_message: str) -> str:
        """Interpret a user response, propose refinements, detect stability.

        Requirements 1.2, 1.3, 1.4, 1.7: interpret, propose GAME/REAL, steer.
        Returns the AI's response to the user.

        Fix #2: After getting LLM response, checks for byte-for-byte duplicate
        of the last assistant turn. Retries once with temperature bump if duplicate.
        Fix #4: User's current message is appended to turns BEFORE building context,
        ensuring it appears as the LAST item in the messages array sent to Ollama.
        """
        # Fix #4: Append user message to turns BEFORE building context
        # so it's the last item in the conversation context sent to the LLM
        self._state.turns.append(ConversationTurn(role="user", content=user_message))
        self._state.turn_count += 1

        # Build conversation context for the LLM (now includes latest user message)
        conversation_context = self._build_conversation_context()

        try:
            result = await generate_json(
                system=INTERPRET_SYSTEM,
                user=conversation_context,
                model=self._model,
                timeout_seconds=self._deadline,
            )

            # Update proposed brief with latest interpretation
            self._update_proposed_brief(result)

            # Check if steering has stabilized — LLM flag OR explicit user confirmation
            llm_says_stable = bool(result.get("steering_stable", False))
            user_confirmed = _user_confirms_stable(user_message)
            self._state.steering_stable = llm_says_stable or user_confirmed

            # Get the response to send back to the user
            response = result.get("response_to_user", "")
            if not response:
                response = result.get("interpretation", "I understand. Let me refine the design.")

            # Fix #2: Response deduplication — detect echo mode
            last_assistant_content = self._last_assistant_content()
            if response == last_assistant_content:
                # Retry once with temperature bump hint
                retry_context = conversation_context + " Please provide a fresh, different suggestion."
                try:
                    retry_result = await generate_json(
                        system=INTERPRET_SYSTEM,
                        user=retry_context,
                        model=self._model,
                        timeout_seconds=self._deadline,
                    )
                    retry_response = retry_result.get("response_to_user", "")
                    if not retry_response:
                        retry_response = retry_result.get("interpretation", "")
                    if retry_response and retry_response != last_assistant_content:
                        # Retry succeeded with different content
                        self._update_proposed_brief(retry_result)
                        response = retry_response
                    else:
                        # Still duplicate after retry — acknowledge user input
                        response = f"(Rethinking...) Based on your message \"{user_message[:60]}\", let me take a different angle on the design."
                except (LLMError, TimeoutError):
                    response = f"(Rethinking...) I hear you — \"{user_message[:60]}\". Let me refine the direction."

            self._state.turns.append(ConversationTurn(role="assistant", content=response))
            return response

        except (LLMError, TimeoutError):
            # On failure, mark stable to proceed with what we have
            self._state.steering_stable = True
            fallback_response = (
                "I think I have a good picture of what you're looking for. "
                "Let me put together the design brief based on our conversation."
            )
            self._state.turns.append(ConversationTurn(role="assistant", content=fallback_response))
            return fallback_response

    def _last_assistant_content(self) -> str:
        """Return the content of the most recent assistant turn, or empty string."""
        for turn in reversed(self._state.turns):
            if turn.role == "assistant":
                return turn.content
        return ""

    # ─── Art Direction Proposal ────────────────────────────────────────────

    async def propose_art_direction(self, user_context: str) -> dict[str, Any]:
        """Generate an art direction proposal based on conversation so far.

        Requirement 1.2: propose era, mood, palette, key objects, spatial character.
        """
        prompt = (
            f"Based on this user description: \"{user_context}\"\n"
            f"And our conversation so far, propose a complete art direction.\n"
            f"Current state: {json.dumps(self._state.proposed_brief, indent=2)}"
        )

        try:
            result = await generate_json(
                system=INTERPRET_SYSTEM,
                user=prompt,
                model=self._model,
                timeout_seconds=self._deadline,
            )
            return {
                "era": result.get("era", {}),
                "atmosphere": result.get("atmosphere", {}),
                "palette": result.get("palette", {}),
                "objects": result.get("objects", []),
            }
        except (LLMError, TimeoutError):
            return {
                "era": {"period": "contemporary", "style_exclusions": []},
                "atmosphere": {"mood": "warm and inviting", "lighting_direction": "warm ambient", "time_of_day": "evening"},
                "palette": {"primary": "warm white", "accent": "natural wood", "material_finishes": ["matte", "wood grain"]},
                "objects": [],
            }

    # ─── GAME Concept Proposal ─────────────────────────────────────────────

    async def propose_game_concept(self) -> dict[str, Any]:
        """Generate a GAME concept proposal tailored to the room.

        Requirement 1.3: propose GAME concept within the first three exchanges.
        """
        room_context = json.dumps(self._state.proposed_brief, indent=2)
        prompt = (
            f"Based on this room design:\n{room_context}\n\n"
            f"Propose a GAME concept. What game could be played in this space "
            f"using the objects present? Be creative and specific."
        )

        try:
            result = await generate_json(
                system=INTERPRET_SYSTEM,
                user=prompt,
                model=self._model,
                timeout_seconds=self._deadline,
            )
            return result.get("game_concept", {
                "theme": "exploration",
                "mechanics": "discover hidden details",
                "scoring": "details found",
                "win_condition": "all secrets revealed",
            })
        except (LLMError, TimeoutError):
            return {
                "theme": "exploration",
                "mechanics": "discover hidden details",
                "scoring": "details found",
                "win_condition": "all secrets revealed",
            }

    # ─── REAL Capability Proposal ──────────────────────────────────────────

    async def propose_real_capabilities(self) -> list[dict[str, Any]]:
        """Generate REAL capability proposals for the room's surfaces.

        Requirement 1.4: propose potential REAL capabilities within first three exchanges.
        """
        room_context = json.dumps(self._state.proposed_brief, indent=2)
        prompt = (
            f"Based on this room design:\n{room_context}\n\n"
            f"Propose REAL capabilities — which real-world tools could display "
            f"data on which surfaces? E.g., a desk could show inbox, a screen "
            f"could show code output. All read-only for v1."
        )

        try:
            result = await generate_json(
                system=INTERPRET_SYSTEM,
                user=prompt,
                model=self._model,
                timeout_seconds=self._deadline,
            )
            caps = result.get("real_capabilities", [])
            if isinstance(caps, list):
                return caps
            return []
        except (LLMError, TimeoutError):
            return [{"tool_type": "display", "surface_binding": "screen", "read_only_v1": True}]

    # ─── Steering Loop ─────────────────────────────────────────────────────

    async def run_steering_loop(self, get_user_input) -> Brief:
        """Run the full steering loop until stable, then extract Brief.

        Requirement 1.7, 1.8: user steers until stable, then produce Brief.

        Args:
            get_user_input: async callable that returns the user's next message,
                           or None to signal that the user is done.

        Returns:
            A validated Brief instance.
        """
        deadline = time.time() + self._deadline

        # Generate opening if we haven't yet
        if not self._state.turns:
            await self.generate_opening()

        # Steering loop — continue until stable or deadline/max turns
        while (
            not self._state.steering_stable
            and self._state.turn_count < MAX_STEERING_TURNS
            and time.time() < deadline
        ):
            user_message = await get_user_input()
            if user_message is None:
                # User signaled done
                self._state.steering_stable = True
                break

            await self.interpret_response(user_message)

        # Extract Brief from conversation
        return await self.extract_brief()

    # ─── Brief Extraction ──────────────────────────────────────────────────

    async def extract_brief(self) -> Brief:
        """Extract a structured Brief from the conversation.

        Requirement 1.8, 2.1, 2.2, 2.3: produce structured Brief with
        all required fields, stable UUIDs, and provenance.

        Includes 30-second deadline with schema-correct fallback.
        """
        conversation_summary = self._build_full_summary()

        try:
            result = await generate_json(
                system=BRIEF_EXTRACTION_SYSTEM,
                user=conversation_summary,
                model=self._model,
                timeout_seconds=self._deadline,
            )
            return self._dict_to_brief(result)
        except (LLMError, TimeoutError):
            # Fallback: try to build Brief from accumulated state
            return self._brief_from_state()

    # ─── Private helpers ───────────────────────────────────────────────────

    def _build_conversation_context(self) -> str:
        """Build a context string from recent conversation history."""
        recent = self._state.turns[-6:]  # Last 6 turns for context window
        parts = []
        for turn in recent:
            parts.append(f"[{turn.role}]: {turn.content}")
        current_state = json.dumps(self._state.proposed_brief, indent=2)
        return (
            f"Conversation so far:\n"
            + "\n".join(parts)
            + f"\n\nCurrent proposed design state:\n{current_state}\n\n"
            f"Turn {self._state.turn_count} of {MAX_STEERING_TURNS}. "
            f"Interpret the latest user message and propose refinements."
        )

    def _build_full_summary(self) -> str:
        """Build a full conversation summary for Brief extraction."""
        parts = []
        for turn in self._state.turns:
            parts.append(f"[{turn.role}]: {turn.content}")
        current_state = json.dumps(self._state.proposed_brief, indent=2)
        return (
            f"Full conversation:\n"
            + "\n".join(parts)
            + f"\n\nAccumulated design state:\n{current_state}\n\n"
            f"Extract the final Brief from this conversation. "
            f"Include all fields with sensible defaults for anything unspecified."
        )

    def _update_proposed_brief(self, result: dict[str, Any]) -> None:
        """Merge LLM interpretation into the running proposed brief."""
        for key in ("room_purpose", "interpretation"):
            if key in result and result[key]:
                self._state.proposed_brief[key] = result[key]

        for key in ("atmosphere", "era", "palette", "game_concept"):
            if key in result and isinstance(result[key], dict):
                self._state.proposed_brief[key] = result[key]

        if "objects" in result and isinstance(result["objects"], list):
            self._state.proposed_brief["objects"] = result["objects"]

        if "real_capabilities" in result and isinstance(result["real_capabilities"], list):
            self._state.proposed_brief["real_capabilities"] = result["real_capabilities"]

    def _dict_to_brief(self, data: dict[str, Any]) -> Brief:
        """Convert LLM output dict to a Brief model instance.

        Requirement 2.2: each object gets a stable UUID.
        Requirement 2.3: record provenance.
        """
        # Parse atmosphere
        atmo_data = data.get("atmosphere", {})
        atmosphere = Atmosphere(
            mood=atmo_data.get("mood", ""),
            lighting_direction=atmo_data.get("lighting_direction", ""),
            time_of_day=atmo_data.get("time_of_day", ""),
        )

        # Parse era
        era_data = data.get("era", {})
        era = Era(
            period=era_data.get("period", ""),
            style_exclusions=tuple(era_data.get("style_exclusions", ())),
        )

        # Parse palette
        pal_data = data.get("palette", {})
        palette = Palette(
            primary=pal_data.get("primary", ""),
            accent=pal_data.get("accent", ""),
            material_finishes=tuple(pal_data.get("material_finishes", ())),
        )

        # Parse object manifest — each gets a stable UUID (Req 2.2)
        objects_raw = data.get("object_manifest", [])
        manifest = tuple(
            ManifestObject(
                id=str(uuid.uuid4()),
                name=obj.get("name", ""),
                role=obj.get("role", ""),
                count=obj.get("count", 1),
                material_hint=obj.get("material_hint", ""),
                is_architectural=obj.get("is_architectural", False),
            )
            for obj in objects_raw
            if isinstance(obj, dict)
        )

        # Parse game concept
        gc_data = data.get("game_concept", {})
        game_concept = GameConcept(
            theme=gc_data.get("theme", ""),
            mechanics=gc_data.get("mechanics", ""),
            scoring=gc_data.get("scoring", ""),
            win_condition=gc_data.get("win_condition", ""),
        )

        # Parse REAL capabilities
        rc_raw = data.get("real_capabilities", [])
        real_capabilities = tuple(
            RealCapability(
                tool_type=rc.get("tool_type", ""),
                surface_binding=rc.get("surface_binding", ""),
                read_only_v1=rc.get("read_only_v1", True),
            )
            for rc in rc_raw
            if isinstance(rc, dict)
        )

        # Build provenance (Req 2.3)
        provenance = {
            "session_id": self._state.session_id,
            "turn_count": str(self._state.turn_count),
            "extraction_method": "llm",
        }

        return Brief(
            room_purpose=data.get("room_purpose", ""),
            atmosphere=atmosphere,
            era=era,
            palette=palette,
            object_manifest=manifest,
            game_concept=game_concept,
            real_capabilities=real_capabilities,
            success_criteria=data.get("success_criteria", ""),
            provenance=provenance,
        )

    def _brief_from_state(self) -> Brief:
        """Build a Brief from accumulated conversation state (fallback).

        Used when LLM extraction fails — constructs from partial data gathered
        during the steering loop, falling back to defaults for missing fields.
        """
        state = self._state.proposed_brief

        # Try to parse what we've accumulated
        atmo_data = state.get("atmosphere", {})
        if isinstance(atmo_data, dict):
            atmosphere = Atmosphere(
                mood=atmo_data.get("mood", "warm and inviting"),
                lighting_direction=atmo_data.get("lighting_direction", "warm ambient"),
                time_of_day=atmo_data.get("time_of_day", "evening"),
            )
        else:
            atmosphere = Atmosphere(mood="warm and inviting", lighting_direction="warm ambient", time_of_day="evening")

        era_data = state.get("era", {})
        if isinstance(era_data, dict):
            era = Era(
                period=era_data.get("period", state.get("proposed_era", "contemporary")),
                style_exclusions=tuple(era_data.get("style_exclusions", ())),
            )
        else:
            era = Era(period="contemporary")

        pal_data = state.get("palette", {})
        if isinstance(pal_data, dict):
            palette = Palette(
                primary=pal_data.get("primary", ""),
                accent=pal_data.get("accent", ""),
                material_finishes=tuple(pal_data.get("material_finishes", ())),
            )
        else:
            palette = Palette()

        # Build objects from accumulated list
        objects_raw = state.get("objects", state.get("proposed_objects", []))
        manifest: list[ManifestObject] = []
        if isinstance(objects_raw, list):
            for obj in objects_raw:
                if isinstance(obj, dict):
                    manifest.append(ManifestObject(
                        id=str(uuid.uuid4()),
                        name=obj.get("name", ""),
                        role=obj.get("role", ""),
                        count=obj.get("count", 1),
                        material_hint=obj.get("material_hint", ""),
                        is_architectural=obj.get("is_architectural", False),
                    ))
                elif isinstance(obj, str):
                    manifest.append(ManifestObject(
                        id=str(uuid.uuid4()),
                        name=obj,
                        role="",
                        count=1,
                    ))

        gc_data = state.get("game_concept", {})
        if isinstance(gc_data, dict):
            game_concept = GameConcept(
                theme=gc_data.get("theme", "exploration"),
                mechanics=gc_data.get("mechanics", "discover hidden details"),
                scoring=gc_data.get("scoring", "details found"),
                win_condition=gc_data.get("win_condition", "all secrets revealed"),
            )
        else:
            game_concept = GameConcept(
                theme="exploration",
                mechanics="discover hidden details",
                scoring="details found",
                win_condition="all secrets revealed",
            )

        rc_raw = state.get("real_capabilities", [])
        real_capabilities: list[RealCapability] = []
        if isinstance(rc_raw, list):
            for rc in rc_raw:
                if isinstance(rc, dict):
                    real_capabilities.append(RealCapability(
                        tool_type=rc.get("tool_type", ""),
                        surface_binding=rc.get("surface_binding", ""),
                        read_only_v1=rc.get("read_only_v1", True),
                    ))

        provenance = {
            "session_id": self._state.session_id,
            "turn_count": str(self._state.turn_count),
            "extraction_method": "state_fallback",
        }

        # If we have nothing useful, return the full default
        if not manifest and not state.get("room_purpose"):
            return _default_brief()

        return Brief(
            room_purpose=state.get("room_purpose", state.get("interpretation", "")),
            atmosphere=atmosphere,
            era=era,
            palette=palette,
            object_manifest=tuple(manifest),
            game_concept=game_concept,
            real_capabilities=tuple(real_capabilities),
            success_criteria=state.get("success_criteria", "A space that matches the described vision."),
            provenance=provenance,
        )
