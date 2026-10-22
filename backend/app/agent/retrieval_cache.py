"""Process-local TTL/LRU adapter; generated answers are never cached by similarity."""

import copy
import hashlib
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

VERSION = 'hybrid-rerank-v1'


def key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def guards(tokens):
    return {
        t
        for t in tokens
        if any(c.isdigit() for c in t) or t in {'no', 'not', 'without', 'exclude', 'excluding', 'only'}
    }


class MemoryRetrievalCache:
    def __init__(self, clock: Callable[[], float] = time.monotonic, ttl: float = 600):
        self._clock = clock
        self._ttl = ttl
        self._lock = threading.RLock()
        self._buckets = {name: OrderedDict() for name in ('results', 'vectors', 'pools')}
        self._limits = {'results': 64, 'vectors': 128, 'pools': 32}

    def get(self, bucket, ident):
        with self._lock:
            table = self._buckets[bucket]
            item = table.get(ident)
            if not item:
                return None
            if item[0] < self._clock():
                del table[ident]
                return None
            table.move_to_end(ident)
            return copy.deepcopy(item[1])

    def put(self, bucket, ident, value):
        with self._lock:
            table = self._buckets[bucket]
            table[ident] = (self._clock() + self._ttl, copy.deepcopy(value))
            table.move_to_end(ident)
            while len(table) > self._limits[bucket]:
                table.popitem(last=False)

    def semantic(self, scope, vector, tokens):
        if not vector:
            return None
        best = None
        best_score = 0.985
        with self._lock:
            entries = list(self._buckets['pools'].values())
        for expires, item in entries:
            if expires < self._clock() or item['scope'] != scope or guards(item['tokens']) != guards(tokens):
                continue
            a, b = set(tokens), set(item['tokens'])
            if len(a & b) / max(1, len(a | b)) < 0.6 or len(vector) != len(item['vector']):
                continue
            score = sum(x * y for x, y in zip(vector, item['vector']))
            if score >= best_score:
                best = item['ids']
                best_score = score
        return set(best) if best is not None else None

    def remember_pool(self, scope, query, vector, tokens, ids):
        if vector:
            self.put(
                'pools', key([scope, query]), {'scope': scope, 'vector': vector, 'tokens': tokens, 'ids': ids}
            )

    def clear(self):
        with self._lock:
            for table in self._buckets.values():
                table.clear()
