# Design Principles

Strict but not dogmatic guidelines for writing testable, decoupled, and maintainable Python code.

---

## 1. Core Philosophy

### Testability is the design quality signal

If a behavior-driven test is hard to write — needs `mock.patch`, `monkeypatch`, or a 20-line arrange phase — the **design is wrong**, not the test. Refactor the code until the test becomes trivial.

### Behavior, not implementation

Tests specify **what** the code does (public behavior), not **how** it does it (internal calls, structure, private methods). A test that mirrors the implementation breaks on every refactor and proves nothing about correctness.

```python
# ❌ BAD — implementation-driven test, coupled to internals
def test_processor_calls_client_with_correct_url():
    with mock.patch("httpx.Client.post") as mock_post:
        mock_post.return_value = Mock(status_code=200, json=lambda: {"id": "123"})

        processor = OrderProcessor(httpx.Client())
        processor.process(Order(items=[Item(10, 2)]))

    mock_post.assert_called_once_with(
        "/pay",
        json={"items": [{"price": 10, "qty": 2}]}
    )
    # ↑ Testing that the code does what the code does.
    #   Refactor the URL? Test breaks. Switch HTTP library? Test is meaningless.
    #   This test is a mirror, not a specification.

# ✅ GOOD — behavior-driven test, specifies the contract
def test_processor_returns_receipt_with_correct_total():
    gateway = FakePaymentGateway(returned_result=PaymentResult(
        success=True,
        transaction_id="123",
    ))
    processor = OrderProcessor(gateway)

    receipt = processor.process(Order(items=[Item(price=10, qty=2)]))

    assert receipt.transaction_id == "123"
    assert receipt.amount == 20
    # ↑ Testing the PUBLIC BEHAVIOR.
    #   Refactor internals? Test still passes. Switch HTTP library? Still passes.
    #   This test is a specification, not a mirror.
```

### Test-first, outside-in — for design

Write tests **before** the code. This forces you to think about the public contract before any implementation exists, which prevents implementation-coupled tests from ever being written.

But *where* you start writing tests matters. There are two directions:

```
   BOTTOM-UP (risky)                  OUTSIDE-IN (balanced)
   ═══════════════════                ═════════════════════════

   Test individual units             Test the highest-level behavior
          │                                  │
          ▼                                  ▼
   Implement each unit                Fake the next layer down
          │                                  │
          ▼                                  ▼
   Stitch them together               The fake reveals the interface
          │                                  │
          ▼                                  ▼
   DISCOVER MISMATCHES                The subsystem's API is DESIGNED
   at integration time                by its consumer — fits perfectly
```

Bottom-up works well for pure computations — value objects, data transformations, calculations with no side effects. These have no collaborators, so there's no interface to get wrong.

But for any system with multiple collaborating layers, bottom-up risks discovering at integration time that the pieces don't fit. The `SessionManager` returns a tuple, but the MCP tool needs a `Session` object. The `DockerClient` expects string arguments, but the `SessionManager` built a dict. Refactor. Tests break. The tests were mirrors, not specifications.

Outside-in avoids this entirely:

```
   PHASE 1: OUTSIDE-IN FOR DESIGN
   ═══════════════════════════════════

   1. Write a test at the highest level with a fake for the next layer.
   2. The test reveals what interface the next layer must provide.
   3. The interface is designed by the consumer — not guessed by the provider.
   4. No integration surprise later.

   Example:
     # Test the MCP tool with a fake SessionManager
     manager = FakeSessionManager()
     tool = ExecutePythonTool(manager)
     result = tool.execute("print(42)")

     # This test revealed that SessionManager needs:
     #   manager.execute_code(session_id, code) -> ExecutionResult
     # Not what I would have guessed. The test told me.
```

```
   Test-first                         Test-after
   ──────────                         ──────────

   "What should this DO?"             Code already exists
          │                                   │
          ▼                                   ▼
   Write test for that behavior       "How do I test this?"
          │                                   │
          ▼                                   ▼
   Write code to make it pass         Patch the internals to reach the code
```

### Consolidate fakes to reality — for confidence

The fakes from the outside-in phase are **temporary scaffolding**, not permanent fixtures. Once the real components exist, swap the fakes for real implementations level by level, stopping where the real thing is too expensive or unreliable.

