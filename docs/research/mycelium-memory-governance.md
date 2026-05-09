# Mycelium: Memory Governance for Long-Running Agent Systems
## A Context-Economy Architecture for Verifier-Mediated Agent Memory

**Sebastian Bui** — May 2026

## Abstract

Long-running agent systems do not fail primarily because they lack storage. They fail because they lack memory governance: explicit rules for deciding which experience should be trusted, compressed, forgotten, audited, promoted into procedure, or hardened into deterministic tooling. Contemporary retrieval-centric memory systems usually follow an append, embed, retrieve pattern. That pattern can surface semantically similar text, but it does not determine whether a memory is verified, obsolete, tenant-bound, procedural, private, contradictory, or safe to load into working context.

This paper presents Mycelium, a context-economy architecture for long-running local and multi-agent systems. Mycelium separates curated semantic memory, behavioral trace memory, session lineage, task coordination, and verifier-mediated action. Its central abstraction is a governed transition chain: events become traces, traces reveal patterns, patterns become lessons, lessons become procedures, and sufficiently stable procedures become deterministic tools. The contribution is not a replacement for vector indexes. Vector search is treated as an indexing primitive inside a larger governance architecture. Mycelium addresses the systems problem of how agent experience should change future behavior without flooding context, corrupting recall, or trusting model self-reports as evidence.

Keywords: agent memory; memory governance; retrieval-augmented generation; verifier-driven learning; context management; multi-agent systems; local inference; session lineage

## 1. Introduction

The dominant narrative around agent memory often begins with autonomy: how can an agent remember enough to operate over long time horizons? That framing is too broad to be operationally useful. A more concrete starting point is degradation. Long-running agent systems often become less reliable over time even as they accumulate more stored information. They repeat failures, over-retrieve stale history, load irrelevant context, summarize away important state, self-report success without evidence, and lose critical distinctions during ad hoc cleanup.

These are not primarily model-quality failures. They are infrastructure failures. A system that stores every event but lacks rules for trust, promotion, decay, consolidation, lineage, and verification does not become more competent. It becomes heavier. The memory store grows, but the agent's working context becomes noisier and less decisive.

Mycelium begins from the claim that memory in agent systems should be treated as governed infrastructure rather than passive storage. Memory is not merely a set of embeddings, a transcript archive, or a long prompt. It is the management of transitions between representations. A raw interaction should not have the same operational authority as a human-confirmed lesson. A model-generated reflection should not have the same status as a verifier-passing procedure. A repeated success should not remain forever as natural language guidance when it can be encoded as a testable tool.

The resulting architecture is a context economy: every model invocation spends a scarce attention budget. The system must decide which facts, procedures, traces, summaries, verifier outputs, and task states are allowed into that budget. A governed memory system does not maximize the amount of retrieved context. It maximizes the relevance, authority, and operational usefulness of what enters the working context.

## 2. Related Work and Positioning

Retrieval-augmented generation (RAG) established a practical pattern for combining parametric language models with external non-parametric memory, typically a dense index of documents retrieved at generation time (Lewis et al., 2020). RAG is foundational for grounding language-model output in external material, but it does not by itself define lifecycle rules for whether a retrieved record is trustworthy, stale, promotable, tenant-bound, contradictory, or suitable for conversion into procedure.

Recent agent architectures have explored memory beyond one-shot retrieval. Generative Agents store observations, retrieve relevant memories, and synthesize reflections to produce believable simulated behavior (Park et al., 2023). Reflexion uses verbal feedback stored in an episodic memory buffer so agents can improve across trials without updating model weights (Shinn et al., 2023). MemGPT frames long-context management through an operating-system analogy, using memory tiers and virtual-context management to work around fixed context windows (Packer et al., 2023).

Mycelium is aligned with this movement away from stateless prompting, but it targets a different layer of the problem. Its focus is not believability, conversational continuity, or a particular memory tiering mechanism. Its focus is governance: how agent experience should move between raw event, trace evidence, extracted pattern, curated lesson, reusable procedure, and deterministic tool. In this sense, Mycelium treats vector search, episodic reflection, and context paging as useful primitives but not as complete memory systems.

## 3. Retrieval Is Not Memory

A retrieval-centric memory system commonly follows a simple path:

```text
interaction -> chunk -> embed -> nearest-neighbor search -> prompt
```

