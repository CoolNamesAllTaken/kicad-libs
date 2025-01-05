# Running KiBot
Run `source kibot/run_kibot.bash <project_name>` from the `kicad` directory. You can run with the `-j` flag to generate JLCPCB outputs.

# Troubleshooting
## `docker: Error from daemon: ... no space left on device.`
Check system storage use with `docker system df`, then remove unused objects with `docker system prune`.