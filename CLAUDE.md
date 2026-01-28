# This is an AI agent for product classification in customs using HTS (US) and TIGIE (MX)

# Rules
- ALWAYS use source .venv/bin/activate && or uv run for running python scripts
- NEVER USE GIT TO REVERT CHANGES, SO THAT WE DO NOT LOSE LOCAL UNCOMMITED EDITS.
- Always come up with diagnostics, a plan, and ask for approval before executing
- Avoid multiplication of files, whenever possible keep codebase minimal
- Try to make scripts as short, minimalistic and straightforward as possible.
- Database is hosted locally, credentials are in .env and you can use them to inspect it. 
- Do not write summary files, ask user if he wants a summary file.
- All .md files should go in the /docs folder

## Repo Map
```
City-Growth-AI-Agent/
├── src/                      # Core agent code
│   ├── visualization_agent.py      # LangGraph entry point + orchestration
│   ├── visualization_nodes.py      # Agent nodes for intent, SQL, plotting, analysis
│   ├── tools.py                    # SQL execution + CSV handoff tooling
│   ├── workspace.py                # Job workspace lifecycle and paths
│   ├── runner.py                   # Safe code execution with retries
│   ├── validator.py                # Code safety checks for generated scripts
│   ├── models.py                   # Pydantic schemas for structured outputs
│   ├── state.py                    # Agent state definition + reducers
│   ├── prompts.py                  # System prompts for LLM behaviors
│   └── logger.py                   # JSONL run logging
├── ETL/                      # R scripts + raw QCEW CSV
├── database/                 # SQL maintenance scripts + DB notes
├── viz/                      # Saved HTML chart artifacts
├── logs/                     # JSONL run logs
├── evals/                    # Evaluation runner
├── tests/                    # Unit/integration/perf tests
├── docs/old/                 # Design notes and plans
├── references/               # Reference workflows
├── scripts/                  # Utilities (LangSmith trace)
├── old/                      # Legacy code
├── pyproject.toml
└── uv.lock
```