This path answers the question, 'What past text looks similar to the current query?' That is useful, but it does not answer the questions that matter in long-running agent operations: Was the record verified? Did it help or hurt a prior attempt? Is it a durable fact, a hypothesis, a correction, a procedure, a failure trace, or raw evidence? Should it be pinned, cooled, decayed, deleted, audited, promoted, or converted into code? Does it apply globally, only within one workspace, or only under a narrow model/tool boundary?

The confusion between retrieval and memory produces a recurring failure mode: systems accumulate records faster than they develop judgment about those records. Similarity search then becomes an accidental authority mechanism. Whatever looks nearby becomes context, even when it is stale, unverified, contradicted, or too low-level to guide action.

Mycelium's position is that retrieval is one operation inside memory. It is not the memory system itself. A mature memory system needs search, but also classification, trust modeling, consolidation, promotion, rollback, scope control, verifier linkage, and deletion.

## 4. Memory as Governance

Memory governance is the management of transitions between representations. Mycelium's central chain is:

```text
event -> trace -> pattern -> lesson -> procedure -> tool
```

An event is something that happened: a model call, tool call, user correction, routing decision, test result, or human review. A trace is preserved evidence about that event: input, output, timing, model tier, failure class, verifier result, workspace, and task ID. A pattern is a recurring relationship across traces. A lesson is a curated statement that should influence future behavior. A procedure is a reusable method derived from one or more lessons. A tool is the deterministic or bounded embodiment of a procedure.

Most agent-memory systems stop at event storage or textual reflection. Mycelium is concerned with the transitions: what evidence authorizes a trace to become a lesson, what conditions prevent a lesson from becoming a procedure, and when repeated successful reasoning should become deterministic infrastructure.

| Representation | Definition | Storage surface | Promotion condition |
| --- | --- | --- | --- |
| Event | A single thing that happened: model call, tool call, correction, routing choice, verifier result. | Coordination log or raw event stream | Preserved when needed for audit, replay, or trace construction. |
| Trace | Structured evidence about an event: inputs, outputs, timings, failure class, task ID, verifier output. | Behavioral memory | Repeated or high-impact traces become candidates for pattern mining. |
| Pattern | A recurring relationship across traces: repeated failure, useful corrective action, routing issue, or stable success shape. | Analysis view / candidate lesson queue | Supported by recurrence, verifier evidence, or human review. |
| Lesson | A curated semantic statement that should influence future behavior. | Curated Mycelium memory | Verified by future use, QC, recurrence, or human confirmation. |
| Procedure | A reusable method derived from one or more lessons. | Procedural memory / harness guidance | Stable across tasks and worth loading as method guidance. |
| Tool | A deterministic or bounded implementation of a procedure. | Tool registry / codebase | Passes tests, has a contract, and is frequent enough to justify hardening. |

The distinction matters because each representation has a different failure mode. Raw traces are too bulky for routine recall. Lessons without trace lineage become ungrounded assertions. Procedures without verification become folklore. Tools without contracts become unsafe capabilities.

## 5. Governance Operations

Governance becomes operational when lifecycle transitions are explicit rather than hidden side effects. The following operations form a minimal governance surface for long-running agent memory.

| Operation | Purpose | Trigger evidence | Guardrails |
| --- | --- | --- | --- |
| Ingest | Accept a new event, trace, correction, or lesson. | Agent action, verifier result, user correction, import. | Schema validation, tenant boundary, secret and PII filters. |
| Classify | Assign representation type, scope, and authority. | Source, task kind, confidence, project, client, workspace. | Unknown scope defaults to conservative isolation. |
| Verify | Attach evidence that a record or output is true, useful, or complete. | Tests, QC pass, human confirmation, replay, benchmark. | Failed verification blocks promotion. |
| Connect | Link related records and preserve lineage. | Trace ID, explicit relation, co-recall, semantic similarity. | Prevent cross-tenant leakage and cap weak inferred edges. |
| Promote | Move records toward more durable and useful forms. | Repeated success, recurring failure, confidence threshold, human review. | No promotion from unverifiable traces into deterministic rules. |
| Consolidate | Replace dense clusters with compact summaries while preserving lineage. | Cluster density, stale repetition, hot-memory pressure. | Snapshot, dry-run, pinned skip, recency skip, smoke test. |
| Pin | Mark a memory as load-bearing or human-confirmed. | Human decision, high-confidence operational fact. | Pinned records resist decay and deletion. |
| Fold | Compress stale session history into a lineage summary. | Cache expiry, session age, context pressure. | Reject on missing intent, unresolved tool state, or failed fold smoke. |
| Replay | Re-run or inspect prior traces for diagnosis and evaluation. | Regression, failed promotion, audit request. | Replay should not mutate production state without sandboxing. |
| Decay/Delete | Lower priority or remove records and edges. | Staleness, failed QC, supersession, legal or safety requirement. | Audit log, snapshot, tenant policy, recall smoke test. |

