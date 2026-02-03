import os
from pathlib import Path

# $STATE_DIRECTORY is set by systemd when StateDirectory is set on the service
STATE_DIRECTORY = Path(os.environ["STATE_DIRECTORY"])

# https://codeberg.org/user/settings/keys
# https://github.com/settings/keys
# https://gitlab.com/-/user_settings/ssh_keys
# https://meta.sr.ht/keys
SSH_KEY = os.environ["SSH_KEY"]

# https://codeberg.org/user/settings/applications
# Permissions:
#  - Repository (read and write)
#  - User (read and write)
CODEBERG_TOKEN = os.environ["CODEBERG_TOKEN"]

# https://github.com/settings/personal-access-tokens
# Repository access:
#  - All repositories
# Permissions:
#  - Administration (read and write)
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]

# https://gitlab.com/-/user_settings/personal_access_tokens
# Scopes:
#  - api
GITLAB_TOKEN = os.environ["GITLAB_TOKEN"]

# https://meta.sr.ht/oauth2
# Access grans:
#  - git.sr.ht PROFILE
#  - git.sr.ht REPOSITORIES
SOURCEHUT_TOKEN = os.environ["SOURCEHUT_TOKEN"]

# Set to `1` to log HTTP requests
HTTPS_DEBUG_LEVEL = int(os.getenv("HTTPS_DEBUG_LEVEL", "0"))
