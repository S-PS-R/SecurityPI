# Home Assistant integration plan

Use the existing official iPhone app to present camera video, calibrated parking
status, service health, event details, and eventually arm/disarm controls. The Pi
service performs detection and rule evaluation; the phone is a viewer/controller.

Prefer Home Assistant Container alongside existing Pi OS. This keeps the normal
host environment for the Sense HAT/fan. Container has no Supervisor-managed app
facility; any broker/media services require separate management. Follow
[the official Pi Container documentation](https://www.home-assistant.io/installation/raspberrypi-other/)
when deployment is reached. No Home Assistant installation is performed in this milestone.

## Planned interfaces

| Data or action | Integration route | Behavior to verify |
| --- | --- | --- |
| Service readiness | Domain API or MQTT availability | Offline when frames/inference become stale, not just when process stops |
| Parking per space | Durable entity via supported integration/MQTT discovery | `free`, `occupied`, or `unknown`; freshness and calibration version |
| Door/vehicle activity | Event publication and Home Assistant automation | Cooldown/deduplication; description reports activity, not criminal intent |
| Phone notification | Home Assistant mobile-app notify action | Actual iPhone receipt while locked and on cellular |
| Live video | Camera integration reading shared MediaMTX feed | Safari-compatible codec, private access, Wi-Fi/cellular reachability |
| Arm/disarm | Authenticated command adapter | State acknowledgement and authorization before mutation |

Do not represent a POST to `/api/states` as a complete durable entity integration:
it sets a state but does not establish device control or persistence/discovery.
Choose a supported integration or MQTT discovery for durable parking entities.
Add Mosquitto only when that route is needed, with availability/expiry semantics.

The eventual REST client uses a configured Home Assistant origin and an
environment-held token. Notifications use documented actions, not a custom APNs
server. Retry/expiry and recorded evidence remain in our service. Do not invoke
real notification actions in tests; test adapters against a local mock transport.

References: [REST API](https://developers.home-assistant.io/docs/api/rest/),
[MQTT sensors](https://www.home-assistant.io/integrations/sensor.mqtt/),
[camera integration](https://www.home-assistant.io/integrations/generic/),
[phone notifications](https://companion.home-assistant.io/docs/notifications/notifications-basic/).

The app is not connected in milestone 1. No dashboard configuration is presented
as working before the underlying entities/video exist. A development workstation's
`localhost` is not reachable as `localhost` from a Pi container or iPhone; deployment
will establish a real private service address once access protection exists.
