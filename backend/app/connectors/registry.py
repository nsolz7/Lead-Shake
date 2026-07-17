from app.connectors.base import Connector
from app.connectors.email_verifier import EmailVerificationConnector
from app.connectors.google_places import GooglePlacesIdsConnector
from app.connectors.hunter import HunterConnector
from app.connectors.overture import OvertureConnector
from app.connectors.website import WebsiteConnector
from app.connectors.sam_gov import SamGovConnector
from app.connectors.usaspending import UsaSpendingConnector
from app.connectors.sec_edgar import SecEdgarConnector
from app.connectors.gleif import GleifConnector


CONNECTORS: dict[str, type[Connector]] = {
    "google_places_ids": GooglePlacesIdsConnector,
    "hunter": HunterConnector,
    "overture": OvertureConnector,
    "website": WebsiteConnector,
    "email_verifier": EmailVerificationConnector,
    "sam_gov": SamGovConnector,
    "usaspending": UsaSpendingConnector,
    "sec_edgar": SecEdgarConnector,
    "gleif": GleifConnector,
}


def get_connector(key: str) -> Connector:
    try:
        return CONNECTORS[key]()
    except KeyError as exc:
        raise ValueError(f"No live connector is registered for {key!r}; use the tabular importer") from exc
