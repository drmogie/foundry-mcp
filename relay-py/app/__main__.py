import logging

import uvicorn

from .main import create_app
from .settings import Settings

settings = Settings.from_env()
logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
if not settings.login_configured:
    logging.getLogger("fga-relay").warning(
        "No username and password set. The web page will not let anyone log in until you set them."
    )
uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.port, log_level=settings.log_level.lower())
