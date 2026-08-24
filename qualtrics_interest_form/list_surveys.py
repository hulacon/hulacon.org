"""Sanity check: confirm auth, base URL, and list surveys."""

from qualtrics_client import QualtricsClient


def main() -> None:
    client = QualtricsClient()

    who = client.whoami()
    print(f"Authenticated as: {who.get('firstName', '')} {who.get('lastName', '')} "
          f"({who.get('userName') or who.get('email', '?')})")
    print(f"Brand: {who.get('brandId')}   Datacenter: {who.get('datacenter')}")
    print(f"Base URL in use: {client.base_url}")
    print()

    surveys = client.list_surveys()
    print(f"Found {len(surveys)} survey(s).")
    for s in surveys[:10]:
        print(f"  {s.get('id')}  {s.get('name')!r}  active={s.get('isActive')}  modified={s.get('lastModified')}")
    if len(surveys) > 10:
        print(f"  ... and {len(surveys) - 10} more")


if __name__ == "__main__":
    main()
