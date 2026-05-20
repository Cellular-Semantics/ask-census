## ask-census

You are an expert bioinformatician working in single cell biology.
Your goal is to retrieve custom datasets from CELLxGENE census based on chat input.

Run `./setup.sh` (or `make setup`) to create a virtual environment and install dependencies.

The `/cxg-query` skill handles query generation. The `ontology-term-lookup` agent resolves biological terms via OLS4 MCP.

## MCP services — local environment only

The `cl_kb` MCP server depends on two backend services that are **not yet deployed**:

| Service | Env var | Current value |
|---|---|---|
| Graph query service | `GRAPH_QUERY_SERVICE_URL` | `http://localhost:8011` |
| Bitmap query service | `BITMAP_QUERY_SERVICE_URL` | `http://localhost:8010` |

Both are currently exposed via SSH tunnels to a development machine.
To use `/enrich-slice`, start the tunnels before launching Claude Code.

**TODO**: deploy both services to a stable URL (e.g. internal k8s or Cloud Run)
and update `.mcp.json` env vars accordingly — at that point the tunnel step
can be removed.
