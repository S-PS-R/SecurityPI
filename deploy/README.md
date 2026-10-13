# Deployment status

Milestone 1 is a local development foundation. Do not expose the unauthenticated
API or treat it as an operating security camera.

The production plan keeps Pi OS, uses Home Assistant Container and a single media
service, and adds systemd supervision, protected credentials, and private access.
Container/media installation and Pi-specific dependencies will be pinned and
tested at their deployment milestones. The Windows virtual environment must not
be copied to the Pi.