These operations define not only what can happen to memory but what evidence authorizes the transition and what can stop it. This is the operational meaning of memory governance.

## 6. Pattern Extraction and Trust

A pattern is a candidate regularity extracted from traces under explicit evidence rules. Pattern extraction can be heuristic, statistical, model-assisted, or human-curated. A heuristic pattern may be the same verifier failure class appearing repeatedly at the same API boundary. A statistical pattern may be a retry-count reduction after a procedure is injected. A model-assisted pattern may be a local model clustering traces and drafting a candidate lesson. A human-curated pattern may be a maintainer marking a trace cluster as operationally meaningful.

```text
candidate_pattern = same failure_class appears >= 3 times
                    within a bounded task family
                    and at least 2 successful retries use the same corrective action
```

The numeric thresholds are policy choices rather than universal constants. The important property is auditability. A candidate lesson should be able to answer: Which traces support me? Which method detected me? What confidence do I currently carry? What evidence would falsify me?

Trust is therefore a first-class memory property. A model observation, a passing verifier result, and a human-confirmed procedure should not compete equally during recall. Confidence should increase with verifier evidence, recurrence, successful replay, successful future use, human confirmation, and independent agreement. It should decrease with contradiction, failed replay, staleness, scope ambiguity, source uncertainty, or brittle prompt dependence.

This does not require a universal numeric score. A system may represent confidence as tiers, tags, weights, or policy predicates. What matters is that confidence has sources, can change, and is attached to lineage. A human pin can protect a record from decay, but it should not erase contradictory evidence.

Conflict resolution should prefer scoped truth over winner-take-all truth. If a lesson works for one model tier, task type, or code boundary but fails in another, the system should narrow the lesson instead of deleting it or making it universal.

## 7. The Context Economy

Every agent invocation spends context. Context is not merely a token budget; it is the limited attention surface through which the model sees the world. Current task state, relevant facts, tool contracts, verifier output, session history, procedural guidance, safety constraints, and raw evidence all compete for entry into that surface.

A governed memory system does not maximize recall volume. It chooses the right representation at the right moment. Sometimes the agent needs a fact. Sometimes it needs a procedure. Sometimes it needs the latest verifier failure. Sometimes it needs a folded lineage summary instead of a full transcript. Sometimes it should receive nothing from memory because the risk of pollution exceeds the expected benefit.

Consider a long-running code-generation workflow. A naive system resumes a large transcript containing raw tool output, duplicated architectural notes, failed attempts, stale plans, and full test logs. The next model call spends most of its context reconstructing what happened. If prompt-cache locality has expired, the system pays to reread history without gaining new information. The model may still miss the useful fact: the last verifier failure was caused by a single API mismatch.

```text
Naive replay:
  full transcript
  + raw logs
  + old plans
  + duplicated failures
  + current task

Governed replay:
  current task
  + tool contract
  + relevant lesson
  + latest verifier failure
  + folded lineage pointer
  + trace ID for audit
```

The governed version does not remember less. It represents memory at the right level. Full traces remain available for replay, but the working context receives the distilled procedure and current failure signal.

## 8. System Model

Mycelium can be modeled as five cooperating layers: curated memory, behavioral trace memory, session lineage, coordination, and verifier-mediated action. No single component is 'the agent.' The system emerges from the interaction between task state, memory, traces, verifiers, models, and promotion gates.

```text
                         human / frontier review
                                  |
                                  v
                         promotion and trust gates
                                  |
                                  v
+-------------+      +-------------------+      +------------------+
| coordination| ---> | verifier harness  | ---> | behavioral trace |
| task state  |      | tools + tests     |      | store            |
+-------------+      +-------------------+      +------------------+
        |                      |                         |
        |                      v                         v
        |              local/frontier models       trace analysis
        |                      |                         |
        v                      v                         v
+-------------+      +-------------------+      +------------------+
| session     | ---> | curated memory    | <--- | distilled lessons|
| lineage     |      | graph/lifecycle   |      | and procedures   |
+-------------+      +-------------------+      +------------------+
```

