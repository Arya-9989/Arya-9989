<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/hero-dark.svg"><img src="assets/hero-light.svg" width="846" alt="Arya Mahindrakar, AI Engineer, LLM Agents, Cloud. I build AI agents and ship them to production, securely. Open to work. AWS Certified Cloud Practitioner. Pune, India."></picture></p>

<p align="center"><a href="mailto:arya.mahindrakar.09@gmail.com"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/cta-email-dark.svg"><img src="assets/cta-email-light.svg" width="123" alt="Email me"></picture></a><a href="https://github.com/Arya-9989?tab=repositories"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/cta-repos-dark.svg"><img src="assets/cta-repos-light.svg" width="190" alt="Browse my repos"></picture></a></p>

## [AutoSWE](https://github.com/Arya-9989/Autonomous-AI-Software-Engineering-Platform)

My flagship public AI project: **a plain-English spec becomes a tested, deployable project** in Python, TypeScript or Go.

- **Agents with guardrails.** Five stages, typed artifacts, file policy checks, sandboxed tests and a bounded repair loop.
- **Quality you can inspect.** [Eval regression gates in CI](https://github.com/Arya-9989/Autonomous-AI-Software-Engineering-Platform/blob/main/.github/workflows/ci.yml), plus a deterministic offline provider for runs without API keys.
- **Usage you can account for.** Per-user token budgets, cost reporting and OpenTelemetry traces across agent stages and model calls.

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/autoswe-pipeline-dark.svg"><img src="assets/autoswe-pipeline-light.svg" width="420" alt="AutoSWE pipeline: Analyst, Architect, Coder, DevOps, Reviewer."></picture></p>

Explore the [architecture](https://github.com/Arya-9989/Autonomous-AI-Software-Engineering-Platform#architecture) and inspect the [tests](https://github.com/Arya-9989/Autonomous-AI-Software-Engineering-Platform/tree/main/tests).

AutoSWE generates infrastructure code; it does not deploy projects to AWS automatically.

## Beyond the flagship

Two private projects deepen the agent work:

- **AI-Agent (private):** a tool-calling loop built from first principles; hybrid RAG with local embeddings and keyword fallback; source-citation and faithfulness checks; context trimming and token/cost tracking.
- **mcp-agent (private):** MCP tool servers; checkpointed LangGraph execution with tool approvals; a manager–worker team; hybrid retrieval and reranking; persistent memory, structured traces and scheduled answer evals.

## How I build AI systems

- **Orchestrate.** Typed agent stages, MCP tools and checkpointed execution with explicit tool approvals.
- **Retrieve.** Hybrid RAG, reranking, source citations and persistent memory with update and deletion.
- **Evaluate.** Regression gates, answer faithfulness checks and offline providers for repeatable tests.
- **Constrain.** Schema-validated tool calls, isolated code execution and bounded agent and repair loops.
- **Account.** Token budgets, cost reports and context trimming; traces connect model and tool calls.
- **Ship.** FastAPI services, persisted jobs, live SSE progress, Docker, CI and Kubernetes manifests.

## Cloud and security behind the agents

These public projects show the backend, deployment and security work I bring to AI systems.

- [SecureCart](https://github.com/Arya-9989/SecureCart-Cloud-Native-Security-Enhanced-eCommerce-Platform): Django REST + React commerce with rotating refresh tokens, signed Stripe webhooks and row-locked checkout tested against concurrent buyers.

- [Secure Cloud Microservices](https://github.com/Arya-9989/secure-cloud-microservices-platform): Django + Java Spring Boot services with JWT/JWKS, OpenTelemetry, signed container images and Kubernetes admission policies.

- [Secure Multi-Tenant Platform](https://github.com/Arya-9989/secure-multi-tenant-platform): Django tenant isolation enforced by ORM scoping and PostgreSQL row-level security, with cross-tenant attack tests and a hash-chained audit log.

- [EcoQuest](https://github.com/Arya-9989/EcoQuest): Django learning platform with teacher-scoped classrooms, replay-safe quiz grading, transaction-protected rewards and a retryable email outbox.

- [Momentum](https://github.com/Arya-9989/Momentum-Live-Stock-Tracker): Typed Streamlit market dashboard with tested indicators, saved watchlists, price alerts and FIFO portfolio accounting.

### Infrastructure Observability & SIEM Platform

Hands-on project experience with Grafana, Wazuh SIEM and Linux:

- Centralized **Grafana monitoring with threshold-based alerting** across virtualized Linux hosts
- **Wazuh SIEM file-integrity and unauthorized-access monitoring**, with real-time anomaly detection

## Education & Certification

**B.Tech, Cloud Technology & Information Security**<br>
Ajeenkya D Y Patil University, Pune · 2022 – 2026<br>
Cloud Computing · Network Security · Information Security · Operating Systems · DBMS · Software Engineering · Data Structures & Algorithms

**AWS Certified Cloud Practitioner**<br>
Amazon Web Services · Apr 2026 – Apr 2029<br>
EC2 · S3 · IAM · VPC networking · security groups · load balancing · cloud deployment best practices

**Location:** Pune, India

## Research

- **Quantum-Resistant Cloud Encryption** — IEEE-style research paper on post-quantum cryptography for cloud data
- **Cooling Solutions for Data Centers** — IEEE-style research paper

<details>
<summary>Stack</summary>

**Agents & retrieval:** Python · FastAPI · MCP · LangGraph · OpenAI-compatible APIs · Ollama · RAG

**Quality & observability:** pytest · Playwright · OpenTelemetry · Prometheus · Grafana · Wazuh SIEM

**Cloud & delivery:** Docker · Kubernetes · Terraform · GitHub Actions · Jenkins

**Backend & data:** Django REST Framework · Spring Boot · PostgreSQL · Redis

**Interfaces:** React · TypeScript · Streamlit

</details>

## Let’s work together

I'm looking for AI engineering roles building agents, MCP integrations and RAG systems, with evals, guardrails and the cloud infrastructure to run them.

[Email me](mailto:arya.mahindrakar.09@gmail.com) · [LinkedIn](https://www.linkedin.com/in/arya-mahindrakar/) · [Browse my repositories](https://github.com/Arya-9989?tab=repositories)
