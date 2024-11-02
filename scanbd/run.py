from config import *
import time
import subprocess
from homeassistantmqtt import BinarySensor, Button, HomeAssistantDevice, MQTTHandler, Sensor
import logging

# Constants for the scanner device
DEVICE_USB_ID = "04c5:11a2"
DEVICE_ID = "fujitsu_scanner"
DEVICE_NAME = "fujitsu:ScanSnap S1500:7920"
MANUFACTURER = "Fujitsu"
MODEL = "ScanSnap S1500"
DEVICE_NAME_FRIENDLY = "Fujitsu Scanner"
SW_VERSION = "1.0.0"
CONFIGURATION_URL = "http://192.168.x.x"

PROCESS_NAME = "scanbd"
SCANBD_COMMAND = "/usr/sbin/scanbd -f -d -c /etc/scanbd/scanbd.conf"
SCAN_SCRIPT_PATH = "/etc/scanbd/scripts"
SCAN_SCRIPT = "./scan.script"

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def find_scanner():
    result = subprocess.run(['lsusb'], capture_output=True, text=True)
    return DEVICE_USB_ID in result.stdout


def poll_scanner():
    result = subprocess.run(['scanimage', '-L'],
                            capture_output=True, text=True)
    return DEVICE_NAME in result.stdout


def start_scanbd():
    if not is_process_running(PROCESS_NAME):
        subprocess.Popen(SCANBD_COMMAND.split())
        print("Scanner service started.")
        return True
    print("Scanner service already running.")
    return False


def stop_scanbd():
    if is_process_running(PROCESS_NAME):
        subprocess.run(['pkill', PROCESS_NAME])
        print("Scanner service stopped.")
        return True
    print("Scanner service not running.")
    return False


def is_process_running(process_name):
    try:
        subprocess.check_output(['pgrep', process_name])
        return True
    except subprocess.CalledProcessError:
        return False


def perform_scan(scan_type):
    try:
        stop_scanbd()
        result = subprocess.run(
            [SCAN_SCRIPT, scan_type.replace(' ', '_').lower()],
            capture_output=True,
            text=True,
            cwd=SCAN_SCRIPT_PATH
        )
        print(result.stdout)
        print(result.stderr)
        start_scanbd()
        if result.returncode == 0:
            return "Scan successful"
        elif result.returncode == 1:
            return "Scanner not found"
        elif result.returncode == 2:
            return "Invalid option"
        elif result.returncode == 3:
            return "Invalid argument"
        elif result.returncode == 4:
            return "I/O error"
        elif result.returncode == 5:
            return "Out of memory"
        elif result.returncode == 6:
            return "Scanner jammed"
        elif result.returncode == 7:
            return "Out of documents"
        elif result.returncode == 8:
            return "Scanner cover open"
        else:
            return f"scanimage command failed with exit status {result.returncode}"
    except Exception as e:
        return f"An error occurred: {str(e)}"


def main():
    program_exit = False
    was_device_connected = True
    scanning = False

    # MQTT broker settings from config
    MQTT_BROKER = mqtt_server_host
    MQTT_PORT = mqtt_server_port
    MQTT_USER = mqtt_username
    MQTT_PASSWORD = mqtt_password
    MQTT_KEEPALIVE = 300

    # Initialize the device using properties from the top
    device = HomeAssistantDevice(
        device_id=DEVICE_ID,
        name=DEVICE_NAME_FRIENDLY,
        manufacturer=MANUFACTURER,
        model=MODEL,
        sw_version=SW_VERSION,
        configuration_url=CONFIGURATION_URL
    )

    # Create entities without passing the device
    scan_buttons = {
        "color_a4": Button("A4 Color", icon="mdi:palette"),
        "greyscale_a4": Button("A4 Greyscale", icon="mdi:invert-colors-off"),
        "color_autosize": Button("Autosize Color", icon="mdi:image-size-select-large"),
        "greyscale_autosize": Button("Autosize Greyscale", icon="mdi:image-size-select-large"),
        "single_page_a4_color": Button("Single Page A4 Color", icon="mdi:file"),
        "single_page_a4_greyscale": Button("Single Page A4 Greyscale", icon="mdi:file"),
    }

    entities = {
        "restart_docker": Button("Restart Docker", icon="mdi:restart", entity_category="diagnostic"),
        "scanner_status": Sensor("Scanner Status", icon="mdi:printer-alert"),
        "scanner_online": BinarySensor("Scanner Online", icon="mdi:printer-check"),
    }

    # Add entities to the device
    for button in scan_buttons.values():
        device.add_entity(button)

    for entity in entities.values():
        device.add_entity(entity)

    # Initialize MQTT handler and register device
    mqtt_handler = MQTTHandler(
        broker=MQTT_BROKER,
        port=MQTT_PORT,
        username=MQTT_USER,
        password=MQTT_PASSWORD,
        keepalive=MQTT_KEEPALIVE
    )

    mqtt_handler.register_device(device)
    mqtt_handler.connect()
    mqtt_handler.publish_ha_autoconfig(device)
    mqtt_handler.set_device_online(device)

    def restart_docker(payload):
        print("Restarting Docker")
        nonlocal program_exit
        program_exit = True

    # Register entity callbacks
    mqtt_handler.register_entity_callback(
        entities["restart_docker"],
        restart_docker
    )

    # Define the scan callback function
    def make_scan_callback(scan_type):
        def callback(payload):
            print(f"Received '{payload}' for '{scan_type}'")
            nonlocal scanning
            scanning = True
            scan_result = perform_scan(scan_type)
            scanning = False
            print(scan_result)
            mqtt_handler.publish_entity_state(
                entities["scanner_status"], scan_result)
        return callback

    # Register callbacks for each scan button
    for key, button in scan_buttons.items():
        mqtt_handler.register_entity_callback(
            button,
            make_scan_callback(key)
        )

    # Monitor scanner status
    try:
        while not program_exit:
            is_device_connected = find_scanner()
            is_service_running = is_process_running(PROCESS_NAME)

            if is_device_connected and not is_service_running and not scanning:
                start_scanbd()
                mqtt_handler.publish_entity_state(
                    entities["scanner_online"], BinarySensor.STATE_ON)

            if not is_device_connected and is_service_running:
                stop_scanbd()
                mqtt_handler.publish_entity_state(
                    entities["scanner_online"], BinarySensor.STATE_OFF)

            if not was_device_connected and is_device_connected:
                logger.info(
                    "USB state changed from disconnected to connected, restarting Docker container.")
                restart_docker(None)

            was_device_connected = is_device_connected
            time.sleep(5)
    except KeyboardInterrupt:
        program_exit = True
    finally:
        # Deregister device and stop MQTT handler
        mqtt_handler.deregister_device(device)
        mqtt_handler.disconnect()
        logger.debug("MQTT client stopped.")
        print("MQTT client stopped.")


if __name__ == "__main__":
    main()
