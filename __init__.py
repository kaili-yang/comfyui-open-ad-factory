from .open_ad_factory import routes  # noqa: F401  registers the /open_ad_factory/ web app
from .open_ad_factory.nodes import OpenAdFactoryExtension

WEB_DIRECTORY = "./web/js"


async def comfy_entrypoint() -> OpenAdFactoryExtension:
    return OpenAdFactoryExtension()
