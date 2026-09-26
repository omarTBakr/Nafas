"""scheduling: when each doctor can be booked, and what is booked.

Owns the `scheduling` schema: booking settings, weekly hours, time off, and
appointments. A slot is checked twice — by the pure rules in
`logic.slots`, then by the database, whose exclusion constraint makes two
overlapping bookings for one doctor impossible however the requests race.
See docs/PLAN.md §2 and §3.
"""
