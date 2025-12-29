"""Local Odoo connection defaults for helper scripts.

This file is intended to hold **developer-local** configuration values such as
Odoo passwords and HTTP basic auth credentials, so they are not hard-coded in
versioned scripts.

Fill in the values below on your own machine and consider adding this file to
.gitignore so that secrets are not pushed to the repository.
"""

# Example (non-production) values – replace with your own as needed.
# It is safe to leave any of these as ``None`` and override via
# command-line arguments.

ODOO_HOST = None  # e.g. "example.com"
ODOO_PORT = None  # e.g. 443
ODOO_DB = None  # e.g. "db_name"

ODOO_LOGIN = None  # e.g. "admin"
ODOO_PASSWORD = None  # password for the Odoo user

ODOO_HTTP_USER = None  # HTTP basic auth username for front proxy
ODOO_HTTP_PASS = None  # HTTP basic auth password for front proxy
