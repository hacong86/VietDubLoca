"""State machine phiên (docs/03 §6). Transition typed + guard; transition không hợp lệ bị từ chối (không âm thầm)."""
from __future__ import annotations

from enum import Enum


class S(str, Enum):
    IDLE = "IDLE"
    CONNECTING = "CONNECTING"
    DISCOVERING = "DISCOVERING"
    WARMING = "WARMING"
    BUFFERING = "BUFFERING"
    PLAYING = "PLAYING"
    PAUSED_USER = "PAUSED_USER"
    PAUSED_AUTO = "PAUSED_AUTO"
    SEEKING = "SEEKING"
    AD_HOLD = "AD_HOLD"
    STALLED = "STALLED"
    SOURCE_LOST = "SOURCE_LOST"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


_ACTIVE = {S.DISCOVERING, S.WARMING, S.BUFFERING, S.PLAYING, S.PAUSED_USER, S.PAUSED_AUTO, S.SEEKING, S.AD_HOLD,
           S.STALLED, S.SOURCE_LOST, S.RECONNECTING}

ALLOWED: dict[S, set[S]] = {
    S.IDLE: {S.CONNECTING, S.DISCOVERING, S.STOPPED},
    S.CONNECTING: {S.DISCOVERING, S.ERROR, S.STOPPED, S.RECONNECTING},
    S.DISCOVERING: {S.WARMING, S.BUFFERING, S.SOURCE_LOST, S.ERROR, S.STOPPED, S.AD_HOLD, S.SEEKING, S.PAUSED_USER},
    S.WARMING: {S.BUFFERING, S.PLAYING, S.ERROR, S.STOPPED, S.AD_HOLD, S.SEEKING, S.PAUSED_USER, S.SOURCE_LOST},
    S.BUFFERING: {S.PLAYING, S.PAUSED_USER, S.PAUSED_AUTO, S.SEEKING, S.AD_HOLD, S.STALLED, S.SOURCE_LOST, S.ERROR,
                  S.STOPPED, S.WARMING, S.RECONNECTING},
    S.PLAYING: {S.BUFFERING, S.PAUSED_USER, S.PAUSED_AUTO, S.SEEKING, S.AD_HOLD, S.STALLED, S.SOURCE_LOST, S.ERROR,
                S.STOPPED, S.RECONNECTING, S.WARMING},
    S.PAUSED_USER: {S.PLAYING, S.BUFFERING, S.SEEKING, S.AD_HOLD, S.STOPPED, S.ERROR, S.SOURCE_LOST, S.RECONNECTING},
    S.PAUSED_AUTO: {S.PLAYING, S.BUFFERING, S.PAUSED_USER, S.SEEKING, S.AD_HOLD, S.STOPPED, S.ERROR, S.SOURCE_LOST,
                    S.RECONNECTING},
    S.SEEKING: {S.BUFFERING, S.PLAYING, S.PAUSED_USER, S.SEEKING, S.AD_HOLD, S.STOPPED, S.ERROR, S.SOURCE_LOST},
    S.AD_HOLD: {S.BUFFERING, S.PLAYING, S.PAUSED_USER, S.SEEKING, S.STOPPED, S.ERROR, S.SOURCE_LOST, S.DISCOVERING},
    S.STALLED: {S.BUFFERING, S.PLAYING, S.PAUSED_USER, S.SEEKING, S.AD_HOLD, S.STOPPED, S.ERROR, S.SOURCE_LOST},
    S.SOURCE_LOST: {S.DISCOVERING, S.BUFFERING, S.STOPPED, S.ERROR, S.SEEKING},
    S.RECONNECTING: {S.BUFFERING, S.PLAYING, S.PAUSED_USER, S.STOPPED, S.ERROR, S.DISCOVERING},
    S.ERROR: {S.STOPPED, S.BUFFERING, S.DISCOVERING, S.RECONNECTING},
    S.STOPPED: set(),
}


class InvalidTransition(ValueError):
    pass


class StateMachine:
    def __init__(self, initial: S = S.IDLE) -> None:
        self.state = initial
        self.reason: str | None = None
        self.history: list[tuple[S, S, str | None]] = []

    def can(self, to: S) -> bool:
        return to == self.state or to in ALLOWED[self.state]

    def to(self, new: S, reason: str | None = None) -> bool:
        """True nếu đổi trạng thái. Cùng trạng thái → cập nhật reason, False. Không hợp lệ → InvalidTransition."""
        if new == self.state:
            self.reason = reason or self.reason
            return False
        if new not in ALLOWED[self.state]:
            raise InvalidTransition(f"{self.state.value}->{new.value}")
        self.history.append((self.state, new, reason))
        self.history = self.history[-100:]
        self.state = new
        self.reason = reason
        return True

    @property
    def active(self) -> bool:
        return self.state in _ACTIVE