```
   PHASE 2: BUILD THE REAL THING
   ═══════════════════════════════════

   Implement the real SessionManager.
   Implement the real DockerClient.
   The interfaces already fit — they were designed
   by their consumers in phase 1.

   PHASE 3: CONSOLIDATE FAKES TO REALITY
   ═══════════════════════════════════

   Replace the FakeSessionManager with RealSessionManager
   (but keep a FakeDockerClient inside it).

   The test becomes more realistic — it tests the actual
   collaboration, not assumptions about it.

   But Docker stays faked: spinning up real containers
   in every test is slow, unreliable, and unnecessary.
```

The boundary for what stays faked is pragmatic:

| Layer | Verdict | Why |
|---|---|---|
| Pure computation / value objects | NO FAKE NEEDED | Test directly with real objects |
| In-process business logic | SWAP TO REAL | Tests are fast, confidence is high |
| IO boundaries (Docker, HTTP, DB) | STAY FAKED | Real IO is slow, flaky, expensive |
| Hardware / OS features | STAY FAKED | Can't run in CI reliably |

The arrange phase stays simple throughout:

```
   Phase 1 arrange:  FakeSessionManager()                    ← 1 line
   Phase 3 arrange:  RealSessionManager(FakeDockerClient())  ← 2 lines
   # Same DI. Same test structure. More realistic.
```

The key constraint: **swapping the fake for the real thing must never break the test.** If it does, the test was coupled to the fake's implementation details, not the real component's behavior. The test was a mirror, not a specification.

### Easy arrange = good design

The arrange phase of a behavior-driven test is the ultimate design heuristic:

- **1–3 lines**: inject fakes, provide input, assert output → good design
- **`mock.patch`, `monkeypatch`, 20+ lines of setup** → bad design, refactor

---

## 2. Dependency Injection

Pass dependencies as constructor parameters. Never instantiate dependencies inside a class. This makes coupling visible in the signature and testing trivial.

```python
# ❌ BAD — hardcoded dependency, untestable without patching
class OrderProcessor:
    def process(self, order: Order) -> Receipt:
        client = httpx.Client()          # hidden coupling
        response = client.post("/pay", json=order.as_dict())
        return Receipt.from_response(response)

# Test for BAD version:
#   with mock.patch("httpx.Client") as m:   ← smell
#       m.return_value.post.return_value = fake_response
#       processor = OrderProcessor()
#       result = processor.process(order)
#   ↑ You're testing your mock, not your code

# ✅ GOOD — dependency injected, trivially testable
class OrderProcessor:
    def __init__(self, payment_client: PaymentClient) -> None:
        self._client = payment_client

    def process(self, order: Order) -> Receipt:
        response = self._client.charge(order)
        return Receipt.from_response(response)

# Test for GOOD version:
#   client = FakePaymentClient(success=True)
#   processor = OrderProcessor(client)       ← 1-line arrange
#   result = processor.process(order)
#   assert result.amount == order.total
#   ↑ No patches. No mocks. Just a fake.

### No `None` sentinels for dependencies

A default value must be a **real, usable value** — not `None` used as a
sentinel that triggers hidden creation.

```python
# ❌ BAD — None as a sentinel, hidden creation
class OrderProcessor:
    def __init__(self, client: PaymentClient | None = None) -> None:
        if client is None:
            client = HttpxPaymentClient()     # hidden coupling!
        self._client = client

# The signature suggests the parameter is optional, but the object
# can't function without a real client. The fallback is hidden from
# the caller and creates a real HTTP client — making tests impossible
# without patching.

# ❌ ALSO BAD — same pattern, any dependency
def create_session_manager(
    config: dict[str, Any],
    docker_client: Any = None,               # sentinel
) -> Any:
    if docker_client is None:
        docker_client = create_docker_client()  # hidden runtime crash
    return SessionManager(docker=docker_client, config=config)

# ✅ GOOD — required parameter, explicit contract
class OrderProcessor:
    def __init__(self, client: PaymentClient) -> None:
        self._client = client        # always required, always visible
```

**Immutable defaults are fine.** `sys.stdin`, `datetime.now`, a frozen
dataclass, a class reference (callable) — these are real, usable values
that don't require `None` sentinels:

```python
# ✅ GOOD — immutable value, safe default
class SessionServer:
    def __init__(self, stdin: TextIO = sys.stdin) -> None:
        self._stdin = stdin
#   ↑ sys.stdin is a real, usable default. No sentinel, no fallback.
#     Callers override for testing: SessionServer(stdin=StringIO())

