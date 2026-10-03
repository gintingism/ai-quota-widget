# Provider adapter

Providers implement the small `QuotaProvider.fetch()` boundary and return an
immutable `ProviderSnapshot`. Keep network or subprocess work off the Tk
thread, preserve provider-specific errors, and do not leak credentials.
