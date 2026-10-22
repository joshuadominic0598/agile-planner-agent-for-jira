"""Thread-safe steering inboxes for active, local chat requests."""

import threading
import time
from dataclasses import dataclass, field

from fastapi import HTTPException


class Steered(Exception):
    pass


@dataclass
class Turn:
    dataset: str
    started: float = field(default_factory=time.monotonic)
    messages: list = field(default_factory=list)
    applied: int = 0
    accepting: bool = True
    model_requests: int = 0
    actions: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, message):
        with self.lock:
            if not self.accepting:
                raise HTTPException(409, 'The response just completed. Send this as the next message.')
            if any(item['id'] == message['id'] for item in self.messages):
                return {'accepted': True, 'count': len(self.messages)}
            if len(self.messages) >= 4:
                raise HTTPException(
                    429,
                    'Please wait for responses. Up to four steering messages can be added to one response.',
                )
            self.messages.append(message)
            return {'accepted': True, 'count': len(self.messages)}

    def checkpoint(self):
        with self.lock:
            if len(self.messages) > self.applied:
                raise Steered()

    def snapshot(self):
        with self.lock:
            self.applied = len(self.messages)
            return list(self.messages)

    def seal(self):
        with self.lock:
            if len(self.messages) > self.applied:
                raise Steered()
            self.accepting = False


RUNS = {}
LOCK = threading.Lock()


def register(request_id, dataset):
    with LOCK:
        if request_id in RUNS:
            raise HTTPException(409, 'This message is already running.')
        turn = Turn(dataset)
        RUNS[request_id] = turn
        return turn


def find(request_id, dataset):
    with LOCK:
        turn = RUNS.get(request_id)
    if turn is None or turn.dataset != dataset:
        raise HTTPException(409, 'The response just completed. Send this as the next message.')
    return turn


def remove(request_id):
    with LOCK:
        RUNS.pop(request_id, None)