# ✅ GOOD — callable as factory, fresh instance per call
class RPCDispatcher:
    def __init__(
        self,
        make_timeout: Callable[[], TimeoutStrategy] = ThreadTimeoutStrategy,
    ) -> None:
        self._timeout = make_timeout()  # fresh instance each time
```

**Mutable / stateful service objects must be required parameters.**
The caller must construct them explicitly:

```python
# ✅ GOOD — required, no default
class RPCDispatcher:
    def __init__(self, timeout: TimeoutStrategy) -> None:
        self._timeout = timeout   # no default, caller provides it
```

**Docstring hint for required params.** When a service object is
required, mention a reasonable standard default in the docstring so
developers can quickly use the function without digging through the
codebase:

```python
def create_mcp_app(
    config: dict[str, Any],
    docker_client: Any,
) -> Any:
    """Create the FastMCP application with all tools registered.

    Args:
        config: Dict with sandbox configuration.
        docker_client: Docker client. Use ``create_docker_client()``
                       to obtain one.

    Returns:
        A configured FastMCP instance.
    """
```

**The rule of thumb:**

| Default type | Verdict | Example |
|---|---|---|
| `None` as sentinel for fallback creation | **NEVER** | `client: Client | None = None` → `if None: create()` |
| Immutable value | **FINE** | `sys.stdin`, `datetime.now`, `Config()`, `ThreadTimeoutStrategy` |
| Callable / class reference | **FINE** | `make_timeout: Callable = ThreadTimeoutStrategy` |
| Mutable / stateful service object | **REQUIRED** | `client: Client` — no default, caller builds it |

**The exception:** `None` is acceptable as a default when the parameter
genuinely means "no value", not as a trigger for fallback creation:

```python
# ✅ OK — None means "no value", not "create something"
class OrderProcessor:
    def __init__(self, callback: Callable[[], None] | None = None) -> None:
        self._callback = callback    # None means "no callback", no fallback

    def process(self, order: Order) -> None:
        if self._callback:
            self._callback()         # only called if provided
```

---

## 3. Factories as Composition Roots

A factory is the **single place** where config is read and objects are created with config already baked in. Intermediate layers never see settings. This eliminates both hidden config coupling and prop drilling.

```
   Settings ──▶ Factory (reads config ONCE)
                     │
                     ├──▶ RetryClient(timeout=5)     ← config baked in here
                     │         │
                     │         ▼
                     └──▶ Processor(client=...)      ← sees a configured object,
                               not Settings
```

```python
# ❌ BAD — settings scattered, hidden coupling everywhere
def process_orders(orders: list[Order]) -> list[Receipt]:
    client = httpx.Client(timeout=settings.TIMEOUT)  # hidden read
    for order in orders:
        response = client.post("/pay", json=order.as_dict())
        # ...

# ❌ ALSO BAD — prop drilling, every layer carries settings
def process_orders(orders: list[Order], settings: Settings) -> list[Receipt]:
    for order in orders:
        response = charge(order, settings)  # passing through

def charge(order: Order, settings: Settings) -> Response:
    return retry_call(order, settings)  # passing through

def retry_call(order: Order, settings: Settings) -> Response:
    # FINALLY used here, 3 layers deep
    return httpx.Client(timeout=settings.TIMEOUT).post(...)

# ✅ GOOD — factory reads config once, objects are pre-configured
class OrderProcessorFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create(self) -> OrderProcessor:
        client = httpx.Client(timeout=self._settings.timeout_seconds)
        return OrderProcessor(client)

class OrderProcessor:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client       # already configured, no settings

    def process(self, orders: list[Order]) -> list[Receipt]:
        return [self._charge(o) for o in orders]

    def _charge(self, order: Order) -> Receipt:
        response = self._client.post("/pay", json=order.as_dict())
        return Receipt.from_response(response)

# Test:
#   factory = OrderProcessorFactory(Settings(timeout_seconds=5))
#   processor = factory.create()       ← config happens here, once
#   # OR: processor = OrderProcessor(fake_client)  ← skip factory in tests
```

---

## 4. Protocols for Interfaces

Use `typing.Protocol` to define what a consumer needs. The consumer defines the interface, not the provider. Any object that fits the shape satisfies the protocol — no inheritance required. Test doubles become trivial.

```python
from typing import Protocol