### 8.1 Curated Memory

Curated memory stores semantic and procedural knowledge: facts, corrections, lessons, design principles, project state, and distilled failure patterns. This layer should become smaller and denser over time. It is not a raw log.

### 8.2 Behavioral Trace Memory

Behavioral memory stores high-volume evidence of decisions and outcomes: prompts, outputs, tool choices, routing decisions, verifier results, failure classes, elapsed time, token counts, and task identifiers. It supports replay, audit, and pattern mining. It should not directly flood semantic recall.

### 8.3 Session Lineage

Session lineage addresses long-running context. When a session is still warm, resumption may preserve useful continuity. When it is stale, blind replay becomes wasteful. A folding layer can summarize the prior transcript, start a successor session, and preserve predecessor links so compression remains auditable.

### 8.4 Coordination

Agents need shared task state. Coordination records what is being worked on, who owns it, whether it passed verification, and what state transitions occurred. Without coordination, memory and action drift apart. At minimum, the coordination layer should support task identity, ownership leases, explicit states, idempotent updates, append-only events, event propagation, retry deduplication, stale-worker recovery, escalation paths, and trace IDs linking task transitions to behavioral evidence.

### 8.5 Verifier-Mediated Action

The action layer is the harness: workspace boundaries, tool registry, model calls, verifier execution, trace capture, and promotion gates. In this layer, models are not trusted to declare their own success. They operate inside specifications and tests.

## 9. Separation of Semantic and Behavioral Memory

Semantic memory and behavioral memory have opposite lifecycle pressures. Semantic memory should consolidate repeated lessons, remove stale clutter, and preserve high-value facts. Its purpose is to make future context sharper. Behavioral memory should accumulate broadly because messy evidence is needed for auditability and pattern discovery.

Combining these layers creates two problems. First, raw traces pollute recall: an agent searching for a principle receives unprocessed logs. Second, curated memories lose evidentiary grounding: a lesson without trace lineage becomes another assertion. Separation allows a one-way distillation flow:

```text
behavioral traces -> repeated patterns -> curated lessons -> procedures -> tools
```

This is stronger than assigning every record a memory type inside one undifferentiated store. The layers can share identifiers and edges, but their retrieval surfaces and promotion rules should remain distinct.

## 10. Promotion, Graduation, and Tooling

Promotion prevents memory governance from becoming manual curation with better terminology. A memory system becomes operational when repeated evidence can move records into more useful forms. Promotion should be conservative. A single model-generated observation should not become a durable procedure. Promotion should require recurrence, verifier evidence, human review, successful replay, or measurable outcome improvement.

```text
observation -> candidate pattern -> verified lesson -> reusable procedure -> deterministic tool or rule
```

A typical pipeline begins when a model repeatedly fails a verifier because it uses a plausible but invalid API call. The trace store records the failed attempts, generated code, verifier output, model settings, and retry results. Pattern extraction identifies the repeated failure class. A curated lesson is saved: for this API boundary, use the reference helper; the superficially similar shortcut is invalid. Future prompts include the lesson and reference implementation. If the lesson repeatedly improves pass rate, it becomes a procedure in the harness. If the procedure is frequent, bounded, and stable, it becomes deterministic code, a lint rule, or a scaffold tool.

The endpoint of learning is not a better paragraph in a prompt. The endpoint is deterministic execution when the behavior is stable enough to deserve it. Repeated successful reasoning should harden into infrastructure:

```text
reason once -> remember
reason repeatedly -> write a procedure
apply procedure reliably -> build a tool
```

Tool graduation removes routine work from the model's context window, makes behavior testable through a contract, reduces variance across agents and sessions, gives verifiers a stable surface to check, and turns successful traces into reusable infrastructure. Not every procedure should become a tool; some remain contextual, rare, or judgment-heavy. But when a procedure is frequent, bounded, verifiable, and stable, leaving it as natural-language guidance wastes context and invites regression.

## 11. Consolidation Risks and Conflict Arbitration

Consolidation is necessary because hot memory grows faster than working context. It is also dangerous because summarization can destroy edge cases. Common risks include over-generalization, contradiction collapse, edge-case loss, lesson drift, inherited bad abstractions, and poisoning preservation. A consolidation process should therefore be reversible and evidence-aware. It should snapshot state, produce a dry-run plan, skip pinned or high-confidence records, avoid recently accessed records, log every transition, and run recall smoke tests afterward.

