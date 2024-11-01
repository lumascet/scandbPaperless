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

    def get_status_topic(self, device_id):
        return f"{device_id}/status"

    def get_command_topic(self, device_id):
        return f"{device_id}/control/{self.entity_id}"

    def get_state_topic(self, device_id):
        return f"{device_id}/state/{self.entity_id}"

    def get_state_payload(self, data):
        return json.dumps({"value": data})

    def get_config(self, device):
        config = {
            "name": self.name,
            "unique_id": f"{device.device_id}_{self.component_type}_{self.entity_id}",
            "object_id": f"{device.device_id}_{self.entity_id}",
            "device": {
                "identifiers": [device.device_id],
                "name": device.name,
                "manufacturer": device.manufacturer,
                "model": device.model,
                "sw_version": device.sw_version,
            },
            "availability": {
                "topic": self.get_status_topic(device.device_id),
                "payload_available": "online",
                "payload_not_available": "offline",
            },
        }
        if self.icon:
            config["icon"] = self.icon
        if self.entity_category:
            config["entity_category"] = self.entity_category
        return config

class Button(HomeAssistantEntity):
    """Represents a Button entity."""

    def __init__(self, name, icon=None, entity_category=None):
        super().__init__(name, "button", icon, entity_category)

    def get_config(self, device):
        config = super().get_config(device)
        config.update({
            "command_topic": self.get_command_topic(device.device_id),
            "payload_press": "PRESS",
        })
        return config


class Switch(HomeAssistantEntity):
    """Represents a Switch entity."""

    def __init__(self, name, icon=None, entity_category=None):
        super().__init__(name, "switch", icon, entity_category)

    def get_config(self, device):
        config = super().get_config(device)
        config.update({
            "command_topic": self.get_command_topic(device.device_id),
            "state_topic": self.get_state_topic(device.device_id),
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

    def get_config(self, device):
        config = super().get_config(device)
        config.update({
            "state_topic": self.get_state_topic(device.device_id),
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

    def get_config(self, device):
        config = super().get_config(device)
        config.update({
            "state_topic": self.get_state_topic(device.device_id),
            "payload_on": self.STATE_ON,
            "payload_off": self.STATE_OFF,
            "value_template": "{{ value_json.state }}"
        })
        return config


class HomeAssistantDevice:
    """Represents a device in Home Assistant."""

    def __init__(self, device_id, name, manufacturer, model, sw_version, configuration_url=None, ha_prefix="homeassistant"):
        self.device_id = device_id.replace(":", "_").lower()
        self.name = name
        self.manufacturer = manufacturer
        self.model = model
        self.configuration_url = configuration_url
        self.ha_prefix = ha_prefix
        self.entities = []
        self.sw_version = sw_version

    def add_entity(self, entity):
        self.entities.append(entity)


class MQTTHandler:
    """Handles MQTT communication."""

    def __init__(self, broker, port=1883, username='', password=''):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if username and password:
            self.client.username_pw_set(username, password)
        self.client.on_message = self._on_message
        self.client.connect(broker, port)
        self.callbacks = {}

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode()
        logger.info("Received message on topic %s: %s", topic, payload)
        if topic in self.callbacks:
            self.callbacks[topic](payload)

    def start(self):
        logger.info("Starting MQTT client loop")
        self.client.loop_start()

    def stop(self):
        logger.info("Stopping MQTT client loop")
        self.client.loop_stop()

    def register_callback(self, topic, callback):
        logger.info("Registering callback for topic %s", topic)
        self.client.subscribe(topic)
        self.callbacks[topic] = callback

    def publish(self, topic, payload, retain=False):
        logger.info("Publishing to topic %s: %s", topic, payload)
        self.client.publish(topic, payload, retain=retain)

    def publish_device_config(self, device):
        """Publish the configuration for all entities of a device."""
        logger.info("Publishing device configuration for %s", device.name)
        for entity in device.entities:
            config_topic = (
                f"{device.ha_prefix}/{entity.component_type}/"
                f"{device.device_id}/{entity.entity_id}/config"
            )
            config_payload = json.dumps(entity.get_config(device))
            self.publish(config_topic, config_payload, retain=True)

    def set_device_online(self, device):
        logger.info("Setting device %s online", device.name)
        status_topic = f"{device.device_id}/status"
        self.publish(status_topic, "online", retain=True)

    def set_device_offline(self, device):
        logger.info("Setting device %s offline", device.name)
        status_topic = f"{device.device_id}/status"
        self.publish(status_topic, "offline", retain=True)

    def publish_entity_state(self, device, entity, data):
        """Publish sensor data to the appropriate state topic."""
        state_topic = entity.get_state_topic(device.device_id)
        payload = entity.get_state_payload(data)
        self.publish(state_topic, payload, retain=False)

    def register_entity_callback(self, device, entity, callback):
        """Register a callback for an entity's command topic."""
        command_topic = entity.get_command_topic(device.device_id)
        self.register_callback(command_topic, callback)