# The consumer defines what it needs — in domain terms
class PaymentClient(Protocol):
    def charge(self, order: Order) -> Response: ...

# Anything that fits the shape works — no inheritance needed
class FakePaymentClient:
    def charge(self, order: Order) -> Response:
        return Response(status=200, body={"paid": True})
#   ↑ Satisfies PaymentClient implicitly. No mock.patch.
```

---

## 5. Interfaces for 3rd Party Libraries

Never let a 3rd party library's types or API leak into your domain. Define a `Protocol` in your domain language, write an adapter at the boundary, and inject the protocol. Domain code never imports the 3rd party.

```python
# ❌ BAD — httpx is everywhere, can't swap or test without patching
class OrderProcessor:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client                    # coupled to httpx

    def process(self, order: Order) -> Receipt:
        resp = self._client.post("/pay", json=order.as_dict())
        #                         ^^^^ httpx-specific API
        return Receipt.from_response(resp)
        #                     ^^^^ httpx.Response type

# ✅ GOOD — your Protocol, your domain language, adapter at boundary
class PaymentGateway(Protocol):
    """What the domain needs — expressed in domain terms."""
    def charge(self, order: Order) -> PaymentResult: ...

class HttpxPaymentGateway:
    """Adapts httpx to the PaymentGateway interface."""
    def __init__(self, client: httpx.Client, url: str) -> None:
        self._client = client
        self._url = url

    def charge(self, order: Order) -> PaymentResult:
        resp = self._client.post(self._url, json=order.as_dict())
        return PaymentResult(
            success=resp.status_code == 200,
            transaction_id=resp.json()["id"],
        )
    # ↑ httpx lives HERE, in the adapter, nowhere else

class OrderProcessor:
    def __init__(self, gateway: PaymentGateway) -> None:
        self._gateway = gateway                 # your interface

    def process(self, order: Order) -> Receipt:
        result = self._gateway.charge(order)    # domain language
        return Receipt.from_result(result)      # domain type

# Test:
#   gateway = FakePaymentGateway(success=True)
#   processor = OrderProcessor(gateway)         ← trivial
# Switch to requests? Write RequestsPaymentGateway. Domain untouched.
```

---

## 6. Composition Over Inheritance

Favor small, injectable, composable pieces over deep inheritance hierarchies. Each piece should be testable in isolation. Inheritance drags in behavior you didn't ask for; composition lets you wire exactly what you need.

```python
# ❌ BAD — deep inheritance, rigid, untestable in isolation
class BaseProcessor:
    def process(self, data: bytes) -> Result: ...

class RetryProcessor(BaseProcessor):
    def process(self, data: bytes) -> Result:
        for _ in range(3):
            try:
                return super().process(data)
            except Exception:
                continue
        raise

class LoggingProcessor(RetryProcessor):       # inherits retry too!
    def process(self, data: bytes) -> Result:
        logger.info("starting")
        result = super().process(data)         # drags retry behavior
        logger.info("done")
        return result

# Testing LoggingProcessor? You get RetryProcessor for free
# whether you want it or not. Can't isolate.

# ✅ GOOD — compose small injectable pieces, each testable alone
class Processor(Protocol):
    def process(self, data: bytes) -> Result: ...

class RetryProcessor:
    def __init__(self, inner: Processor, retries: int = 3) -> None:
        self._inner = inner
        self._retries = retries

    def process(self, data: bytes) -> Result:
        for _ in range(self._retries):
            try:
                return self._inner.process(data)
            except Exception:
                continue
        raise

class LoggingProcessor:
    def __init__(self, inner: Processor) -> None:
        self._inner = inner

    def process(self, data: bytes) -> Result:
        logger.info("starting")
        result = self._inner.process(data)
        logger.info("done")
        return result

# Test LoggingProcessor in isolation:
#   inner = FakeProcessor(returns=Result(ok=True))
#   proc = LoggingProcessor(inner)
#   result = proc.process(b"data")
#   ↑ No retry logic dragged in. Pure. Simple arrange.
#
# Want both? Compose them:
#   proc = LoggingProcessor(RetryProcessor(real_processor, retries=5))
```

---

## 7. Rich Domain Models

Behavior lives with the data it operates on. Avoid anemic domain models where classes are data bags and all logic lives in separate service classes. A domain object should know its own invariants, calculations, and state transitions.

```python
# ❌ BAD — anemic: data bag + service doing all the thinking
class Order:
    def __init__(self, items: list[Item]) -> None:
        self.items = items              # just data, no behavior

