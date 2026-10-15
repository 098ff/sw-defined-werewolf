# Contribution Guidelines (CONTRIBUTE.md)

Welcome to the **Multiplayer Werewolf (Software-Defined Systems)** project! This document outlines our team development workflow, branch management, coding standards, and how to work alongside AI/Agent tools effectively.

---

## 1. Team Members & Roles

| Member Name | Default Role / Area of Responsibility | Relevant Guide |
|---|---|---|
| **Chanatda Konchom** | Infrastructure, K3s, Flannel CNI, MetalLB, K8s Manifests, Scripts | [01-role-infra-k8s.md](docs/roles/01-role-infra-k8s.md) |
| **Khanapong Kamchoom** | Gateway Reverse Proxy, Trace Aggregator, React Frontend UI & Polling | [02-role-gateway-frontend.md](docs/roles/02-role-gateway-frontend.md) |
| **Thanyaporn Rattanacharoentham** | Lobby Service, Room Management, Session Tokens, Capacity Rules | [03-role-lobby.md](docs/roles/03-role-lobby.md) |
| **Nantaporn Phuaphanbun** | GameMaster Service, Rule Engine, FSM Transitions, PlayerView Sanitizer | [04-role-gamemaster.md](docs/roles/04-role-gamemaster.md) |
| **Chayut Archamongkol** | Chat Service, Shared `StateStore` Layer, Redis CAS, Docker Compose & QA | [05-role-chat-statestore-qa.md](docs/roles/05-role-chat-statestore-qa.md) |

*(Note: Roles can be adapted among team members as agreed upon, but each microservice must have a single dedicated owner).*

---

## 2. Git Branching Strategy

We follow a structured Git feature-branch workflow:

```text
main (Production / Grading ready)
  └── develop (Integration & staging)
        ├── feat/infra-metallb
        ├── feat/gateway-proxy
        ├── feat/lobby-auth
        ├── feat/gm-rules
        └── feat/chat-channels
```

### 2.1 Branch Rules
- **`main`:** Protected branch. Only merged from `develop` after full End-to-End verification and testing on the physical Raspberry Pi cluster.
- **`develop`:** Shared integration branch. All feature branches merge here via Pull Request.
- **`feat/<service-or-topic>`:** Individual feature branches created by members from `develop`.
- **`fix/<bug-description>`:** Bug fix branches.

### 2.2 Branch Naming Conventions
- `feat/gateway-downward-trace`
- `feat/gamemaster-night-resolution`
- `feat/lobby-capacity-check`
- `feat/chat-role-permissions`
- `feat/k8s-anti-affinity`

---

## 3. Commit Message Conventions

We enforce [Conventional Commits](https://www.conventionalcommits.org/) to keep the git log clean and traceable:

```text
<type>(<scope>): <short description>
```

### Types:
- `feat`: A new feature (e.g., `feat(lobby): add player capacity enforcement`)
- `fix`: A bug fix (e.g., `fix(gamemaster): resolve vote tie-breaking edge case`)
- `docs`: Documentation changes (e.g., `docs(readme): update IP allocation table`)
- `test`: Adding or updating tests (e.g., `test(statestore): add redis CAS concurrency test`)
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `infra`: Kubernetes manifests, Dockerfiles, or shell scripts (e.g., `infra(k8s): adjust memory limits to 160MiB`)

---

## 4. Development & Testing Standards

Before opening a Pull Request (PR) to `develop`, ensure your code passes the following standards:

### 4.1 Golden Rules (Do NOT Break)
1. **Never alter API contracts unilaterally:** All API routes, request bodies, and response envelopes must adhere strictly to [contracts/api-contract.md](contracts/api-contract.md). If you must change a field, announce it in the team chat and update the contract first.
2. **Standard Response Envelope:** Every HTTP endpoint must return:
   ```json
   { "ok": true, "data": ..., "request_id": "...", "trace": [...] }
   ```
3. **No WebSockets:** All real-time mechanics must rely strictly on 2-second REST polling.
4. **ARM64 & Memory Ceilings:** Every backend service must build cleanly for `linux/arm64` and stay under **160 MiB** RAM limit.
5. **No Secrets in Repo:** Never commit `.env` files with actual secrets or credentials. Use `.env.example`.

### 4.2 Pre-PR Checklist
- [ ] Code passes isolated unit tests: `pytest tests/unit/`
- [ ] Code conforms to response envelope schemas: `pytest tests/contract/`
- [ ] Service builds cleanly in Docker: `docker build -t test-img services/<service_name>`
- [ ] End-to-End flow verified locally in `docker compose -f docker-compose.dev.yml up`
- [ ] Code reviewed by at least one other team member.

---

## 5. Working with AI / LLM Agents

If you are using AI tools (Gemini, ChatGPT, Claude, Cursor, Antigravity, or GitHub Copilot):

1. **Always reference the central agent guidelines:** Point your AI assistant to:
   - [docs/roles/00-agent-system-prompt.md](docs/roles/00-agent-system-prompt.md)
2. **Attach your specific role guide:** Point your AI assistant to your role guide in `docs/roles/` (e.g. `docs/roles/03-role-lobby.md`).
3. **Use the "Ready-to-Use Agent Prompt"** provided at the bottom of your role document to set clear guardrails and prevent hallucinated architectures.
4. **Never let an AI edit files outside your assigned domain** without consulting the respective service owner.
