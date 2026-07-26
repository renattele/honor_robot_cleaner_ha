"""Constants for Honor Robot Cleaner (YuGong / Grit cloud)."""

from __future__ import annotations

DOMAIN = "honor_robot_cleaner"

CONF_TOKEN = "token"
CONF_DEVICE_ID = "device_id"
CONF_REGION = "region"
CONF_BASE_URL = "base_url"
CONF_SUB_TYPE = "sub_type"
CONF_NAME = "name"

DEFAULT_BASE_URL = "https://honour.grit-cloud.com/prod/"
DEFAULT_REGION = "eu-central-1"
DEFAULT_SUB_TYPE = "rob-01"
DEFAULT_NAME = "Honor Robot Cleaner"
DEFAULT_SCAN_INTERVAL = 30

# Cloud working_status -> command payload
CMD_START = "AutoClean"
CMD_PAUSE = "Pause"
CMD_CONTINUE = "ContinueClean"
CMD_STOP = "Standby"
CMD_DOCK = "BackCharging"
CMD_SPOT = "SpotClean"

FAN_QUIET = "Quiet"
FAN_NORMAL = "Normal"
FAN_STRONG = "Strong"
FAN_MAX = "Max"
FAN_NONE = "None"

FAN_SPEEDS = [FAN_QUIET, FAN_NORMAL, FAN_STRONG, FAN_MAX]

ATTR_WORKING_STATUS = "working_status"
ATTR_ERROR_INFO = "error_info"
ATTR_LOCAL_IP = "local_ip"
ATTR_WIFI_SSID = "wifi_ssid"
ATTR_CLEAN_AREA = "clean_area"
ATTR_CLEAN_TIME = "clean_time"
ATTR_FAN_STATUS = "fan_status"
ATTR_WATER_LEVEL = "water_level"
ATTR_FIRMWARE = "firmware"
ATTR_CONNECTED = "connected"
