"""Constants of the CleanYourTV integration."""

DOMAIN = "cleanyourtv"

CONF_TOKEN = "token"
CONF_CODE = "code"
CONF_MAC = "mac"
CONF_DEVICE_NAME = "device_name"  # the name the TV keeps for this Home Assistant
CONF_LIVE_SOURCES = "live_sources"  # Live TV channels in the media player's source list

DEFAULT_DEVICE_NAME = "Home Assistant"
LIVE_PREFIX = "Live: "  # a source that is a Live TV channel: "Live: 12 NPO 1"
LISTS_REFRESH_S = 600
HOME_APP = "com.webos.app.home"

MEDIA_TYPE_APP = "app"
MEDIA_TYPE_CHANNEL = "channel"