class OrderService:                      # logic lives elsewhere
    def total(self, order: Order) -> float:
        return sum(i.price * i.qty for i in order.items)

    def is_valid(self, order: Order) -> bool:
        return len(order.items) > 0 and self.total(order) > 0

    def summary(self, order: Order) -> str:
        return f"Order: {self.total(order):.2f} ({len(order.items)} items)"

# The order doesn't know anything about itself.
# The service functions could be pure functions — the class adds nothing.

# ✅ GOOD — rich: behavior lives with the data it operates on
class Order:
    def __init__(self, items: list[Item]) -> None:
        self._items = items

    def total(self) -> float:
        return sum(i.price * i.qty for i in self._items)

    def is_valid(self) -> bool:
        return len(self._items) > 0 and self.total() > 0

    def summary(self) -> str:
        return f"Order: {self.total():.2f} ({len(self._items)} items)"

# Test:
#   order = Order([Item(price=10, qty=2)])
#   assert order.total() == 20            ← no service needed
#   assert order.is_valid() is True       ← behavior is on the object
```

---

## 8. Readability Guards

### No magic numbers — centralize in Settings

Don't scatter bare numbers or module-level constants. Centralize all configuration in a `Settings` object so there is a single source of truth. Factories read from it once (see section 3).

```python
# ❌ BAD — magic numbers scattered inline
def process(order: Order) -> Receipt:
    for _ in range(3):                    # 3 = ?
        try:
            response = httpx.post("/pay", timeout=30)  # 30 = ?
            if response.status_code == 200:
                break
    else:
        raise TimeoutError()

# ❌ STILL BAD — named but scattered, no central source of truth
MAX_RETRIES = 3
DEFAULT_TIMEOUT_SECONDS = 30

def process(order: Order) -> Receipt:
    for _ in range(MAX_RETRIES):
        # ...
# What if another module needs the same timeout? Copy it? Import it?

# ✅ GOOD — centralized in Settings, read via factory
@dataclass(frozen=True)
class Settings:
    max_retries: int = 3
    timeout_seconds: int = 30
    max_payload_bytes: int = 1024 * 1024

class OrderProcessorFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create(self) -> OrderProcessor:
        client = httpx.Client(timeout=self._settings.timeout_seconds)
        return OrderProcessor(
            client=client,
            max_retries=self._settings.max_retries,
        )
# One place to look. One place to change. Factory bakes it in.
```

### No premature optimization — measure first

Write clean, readable code first. Never sacrifice readability or maintainability to solve a performance bottleneck that hasn't been measured. If something is slow, profile it, prove the bottleneck, optimize with a test demonstrating the improvement, and comment why.

```python
# ❌ BAD — sacrificed readability for unmeasured "performance"
class OrderRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_user_orders(self, user_id: str) -> list[Order]:
        # "ORM is slow, so we use raw SQL with manual caching..."
        cursor = self._session.execute_sql(
            "SELECT o.*, oi.* FROM orders o JOIN order_items oi "
            "ON o.id = oi.order_id WHERE o.user_id = ? "
            # ... 30 more lines of unreadable "fast" code
        )
        return [Order.from_row(row) for row in cursor]

# ✅ GOOD — clean and readable first, optimize when measured
class OrderRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_user_orders(self, user_id: str) -> list[Order]:
        return self._session.query(Order).filter(Order.user_id == user_id).all()

# Is it slow? Profile it.
#   → Not a bottleneck? Great. Done. Move on.
#   → Is a bottleneck? NOW optimize — with a test proving the
#     improvement and a comment explaining why.
```

---

## 9. Named Arguments at Call Sites

Use keyword arguments whenever the meaning of a positional argument isn't immediately obvious. The call site is a contract with the reader — make it self-documenting.

```python
# ❌ BAD — what do these values mean?
result = calculate(42, "active", True, None)

# ✅ GOOD — self-documenting call site
result = calculate(
    user_id=42,
    status="active",
    include_inactive=True,
    callback=None,
)
```

### When positional is fine

Positional arguments are acceptable — even preferred — when the argument is the obvious, singular subject of the function and the reader can infer meaning without looking up the signature:

```python
# ✅ GOOD — obvious, single primary subject
total = sum(items)
result = sqrt(16)
order.total()
json.loads(raw_string)
datetime.fromisoformat("2024-01-01")
```

### When keyword is required

Use keyword arguments for anything that is **not** the obvious single subject:

```python
# ❌ BAD — ambiguous positional args
client.connect("localhost", 8080, 30, True)

