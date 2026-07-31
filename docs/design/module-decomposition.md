# Why memory is its own module — Parnas 1971 applied to an agent

This is a design-rationale doc. It explains *why* mycelium is shaped the way it
is — a separate process with a small, abstract interface — rather than a table
your agent reaches into directly. The argument is not new. It is David Parnas's,
from 1971, and it holds up unreasonably well for LLM agents.

If you're integrating mycelium into your own agent and wondering where the seams
should go, this is the doc that answers it.

Paper (open access, ~15 pages, worth reading):
**David Parnas, *On the Criteria To Be Used in Decomposing Systems into Modules*
(1971)** — <https://prl.khoury.northeastern.edu/img/p-tr-1971.pdf>

---

## The paper in plain language

Parnas asks a question that sounds trivial and isn't: when you split a system
into modules, *what decides where the cuts go?*

The obvious answer — the one he argues against — is to make each **step in the
processing** a module. Draw the flowchart (read input → transform → sort →
format → output) and turn each box into a module. Almost everyone's first
instinct.

His alternative: start with a list of the **design decisions that are likely to
change**, and make each module *hide one of those decisions* from all the others.
A module's interface should "reveal as little as possible about its inner
workings." He calls this **information hiding**, and it's the idea that most of
modern software architecture is downstream of.

He proves it with two versions of the same small program (a keyword-in-context
index). Version one is cut by processing step. Version two is cut by hidden
decision. Then he writes down a list of plausible changes — change the input
format, stop holding everything in memory at once, compute results lazily instead
of storing them — and shows that in version two **each change stays inside one
module**, while in version one the same change ripples through nearly all of them.

Three payoffs he names for cutting on the right criterion:

- **Changeability** — a likely change touches one module, not five.
- **Independent development** — simple interfaces (function names + parameter
  types) let people build against a module without co-designing its internals.
- **Comprehensibility** — you can understand a module without understanding its
  neighbors.

The whole essay is one claim: *don't derive your module boundaries from the
order of execution. Derive them from what's likely to change.*

---

## Mycelium is a Parnas module

Mycelium hides exactly one hard, change-prone design decision: **how memory is
stored, connected, decayed, and retrieved.** That is its secret. Everything
behind the interface — the SQLite schema, the FTS index, the co-access edges, the
`exp(-days / tau)` decay curve, the hot/cold tiering, the pruning threshold — is
information the rest of your system is *not allowed to know*.

What it exposes instead is a small, abstract interface — verbs, not tables:

```
context()   save()   recall()   pin()   forget()   connections()   ...
```

That interface is Parnas's "reveal as little as possible" done deliberately. You
`recall("the deploy target")`; you do not `SELECT ... FROM memories JOIN
connections`. The moment your agent knows the decay formula is
`exp(-days / tau)`, or that connections live in a table called `connections`,
that knowledge has leaked across the boundary — and every future change to how
memory works becomes a change to *your agent too*. The interface exists precisely
so that it doesn't.

This pays off exactly where Parnas said it would. Every design decision inside
mycelium is one he'd have put on his "likely to change" list:

| Decision that could change | Stays hidden behind |
|---|---|
| Decay curve / `tau` / pruning threshold | `recall()` (decay runs inside it) |
| How connections form and strengthen | `save()` / `recall()` co-access logic |
| Storage format (SQLite today, something else tomorrow) | the whole tool surface |
| What counts as a "hub" at session start | `context()` |

Swap any of those and your agent code does not change. That is the entire benefit,
and it is not an accident — it's the criterion the boundary was drawn on.

### Two secrets, not one — semantic vs. behavioral memory

Mycelium ships **two** memory subsystems that "share nothing — different SQLite
files, different tools, different lifecycles" (see [concepts.md](../concepts.md)):

- **Semantic memory** — durable "what I know." Free-text, decays, self-connects.
- **Behavioral memory (foundry)** — append-only log of decisions made, queried
  later in aggregate.

Parnas would recognize why they're separate modules and not one: they change for
*different reasons and at different rates*. Semantic memory's hard problem is
relevance-over-time (decay, connection, recall). Foundry's hard problem is
cheap, fail-soft, high-volume append. Different secret, different lifecycle,
different module. Fusing them would put two unrelated change-drivers behind one
interface — the exact coupling the criterion tells you to avoid.

