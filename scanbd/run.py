import math
import os
from config import *
import time
import subprocess
from homeassistantmqtt import BinarySensor, Button, HomeAssistantDevice, MQTTHandler, Sensor, Image as ImageEntity
import logging
from pdf2image import convert_from_path
from PIL import Image
from io import BytesIO
import threading

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
PDF_PATH = "/home/paperless/last.pdf"

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
        logger.info("Scanner service started.")
        return True
    logger.info("Scanner service already running.")
    return False


def stop_scanbd():
    if is_process_running(PROCESS_NAME):
        subprocess.run(['pkill', PROCESS_NAME])
        logger.info("Scanner service stopped.")
        return True
    logger.info("Scanner service not running.")
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
        logger.info(result.stdout)
        logger.error(result.stderr)
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
    last_pdf_time = 0

    # MQTT broker settings from config
    MQTT_BROKER = mqtt_server_host
    MQTT_PORT = mqtt_server_port
    MQTT_USER = mqtt_username
    MQTT_PASSWORD = mqtt_password
    MQTT_KEEPALIVE = mqtt_keepalive

    # Initialize the device using properties from the top
    device = HomeAssistantDevice(
        device_id=DEVICE_ID,
        name=DEVICE_NAME_FRIENDLY,
        manufacturer=MANUFACTURER,
        model=MODEL,
        sw_version=SW_VERSION,
        configuration_url=CONFIGURATION_URL
    )

    entities = {
        "restart_docker": Button("Restart Docker", icon="mdi:restart", entity_category="diagnostic"),
        "scanner_status": Sensor("Scanner Status", icon="mdi:printer-alert"),
        "scanner_online": BinarySensor("Scanner Online", icon="mdi:printer-check"),
        "scanner_preview": ImageEntity("Scanner Preview", "image/jpeg", icon="mdi:image")
    }

    for entity in entities.values():
        device.add_entity(entity)

    # Create entities without passing the device
    scan_buttons = {
        "color_a4": Button("A4 Color", icon="mdi:palette"),
        "greyscale_a4": Button("A4 Greyscale", icon="mdi:invert-colors-off"),
        "color_autosize": Button("Autosize Color", icon="mdi:image-size-select-large"),
        "greyscale_autosize": Button("Autosize Greyscale", icon="mdi:image-size-select-large"),
        "single_page_a4_color": Button("Single Page A4 Color", icon="mdi:file"),
        "single_page_a4_greyscale": Button("Single Page A4 Greyscale", icon="mdi:file"),
    }

    for button in scan_buttons.values():
        availability = {
            "topic": entities["scanner_online"].get_state_topic(),
            "payload_available": "ON",
            "payload_not_available": "OFF",
            "value_template": "{{ value_json.state }}"
        }
        button.add_availability(availability)
        device.add_entity(button)

    # Initialize MQTT handler and register device
    mqtt_handler = MQTTHandler(
        broker=MQTT_BROKER,
        port=MQTT_PORT,
        username=MQTT_USER,
        password=MQTT_PASSWORD,
        keepalive=MQTT_KEEPALIVE
    )

    mqtt_handler.register_device(device)

    def restart_docker(client=None, userdata=None, message=None):
        logger.info("Restarting Docker")
        nonlocal program_exit
        program_exit = True

    # Register entity callbacks
    mqtt_handler.register_entity_callback(
        entities["restart_docker"],
        restart_docker
    )

    mqtt_handler.connect()
    mqtt_handler.publish_ha_autoconfig(device)
    mqtt_handler.set_device_online(device)

    # Define the scan callback function
    def make_scan_callback(scan_type):
        def callback(client, userdata, message):
            def scan_task():
                nonlocal scanning
                mqtt_handler.publish_entity_state(
                    entities["scanner_status"], f"Scanning {scan_type}...")
                logger.info(
                    f"Received '{message.payload.decode()}' for '{scan_type}'")
                scanning = True
                scan_result = perform_scan(scan_type)
                scanning = False
                logger.info(scan_result)
                mqtt_handler.publish_entity_state(
                    entities["scanner_status"], scan_result)

            # Run the scan task in a separate thread
            threading.Thread(target=scan_task).start()
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
                mqtt_handler.publish_entity_state(
                    entities["scanner_status"], "Ready")

            if not is_device_connected and is_service_running:
                stop_scanbd()
                mqtt_handler.publish_entity_state(
                    entities["scanner_online"], BinarySensor.STATE_OFF)
                mqtt_handler.publish_entity_state(
                    entities["scanner_status"], "Scanner disconnected")

            if not was_device_connected and is_device_connected:
                logger.info(
                    "USB state changed from disconnected to connected, restarting Docker container.")
                restart_docker()

            # if last.pdf changed, convert to image
            if os.path.exists(PDF_PATH) and os.path.getmtime(PDF_PATH) != last_pdf_time:
                logger.info("PDF file changed, converting to image.")
                last_pdf_time = os.path.getmtime(PDF_PATH)
                pages = convert_from_path(PDF_PATH, dpi=200)
                # Calculate grid dimensions to make it as square as possible
                num_pages = len(pages)
                cols = math.ceil(math.sqrt(num_pages))  # Number of columns
                rows = math.ceil(num_pages / cols)      # Number of rows

                # Determine the cell size by finding the maximum width and height of each page
                cell_width = max(page.width for page in pages)
                cell_height = max(page.height for page in pages)

                # Calculate the size of the full grid image
                grid_width = cell_width * cols
                grid_height = cell_height * rows

                # Create a blank canvas for the grid
                combined_image = Image.new(
                    'RGB', (grid_width, grid_height), color=(0, 0, 0))

                # Paste each page into the grid
                for index, page in enumerate(pages):
                    row = index // cols
                    col = index % cols

                    # Resize page to fit within the cell, maintaining aspect ratio
                    page.thumbnail((cell_width, cell_height))

                    # Calculate x and y position to paste the page in the grid
                    x = col * cell_width + (cell_width - page.width) // 2
                    y = row * cell_height + (cell_height - page.height) // 2
                    combined_image.paste(page, (x, y))

                # shrink image uniformly if it's too big
                max_dimension = max(grid_width, grid_height)
                if max_dimension > 2048:
                    combined_image.thumbnail((2048, 2048))

                with BytesIO() as img_buffer:
                    combined_image.save(img_buffer, format="JPEG")
                    img_bytes = img_buffer.getvalue()
                    mqtt_handler.publish_entity_state(
                        entities["scanner_preview"], img_bytes)

                    logger.info("Sent combined image grid to Home Assistant.")

            was_device_connected = is_device_connected
            time.sleep(5)
    except KeyboardInterrupt:
        program_exit = True
    finally:
        # Deregister device and stop MQTT handler
        mqtt_handler.deregister_device(device)
        mqtt_handler.disconnect()
        logger.debug("MQTT client stopped.")
        logger.info("MQTT client stopped.")


if __name__ == "__main__":
    main()