Contradictions should not be resolved by averaging. If two lessons conflict, safer consolidation preserves the condition under which each applies. 'Use model tier B for code generation' is too broad. 'Use model tier B for short classification prompts; use model tier A for verifier-driven code generation when retry context exceeds tier B limits' preserves operational precision.

Multi-agent settings make conflict normal. Two agents may produce contradictory lessons. Two workers may attempt overlapping writes. Two verifiers may disagree. Two folds may summarize the same session differently. Conflict arbitration should be explicit: verifier evidence outranks model self-report; human arbitration outranks automated promotion; tenant and workspace isolation outrank recall convenience; new evidence narrows old lessons before deleting them; and quorum cannot replace deterministic verification when such verification exists.

## 12. Verifier-Driven Learning

Agent systems should not treat model self-reports as evidence. A model saying 'done' is not a completion signal. A verifier passing is a completion signal. Verifier-driven learning uses external checks as the learning substrate: unit tests, smoke tests, QC verdicts, schema validation, static analysis, replay, or human review. The system records both the attempt and the outcome.

```text
specification + tests + reference context
  -> model attempt
  -> syntax/interface validation
  -> verifier
  -> retry with failure output if appropriate
  -> trace capture
  -> distilled lesson
```

This pattern creates a healthy division of labor. Ambiguous architecture, trust boundaries, credentials, verifier design, and promotion logic remain under frontier or human review. Local or cheaper models can handle bounded leaf work against tests. The system improves not because a model claims to have learned, but because traces show how future attempts change under verifier pressure.

## 13. Folding and Session Lineage

Context-window exhaustion is a hidden architectural problem in agent systems. Long sessions accumulate tool results, explanations, file contents, and obsolete plans. When resumed repeatedly, the system may pay to reread context that is no longer useful. Folding manages the transition between session continuity and summary.

A fold is not merely a summary. It is lineage-preserving compression. A fold should record which session it summarized, which successor session it created, how many turns were folded, what summary was introduced, when the transition occurred, and whether the downstream task still succeeded. If a later failure occurs, the system can ask whether the fold dropped necessary state.

Folding should be rejected or escalated when the current task goal is unresolved, tool calls are in flight, file paths or verifier failures are missing, the summary invents decisions, alternatives collapse into one asserted plan, tenant-boundary material cannot safely transfer, or a post-fold smoke question cannot recover essential state. A bad fold can be worse than a long transcript because it creates false confidence.

## 14. Local Inference as a Memory Primitive

Local inference is often justified by cost or privacy. In this architecture, there is a third reason: it makes memory maintenance cheap enough to run continuously. Many memory operations are not worth frontier calls: summarizing stale session history, classifying traces, extracting failure patterns, drafting candidate lessons, checking trace repetition, generating bounded code under tests, and producing retry prompts from verifier output.

This does not eliminate frontier models. It changes their role. Frontier models handle ambiguous judgment, system design, high-stakes review, and trust boundaries. Local models handle repetitive, bounded, verifiable cognition. The memory system becomes more practical when background cognition is cheap enough to run as maintenance rather than as an exceptional event.

## 15. Observed Failure Patterns

The architecture is motivated by operational failure patterns rather than abstract autonomy goals. These patterns are early case-study evidence, not a broad benchmark.

- Raw trace pollution: when logs and curated lessons share one recall surface, agents retrieve evidence fragments instead of principles.
- Stale session replay: long sessions burn budget by repeatedly replaying history after cache locality is gone.
- Self-reported success: agents produce plausible completion narratives without passing tests or creating expected artifacts.
- Cheap-model illusion: smaller models appear cheaper until context limits and retries make them operationally more expensive.
- Unsafe consolidation: cleanup damages recall when it lacks snapshots, dry runs, pinned-memory checks, recency checks, and smoke tests.

These cases suggest that evaluation should focus on whether memory governance changes system behavior: fewer repeated failures, better verifier pass rates, lower retry counts, lower context replay cost, safer consolidation, and more reliable promotion into procedure.

## 16. Evaluation Agenda

