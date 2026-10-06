# Data Pipeline

```mermaid
sequenceDiagram
    participant S as Stats Collector
    participant R as Renderer
    participant P as Protocol
    participant D as ttyACM0
    participant L as LCD Screen
    participant K as Keepalive thread

    P->>D: FF D9 FF D9 (stop current display), wait 200 ms
    P->>D: getDeviceInfo (cmd 6)
    D-->>P: device JSON (320x240, ST7789S)
    P->>D: startLive (cmd 17)

    par Every 0.8s
        K->>D: startLive (cmd 17) keepalive
    and Every refresh_interval (config.yaml, 2s; --interval overrides)
        S->>S: Read CPU (psutil + hwmon, RAPL power)
        S->>S: Read GPU (pynvml)
        S->>S: Read RAM, disk, network, voltages
        S->>R: StatsSnapshot

        R->>R: Apply theme (config.yaml: effece)
        R->>R: Apply layout (config.yaml: grid)
        R->>R: Compose PIL Image (320×240 grid, 320×320 others)
        R->>P: PIL Image

        P->>P: Resize to 320×240, encode as JPEG
        P->>D: Write raw JPEG bytes (no framing)

        D->>L: USB CDC ACM serial
        L->>L: Display frame
    end
```
