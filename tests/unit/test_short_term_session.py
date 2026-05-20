"""Unit tests for ``engine.memory.short_term.InMemorySessionStore``.

The store is the process-local conversation buffer used in P1 (Redis lands
in P2). These tests pin down the sliding-window semantics, the reset
behaviour, and the multi-chat isolation guarantee.
"""

from __future__ import annotations

import pytest

from engine.core.session import ConversationSession
from engine.core.types import Role, Turn
from engine.memory.short_term import InMemorySessionStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_turn(text: str = "hi") -> Turn:
    return Turn(role=Role.user, text=text)


def _asst_turn(text: str = "hello") -> Turn:
    return Turn(role=Role.assistant, text=text)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_default_max_turns_is_twelve() -> None:
    store = InMemorySessionStore()
    assert store.max_turns == 12


@pytest.mark.unit
def test_explicit_max_turns_honored() -> None:
    store = InMemorySessionStore(max_turns=4)
    assert store.max_turns == 4


@pytest.mark.unit
@pytest.mark.parametrize("bad", [0, -1, -100])
def test_max_turns_below_one_rejected(bad: int) -> None:
    with pytest.raises(ValueError):
        InMemorySessionStore(max_turns=bad)


# ---------------------------------------------------------------------------
# get_or_create
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_or_create_returns_new_session_for_new_chat() -> None:
    store = InMemorySessionStore()
    session = store.get_or_create("c1", "biz_a")

    assert isinstance(session, ConversationSession)
    assert session.chat_id == "c1"
    assert session.business_id == "biz_a"
    assert session.turns == []


@pytest.mark.unit
def test_get_or_create_is_idempotent() -> None:
    """Subsequent calls return the same live session object."""
    store = InMemorySessionStore()
    s1 = store.get_or_create("c1", "biz_a")
    s2 = store.get_or_create("c1", "biz_a")

    assert s1 is s2


@pytest.mark.unit
def test_get_or_create_does_not_reset_existing_state() -> None:
    store = InMemorySessionStore()
    store.get_or_create("c1", "biz_a")
    store.add_turn("c1", _user_turn("ايوا"))

    # Calling again should not wipe the turn we just added.
    session = store.get_or_create("c1", "biz_a")
    assert len(session.turns) == 1


# ---------------------------------------------------------------------------
# add_turn / recent_turns ordering
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_add_turn_without_session_raises() -> None:
    store = InMemorySessionStore()
    with pytest.raises(KeyError):
        store.add_turn("nonexistent", _user_turn())


@pytest.mark.unit
def test_add_turn_preserves_order() -> None:
    store = InMemorySessionStore()
    store.get_or_create("c1", "biz_a")

    expected_texts = ["one", "two", "three", "four"]
    for txt in expected_texts:
        store.add_turn("c1", _user_turn(txt))

    actual = [t.text for t in store.recent_turns("c1")]
    assert actual == expected_texts


@pytest.mark.unit
def test_recent_turns_empty_for_unknown_chat() -> None:
    store = InMemorySessionStore()
    assert store.recent_turns("never_seen") == []


@pytest.mark.unit
def test_recent_turns_default_returns_all() -> None:
    store = InMemorySessionStore(max_turns=20)
    store.get_or_create("c1", "biz_a")
    for i in range(5):
        store.add_turn("c1", _user_turn(f"t{i}"))

    assert len(store.recent_turns("c1")) == 5


@pytest.mark.unit
def test_recent_turns_with_n_returns_last_n() -> None:
    store = InMemorySessionStore(max_turns=20)
    store.get_or_create("c1", "biz_a")
    for i in range(10):
        store.add_turn("c1", _user_turn(f"t{i}"))

    last_three = store.recent_turns("c1", n=3)

    assert len(last_three) == 3
    assert [t.text for t in last_three] == ["t7", "t8", "t9"]


@pytest.mark.unit
def test_recent_turns_n_larger_than_history_returns_all() -> None:
    store = InMemorySessionStore(max_turns=20)
    store.get_or_create("c1", "biz_a")
    for i in range(3):
        store.add_turn("c1", _user_turn(f"t{i}"))

    assert len(store.recent_turns("c1", n=99)) == 3


