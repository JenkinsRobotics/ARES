# Docker deployment notes

The compose files in this directory are retained compatibility deployment
surfaces. They are not the primary internal-alpha install path; use the root
installer unless container isolation is specifically required.

## What the multi-container setup isolates

The two- and three-container layouts provide process, network, and resource
isolation. They do **not** provide filesystem isolation: the services still
share explicitly mounted workspace and state volumes. Treat every service
with access to those mounts as part of the same filesystem trust boundary.

## Upgrading the agent container

The `ares-agent-src` named volume caches agent source from the first startup.
Pulling a newer image does not replace that volume, which can produce the
missing-entrypoint symptom tracked in #1416. Recreate it during an upgrade:

```bash
docker compose -f docker-compose.two-container.yml down
docker volume ls
docker volume rm <compose-project>_ares-agent-src
docker compose -f docker-compose.two-container.yml pull
docker compose -f docker-compose.two-container.yml up -d
```

Resolve the exact project-prefixed volume with `docker volume ls` before
removing it. Removing the volume discards its cached agent-source copy.

## Compatibility troubleshooting

Historical reports #1389, #1399, #858, and #681 cover recurring permission,
architecture, state-mount, and container-startup symptoms. Podman 3.4 or
multi-architecture users can evaluate the community `sunnysktsang/ares-suite`
single-container image; it is not an ARES release artifact.

Running `sudo docker compose` can expand `${HOME}` as root and mount
`/root/.ares` instead of the user's state. Prefer Docker's `docker group`, or
preserve the intended environment deliberately with `sudo -E docker compose`.

The WebUI reads external agent source but must not mutate it (#2453). See the complete
source/API boundary inventory in `rfcs/agent-source-boundary.md`.

## Optional GPU runtime image

The default Ares WebUI Docker image stays CPU-only. The compatibility image can
include VA-API libraries with:

```bash
docker build --build-arg INSTALL_GPU_LIBS=1 -t ares-webui:gpu .
```

### Intel and AMD VA-API

Pass the render devices with `--device /dev/dri:/dev/dri`, or in Compose use
`devices: ["/dev/dri:/dev/dri"]` and `group_add:` entries for the host `video`
and `render` groups. `docker_init.bash` preserves Docker-provided supplemental groups
groups. Validate the resulting container with `vainfo`.

### NVIDIA

Install the NVIDIA Container Toolkit and a compatible host NVIDIA driver, then
use `--gpus all` or Compose `gpus: all`. The image does not install host kernel drivers
or the NVIDIA runtime.

These recipes document configuration shapes; this is not a claim that native GPU passthrough was verified.
Success depends on host drivers and container
runtime configuration.

## Gateway approval compatibility

Interactive approval cards require the WebUI service to opt into the gateway runs API:

```text
ARES_WEBUI_CHAT_BACKEND=gateway
ARES_WEBUI_GATEWAY_BASE_URL=http://ares-agent:8642
ARES_WEBUI_GATEWAY_USE_RUNS_API=true
```