# ✅ GOOD — explicit intent
client.connect(
    host="localhost",
    port=8080,
    timeout=30,
    use_ssl=True,
)
```

This applies especially to boolean flags, numeric values, `None`, strings whose purpose isn't obvious, and injected dependencies.

### The heuristic

> If you had to look at the function's signature to understand a positional argument, use a keyword argument instead.

If `foo(42, "bar", True)` makes you pause, the call site should be `foo(timeout=42, name="bar", retry=True)`. If it's obvious at a glance (`sqrt(16)`), positional is fine.

---

## 10. When to Inject vs Relax

Not everything needs to be injected. The boundary is whether the dependency is **business logic** (inject it, define a Protocol) or **infrastructure/observability** (use it directly).

| Dependency | Verdict | Rationale |
|---|---|---|
| HTTP client | INJECT | Avoid patching external IO |
| Database session | INJECT | Avoid patching external IO |
| API keys / secrets | INJECT via factory | Never hardcode secrets |
| 3rd party libraries | INJECT via Protocol | Keep domain decoupled (see section 5) |
| `datetime.now()` | CONTEXT-DEPENDENT | See below |
| Settings / Config | INJECT via factory | Factory reads once, no prop drilling (see section 3) |
| Logging | DON'T INJECT | Use `logging.getLogger(__name__)` — logs are observability, not business logic |
| `pathlib.Path` | DON'T INJECT | Use `tmp_path` in tests — filesystem abstraction is over-engineering for most code |

### `datetime.now()` — context-dependent

If time is **central to the function's output** and you must assert on it downstream (e.g., a report generator that stamps records), inject a clock function:

```python
# ✅ INJECT when time shapes the output
class ReportGenerator:
    def __init__(self, clock: Callable[[], datetime] = datetime.now) -> None:
        self._clock = clock

    def generate(self, records: list[Record]) -> Report:
        timestamp = self._clock()
        return Report(generated_at=timestamp, records=records)

# Test:
#   fixed_time = datetime(2024, 1, 1, 12, 0, 0)
#   gen = ReportGenerator(clock=lambda: fixed_time)
#   report = gen.generate(records)
#   assert report.generated_at == fixed_time   ← trivial
```

If time is **incidental** (logging timestamps, metadata), just call `datetime.now()` directly. Don't complicate the design for observability.

### The decision procedure

When encountering a dependency not listed above, ask:

```
   Is this dependency part of the BUSINESS LOGIC,
   or is it INFRASTRUCTURE / OBSERVABILITY?

   BUSINESS LOGIC              INFRASTRUCTURE
   • Payment gateway           • Logging
   • Database queries          • File paths (Path)
   • Time-as-output            • Time-as-metadata
   • Config that shapes        • Metrics
     behavior

   → INJECT IT                 → RELAX, use directly
   → Protocol interface        → Don't complicate
   → Fake in tests               the design for it
```

---

## 11. Implied Anti-Patterns

These don't need their own sections because the principles above kill them naturally. They're listed here so they're explicitly named.

| Anti-pattern | Why it's dead |
|---|---|
| **God classes** | If a class does too much, its behavior-driven test needs a massive arrange phase. The testability pressure forces decomposition. |
| **Circular dependencies** | If A needs B needs A, you can't construct either in a test. Testability pressure forces breaking the cycle. |
| **Service locator** | A global registry that hands out dependencies is just DI with hidden coupling. The signature doesn't show the deps. Replaced by explicit DI. |
| **`mock.patch` as standard practice** | If you need `mock.patch` in a behavior-driven test, the dependency wasn't injected. Fix the design, not the test. |
| **`None` sentinel defaults** | A hidden fallback that creates a dependency defeats DI and forces patching. Required params or real defaults instead (see section 2). |
| **Duplicated defaults across layers** | Copies of a config value silently diverge. One source of truth, read once by the factory (see section 8). |
| **Anemic domain models** | Data bags + service classes split behavior from data. Rich models keep them together (see section 7). |
| **Implementation-coupled tests** | Tests that mirror source code break on refactor and prove nothing. Test-first prevents them from existing (see section 1). |
