#!/usr/bin/env python3
"""Import Saleor product IDs into Odoo from Kencove CSV exports.

This script reads:

* ``KencoveApiProduct.csv``
* ``SaleorProduct.csv``

and uses the following mapping chain:

* ``KencoveApiProduct.id`` == ``product_template.id`` (Odoo)
* ``KencoveApiProduct.productId`` == ``SaleorProduct.productId`` (``pro_...``)
* ``SaleorProduct.id`` is the Saleor product ID to write to
  ``product.template.saleor_product_id``.

It then connects to a single Odoo instance (typically 18.0-unstable) via
``odoorpc`` and, for each matching line, writes ``saleor_product_id`` on the
corresponding ``product.template``.

Use ``--dry-run`` to only log what would be changed without writing.
"""

import argparse
import csv
import logging
import sys
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.request import (
    HTTPBasicAuthHandler,
    HTTPCookieProcessor,
    HTTPPasswordMgrWithDefaultRealm,
    build_opener,
)

import odoorpc
from odoo_config import (
    ODOO_DB,
    ODOO_HOST,
    ODOO_HTTP_PASS,
    ODOO_HTTP_USER,
    ODOO_LOGIN,
    ODOO_PASSWORD,
    ODOO_PORT,
)

_logger = logging.getLogger(__name__)

###############################################################################
# ARGUMENTS
###############################################################################


parser = argparse.ArgumentParser(
    description="Import saleor_product_id into Odoo from Kencove/Saleor CSV files",
)

parser.add_argument(
    "--kencove-api-product-csv",
    type=str,
    default=str(Path(__file__).resolve().parent / "KencoveApiProduct.csv"),
    help="Path to KencoveApiProduct.csv export",
)
parser.add_argument(
    "--saleor-product-csv",
    type=str,
    default=str(Path(__file__).resolve().parent / "SaleorProduct.csv"),
    help="Path to SaleorProduct.csv export",
)

parser.add_argument(
    "--odoo-host",
    type=str,
    default=ODOO_HOST,
    help="Host of target Odoo instance",
)
parser.add_argument(
    "--odoo-port",
    type=int,
    default=ODOO_PORT if ODOO_PORT is not None else 443,
    help="Port of target Odoo instance",
)
parser.add_argument(
    "--odoo-db",
    type=str,
    default=ODOO_DB,
    help="Database name on target Odoo",
)
parser.add_argument(
    "--odoo-login",
    type=str,
    default=ODOO_LOGIN,
    help="Login user on target Odoo",
)
parser.add_argument(
    "--odoo-password",
    type=str,
    default=ODOO_PASSWORD,
    help="Password for target Odoo user",
)
parser.add_argument(
    "--odoo-http-auth-username",
    type=str,
    default=ODOO_HTTP_USER,
    help="HTTP basic auth username for front proxy (if any)",
)
parser.add_argument(
    "--odoo-http-auth-password",
    type=str,
    default=ODOO_HTTP_PASS,
    help="HTTP basic auth password for front proxy (if any)",
)

parser.add_argument(
    "--dry-run",
    action="store_true",
    help=(
        "Do not write anything on Odoo, only print what would be done. "
        "Recommended for first runs."
    ),
)

args = parser.parse_args()


###############################################################################
# HELPERS
###############################################################################


def _connect():
    """Create an ``odoorpc.ODOO`` connection with HTTP basic auth and cookies."""

    host = args.odoo_host
    port = args.odoo_port
    db = args.odoo_db
    username = args.odoo_login
    password = args.odoo_password
    http_user = args.odoo_http_auth_username
    http_pass = args.odoo_http_auth_password

    pwd_mgr = HTTPPasswordMgrWithDefaultRealm()
    if http_user and http_pass:
        pwd_mgr.add_password(
            None,
            f"https://{host}:{port}",
            http_user,
            http_pass,
        )
        auth_handler = HTTPBasicAuthHandler(pwd_mgr)
        opener = build_opener(auth_handler)
    else:
        opener = build_opener()

    cookie_jar = CookieJar()
    opener.add_handler(HTTPCookieProcessor(cookie_jar))

    if port == 443:
        protocol = "jsonrpc+ssl"
    else:
        protocol = "jsonrpc"

    odoo = odoorpc.ODOO(
        host,
        protocol=protocol,
        port=port,
        opener=opener,
        timeout=None,
    )
    odoo.login(db, username, password)
    return odoo


def _read_kencove_api_product_csv(path: Path):
    """Read KencoveApiProduct.csv and return mapping OdooID(int)->productId(str)."""

    mapping = {}
    total = 0
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            raw_id = row.get("id")
            product_id = row.get("productId")
            if not raw_id or not product_id:
                _logger.warning(
                    "[CSV][KencoveApiProduct][SKIP] row missing id or productId: %s",
                    row,
                )
                continue
            try:
                odoo_id = int(raw_id)
            except ValueError:
                _logger.warning(
                    "[CSV][KencoveApiProduct][SKIP] invalid id=%r"
                    " (expected int) in row: %r",
                    raw_id,
                    row,
                )
                continue
            # Last write wins if duplicates for same Odoo ID
            mapping[odoo_id] = product_id
    _logger.info(
        "Loaded %d rows from KencoveApiProduct.csv,"
        " built mapping for %d distinct Odoo IDs",
        total,
        len(mapping),
    )
    return mapping


