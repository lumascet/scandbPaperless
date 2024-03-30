# One Button Press to Paperless

just a simple docker container for the Fujitsu SnapScan S1500 (or others if adapted) to scan if the hardware button is pressed. The scan is automatically converted to a pdf and sent to a Paperless consume folder.

A quick & easy method to digitalize, sort and store documents.

Use the docker compose file to spin up your server.

> [!WARNING]
> I was not able get the system to communicate with the scanner as non-root user, so i set the docker container to use the root user. If you know how to properly set the permissions, consider supporting!