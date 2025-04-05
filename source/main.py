# -*- coding: utf-8 -*-

from resources.lib import kodilogging
from resources.lib import service


# Keep this file to a minimum, as Kodi
# doesn't keep a compiled copy of this
kodilogging.config()
service.run()
