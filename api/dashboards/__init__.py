"""Read-side aggregation for the client dashboards, one module per page.
Pure database reads over processed rows: no LLM, no provider calls.

`api.dashboards_service` re-exports everything here for older imports."""
