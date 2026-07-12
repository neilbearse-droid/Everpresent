"""RQ job functions. M0 ships only a liveness job; Mode A run jobs arrive
with M2 and must go through engine/ code paths, never call SDKs directly."""


def ping() -> str:
    return "pong"
