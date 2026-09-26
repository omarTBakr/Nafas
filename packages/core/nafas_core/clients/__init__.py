"""Clients for the services' internal APIs, shared by every service that calls them.

One module per service. A refusal the end user can act on (not found,
conflict, invalid) arrives as UpstreamRefusal with the service's own body; any
other failure is a ProviderError.
"""
