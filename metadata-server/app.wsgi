
app_path = '/var/context-server/metadata-server'

import sys
sys.path.insert(0, app_path)

activate_this = app_path + '/.venv/bin/activate_this.py'
execfile(activate_this, dict(__file__=activate_this))

from metadata import app as application
