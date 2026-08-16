# Container onboarding

Inside a container, `localhost` names the container itself. For a provider on
the host, Docker Desktop commonly supports `host.docker.internal`. On Linux,
add an alias such as `api.local` using Compose:

```yaml
extra_hosts:
  - "api.local:host-gateway"
```

Then configure the provider URL with `api.local`, not container `localhost`.
This is compatibility guidance for issue #3012, not a hosted provider service.
