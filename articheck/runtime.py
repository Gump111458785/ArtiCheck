from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Any


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Budget:
    max_tools: int = 8
    max_tokens: int = 32000
    max_seconds: float = 180
    max_usd: float = 1.0
    tools: int = 0
    tokens: int = 0
    usd: float = 0
    started: float = 0

    def __post_init__(self):
        self.started = time.monotonic()
        if min(self.max_tools, self.max_tokens, self.max_seconds, self.max_usd) < 0:
            raise ValueError("Budgets must be nonnegative")

    def check(self):
        if time.monotonic() - self.started >= self.max_seconds:
            raise BudgetExceeded("wall-clock budget exceeded")

    def tool(self):
        self.check()
        if self.tools >= self.max_tools:
            raise BudgetExceeded("tool budget exceeded")
        self.tools += 1

    def reserve_model(self, token_bound: int, cost_bound: float):
        self.check()
        if self.tokens + token_bound > self.max_tokens or self.usd + cost_bound > self.max_usd:
            raise BudgetExceeded("model token/cost budget exceeded")
        # Charge an upper bound before submission; caller refunds unused capacity.
        self.tokens += token_bound
        self.usd += cost_bound


@dataclass
class Node:
    name: str
    deps: tuple[str, ...]
    run: Callable[[dict[str, Any]], Awaitable[Any]]


async def run_dag(nodes: list[Node], concurrency: int = 4) -> dict[str, Any]:
    graph = {n.name: n for n in nodes}
    if len(graph) != len(nodes) or concurrency < 1:
        raise ValueError("Duplicate DAG nodes or invalid concurrency")
    if any(dep not in graph for n in nodes for dep in n.deps):
        raise ValueError("Unknown DAG dependency")
    # Validate cycles before starting any side effects.
    seen, visiting = set(), set()
    def visit(name):
        if name in visiting:
            raise ValueError("DAG cycle")
        if name in seen:
            return
        visiting.add(name)
        for dep in graph[name].deps:
            visit(dep)
        visiting.remove(name)
        seen.add(name)
    for name in graph:
        visit(name)
    result = {}
    semaphore = asyncio.Semaphore(concurrency)
    async def execute(node):
        async with semaphore:
            return await node.run({dep: result[dep] for dep in node.deps})
    pending = set(graph)
    while pending:
        ready = sorted(n for n in pending if set(graph[n].deps) <= result.keys())
        values = await asyncio.gather(*(execute(graph[n]) for n in ready))
        for name, value in zip(ready, values):
            result[name] = value
            pending.remove(name)
    return result


def repo_digest(repo: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(repo.rglob("*")):
        rel = path.relative_to(repo)
        if any(x in {".git", "__pycache__", ".venv"} for x in rel.parts):
            continue
        if path.is_symlink():
            raise ValueError("Symlinks are not supported in artifact snapshots")
        if path.is_file():
            h.update(str(rel).encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


class ResultCache:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(repo_hash: str, argv: list[str], identity: dict) -> str:
        return hashlib.sha256(json.dumps([repo_hash, argv, identity], sort_keys=True).encode()).hexdigest()

    def get(self, key):
        path = self.root / f"{key}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def put(self, key, value):
        path = self.root / f"{key}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, allow_nan=False))
        tmp.replace(path)
