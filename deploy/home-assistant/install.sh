#!/usr/bin/env bash
# Run through sudo after reviewing. No credentials, camera ownership or phone pushes.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo 'Run this installer with sudo in your Pi terminal.' >&2
  exit 1
fi
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
config_dir="$repo/data/home-assistant"
unit="$repo/data/home-assistant-setup/securitypi-api.service"
image='ghcr.io/home-assistant/home-assistant@sha256:1edf9ce6c140826cdfcd6358802cf3466e38045cd7ed62ccf42c78980ff937ae'
# Config digest from that exact official manifest; also supports a verified offline import.
image_id='sha256:e993d746d4b722f844d8791caa28c4bce66507c87dcc11b4d3fa13e61c05ade0'
container='securitypi-homeassistant'

if [[ $(uname -m) != aarch64 ]]; then
  echo 'This pinned image was prepared for the ARM64 Pi.' >&2
  exit 1
fi
for required in "$config_dir/configuration.yaml" "$config_dir/securitypi-dashboard.yaml" "$unit"; do
  if [[ ! -f "$required" ]]; then
    echo "Missing prepared setup file: $required" >&2
    exit 1
  fi
done
if [[ -e /etc/systemd/system/securitypi-api.service ]] &&
   ! cmp -s "$unit" /etc/systemd/system/securitypi-api.service; then
  echo 'An existing SecurityPI API unit differs; refusing to replace it.' >&2
  exit 1
fi

if ! command -v docker >/dev/null; then
  apt-get update
  # Debian splits the CLI into a separate recommended package; request it explicitly.
  apt-get install -y --no-install-recommends docker.io docker-cli
fi
systemctl start docker
if [[ $(docker info --format '{{.MemoryLimit}} {{.SwapLimit}}') != 'true true' ]]; then
  echo 'Docker cannot enforce RAM/swap limits; stopping before container startup.' >&2
  echo 'On this Pi, enable cgroup_enable=memory in the boot command line and reboot.' >&2
  exit 1
fi
if docker container inspect "$container" >/dev/null 2>&1; then
  if [[ $(docker inspect --format '{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}}' "$container") != '671088640 805306368' ]]; then
    echo "Container $container exists without the expected RAM/swap limits; correct its limits before starting it." >&2
    exit 1
  fi
  echo "Container $container already exists; leaving it unchanged."
  exit 0
fi

# Approximately 609 MiB compressed when prepared; digest prevents moving-tag updates.
if docker image inspect "$image_id" >/dev/null 2>&1; then
  image="$image_id"
else
  docker pull "$image"
fi
docker run --rm --network=host --memory=640m --memory-swap=768m --cpus=1 \
  --pids-limit=256 --env DISABLE_JEMALLOC=true --env TZ=America/New_York \
  --volume "$config_dir:/config" --entrypoint python "$image" \
  -m homeassistant --script check_config --config /config

install -m 0644 "$unit" /etc/systemd/system/securitypi-api.service
systemctl daemon-reload
systemctl start securitypi-api.service

# No privileged mode, device access, Docker socket mount, or Bluetooth dependency.
# Trial startup only: enable restart-on-boot after measuring the combined workload.
docker run --detach --name "$container" --network=host --restart=no \
  --memory=640m --memory-swap=768m --cpus=1 --pids-limit=256 \
  --stop-timeout=60 --log-driver=json-file --log-opt max-size=5m --log-opt max-file=2 \
  --security-opt=no-new-privileges:true \
  --env DISABLE_JEMALLOC=true --env TZ=America/New_York \
  --volume "$config_dir:/config" "$image"

echo 'Home Assistant is starting. Allow a few minutes, then open http://<Pi-address>:8123.'
echo 'Keep your new account password in the browser; do not paste it into chat.'
echo 'Camera analysis and real phone notifications have not been started by this installer.'
echo 'Return to the SecurityPI chat for startup verification and combined resource measurement.'
