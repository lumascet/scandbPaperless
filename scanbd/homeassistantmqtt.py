import paho.mqtt.client as mqtt
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class HomeAssistantEntity:
    """Base class for Home Assistant entities."""

    def __init__(self, name, component_type, icon=None, entity_category=None):
        self.name = name
        self.component_type = component_type
        self.icon = icon
        self.entity_id = name.replace(" ", "_").lower()
        self.entity_category = entity_category
        self.device = None  # Device will be set when added to a device
        self.availability_objects = []

    def get_status_topic(self):
        return f"{self.device.device_id}/status"

    def get_command_topic(self):
        return f"{self.device.device_id}/control/{self.entity_id}"

    def get_state_topic(self):
        return f"{self.device.device_id}/state/{self.entity_id}"

    def get_state_payload(self, data):
        return json.dumps({"value": data})

    def add_availability(self, availability):
        self.availability_objects.append(availability)

    def get_config(self):
        config = {
            "name": self.name,
            "unique_id": f"{self.device.device_id}_{self.component_type}_{self.entity_id}",
            "object_id": f"{self.device.device_id}_{self.entity_id}",
            "device": {
                "identifiers": [self.device.device_id],
                "name": self.device.name,
                "manufacturer": self.device.manufacturer,
                "model": self.device.model,
                "sw_version": self.device.sw_version,
            },
            "availability": [
                {
                    "topic": self.get_status_topic(),
                    "payload_available": "online",
                    "payload_not_available": "offline",
                }
            ],
            "availability_mode": "all",

        }
        if self.availability_objects:
            config["availability"].extend(self.availability_objects)
        if self.icon:
            config["icon"] = self.icon
        if self.entity_category:
            config["entity_category"] = self.entity_category
        return config


class Button(HomeAssistantEntity):
    """Represents a Button entity."""

    def __init__(self, name, icon=None, entity_category=None):
        super().__init__(name, "button", icon, entity_category)

    def get_config(self):
        config = super().get_config()
        config.update({
            "command_topic": self.get_command_topic(),
            "payload_press": "PRESS",
        })
        return config


class Switch(HomeAssistantEntity):
    """Represents a Switch entity."""

    def __init__(self, name, icon=None, entity_category=None):
        super().__init__(name, "switch", icon, entity_category)

    def get_config(self):
        config = super().get_config()
        config.update({
            "command_topic": self.get_command_topic(),
            "state_topic": self.get_state_topic(),
            "payload_on": "ON",
            "payload_off": "OFF",
            "state_on": "ON",
            "state_off": "OFF",
        })
        return config


class Sensor(HomeAssistantEntity):
    """Represents a Sensor entity."""

    def __init__(self, name, icon=None, entity_category=None):
        super().__init__(name, "sensor", icon, entity_category)

    def get_config(self):
        config = super().get_config()
        config.update({
            "state_topic": self.get_state_topic(),
            "value_template": "{{ value_json.value }}",
        })
        return config


class BinarySensor(HomeAssistantEntity):
    """Represents a Binary Sensor entity."""

    STATE_ON = "ON"
    STATE_OFF = "OFF"

    def __init__(self, name, icon=None, entity_category=None):
        super().__init__(name, "binary_sensor", icon, entity_category)

    def get_state_payload(self, data):
        return json.dumps({"state": data})

    def get_config(self):
        config = super().get_config()
        config.update({
            "state_topic": self.get_state_topic(),
            "payload_on": self.STATE_ON,
            "payload_off": self.STATE_OFF,
            "value_template": "{{ value_json.state }}"
        })
        return config


class Image(HomeAssistantEntity):
    """Represents an Image entity."""

    def __init__(self, name, content_type, icon=None, entity_category=None):
        super().__init__(name, "image", icon, entity_category)
        self.content_type = content_type

    def get_config(self):
        config = super().get_config()
        config.update({
            "image_topic": self.get_state_topic(),
            "content_type": self.content_type,
        })
        return config

    def get_state_payload(self, data):
        """Override to handle binary encoded JPG data."""
        return data


class HomeAssistantDevice:
    """Represents a device in Home Assistant."""

    def __init__(self, device_id, name, manufacturer, model, sw_version, configuration_url=None, ha_prefix="homeassistant"):
        self.device_id = device_id.replace(":", "_").lower()
        self.name = name
        self.manufacturer = manufacturer
        self.model = model
        self.configuration_url = configuration_url
        self.ha_prefix = ha_prefix
        self.sw_version = sw_version
        self.entities = []

    def add_entity(self, entity):
        """Add an entity to the device."""
        entity.device = self  # Associate the entity with this device
        self.entities.append(entity)


class MQTTHandler:
    """Handles MQTT communication."""

    def __init__(self, broker, port=1883, username='', password='', keepalive=60, debug=False):
        self.debug = debug
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if username and password:
            self.client.username_pw_set(username, password)
        self.keepalive = keepalive
        self.broker = broker
        self.port = port
        self.devices = []

    def connect(self):
        try:
            logger.info("Connecting to MQTT broker at %s:%s",
                        self.broker, self.port)
            self.client.connect(self.broker, self.port, self.keepalive)
            self.client.subscribe("+/control/#")
            self.client.loop_start()
            logger.info("MQTT client loop started")
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            raise

    def disconnect(self):
        logger.info("Stopping MQTT client loop")
        self.client.loop_stop()
        self.client.disconnect()
        logger.info("MQTT client disconnected")

    def register_device(self, device):
        """Register the device and its entities with the MQTT handler."""
        logger.info("Registering device %s", device.name)

        lwt_topic = f"{device.device_id}/status"
        lwt_payload = "offline"
        self.client.will_set(lwt_topic, lwt_payload, retain=True)
        self.devices.append(device)

    def deregister_device(self, device):
        logger.info("Deregistering device %s", device.name)
        self.set_device_offline(device)
        self.devices.remove(device)

    def register_callback(self, topic, callback):
        logger.info("Registering callback for topic %s", topic)
        self.client.message_callback_add(topic, callback)
        self.client.subscribe(topic)

    def publish(self, topic, payload, retain=False):
        if self.debug:
            logger.info("Publishing to topic %s: %s", topic, payload)
        else:
            logger.info("Publishing to topic %s", topic)
        self.client.publish(topic, payload, retain=retain)

    def publish_ha_autoconfig(self, device):
        """Publish the configuration for all entities of a device."""
        logger.info("Publishing device configuration for %s", device.name)
        for entity in device.entities:
            config_topic = (
                f"{device.ha_prefix}/{entity.component_type}/"
                f"{device.device_id}/{entity.entity_id}/config"
            )
            config_payload = json.dumps(entity.get_config())
            self.publish(config_topic, config_payload, retain=True)

    def set_device_online(self, device):
        logger.info("Setting device %s online", device.name)
        status_topic = f"{device.device_id}/status"
        self.publish(status_topic, "online", retain=True)

    def set_device_offline(self, device):
        logger.info("Setting device %s offline", device.name)
        status_topic = f"{device.device_id}/status"
        self.publish(status_topic, "offline", retain=True)

    def publish_entity_state(self, entity, data):
        """Publish sensor data without specifying the topic."""
        state_topic = entity.get_state_topic()
        payload = entity.get_state_payload(data)
        self.publish(state_topic, payload)

    def register_entity_callback(self, entity, callback):
        """Register a callback for an entity's command topic."""
        command_topic = entity.get_command_topic()
        self.register_callback(command_topic, callback)
