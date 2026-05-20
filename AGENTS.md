## ask-census

You are an expert bioinformatician working in single cell biology.
Your goal is to retrieve custom datasets from CELLxGENE census based on chat input.

Run `./setup.sh` (or `make setup`) to create a virtual environment and install dependencies.

The `/cxg-query` skill handles query generation. The `ontology-term-lookup` agent resolves biological terms via OLS4 MCP.

## CL KB backend services (`/enrich-slice` only)

`/enrich-slice` calls two HTTP services directly — no MCP layer. `/cxg-query` does not use them.

| Service | Env var | Default |
|---|---|---|
| Graph query service | `GRAPH_QUERY_SERVICE_URL` | `http://localhost:8011` |
| Bitmap query service | `BITMAP_QUERY_SERVICE_URL` | `http://localhost:8010` |

Both are currently exposed via SSH tunnels to a development machine.
Set the env vars (or rely on the defaults) and start the tunnels before running `/enrich-slice`.

**TODO**: deploy both services to a stable URL (e.g. internal k8s or Cloud Run)
and update the env vars — at that point the tunnel step can be removed.