def _read_saleor_product_csv(path: Path):
    """Read SaleorProduct.csv and return mapping productId->saleor_product_id."""

    mapping = {}
    total = 0
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            product_id = row.get("productId")
            saleor_id = row.get("id")
            if not product_id or not saleor_id:
                _logger.warning(
                    "[CSV][SaleorProduct][SKIP] row missing productId or id: %s",
                    row,
                )
                continue
            mapping[product_id] = saleor_id
    _logger.info(
        "Loaded %d rows from SaleorProduct.csv, built mapping for %d productIds",
        total,
        len(mapping),
    )
    return mapping


###############################################################################
# MAIN
###############################################################################


def main() -> None:
    kencove_path = Path(args.kencove_api_product_csv).expanduser().resolve()
    saleor_path = Path(args.saleor_product_csv).expanduser().resolve()

    _logger.info("Using KencoveApiProduct CSV: %s", kencove_path)
    _logger.info("Using SaleorProduct CSV:    %s", saleor_path)

    if not kencove_path.is_file():
        _logger.error("KencoveApiProduct CSV not found: %s", kencove_path)
        sys.exit(1)
    if not saleor_path.is_file():
        _logger.error("SaleorProduct CSV not found: %s", saleor_path)
        sys.exit(1)

    odoo_from_kencove = _read_kencove_api_product_csv(kencove_path)
    saleor_from_product = _read_saleor_product_csv(saleor_path)

    # Build final mapping: OdooID(int) -> saleor_product_id(str)
    odoo_to_saleor = {}
    missing_in_saleor = 0
    for odoo_id, product_id in odoo_from_kencove.items():
        saleor_id = saleor_from_product.get(product_id)
        if not saleor_id:
            missing_in_saleor += 1
            _logger.warning(
                "[MAPPING][SKIP] Odoo product_template.id=%s has productId=%r"
                " not present in SaleorProduct.csv",
                odoo_id,
                product_id,
            )
            continue
        odoo_to_saleor[odoo_id] = saleor_id

    _logger.info(
        "Built mapping for %d Odoo IDs; %d Odoo IDs had productIds"
        " not found in SaleorProduct.csv",
        len(odoo_to_saleor),
        missing_in_saleor,
    )

    if not odoo_to_saleor:
        _logger.info("No mapping to apply. Exiting.")
        return

    _logger.info("Connecting to Odoo...")
    odoo = _connect()
    Product = odoo.env["product.template"]

    updated = 0
    unchanged = 0
    not_found = 0

    for odoo_id, saleor_id in odoo_to_saleor.items():
        # We browse by ID directly; if record does not exist, browse() returns
        # an empty recordset.
        rec = Product.browse(odoo_id)
        if not rec.exists():  # type: ignore[truthy-function]
            not_found += 1
            _logger.warning(
                "[DEST][SKIP-NOT-FOUND] No product.template with id=%s"
                " on Odoo (expected saleor_product_id=%r)",
                odoo_id,
                saleor_id,
            )
            continue

        current = rec.saleor_product_id
        name = rec.name

        if current == saleor_id:
            unchanged += 1
            _logger.info(
                "[DEST][SKIP-UNCHANGED] product.template id=%s name=%r"
                " already has saleor_product_id=%r",
                odoo_id,
                name,
                current,
            )
            continue

        _logger.info(
            "[DEST][UPDATE] product.template id=%s name=%r: saleor_product_id %r -> %r",
            odoo_id,
            name,
            current,
            saleor_id,
        )
        if args.dry_run:
            _logger.info(
                "[DEST][DRY-RUN] Skipping write on Odoo for product_template id=%s",
                odoo_id,
            )
        else:
            rec.write({"saleor_product_id": saleor_id})
        updated += 1

    _logger.info("=== SUMMARY ===")
    _logger.info(
        "Total Odoo IDs from KencoveApiProduct.csv: %d", len(odoo_from_kencove)
    )
    _logger.info("Total Odoo IDs with Saleor mapping: %d", len(odoo_to_saleor))
    _logger.info(
        "Odoo IDs skipped because productId not in SaleorProduct.csv: %d",
        missing_in_saleor,
    )
    _logger.info(
        "Odoo products updated with new saleor_product_id: %d",
        updated,
    )
    _logger.info(
        "Odoo products unchanged (already had same saleor_product_id): %d",
        unchanged,
    )
    _logger.info(
        "Odoo IDs not found in product.template: %d",
        not_found,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
