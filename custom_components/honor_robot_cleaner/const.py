"""Constants for Honor Robot Cleaner (YuGong / Grit cloud)."""

from __future__ import annotations

DOMAIN = "honor_robot_cleaner"

CONF_TOKEN = "token"
CONF_DEVICE_ID = "device_id"
CONF_REGION = "region"
CONF_BASE_URL = "base_url"
CONF_SUB_TYPE = "sub_type"
CONF_NAME = "name"
CONF_ACCOUNT = "account"
CONF_PASSWORD = "password"
CONF_CALLING_CODE = "calling_code"
CONF_LANGUAGE = "language"
CONF_AUTH_MODE = "auth_mode"
CONF_TOKEN_EXPIRES_AT = "token_expires_at"
CONF_SMS_CODE = "sms_code"
CONF_RESEND_SMS = "resend_sms"
CONF_HONOR_SESSION = "honor_session"

AUTH_MODE_PASSWORD = "password"
AUTH_MODE_TOKEN = "token"
AUTH_MODE_HONOR = "honor"

DEFAULT_BASE_URL = "https://honour.grit-cloud.com/prod/"
DEFAULT_BASE_URL_CN = "https://honour.grit-cloud.cn/prod/"
DEFAULT_REGION = "eu-central-1"
DEFAULT_SUB_TYPE = "rob-01"
DEFAULT_NAME = "Honor Robot Cleaner"
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_CALLING_CODE = "007"
DEFAULT_LANGUAGE = "ru"
DEFAULT_APP_VERSION = "1.3.1.8"
APP_NAME = "RobotCleaner"
APP_SECRET = "36d57723-446c-4c1c-b211-62552556139d"
BUNDLE_ID = "com.yx.honor.sweeper"
CLIENT_ID = "yugong_app"

# Refresh this many seconds before JWT expiry
TOKEN_REFRESH_SKEW = 600

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

# Common calling codes for the UI selector
CALLING_CODES = {
    "007": "Russia / Kazakhstan (+7)",
    "00375": "Belarus (+375)",
    "00380": "Ukraine (+380)",
    "0049": "Germany (+49)",
    "0048": "Poland (+48)",
    "001": "US / Canada (+1)",
    "0086": "China (+86)",
    "0090": "Turkey (+90)",
    "0044": "United Kingdom (+44)",
}
