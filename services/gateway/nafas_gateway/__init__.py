"""The gateway: the doctor dashboard's HTTP edge.

It authenticates, then hands each request to the service that owns the data.
It keeps no state and runs no worker. See docs/PLAN.md §4.
"""