---

## "Memory is guidance, system state is truth" is a clean boundary

A good decomposition has a property Parnas leaned on: a fault stays on its own
side of the interface. Mycelium's integration guidance — *memory suggests, but
the agent verifies against real state before acting* — is that property stated as
a rule.

It splits responsibility cleanly:

- **Memory's job** is to *select and scope*: surface what mattered before, narrow
  the search. It fails by selecting the wrong thing — and the fix lives in memory
  (sharpen the query, prune a stale hub, `forget()` the bad row).
- **The executor's job** is to *act and verify*: check the file, the database,
  the API, then do the thing. It fails by executing wrong — and the fix lives in
  the executor.

Because the boundary is clean, a memory mistake can't become an execution
mistake without the executor's own verification failing too. The two failure
modes don't smear across the interface. That's not a lucky property; it's what
"clean decomposition" *means*.

---

## The pruning test — and mycelium passes it

Parnas's discussion of hierarchy includes a test worth stealing: a good
decomposition lets you **cut off the top of the system and still have something
useful left on the trunk**. If a module only makes sense as part of the whole,
the boundary is fake.

Mycelium passes literally. It's a "single-process MCP server, SQLite + FTS5, zero
external services." You can run it with no agent above it at all — save and
recall from any MCP client, or none, and it's a working memory store on its own.
The fact that it's useful *pruned away from any particular agent* is the evidence
the seam is real. A memory layer that only worked as an internal detail of one
specific agent framework would have failed this test.

This is also why the same store can be shared across Claude Code, Claude Desktop,
and Codex at once: the memory is the *agent's*, not any one CLI's. Only a module
with a genuinely abstract interface can be shared like that. A leaky one couldn't.

---

## The part Parnas didn't have: information hiding in the *attention* domain

Parnas hid design decisions across an **address space** — module A cannot reach
into module B's variables. LLM agents have a second place to hide things that he
never had: the **context window**.

A common and effective agent pattern is to run a multi-step task as a chain of
steps where **each step gets a fresh context** and receives only the *structured
output* of the previous step — never the previous step's raw working material. A
step that digests a 10,000-row dump emits a short structured summary; the next
step sees the summary and cannot see the rows.

That is information hiding, implemented in tokens:

- the **secret** is the raw upstream material (the full dump, the whole document),
- the **module wall** is the fresh context window,
- the **abstract interface** is the structured output schema passed forward.

And the enforcement is *stronger* than Parnas's, because it's physical rather than
conventional: a downstream step cannot attend to what was never placed in its
context. There is no discipline to violate. This is why context isolation keeps
raw retrieved data from polluting later reasoning — it's the same principle,
relocated from memory addresses to attention.

Mycelium is built to feed this pattern rather than fight it: `recall()` returns a
*narrow, ranked* set of memories, not a dump. That narrowness is an interface
decision, not a performance tweak — it exists so the caller can hide the rest.

---

## How to apply this to your own integration

If you're wiring mycelium (or any memory) into an agent, Parnas gives you a cheap,
concrete design ritual — usable before you write a line of code:

1. **Write the list of things likely to change first.** Which facts vary per
   user, per project, per environment? Which policies will you tune? That list
   *is* your module boundaries.
2. **Put each change-prone decision behind an interface**, and let callers depend
   only on the interface. Concretely: talk to memory through its tools
   (`save`/`recall`/`context`), never through its database. The day the storage
   changes, you want your agent untouched.
3. **Watch for interfaces that reveal more than they must.** Parnas's one
   self-flagged mistake was a module that exposed the *order* of its output when
   nothing needed that order — needlessly blocking alternative implementations.
   If your integration starts depending on the row shape, the tier names, or the
   decay constant, that's the same leak. Depend on *what a tool gives you*, not
   *how it happens to produce it*.
4. **Keep memory advisory.** Let it select and scope; verify against real state
   before acting. That's the boundary that keeps a recall miss from becoming a
   production mistake.

---

## Further reading

- The paper: <https://prl.khoury.northeastern.edu/img/p-tr-1971.pdf>
- [concepts.md](../concepts.md) — the full mental model for what each tool is
  *for*, including the semantic/behavioral split this doc treats as two modules.
