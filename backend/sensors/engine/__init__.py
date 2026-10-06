"""The sensor engine: pure functions over plain data (no database).

days (#11), availability (#12), collection (#14) and replay (#13) take
evidence and return results; reconcile (#15) loads the evidence, runs the
replay and records what changed.
"""
