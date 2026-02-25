# 02-development

Architecture and engineering design documents for the Ops Analyst Agent.

## Documentation

- **[Developer Guide](./developer-guide.md)**: Day-to-day local workflow, commands, quality gates, and agent runtime orientation.

- **[Architecture](./architecture.md)**: System mission, architectural principles, integration topology, internal service modules, processing modes, and reliability targets.

- **[Domain and Data Model](./domain-and-data-model.md)**: Core domain entities (transactions, investigations, insights, recommendations, rule drafts), their relationships, and state transitions.

- **[Agent Workflow and Orchestration](./agent-workflow-and-orchestration.md)**: Pipeline orchestration, agent coordination, error handling, and state management.

- **[Storage and Migrations](./storage-and-migrations.md)**: Schema design, migration strategy, indexing guidance, integrity constraints, and SQL injection prevention patterns.

- **[Idempotency and Replay](./idempotency-and-replay.md)**: Idempotency keys, replay protection, duplicate handling, and idempotent operation patterns.

- **[Performance Patterns](./performance-patterns.md)**: Parallel query execution, settings caching, connection pool management, JWKS caching, LLM timeout/retry patterns, and performance best practices.