@pytest.mark.unit
def test_recent_turns_zero_or_negative_returns_empty() -> None:
    store = InMemorySessionStore(max_turns=20)
    store.get_or_create("c1", "biz_a")
    for i in range(3):
        store.add_turn("c1", _user_turn(f"t{i}"))

    assert store.recent_turns("c1", n=0) == []


# ---------------------------------------------------------------------------
# Sliding window
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sliding_window_drops_oldest_first() -> None:
    """After max_turns + 3 turns added, only the latest max_turns remain."""
    store = InMemorySessionStore(max_turns=5)
    store.get_or_create("c1", "biz_a")
    for i in range(8):  # 5 + 3 = 8 turns; expect the first three to be dropped.
        store.add_turn("c1", _user_turn(f"t{i}"))

    retained = store.recent_turns("c1")
    assert len(retained) == 5
    assert [t.text for t in retained] == ["t3", "t4", "t5", "t6", "t7"]


@pytest.mark.unit
def test_sliding_window_max_one_keeps_only_latest() -> None:
    store = InMemorySessionStore(max_turns=1)
    store.get_or_create("c1", "biz_a")
    store.add_turn("c1", _user_turn("old"))
    store.add_turn("c1", _user_turn("new"))

    turns = store.recent_turns("c1")
    assert len(turns) == 1
    assert turns[0].text == "new"


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_reset_clears_only_target_chat() -> None:
    store = InMemorySessionStore()
    store.get_or_create("c1", "biz_a")
    store.get_or_create("c2", "biz_a")
    store.add_turn("c1", _user_turn("a"))
    store.add_turn("c2", _user_turn("b"))

    store.reset("c1")

    # c1 is gone; c2 still has its turn.
    assert store.recent_turns("c1") == []
    assert [t.text for t in store.recent_turns("c2")] == ["b"]


@pytest.mark.unit
def test_reset_unknown_chat_is_safe() -> None:
    store = InMemorySessionStore()
    # No KeyError, no exception — reset on an unknown chat is a no-op.
    store.reset("never_seen")


@pytest.mark.unit
def test_reset_then_get_or_create_yields_fresh_session() -> None:
    store = InMemorySessionStore()
    s1 = store.get_or_create("c1", "biz_a")
    store.add_turn("c1", _user_turn("a"))
    store.reset("c1")

    s2 = store.get_or_create("c1", "biz_a")
    assert s2 is not s1
    assert s2.turns == []


# ---------------------------------------------------------------------------
# all_chat_ids
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_all_chat_ids_empty_initially() -> None:
    store = InMemorySessionStore()
    assert store.all_chat_ids() == []


@pytest.mark.unit
def test_all_chat_ids_lists_known_chats() -> None:
    store = InMemorySessionStore()
    store.get_or_create("c1", "biz_a")
    store.get_or_create("c2", "biz_a")
    store.get_or_create("c3", "biz_b")

    assert set(store.all_chat_ids()) == {"c1", "c2", "c3"}


@pytest.mark.unit
def test_all_chat_ids_excludes_reset_chats() -> None:
    store = InMemorySessionStore()
    store.get_or_create("c1", "biz_a")
    store.get_or_create("c2", "biz_a")
    store.reset("c1")

    assert store.all_chat_ids() == ["c2"]


# ---------------------------------------------------------------------------
# Multi-chat isolation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_add_turn_isolation_between_chats() -> None:
    store = InMemorySessionStore()
    store.get_or_create("c1", "biz_a")
    store.get_or_create("c2", "biz_a")

    store.add_turn("c1", _user_turn("only-in-c1"))
    store.add_turn("c2", _asst_turn("only-in-c2"))

    c1 = store.recent_turns("c1")
    c2 = store.recent_turns("c2")
    assert [t.text for t in c1] == ["only-in-c1"]
    assert [t.text for t in c2] == ["only-in-c2"]


@pytest.mark.unit
def test_len_counts_live_sessions() -> None:
    store = InMemorySessionStore()
    assert len(store) == 0
    store.get_or_create("c1", "biz_a")
    store.get_or_create("c2", "biz_a")
    assert len(store) == 2
    store.reset("c1")
    assert len(store) == 1
