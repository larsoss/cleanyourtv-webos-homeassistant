"""Constants of the CleanYourTV integration."""

DOMAIN = "cleanyourtv"

CONF_TOKEN = "token"
CONF_MAC = "mac"
CONF_DEVICE_NAME = "device_name"  # the name the TV keeps for this Home Assistant
CONF_LIVE_SOURCES = "live_sources"  # Live TV channels in the media player's source list
CONF_SIDEBAR = "sidebar"  # the remote page in the sidebar (on by default)
# Jellyfin, for the play action: the server, an API key (Dashboard > API keys), whose library is searched, and the app to open on the TV
CONF_JF_URL = "jellyfin_url"
CONF_JF_KEY = "jellyfin_key"
CONF_JF_USER = "jellyfin_user"
CONF_JF_APP = "jellyfin_app"

DEFAULT_DEVICE_NAME = "Home Assistant"
LIVE_PREFIX = "Live: "  # a source that is a Live TV channel: "Live: 12 NPO 1"
LISTS_REFRESH_S = 600
HOME_APP = "com.webos.app.home"

DEFAULT_JF_APP = "org.jellyfin.webos"
PLAY_WAIT_S = 25  # how long the Jellyfin app on the TV gets to sign in after it is opened

MEDIA_TYPE_APP = "app"
MEDIA_TYPE_CHANNEL = "channel"
