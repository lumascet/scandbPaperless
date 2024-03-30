#!/bin/bash

# Define the ID of your device
device_id="04c5:11a2"
process_name="scanbd"
first_execution=1

echo "Searching scanner with id $device_id..."
while true; do
    # Check if the device is connected
    if lsusb | grep -q "$device_id"; then

        # Check if the process is not running
        if ! pgrep -x "$process_name" >/dev/null; then
            if [ $first_execution -eq 1 ]; then
                echo "Scanner found."
                /usr/sbin/scanbd -f -d -c /etc/scanbd/scanbd.conf &
                echo "Service started."
                first_execution=0
            else ## workaround for the scanner reconnection, it will not work only if the service is stopped and restarted
                echo "Scanner reconnected, restarting container..."
                while pgrep -x "convert.script" > /dev/null
                do
                    echo "Waiting for convert.script to finish..."
                    sleep 10
                done
                break
            fi
        fi
    else
        # Check if the process is running
        if pgrep -x "$process_name" >/dev/null; then
            echo "Device disconnected."
            echo "Stopping the service..."
            pkill -x "$process_name"
        fi
    fi

    sleep 1
done