A serious evaluation of memory governance should not stop at retrieval accuracy. It should measure whether memory changes future behavior. Useful metrics include recall stability after consolidation, verifier pass rate with and without recalled lessons, retry success rate after verifier-feedback prompting, token and cache-read reduction from folding, trace-to-lesson precision, promotion accuracy, frontier-call displacement without quality regression, regression rate after memory maintenance, time-to-recovery after failed attempts, and repeated-failure-class reduction over time.

| Metric | Question answered | Possible measurement |
| --- | --- | --- |
| Recall stability | Does maintenance preserve important memories? | Smoke-test pass rate before and after consolidation. |
| Verifier pass delta | Do recalled lessons improve task outcomes? | Pass rate with relevant lessons injected versus withheld. |
| Retry reduction | Does memory reduce repeated mistakes? | Median attempts per bounded task before and after lesson recall. |
| Fold compression | Does lineage reduce context cost safely? | Raw transcript tokens replaced by fold-summary tokens plus downstream success rate. |
| Promotion precision | Are promoted lessons actually useful? | Fraction of promoted lessons surviving replay or human review. |
| Tool graduation yield | Does repeated reasoning become infrastructure? | Number of procedures converted into tested tools and their reuse rate. |
| Regression after maintenance | Does cleanup damage behavior? | Post-maintenance verifier failures attributable to lost or altered memory. |

The target is not 'does retrieval find similar text?' The target is 'does the system become more reliable while spending less context?' Even modest before/after measurements would sharpen the claim: median retry count, prompt-token load, verifier pass rate on first attempt, fold compression ratio, and promoted-lesson reuse frequency.

## 17. Relationship to Vector Databases

Mycelium does not make vector databases obsolete. That framing is a category error. Vector databases are indexing systems. They can be useful inside a larger memory architecture. The missing abstraction is governance. A vector index does not decide when a memory should become cold, when a trace should become a lesson, when a lesson should become a rule, or when a session should be folded. It does not maintain task state, verifier outcomes, promotion gates, audit trails, or tenant boundaries.

```text
Not: Mycelium vs. vector DB
But: memory governance architecture vs. retrieval-only memory
```

Retrieval-only memory can be one component. It cannot be the whole system.

## 18. Anti-Goals and Limitations

Mycelium is not an autonomous AGI design, unrestricted self-modifying cognition, universal memory shared across all contexts, a mandate to store everything, a replacement for deterministic systems, a replacement for human review, a replacement for vector indexes, a claim that local models are always sufficient, or a way to let weak models rewrite their own trust boundaries.

The architecture should not be oversold. It is not a theory of consciousness, not a complete autonomy framework, and not proven at large scale. The current evidence is best understood as operational case-study evidence: specific systems degraded in specific ways, and the architecture emerged to address those failures. Open questions remain around trace clustering, portable procedural schemas, fold evaluation, tenant isolation, smoke-test design, rollback mechanisms, and promotion criteria for deterministic tooling.

## 19. Conclusion

Mycelium treats memory as infrastructure. Its purpose is to govern how agent experience moves between representations: raw events become traces, traces become patterns, patterns become lessons, lessons become procedures, and procedures may become tools. The architecture is grounded in a simple observation: long-running agent systems degrade when they lack disciplined transitions between context, memory, evidence, and action.

Better retrieval helps, but it does not solve the governance problem. A practical memory system must separate semantic memory from behavioral evidence, use verifiers rather than self-reports as learning signals, fold stale session history into lineage, and keep local inference cheap enough to support continuous maintenance. The result is not magic memory. It is an operating discipline for systems that must remember without drowning in what they remember.

## References

Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N., Küttler, H., Lewis, M., Yih, W., Rocktäschel, T., Riedel, S., & Kiela, D. (2020). Retrieval-augmented generation for knowledge-intensive NLP tasks. Advances in Neural Information Processing Systems.

Packer, C., Wooders, S., Lin, K., Fang, V., Patil, S. G., Stoica, I., & Gonzalez, J. E. (2023). MemGPT: Towards LLMs as operating systems. arXiv:2310.08560.

Park, J. S., O'Brien, J. C., Cai, C. J., Morris, M. R., Liang, P., & Bernstein, M. S. (2023). Generative agents: Interactive simulacra of human behavior. Proceedings of the ACM Symposium on User Interface Software and Technology.

Shinn, N., Cassano, F., Berman, E., Gopinath, A., Narasimhan, K., & Yao, S. (2023). Reflexion: Language agents with verbal reinforcement learning. Advances in Neural Information Processing Systems.
