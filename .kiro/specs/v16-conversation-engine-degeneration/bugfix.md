# Bugfix Requirements Document

## Introduction

The V16 conversation engine (`ConversationEngine` in `src/unified_pipeline/conversation.py`) exhibits three degeneration defects that compound into a broken user experience: (1) a fresh session opens with persona/theme text inherited from a prior Ollama session's KV cache, (2) the engine falls into byte-for-byte echo mode after the third user turn, and (3) explicit user confirmations like "Yes, build it" fail to trigger brief extraction and pipeline launch. Together these defects make the V16 conversational flow unusable — the system ignores user intent, repeats itself, and never transitions to the build phase.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a new session calls `generate_opening()` and the Ollama model's KV cache contains residual context from a previous session (e.g. the "Whimsical Bohemia" theme) THEN the system returns an opening greeting that references personas, themes, or style directions the current user never mentioned

1.2 WHEN consecutive calls to `interpret_response()` build context from `self._state.turns[-6:]` and the Ollama model returns a deterministic response (temperature=0 or prompt-cache hit from identical context) THEN the system delivers a byte-for-byte duplicate of the previous assistant reply

1.3 WHEN the user sends a confirmation message matching known approval patterns (e.g. "Yes, build it", "Lock the brief", "Let's go") THEN the system continues generating conversational replies instead of transitioning to brief extraction and pipeline launch

1.4 WHEN the conversation context sent to Ollama omits the user's latest message from the explicit prompt payload (relying instead on Ollama's own context window retention) THEN the system produces responses that do not acknowledge or incorporate the user's most recent input

### Expected Behavior (Correct)

2.1 WHEN a new session calls `generate_opening()` THEN the system SHALL include a session-unique seed (UUID or timestamp) in the system prompt to invalidate any cached Ollama KV context, ensuring the opening greeting is free of personas or themes from prior sessions

2.2 WHEN `interpret_response()` receives a response from Ollama that is byte-for-byte identical to the most recent assistant turn in `self._state.turns` THEN the system SHALL retry the LLM call with increased temperature (or append a deduplication nudge to the prompt) and return a distinct response

2.3 WHEN the user sends a message that matches confirmation patterns (detected by `_user_confirms_stable()`) THEN the system SHALL set `steering_stable = True`, extract the brief, persist it to `artifacts/brief.json`, update session state to `brief_ready`, and launch the durable pipeline — all within the same message-handling cycle

2.4 WHEN building the conversation context for Ollama via `_build_conversation_context()` THEN the system SHALL explicitly include the user's latest message in the prompt payload sent to `generate_json()`, not relying on Ollama's internal context window to retain it

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the Ollama model produces a genuinely novel response on every turn (no duplication) THEN the system SHALL CONTINUE TO return that response without retry or modification

3.2 WHEN the user sends non-confirmation messages (questions, style redirections, object additions) THEN the system SHALL CONTINUE TO interpret them as conversational input and respond with design refinements without triggering brief extraction

3.3 WHEN `generate_opening()` fails with an LLMError or TimeoutError THEN the system SHALL CONTINUE TO return the existing hardcoded fallback greeting and proceed normally

3.4 WHEN `interpret_response()` fails with an LLMError or TimeoutError THEN the system SHALL CONTINUE TO mark steering as stable, return the existing fallback response, and allow brief extraction to proceed

3.5 WHEN the conversation has fewer than 6 turns THEN the system SHALL CONTINUE TO build context from all available turns (the `[-6:]` slice gracefully handles short histories)

3.6 WHEN the user's message is a short affirmative ("yes") that is fewer than 30 characters THEN the system SHALL CONTINUE TO recognize it as a confirmation via the existing `_user_confirms_stable()` heuristic

---

## Bug Condition (Formal)

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type ConversationInput  -- (session_state, user_message, ollama_response)
  OUTPUT: boolean

  // Condition A: Persona bleed — response contains themes/personas not present in user history
  LET persona_bleed := X.ollama_response contains text from external cached context
                       AND X.session_turns contain no mention of that text

  // Condition B: Echo mode — response duplicates previous assistant turn
  LET echo_mode := X.ollama_response = X.previous_assistant_response  -- byte-for-byte

  // Condition C: Confirmation deafness — user confirms but no state transition
  LET confirmation_deaf := _user_confirms_stable(X.user_message) = True
                           AND X.result_steering_stable = False

  RETURN persona_bleed OR echo_mode OR confirmation_deaf
END FUNCTION
```

### Fix Checking Property

```pascal
// Property: Fix Checking — all buggy inputs produce correct behavior after the fix
FOR ALL X WHERE isBugCondition(X) DO
  result ← ConversationEngine'(X)

  // If persona_bleed triggered: opening must not contain external cached themes
  IF X triggered persona_bleed THEN
    ASSERT result.opening contains NO text from other sessions' themes/personas

  // If echo_mode triggered: response must differ from previous
  IF X triggered echo_mode THEN
    ASSERT result.response ≠ X.previous_assistant_response

  // If confirmation_deaf triggered: must transition to stable + extract brief
  IF X triggered confirmation_deaf THEN
    ASSERT result.steering_stable = True
    AND result.brief IS extracted
    AND result.session_state = "brief_ready"
END FOR
```

### Preservation Checking Property

```pascal
// Property: Preservation — non-buggy inputs produce identical behavior before and after
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT ConversationEngine(X) = ConversationEngine'(X)
END FOR
```
